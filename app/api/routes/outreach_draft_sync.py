from fastapi import APIRouter, HTTPException

from app.api.routes.outreach import get_service
from app.core.database import pool
from app.repositories.outreach_gmail import OutreachGmailRepository
from app.schemas.outreach import OutreachUpdate, OutreachVersionAction
from app.services.outreach import (
    OutreachBlocked,
    OutreachConflict,
    OutreachIntegrationUnavailable,
)
from app.services.outreach_draft_sync import OutreachDraftSyncService


router = APIRouter(prefix="/api/outreach", tags=["outreach"])


def get_sync_service() -> OutreachDraftSyncService:
    return OutreachDraftSyncService(
        outreach=get_service(),
        gmail_repository=OutreachGmailRepository(pool),
    )


@router.patch("/items/{item_id}/save-synced")
def save_synced_draft(item_id: str, payload: OutreachUpdate) -> dict:
    changes = payload.model_dump(
        exclude={"expected_version"},
        exclude_unset=True,
    )
    try:
        result = get_sync_service().save(
            item_id,
            expected_version=payload.expected_version,
            changes=changes,
        )
    except OutreachConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OutreachBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OutreachIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="outreach item not found")
    return result


@router.post("/items/{item_id}/regenerate-synced")
def regenerate_synced_draft(item_id: str, payload: OutreachVersionAction) -> dict:
    try:
        result = get_sync_service().regenerate(
            item_id,
            expected_version=payload.expected_version,
            angle=payload.angle,
        )
    except OutreachConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OutreachBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OutreachIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="outreach item not found")
    return result