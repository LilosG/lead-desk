from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.core.database import pool
from app.repositories.runs import RunRepository
from app.schemas.runs import RunDetail, RunListResponse
from app.services.runs import RunService
from pipeline.config import QUALIFICATION_LABELS


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunListResponse)
def list_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    service = RunService(RunRepository(pool))
    return service.list_runs(page=page, page_size=page_size)


@router.get("/{run_id}/funnel")
def run_funnel(run_id: UUID) -> dict:
    result = RunRepository(pool).funnel(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {**result, "labels": QUALIFICATION_LABELS}


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: UUID) -> dict:
    service = RunService(RunRepository(pool))
    result = service.get_run(run_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="run not found",
        )

    return result
