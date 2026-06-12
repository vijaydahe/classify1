import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


def gen_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(24)}"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), unique=True, nullable=False)
    status = Column(String(20), default="active")  # active | suspended
    created_at = Column(DateTime, default=utcnow)

    users = relationship("User", back_populates="tenant")
    subscription = relationship("Subscription", back_populates="tenant", uselist=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)  # null => platform owner
    email = Column(String(255), nullable=False)
    full_name = Column(String(120), default="")
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")  # owner | admin | user
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant", back_populates="users")


class ClassificationLabel(Base):
    __tablename__ = "classification_labels"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(60), nullable=False)
    level = Column(Integer, default=0)  # higher = more sensitive
    color = Column(String(20), default="#6b7280")
    description = Column(String(255), default="")

    rules = relationship("ClassificationRule", back_populates="label")


class ClassificationRule(Base):
    __tablename__ = "classification_rules"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    rule_type = Column(String(20), default="keyword")  # keyword | regex
    pattern = Column(Text, nullable=False)
    label_id = Column(Integer, ForeignKey("classification_labels.id"), nullable=False)
    priority = Column(Integer, default=100)
    enabled = Column(Boolean, default=True)

    label = relationship("ClassificationLabel", back_populates="rules")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    asset_type = Column(String(60), default="document")
    content_excerpt = Column(Text, default="")
    label_id = Column(Integer, ForeignKey("classification_labels.id"), nullable=True)
    matched_rules = Column(Text, default="")  # comma separated rule names
    source = Column(String(20), default="manual")  # manual | csv | agent
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=True)
    classified_at = Column(DateTime, default=utcnow)

    label = relationship("ClassificationLabel")
    endpoint = relationship("Endpoint")


class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    hostname = Column(String(255), default="")
    platform = Column(String(20), default="unknown")  # macos | windows
    api_key = Column(String(80), unique=True, default=lambda: gen_token("ep"))
    status = Column(String(20), default="enrolled")
    enrolled_at = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, nullable=True)
    build_id = Column(Integer, ForeignKey("agent_builds.id"), nullable=True)


class AgentBuild(Base):
    __tablename__ = "agent_builds"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    platform = Column(String(20), nullable=False)  # macos | windows
    version = Column(String(20), default="1.0.0")
    enrollment_token = Column(String(80), unique=True, default=lambda: gen_token("enroll"))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    downloads = Column(Integer, default=0)


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), unique=True, nullable=False)
    price_monthly = Column(Float, default=0.0)
    max_users = Column(Integer, default=3)
    max_endpoints = Column(Integer, default=2)
    max_assets = Column(Integer, default=500)
    is_active = Column(Boolean, default=True)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), unique=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    status = Column(String(20), default="active")  # active | past_due | canceled
    started_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant", back_populates="subscription")
    plan = relationship("Plan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    amount = Column(Float, default=0.0)
    currency = Column(String(10), default="USD")
    status = Column(String(20), default="succeeded")
    provider_ref = Column(String(80), default=lambda: gen_token("pay"))
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant")
    plan = relationship("Plan")


class PaymentGatewayConfig(Base):
    __tablename__ = "payment_gateway_config"

    id = Column(Integer, primary_key=True)
    provider = Column(String(40), default="stripe")
    mode = Column(String(20), default="test")  # test | live
    publishable_key = Column(String(255), default="")
    secret_key = Column(String(255), default="")
    webhook_secret = Column(String(255), default="")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class StampPolicy(Base):
    __tablename__ = "stamp_policy"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), unique=True, nullable=False)
    enabled = Column(Boolean, default=False)
    mandatory = Column(Boolean, default=False)       # block save unless stamped
    placement = Column(String(10), default="footer")  # header | footer
    font_name = Column(String(60), default="Arial")
    font_size = Column(Integer, default=10)
    color = Column(String(20), default="#dc2626")
    text_template = Column(String(120), default="CLASSIFICATION: {label}")
    exempt_emails = Column(Text, default="")          # newline/comma separated, admin-granted


class WatermarkConfig(Base):
    __tablename__ = "watermark_config"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    opacity = Column(Float, default=0.15)          # 0.05 - 0.5
    font_size = Column(Integer, default=18)         # px, 10 - 48
    placement = Column(String(20), default="tiled")  # tiled | center | top-left | top-right | bottom-left | bottom-right
    show_timestamp = Column(Boolean, default=True)
    show_classification = Column(Boolean, default=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    key_prefix = Column(String(20), nullable=False)  # shown in lists; full key never stored
    key_hash = Column(String(64), unique=True, nullable=False)  # sha256 of the full key
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    last_used = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)


class ContactMessage(Base):
    __tablename__ = "contact_messages"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False)
    company = Column(String(120), default="")
    topic = Column(String(60), default="General question")
    message = Column(Text, nullable=False)
    status = Column(String(20), default="new")  # new | replied
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(120), nullable=False)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
