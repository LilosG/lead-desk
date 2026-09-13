from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, overview, prospects, runs
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
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/api")
app.include_router(overview.router, prefix="/api")
app.include_router(prospects.router, prefix="/api")
app.include_router(runs.router, prefix="/api")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "status": "ok",
        "api": "/api",
        "docs": "/docs",
    }
