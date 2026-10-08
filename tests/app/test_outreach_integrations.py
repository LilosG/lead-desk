from uuid import UUID

from pydantic import ValidationError

from app.integrations.gmail import GmailDraftError, GmailDraftResult
from app.integrations.openrouter import (
    CLAIM_TOKEN,
    GeneratedCopy,
    OpenRouterClient,
    OpenRouterError,
)
from app.schemas.prospects import ProspectWorkflowUpdate
from app.services.outreach import (
    OutreachBlocked,
    OutreachIntegrationUnavailable,
    OutreachService,
)
from app.services.outreach_copy import client_facing_claim
from app.services.outreach_verification import OutreachClaimVerifier, VerifiedClaim


class FakeGenerator:
    def generate_email(self, **kwargs):
        assert kwargs["business_name"] == "Example Electric"
        assert "LocalBusiness schema" not in (kwargs["verified_claim"] or "")
        return GeneratedCopy(
            subject="Example Electric",
            body=(
                "Hi,\n\nI was looking through Example Electric's site earlier and "
                f"{CLAIM_TOKEN} If you handle the site internally, I can point you "
                "to the exact spot I mean."
            ),
            model="test/model",
        )


class SequenceGenerator:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.calls = 0

    def generate_email(self, **kwargs):
        index = min(self.calls, len(self.bodies) - 1)
        body = self.bodies[index]
        self.calls += 1
        return GeneratedCopy(
            subject="Example Electric",
            body=body,
            model="test/model",
        )


class CapturingGenerator(FakeGenerator):
    def __init__(self):
        self.verified_claim = None

    def generate_email(self, **kwargs):
        self.verified_claim = kwargs["verified_claim"]
        return super().generate_email(**kwargs)


class FakeEvidenceRepository:
    def get(self, place_id):
        assert place_id == "place-1"
        return {
            "rating": 4.9,
            "review_count": 40,
            "last_review_days": 21,
            "recent_reviews_90d": 3,
            "confirmed_trading": True,
            "established": True,
            "total_score": 13,
            "tier": "A",
            "authority_score": 5,
        }


class FakeVerifier:
    def verify(self, context):
        return VerifiedClaim(
            signal="no_localbusiness_schema",
            text="I noticed the homepage does not appear to include LocalBusiness schema markup.",
            status="verified",
            note="Re-checked live homepage before drafting.",
        )


class FakeGmail:
    def __init__(self):
        self.create_calls = 0
        self.recovered = None

    def create_draft(self, **kwargs):
        self.create_calls += 1
        assert kwargs["to_address"] == "owner@example.com"
        assert kwargs["subject"] == "Reviewed subject"
        assert "1440 Columbia St" in kwargs["body"]
        assert kwargs["message_id_header"].startswith("<")
        assert kwargs["message_id_header"].endswith("@lead-desk.lilosgrowth.com>")
        return GmailDraftResult(draft_id="draft-123", message_id="message-123")

    def find_draft_by_message_id(self, message_id_header):
        return self.recovered


class UncertainThenRecoveringGmail(FakeGmail):
    def create_draft(self, **kwargs):
        self.create_calls += 1
        self.recovered = GmailDraftResult(
            draft_id="draft-recovered",
            message_id="message-recovered",
        )
        raise GmailDraftError(
            "transport outcome uncertain",
            uncertain_side_effect=True,
        )


