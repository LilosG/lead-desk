from app.integrations.gmail import GmailDraftResult
from app.integrations.openrouter import GeneratedCopy
from app.services.outreach import OutreachBlocked, OutreachService
from app.services.outreach_verification import VerifiedClaim


class FakeGenerator:
    def generate_email(self, **kwargs):
        assert kwargs["business_name"] == "Example Electric"
        return GeneratedCopy(
            subject="Quick question for Example Electric",
            intro="Hi there — I work with local electrical companies in San Diego.",
            cta="Want me to send over the observation?",
            model="test/model",
        )


class FakeVerifier:
    def verify(self, context):
        return VerifiedClaim(
            signal="no_localbusiness_schema",
            text="I noticed the homepage does not appear to include LocalBusiness schema markup.",
            status="verified",
            note="Re-checked live homepage before drafting.",
        )


class FakeGmail:
    def create_draft(self, **kwargs):
        assert kwargs["to_address"] == "owner@example.com"
        assert kwargs["subject"] == "Reviewed subject"
        assert "1440 Columbia St" in kwargs["body"]
        return GmailDraftResult(draft_id="draft-123", message_id="message-123")


class FakeRepository:
    def __init__(self):
        self.generated = None
        self.gmail = None
        self.item = {
            "id": "11111111-1111-1111-1111-111111111111",
            "place_id": "place-1",
            "channel": "email",
            "status": "queued",
            "to_address": "owner@example.com",
            "subject": None,
            "body": None,
            "claim_signal": None,
            "verification_status": "pending",
            "verification_note": None,
            "gmail_draft_id": None,
            "version": 1,
        }

    def draft_context(self, item_id):
        return {
            **self.item,
            "name": "Example Electric",
            "city": "San Diego",
            "vertical": "electrician",
            "website_url": "https://example.com",
            "resolved_url": "https://example.com",
            "needs_manual_check": False,
            "findings": [{"signal": "no_localbusiness_schema"}],
        }

    def is_suppressed(self, email):
        return False

    def record_generated_draft(self, item_id, **kwargs):
        self.generated = kwargs
        return {
            **self.item,
            **kwargs,
            "status": "review_required",
            "version": 2,
        }, False

    def get_item(self, item_id):
        return dict(self.item)

    def record_gmail_draft(self, item_id, **kwargs):
        self.gmail = kwargs
        return {
            **self.item,
            "gmail_draft_id": kwargs["draft_id"],
            "gmail_message_id": kwargs["message_id"],
            "version": 2,
        }, False

    def update_item(self, item_id, *, changes, expected_version):
        return {**self.item, **changes, "version": expected_version + 1}, False


def test_generation_uses_verified_claim_and_deterministic_footer():
    repo = FakeRepository()
    service = OutreachService(
        repo,
        generator=FakeGenerator(),
        verifier=FakeVerifier(),
        generation_model="test/model",
    )

    result = service.generate_draft(repo.item["id"], expected_version=1)

    assert result["status"] == "review_required"
    assert repo.generated["claim_signal"] == "no_localbusiness_schema"
    assert repo.generated["verification_status"] == "verified"
    assert "LocalBusiness schema markup" in repo.generated["body"]
    assert "1440 Columbia St" in repo.generated["body"]
    assert "If you'd rather I not reach out again" in repo.generated["body"]
    assert repo.generated["generation_model"] == "test/model"


def test_gmail_creation_requires_human_ready_state_and_never_sends():
    repo = FakeRepository()
    repo.item.update({
        "status": "draft_ready",
        "subject": "Reviewed subject",
        "body": "Reviewed body\n\n1440 Columbia St",
        "verification_status": "verified",
    })
    service = OutreachService(
        repo,
        gmail=FakeGmail(),
        gmail_sender_email="mike@lilosgrowth.com",
    )

    result = service.create_gmail_draft(repo.item["id"], expected_version=1)

    assert result["gmail_draft_id"] == "draft-123"
    assert repo.gmail["draft_id"] == "draft-123"
    assert service.integration_status()["send_enabled"] is False


def test_gmail_creation_blocks_unreviewed_queue_item():
    repo = FakeRepository()
    repo.item.update({
        "subject": "Subject",
        "body": "Body",
        "verification_status": "verified",
    })
    service = OutreachService(repo, gmail=FakeGmail())

    try:
        service.create_gmail_draft(repo.item["id"], expected_version=1)
    except OutreachBlocked as exc:
        assert "mark the draft ready" in str(exc)
    else:
        raise AssertionError("expected unreviewed Gmail draft creation to be blocked")


def test_explicit_null_status_is_rejected_before_repository_write():
    repo = FakeRepository()
    service = OutreachService(repo)

    try:
        service.update_item(
            repo.item["id"],
            changes={"status": None},
            expected_version=1,
        )
    except OutreachBlocked as exc:
        assert "status cannot be null" in str(exc)
    else:
        raise AssertionError("expected null status to be rejected")
