from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.database import pool
from app.schemas.common import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1 as ok")
                row = cur.fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="database unavailable",
        ) from exc

    if not row or row["ok"] != 1:
        raise HTTPException(
            status_code=503,
            detail="database health check failed",
        )

    return HealthResponse(
        status="ok",
        database="ok",
        app=settings.app_name,
        version=settings.app_version,
    )