class FakeRepository:
    def __init__(self):
        self.generated = None
        self.gmail = None
        self.operation = None
        self.recent_drafts = []
        self.recent_query = None
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

    def recent_generated_drafts(self, *, limit=25, exclude_id=None):
        self.recent_query = {
            "limit": limit,
            "exclude_id": exclude_id,
        }
        return list(self.recent_drafts)

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

    def update_item(self, item_id, *, changes, expected_version):
        return {**self.item, **changes, "version": expected_version + 1}, False

    def begin_gmail_draft_operation(self, item_id, *, expected_version, message_id_header):
        if expected_version != self.item["version"]:
            return {"queue_version": self.item["version"]}, True
        if self.operation is not None:
            return {**self.operation, "created_now": False}, False
        self.operation = {
            "id": "22222222-2222-2222-2222-222222222222",
            "queue_id": item_id,
            "queue_version": expected_version,
            "message_id_header": message_id_header,
            "state": "pending",
            "gmail_draft_id": None,
            "gmail_message_id": None,
            "error_message": None,
        }
        return {**self.operation, "created_now": True}, False

    def reopen_gmail_draft_operation(self, operation_id):
        if not self.operation or self.operation["id"] != operation_id:
            return None
        self.operation["state"] = "pending"
        self.operation["error_message"] = None
        return dict(self.operation)

    def record_gmail_operation_error(self, operation_id, *, error_message, uncertain):
        assert self.operation and self.operation["id"] == operation_id
        self.operation["state"] = "pending" if uncertain else "failed"
        self.operation["error_message"] = error_message

    def complete_gmail_draft_operation(self, operation_id, *, draft_id, message_id):
        assert self.operation and self.operation["id"] == operation_id
        self.operation.update({
            "state": "created",
            "gmail_draft_id": draft_id,
            "gmail_message_id": message_id,
            "error_message": None,
        })
        self.gmail = {
            "draft_id": draft_id,
            "message_id": message_id,
            "operation_id": operation_id,
        }
        self.item.update({
            "gmail_draft_id": draft_id,
            "gmail_message_id": message_id,
            "version": self.item["version"] + 1,
        })
        return dict(self.item)


def test_generation_uses_one_coherent_note_and_verified_claim_slot():
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
    assert repo.generated["body"].startswith("Hi,\n\nI was looking through")
    assert "structured business markup" in repo.generated["body"]
    assert "LocalBusiness schema markup" not in repo.generated["body"]
    assert CLAIM_TOKEN not in repo.generated["body"]
    assert "Happy to send over" not in repo.generated["body"]
    assert "1440 Columbia St" in repo.generated["body"]
    assert "If you'd rather I not reach out again" in repo.generated["body"]
    assert repo.generated["generation_model"] == "test/model"
    assert repo.generated["prompt_version"] == "outreach-v9"


def test_generation_adds_public_google_evidence_but_not_internal_scores():
    repo = FakeRepository()
    generator = CapturingGenerator()
    service = OutreachService(
        repo,
        evidence_repository=FakeEvidenceRepository(),
        generator=generator,
        verifier=FakeVerifier(),
        generation_model="test/model",
    )

    result = service.generate_draft(repo.item["id"], expected_version=1)

    assert result["status"] == "review_required"
    assert generator.verified_claim is not None
    assert "Google shows Example Electric at 4.9 stars across 40 reviews." in generator.verified_claim
    assert "structured business markup" in generator.verified_claim
    assert "score" not in generator.verified_claim.lower()
    assert "tier" not in generator.verified_claim.lower()
    assert "authority" not in generator.verified_claim.lower()
    assert "4.9 stars across 40 reviews" in repo.generated["body"]


def test_client_facing_claim_keeps_verification_technical_details_out_of_email():
    rendered = client_facing_claim(
        "no_localbusiness_schema",
        "I noticed the homepage does not appear to include LocalBusiness schema markup.",
    )
    assert rendered == (
        "The homepage isn't currently using structured business markup to identify the company to Google."
    )


def test_copy_validator_rejects_mass_outreach_patterns_and_city_stuffing():
    try:
        OpenRouterClient._validate_copy(
            subject="Example Electric in San Diego",
            body=(
                "Hi, I was reviewing Example Electric online and noticed one thing "
                f"worth flagging. {CLAIM_TOKEN} Want me to send over the detail on that? "
                "I can explain more if needed."
            ),
            has_verified_claim=True,
            business_name="Example Electric",
            city="San Diego",
        )
    except OpenRouterError:
        pass
    else:
        raise AssertionError("mass-outreach copy should be rejected")


