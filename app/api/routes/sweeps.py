from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.sweeps import SweepAlreadyActiveError
from app.services.sweeps import (
    SweepExecutionDisabledError,
    SweepService,
)


router = APIRouter(
    prefix="/api/sweeps",
    tags=["sweeps"],
)


class SweepCreateRequest(BaseModel):
    verticals: list[str] = Field(min_length=1)
    cities: list[str] | None = None
    use_grid: bool = False
    merge_results: bool = True
    crawl_batch: int = Field(default=80, ge=1, le=500)
    psi_batch: int = Field(default=20, ge=1, le=200)


@router.get("/current")
def current_sweep():
    service = SweepService()

    return {
        "execution_enabled": service.execution_enabled(),
        "job": service.current(),
    }


@router.get("")
def list_sweeps(limit: int = 25):
    limit = max(1, min(limit, 100))

    return {
        "items": SweepService().list(limit),
    }


@router.post("", status_code=202)
def create_sweep(payload: SweepCreateRequest):
    service = SweepService()

    try:
        job = service.create(
            verticals=payload.verticals,
            cities=payload.cities,
            use_grid=payload.use_grid,
            merge_results=payload.merge_results,
            crawl_batch=payload.crawl_batch,
            psi_batch=payload.psi_batch,
        )

    except SweepExecutionDisabledError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except SweepAlreadyActiveError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return job


@router.post("/{job_id}/cancel")
def cancel_sweep(job_id: UUID):
    job = SweepService().cancel(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Active sweep job not found.",
        )

    return job
