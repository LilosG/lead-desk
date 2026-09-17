from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.database import pool
from app.integrations.openrouter import OpenRouterClient
from app.integrations.openrouter_constrained import ConstrainedOutreachClient
from app.integrations.openrouter_structured import StructuredOpenRouterClient
from app.repositories.integrations import IntegrationRepository
from app.repositories.outreach import OutreachRepository
from app.repositories.outreach_evidence import OutreachEvidenceRepository
from app.repositories.outreach_gmail import OutreachGmailRepository
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
from app.services.outreach_gmail_review import OutreachGmailReviewService


router = APIRouter(prefix='/api/outreach', tags=['outreach'])


class OutreachReviewGmailRequest(BaseModel):
    expected_version: int = Field(ge=1)
    to_address: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


def get_service() -> OutreachService:
    settings = get_settings()
    generator = None
    if settings.openrouter_configured:
        if settings.openrouter_model == 'qwen/qwen3-30b-a3b-instruct-2507':
            generator_class = ConstrainedOutreachClient
        elif settings.openrouter_model == 'openai/gpt-5-mini':
            generator_class = StructuredOpenRouterClient
        else:
            generator_class = OpenRouterClient

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
        evidence_repository=OutreachEvidenceRepository(pool),
        generator=generator,
        gmail=gmail,
        generation_model=settings.openrouter_model if generator else None,
        gmail_sender_email=settings.gmail_sender_email if gmail else None,
    )


def get_gmail_review_service() -> OutreachGmailReviewService:
    settings = get_settings()
    integration = GmailIntegrationService(IntegrationRepository(pool), settings)
    try:
        gmail = integration.gmail_client()
    except IntegrationConfigurationError as exc:
        raise OutreachIntegrationUnavailable(str(exc)) from exc
    if gmail is None:
        raise OutreachIntegrationUnavailable('Gmail draft integration is not configured')

    repository = OutreachRepository(pool)
    outreach = get_service()
    return OutreachGmailReviewService(
        outreach=outreach,
        repository=repository,
        gmail_repository=OutreachGmailRepository(pool),
        gmail=gmail,
    )


@router.get('/integrations')
def integration_status() -> dict:
    settings = get_settings()
    result = get_service().integration_status()
    gmail_status = GmailIntegrationService(
        IntegrationRepository(pool),
        settings,
    ).status()
    result['gmail_account_email'] = gmail_status.get('account_email')
    result['gmail_connection_mode'] = (
        'oauth'
        if gmail_status.get('connected')
        else 'legacy_env'
        if settings.gmail_legacy_configured
        else None
    )
    return result


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
        'queued', 'researching', 'review_required', 'no_outreach_finding',
        'draft_ready', 'approved', 'contacted', 'replied', 'archived', 'suppressed'
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


@router.post('/items/{item_id}/review-gmail-draft')
def review_and_create_gmail_draft(
    item_id: str,
    payload: OutreachReviewGmailRequest,
) -> dict:
    try:
        result = get_gmail_review_service().review_and_create(
            item_id,
            expected_version=payload.expected_version,
            to_address=payload.to_address,
            subject=payload.subject,
            body=payload.body,
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
