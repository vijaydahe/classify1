import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..classification import seed_tenant_defaults
from ..database import get_db
from ..deps import get_current_user
from ..models import AuditLog, Plan, Subscription, Tenant, User
from ..schemas import LoginRequest, TenantSignup, TokenResponse, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


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


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
