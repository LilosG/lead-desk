from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage

import requests


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"


class GmailDraftError(RuntimeError):
    def __init__(self, message: str, *, uncertain_side_effect: bool = False) -> None:
        super().__init__(message)
        self.uncertain_side_effect = uncertain_side_effect


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

    def _raw_message(
        self,
        *,
        to_address: str,
        subject: str,
        body: str,
        message_id_header: str | None = None,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> str:
        message = EmailMessage()
        message["To"] = to_address
        message["From"] = self.sender_email
        message["Subject"] = subject
        if message_id_header:
            message["Message-ID"] = message_id_header
        message.set_content(body)
        for filename, data in attachments or []:
            message.add_attachment(
                data, maintype="application", subtype="pdf", filename=filename,
            )
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")

    def create_draft(
        self,
        *,
        to_address: str,
        subject: str,
        body: str,
        message_id_header: str,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> GmailDraftResult:
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        raw = self._raw_message(
            to_address=to_address,
            subject=subject,
            body=body,
            message_id_header=message_id_header,
            attachments=attachments,
        )

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
            raise GmailDraftError(
                "Gmail draft request outcome is uncertain",
                uncertain_side_effect=True,
            ) from exc

        if not response.ok:
            raise GmailDraftError(
                f"Gmail returned {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
            draft_id = str(data["id"])
            message_id = data.get("message", {}).get("id")
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError(
                "Gmail accepted the request but returned an invalid draft response",
                uncertain_side_effect=True,
            ) from exc

        return GmailDraftResult(
            draft_id=draft_id,
            message_id=str(message_id) if message_id else None,
        )

    def update_draft(
        self,
        draft_id: str,
        *,
        to_address: str,
        subject: str,
        body: str,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> GmailDraftResult | None:
        """Replace an existing Gmail draft in place.

        Returns None when Gmail reports the recorded draft no longer exists.
        Attachments must be passed again: Gmail replaces the whole message.
        """
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        raw = self._raw_message(
            to_address=to_address,
            subject=subject,
            body=body,
            attachments=attachments,
        )

        try:
            response = requests.put(
                f"{GMAIL_DRAFTS_URL}/{draft_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"id": draft_id, "message": {"raw": raw}},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError(
                "Gmail draft update outcome is uncertain",
                uncertain_side_effect=True,
            ) from exc

        if response.status_code == 404:
            return None
        if not response.ok:
            raise GmailDraftError(
                f"Gmail draft update returned {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
            returned_id = str(data["id"])
            message_id = data.get("message", {}).get("id")
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError(
                "Gmail updated the draft but returned an invalid response",
                uncertain_side_effect=True,
            ) from exc

        return GmailDraftResult(
            draft_id=returned_id,
            message_id=str(message_id) if message_id else None,
        )

    def get_draft(self, draft_id: str) -> GmailDraftResult | None:
        """Return one Gmail draft by id, or None when Gmail says it no longer exists."""
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        try:
            response = requests.get(
                f"{GMAIL_DRAFTS_URL}/{draft_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": "minimal"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError("Gmail draft verification request failed") from exc

        if response.status_code == 404:
            return None
        if not response.ok:
            raise GmailDraftError(
                f"Gmail draft verification returned {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
            returned_id = str(data["id"])
            message_id = data.get("message", {}).get("id")
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError("Gmail returned an invalid draft response") from exc

        return GmailDraftResult(
            draft_id=returned_id,
            message_id=str(message_id) if message_id else None,
        )

    def find_draft_by_message_id(self, message_id_header: str) -> GmailDraftResult | None:
        """Find a previously-created draft by its RFC 5322 Message-ID."""
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        try:
            response = requests.get(
                GMAIL_DRAFTS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "q": f"rfc822msgid:{message_id_header}",
                    "maxResults": 2,
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError("Gmail draft reconciliation request failed") from exc

        if not response.ok:
            raise GmailDraftError(
                f"Gmail draft reconciliation returned {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            drafts = response.json().get("drafts") or []
        except (TypeError, ValueError) as exc:
            raise GmailDraftError("Gmail returned an invalid draft list response") from exc

        if not drafts:
            return None
        if len(drafts) > 1:
            raise GmailDraftError(
                "Gmail returned multiple drafts for one Lead Desk Message-ID; manual review required"
            )

        draft = drafts[0]
        try:
            draft_id = str(draft["id"])
            message_id = draft.get("message", {}).get("id")
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError("Gmail returned an invalid reconciled draft") from exc

        return GmailDraftResult(
            draft_id=draft_id,
            message_id=str(message_id) if message_id else None,
        )

    def _assert_sender_account(self, access_token: str) -> None:
        try:
            response = requests.get(
                GMAIL_PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError("Gmail account verification failed") from exc

        if not response.ok:
            raise GmailDraftError(
                f"Gmail account verification returned {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            account_email = str(response.json()["emailAddress"]).strip().lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError("Gmail account verification returned no email address") from exc

        expected = self.sender_email.strip().lower()
        if account_email != expected:
            raise GmailDraftError(
                f"Gmail OAuth is connected to {account_email}, not {expected}. Reconnect the correct Gmail account before creating drafts."
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
            if "invalid_grant" in response.text:
                raise GmailDraftError(
                    "Gmail access has expired. Go to Settings, click Disconnect, then "
                    "Connect Gmail again. (If this keeps happening every week, the Google "
                    "OAuth app is still in Testing mode; publish it to Production.)"
                )
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