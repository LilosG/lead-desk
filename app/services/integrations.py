from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlencode

import requests

from app.core.config import Settings
from app.core.crypto import CredentialCipher
from app.integrations.gmail import GmailDraftClient
from app.repositories.integrations import IntegrationRepository


GMAIL_PROVIDER = "gmail"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class IntegrationConfigurationError(RuntimeError):
    pass


class MissingGmailPermission(RuntimeError):
    """The Google account was authorized without the Gmail drafts permission."""


class OAuthExchangeError(RuntimeError):
    pass


class GmailIntegrationService:
    def __init__(
        self,
        repository: IntegrationRepository,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.settings = settings

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.public_app_url}/api/integrations/gmail/callback"

    def status(self) -> dict:
        credential = self.repository.get_credential(GMAIL_PROVIDER)
        return {
            "configured": self.settings.gmail_oauth_configured,
            "connected": credential is not None,
            "account_email": credential.get("account_email") if credential else None,
            "sender_email": self.settings.gmail_sender_email,
            "redirect_uri": self.redirect_uri,
            "scope": GMAIL_SCOPE,
            "send_enabled": False,
        }

    def authorization_url(self) -> str:
        self._require_oauth_configuration()
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        self.repository.create_oauth_state(
            GMAIL_PROVIDER,
            state_hash=state_hash,
            ttl_minutes=10,
        )
        params = {
            "client_id": self.settings.gmail_client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": f"openid email {GMAIL_SCOPE}",
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "select_account consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def complete_authorization(self, *, code: str, state: str) -> dict:
        self._require_oauth_configuration()
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        if not self.repository.consume_oauth_state(
            GMAIL_PROVIDER,
            state_hash=state_hash,
        ):
            raise OAuthExchangeError("OAuth state is invalid, expired, or already used")

        try:
            token_response = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.settings.gmail_client_id,
                    "client_secret": self.settings.gmail_client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise OAuthExchangeError("Google OAuth token exchange failed") from exc

        if not token_response.ok:
            raise OAuthExchangeError(
                f"Google OAuth returned {token_response.status_code}: "
                f"{token_response.text[:500]}"
            )

        payload = token_response.json()
        refresh_token = payload.get("refresh_token")
        access_token = payload.get("access_token")
        if not refresh_token:
            raise OAuthExchangeError(
                "Google did not return a refresh token; revoke the prior grant and reconnect"
            )
        if not access_token:
            raise OAuthExchangeError("Google did not return an access token")

        try:
            userinfo = requests.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise OAuthExchangeError("Google account verification failed") from exc
        if not userinfo.ok:
            raise OAuthExchangeError(
                f"Google account verification returned {userinfo.status_code}"
            )

        account_email = str(userinfo.json().get("email") or "").strip().lower()
        if not account_email:
            raise OAuthExchangeError("Google did not return an account email")

        # Google lets people untick individual permissions on the consent
        # screen. Without gmail.compose every draft fails with a 403 later,
        # so refuse the connection now and say why.
        scopes = str(payload.get("scope") or "").split()
        if scopes and GMAIL_SCOPE not in scopes:
            raise MissingGmailPermission(
                "Google didn't grant the Gmail drafts permission"
            )

        cipher = self._cipher()
        encrypted = cipher.encrypt(refresh_token, aad=GMAIL_PROVIDER)
        scopes = scopes or f"openid email {GMAIL_SCOPE}".split()
        return self.repository.upsert_credential(
            GMAIL_PROVIDER,
            account_email=account_email,
            refresh_token_ciphertext=encrypted,
            scopes=scopes,
        )

    def disconnect(self) -> bool:
        return self.repository.delete_credential(GMAIL_PROVIDER)

    def gmail_client(self) -> GmailDraftClient | None:
        credential = self.repository.get_credential(GMAIL_PROVIDER)
        if credential is None:
            if self.settings.gmail_legacy_configured:
                return GmailDraftClient(
                    client_id=self.settings.gmail_client_id or "",
                    client_secret=self.settings.gmail_client_secret or "",
                    refresh_token=self.settings.gmail_refresh_token or "",
                    sender_email=credential.get("account_email") or self.settings.gmail_sender_email,
                )
            return None
        self._require_oauth_configuration()
        refresh_token = self._cipher().decrypt(
            bytes(credential["refresh_token_ciphertext"]),
            aad=GMAIL_PROVIDER,
        )
        return GmailDraftClient(
            client_id=self.settings.gmail_client_id or "",
            client_secret=self.settings.gmail_client_secret or "",
            refresh_token=refresh_token,
            sender_email=credential.get("account_email") or self.settings.gmail_sender_email,
        )

    def _cipher(self) -> CredentialCipher:
        key = self.settings.integration_encryption_key
        if not key:
            raise IntegrationConfigurationError(
                "INTEGRATION_ENCRYPTION_KEY is not configured"
            )
        try:
            return CredentialCipher(key)
        except ValueError as exc:
            raise IntegrationConfigurationError(str(exc)) from exc

    def _require_oauth_configuration(self) -> None:
        if not self.settings.gmail_oauth_configured:
            raise IntegrationConfigurationError(
                "Gmail OAuth requires GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
                "INTEGRATION_ENCRYPTION_KEY, GMAIL_SENDER_EMAIL, and PUBLIC_APP_URL"
            )
