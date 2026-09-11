from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.seed import seed_demo_data
from app.routers import auth, feedback, queue, appointments, emr, billing, chat
from app.middleware.audit import AuditLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
    return {"status": "healthy", "service": settings.APP_NAME}


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

