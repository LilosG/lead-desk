from app.integrations.openrouter import CLAIM_TOKEN, GeneratedCopy
from app.services.outreach import PROMPT_VERSION, OutreachService
from app.services.outreach_verification import VerifiedClaim


class ClaimFreeGenerator:
    def __init__(self):
        self.calls = 0

    def generate_email(self, **kwargs):
        self.calls += 1
        assert kwargs["verified_claim"] is None
        return GeneratedCopy(
            subject="Example Electric",
            body=(
                "Hi,\n\n"
                "I wanted to introduce LILOs Growth and reach out directly about Example Electric. "
                "If website or local visibility work is on your list, I can share what we do and "
                "you can decide if it is relevant."
            ),
            model="qwen/qwen3-30b-a3b-instruct-2507",
        )


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
                "Hi,\n\n"
                f"{CLAIM_TOKEN}\n\n"
                "I can send the exact page location I checked if that would be useful."
            ),
            model="qwen/qwen3-30b-a3b-instruct-2507",
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
            "generation_model": "qwen/qwen3-30b-a3b-instruct-2507",
            "generation_prompt_version": "outreach-v6",
            "draft_generated_at": "2026-09-16T19:15:47Z",
            "gmail_draft_id": None,
            "gmail_message_id": None,
            "gmail_draft_created_at": None,
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

    def list_items(self, status=None):
        return [], 0

    def recent_generated_drafts(self, *, limit=25, exclude_id=None):
        return []

    def update_item(self, item_id, *, changes, expected_version):
        assert expected_version == self.item["version"]
        self.updated_changes = changes
        updated = {**self.item, **changes, "version": expected_version + 1}
        self.item = updated
        return updated, False

    def record_no_outreach_finding(
        self,
        item_id,
        *,
        expected_version,
        claim_signal,
        verification_status,
        verification_note,
    ):
        raise AssertionError("no-finding state must not replace a valid claim-free draft")

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


def test_internal_only_finding_is_filtered_and_claim_free_draft_is_generated():
    repo = Repo(findings=[{"signal": "template_builder"}])
    verifier = CapturingNoClaimVerifier()
    generator = ClaimFreeGenerator()
    service = OutreachService(
        repo,
        generator=generator,
        verifier=verifier,
        generation_model="qwen/qwen3-30b-a3b-instruct-2507",
    )

    result = service.generate_draft(repo.item["id"], expected_version=7)

    assert verifier.context is not None
    assert verifier.context["findings"] == []
    assert generator.calls == 1
    assert result["subject"] == "Example Electric"
    assert "LILOs Growth" in result["body"]
    assert CLAIM_TOKEN not in result["body"]
    assert result["status"] == "review_required"
    assert result["verification_status"] == "not_required"
    assert result["claim_signal"] is None
    assert result["verification_note"] == "No safely re-verifiable outreach claim was available."
    assert result["generation_model"] == "qwen/qwen3-30b-a3b-instruct-2507"
    assert result["prompt_version"] == PROMPT_VERSION


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
        generation_model="qwen/qwen3-30b-a3b-instruct-2507",
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


def test_generated_audit_supplies_useful_grounding_without_live_claim():
    repo = Repo(findings=[{"signal": "template_builder"}])
    verifier = CapturingNoClaimVerifier()
    service = OutreachService(
        repo,
        generator=ClaimGenerator(),
        verifier=verifier,
        generation_model="qwen/qwen3-30b-a3b-instruct-2507",
    )
    context = repo.draft_context(repo.item["id"])
    context["audit_snapshot"] = {
        "business": {"rating": 4.9, "review_count": 71},
        "findings": [
            {"signal": "no_service_pages"},
            {"signal": "no_city_pages"},
            {"signal": "no_localbusiness_schema"},
            {"signal": "no_gbp_link"},
        ],
    }
    context["audit_source_checked_at"] = "2026-09-13T12:00:00+00:00"

    visible_claim, claim_signal, verification_status, verification_note = (
        service._resolve_draft_grounding(
            context,
            business_name="Example Electric",
        )
    )

    assert verifier.context is None
    assert claim_signal == "audit_report"
    assert verification_status == "not_required"
    # Older (v4) snapshots carry no numbers: the email still leads with one
    # plain-English finding and names up to two more, without jargon.
    assert "service pages" in visible_claim
    assert "pages for the areas you serve" in visible_claim
    assert "structured business data" not in visible_claim
    assert "several areas" not in visible_claim
    assert "Local Visibility Audit" in verification_note



def test_audit_grounding_covers_profile_and_speed_findings_for_volume():
    repo = Repo(findings=[{"signal": "template_builder"}])
    verifier = CapturingNoClaimVerifier()
    service = OutreachService(
        repo,
        generator=ClaimGenerator(),
        verifier=verifier,
        generation_model="qwen/qwen3-30b-a3b-instruct-2507",
    )
    context = repo.draft_context(repo.item["id"])
    context["audit_snapshot"] = {
        "business": {"rating": 4.6, "review_count": 12},
        "market_comparison": {"market": "Scottsdale, AZ", "niche": "med spa", "median_reviews": 66},
        "findings": [
            {"signal": "reviews_below_median", "phrase": "review count compared with nearby competitors",
             "data": {"reviews": 12, "median": 66, "market": "Scottsdale, AZ", "niche": "med spa"}},
            {"signal": "psi_mobile_poor", "phrase": "mobile page speed",
             "data": {"psi_performance": 38, "lcp_ms": 9100}},
            {"signal": "no_service_pages", "title": "No individual treatment pages",
             "phrase": "treatment pages"},
        ],
    }

    visible_claim, claim_signal, _, _ = service._resolve_draft_grounding(
        context, business_name="Glow Med Spa",
    )

    assert verifier.context is None
    assert claim_signal == "audit_report"
    # Leads with the concrete number, then names the others plainly.
    assert visible_claim.startswith("I ran Glow Med Spa's homepage through Google's mobile speed test")
    assert "scored 38 out of 100" in visible_claim
    assert "about 9 seconds" in visible_claim
    assert "the number of Google reviews" in visible_claim
    assert "treatment pages" in visible_claim
    assert "online presence" not in visible_claim
    assert context["_audit_subject"] == "Glow Med Spa website on phones"
