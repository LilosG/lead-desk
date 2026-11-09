from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from app.core.config import get_settings
from app.core.database import pool
from app.repositories.demo_media import DemoMediaRepository
from app.repositories.demo_sites import DemoSiteRepository
from app.repositories.prospects import ProspectRepository
from app.schemas.demo_sites import (
    DemoCopyRequest,
    DemoCopyResponse,
    DemoMediaGenerateRequest,
    DemoMediaItem,
    DemoSiteCreateRequest,
    DemoSiteDetail,
    DemoSiteOptionsResponse,
    DemoSiteSummary,
)
from app.services.demo_media import DemoMediaError, DemoMediaService
from app.services.demo_sites import DemoSiteError, DemoSiteService


router = APIRouter(prefix="/api/demo-sites", tags=["demo-sites"])


def get_service() -> DemoSiteService:
    return DemoSiteService(
        ProspectRepository(pool),
        DemoSiteRepository(pool),
    )


def get_media_service() -> DemoMediaService:
    return DemoMediaService(
        ProspectRepository(pool),
        DemoMediaRepository(pool),
    )


@router.get(
    "/prospects/{place_id}/options",
    response_model=DemoSiteOptionsResponse,
)
def demo_site_options(place_id: str) -> dict:
    try:
        options = get_service().options_for_prospect(place_id)
    except DemoSiteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**options, "ai_copy_available": get_settings().openrouter_configured}


@router.post(
    "/prospects/{place_id}/copy",
    response_model=DemoCopyResponse,
)
def write_demo_copy(place_id: str, payload: DemoCopyRequest) -> dict:
    settings = get_settings()
    if not settings.openrouter_configured:
        raise HTTPException(status_code=503, detail="AI copy is not configured")
    try:
        return get_service().write_copy(
            place_id,
            services=payload.services,
            service_areas=payload.service_areas,
            api_key=settings.openrouter_api_key or "",
            model=settings.demo_copy_model,
        )
    except DemoSiteError as exc:
        message = str(exc)
        raise HTTPException(status_code=404 if message == "prospect not found" else 422, detail=message) from exc


@router.get(
    "/prospects/{place_id}",
    response_model=list[DemoSiteSummary],
)
def list_prospect_demos(place_id: str) -> list[dict]:
    return get_service().list_for_prospect(place_id)


@router.get(
    "/prospects/{place_id}/media",
    response_model=list[DemoMediaItem],
)
def list_prospect_demo_media(place_id: str) -> list[dict]:
    return get_media_service().list_for_prospect(place_id)


@router.post(
    "/prospects/{place_id}/media/generate",
    response_model=DemoMediaItem,
    status_code=201,
)
def generate_prospect_demo_media(
    place_id: str,
    payload: DemoMediaGenerateRequest,
) -> dict:
    settings = get_settings()
    if not settings.demo_image_generation_configured:
        raise HTTPException(
            status_code=503,
            detail="demo image generation is not configured",
        )
    try:
        return get_media_service().generate(
            place_id,
            role=payload.role,
            direction=payload.direction,
            api_key=settings.openrouter_api_key or "",
            model=settings.demo_image_model,
            root=Path(settings.demo_site_root),
            base_url=settings.demo_site_base_url,
        )
    except DemoMediaError as exc:
        message = str(exc)
        status_code = 404 if message == "prospect not found" else 422
        if message == "demo image generation is not configured":
            status_code = 503
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post(
    "/prospects/{place_id}",
    response_model=DemoSiteDetail,
    status_code=201,
)
def create_demo_site(place_id: str, payload: DemoSiteCreateRequest) -> dict:
    settings = get_settings()
    try:
        return get_service().create_demo(
            place_id,
            template_key=payload.template_key,
            services=payload.services,
            service_areas=payload.service_areas,
            headline=payload.headline,
            subheadline=payload.subheadline,
            hero_image_url=payload.hero_image_url,
            work_image_url=payload.work_image_url,
            secondary_image_url=payload.secondary_image_url,
            use_site_branding=payload.use_site_branding,
            about=payload.about,
            service_blurbs=payload.service_blurbs,
            media_root=Path(settings.demo_site_root),
            media_base_url=settings.demo_site_base_url,
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
