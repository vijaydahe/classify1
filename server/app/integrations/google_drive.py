"""Server-side Google Workspace auto-stamper.

Uses a Google service account with domain-wide delegation (authorized once by
the Workspace admin) to scan Drive, classify each Google Doc against the
tenant's rules, and stamp the classification into the document — automatically,
with no user action. This is the only way to enforce stamping without relying on
each user, because add-ons only run when a user opens them.

Standard-library HTTP + python-jose for the service-account JWT, so no extra
runtime dependencies.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from jose import jwt
from sqlalchemy.orm import Session

from .. import models
from ..classification import classify_text

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DOCS_BATCH = "https://docs.googleapis.com/v1/documents/{}:batchUpdate"
SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/documents"
DOC_MIME = "application/vnd.google-apps.document"
MAX_DOCS_PER_SCAN = 200


def _http(url: str, method: str = "GET", token: str | None = None,
          data: bytes | None = None, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def get_access_token(sa: dict, subject: str) -> str:
    """Exchanges a service-account JWT (impersonating `subject`) for an OAuth token."""
    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "sub": subject,
        "scope": SCOPES,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(claims, sa["private_key"], algorithm="RS256",
                           headers={"kid": sa.get("private_key_id")})
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    resp = _http(TOKEN_URL, "POST", data=data,
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return resp["access_token"]


def list_docs(token: str) -> list[dict]:
    """Lists Google Docs the service account can see, newest first."""
    q = urllib.parse.quote(f"mimeType='{DOC_MIME}' and trashed=false")
    url = (f"{DRIVE_FILES}?q={q}&orderBy=modifiedTime desc"
           f"&pageSize={MAX_DOCS_PER_SCAN}&fields=files(id,name,modifiedTime)")
    return _http(url, token=token).get("files", [])


def export_text(token: str, file_id: str) -> str:
    url = f"{DRIVE_FILES}/{file_id}/export?mimeType=text/plain"
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()[:65536].decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return ""


def _color(hexstr: str) -> dict:
    h = hexstr.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return {"color": {"rgbColor": {"red": r, "green": g, "blue": b}}}


def stamp_doc(token: str, file_id: str, text: str, color_hex: str) -> None:
    """Inserts a bold, coloured classification line at the very top of the doc body."""
    line = text + "\n"
    requests_body = {
        "requests": [
            {"insertText": {"location": {"index": 1}, "text": line}},
            {"updateTextStyle": {
                "range": {"startIndex": 1, "endIndex": 1 + len(line)},
                "textStyle": {"bold": True, "foregroundColor": _color(color_hex)},
                "fields": "bold,foregroundColor",
            }},
        ]
    }
    _http(DOCS_BATCH.format(file_id), "POST", token=token,
          data=json.dumps(requests_body).encode(),
          headers={"Content-Type": "application/json"})


def already_stamped(text: str) -> bool:
    return text.lstrip().startswith("CLASSIFICATION:") or "[CLASSIFICATION]" in text[:200]


def scan_tenant(db: Session, cfg: models.GoogleWorkspaceConfig) -> dict:
    """One scan pass for a tenant: classify + stamp new Google Docs. Returns a summary."""
    try:
        sa = json.loads(cfg.service_account_json)
    except (ValueError, TypeError):
        return _finish(db, cfg, "error: service account JSON is invalid")
    if not cfg.impersonate_subject:
        return _finish(db, cfg, "error: set an admin user to impersonate")

    try:
        token = get_access_token(sa, cfg.impersonate_subject)
    except Exception as e:  # auth/delegation problems surface here
        return _finish(db, cfg, f"error: auth failed ({str(e)[:120]})")

    pol = db.query(models.StampPolicy).filter(models.StampPolicy.tenant_id == cfg.tenant_id).first()
    template = pol.text_template if pol else "CLASSIFICATION: {label}"
    done = {s.file_id for s in db.query(models.StampedDoc.file_id)
            .filter(models.StampedDoc.tenant_id == cfg.tenant_id,
                    models.StampedDoc.provider == "google").all()}

    stamped = 0
    scanned = 0
    try:
        docs = list_docs(token)
    except Exception as e:
        return _finish(db, cfg, f"error: listing Drive failed ({str(e)[:120]})")

    for f in docs:
        if f["id"] in done:
            continue
        scanned += 1
        text = export_text(token, f["id"])
        if already_stamped(text):
            db.add(models.StampedDoc(tenant_id=cfg.tenant_id, file_id=f["id"], label="(pre-stamped)"))
            continue
        label, _ = classify_text(db, cfg.tenant_id, f.get("name", ""), text)
        if not label:
            continue
        stamp_line = template.replace("{label}", label.name)
        try:
            stamp_doc(token, f["id"], stamp_line, label.color)
            db.add(models.StampedDoc(tenant_id=cfg.tenant_id, file_id=f["id"], label=label.name))
            stamped += 1
        except Exception:
            continue  # skip a doc we can't write; try again next scan
    db.commit()
    return _finish(db, cfg, f"ok: scanned {scanned} new docs, stamped {stamped}")


def _finish(db: Session, cfg: models.GoogleWorkspaceConfig, status: str) -> dict:
    cfg.last_scan = datetime.now(timezone.utc)
    cfg.last_status = status[:255]
    db.commit()
    return {"status": status}
