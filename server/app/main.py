import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import metrics
from .config import APP_NAME, APP_VERSION
from .database import Base, SessionLocal, engine, get_db
from .models import ContactMessage
from .routers import agent_api, assets, auth, billing, owner, tenant_admin
from .schemas import ContactIn
from .seed import seed_platform

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def perf_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - t0) * 1000
    path = request.url.path
    if path.startswith("/static"):
        # Assets only change on deploy; let browsers and the CDN keep them.
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
    elif path.startswith("/api"):
        metrics.record(duration_ms, response.status_code >= 500)
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.0f}"
    else:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return response

# When the schema is managed externally (e.g. supabase/schema.sql), set
# CLASSIFYHUB_SKIP_BOOTSTRAP=1 to avoid create_all/seed on every cold start.
if os.environ.get("CLASSIFYHUB_SKIP_BOOTSTRAP") != "1":
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
def landing():
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/app", include_in_schema=False)
def tenant_app():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/support", include_in_schema=False)
def support_page():
    return FileResponse(STATIC_DIR / "support.html")


@app.get("/contact", include_in_schema=False)
def contact_page():
    return FileResponse(STATIC_DIR / "contact.html")


@app.get("/owner", include_in_schema=False)
def owner_console():
    return FileResponse(STATIC_DIR / "owner.html")


@app.post("/api/contact", tags=["public"])
def submit_contact(payload: ContactIn, db: Session = Depends(get_db)):
    db.add(ContactMessage(**payload.model_dump()))
    db.commit()
    return {"ok": True}


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@app.get("/api/health/db", tags=["meta"])
def health_db():
    """Verifies database connectivity and that the schema + owner seed exist."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
            tables_ok = conn.execute(text(
                "select count(*) from users where role = 'owner'")).scalar()
        return {"database": "connected", "owner_accounts": tables_ok}
    except Exception as exc:  # surface the driver error for deploy debugging
        return JSONResponse(status_code=503, content={
            "database": "error",
            "detail": str(exc).splitlines()[0][:300],
        })
