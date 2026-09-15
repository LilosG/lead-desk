from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.database import pool
from app.repositories.integrations import IntegrationRepository
from app.services.integrations import (
    GmailIntegrationService,
    IntegrationConfigurationError,
    OAuthExchangeError,
)


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def get_gmail_service() -> GmailIntegrationService:
    return GmailIntegrationService(
        IntegrationRepository(pool),
        get_settings(),
    )


@router.get("/gmail/status")
def gmail_status() -> dict:
    return get_gmail_service().status()


@router.post("/gmail/connect")
def gmail_connect() -> dict:
    try:
        url = get_gmail_service().authorization_url()
    except IntegrationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url}


@router.get("/gmail/callback", include_in_schema=False)
def gmail_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    settings = get_settings()
    if error:
        return RedirectResponse(
            url=f"{settings.public_app_url}/settings?gmail=error&reason=denied",
            status_code=303,
        )
    if not code or not state:
        return RedirectResponse(
            url=f"{settings.public_app_url}/settings?gmail=error&reason=invalid_callback",
            status_code=303,
        )
    try:
        get_gmail_service().complete_authorization(code=code, state=state)
    except (IntegrationConfigurationError, OAuthExchangeError):
        return RedirectResponse(
            url=f"{settings.public_app_url}/settings?gmail=error&reason=authorization_failed",
            status_code=303,
        )
    return RedirectResponse(
        url=f"{settings.public_app_url}/settings?gmail=connected",
        status_code=303,
    )


@router.delete("/gmail")
def gmail_disconnect() -> dict:
    disconnected = get_gmail_service().disconnect()
    return {"disconnected": disconnected}
