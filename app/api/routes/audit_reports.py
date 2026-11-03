from fastapi import APIRouter, HTTPException, Response

from app.core.database import pool
from app.repositories.audit_reports import AuditReportRepository
from app.repositories.demo_sites import DemoSiteRepository
from app.repositories.prospects import ProspectRepository
from app.schemas.audit_reports import (
    AuditReportBatchRequest,
    AuditReportBatchResponse,
    AuditReportCreateRequest,
    AuditReportDetail,
    AuditReportOptionsResponse,
    AuditReportSummary,
)
from app.services.audit_report_pdf import render_audit_report_pdf
from app.services.audit_reports import AuditReportError, AuditReportService
from app.services.site_refresh import SiteRefresher


router = APIRouter(
    prefix="/api/audit-reports",
    tags=["audit-reports"],
)


def get_service() -> AuditReportService:
    return AuditReportService(
        ProspectRepository(pool),
        AuditReportRepository(pool),
        DemoSiteRepository(pool),
        site_refresher=SiteRefresher(ProspectRepository(pool)),
    )


@router.post(
    "/batch",
    response_model=AuditReportBatchResponse,
    status_code=201,
)
def create_audit_reports_batch(payload: AuditReportBatchRequest) -> dict:
    """Create one default report per prospect, for working leads at volume."""
    items = get_service().create_default_reports(payload.place_ids)
    created = sum(1 for item in items if item["status"] == "created")
    return {"items": items, "created": created, "skipped": len(items) - created}


@router.get(
    "/prospects/{place_id}/options",
    response_model=AuditReportOptionsResponse,
)
def audit_report_options(place_id: str) -> dict:
    try:
        return get_service().options_for_prospect(place_id)
    except AuditReportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/prospects/{place_id}",
    response_model=list[AuditReportSummary],
)
def list_prospect_reports(place_id: str) -> list[dict]:
    return get_service().list_for_prospect(place_id)


@router.post(
    "/prospects/{place_id}",
    response_model=AuditReportDetail,
    status_code=201,
)
def create_audit_report(
    place_id: str,
    payload: AuditReportCreateRequest,
) -> dict:
    try:
        return get_service().create_report(
            place_id,
            selected_signals=payload.selected_signals,
        )
    except AuditReportError as exc:
        message = str(exc)
        status_code = 404 if message == "prospect not found" else 422
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/{report_id}", response_model=AuditReportDetail)
def get_audit_report(report_id: str) -> dict:
    report = get_service().get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="audit report not found")
    return report


@router.get("/{report_id}/pdf")
def get_audit_report_pdf(report_id: str) -> Response:
    report = get_service().get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="audit report not found")

    pdf = render_audit_report_pdf(report)
    safe_name = "local-visibility-audit.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Cache-Control": "private, no-store",
        },
    )
