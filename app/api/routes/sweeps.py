from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.repositories.sweeps import SweepAlreadyActiveError
from app.services.sweep_locations import SweepLocationLookupError, suggest_us_cities
from app.services.sweeps import (
    SweepExecutionDisabledError,
    SweepService,
)
from pipeline import config as market_config


router = APIRouter(
    prefix="/api/sweeps",
    tags=["sweeps"],
)


class SweepCreateRequest(BaseModel):
    verticals: list[str] = Field(min_length=1)
    cities: list[str] = Field(min_length=1)
    use_grid: bool = False
    merge_results: bool = True
    crawl_batch: int = Field(default=80, ge=1, le=500)
    psi_batch: int = Field(default=20, ge=1, le=200)

    @field_validator("cities")
    @classmethod
    def normalize_cities(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for raw_city in value:
            city = " ".join(raw_city.split())
            if not city:
                continue
            if len(city) > 120:
                raise ValueError("sweep city is too long")
            if any(ord(char) < 32 for char in city):
                raise ValueError("sweep city contains invalid characters")

            key = city.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(city)

        if not normalized:
            raise ValueError("select at least one U.S. city for the sweep")

        return normalized


@router.get("/config")
def sweep_configuration():
    return SweepService.market_configuration()


@router.get("/locations")
def sweep_location_suggestions(
    q: str = Query(min_length=2, max_length=80),
):
    try:
        items = suggest_us_cities(
            q,
            api_key=market_config.GOOGLE_API_KEY,
        )
    except SweepLocationLookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"items": items}


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

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
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
