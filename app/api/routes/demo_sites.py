from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from app.core.config import get_settings
from app.core.database import pool
from app.repositories.demo_sites import DemoSiteRepository
from app.repositories.prospects import ProspectRepository
from app.schemas.demo_sites import (
    DemoSiteCreateRequest,
    DemoSiteDetail,
    DemoSiteOptionsResponse,
    DemoSiteSummary,
)
from app.services.demo_sites import DemoSiteError, DemoSiteService


router = APIRouter(prefix="/api/demo-sites", tags=["demo-sites"])


def get_service() -> DemoSiteService:
    return DemoSiteService(
        ProspectRepository(pool),
        DemoSiteRepository(pool),
    )


@router.get(
    "/prospects/{place_id}/options",
    response_model=DemoSiteOptionsResponse,
)
def demo_site_options(place_id: str) -> dict:
    try:
        return get_service().options_for_prospect(place_id)
    except DemoSiteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/prospects/{place_id}",
    response_model=list[DemoSiteSummary],
)
def list_prospect_demos(place_id: str) -> list[dict]:
    return get_service().list_for_prospect(place_id)


@router.post(
    "/prospects/{place_id}",
    response_model=DemoSiteDetail,
    status_code=201,
)
def create_demo_site(place_id: str, payload: DemoSiteCreateRequest) -> dict:
    try:
        return get_service().create_demo(
            place_id,
            template_key=payload.template_key,
            services=payload.services,
            service_areas=payload.service_areas,
            headline=payload.headline,
            subheadline=payload.subheadline,
        )
    except DemoSiteError as exc:
        message = str(exc)
        status_code = 404 if message == "prospect not found" else 422
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/{demo_id}", response_model=DemoSiteDetail)
def get_demo_site(demo_id: str) -> dict:
    demo = get_service().get_demo(demo_id)
    if demo is None:
        raise HTTPException(status_code=404, detail="demo site not found")
    return demo


@router.get("/{demo_id}/preview")
def preview_demo_site(demo_id: str) -> Response:
    html = get_service().get_preview_html(demo_id)
    if html is None:
        raise HTTPException(status_code=404, detail="demo site not found")
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


@router.post("/{demo_id}/publish", response_model=DemoSiteSummary)
def publish_demo_site(demo_id: str) -> dict:
    settings = get_settings()
    try:
        return get_service().publish_demo(
            demo_id,
            root=Path(settings.demo_site_root),
            base_url=settings.demo_site_base_url,
        )
    except DemoSiteError as exc:
        message = str(exc)
        status_code = 404 if message == "demo site not found" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc
