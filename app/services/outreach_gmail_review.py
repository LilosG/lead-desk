from __future__ import annotations

from app.integrations.gmail import GmailDraftClient, GmailDraftError
from app.repositories.outreach import OutreachRepository
from app.repositories.outreach_gmail import OutreachGmailRepository
from app.services.outreach import (
    OutreachBlocked,
    OutreachConflict,
    OutreachIntegrationUnavailable,
    OutreachService,
)


class OutreachGmailReviewService:
    def __init__(
        self,
        *,
        outreach: OutreachService,
        repository: OutreachRepository,
        gmail_repository: OutreachGmailRepository,
        gmail: GmailDraftClient,
    ) -> None:
        self.outreach = outreach
        self.repository = repository
        self.gmail_repository = gmail_repository
        self.gmail = gmail

    def review_and_create(
        self,
        item_id: str,
        *,
        expected_version: int,
        to_address: str,
        subject: str,
        body: str,
    ) -> dict | None:
        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")
        if current["channel"] != "email":
            raise OutreachBlocked("Gmail drafts are available for email queue items only")

        existing_draft_id = current.get("gmail_draft_id")
        if existing_draft_id:
            try:
                remote = self.gmail.get_draft(existing_draft_id)
            except GmailDraftError as exc:
                raise OutreachIntegrationUnavailable(str(exc)) from exc
            if remote is not None:
                return current

            cleared, conflict = self.gmail_repository.clear_stale_draft(
                item_id,
                expected_version=expected_version,
                stale_draft_id=existing_draft_id,
            )
            if conflict:
                raise OutreachConflict("outreach item changed while Gmail draft state was being checked")
            if cleared is None:
                return None
            current = cleared
            expected_version = int(cleared["version"])

        if current.get("verification_status") not in {"verified", "not_required"}:
            raise OutreachBlocked(
                "Gmail does not contain the recorded draft. Lead Desk removed the stale Gmail lock. Regenerate the outreach draft so verification is current, then create the Gmail draft again."
                if existing_draft_id
                else "Generate and review the outreach draft before creating it in Gmail."
            )

        updated = self.outreach.update_item(
            item_id,
            changes={
                "to_address": to_address,
                "subject": subject,
                "body": body,
                "status": "draft_ready",
            },
            expected_version=expected_version,
        )
        if updated is None:
            return None

        return self.outreach.create_gmail_draft(
            item_id,
            expected_version=int(updated["version"]),
        )
