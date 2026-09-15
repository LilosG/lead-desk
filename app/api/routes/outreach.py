from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.core.database import pool
from app.integrations.openrouter import OpenRouterClient
from app.integrations.openrouter_structured import StructuredOpenRouterClient
from app.repositories.integrations import IntegrationRepository
from app.repositories.outreach import OutreachRepository
from app.schemas.outreach import (
    OutreachCreate,
    OutreachQueueResponse,
    OutreachUpdate,
    OutreachVersionAction,
)
from app.services.integrations import GmailIntegrationService, IntegrationConfigurationError
from app.services.outreach import (
    OutreachBlocked,
    OutreachConflict,
    OutreachIntegrationUnavailable,
    OutreachService,
)


router = APIRouter(prefix='/api/outreach', tags=['outreach'])


def get_service() -> OutreachService:
    settings = get_settings()
    generator = None
    if settings.openrouter_configured:
        generator_class = (
            StructuredOpenRouterClient
            if settings.openrouter_model == 'openai/gpt-5-mini'
            else OpenRouterClient
        )
        generator = generator_class(
            api_key=settings.openrouter_api_key or '',
            model=settings.openrouter_model,
        )

    gmail = None
    try:
        gmail = GmailIntegrationService(
            IntegrationRepository(pool),
            settings,
        ).gmail_client()
    except IntegrationConfigurationError:
        gmail = None

    return OutreachService(
        OutreachRepository(pool),
        generator=generator,
        gmail=gmail,
        generation_model=settings.openrouter_model if generator else None,
        gmail_sender_email=settings.gmail_sender_email if gmail else None,
    )


@router.get('/integrations')
def integration_status() -> dict:
    return get_service().integration_status()


@router.get('/candidates')
def list_candidates(limit: int = Query(default=100, ge=1, le=250)) -> dict:
    return get_service().list_candidates(limit=limit)


@router.get('/readiness/{place_id}')
def outreach_readiness(place_id: str) -> dict:
    result = get_service().candidate_readiness(place_id)

    if result is None:
        raise HTTPException(status_code=404, detail='prospect not found')

    return result


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
    service = get_service()
    readiness = service.candidate_readiness(place_id)

    if readiness is None:
        raise HTTPException(status_code=404, detail='prospect not found')

    blockers = [
        reason
        for reason in readiness['reasons']
        if reason != 'Prospect is already in the outreach queue.'
    ]
    if blockers:
        raise HTTPException(
            status_code=422,
            detail='outreach readiness blocked: ' + ' '.join(blockers),
        )

    try:
        result = service.create_item(
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


@router.post('/items/{item_id}/generate')
def generate_outreach_draft(item_id: str, payload: OutreachVersionAction) -> dict:
    try:
        result = get_service().generate_draft(
            item_id,
            expected_version=payload.expected_version,
        )
    except OutreachConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OutreachBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OutreachIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail='outreach item not found')
    return result


@router.post('/items/{item_id}/gmail-draft')
def create_gmail_draft(item_id: str, payload: OutreachVersionAction) -> dict:
    try:
        result = get_service().create_gmail_draft(
            item_id,
            expected_version=payload.expected_version,
        )
    except OutreachConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OutreachBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OutreachIntegrationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail='outreach item not found')
    return result
