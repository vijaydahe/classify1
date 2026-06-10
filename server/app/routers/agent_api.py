from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..classification import classify_text, export_rules
from ..database import get_db
from ..deps import get_agent_endpoint
from ..models import AgentBuild, Asset, AuditLog, ClassificationLabel, Endpoint, Subscription, Tenant
from ..schemas import AgentEnrollRequest, AgentReportRequest

router = APIRouter(prefix="/api/agent", tags=["agent"])


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
    labels = {l.name: l for l in db.query(ClassificationLabel)
              .filter(ClassificationLabel.tenant_id == endpoint.tenant_id).all()}
    created = 0
    for item in payload.assets:
        if item.label and item.label in labels:
            label_id = labels[item.label].id
            matched = ", ".join(item.matched_rules)
        else:
            # Agent didn't classify locally — classify server-side.
            label, matched_names = classify_text(db, endpoint.tenant_id, item.name, item.content_excerpt)
            label_id = label.id if label else None
            matched = ", ".join(matched_names)
        db.add(Asset(
            tenant_id=endpoint.tenant_id, name=item.name, asset_type=item.asset_type,
            content_excerpt=item.content_excerpt[:300], label_id=label_id,
            matched_rules=matched, source="agent", endpoint_id=endpoint.id,
        ))
        created += 1
    db.add(AuditLog(tenant_id=endpoint.tenant_id, action="agent.report",
                    detail=f"{created} assets reported by {endpoint.hostname}"))
    db.commit()
    return {"accepted": created}
