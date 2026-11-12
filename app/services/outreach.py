from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from uuid import UUID, uuid4

from app.campaigns import DEFAULT_CAMPAIGN, EV_PERMITS, get_campaign
from app.integrations.gmail import GmailDraftClient, GmailDraftError
from app.integrations.openrouter import CLAIM_TOKEN, OpenRouterClient, OpenRouterError
from app.outreach_policy import OUTREACHABLE_SIGNALS, client_facing_claim
from app.repositories.outreach import OutreachOperationLocked, OutreachRepository
from app.repositories.outreach_evidence import OutreachEvidenceRepository
from app.schemas.audit_reports import REPORT_VERSION
from app.services.outreach_audit_copy import (
    audit_email_paragraph,
    clean_business_name,
    contact_first_name,
    personal_greeting,
)
from app.services import permit_offer, seo_offer
from app.services.email_angles import BEST, ROTATE, is_known, resolve_angle
from app.services.outreach_evidence import RecipientEvidence, recipient_finding_block
from app.services.outreach_similarity import is_too_similar
from app.services.outreach_verification import OutreachClaimVerifier


PROMPT_VERSION = "outreach-v12"
FIXED_COPY = "fixed copy"
# Days to wait after the previous email before each follow-up.
FOLLOW_UP_GAPS = {2: 3, 3: 4}
# Reports older than this version lack the checks the email and PDF now rely on.
CURRENT_AUDIT_VERSION = REPORT_VERSION
MAX_DRAFT_ATTEMPTS = 3
# Signature plus a working opt-out. The postal line is optional and comes from
# OUTREACH_POSTAL_ADDRESS (e.g. a PO box or virtual mailbox); CAN-SPAM expects
# a valid postal address on commercial email, so set one before sending at volume.
def _footer(postal_address: str | None = None) -> str:
    lines = ["Mike Prickett", "Lilos Growth", "lilosgrowth.com"]
    if postal_address and postal_address.strip():
        lines.append(" ".join(postal_address.split()))
    return "\n".join(lines) + (
        "\n\nIf you'd rather not hear from me, just reply \"no thanks\" and I won't reach out again."
    )


def _configured_postal_address() -> str | None:
    import os
    return os.environ.get("OUTREACH_POSTAL_ADDRESS") or None


CAN_SPAM_FOOTER = _footer(_configured_postal_address())
_EMAIL_SHAPE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.I)


def looks_like_email(address: str | None) -> bool:
    return bool(_EMAIL_SHAPE.fullmatch((address or "").strip()))


def uses_old_copy(item: dict) -> bool:
    """A draft written before the current emails. Older rows have no angle behind them."""
    current = {"ev_permit_offer": permit_offer.PROMPT_VERSION, "audit_report": seo_offer.PROMPT_VERSION}
    expected = current.get(item.get("claim_signal"))
    version = item.get("generation_prompt_version")
    return bool(expected and version and version != expected)


class OutreachConflict(RuntimeError):
    pass


class OutreachBlocked(RuntimeError):
    pass


class OutreachIntegrationUnavailable(RuntimeError):
    pass


