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
    Endpoint, StampPolicy, Subscription, User, WatermarkConfig,
)
from ..schemas import (
    BuildCreate, BuildOut, EndpointOut, LabelCreate, LabelOut,
    RuleCreate, RuleOut, RuleUpdate, StampPolicyIn, StampPolicyOut,
    UserCreate, UserOut, WatermarkIn, WatermarkOut,
)
from ..deps import require_tenant_admin
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["tenant-admin"])

AGENT_DIR = Path(__file__).resolve().parents[3] / "agent"
# Prebuilt single-file Go agent binaries served with the download (static, no
# Python/Node runtime needed). macOS binary is a universal x86_64+arm64 build.
AGENT_BIN_DIR = Path(__file__).resolve().parents[2] / "agent_bin"
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
    # The agent runs as a system service (root / SYSTEM), so scan the all-users
    # directory rather than a single user's home. The scanner prunes caches and
    # system folders, and is capped by max_files_per_scan.
    scan_paths = ["C:\\Users"] if build.platform == "windows" else ["/Users"]
    config = {
        "server_url": server_url,
        "enrollment_token": build.enrollment_token,
        "platform": build.platform,
        "version": build.version,
        "scan_paths": scan_paths,
        "scan_interval_minutes": 60,
    }

    # Single statically-linked Go binary — no Python/Node runtime on the endpoint.
    if build.platform == "windows":
        binary_path = AGENT_BIN_DIR / "classifyhub-agent.exe"
        binary_arcname = "classifyhub-agent/classifyhub-agent.exe"
    else:
        binary_path = AGENT_BIN_DIR / "classifyhub-agent"
        binary_arcname = "classifyhub-agent/classifyhub-agent"
    if not binary_path.exists():
        raise HTTPException(503, "Agent binary not available on the server for this platform. "
                                 "Build it via build/build.sh and redeploy.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # The compiled agent (mark executable in the zip for macOS/Linux).
        info = zipfile.ZipInfo(binary_arcname)
        info.external_attr = 0o755 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, binary_path.read_bytes())
        zf.writestr("classifyhub-agent/config.json", json.dumps(config, indent=2))

        if build.platform == "macos":
            installer = (
                "#!/bin/bash\n"
                "# ClassifyHub macOS installer — copies the agent to a stable location,\n"
                "# clears the download quarantine, and registers it as a launchd daemon.\n"
                "set -e\n"
                'cd "$(dirname "$0")"\n'
                'DIR="/Library/Application Support/ClassifyHub"\n'
                'echo "Installing ClassifyHub agent (requires your admin password)..."\n'
                'sudo mkdir -p "$DIR"\n'
                'sudo cp classifyhub-agent "$DIR/classifyhub-agent"\n'
                'sudo cp config.json "$DIR/config.json"\n'
                'sudo xattr -dr com.apple.quarantine "$DIR/classifyhub-agent" 2>/dev/null || true\n'
                'sudo chmod +x "$DIR/classifyhub-agent"\n'
                'sudo "$DIR/classifyhub-agent" install\n'
                'echo "Installed. The agent runs at boot and scans on schedule."\n'
            )
            info = zipfile.ZipInfo("classifyhub-agent/install.command")
            info.external_attr = 0o755 << 16
            zf.writestr(info, installer)
            readme = (
                f"ClassifyHub agent (macOS, universal) v{build.version}\n"
                f"{'=' * 48}\n\n"
                "INSTALL — double-click 'install.command' (or in Terminal: bash install.command).\n"
                "It asks for your admin password, installs the agent as a background service,\n"
                "and starts it. That's it — one binary, no Python or other runtime needed.\n\n"
                "If macOS says \"cannot verify it is free of malware\", the binary just isn't\n"
                "Apple-notarized yet: right-click install.command > Open, or run\n"
                "  xattr -dr com.apple.quarantine .\n"
                "in this folder first. (Production builds are signed + notarized — see\n"
                "agent/installers/SIGNING_AND_CERTIFICATION.md.)\n\n"
                "Manage: sudo classifyhub-agent {start|stop|uninstall}\n"
                "Logs:   /Library/Application Support/ClassifyHub/agent.log\n"
            )
        else:
            installer = (
                "@echo off\r\n"
                "REM ClassifyHub Windows installer — elevates, copies the agent, and\r\n"
                "REM registers it as a Windows Service.\r\n"
                'net session >nul 2>&1\r\n'
                "if %errorlevel% neq 0 (\r\n"
                "  powershell -Command \"Start-Process '%~f0' -Verb RunAs\"\r\n"
                "  exit /b\r\n"
                ")\r\n"
                'cd /d "%~dp0"\r\n'
                'set "DIR=%ProgramData%\\ClassifyHub"\r\n'
                'if not exist "%DIR%" mkdir "%DIR%"\r\n'
                'copy /Y classifyhub-agent.exe "%DIR%\\classifyhub-agent.exe" >nul\r\n'
                'copy /Y config.json "%DIR%\\config.json" >nul\r\n'
                '"%DIR%\\classifyhub-agent.exe" install\r\n'
                'echo Installed. The agent runs as a Windows Service.\r\n'
                "pause\r\n"
            )
            zf.writestr("classifyhub-agent/Install ClassifyHub.bat", installer)
            readme = (
                f"ClassifyHub agent (Windows) v{build.version}\n"
                f"{'=' * 48}\n\n"
                "INSTALL — double-click 'Install ClassifyHub.bat'. It requests admin rights,\r\n"
                "installs the agent as a Windows Service, and starts it. One binary, no\r\n"
                "Python or other runtime needed.\r\n\n"
                "SmartScreen may warn because the binary isn't code-signed yet: choose\r\n"
                "\"More info\" > \"Run anyway\". (Production builds are signed — see\r\n"
                "agent/installers/SIGNING_AND_CERTIFICATION.md.)\r\n\n"
                "Manage (admin prompt): classifyhub-agent.exe {start|stop|uninstall}\r\n"
                "Logs: %ProgramData%\\ClassifyHub\\agent.log\r\n"
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


# ---------- Document stamping policy ----------
def _stamp_for(db: Session, tenant_id: int) -> StampPolicy:
    pol = db.query(StampPolicy).filter(StampPolicy.tenant_id == tenant_id).first()
    if not pol:
        pol = StampPolicy(tenant_id=tenant_id)
        db.add(pol)
        db.commit()
        db.refresh(pol)
    return pol


@router.get("/stamp-policy", response_model=StampPolicyOut)
def get_stamp_policy(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    return _stamp_for(db, user.tenant_id)


@router.put("/stamp-policy", response_model=StampPolicyOut)
def set_stamp_policy(payload: StampPolicyIn,
                     user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    if payload.placement not in ("header", "footer"):
        raise HTTPException(400, "placement must be 'header' or 'footer'")
    if "{label}" not in payload.text_template:
        raise HTTPException(400, "text_template must contain {label}")
    pol = _stamp_for(db, user.tenant_id)
    for field, value in payload.model_dump().items():
        setattr(pol, field, value)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="stamp_policy.updated",
                    detail=f"enabled={payload.enabled} mandatory={payload.mandatory}"))
    db.commit()
    db.refresh(pol)
    return pol


# ---------- Google Workspace auto-stamp ----------
@router.get("/gdrive")
def get_gdrive(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    from ..models import GoogleWorkspaceConfig
    cfg = db.query(GoogleWorkspaceConfig).filter(GoogleWorkspaceConfig.tenant_id == user.tenant_id).first()
    if not cfg:
        return {"enabled": False, "service_account_configured": False, "impersonate_subject": "",
                "placement": "header", "client_email": "", "last_scan": None, "last_status": ""}
    client_email = ""
    if cfg.service_account_json:
        try:
            client_email = json.loads(cfg.service_account_json).get("client_email", "")
        except ValueError:
            client_email = "(invalid JSON)"
    return {
        "enabled": cfg.enabled,
        "service_account_configured": bool(cfg.service_account_json),
        "client_email": client_email,
        "impersonate_subject": cfg.impersonate_subject,
        "placement": cfg.placement,
        "last_scan": cfg.last_scan.isoformat() if cfg.last_scan else None,
        "last_status": cfg.last_status,
    }


@router.put("/gdrive")
def set_gdrive(payload: dict, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    from ..models import GoogleWorkspaceConfig
    cfg = db.query(GoogleWorkspaceConfig).filter(GoogleWorkspaceConfig.tenant_id == user.tenant_id).first()
    if not cfg:
        cfg = GoogleWorkspaceConfig(tenant_id=user.tenant_id)
        db.add(cfg)
    sa = str(payload.get("service_account_json", "")).strip()
    if sa:  # keep existing key if the field is left blank on save
        try:
            json.loads(sa)
        except ValueError:
            raise HTTPException(400, "Service account JSON is not valid JSON")
        cfg.service_account_json = sa
    cfg.impersonate_subject = str(payload.get("impersonate_subject", cfg.impersonate_subject)).strip()
    cfg.placement = payload.get("placement", cfg.placement)
    cfg.enabled = bool(payload.get("enabled", cfg.enabled))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="gdrive.configured",
                    detail=f"enabled={cfg.enabled}"))
    db.commit()
    return {"ok": True}


@router.post("/gdrive/scan")
def scan_gdrive(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    from ..integrations import google_drive
    from ..models import GoogleWorkspaceConfig
    cfg = db.query(GoogleWorkspaceConfig).filter(GoogleWorkspaceConfig.tenant_id == user.tenant_id).first()
    if not cfg or not cfg.service_account_json:
        raise HTTPException(400, "Configure the Google service account first")
    return google_drive.scan_tenant(db, cfg)


# ---------- Microsoft 365 auto-stamp ----------
@router.get("/m365")
def get_m365(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    from ..models import MicrosoftConfig
    cfg = db.query(MicrosoftConfig).filter(MicrosoftConfig.tenant_id == user.tenant_id).first()
    if not cfg:
        return {"enabled": False, "azure_tenant_id": "", "client_id": "", "secret_configured": False,
                "drive_user": "", "placement": "footer", "last_scan": None, "last_status": ""}
    return {
        "enabled": cfg.enabled, "azure_tenant_id": cfg.azure_tenant_id, "client_id": cfg.client_id,
        "secret_configured": bool(cfg.client_secret), "drive_user": cfg.drive_user,
        "placement": cfg.placement,
        "last_scan": cfg.last_scan.isoformat() if cfg.last_scan else None,
        "last_status": cfg.last_status,
    }


@router.put("/m365")
def set_m365(payload: dict, user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    from ..models import MicrosoftConfig
    cfg = db.query(MicrosoftConfig).filter(MicrosoftConfig.tenant_id == user.tenant_id).first()
    if not cfg:
        cfg = MicrosoftConfig(tenant_id=user.tenant_id)
        db.add(cfg)
    cfg.azure_tenant_id = str(payload.get("azure_tenant_id", cfg.azure_tenant_id)).strip()
    cfg.client_id = str(payload.get("client_id", cfg.client_id)).strip()
    secret = str(payload.get("client_secret", "")).strip()
    if secret:  # keep existing if left blank
        cfg.client_secret = secret
    cfg.drive_user = str(payload.get("drive_user", cfg.drive_user)).strip()
    cfg.placement = payload.get("placement", cfg.placement)
    cfg.enabled = bool(payload.get("enabled", cfg.enabled))
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="m365.configured",
                    detail=f"enabled={cfg.enabled}"))
    db.commit()
    return {"ok": True}


@router.post("/m365/scan")
def scan_m365(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    from ..integrations import microsoft365
    from ..models import MicrosoftConfig
    cfg = db.query(MicrosoftConfig).filter(MicrosoftConfig.tenant_id == user.tenant_id).first()
    if not cfg or not cfg.client_secret:
        raise HTTPException(400, "Configure the Microsoft 365 app registration first")
    return microsoft365.scan_tenant(db, cfg)


# ---------- Audit log ----------
@router.get("/audit")
def audit_log(user: User = Depends(require_tenant_admin), db: Session = Depends(get_db)):
    logs = (db.query(AuditLog).filter(AuditLog.tenant_id == user.tenant_id)
            .order_by(AuditLog.created_at.desc()).limit(200).all())
    return [{"id": l.id, "action": l.action, "detail": l.detail,
             "created_at": l.created_at.isoformat()} for l in logs]
