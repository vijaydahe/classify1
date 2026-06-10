from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_tenant_admin, require_tenant_user
from ..models import AuditLog, Payment, PaymentGatewayConfig, Plan, Subscription, User
from ..schemas import PlanOut, SubscribeRequest

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db)):
    return db.query(Plan).filter(Plan.is_active.is_(True)).order_by(Plan.price_monthly).all()


@router.get("/subscription")
def my_subscription(user: User = Depends(require_tenant_user), db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.tenant_id == user.tenant_id).first()
    if not sub:
        return {"plan": None}
    return {
        "plan": PlanOut.model_validate(sub.plan),
        "status": sub.status,
        "started_at": sub.started_at.isoformat(),
    }


@router.get("/payments")
def my_payments(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    payments = (db.query(Payment).filter(Payment.tenant_id == user.tenant_id)
                .order_by(Payment.created_at.desc()).all())
    return [{
        "id": p.id, "amount": p.amount, "currency": p.currency, "status": p.status,
        "plan": p.plan.name if p.plan else None, "ref": p.provider_ref,
        "created_at": p.created_at.isoformat(),
    } for p in payments]


@router.post("/subscribe")
def subscribe(payload: SubscribeRequest,
              user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    """Mock checkout: records a payment and switches the tenant's plan.

    Swap this implementation for a real gateway (e.g. Stripe Checkout) using the
    keys configured by the platform owner in PaymentGatewayConfig.
    """
    plan = db.query(Plan).filter(Plan.id == payload.plan_id, Plan.is_active.is_(True)).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    gateway = db.query(PaymentGatewayConfig).first()
    if plan.price_monthly > 0 and not payload.card_number.strip():
        raise HTTPException(400, "Card details are required for paid plans")

    sub = db.query(Subscription).filter(Subscription.tenant_id == user.tenant_id).first()
    if sub:
        sub.plan_id = plan.id
        sub.status = "active"
    else:
        sub = Subscription(tenant_id=user.tenant_id, plan_id=plan.id)
        db.add(sub)

    if plan.price_monthly > 0:
        db.add(Payment(tenant_id=user.tenant_id, plan_id=plan.id,
                       amount=plan.price_monthly, status="succeeded"))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="billing.subscribed",
                    detail=f"Switched to {plan.name} plan"))
    db.commit()
    return {"ok": True, "plan": plan.name,
            "gateway": gateway.provider if gateway else "mock"}
