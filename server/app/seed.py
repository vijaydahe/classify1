"""Seeds the platform owner account and default subscription plans."""
from sqlalchemy.orm import Session

from .config import OWNER_EMAIL, OWNER_PASSWORD
from .models import Plan, User
from .security import hash_password

DEFAULT_PLANS = [
    {"name": "Free", "price_monthly": 0.0, "max_users": 3, "max_endpoints": 2, "max_assets": 500},
    {"name": "Pro", "price_monthly": 49.0, "max_users": 25, "max_endpoints": 50, "max_assets": 50000},
    {"name": "Enterprise", "price_monthly": 199.0, "max_users": 1000, "max_endpoints": 1000, "max_assets": 1000000},
]


def seed_platform(db: Session) -> None:
    if not db.query(User).filter(User.role == "owner").first():
        db.add(User(
            tenant_id=None,
            email=OWNER_EMAIL,
            full_name="Platform Owner",
            password_hash=hash_password(OWNER_PASSWORD),
            role="owner",
        ))
    for spec in DEFAULT_PLANS:
        if not db.query(Plan).filter(Plan.name == spec["name"]).first():
            db.add(Plan(**spec))
    db.commit()
