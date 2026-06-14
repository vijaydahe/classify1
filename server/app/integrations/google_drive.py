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
SHEETS_GET = "https://sheets.googleapis.com/v4/spreadsheets/{}?fields=sheets.properties(sheetId)"
SHEETS_BATCH = "https://sheets.googleapis.com/v4/spreadsheets/{}:batchUpdate"
SLIDES_GET = "https://slides.googleapis.com/v1/presentations/{}?fields=slides.objectId,pageSize"
SLIDES_BATCH = "https://slides.googleapis.com/v1/presentations/{}:batchUpdate"
SCOPES = ("https://www.googleapis.com/auth/drive "
          "https://www.googleapis.com/auth/documents "
          "https://www.googleapis.com/auth/spreadsheets "
          "https://www.googleapis.com/auth/presentations")
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDE_MIME = "application/vnd.google-apps.presentation"
EXPORT_MIME = {DOC_MIME: "text/plain", SHEET_MIME: "text/csv", SLIDE_MIME: "text/plain"}
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
    """Lists Google Docs, Sheets and Slides the service account can see."""
    mimes = " or ".join(f"mimeType='{m}'" for m in (DOC_MIME, SHEET_MIME, SLIDE_MIME))
    q = urllib.parse.quote(f"({mimes}) and trashed=false")
    url = (f"{DRIVE_FILES}?q={q}&orderBy=modifiedTime desc"
           f"&pageSize={MAX_DOCS_PER_SCAN}&fields=files(id,name,mimeType)")
    return _http(url, token=token).get("files", [])


def export_text(token: str, file_id: str, mime: str) -> str:
    export_as = EXPORT_MIME.get(mime, "text/plain")
    url = f"{DRIVE_FILES}/{file_id}/export?mimeType={urllib.parse.quote(export_as)}"
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


def _post(url: str, token: str, body: dict) -> dict:
    return _http(url, "POST", token=token, data=json.dumps(body).encode(),
                 headers={"Content-Type": "application/json"})


def stamp_doc(token: str, file_id: str, text: str, color_hex: str) -> None:
    """Inserts a bold, coloured classification line at the top of a Google Doc body."""
    line = text + "\n"
    _post(DOCS_BATCH.format(file_id), token, {"requests": [
        {"insertText": {"location": {"index": 1}, "text": line}},
        {"updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 1 + len(line)},
            "textStyle": {"bold": True, "foregroundColor": _color(color_hex)},
            "fields": "bold,foregroundColor",
        }},
    ]})


def stamp_sheet(token: str, file_id: str, text: str, color_hex: str) -> None:
    """Inserts a bold, coloured banner row at the top of the first sheet."""
    sheets = _http(SHEETS_GET.format(file_id), token=token).get("sheets", [])
    sheet_id = sheets[0]["properties"]["sheetId"] if sheets else 0
    c = _color(color_hex)["color"]["rgbColor"]
    _post(SHEETS_BATCH.format(file_id), token, {"requests": [
        {"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS",
                                       "startIndex": 0, "endIndex": 1}, "inheritFromBefore": False}},
        {"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
            "rows": [{"values": [{"userEnteredValue": {"stringValue": text},
                                  "userEnteredFormat": {"textFormat": {"bold": True, "foregroundColor": c}}}]}],
            "fields": "userEnteredValue,userEnteredFormat.textFormat",
        }},
    ]})


def stamp_slides(token: str, file_id: str, text: str, color_hex: str) -> None:
    """Adds a banner text box to the bottom of every slide."""
    pres = _http(SLIDES_GET.format(file_id), token=token)
    slides = pres.get("slides", [])
    h = pres.get("pageSize", {}).get("height", {}).get("magnitude", 5143500)
    w = pres.get("pageSize", {}).get("width", {}).get("magnitude", 9144000)
    c = _color(color_hex)["color"]["rgbColor"]
    reqs = []
    for i, sl in enumerate(slides):
        box_id = f"chstamp_{i}"
        reqs.append({"createShape": {"objectId": box_id, "shapeType": "TEXT_BOX",
            "elementProperties": {"pageObjectId": sl["objectId"],
                "size": {"width": {"magnitude": w - 240000, "unit": "EMU"},
                         "height": {"magnitude": 300000, "unit": "EMU"}},
                "transform": {"scaleX": 1, "scaleY": 1, "translateX": 120000,
                              "translateY": h - 360000, "unit": "EMU"}}}})
        reqs.append({"insertText": {"objectId": box_id, "text": text}})
        reqs.append({"updateTextStyle": {"objectId": box_id, "style": {"bold": True,
            "foregroundColor": {"opaqueColor": {"rgbColor": c}}},
            "fields": "bold,foregroundColor", "textRange": {"type": "ALL"}}})
    if reqs:
        _post(SLIDES_BATCH.format(file_id), token, {"requests": reqs})


def stamp_file(token: str, f: dict, text: str, color_hex: str) -> None:
    mime = f.get("mimeType")
    if mime == DOC_MIME:
        stamp_doc(token, f["id"], text, color_hex)
    elif mime == SHEET_MIME:
        stamp_sheet(token, f["id"], text, color_hex)
    elif mime == SLIDE_MIME:
        stamp_slides(token, f["id"], text, color_hex)


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
        text = export_text(token, f["id"], f.get("mimeType", DOC_MIME))
        if already_stamped(text):
            db.add(models.StampedDoc(tenant_id=cfg.tenant_id, file_id=f["id"], label="(pre-stamped)"))
            continue
        label, _ = classify_text(db, cfg.tenant_id, f.get("name", ""), text)
        if not label:
            continue
        stamp_line = template.replace("{label}", label.name)
        try:
            stamp_file(token, f, stamp_line, label.color)
            db.add(models.StampedDoc(tenant_id=cfg.tenant_id, file_id=f["id"], label=label.name))
            stamped += 1
        except Exception:
            continue  # skip a file we can't write; try again next scan
    db.commit()
    return _finish(db, cfg, f"ok: scanned {scanned} new files (Docs/Sheets/Slides), stamped {stamped}")


def _finish(db: Session, cfg: models.GoogleWorkspaceConfig, status: str) -> dict:
    cfg.last_scan = datetime.now(timezone.utc)
    cfg.last_status = status[:255]
    db.commit()
    return {"status": status}
