from __future__ import annotations

from app.integrations.gmail import GmailDraftError
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    personal_greeting,
)
from app.integrations.openrouter import CLAIM_TOKEN, OpenRouterError
from app.repositories.outreach_gmail import OutreachGmailRepository
from app.services.outreach import (
    CAN_SPAM_FOOTER,
    MAX_DRAFT_ATTEMPTS,
    PROMPT_VERSION,
    OutreachBlocked,
    OutreachConflict,
    OutreachIntegrationUnavailable,
    OutreachService,
)
from app.services.outreach_similarity import is_too_similar


class OutreachDraftSyncService:
    """Keep Lead Desk and Gmail draft content synchronized while drafts are editable."""

    def __init__(
        self,
        *,
        outreach: OutreachService,
        gmail_repository: OutreachGmailRepository,
    ) -> None:
        self.outreach = outreach
        self.repository = outreach.repository
        self.gmail_repository = gmail_repository

    def save(
        self,
        item_id: str,
        *,
        expected_version: int,
        changes: dict,
    ) -> dict | None:
        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")

        gmail_draft_id = current.get("gmail_draft_id")
        if not gmail_draft_id:
            return self.outreach.update_item(
                item_id,
                changes=changes,
                expected_version=expected_version,
            )

        if self.outreach.gmail is None:
            raise OutreachIntegrationUnavailable(
                "Gmail draft integration is not configured"
            )

        proposed = dict(current)
        proposed.update(changes)
        to_address = (proposed.get("to_address") or "").strip()
        subject = (proposed.get("subject") or "").strip()
        body = proposed.get("body") or ""

        if current["channel"] != "email":
            raise OutreachBlocked("Gmail draft synchronization is available for email only")
        if not to_address or not subject or not body:
            raise OutreachBlocked("recipient, subject, and body are required")
        if self.repository.is_suppressed(to_address):
            raise OutreachBlocked("email address is suppressed")

        content_changed = any(
            proposed.get(key) != current.get(key)
            for key in ("to_address", "subject", "body")
        )

        remote_updated = False
        if content_changed:
            try:
                remote = self.outreach.gmail.update_draft(
                    gmail_draft_id,
                    to_address=to_address,
                    subject=subject,
                    body=body,
                    attachments=self.outreach.audit_attachments(current),
                )
            except GmailDraftError as exc:
                raise OutreachIntegrationUnavailable(str(exc)) from exc

            if remote is None:
                cleared, conflict = self.gmail_repository.clear_stale_draft(
                    item_id,
                    expected_version=expected_version,
                    stale_draft_id=gmail_draft_id,
                )
                if conflict:
                    raise OutreachConflict(
                        "outreach item changed while Gmail draft state was checked"
                    )
                if cleared is None:
                    return None
                return self.outreach.update_item(
                    item_id,
                    changes=changes,
                    expected_version=int(cleared["version"]),
                )
            remote_updated = True

        try:
            updated, conflict = self.repository.update_item(
                item_id,
                changes=changes,
                expected_version=expected_version,
            )
        except Exception:
            if remote_updated:
                self._restore_remote(current)
            raise

        if conflict:
            if remote_updated:
                self._restore_remote(current)
            raise OutreachConflict("outreach item changed since it was loaded")
        return updated

    def regenerate(
        self,
        item_id: str,
        *,
        expected_version: int,
    ) -> dict | None:
        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")

        gmail_draft_id = current.get("gmail_draft_id")
        if not gmail_draft_id:
            return self.outreach.generate_draft(
                item_id,
                expected_version=expected_version,
            )

        if self.outreach.generator is None:
            raise OutreachIntegrationUnavailable(
                "OpenRouter draft generation is not configured"
            )
        if self.outreach.gmail is None:
            raise OutreachIntegrationUnavailable(
                "Gmail draft integration is not configured"
            )

        context = self.repository.draft_context(item_id)
        if context is None:
            return None
        if context["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")
        if context["channel"] != "email":
            raise OutreachBlocked("AI draft generation is available for email only")
        if not context.get("to_address"):
            raise OutreachBlocked("email queue item has no recipient address")
        if self.repository.is_suppressed(context["to_address"]):
            raise OutreachBlocked("email address is suppressed")

        context = self.outreach.ensure_current_audit(context)
        business_name = clean_business_name(context.get("name"))
        visible_claim, claim_signal, verification_status, verification_note = (
            self.outreach._resolve_draft_grounding(
                context,
                business_name=business_name,
            )
        )

        recent_drafts = self.outreach._recent_draft_structures(
            current_item_id=item_id,
        )
        copy = None
        rendered_note = None
        last_similarity = 0.0
        last_match: str | None = None

        for _attempt in range(MAX_DRAFT_ATTEMPTS):
            try:
                candidate = self.outreach.generator.generate_email(
                    business_name=business_name,
                    city=context.get("city"),
                    vertical=context.get("vertical"),
                    verified_claim=visible_claim,
                )
            except OpenRouterError as exc:
                raise OutreachIntegrationUnavailable(str(exc)) from exc

            note = personal_greeting(
                candidate.body.strip(),
                contact_first_name(context.get("to_address"), context.get("name")),
            )
            if visible_claim:
                if note.count(CLAIM_TOKEN) != 1:
                    raise OutreachIntegrationUnavailable(
                        "generated outreach did not preserve the verified finding slot"
                    )
                candidate_rendered = note.replace(CLAIM_TOKEN, visible_claim)
            else:
                if CLAIM_TOKEN in note:
                    raise OutreachIntegrationUnavailable(
                        "generated claim-free outreach inserted an unsupported finding slot"
                    )
                candidate_rendered = note

            too_similar, ratio, matched_business = is_too_similar(
                candidate_rendered,
                candidate_business_name=business_name,
                candidate_verified_claim=visible_claim,
                recent_drafts=recent_drafts,
            )
            if not too_similar:
                copy = candidate
                rendered_note = candidate_rendered
                break
            last_similarity = ratio
            last_match = matched_business

        if copy is None or rendered_note is None:
            matched = last_match or "a recent draft"
            raise OutreachIntegrationUnavailable(
                "generated outreach remained too similar to recent draft structure "
                f"after {MAX_DRAFT_ATTEMPTS} attempts ({last_similarity:.2f} similarity vs {matched}); "
                "no draft was saved"
            )

        body = f"{rendered_note}\n\n{CAN_SPAM_FOOTER}"

        try:
            remote = self.outreach.gmail.update_draft(
                gmail_draft_id,
                to_address=context["to_address"],
                subject=context.get("_audit_subject") or copy.subject,
                body=body,
                attachments=self.outreach.audit_attachments(
                    {"claim_signal": claim_signal, "place_id": context.get("place_id")}
                ),
            )
        except GmailDraftError as exc:
            raise OutreachIntegrationUnavailable(str(exc)) from exc

        if remote is None:
            cleared, conflict = self.gmail_repository.clear_stale_draft(
                item_id,
                expected_version=expected_version,
                stale_draft_id=gmail_draft_id,
            )
            if conflict:
                raise OutreachConflict(
                    "outreach item changed while Gmail draft state was checked"
                )
            if cleared is None:
                return None
            updated, conflict = self.repository.record_generated_draft(
                item_id,
                expected_version=int(cleared["version"]),
                subject=context.get("_audit_subject") or copy.subject,
                body=body,
                claim_signal=claim_signal,
                verification_status=verification_status,
                verification_note=verification_note,
                generation_model=copy.model,
                prompt_version=PROMPT_VERSION,
            )
            if conflict:
                raise OutreachConflict(
                    "outreach item changed while the draft was being generated"
                )
            return updated

        updated, conflict = self.gmail_repository.record_synced_generated_draft(
            item_id,
            expected_version=expected_version,
            expected_gmail_draft_id=gmail_draft_id,
            subject=context.get("_audit_subject") or copy.subject,
            body=body,
            claim_signal=claim_signal,
            verification_status=verification_status,
            verification_note=verification_note,
            generation_model=copy.model,
            prompt_version=PROMPT_VERSION,
            gmail_message_id=remote.message_id,
        )
        if conflict:
            self._restore_remote(current)
            raise OutreachConflict(
                "outreach item changed while the regenerated Gmail draft was being saved"
            )
        return updated

    def _restore_remote(self, item: dict) -> None:
        draft_id = item.get("gmail_draft_id")
        to_address = item.get("to_address")
        subject = item.get("subject")
        body = item.get("body")
        if (
            self.outreach.gmail is None
            or not draft_id
            or not to_address
            or not subject
            or not body
        ):
            return
        try:
            self.outreach.gmail.update_draft(
                draft_id,
                to_address=to_address,
                subject=subject,
                body=body,
                attachments=self.outreach.audit_attachments(item),
            )
        except GmailDraftError:
            # The original request already failed; preserve the primary error.
            pass