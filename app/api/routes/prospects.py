from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.database import pool
from app.repositories.prospects import ProspectRepository
from app.schemas.prospects import (
    ProspectDetail,
    ProspectFilterMeta,
    ProspectListResponse,
    ProspectWorkflowState,
    ProspectWorkflowUpdate,
)
from app.services.prospects import ProspectService, WorkflowVersionConflict


router = APIRouter(
    prefix="/prospects",
    tags=["prospects"],
)


def get_service() -> ProspectService:
    return ProspectService(ProspectRepository(pool))


@router.get("", response_model=ProspectListResponse)
def list_prospects(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    tier: Literal["A", "B", "C", "D"] | None = None,
    city: str | None = Query(default=None, max_length=100),
    vertical: str | None = Query(default=None, max_length=100),
    contact: Literal["email", "phone", "none"] | None = None,
    trading: bool | None = None,
    established: bool | None = None,
    category_opportunity: bool | None = None,
) -> dict:
    return get_service().list_prospects(
        page=page,
        page_size=page_size,
        search=search,
        tier=tier,
        city=city,
        vertical=vertical,
        contact=contact,
        trading=trading,
        established=established,
        category_opportunity=category_opportunity,
    )


@router.get("/meta", response_model=ProspectFilterMeta)
def prospect_filter_meta() -> dict:
    return get_service().filter_meta()


@router.get("/{place_id}", response_model=ProspectDetail)
def get_prospect(place_id: str) -> dict:
    result = get_service().get_prospect(place_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="prospect not found in latest completed run",
        )

    return result


@router.patch(
    "/{place_id}/workflow",
    response_model=ProspectWorkflowState,
)
def update_prospect_workflow(
    place_id: str,
    payload: ProspectWorkflowUpdate,
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    expected_version = data.pop("expected_version")

    try:
        result = get_service().update_workflow(
            place_id,
            changes=data,
            expected_version=expected_version,
        )
    except WorkflowVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "prospect workflow changed since it was loaded; "
                "refresh before saving again"
            ),
        ) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="prospect not found")

    return result
