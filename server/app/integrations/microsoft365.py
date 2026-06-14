"""Server-side Microsoft 365 auto-stamper.

Uses a Microsoft Entra (Azure AD) app registration with application permissions
(admin-consented once) to scan OneDrive/SharePoint via Microsoft Graph, classify
each Word document against the tenant's rules, and stamp the classification into
its footer — automatically, no user action. Mirrors the Google Drive integration.

Word .docx files are stamped by downloading, editing the footer with python-docx,
and uploading back through Graph.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from ..classification import classify_text

GRAPH = "https://graph.microsoft.com/v1.0"
MAX_DOCS_PER_SCAN = 200


def _http(url: str, method: str = "GET", token: str | None = None,
          data: bytes | None = None, headers: dict | None = None, raw: bool = False):
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=45) as resp:
        body = resp.read()
        if raw:
            return body
        return json.loads(body) if body else {}


def get_token(azure_tenant: str, client_id: str, client_secret: str) -> str:
    """App-only (client credentials) token for Microsoft Graph."""
    url = f"https://login.microsoftonline.com/{azure_tenant}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    resp = _http(url, "POST", data=data,
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return resp["access_token"]


def list_word_docs(token: str, drive_user: str) -> list[dict]:
    """Lists .docx files in the target user's OneDrive (newest first)."""
    url = (f"{GRAPH}/users/{urllib.parse.quote(drive_user)}/drive/root/search(q='.docx')"
           f"?$top={MAX_DOCS_PER_SCAN}&$select=id,name,file")
    items = _http(url, token=token).get("value", [])
    return [i for i in items if i.get("name", "").lower().endswith(".docx")]


def download(token: str, drive_user: str, item_id: str) -> bytes:
    url = f"{GRAPH}/users/{urllib.parse.quote(drive_user)}/drive/items/{item_id}/content"
    return _http(url, token=token, raw=True)


def upload(token: str, drive_user: str, item_id: str, content: bytes) -> None:
    url = f"{GRAPH}/users/{urllib.parse.quote(drive_user)}/drive/items/{item_id}/content"
    _http(url, "PUT", token=token, data=content,
          headers={"Content-Type": "application/octet-stream"})


def stamp_docx_bytes(data: bytes, text: str, color_hex: str, placement: str) -> bytes:
    """Stamps a .docx (in memory) into its header or footer, returns new bytes."""
    from docx import Document
    from docx.shared import Pt, RGBColor

    h = color_hex.lstrip("#")
    rgb = RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    doc = Document(io.BytesIO(data))
    for section in doc.sections:
        container = section.header if placement == "header" else section.footer
        container.is_linked_to_previous = False
        para = container.paragraphs[0] if container.paragraphs else container.add_paragraph()
        if para.text.strip().startswith("CLASSIFICATION"):
            para.clear()
        run = para.add_run(text)
        run.font.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = rgb
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def doc_text(data: bytes) -> str:
    """Extracts plain text from a .docx for classification."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)[:65536]
    except Exception:
        return ""


def scan_tenant(db: Session, cfg: models.MicrosoftConfig) -> dict:
    if not (cfg.azure_tenant_id and cfg.client_id and cfg.client_secret and cfg.drive_user):
        return _finish(db, cfg, "error: set Azure tenant id, client id/secret and a drive user")
    try:
        token = get_token(cfg.azure_tenant_id, cfg.client_id, cfg.client_secret)
    except Exception as e:
        return _finish(db, cfg, f"error: auth failed ({str(e)[:120]})")

    pol = db.query(models.StampPolicy).filter(models.StampPolicy.tenant_id == cfg.tenant_id).first()
    template = pol.text_template if pol else "CLASSIFICATION: {label}"
    placement = cfg.placement or "footer"
    done = {s.file_id for s in db.query(models.StampedDoc.file_id)
            .filter(models.StampedDoc.tenant_id == cfg.tenant_id,
                    models.StampedDoc.provider == "microsoft").all()}

    try:
        docs = list_word_docs(token, cfg.drive_user)
    except Exception as e:
        return _finish(db, cfg, f"error: listing OneDrive failed ({str(e)[:120]})")

    scanned = stamped = 0
    for f in docs:
        if f["id"] in done:
            continue
        scanned += 1
        try:
            data = download(token, cfg.drive_user, f["id"])
        except Exception:
            continue
        text = doc_text(data)
        label, _ = classify_text(db, cfg.tenant_id, f.get("name", ""), text)
        if not label:
            continue
        try:
            new = stamp_docx_bytes(data, template.replace("{label}", label.name), label.color, placement)
            upload(token, cfg.drive_user, f["id"], new)
            db.add(models.StampedDoc(tenant_id=cfg.tenant_id, provider="microsoft",
                                     file_id=f["id"], label=label.name))
            stamped += 1
        except Exception:
            continue
    db.commit()
    return _finish(db, cfg, f"ok: scanned {scanned} new docs, stamped {stamped}")


def _finish(db: Session, cfg: models.MicrosoftConfig, status: str) -> dict:
    cfg.last_scan = datetime.now(timezone.utc)
    cfg.last_status = status[:255]
    db.commit()
    return {"status": status}
