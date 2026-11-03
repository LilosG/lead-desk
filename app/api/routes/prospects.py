from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import pool
from app.repositories.prospects import ProspectRepository
from app.schemas.prospects import (
    ProspectDetail,
    ProspectFilterMeta,
    ProspectListResponse,
    ProspectWorkflowState,
    ProspectWorkflowUpdate,
)
from app.services.pipeline_bridge import load
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
    label: str | None = Query(default=None, max_length=40, pattern=r"^[a-z_]+$"),
    market: str | None = Query(default=None, max_length=120),
    qualification: str | None = Query(default=None, max_length=40, pattern=r"^[a-z_]+$"),
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
        label=label,
        market=market,
        qualification=qualification,
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
            detail="prospect not found in operational inventory",
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
    data = payload.model_dump(exclude_unset=True, mode="json")
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


class WebsiteUpdate(BaseModel):
    url: str


class ContactUpdate(BaseModel):
    email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    site_checked: bool = False


@router.post("/{place_id}/contact")
def update_prospect_contact(place_id: str, payload: ContactUpdate) -> dict:
    """Add an email Mike found, or sign off a site the crawler couldn't read."""
    if payload.email is None and not payload.site_checked:
        raise HTTPException(status_code=422, detail="nothing to update")
    email = payload.email.lower() if payload.email else None
    if not get_service().repository.set_manual_contact(
        place_id, email=email, site_checked=payload.site_checked,
    ):
        raise HTTPException(status_code=404, detail="prospect not found")

    load("site_rescore").rescore_lead(place_id, "Contact updated by hand")
    return {"place_id": place_id, "email": email, "site_checked": payload.site_checked}


@router.post("/{place_id}/website")
def set_prospect_website(place_id: str, payload: WebsiteUpdate) -> dict:
    """Link a website to a lead whose Google profile has none, then re-score it.

    Crawls the site now (seconds) and re-scores; Google's speed test runs in
    the background and re-scores again when it finishes (about a minute).
    The lead is then audited on that site, with 'website isn't linked on the
    Google profile' as a finding instead of 'no website'.
    """
    site_rescore = load("site_rescore")
    WebsiteError, set_manual_website = site_rescore.WebsiteError, site_rescore.set_manual_website

    try:
        result = set_manual_website(place_id, payload.url, with_psi=False)
    except WebsiteError as exc:
        status = 404 if "not found" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    import threading

    def _speed_test() -> None:
        try:
            set_manual_website(place_id, result["website_url"], with_psi=True)
        except Exception:
            pass  # the crawl-only score already saved stays in place

    threading.Thread(target=_speed_test, daemon=True).start()
    return {**result, "speed_test": "running"}
