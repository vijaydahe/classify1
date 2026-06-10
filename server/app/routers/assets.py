import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..classification import classify_text
from ..database import get_db
from ..deps import require_tenant_user
from ..models import Asset, AuditLog, Subscription, User
from ..schemas import AssetClassifyRequest, AssetOut

router = APIRouter(prefix="/api/assets", tags=["assets"])

EXCERPT_LEN = 300


def check_asset_quota(db: Session, tenant_id: int, adding: int = 1):
    sub = db.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()
    if not sub:
        return
    count = db.query(Asset).filter(Asset.tenant_id == tenant_id).count()
    if count + adding > sub.plan.max_assets:
        raise HTTPException(402, f"Asset limit reached for the {sub.plan.name} plan. Upgrade to continue.")


@router.get("", response_model=list[AssetOut])
def list_assets(
    q: str = "", source: str = "", label_id: int | None = None,
    user: User = Depends(require_tenant_user), db: Session = Depends(get_db),
):
    query = db.query(Asset).filter(Asset.tenant_id == user.tenant_id)
    if q:
        query = query.filter(Asset.name.ilike(f"%{q}%"))
    if source:
        query = query.filter(Asset.source == source)
    if label_id:
        query = query.filter(Asset.label_id == label_id)
    return query.order_by(Asset.classified_at.desc()).limit(500).all()


@router.post("/classify", response_model=AssetOut)
def classify_asset(
    payload: AssetClassifyRequest,
    user: User = Depends(require_tenant_user), db: Session = Depends(get_db),
):
    check_asset_quota(db, user.tenant_id)
    label, matched = classify_text(db, user.tenant_id, payload.name, payload.content)
    asset = Asset(
        tenant_id=user.tenant_id,
        name=payload.name,
        asset_type=payload.asset_type,
        content_excerpt=payload.content[:EXCERPT_LEN],
        label_id=label.id if label else None,
        matched_rules=", ".join(matched),
        source="manual",
    )
    db.add(asset)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="asset.classified",
                    detail=f"'{payload.name}' -> {label.name if label else 'unlabeled'}"))
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/bulk-csv")
async def bulk_classify_csv(
    file: UploadFile,
    user: User = Depends(require_tenant_user), db: Session = Depends(get_db),
):
    """CSV columns: name, asset_type (optional), content (optional)."""
    raw = (await file.read()).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(400, "CSV must include a 'name' column")
    rows = [{(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader]
    check_asset_quota(db, user.tenant_id, adding=len(rows))

    created = 0
    for row in rows:
        name = row.get("name", "").strip()
        if not name:
            continue
        content = row.get("content", "")
        label, matched = classify_text(db, user.tenant_id, name, content)
        db.add(Asset(
            tenant_id=user.tenant_id, name=name,
            asset_type=row.get("asset_type", "document") or "document",
            content_excerpt=content[:EXCERPT_LEN],
            label_id=label.id if label else None,
            matched_rules=", ".join(matched), source="csv",
        ))
        created += 1
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="asset.bulk_csv",
                    detail=f"{created} assets classified from {file.filename}"))
    db.commit()
    return {"created": created}


@router.get("/export")
def export_csv(user: User = Depends(require_tenant_user), db: Session = Depends(get_db)):
    assets = (
        db.query(Asset).filter(Asset.tenant_id == user.tenant_id)
        .order_by(Asset.classified_at.desc()).all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "asset_type", "classification", "matched_rules", "source", "classified_at"])
    for a in assets:
        writer.writerow([a.name, a.asset_type, a.label.name if a.label else "",
                         a.matched_rules, a.source, a.classified_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=assets.csv"})


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, user: User = Depends(require_tenant_user), db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == user.tenant_id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    db.delete(asset)
    db.commit()
    return {"ok": True}
