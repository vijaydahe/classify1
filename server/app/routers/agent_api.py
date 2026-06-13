from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..classification import export_rules, load_matcher, match_rules
from ..database import get_db
from ..deps import get_agent_endpoint
from ..models import AgentBuild, Asset, AuditLog, ClassificationLabel, Endpoint, Subscription, Tenant
from ..schemas import AgentEnrollRequest, AgentReportRequest

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _clean(s: str) -> str:
    """Strip NUL bytes (and other C0 control chars except tab/newline) that
    Postgres text columns reject and that have no business in stored metadata."""
    if not s:
        return ""
    return "".join(ch for ch in s if ch == "\t" or ch == "\n" or ch >= " ")


@router.post("/enroll")
def enroll(payload: AgentEnrollRequest, db: Session = Depends(get_db)):
    build = db.query(AgentBuild).filter(AgentBuild.enrollment_token == payload.enrollment_token).first()
    if not build:
        raise HTTPException(401, "Invalid enrollment token")
    tenant = db.get(Tenant, build.tenant_id)
    if not tenant or tenant.status != "active":
        raise HTTPException(403, "Tenant is suspended")
    sub = db.query(Subscription).filter(Subscription.tenant_id == build.tenant_id).first()
    if sub and db.query(Endpoint).filter(Endpoint.tenant_id == build.tenant_id).count() >= sub.plan.max_endpoints:
        raise HTTPException(402, f"Endpoint limit reached for the {sub.plan.name} plan")

    endpoint = Endpoint(tenant_id=build.tenant_id, hostname=payload.hostname,
                        platform=payload.platform, build_id=build.id,
                        last_seen=datetime.now(timezone.utc))
    db.add(endpoint)
    db.add(AuditLog(tenant_id=build.tenant_id, action="endpoint.enrolled",
                    detail=f"{payload.hostname} ({payload.platform})"))
    db.commit()
    db.refresh(endpoint)
    return {"endpoint_id": endpoint.id, "api_key": endpoint.api_key}


@router.get("/rules")
def get_rules(endpoint: Endpoint = Depends(get_agent_endpoint), db: Session = Depends(get_db)):
    endpoint.last_seen = datetime.now(timezone.utc)
    db.commit()
    return {"rules": export_rules(db, endpoint.tenant_id)}


@router.post("/report")
def report(payload: AgentReportRequest,
           endpoint: Endpoint = Depends(get_agent_endpoint), db: Session = Depends(get_db)):
    endpoint.last_seen = datetime.now(timezone.utc)
    tid = endpoint.tenant_id

    labels = {l.name: l.id for l in db.query(ClassificationLabel)
              .filter(ClassificationLabel.tenant_id == tid).all()}
    # Load rules once and classify in memory — avoids a DB query per reported file.
    compiled, fallback_id = load_matcher(db, tid)
    # Skip files this endpoint already reported, so repeated scans don't pile up duplicates.
    seen = {n for (n,) in db.query(Asset.name)
            .filter(Asset.tenant_id == tid, Asset.endpoint_id == endpoint.id).all()}

    rows = []
    for item in payload.assets:
        if item.name in seen:
            continue
        seen.add(item.name)
        if item.label and item.label in labels:
            label_id = labels[item.label]
            matched = ", ".join(item.matched_rules)
        else:
            label_id, matched_names = match_rules(compiled, fallback_id, item.name, item.content_excerpt)
            matched = ", ".join(matched_names)
        # Postgres text columns reject NUL bytes, which appear in binary/log files.
        rows.append({
            "tenant_id": tid, "name": _clean(item.name)[:255],
            "asset_type": _clean(item.asset_type)[:60] or "file",
            "content_excerpt": _clean(item.content_excerpt)[:300],
            "label_id": label_id, "matched_rules": _clean(matched),
            "source": "agent", "endpoint_id": endpoint.id,
        })

    if rows:
        db.bulk_insert_mappings(Asset, rows)
    db.add(AuditLog(tenant_id=tid, action="agent.report",
                    detail=f"{len(rows)} new assets reported by {endpoint.hostname}"))
    db.commit()
    return {"accepted": len(rows), "skipped_duplicates": len(payload.assets) - len(rows)}
