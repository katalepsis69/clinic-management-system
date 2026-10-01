from contextlib import asynccontextmanager
import logging
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.seed import seed_demo_data
from app.routers import admin, auth, feedback, queue, appointments, emr, billing, chat
from app.middleware.audit import AuditLoggingMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # ponytail: idempotent startup migration so the active-ticket index also lands
    # on databases created before it existed; alembic when schema changes grow
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_queue_patient_active "
                "ON queue_tickets (patient_id) WHERE status = 'WAITING'"
            ))
    except Exception:
        logger.exception("Could not ensure ux_queue_patient_active index; "
                         "existing rows may violate the one-active-ticket rule")
    if settings.DATABASE_URL.startswith("sqlite") and (
        os.environ.get("WEB_CONCURRENCY") or os.environ.get("RENDER_EXTERNAL_URL")
    ):
        logger.warning(
            "SQLite at %s is local and ephemeral on most platforms; set DATABASE_URL "
            "to a managed database for any deployed or multi-worker profile",
            settings.DATABASE_URL,
        )
    if settings.DEMO_MODE:
        with SessionLocal() as db:
            seed_demo_data(db)
    yield


settings = get_settings()
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.add_middleware(AuditLoggingMiddleware)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:;"
    )
    return response

# Mount API Routers
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(feedback.router)
app.include_router(queue.router)
app.include_router(appointments.router)
app.include_router(emr.router)
app.include_router(billing.router)
app.include_router(chat.router)

# Static files and SPA entry
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/api/health")
def health_check():
    # Readiness must mean "can serve data"; a DB outage should fail the probe.
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check failed: database unreachable")
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "healthy", "database": "ok", "service": settings.APP_NAME}


NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/")
def serve_index():
    return FileResponse("app/static/index.html", headers=NO_CACHE_HEADERS)


@app.get("/display")
def serve_public_display():
    return FileResponse("app/static/display.html", headers=NO_CACHE_HEADERS)


@app.get("/manifest.json")
def serve_manifest():
    return FileResponse("app/static/manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
def serve_service_worker():
    return FileResponse(
        "app/static/sw.js",
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )

