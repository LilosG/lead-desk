from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routes import health, overview, prospects, runs
from app.api.routes.audit_reports import router as audit_reports_router
from app.api.routes.auth import router as auth_router
from app.api.routes.demo_sites import router as demo_sites_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.outreach import router as outreach_router
from app.api.routes.sweeps import router as sweeps_router
from app.core.auth import session_from_request
from app.core.config import get_settings
from app.core.database import close_pool, open_pool


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/session",
    "/api/auth/logout",
    "/api/integrations/gmail/callback",
}


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path

    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        if session_from_request(request) is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "authentication required"},
            )

    return await call_next(request)


app.include_router(auth_router)
app.include_router(health.router, prefix="/api")
app.include_router(overview.router, prefix="/api")
app.include_router(prospects.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(sweeps_router)
app.include_router(outreach_router)
app.include_router(audit_reports_router)
app.include_router(demo_sites_router)
app.include_router(integrations_router)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "status": "ok",
    }
