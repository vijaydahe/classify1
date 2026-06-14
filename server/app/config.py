import os

SECRET_KEY = os.environ.get("CLASSIFYHUB_SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("CLASSIFYHUB_TOKEN_TTL_MIN", "480"))
DATABASE_URL = os.environ.get("CLASSIFYHUB_DATABASE_URL", "sqlite:///./classifyhub.db")

OWNER_EMAIL = os.environ.get("CLASSIFYHUB_OWNER_EMAIL", "owner@classifyhub.app")
OWNER_PASSWORD = os.environ.get("CLASSIFYHUB_OWNER_PASSWORD", "owner-admin-123")

APP_NAME = "ClassifyHub"
APP_VERSION = "1.9.0"
