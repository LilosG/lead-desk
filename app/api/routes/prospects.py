from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.database import pool
from app.repositories.prospects import ProspectRepository
from app.schemas.prospects import ProspectDetail, ProspectFilterMeta, ProspectListResponse
from app.services.prospects import ProspectService


router = APIRouter(
    prefix="/prospects",
    tags=["prospects"],
)


@router.get("", response_model=ProspectListResponse)
def list_prospects(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    tier: Literal["A", "B", "C", "D"] | None = None,
    city: str | None = Query(default=None, max_length=100),
    contact: Literal["email", "phone", "none"] | None = None,
    trading: bool | None = None,
    established: bool | None = None,
    category_opportunity: bool | None = None,
) -> dict:
    service = ProspectService(
        ProspectRepository(pool)
    )

    return service.list_prospects(
        page=page,
        page_size=page_size,
        search=search,
        tier=tier,
        city=city,
        contact=contact,
        trading=trading,
        established=established,
        category_opportunity=category_opportunity,
    )


@router.get(
    "/meta",
    response_model=ProspectFilterMeta,
)
def prospect_filter_meta() -> dict:
    service = ProspectService(
        ProspectRepository(pool)
    )
    return service.filter_meta()


@router.get(
    "/{place_id}",
    response_model=ProspectDetail,
)
def get_prospect(place_id: str) -> dict:
    service = ProspectService(
        ProspectRepository(pool)
    )

    result = service.get_prospect(place_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="prospect not found in latest completed run",
        )

    return result