def test_copy_validator_requires_verified_finding_slot_exactly_once():
    OpenRouterClient._validate_copy(
        subject="Example Electric",
        body=(
            "Hi, I was looking through Example Electric's site earlier and "
            f"{CLAIM_TOKEN} If you handle the site internally, I can point you "
            "to the exact spot I mean without turning this into a whole pitch."
        ),
        has_verified_claim=True,
        business_name="Example Electric",
        city="San Diego",
    )

    try:
        OpenRouterClient._validate_copy(
            subject="Example Electric",
            body=(
                "Hi, I was looking through Example Electric's site earlier. "
                "There was one technical item I wanted to mention, and I can "
                "point you to it if that would help at some point."
            ),
            has_verified_claim=True,
            business_name="Example Electric",
            city="San Diego",
        )
    except OpenRouterError:
        pass
    else:
        raise AssertionError("verified copy must preserve the finding slot")


def test_generation_uses_dedicated_recent_draft_query():
    repo = FakeRepository()
    repo.recent_drafts = [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Prior Electric",
            "body": (
                "Hello,\n\n"
                "The homepage isn't currently using structured business markup "
                "to identify the company to Google.\n\n"
                "If you already know about it, no need to reply."
            ),
            "claim_signal": "no_localbusiness_schema",
            "verification_note": "verified",
        }
    ]

    service = OutreachService(
        repo,
        generator=FakeGenerator(),
        verifier=FakeVerifier(),
        generation_model="test/model",
    )

    service.generate_draft(
        repo.item["id"],
        expected_version=1,
    )

    assert repo.recent_query == {
        "limit": 25,
        "exclude_id": UUID(repo.item["id"]),
    }


def test_generation_rejects_three_similar_attempts_without_persisting():
    repo = FakeRepository()
    repo.recent_drafts = [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Prior Electric",
            "body": (
                "Hi,\n\n"
                "The homepage isn't currently using structured business markup "
                "to identify the company to Google.\n\n"
                "That is all I wanted to pass along."
            ),
            "claim_signal": "no_localbusiness_schema",
            "verification_note": "verified",
        }
    ]

    generator = SequenceGenerator(
        [
            "Hi,\n\n"
            f"{CLAIM_TOKEN}\n\n"
            "That is all I wanted to pass along."
        ]
    )

    service = OutreachService(
        repo,
        generator=generator,
        verifier=FakeVerifier(),
        generation_model="test/model",
    )

    try:
        service.generate_draft(
            repo.item["id"],
            expected_version=1,
        )
    except OutreachIntegrationUnavailable as exc:
        assert "after 3 attempts" in str(exc)
        assert "no draft was saved" in str(exc)
    else:
        raise AssertionError("expected similarity retry exhaustion")

    assert generator.calls == 3
    assert repo.generated is None


def test_generation_persists_third_attempt_when_first_two_are_similar():
    repo = FakeRepository()
    repo.recent_drafts = [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Prior Electric",
            "body": (
                "Hi,\n\n"
                "The homepage isn't currently using structured business markup "
                "to identify the company to Google.\n\n"
                "That is all I wanted to pass along."
            ),
            "claim_signal": "no_localbusiness_schema",
            "verification_note": "verified",
        }
    ]

    similar = (
        "Hi,\n\n"
        f"{CLAIM_TOKEN}\n\n"
        "That is all I wanted to pass along."
    )
    distinct = (
        "Here is the one website detail I found for Example Electric:\n\n"
        f"{CLAIM_TOKEN}\n\n"
        "I can point you to the exact spot if useful."
    )

    generator = SequenceGenerator(
        [
            similar,
            similar,
            distinct,
        ]
    )

    service = OutreachService(
        repo,
        generator=generator,
        verifier=FakeVerifier(),
        generation_model="test/model",
    )

    result = service.generate_draft(
        repo.item["id"],
        expected_version=1,
    )

    assert generator.calls == 3
    assert result["status"] == "review_required"
    assert repo.generated is not None
    assert "exact spot if useful" in repo.generated["body"]


