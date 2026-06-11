"""Public integration API (v1).

Authenticated with a tenant-created API key via the X-API-Key header.
Available only to tenants on an active paid plan — enforced in get_api_key.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..classification import classify_text, export_rules
from ..database import get_db
from ..deps import get_api_key
from ..models import ApiKey, Asset, ClassificationLabel
from ..routers.assets import EXCERPT_LEN, check_asset_quota
from ..schemas import AssetClassifyRequest, AssetOut, LabelOut

router = APIRouter(prefix="/api/v1", tags=["public-api"])


@router.post("/classify", response_model=AssetOut)
def classify(payload: AssetClassifyRequest,
             key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    """Classifies one asset and stores it in the tenant inventory (source: api)."""
    check_asset_quota(db, key.tenant_id)
    label, matched = classify_text(db, key.tenant_id, payload.name, payload.content)
    asset = Asset(
        tenant_id=key.tenant_id, name=payload.name, asset_type=payload.asset_type,
        content_excerpt=payload.content[:EXCERPT_LEN],
        label_id=label.id if label else None,
        matched_rules=", ".join(matched), source="api",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/assets", response_model=list[AssetOut])
def list_assets(q: str = "", source: str = "", limit: int = 100,
                key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    """Lists classified assets, newest first. Filters: q (name contains), source."""
    query = db.query(Asset).filter(Asset.tenant_id == key.tenant_id)
    if q:
        query = query.filter(Asset.name.ilike(f"%{q}%"))
    if source:
        query = query.filter(Asset.source == source)
    return query.order_by(Asset.classified_at.desc()).limit(min(max(limit, 1), 500)).all()


@router.get("/labels", response_model=list[LabelOut])
def list_labels(key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    """Lists the tenant's classification labels, lowest sensitivity first."""
    return (db.query(ClassificationLabel)
            .filter(ClassificationLabel.tenant_id == key.tenant_id)
            .order_by(ClassificationLabel.level).all())


@router.get("/rules")
def list_rules(key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db)):
    """Lists the tenant's enabled classification rules in priority order."""
    return {"rules": export_rules(db, key.tenant_id)}
