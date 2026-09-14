from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage

import requests


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"


class GmailDraftError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailDraftResult:
    draft_id: str
    message_id: str | None


class GmailDraftClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sender_email: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.sender_email = sender_email
        self.timeout_seconds = timeout_seconds

    def create_draft(
        self,
        *,
        to_address: str,
        subject: str,
        body: str,
    ) -> GmailDraftResult:
        access_token = self._access_token()

        message = EmailMessage()
        message["To"] = to_address
        message["From"] = self.sender_email
        message["Subject"] = subject
        message.set_content(body)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")

        try:
            response = requests.post(
                GMAIL_DRAFTS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"message": {"raw": raw}},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError("Gmail draft request failed") from exc

        if not response.ok:
            raise GmailDraftError(
                f"Gmail returned {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
            draft_id = str(data["id"])
            message_id = data.get("message", {}).get("id")
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError("Gmail returned an invalid draft response") from exc

        return GmailDraftResult(
            draft_id=draft_id,
            message_id=str(message_id) if message_id else None,
        )

    def _access_token(self) -> str:
        try:
            response = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError("Google OAuth token refresh failed") from exc

        if not response.ok:
            raise GmailDraftError(
                f"Google OAuth returned {response.status_code}: {response.text[:500]}"
            )

        try:
            token = str(response.json()["access_token"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError("Google OAuth returned no access token") from exc

        if not token:
            raise GmailDraftError("Google OAuth returned an empty access token")
        return token
