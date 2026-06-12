import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..classification import classify_text, seed_tenant_defaults
from ..database import get_db
from ..deps import get_current_user
from ..models import Asset, AuditLog, Plan, Subscription, Tenant, User
from ..schemas import LoginRequest, TenantSignup, TokenResponse, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

DEMO_EMAIL = "demo@classifyhub.app"
DEMO_PASSWORD = "demo1234"

DEMO_ASSETS = [
    ("Q3-payroll.xlsx", "spreadsheet", "salary data, bank account 50100223344, SSN 123-45-6789"),
    ("customer-crm-export.csv", "spreadsheet", "customer list: jane@acme.com, phone (555) 123-4567"),
    ("production.env", "source code", "api_key = sk_live_demo123\npassword = hunter2"),
    ("press-release-launch.docx", "document", "Public announcement: marketing launch press release"),
    ("project-phoenix-roadmap.pptx", "document", "Internal use only — roadmap draft and project plan"),
    ("patient-records-2025.pdf", "document", "patient diagnosis, medical record, health insurance"),
    ("nda-acme-corp.pdf", "document", "Confidential — NDA, do not distribute"),
    ("meeting-notes-jan.md", "document", "Meeting notes and project plan for January"),
    ("invoice-2026-031.pdf", "document", "Invoice: bank account IBAN DE89370400440532013000"),
    ("website-brochure.pdf", "document", "Public brochure for the marketing website"),
]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tenant"


@router.post("/register", response_model=TokenResponse)
def register_tenant(payload: TenantSignup, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")

    slug = base_slug = slugify(payload.company_name)
    n = 1
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        n += 1
        slug = f"{base_slug}-{n}"

    tenant = Tenant(name=payload.company_name, slug=slug)
    db.add(tenant)
    db.flush()

    admin = User(
        tenant_id=tenant.id,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="admin",
    )
    db.add(admin)
    db.flush()

    seed_tenant_defaults(db, tenant.id)

    free_plan = db.query(Plan).filter(Plan.name == "Free").first()
    if free_plan:
        db.add(Subscription(tenant_id=tenant.id, plan_id=free_plan.id))

    db.add(AuditLog(tenant_id=tenant.id, user_id=admin.id, action="tenant.registered",
                    detail=f"Tenant '{tenant.name}' created"))
    db.commit()

    token = create_access_token(admin.id, admin.role, tenant.id)
    return TokenResponse(access_token=token, role=admin.role, tenant_id=tenant.id,
                         tenant_name=tenant.name, full_name=admin.full_name)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "Account is disabled")
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    if tenant and tenant.status != "active":
        raise HTTPException(403, "Your organization is suspended. Contact support.")
    token = create_access_token(user.id, user.role, user.tenant_id)
    return TokenResponse(access_token=token, role=user.role, tenant_id=user.tenant_id,
                         tenant_name=tenant.name if tenant else None, full_name=user.full_name)


@router.post("/demo", response_model=TokenResponse)
def demo_login(db: Session = Depends(get_db)):
    """Logs into the shared demo workspace, creating and pre-populating it on first use."""
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if not user:
        slug = "demo-workspace"
        n = 1
        while db.query(Tenant).filter(Tenant.slug == slug).first():
            n += 1
            slug = f"demo-workspace-{n}"
        tenant = Tenant(name="Demo Workspace", slug=slug)
        db.add(tenant)
        db.flush()
        user = User(
            tenant_id=tenant.id, email=DEMO_EMAIL, full_name="Demo User",
            password_hash=hash_password(DEMO_PASSWORD), role="admin",
        )
        db.add(user)
        db.flush()
        seed_tenant_defaults(db, tenant.id)
        db.flush()  # session has autoflush=False; rules must be visible to classify_text below
        free_plan = db.query(Plan).filter(Plan.name == "Free").first()
        if free_plan:
            db.add(Subscription(tenant_id=tenant.id, plan_id=free_plan.id))
        for name, asset_type, content in DEMO_ASSETS:
            label, matched = classify_text(db, tenant.id, name, content)
            db.add(Asset(
                tenant_id=tenant.id, name=name, asset_type=asset_type,
                content_excerpt=content[:300], label_id=label.id if label else None,
                matched_rules=", ".join(matched), source="manual",
            ))
        db.add(AuditLog(tenant_id=tenant.id, user_id=user.id, action="tenant.registered",
                        detail="Demo workspace created"))
        db.commit()
    tenant = db.get(Tenant, user.tenant_id)
    token = create_access_token(user.id, user.role, user.tenant_id)
    return TokenResponse(access_token=token, role=user.role, tenant_id=user.tenant_id,
                         tenant_name=tenant.name if tenant else None, full_name=user.full_name)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/stamp-policy")
def my_stamp_policy(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stamping policy for the current user, including whether they're exempt."""
    from ..models import StampPolicy
    pol = None
    if user.tenant_id is not None:
        pol = db.query(StampPolicy).filter(StampPolicy.tenant_id == user.tenant_id).first()
    exempt = False
    if pol and pol.exempt_emails:
        exempt_list = {e.strip().lower() for e in pol.exempt_emails.replace(",", "\n").split("\n") if e.strip()}
        exempt = user.email.lower() in exempt_list
    return {
        "enabled": pol.enabled if pol else False,
        "mandatory": (pol.mandatory if pol else False) and not exempt,
        "exempt": exempt,
        "placement": pol.placement if pol else "footer",
        "font_name": pol.font_name if pol else "Arial",
        "font_size": pol.font_size if pol else 10,
        "color": pol.color if pol else "#dc2626",
        "text_template": pol.text_template if pol else "CLASSIFICATION: {label}",
    }


@router.get("/watermark")
def my_watermark(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Watermark config for the current user's workspace, plus their display identity."""
    from ..models import WatermarkConfig
    cfg = None
    if user.tenant_id is not None:
        cfg = db.query(WatermarkConfig).filter(WatermarkConfig.tenant_id == user.tenant_id).first()
    return {
        "identity": user.full_name or user.email,
        "email": user.email,
        "config": {
            "enabled": cfg.enabled if cfg else True,
            "opacity": cfg.opacity if cfg else 0.15,
            "font_size": cfg.font_size if cfg else 18,
            "placement": cfg.placement if cfg else "tiled",
            "show_timestamp": cfg.show_timestamp if cfg else True,
            "show_classification": cfg.show_classification if cfg else True,
        },
    }
