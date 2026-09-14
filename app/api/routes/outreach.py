from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.database import pool
from app.repositories.outreach import OutreachRepository
from app.schemas.outreach import OutreachCreate, OutreachQueueResponse, OutreachUpdate
from app.services.outreach import OutreachBlocked, OutreachConflict, OutreachService


router = APIRouter(prefix='/api/outreach', tags=['outreach'])


def get_service() -> OutreachService:
    return OutreachService(OutreachRepository(pool))


@router.get('', response_model=OutreachQueueResponse)
def list_outreach(
    status: Literal[
        'queued', 'researching', 'review_required', 'draft_ready',
        'approved', 'contacted', 'replied', 'archived', 'suppressed'
    ] | None = Query(default=None),
) -> dict:
    return get_service().list_items(status=status)


@router.post('/{place_id}', status_code=201)
def queue_outreach(place_id: str, payload: OutreachCreate) -> dict:
    try:
        result = get_service().create_item(
            place_id,
            payload.channel,
            payload.to_address,
        )
    except OutreachBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail='prospect not found')
    return result


@router.patch('/items/{item_id}')
def update_outreach(item_id: str, payload: OutreachUpdate) -> dict:
    data = payload.model_dump(exclude_unset=True)
    expected_version = data.pop('expected_version')
    try:
        result = get_service().update_item(
            item_id,
            changes=data,
            expected_version=expected_version,
        )
    except OutreachConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OutreachBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail='outreach item not found')
    return result
