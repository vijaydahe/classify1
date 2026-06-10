from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ---- Auth ----
class TenantSignup(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    full_name: str = ""
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: int | None
    tenant_name: str | None = None
    full_name: str = ""


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=8)
    role: str = "user"  # user | admin


# ---- Classification config ----
class LabelOut(BaseModel):
    id: int
    name: str
    level: int
    color: str
    description: str

    class Config:
        from_attributes = True


class LabelCreate(BaseModel):
    name: str
    level: int = 0
    color: str = "#6b7280"
    description: str = ""


class RuleOut(BaseModel):
    id: int
    name: str
    rule_type: str
    pattern: str
    label_id: int
    priority: int
    enabled: bool

    class Config:
        from_attributes = True


class RuleCreate(BaseModel):
    name: str
    rule_type: str = "keyword"
    pattern: str
    label_id: int
    priority: int = 100
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    rule_type: str | None = None
    pattern: str | None = None
    label_id: int | None = None
    priority: int | None = None
    enabled: bool | None = None


# ---- Assets ----
class AssetClassifyRequest(BaseModel):
    name: str
    asset_type: str = "document"
    content: str = ""


class AssetOut(BaseModel):
    id: int
    name: str
    asset_type: str
    content_excerpt: str
    label: LabelOut | None
    matched_rules: str
    source: str
    classified_at: datetime

    class Config:
        from_attributes = True


# ---- Endpoints / builds ----
class BuildCreate(BaseModel):
    platform: str  # macos | windows


class BuildOut(BaseModel):
    id: int
    platform: str
    version: str
    enrollment_token: str
    created_at: datetime
    downloads: int

    class Config:
        from_attributes = True


class EndpointOut(BaseModel):
    id: int
    hostname: str
    platform: str
    status: str
    enrolled_at: datetime
    last_seen: datetime | None

    class Config:
        from_attributes = True


# ---- Agent API ----
class AgentEnrollRequest(BaseModel):
    enrollment_token: str
    hostname: str
    platform: str


class AgentAssetReport(BaseModel):
    name: str
    asset_type: str = "file"
    label: str | None = None
    matched_rules: list[str] = []
    content_excerpt: str = ""


class AgentReportRequest(BaseModel):
    assets: list[AgentAssetReport]


# ---- Billing / owner ----
class PlanOut(BaseModel):
    id: int
    name: str
    price_monthly: float
    max_users: int
    max_endpoints: int
    max_assets: int
    is_active: bool

    class Config:
        from_attributes = True


class PlanUpdate(BaseModel):
    price_monthly: float | None = None
    max_users: int | None = None
    max_endpoints: int | None = None
    max_assets: int | None = None
    is_active: bool | None = None


class SubscribeRequest(BaseModel):
    plan_id: int
    card_number: str = ""  # mock checkout field
    card_exp: str = ""
    card_cvc: str = ""


class GatewayConfigIn(BaseModel):
    provider: str = "stripe"
    mode: str = "test"
    publishable_key: str = ""
    secret_key: str = ""
    webhook_secret: str = ""