def test_generation_blocks_when_gmail_draft_already_exists():
    repo = FakeRepository()
    repo.item["gmail_draft_id"] = "draft-existing"
    service = OutreachService(repo, generator=FakeGenerator(), verifier=FakeVerifier())

    try:
        service.generate_draft(repo.item["id"], expected_version=1)
    except OutreachBlocked as exc:
        assert "Gmail draft already exists" in str(exc)
    else:
        raise AssertionError("expected regeneration after Gmail draft to be blocked")

    assert repo.generated is None


def test_gmail_creation_requires_human_ready_state_and_never_sends():
    repo = FakeRepository()
    repo.item.update({
        "status": "draft_ready",
        "subject": "Reviewed subject",
        "body": "Reviewed body\n\n1440 Columbia St",
        "verification_status": "verified",
    })
    gmail = FakeGmail()
    service = OutreachService(
        repo,
        gmail=gmail,
        gmail_sender_email="mike@lilosgrowth.com",
    )

    result = service.create_gmail_draft(repo.item["id"], expected_version=1)

    assert result["gmail_draft_id"] == "draft-123"
    assert repo.gmail["draft_id"] == "draft-123"
    assert gmail.create_calls == 1
    assert service.integration_status()["send_enabled"] is False


def test_uncertain_gmail_result_reconciles_without_duplicate_creation():
    repo = FakeRepository()
    repo.item.update({
        "status": "draft_ready",
        "subject": "Reviewed subject",
        "body": "Reviewed body\n\n1440 Columbia St",
        "verification_status": "verified",
    })
    gmail = UncertainThenRecoveringGmail()
    service = OutreachService(repo, gmail=gmail)

    try:
        service.create_gmail_draft(repo.item["id"], expected_version=1)
    except OutreachIntegrationUnavailable as exc:
        assert "preserved for reconciliation" in str(exc)
    else:
        raise AssertionError("expected uncertain Gmail response to remain pending")

    assert gmail.create_calls == 1
    assert repo.operation["state"] == "pending"

    result = service.create_gmail_draft(repo.item["id"], expected_version=1)

    assert result["gmail_draft_id"] == "draft-recovered"
    assert gmail.create_calls == 1
    assert repo.operation["state"] == "created"


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


def test_workflow_required_fields_reject_explicit_null():
    for field_name in ("status", "priority"):
        try:
            ProspectWorkflowUpdate.model_validate({
                field_name: None,
                "expected_version": 0,
            })
        except ValidationError as exc:
            assert f"{field_name} cannot be null" in str(exc)
        else:
            raise AssertionError(f"expected null {field_name} to be rejected")


def test_schema_verifier_detects_known_localbusiness_type():
    html = '''
    <html><head>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Electrician","name":"Example Electric"}
      </script>
    </head></html>
    '''
    assert OutreachClaimVerifier._localbusiness_schema_state(html) == "present"


def test_schema_verifier_treats_unknown_business_type_as_ambiguous():
    html = '''
    <html><head>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"SomeFutureLocalBusinessSubtype","name":"Example"}
      </script>
    </head></html>
    '''
    assert OutreachClaimVerifier._localbusiness_schema_state(html) == "ambiguous"


def test_schema_verifier_only_calls_absent_when_safe():
    html = '''
    <html><head>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"WebSite","name":"Example"}
      </script>
    </head></html>
    '''
    assert OutreachClaimVerifier._localbusiness_schema_state(html) == "absent"


def test_live_verifier_rejects_private_network_targets():
    assert OutreachClaimVerifier._is_public_http_url("http://127.0.0.1/") is False
    assert OutreachClaimVerifier._is_public_http_url("http://[::1]/") is False
