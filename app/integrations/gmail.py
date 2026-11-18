from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
import re
from typing import Any

import requests


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


class GmailDraftError(RuntimeError):
    def __init__(self, message: str, *, uncertain_side_effect: bool = False) -> None:
        super().__init__(message)
        self.uncertain_side_effect = uncertain_side_effect


class GmailReadScopeMissingError(GmailDraftError):
    pass


@dataclass(frozen=True)
class GmailDraftResult:
    draft_id: str
    message_id: str | None
    thread_id: str | None = None


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
        in_reply_to: str | None = None,
    ) -> str:
        message = EmailMessage()
        message["To"] = to_address
        message["From"] = self.sender_email
        message["Subject"] = subject
        if message_id_header:
            message["Message-ID"] = message_id_header
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to
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
        in_reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> GmailDraftResult:
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        raw = self._raw_message(
            to_address=to_address,
            subject=subject,
            body=body,
            message_id_header=message_id_header,
            attachments=attachments,
            in_reply_to=in_reply_to,
        )
        message: dict[str, str] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id

        try:
            response = requests.post(
                GMAIL_DRAFTS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"message": message},
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
            gmail_thread_id = data.get("message", {}).get("threadId")
        except (KeyError, TypeError, ValueError) as exc:
            raise GmailDraftError(
                "Gmail accepted the request but returned an invalid draft response",
                uncertain_side_effect=True,
            ) from exc

        return GmailDraftResult(
            draft_id=draft_id,
            message_id=str(message_id) if message_id else None,
            thread_id=str(gmail_thread_id) if gmail_thread_id else None,
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

    def list_draft_ids(self) -> set[str]:
        """Every draft id currently in the mailbox. gmail.compose allows this."""
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        ids: set[str] = set()
        page_token: str | None = None
        while True:
            params: dict[str, str | int] = {"maxResults": 500}
            if page_token:
                params["pageToken"] = page_token
            try:
                response = requests.get(
                    GMAIL_DRAFTS_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                raise GmailDraftError("Gmail draft list request failed") from exc
            if not response.ok:
                raise GmailDraftError(
                    f"Gmail draft list returned {response.status_code}: {response.text[:500]}"
                )
            try:
                data = response.json()
                ids.update(str(d["id"]) for d in data.get("drafts") or [])
            except (KeyError, TypeError, ValueError) as exc:
                raise GmailDraftError("Gmail returned an invalid draft list") from exc
            page_token = data.get("nextPageToken")
            if not page_token:
                return ids

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


    @staticmethod
    def _decode_b64url(data: str) -> str:
        if not data:
            return ""
        padded = data + "=" * (-len(data) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
        except Exception:
            return ""

    @classmethod
    def _extract_body_text(cls, payload: dict[str, Any]) -> str:
        plain_parts: list[str] = []
        html_parts: list[str] = []

        def walk(part: dict[str, Any]) -> None:
            mime = str(part.get("mimeType") or "").lower()
            body_data = (part.get("body") or {}).get("data")
            if body_data and mime == "text/plain":
                plain_parts.append(cls._decode_b64url(str(body_data)))
            elif body_data and mime == "text/html":
                html_parts.append(cls._decode_b64url(str(body_data)))
            for child in part.get("parts") or []:
                if isinstance(child, dict):
                    walk(child)

        walk(payload)
        if plain_parts:
            return "\n".join(plain_parts).strip()
        if html_parts:
            raw_html = "\n".join(html_parts)
            return re.sub(r"<[^>]+>", " ", raw_html).strip()
        return ""

    def list_inbound_replies(self, *, days: int = 90) -> list[dict[str, Any]]:
        """Return inbound messages (including bounces/OOO) with extracted text for classification."""
        access_token = self._access_token()
        self._assert_sender_account(access_token)
        msg_ids: list[str] = []
        page_token: str | None = None
        while len(msg_ids) < 1000:
            params: dict[str, str | int] = {
                "q": f"-from:me -in:drafts -in:spam -in:trash newer_than:{days}d",
                "maxResults": 500,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                response = requests.get(
                    GMAIL_MESSAGES_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                raise GmailDraftError("Gmail message list request failed") from exc
            if response.status_code == 403 and "SCOPE_INSUFFICIENT" in (response.text or ""):
                raise GmailReadScopeMissingError("Gmail read permission not granted yet")
            if not response.ok:
                raise GmailDraftError(
                    f"Gmail message list returned {response.status_code}: {response.text[:500]}"
                )
            data = response.json()
            msg_ids.extend(str(m["id"]) for m in data.get("messages") or [] if m.get("id"))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        if not msg_ids:
            return []

        own_email = self.sender_email.strip().lower()
        email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

        def fetch_msg(mid: str) -> dict[str, Any] | None:
            try:
                res = requests.get(
                    f"{GMAIL_MESSAGES_URL}/{mid}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"format": "full"},
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException:
                return None
            if not res.ok:
                return None
            data = res.json()
            payload = data.get("payload") or {}
            headers = {
                str(h.get("name", "")).lower(): str(h.get("value", ""))
                for h in (payload.get("headers") or [])
            }
            sender = parseaddr(headers.get("from", ""))[1].strip().lower()
            if not sender or sender == own_email:
                return None

            subject = headers.get("subject", "").strip()
            snippet = str(data.get("snippet") or "").strip()
            body_text = self._extract_body_text(payload) or snippet
            # Strip quoted reply history so the classifier focuses on the new message
            clean_lines = []
            for line in body_text.splitlines():
                stripped = line.strip()
                if stripped.startswith(">") or re.match(r"^On .+ wrote:$", stripped):
                    break
                clean_lines.append(line)
            clean_body = ("\n".join(clean_lines).strip() or body_text)[:1500]

            failed_rcpts = headers.get("x-failed-recipients", "")
            is_bounce_header = (
                any(b in sender for b in ("mailer-daemon@", "postmaster@"))
                or bool(failed_rcpts.strip())
                or subject.lower().startswith(("delivery status notification", "undeliverable:", "mail delivery failed"))
            )
            auto_sub = headers.get("auto-submitted", "").strip().lower()
            is_auto_reply_header = (
                (bool(auto_sub) and auto_sub != "no")
                or bool(headers.get("x-autoreply"))
                or bool(headers.get("x-auto-response-suppress"))
            )

            mentioned = {
                m.lower()
                for m in email_re.findall(f"{failed_rcpts}\n{snippet}\n{body_text[:2000]}")
                if m.lower() != own_email
            }

            return {
                "thread_id": str(data.get("threadId") or ""),
                "message_id": mid,
                "sender_email": sender,
                "subject": subject,
                "snippet": snippet,
                "body": clean_body,
                "is_bounce_header": is_bounce_header,
                "is_auto_reply_header": is_auto_reply_header,
                "mentioned_emails": sorted(mentioned),
            }

        with ThreadPoolExecutor(max_workers=10) as pool:
            return [r for r in pool.map(fetch_msg, msg_ids) if r is not None]

    def _assert_sender_account(self, access_token: str) -> None:
        try:
            response = requests.get(
                GMAIL_PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GmailDraftError("Gmail account verification failed") from exc

        if getattr(response, "status_code", None) == 403 and "SCOPE_INSUFFICIENT" in (getattr(response, "text", "") or ""):
            raise GmailDraftError(
                "Gmail is connected without permission to create drafts. Go to Settings, "
                "click Disconnect, then Connect Gmail and make sure the box for "
                "\"Manage drafts and send emails\" is ticked on Google's screen."
            )
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