import hashlib
import io
import json
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import APP_VERSION
from ..database import get_db
from ..models import (
    AgentBuild, ApiKey, Asset, AuditLog, ClassificationLabel, ClassificationRule,
    Endpoint, Subscription, User, WatermarkConfig,
)
from ..schemas import (
    BuildCreate, BuildOut, EndpointOut, LabelCreate, LabelOut,
    RuleCreate, RuleOut, RuleUpdate, UserCreate, UserOut,
    WatermarkIn, WatermarkOut,
)
from ..deps import require_tenant_admin
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["tenant-admin"])

AGENT_DIR = Path(__file__).resolve().parents[3] / "agent"
SUPPORTED_PLATFORMS = {"macos", "windows"}


# ---------- Dashboard ----------
@router.get("/dashboard")
def dashboard(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    tid = user.tenant_id
    by_label = (
        db.query(ClassificationLabel.name, ClassificationLabel.color, func.count(Asset.id))
        .outerjoin(Asset, (Asset.label_id == ClassificationLabel.id))
        .filter(ClassificationLabel.tenant_id == tid)
        .group_by(ClassificationLabel.id)
        .order_by(ClassificationLabel.level)
        .all()
    )
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    sub = db.query(Subscription).filter(Subscription.tenant_id == tid).first()
    return {
        "assets_total": db.query(Asset).filter(Asset.tenant_id == tid).count(),
        "assets_last_7d": db.query(Asset).filter(Asset.tenant_id == tid, Asset.classified_at >= week_ago).count(),
        "endpoints": db.query(Endpoint).filter(Endpoint.tenant_id == tid).count(),
        "users": db.query(User).filter(User.tenant_id == tid).count(),
        "rules": db.query(ClassificationRule).filter(ClassificationRule.tenant_id == tid).count(),
        "by_label": [{"name": n, "color": c, "count": cnt} for n, c, cnt in by_label],
        "plan": sub.plan.name if sub else None,
        "plan_limits": {"max_users": sub.plan.max_users, "max_endpoints": sub.plan.max_endpoints,
                        "max_assets": sub.plan.max_assets} if sub else None,
    }


# ---------- Labels ----------
@router.get("/labels", response_model=list[LabelOut])
def list_labels(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return (db.query(ClassificationLabel).filter(ClassificationLabel.tenant_id == user.tenant_id)
            .order_by(ClassificationLabel.level).all())


@router.post("/labels", response_model=LabelOut)
def create_label(payload: LabelCreate, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    label = ClassificationLabel(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.delete("/labels/{label_id}")
def delete_label(label_id: int, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    label = (db.query(ClassificationLabel)
             .filter(ClassificationLabel.id == label_id, ClassificationLabel.tenant_id == user.tenant_id).first())
    if not label:
        raise HTTPException(404, "Label not found")
    in_use = db.query(ClassificationRule).filter(ClassificationRule.label_id == label_id).count()
    if in_use:
        raise HTTPException(400, f"Label is used by {in_use} rule(s). Remove those rules first.")
    db.query(Asset).filter(Asset.label_id == label_id).update({Asset.label_id: None})
    db.delete(label)
    db.commit()
    return {"ok": True}


# ---------- Rules ----------
@router.get("/rules", response_model=list[RuleOut])
def list_rules(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return (db.query(ClassificationRule).filter(ClassificationRule.tenant_id == user.tenant_id)
            .order_by(ClassificationRule.priority).all())


@router.post("/rules", response_model=RuleOut)
def create_rule(payload: RuleCreate, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    label = (db.query(ClassificationLabel)
             .filter(ClassificationLabel.id == payload.label_id,
                     ClassificationLabel.tenant_id == user.tenant_id).first())
    if not label:
        raise HTTPException(400, "Invalid label for this tenant")
    rule = ClassificationRule(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(rule)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="rule.created", detail=payload.name))
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, payload: RuleUpdate,
                user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    rule = (db.query(ClassificationRule)
            .filter(ClassificationRule.id == rule_id, ClassificationRule.tenant_id == user.tenant_id).first())
    if not rule:
        raise HTTPException(404, "Rule not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    rule = (db.query(ClassificationRule)
            .filter(ClassificationRule.id == rule_id, ClassificationRule.tenant_id == user.tenant_id).first())
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}


# ---------- Tenant users ----------
@router.get("/users", response_model=list[UserOut])
def list_users(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return db.query(User).filter(User.tenant_id == user.tenant_id).order_by(User.created_at).all()


@router.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    if payload.role not in ("user", "admin"):
        raise HTTPException(400, "Role must be 'user' or 'admin'")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")
    sub = db.query(Subscription).filter(Subscription.tenant_id == user.tenant_id).first()
    if sub and db.query(User).filter(User.tenant_id == user.tenant_id).count() >= sub.plan.max_users:
        raise HTTPException(402, f"User limit reached for the {sub.plan.name} plan. Upgrade to continue.")
    new_user = User(
        tenant_id=user.tenant_id, email=payload.email, full_name=payload.full_name,
        password_hash=hash_password(payload.password), role=payload.role,
    )
    db.add(new_user)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="user.created", detail=payload.email))
    db.commit()
    db.refresh(new_user)
    return new_user


@router.patch("/users/{user_id}/toggle", response_model=UserOut)
def toggle_user(user_id: int, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id, User.tenant_id == user.tenant_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(400, "You cannot disable your own account")
    target.is_active = not target.is_active
    db.commit()
    db.refresh(target)
    return target


# ---------- Endpoint agent builds ----------
@router.get("/builds", response_model=list[BuildOut])
def list_builds(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return (db.query(AgentBuild).filter(AgentBuild.tenant_id == user.tenant_id)
            .order_by(AgentBuild.created_at.desc()).all())


@router.post("/builds", response_model=BuildOut)
def create_build(payload: BuildCreate, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    if payload.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(400, "Platform must be 'macos' or 'windows'")
    build = AgentBuild(tenant_id=user.tenant_id, platform=payload.platform,
                       version=APP_VERSION, created_by=user.id)
    db.add(build)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="build.created",
                    detail=f"{payload.platform} agent build"))
    db.commit()
    db.refresh(build)
    return build


@router.get("/builds/{build_id}/download")
def download_build(build_id: int, request: Request,
                   user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    build = (db.query(AgentBuild)
             .filter(AgentBuild.id == build_id, AgentBuild.tenant_id == user.tenant_id).first())
    if not build:
        raise HTTPException(404, "Build not found")

    server_url = str(request.base_url).rstrip("/")
    config = {
        "server_url": server_url,
        "enrollment_token": build.enrollment_token,
        "platform": build.platform,
        "version": build.version,
        "scan_paths": ["~/Documents", "~/Desktop", "~/Downloads"],
        "scan_interval_minutes": 60,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(AGENT_DIR / "agent.py", "classifyhub-agent/agent.py")
        zf.writestr("classifyhub-agent/config.json", json.dumps(config, indent=2))
        if build.platform == "macos":
            zf.write(AGENT_DIR / "installers" / "install_macos.sh", "classifyhub-agent/install.sh")
        else:
            zf.write(AGENT_DIR / "installers" / "install_windows.ps1", "classifyhub-agent/install.ps1")
        readme = (
            f"ClassifyHub endpoint agent ({build.platform}) v{build.version}\n"
            f"{'=' * 48}\n\n"
        )
        if build.platform == "macos":
            readme += (
                "INSTALL (macOS)\n"
                "---------------\n"
                "macOS quarantines files downloaded from the internet, so first clear\n"
                "the quarantine flag on this unzipped folder, then run the installer:\n\n"
                "  xattr -dr com.apple.quarantine \"<this folder>\"\n"
                "  bash install.sh\n\n"
                "If you skip the first line you'll see \"cannot verify it is free of\n"
                "malware\" — that only means the agent isn't Apple-notarized yet, not\n"
                "that anything is wrong. (Alternatively: System Settings > Privacy &\n"
                "Security > Open Anyway.)\n\n"
                "Requires python3 (preinstalled, or from the Xcode Command Line Tools).\n"
            )
        else:
            readme += (
                "INSTALL (Windows)\n"
                "-----------------\n"
                "Right-click install.ps1 > Properties > tick \"Unblock\", or run:\n\n"
                "  powershell -ExecutionPolicy Bypass -File install.ps1\n\n"
                "SmartScreen may warn because the script isn't code-signed yet; choose\n"
                "\"More info\" > \"Run anyway\". Requires Python 3 (python.org).\n"
            )
        readme += (
            "\nThe agent enrolls with your workspace on first run, then scans the\n"
            "configured paths and reports classified assets back to the server.\n"
            "For signed, fleet-managed deployment see the MSI/PKG installers and\n"
            "MANAGED_DEPLOYMENT guide in the ClassifyHub repository.\n"
        )
        zf.writestr("classifyhub-agent/README.txt", readme)

    build.downloads += 1
    db.commit()
    buf.seek(0)
    filename = f"classifyhub-agent-{build.platform}-{build.version}.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/endpoints", response_model=list[EndpointOut])
def list_endpoints(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return (db.query(Endpoint).filter(Endpoint.tenant_id == user.tenant_id)
            .order_by(Endpoint.enrolled_at.desc()).all())


# ---------- API keys (paid plans only) ----------
MAX_API_KEYS = 10


def require_paid_plan(db: Session, tenant_id: int) -> None:
    sub = db.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()
    if not sub or sub.status != "active" or sub.plan.price_monthly <= 0:
        raise HTTPException(402, "API access requires an active paid plan (Pro or Enterprise). "
                                 "Upgrade under Admin Console → Billing.")


@router.get("/apikeys")
def list_api_keys(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    keys = (db.query(ApiKey).filter(ApiKey.tenant_id == user.tenant_id)
            .order_by(ApiKey.created_at.desc()).all())
    return [{
        "id": k.id, "name": k.name, "key_prefix": k.key_prefix,
        "created_at": k.created_at.isoformat(),
        "last_used": k.last_used.isoformat() if k.last_used else None,
        "revoked": k.revoked,
    } for k in keys]


@router.post("/apikeys")
def create_api_key(payload: dict, user: User = Depends(require_tenant_admin),
                   db: Session = Depends(get_db)):
    require_paid_plan(db, user.tenant_id)
    name = str(payload.get("name", "")).strip() or "Integration key"
    active = (db.query(ApiKey)
              .filter(ApiKey.tenant_id == user.tenant_id, ApiKey.revoked.is_(False)).count())
    if active >= MAX_API_KEYS:
        raise HTTPException(400, f"Limit of {MAX_API_KEYS} active keys reached. Revoke unused keys first.")

    full_key = f"chk_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        tenant_id=user.tenant_id, name=name[:120],
        key_prefix=full_key[:12] + "…",
        key_hash=hashlib.sha256(full_key.encode()).hexdigest(),
        created_by=user.id,
    )
    db.add(key)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id,
                    action="apikey.created", detail=name))
    db.commit()
    db.refresh(key)
    # The full key is returned exactly once; only its hash is stored.
    return {"id": key.id, "name": key.name, "key": full_key, "key_prefix": key.key_prefix,
            "created_at": key.created_at.isoformat()}


@router.patch("/apikeys/{key_id}/revoke")
def revoke_api_key(key_id: int, user: User = Depends(require_tenant_admin),
                   db: Session = Depends(get_db)):
    key = (db.query(ApiKey)
           .filter(ApiKey.id == key_id, ApiKey.tenant_id == user.tenant_id).first())
    if not key:
        raise HTTPException(404, "API key not found")
    key.revoked = True
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id,
                    action="apikey.revoked", detail=key.name))
    db.commit()
    return {"id": key.id, "revoked": True}


# ---------- Screen watermark ----------
PLACEMENTS = {"tiled", "center", "top-left", "top-right", "bottom-left", "bottom-right"}


def _watermark_for(db: Session, tenant_id: int) -> WatermarkConfig:
    cfg = db.query(WatermarkConfig).filter(WatermarkConfig.tenant_id == tenant_id).first()
    if not cfg:
        cfg = WatermarkConfig(tenant_id=tenant_id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


@router.get("/watermark", response_model=WatermarkOut)
def get_watermark(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return _watermark_for(db, user.tenant_id)


@router.put("/watermark", response_model=WatermarkOut)
def set_watermark(payload: WatermarkIn,
                  user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    if payload.placement not in PLACEMENTS:
        raise HTTPException(400, f"placement must be one of {sorted(PLACEMENTS)}")
    cfg = _watermark_for(db, user.tenant_id)
    for field, value in payload.model_dump().items():
        setattr(cfg, field, value)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="watermark.updated",
                    detail=f"enabled={payload.enabled} placement={payload.placement}"))
    db.commit()
    db.refresh(cfg)
    return cfg


# ---------- Audit log ----------
@router.get("/audit")
def audit_log(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    logs = (db.query(AuditLog).filter(AuditLog.tenant_id == user.tenant_id)
            .order_by(AuditLog.created_at.desc()).limit(200).all())
    return [{"id": l.id, "action": l.action, "detail": l.detail,
             "created_at": l.created_at.isoformat()} for l in logs]
