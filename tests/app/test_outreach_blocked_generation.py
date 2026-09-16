from app.integrations.openrouter import CLAIM_TOKEN, GeneratedCopy
from app.services.outreach import NO_CLIENT_FACING_FINDING, OutreachService
from app.services.outreach_verification import VerifiedClaim


class NeverCalledGenerator:
    def generate_email(self, **kwargs):
        raise AssertionError("generator must not run without a client-facing finding")


class CapturingNoClaimVerifier:
    def __init__(self):
        self.context = None

    def verify(self, context):
        self.context = context
        return VerifiedClaim(
            signal=None,
            text=None,
            status="not_required",
            note="No safely re-verifiable outreach claim was available.",
        )


class ApprovedClaimVerifier:
    def __init__(self):
        self.context = None

    def verify(self, context):
        self.context = context
        return VerifiedClaim(
            signal="no_localbusiness_schema",
            text="Verified missing LocalBusiness schema.",
            status="verified",
            note="Re-checked live homepage before drafting: https://example.com/",
        )


class ClaimGenerator:
    def __init__(self):
        self.calls = 0

    def generate_email(self, **kwargs):
        self.calls += 1
        assert kwargs["verified_claim"]
        return GeneratedCopy(
            subject="Example Electric",
            body=(
                "Hi,\n\nI looked at Example Electric's website earlier.\n\n"
                f"{CLAIM_TOKEN}\n\n"
                "If you'd like, I can point to the exact spot or send a screenshot."
            ),
            model="openai/gpt-5-mini",
        )


class Repo:
    def __init__(self, findings=None):
        self.findings = findings or [{"signal": "template_builder"}]
        self.item = {
            "id": "11111111-1111-1111-1111-111111111111",
            "place_id": "place-1",
            "channel": "email",
            "status": "review_required",
            "to_address": "owner@example.com",
            "subject": "Old subject",
            "body": "Old stale generated body",
            "claim_signal": "template_builder",
            "verification_status": "verified",
            "verification_note": "old note",
            "gmail_draft_id": None,
            "version": 7,
        }
        self.updated_changes = None
        self.generated = None

    def draft_context(self, item_id):
        return {
            **self.item,
            "name": "Example Electric",
            "city": "San Diego",
            "vertical": "electrician",
            "website_url": "https://example.com",
            "resolved_url": "https://example.com",
            "findings": self.findings,
        }

    def get_item(self, item_id):
        return dict(self.item)

    def is_suppressed(self, email):
        return False

    def update_item(self, item_id, *, changes, expected_version):
        assert expected_version == self.item["version"]
        self.updated_changes = changes
        updated = {**self.item, **changes, "version": expected_version + 1}
        self.item = updated
        return updated, False

    def record_generated_draft(self, item_id, **kwargs):
        self.generated = kwargs
        updated = {
            **self.item,
            **kwargs,
            "status": "review_required",
            "version": self.item["version"] + 1,
        }
        self.item = updated
        return updated, False


def test_internal_only_finding_is_filtered_before_verification_and_not_drafted():
    repo = Repo(findings=[{"signal": "template_builder"}])
    verifier = CapturingNoClaimVerifier()
    service = OutreachService(
        repo,
        generator=NeverCalledGenerator(),
        verifier=verifier,
        generation_model="openai/gpt-5-mini",
    )

    result = service.generate_draft(repo.item["id"], expected_version=7)

    assert verifier.context is not None
    assert verifier.context["findings"] == []
    assert result["subject"] is None
    assert result["body"] is None
    assert result["status"] == "no_outreach_finding"
    assert result["verification_status"] == "not_required"
    assert result["claim_signal"] is None
    assert NO_CLIENT_FACING_FINDING in result["verification_note"]
    assert repo.updated_changes["subject"] is None
    assert repo.updated_changes["body"] is None


def test_internal_finding_cannot_shadow_later_approved_finding():
    repo = Repo(
        findings=[
            {"signal": "template_builder"},
            {"signal": "no_localbusiness_schema"},
        ]
    )
    verifier = ApprovedClaimVerifier()
    generator = ClaimGenerator()
    service = OutreachService(
        repo,
        generator=generator,
        verifier=verifier,
        generation_model="openai/gpt-5-mini",
    )

    result = service.generate_draft(repo.item["id"], expected_version=7)

    assert [finding["signal"] for finding in verifier.context["findings"]] == [
        "no_localbusiness_schema"
    ]
    assert generator.calls == 1
    assert result["status"] == "review_required"
    assert result["claim_signal"] == "no_localbusiness_schema"
    assert "structured business markup" in result["body"]
    assert "template" not in result["body"].lower()
