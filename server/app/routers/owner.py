from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_owner
from ..models import (
    Asset, AuditLog, ContactMessage, Endpoint, Payment, PaymentGatewayConfig,
    Plan, Subscription, Tenant, User,
)
from ..schemas import ContactIn, GatewayConfigIn, PlanOut, PlanUpdate

router = APIRouter(prefix="/api/owner", tags=["owner"])


def mask(value: str) -> str:
    if not value:
        return ""
    return value[:4] + "•" * max(len(value) - 8, 4) + value[-4:] if len(value) > 8 else "•" * len(value)


@router.get("/stats")
def platform_stats(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    revenue = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
        Payment.status == "succeeded").scalar()
    return {
        "tenants": db.query(Tenant).count(),
        "active_tenants": db.query(Tenant).filter(Tenant.status == "active").count(),
        "users": db.query(User).filter(User.role != "owner").count(),
        "assets": db.query(Asset).count(),
        "endpoints": db.query(Endpoint).count(),
        "payments": db.query(Payment).count(),
        "revenue": round(revenue, 2),
    }


@router.get("/tenants")
def list_tenants(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    out = []
    for t in db.query(Tenant).order_by(Tenant.created_at.desc()).all():
        sub = db.query(Subscription).filter(Subscription.tenant_id == t.id).first()
        out.append({
            "id": t.id, "name": t.name, "slug": t.slug, "status": t.status,
            "created_at": t.created_at.isoformat(),
            "plan": sub.plan.name if sub else None,
            "users": db.query(User).filter(User.tenant_id == t.id).count(),
            "assets": db.query(Asset).filter(Asset.tenant_id == t.id).count(),
            "endpoints": db.query(Endpoint).filter(Endpoint.tenant_id == t.id).count(),
        })
    return out


@router.patch("/tenants/{tenant_id}/toggle")
def toggle_tenant(tenant_id: int, user: User = Depends(require_owner), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    tenant.status = "suspended" if tenant.status == "active" else "active"
    db.add(AuditLog(tenant_id=tenant.id, user_id=user.id,
                    action=f"tenant.{tenant.status}", detail=tenant.name))
    db.commit()
    return {"id": tenant.id, "status": tenant.status}


@router.get("/users")
def list_all_users(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    rows = (db.query(User, Tenant).outerjoin(Tenant, User.tenant_id == Tenant.id)
            .filter(User.role != "owner").order_by(User.created_at.desc()).all())
    return [{
        "id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role,
        "is_active": u.is_active, "tenant": t.name if t else None,
        "created_at": u.created_at.isoformat(),
    } for u, t in rows]


@router.get("/payments")
def list_all_payments(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    payments = db.query(Payment).order_by(Payment.created_at.desc()).limit(500).all()
    return [{
        "id": p.id, "tenant": p.tenant.name if p.tenant else None,
        "plan": p.plan.name if p.plan else None, "amount": p.amount,
        "currency": p.currency, "status": p.status, "ref": p.provider_ref,
        "created_at": p.created_at.isoformat(),
    } for p in payments]


@router.get("/plans", response_model=list[PlanOut])
def list_plans(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    return db.query(Plan).order_by(Plan.price_monthly).all()


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, payload: PlanUpdate,
                _: User = Depends(require_owner), db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/messages")
def list_messages(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    msgs = db.query(ContactMessage).order_by(ContactMessage.created_at.desc()).limit(500).all()
    return [{
        "id": m.id, "name": m.name, "email": m.email, "company": m.company,
        "topic": m.topic, "message": m.message, "status": m.status,
        "created_at": m.created_at.isoformat(),
    } for m in msgs]


@router.patch("/messages/{message_id}/toggle")
def toggle_message(message_id: int, _: User = Depends(require_owner), db: Session = Depends(get_db)):
    msg = db.get(ContactMessage, message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.status = "replied" if msg.status == "new" else "new"
    db.commit()
    return {"id": msg.id, "status": msg.status}


@router.get("/gateway")
def get_gateway(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    cfg = db.query(PaymentGatewayConfig).first()
    if not cfg:
        return {"provider": "stripe", "mode": "test", "publishable_key": "",
                "secret_key": "", "webhook_secret": "", "configured": False}
    return {
        "provider": cfg.provider, "mode": cfg.mode,
        "publishable_key": cfg.publishable_key,
        "secret_key": mask(cfg.secret_key),
        "webhook_secret": mask(cfg.webhook_secret),
        "configured": True,
    }


@router.put("/gateway")
def set_gateway(payload: GatewayConfigIn,
                user: User = Depends(require_owner), db: Session = Depends(get_db)):
    cfg = db.query(PaymentGatewayConfig).first()
    if not cfg:
        cfg = PaymentGatewayConfig()
        db.add(cfg)
    cfg.provider = payload.provider
    cfg.mode = payload.mode
    cfg.publishable_key = payload.publishable_key
    # Keep existing secrets when the (masked) value isn't re-entered.
    if payload.secret_key and "•" not in payload.secret_key:
        cfg.secret_key = payload.secret_key
    if payload.webhook_secret and "•" not in payload.webhook_secret:
        cfg.webhook_secret = payload.webhook_secret
    db.add(AuditLog(user_id=user.id, action="gateway.updated",
                    detail=f"{payload.provider} ({payload.mode})"))
    db.commit()
    return {"ok": True}
