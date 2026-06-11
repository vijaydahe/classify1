import resource
import sys
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import metrics

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
    # Grouped counts instead of per-tenant queries: 5 queries total regardless of tenant count.
    user_counts = dict(db.query(User.tenant_id, func.count()).group_by(User.tenant_id).all())
    asset_counts = dict(db.query(Asset.tenant_id, func.count()).group_by(Asset.tenant_id).all())
    endpoint_counts = dict(db.query(Endpoint.tenant_id, func.count()).group_by(Endpoint.tenant_id).all())
    plans = {s.tenant_id: s.plan.name for s in
             db.query(Subscription).join(Plan, Subscription.plan_id == Plan.id).all()}
    return [{
        "id": t.id, "name": t.name, "slug": t.slug, "status": t.status,
        "created_at": t.created_at.isoformat(),
        "plan": plans.get(t.id),
        "users": user_counts.get(t.id, 0),
        "assets": asset_counts.get(t.id, 0),
        "endpoints": endpoint_counts.get(t.id, 0),
    } for t in db.query(Tenant).order_by(Tenant.created_at.desc()).all()]


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


def _grade(value: float, good: float, fair: float) -> str:
    return "good" if value <= good else ("fair" if value <= fair else "poor")


@router.get("/infra")
def infrastructure(_: User = Depends(require_owner), db: Session = Depends(get_db)):
    """Live capacity & performance snapshot for infra upgrade decisions."""
    pings = []
    for _i in range(3):
        t0 = time.perf_counter()
        db.execute(text("select 1"))
        pings.append((time.perf_counter() - t0) * 1000)
    db_ms = round(sum(pings) / len(pings), 1)

    s = metrics.stats
    avg_api_ms = round(s["total_ms"] / s["requests"], 1) if s["requests"] else 0.0
    error_rate = round(100 * s["errors"] / s["requests"], 2) if s["requests"] else 0.0
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    uptime_min = round((time.time() - metrics.started_at) / 60, 1)

    counts = {
        "tenants": db.query(Tenant).count(),
        "users": db.query(User).count(),
        "assets": db.query(Asset).count(),
        "endpoints": db.query(Endpoint).count(),
    }

    checks = [
        {"name": "Database latency", "value": f"{db_ms} ms", "status": _grade(db_ms, 30, 120),
         "hint": "Round-trip from the app server to the database (avg of 3 pings).",
         "fix": "1) Vercel → Project Settings → Functions → set the function region to the one closest to "
                "your Supabase project (e.g. bom1 for ap-south-1). 2) Confirm the connection string uses the "
                "transaction pooler (port 6543). 3) If still slow, buy the Supabase Compute add-on "
                "(Project Settings → Add-ons)."},
        {"name": "Avg API response", "value": f"{avg_api_ms} ms", "status": _grade(avg_api_ms, 300, 800),
         "hint": "Average across all API requests handled by this instance.",
         "fix": "Open browser DevTools → Network and read the Server-Timing header to find slow endpoints. "
                "Then: raise function memory in Vercel (Settings → Functions → Memory — more memory = more CPU) "
                "and upgrade Supabase compute if database latency is also elevated."},
        {"name": "Slowest API request", "value": f"{round(s['max_ms'], 1)} ms", "status": _grade(s["max_ms"], 1000, 3000),
         "hint": "Worst single request since this instance started.",
         "fix": "A single slow request is usually a cold start (first request after idle). Reduce impact with "
                "Vercel Pro (faster cold starts) or keep the function warm: add a Vercel Cron Job that pings "
                "/api/health every 5 minutes."},
        {"name": "Error rate (5xx)", "value": f"{error_rate}%", "status": _grade(error_rate, 0.5, 2),
         "hint": "Server errors as a share of API requests.",
         "fix": "Do not scale yet — errors are usually bugs or exhausted DB connections, not capacity. "
                "Open Vercel → Logs, find the failing endpoint and the Python exception, fix the cause. "
                "If errors mention connection limits, you are not using the pooler URI."},
        {"name": "Instance memory", "value": f"{rss_mb} MB", "status": _grade(rss_mb, 512, 900),
         "hint": "Peak memory of this serverless instance (typical limit 1024 MB).",
         "fix": "Vercel → Project Settings → Functions → increase Memory (1024 → 2048/3008 MB). "
                "This also doubles CPU, so API times improve too."},
    ]

    # Every non-green check becomes an actionable recommendation; volume checks add capacity planning.
    recs = []
    for c in checks:
        if c["status"] != "good":
            recs.append({"severity": "high" if c["status"] == "poor" else "medium",
                         "title": f"Fix: {c['name']} ({c['value']})", "detail": c["fix"]})
    if counts["assets"] > 100_000:
        recs.append({"severity": "medium", "title": "Large asset inventory",
                     "detail": "Past ~100k assets, upgrade Supabase compute (Settings → Add-ons) and plan "
                               "table partitioning for the assets table."})
    if counts["tenants"] > 50:
        recs.append({"severity": "medium", "title": "Tenant count growing",
                     "detail": "With 50+ tenants, move from the Supabase free tier to Pro for predictable "
                               "performance, daily backups and no project pausing."})
    if not recs:
        recs.append({"severity": "ok", "title": "Capacity is healthy — nothing to fix",
                     "detail": "All signals are green for the current load. Standard growth path when numbers "
                               "turn amber: ① match Vercel function region to Supabase, ② Supabase Pro plan, "
                               "③ Supabase Compute add-on, ④ more Vercel function memory, ⑤ Vercel Pro."})

    return {
        "checks": checks,
        "recommendations": recs,
        "instance": {
            "uptime_min": uptime_min,
            "requests": s["requests"],
            "python": sys.version.split()[0],
        },
        "counts": counts,
    }


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
