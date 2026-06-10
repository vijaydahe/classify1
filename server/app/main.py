from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION
from .database import Base, SessionLocal, engine
from .routers import agent_api, assets, auth, billing, owner, tenant_admin
from .seed import seed_platform

app = FastAPI(title=APP_NAME, version=APP_VERSION)

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    seed_platform(db)

app.include_router(auth.router)
app.include_router(assets.router)
app.include_router(tenant_admin.router)
app.include_router(agent_api.router)
app.include_router(billing.router)
app.include_router(owner.router)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/owner", include_in_schema=False)
def owner_console():
    return FileResponse(STATIC_DIR / "owner.html")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}
