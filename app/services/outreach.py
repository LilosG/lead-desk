from __future__ import annotations

from uuid import uuid4

from app.integrations.gmail import GmailDraftClient, GmailDraftError
from app.integrations.openrouter import OpenRouterClient, OpenRouterError
from app.repositories.outreach import OutreachOperationLocked, OutreachRepository
from app.services.outreach_verification import OutreachClaimVerifier


PROMPT_VERSION = "outreach-v2"
CAN_SPAM_FOOTER = (
    "Mike\n"
    "LILOs Growth\n"
    "1440 Columbia St\n"
    "San Diego, CA 92101\n\n"
    "If you'd rather I not reach out again, just reply and I'll make sure I don't."
)


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
        generator: OpenRouterClient | None = None,
        gmail: GmailDraftClient | None = None,
        verifier: OutreachClaimVerifier | None = None,
        generation_model: str | None = None,
        gmail_sender_email: str | None = None,
    ) -> None:
        self.repository = repository
        self.generator = generator
        self.gmail = gmail
        self.verifier = verifier or OutreachClaimVerifier()
        self.generation_model = generation_model
        self.gmail_sender_email = gmail_sender_email

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
        return {'items': items, 'total': len(items)}

    def list_items(self, status: str | None = None) -> dict:
        items, total = self.repository.list_items(status=status)
        return {'items': items, 'total': total}

    def create_item(self, place_id: str, channel: str, to_address: str | None) -> dict | None:
        prospect = self.repository.prospect_context(place_id)
        if prospect is None:
            return None

        if channel == 'email':
            address = to_address or ((prospect.get('emails_found') or [None])[0])
            if not address:
                raise OutreachBlocked('prospect has no usable email address')
            if self.repository.is_suppressed(address):
                raise OutreachBlocked('email address is suppressed')
            to_address = address
        elif channel == 'phone':
            if not prospect.get('phone'):
                raise OutreachBlocked('prospect has no phone number')
            to_address = to_address or prospect['phone']

        return self.repository.create_item(place_id, channel, to_address)

    def update_item(self, item_id: str, *, changes: dict, expected_version: int) -> dict | None:
        current = self.repository.get_item(item_id)
        if current is None:
            return None

        if current['version'] != expected_version:
            raise OutreachConflict('outreach item changed since it was loaded')

        for required_field in ('status', 'verification_status'):
            if required_field in changes and changes[required_field] is None:
                raise OutreachBlocked(f'{required_field} cannot be null')

        effective_address = changes.get('to_address', current.get('to_address'))
        if current['channel'] == 'email' and self.repository.is_suppressed(effective_address):
            raise OutreachBlocked('email address is suppressed')

        if current.get('gmail_draft_id') and any(
            key in changes and changes[key] != current.get(key)
            for key in ('to_address', 'subject', 'body')
        ):
            raise OutreachBlocked(
                'content is locked because a Gmail draft already exists for this queue item'
            )

        next_status = changes.get('status', current['status'])
        verification = changes.get(
            'verification_status',
            current['verification_status'],
        )
        subject = changes.get('subject', current.get('subject'))
        body = changes.get('body', current.get('body'))

        if next_status in {'draft_ready', 'approved'}:
            if current['channel'] == 'email' and (not subject or not body):
                raise OutreachBlocked('email draft requires both subject and body')
            if verification not in {'verified', 'not_required'}:
                raise OutreachBlocked('claim verification is required before a draft can be ready')

        try:
            updated, conflict = self.repository.update_item(
                item_id,
                changes=changes,
                expected_version=expected_version,
            )
        except OutreachOperationLocked as exc:
            raise OutreachBlocked(str(exc)) from exc
        if conflict:
            raise OutreachConflict('outreach item changed since it was loaded')
        return updated

    def generate_draft(self, item_id: str, *, expected_version: int) -> dict | None:
        if self.generator is None:
            raise OutreachIntegrationUnavailable('OpenRouter draft generation is not configured')

        context = self.repository.draft_context(item_id)
        if context is None:
            return None
        if context['version'] != expected_version:
            raise OutreachConflict('outreach item changed since it was loaded')
        if context['channel'] != 'email':
            raise OutreachBlocked('AI draft generation is currently available for email only')

        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current['version'] != expected_version:
            raise OutreachConflict('outreach item changed since it was loaded')
        if current.get('gmail_draft_id'):
            raise OutreachBlocked(
                'a Gmail draft already exists for this queue item; create a new queue item before regenerating'
            )

        if not context.get('to_address'):
            raise OutreachBlocked('email queue item has no recipient address')
        if self.repository.is_suppressed(context['to_address']):
            raise OutreachBlocked('email address is suppressed')

        claim = self.verifier.verify(context)
        try:
            copy = self.generator.generate_email(
                business_name=context.get('name') or 'your business',
                city=context.get('city'),
                vertical=context.get('vertical'),
                verified_claim=claim.text,
            )
        except OpenRouterError as exc:
            raise OutreachIntegrationUnavailable(str(exc)) from exc

        body_parts = [copy.intro]
        if claim.text:
            body_parts.append(claim.text)
        body_parts.extend([copy.cta, CAN_SPAM_FOOTER])
        body = "\n\n".join(part.strip() for part in body_parts if part and part.strip())

        try:
            updated, conflict = self.repository.record_generated_draft(
                item_id,
                expected_version=expected_version,
                subject=copy.subject,
                body=body,
                claim_signal=claim.signal,
                verification_status=claim.status,
                verification_note=claim.note,
                generation_model=copy.model,
                prompt_version=PROMPT_VERSION,
            )
        except OutreachOperationLocked as exc:
            raise OutreachBlocked(str(exc)) from exc
        if conflict:
            raise OutreachConflict('outreach item changed while the draft was being generated')
        return updated

    def create_gmail_draft(self, item_id: str, *, expected_version: int) -> dict | None:
        if self.gmail is None:
            raise OutreachIntegrationUnavailable('Gmail draft integration is not configured')

        current = self.repository.get_item(item_id)
        if current is None:
            return None
        if current['version'] != expected_version:
            raise OutreachConflict('outreach item changed since it was loaded')
        if current['channel'] != 'email':
            raise OutreachBlocked('Gmail drafts are available for email queue items only')
        if current.get('gmail_draft_id'):
            raise OutreachBlocked('a Gmail draft already exists for this queue item')
        if current['status'] not in {'draft_ready', 'approved'}:
            raise OutreachBlocked('mark the draft ready after human review before creating it in Gmail')
        if current['verification_status'] not in {'verified', 'not_required'}:
            raise OutreachBlocked('claim verification is required before creating a Gmail draft')
        if not current.get('to_address') or not current.get('subject') or not current.get('body'):
            raise OutreachBlocked('recipient, subject, and body are required for a Gmail draft')
        if self.repository.is_suppressed(current['to_address']):
            raise OutreachBlocked('email address is suppressed')

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
            raise OutreachConflict('outreach item changed since it was loaded')
        if operation is None:
            return None

        # A prior request may have reached Gmail but failed before Lead Desk
        # persisted Gmail's response. Reconcile the durable Message-ID first;
        # never create a second draft while the first outcome is ambiguous.
        if not operation['created_now']:
            if operation['state'] == 'created':
                return self.repository.get_item(item_id)
            if operation['state'] == 'pending':
                try:
                    recovered = self.gmail.find_draft_by_message_id(
                        operation['message_id_header']
                    )
                except GmailDraftError as exc:
                    raise OutreachIntegrationUnavailable(str(exc)) from exc
                if recovered is not None:
                    return self.repository.complete_gmail_draft_operation(
                        operation['id'],
                        draft_id=recovered.draft_id,
                        message_id=recovered.message_id,
                    )
                raise OutreachIntegrationUnavailable(
                    'Gmail draft creation is pending reconciliation; Lead Desk will not create a duplicate draft'
                )
            if operation['state'] == 'failed':
                reopened = self.repository.reopen_gmail_draft_operation(operation['id'])
                if reopened is None:
                    raise OutreachIntegrationUnavailable(
                        'Gmail draft operation could not be reopened safely'
                    )
                operation = {**reopened, 'created_now': False}

        try:
            result = self.gmail.create_draft(
                to_address=current['to_address'],
                subject=current['subject'],
                body=current['body'],
                message_id_header=operation['message_id_header'],
            )
        except GmailDraftError as exc:
            self.repository.record_gmail_operation_error(
                operation['id'],
                error_message=str(exc),
                uncertain=exc.uncertain_side_effect,
            )
            if exc.uncertain_side_effect:
                raise OutreachIntegrationUnavailable(
                    'Gmail draft request outcome is uncertain; the durable operation was preserved for reconciliation and no retry will create a duplicate'
                ) from exc
            raise OutreachIntegrationUnavailable(str(exc)) from exc

        # If this transaction fails after Gmail accepted the draft, the durable
        # operation remains pending. A retry reconciles by Message-ID and closes
        # the operation instead of creating another external side effect.
        return self.repository.complete_gmail_draft_operation(
            operation['id'],
            draft_id=result.draft_id,
            message_id=result.message_id,
        )
