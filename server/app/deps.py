from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import Endpoint, Tenant, User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    if user.tenant_id is not None:
        tenant = db.get(Tenant, user.tenant_id)
        if not tenant or tenant.status != "active":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant is suspended")
    return user


def require_tenant_user(user: User = Depends(get_current_user)) -> User:
    if user.tenant_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant account required")
    return user


def require_tenant_admin(user: User = Depends(get_current_user)) -> User:
    if user.tenant_id is None or user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant admin access required")
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform owner access required")
    return user


def get_agent_endpoint(
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
    db: Session = Depends(get_db),
) -> Endpoint:
    endpoint = db.query(Endpoint).filter(Endpoint.api_key == x_agent_key).first()
    if not endpoint:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent key")
    tenant = db.get(Tenant, endpoint.tenant_id)
    if not tenant or tenant.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant is suspended")
    return endpoint