class OutreachService:
    def __init__(
        self,
        repository: OutreachRepository,
        *,
        evidence_repository: OutreachEvidenceRepository | None = None,
        generator: OpenRouterClient | None = None,
        gmail: GmailDraftClient | None = None,
        verifier: OutreachClaimVerifier | None = None,
        generation_model: str | None = None,
        gmail_sender_email: str | None = None,
        audit_builder: Callable[[str], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.evidence_repository = evidence_repository
        self.generator = generator
        self.gmail = gmail
        self.verifier = verifier or OutreachClaimVerifier()
        self.generation_model = generation_model
        self.gmail_sender_email = gmail_sender_email
        # Callable(place_id) that builds a default audit report.
        self.audit_builder = audit_builder

    def integration_status(self) -> dict:
        return {
            "openrouter_configured": self.generator is not None,
            "openrouter_model": self.generation_model,
            "gmail_configured": self.gmail is not None,
            "gmail_sender_email": self.gmail_sender_email,
            "send_enabled": False,
        }

    def list_candidates(self, limit: int = 100) -> dict:
        items = self.repository.list_candidates(limit=limit)
        return {"items": items, "total": len(items)}

    def candidate_readiness(
        self, place_id: str, campaign_key: str = DEFAULT_CAMPAIGN,
    ) -> dict | None:
        item = self.repository.candidate_readiness(place_id, campaign_key)
        if item is None:
            return None

        review_count = int(item.get("review_count") or 0)
        email = item.get("email")
        phone = item.get("phone")
        suppressed = bool(item.get("suppressed"))
        already_queued = bool(item.get("already_queued"))

        reasons: list[str] = []

        if item.get("needs_manual_check"):
            reasons.append("Manual verification is required before outreach.")
        if not email and not phone:
            reasons.append("No reachable email address or phone number is available.")
        if email and suppressed:
            reasons.append("The prospect email address is suppressed.")
        if already_queued:
            reasons.append("Prospect is already in the outreach queue.")

        preferred_channel = "email" if email else ("phone" if phone else None)

        return {
            "eligible": not reasons,
            "reasons": reasons,
            "preferred_channel": preferred_channel,
            "review_count": review_count,
            "strong_review_base": review_count >= 15,
            "confirmed_trading": bool(item.get("confirmed_trading")),
            "established": bool(item.get("established")),
            "needs_manual_check": bool(item.get("needs_manual_check")),
            "suppressed": suppressed,
            "already_queued": already_queued,
        }

    def list_items(self, status: str | None = None) -> dict:
        items, total = self.repository.list_items(status=status)
        return {"items": items, "total": total}

    def cooldown_block(self, place_id: str, campaign_key: str | None) -> str | None:
        """Why this business can't be contacted in this campaign yet, if so."""
        recent = self.repository.recent_contact(place_id, campaign_key or DEFAULT_CAMPAIGN)
        if not recent:
            return None
        until = recent["until"]
        return f"Already in {recent['campaign']} outreach. Wait until {until:%b} {until.day}."

    def create_item(
        self,
        place_id: str,
        channel: str,
        to_address: str | None,
        campaign_key: str = DEFAULT_CAMPAIGN,
    ) -> dict | None:
        prospect = self.repository.prospect_context(place_id)
        if prospect is None:
            return None

        if self.repository.place_opted_out(place_id):
            raise OutreachBlocked("this business is on the do-not-contact list")

        if channel == "email":
            address = to_address or ((prospect.get("emails_found") or [None])[0])
            if not address:
                raise OutreachBlocked("prospect has no usable email address")
            if self.repository.is_suppressed(address):
                raise OutreachBlocked("email address is suppressed")
            to_address = address
        elif channel == "phone":
            if not prospect.get("phone"):
                raise OutreachBlocked("prospect has no phone number")
            to_address = to_address or prospect["phone"]

        return self.repository.create_item(place_id, channel, to_address, campaign_key)

    def update_item(self, item_id: str, *, changes: dict, expected_version: int) -> dict | None:
        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")

        for required_field in ("status", "verification_status"):
            if required_field in changes and changes[required_field] is None:
                raise OutreachBlocked(f"{required_field} cannot be null")

        effective_address = changes.get("to_address", current.get("to_address"))
        if current["channel"] == "email" and self.repository.is_suppressed(effective_address):
            raise OutreachBlocked("email address is suppressed")

        if current.get("gmail_draft_id") and any(
            key in changes and changes[key] != current.get(key)
            for key in ("to_address", "subject", "body")
        ):
            raise OutreachBlocked(
                "content is locked because a Gmail draft already exists for this queue item"
            )

        next_status = changes.get("status", current["status"])
        verification = changes.get("verification_status", current["verification_status"])
        subject = changes.get("subject", current.get("subject"))
        body = changes.get("body", current.get("body"))

        if next_status in {"draft_ready", "approved"}:
            if current["channel"] == "email" and (not subject or not body):
                raise OutreachBlocked("email draft requires both subject and body")
            if verification not in {"verified", "not_required"}:
                raise OutreachBlocked(
                    "claim verification is required before a draft can be ready"
                )

        try:
            updated, conflict = self.repository.update_item(
                item_id,
                changes=changes,
                expected_version=expected_version,
            )
        except OutreachOperationLocked as exc:
            raise OutreachBlocked(str(exc)) from exc
        if conflict:
            raise OutreachConflict("outreach item changed since it was loaded")
        return updated

    @staticmethod
    def _client_facing_verification_context(context: dict) -> dict:
        findings = [
            finding
            for finding in (context.get("findings") or [])
            if finding.get("signal") in OUTREACHABLE_SIGNALS
        ]
        return {**context, "findings": findings}

    @staticmethod
    def _audit_report_grounding(
        context: dict,
        *,
        business_name: str,
    ) -> tuple[str, str, str, str] | None:
        snapshot = context.get("audit_snapshot")
        if not isinstance(snapshot, dict):
            return None
        rendered = audit_email_paragraph(snapshot, business_name)
        if rendered is None:
            return None
        paragraph, subject = rendered
        # Subject follows the lead finding; both draft paths read it back.
        context["_audit_subject"] = subject

        note = "Grounded in the latest generated Local Visibility Audit"
        if context.get("audit_source_checked_at"):
            note += f" using evidence dated {context['audit_source_checked_at']}"
        note += "."
        return paragraph, "audit_report", "not_required", note

    def audit_attachments(self, item: dict | None) -> list[tuple[str, bytes]] | None:
        """The audit PDF for drafts that say it is attached; None otherwise.

        Rows from before angles have no angle, and their copy says it's attached.

        The email copy says the audit is attached, so the draft must really
        carry it. Gmail replaces the whole message on update, so every draft
        write for an audit-grounded item passes this again.
        """
        if not item or item.get("claim_signal") != "audit_report" or not item.get("place_id"):
            return None
        if item.get("angle") is not None and item.get("angle") not in seo_offer.ATTACHES_AUDIT:
            return None
        lookup = getattr(self.repository, "latest_audit_report", None)
        if lookup is None:
            return None
        report = lookup(item["place_id"])
        if not report or not isinstance(report.get("snapshot"), dict):
            return None
        from app.services.audit_report_pdf import render_audit_report_pdf

        name = clean_business_name(report.get("name"))
        safe = "".join(ch for ch in name if ch.isalnum() or ch in " &-").strip() or "Audit"
        return [(f"{safe} - Local Visibility Audit.pdf", render_audit_report_pdf(report))]

    def ensure_current_audit(self, context: dict) -> dict:
        """Every email is written from, and attaches, a current audit report."""
        snapshot = context.get("audit_snapshot")
        version = snapshot.get("report_version", 0) if isinstance(snapshot, dict) else 0
        if self.audit_builder is None or version >= CURRENT_AUDIT_VERSION:
            return context
        self.audit_builder(context["place_id"])
        return self.repository.draft_context(context["id"]) or context

    def _resolve_draft_grounding(
        self,
        context: dict,
        *,
        business_name: str,
    ) -> tuple[str | None, str | None, str, str]:
        audit = self._audit_report_grounding(context, business_name=business_name)
        if audit is not None:
            return audit

        verification_context = self._client_facing_verification_context(context)
        claim = self.verifier.verify(verification_context)
        technical_claim = client_facing_claim(claim.signal, claim.text)
        if not technical_claim:
            return None, None, claim.status, claim.note

        evidence = None
        if self.evidence_repository is not None:
            evidence = RecipientEvidence.from_row(
                self.evidence_repository.get(context["place_id"])
            )
        visible_claim = recipient_finding_block(
            business_name=business_name,
            technical_claim=technical_claim,
            evidence=evidence,
        )
        return visible_claim, claim.signal, claim.status, claim.note

    def _recent_draft_structures(
        self,
        *,
        current_item_id: str,
    ) -> list[tuple[str | None, str, str | None]]:
        items = self.repository.recent_generated_drafts(
            limit=25,
            exclude_id=UUID(current_item_id),
        )
        recent: list[tuple[str | None, str, str | None]] = []
        for item in items:
            visible_claim = client_facing_claim(
                item.get("claim_signal"),
                item.get("verification_note") or "verified",
            )
            recent.append(
                (
                    item.get("name"),
                    item["body"],
                    visible_claim,
                )
            )
        return recent

    def write_ev_draft(self, context: dict, angle: str | None = None) -> dict:
        """The Permit Packets email, refused unless its facts check out."""
        if context.get("vertical") != "electrician":
            raise OutreachBlocked("Permit Packets is only for electricians.")
        evidence = permit_offer.permit_evidence(context)
        if angle == BEST:
            angle = ROTATE  # Permit emails carry no audit or mockup.
        chosen = resolve_angle(EV_PERMITS, context["place_id"], angle, context.get("angle"))
        if not is_known(EV_PERMITS, chosen):
            raise OutreachBlocked(f"Unknown email angle: {chosen}")
        written = permit_offer.write_email(context, chosen)
        return {
            "subject": written["subject"],
            "body": f"{written['body']}\n\n{CAN_SPAM_FOOTER}",
            "claim_signal": get_campaign(context.get("campaign_key")).claim_signal,
            "verification_status": "verified",
            "verification_note": (f"Permit work found: {evidence}." if evidence else "")
                                  + f" {written['note']}".rstrip(),
            "generation_model": FIXED_COPY,
            "prompt_version": permit_offer.PROMPT_VERSION,
            "angle": chosen,
        }

    def write_seo_draft(self, context: dict, angle: str | None = None) -> dict | None:
        """The audit-led email. None when the audit gives it nothing to say."""
        campaign = get_campaign(context.get("campaign_key")).key
        if angle == BEST:
            angle = seo_offer.FREE_HOMEPAGE if context.get("demo_url") else seo_offer.AI_SEARCH
        chosen = resolve_angle(campaign, context["place_id"], angle, context.get("angle"))
        if not is_known(campaign, chosen):
            raise OutreachBlocked(f"Unknown email angle: {chosen}")
        written = seo_offer.write_email(context, chosen)
        if written is None:
            return None
        note = "Grounded in the latest generated Local Visibility Audit"
        if context.get("audit_source_checked_at"):
            note += f" using evidence dated {context['audit_source_checked_at']}"
        return {
            "subject": written["subject"],
            "body": f"{written['body']}\n\n{CAN_SPAM_FOOTER}",
            "claim_signal": "audit_report",
            "verification_status": "not_required",
            "verification_note": f"{note}. {written['note']}".strip(),
            "generation_model": FIXED_COPY,
            "prompt_version": seo_offer.PROMPT_VERSION,
            "angle": written["angle"],
        }

    def write_fixed_copy(self, context: dict, angle: str | None = None) -> dict | None:
        if get_campaign(context.get("campaign_key")).uses_audit:
            return self.write_seo_draft(context, angle)
        return self.write_ev_draft(context, angle)

    def generate_draft(
        self, item_id: str, *, expected_version: int, angle: str | None = None,
    ) -> dict | None:
        context = self.repository.draft_context(item_id)
        if context is None:
            return None
        uses_audit = get_campaign(context.get("campaign_key")).uses_audit
        if context["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")
        if context["channel"] != "email":
            raise OutreachBlocked(
                "AI draft generation is currently available for email only"
            )
        if uses_audit:
            context = self.ensure_current_audit(context)

        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")
        if current.get("gmail_draft_id"):
            raise OutreachBlocked(
                "a Gmail draft already exists for this queue item; create a new queue item before regenerating"
            )
        if not context.get("to_address"):
            raise OutreachBlocked("email queue item has no recipient address")
        if self.repository.is_suppressed(context["to_address"]):
            raise OutreachBlocked("email address is suppressed")

        written = self.write_fixed_copy(context, angle)
        if written is not None:
            try:
                updated, conflict = self.repository.record_generated_draft(
                    item_id, expected_version=expected_version, **written,
                )
            except OutreachOperationLocked as exc:
                raise OutreachBlocked(str(exc)) from exc
            if conflict:
                raise OutreachConflict("outreach item changed while the draft was being generated")
            return updated

        if self.generator is None:
            raise OutreachIntegrationUnavailable(
                "OpenRouter draft generation is not configured"
            )
        business_name = clean_business_name(context.get("name"))
        visible_claim, claim_signal, verification_status, verification_note = (
            self._resolve_draft_grounding(
                context,
                business_name=business_name,
            )
        )

        recent_drafts = self._recent_draft_structures(current_item_id=item_id)
        copy = None
        rendered_note = None
        last_similarity = 0.0
        last_match: str | None = None

        for _attempt in range(MAX_DRAFT_ATTEMPTS):
            try:
                candidate = self.generator.generate_email(
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
            updated, conflict = self.repository.record_generated_draft(
                item_id,
                expected_version=expected_version,
                subject=context.get("_audit_subject") or copy.subject,
                body=body,
                claim_signal=claim_signal,
                verification_status=verification_status,
                verification_note=verification_note,
                generation_model=copy.model,
                prompt_version=PROMPT_VERSION,
            )
        except OutreachOperationLocked as exc:
            raise OutreachBlocked(str(exc)) from exc
        if conflict:
            raise OutreachConflict(
                "outreach item changed while the draft was being generated"
            )
        return updated

    def create_gmail_draft(self, item_id: str, *, expected_version: int) -> dict | None:
        if self.gmail is None:
            raise OutreachIntegrationUnavailable(
                "Gmail draft integration is not configured"
            )

        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current["version"] != expected_version:
            raise OutreachConflict("outreach item changed since it was loaded")
        if current["channel"] != "email":
            raise OutreachBlocked("Gmail drafts are available for email queue items only")
        if current.get("gmail_draft_id"):
            raise OutreachBlocked("a Gmail draft already exists for this queue item")
        if current.get("to_address") and not looks_like_email(current["to_address"]):
            raise OutreachBlocked("That isn't a complete email address. Fix it in the To field first.")
        if uses_old_copy(current):
            raise OutreachBlocked("This draft has the old email. Click Regenerate draft first.")
        if current["status"] not in {"draft_ready", "approved"}:
            raise OutreachBlocked(
                "mark the draft ready after human review before creating it in Gmail"
            )
        if current["verification_status"] not in {"verified", "not_required"}:
            raise OutreachBlocked(
                "claim verification is required before creating a Gmail draft"
            )
        if not current.get("to_address") or not current.get("subject") or not current.get("body"):
            raise OutreachBlocked(
                "recipient, subject, and body are required for a Gmail draft"
            )
        if self.repository.is_suppressed(current["to_address"]):
            raise OutreachBlocked("email address is suppressed")
        waiting = self.cooldown_block(current["place_id"], current.get("campaign_key"))
        if waiting:
            raise OutreachBlocked(waiting)

        # Build the audit PDF before anything is recorded: if it fails, the
        # item must not be left in a "pending" Gmail state that blocks retries.
        try:
            attachments = self.audit_attachments(current)
        except Exception as exc:
            raise OutreachBlocked(
                f"couldn't build the audit PDF to attach ({exc}); rebuild the audit report and try again"
            ) from exc

        if "audit" in current["body"].lower() and not attachments:
            raise OutreachBlocked(
                "this draft mentions an attached audit but has none; regenerate the draft first"
            )

        message_id_header = f"<{uuid4()}@lead-desk.lilosgrowth.com>"
        try:
            operation, conflict = self.repository.begin_gmail_draft_operation(
                item_id,
                expected_version=expected_version,
                message_id_header=message_id_header,
            )
        except OutreachOperationLocked as exc:
            raise OutreachBlocked(str(exc)) from exc
        if conflict:
            raise OutreachConflict("outreach item changed since it was loaded")
        if operation is None:
            return None

        if not operation["created_now"]:
            if operation["state"] == "created":
                return self.repository.get_item(item_id)
            if operation["state"] == "pending":
                try:
                    recovered = self.gmail.find_draft_by_message_id(
                        operation["message_id_header"]
                    )
                except GmailDraftError as exc:
                    raise OutreachIntegrationUnavailable(str(exc)) from exc
                if recovered is not None:
                    return self.repository.complete_gmail_draft_operation(
                        operation["id"],
                        draft_id=recovered.draft_id,
                        message_id=recovered.message_id,
                    )
                # Gmail confirmed no draft carries this Message-ID, so the
                # earlier attempt never landed: retrying cannot duplicate it.
                self.repository.record_gmail_operation_error(
                    operation["id"],
                    error_message="previous attempt not found in Gmail; retrying",
                    uncertain=False,
                )
                operation = {**operation, "state": "failed"}
            if operation["state"] == "failed":
                reopened = self.repository.reopen_gmail_draft_operation(operation["id"])
                if reopened is None:
                    raise OutreachIntegrationUnavailable(
                        "Gmail draft operation could not be reopened safely"
                    )
                operation = {**reopened, "created_now": False}

        try:
            result = self.gmail.create_draft(
                to_address=current["to_address"],
                subject=current["subject"],
                body=current["body"],
                message_id_header=operation["message_id_header"],
                attachments=attachments,
            )
        except GmailDraftError as exc:
            self.repository.record_gmail_operation_error(
                operation["id"],
                error_message=str(exc),
                uncertain=exc.uncertain_side_effect,
            )
            if exc.uncertain_side_effect:
                raise OutreachIntegrationUnavailable(
                    "Gmail draft request outcome is uncertain; the durable operation was preserved for reconciliation and no retry will create a duplicate"
                ) from exc
            raise OutreachIntegrationUnavailable(str(exc)) from exc

        return self.repository.complete_gmail_draft_operation(
            operation["id"],
            draft_id=result.draft_id,
            message_id=result.message_id,
            thread_id=result.thread_id,
        )

    def draft_follow_up(self, item_id: str, now: datetime | None = None) -> dict | None:
        """The next email in the sequence, as a Gmail draft in the first email's thread."""
        if self.gmail is None:
            raise OutreachIntegrationUnavailable("Gmail draft integration is not configured")
        item = self.repository.follow_up_context(item_id)
        if item is None:
            return None
        if item["channel"] != "email" or item["status"] != "contacted" or item["suppressed"]:
            raise OutreachBlocked("Follow-ups only go to contacted leads who haven't replied.")
        sent = [f for f in item["follow_ups"] if f.get("gmail_draft_id")]
        step = len(sent) + 2
        if step not in FOLLOW_UP_GAPS:
            raise OutreachBlocked("This lead has had every follow-up.")
        if sent and not sent[-1].get("sent_at"):
            raise OutreachBlocked("The last follow-up is still in Gmail. Send it first.")
        previous = (datetime.fromisoformat(sent[-1]["sent_at"]) if sent else item["contacted_at"])
        due = previous + timedelta(days=FOLLOW_UP_GAPS[step])
        if (now or datetime.now(timezone.utc)) < due:
            raise OutreachBlocked(f"This follow-up is due on {due:%b} {due.day}.")

        offer = permit_offer if item["campaign_key"] == EV_PERMITS else seo_offer
        subject = item["subject"] or ""
        follow_up = self.repository.begin_follow_up(
            item_id, step,
            subject=subject if subject.lower().startswith("re:") else f"Re: {subject}",
            body=f"{offer.write_follow_up(item, step)}\n\n{CAN_SPAM_FOOTER}",
            message_id_header=f"<{uuid4()}@lead-desk.lilosgrowth.com>",
        )
        try:
            result = self.gmail.find_draft_by_message_id(follow_up["message_id_header"]) or self.gmail.create_draft(
                to_address=item["to_address"],
                subject=follow_up["subject"],
                body=follow_up["body"],
                message_id_header=follow_up["message_id_header"],
                in_reply_to=item.get("first_message_id"),
                thread_id=item.get("gmail_thread_id"),
            )
        except GmailDraftError as exc:
            raise OutreachIntegrationUnavailable(str(exc)) from exc
        self.repository.complete_follow_up(
            follow_up["id"], draft_id=result.draft_id, message_id=result.message_id,
            place_id=item["place_id"], item_id=item_id, step=step,
        )
        return {"step": step, "gmail_message_id": result.message_id}
