from app.services.outreach import NO_CLIENT_FACING_FINDING, OutreachService
from app.services.outreach_verification import VerifiedClaim


class NeverCalledGenerator:
    def generate_email(self, **kwargs):
        raise AssertionError("generator must not run without a client-facing finding")


class InternalOnlyVerifier:
    def verify(self, context):
        return VerifiedClaim(
            signal="template_builder",
            text="Verified live builder signatures.",
            status="verified",
            note="Verified live builder signatures on: https://example.com/",
        )


class Repo:
    def __init__(self):
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

    def draft_context(self, item_id):
        return {
            **self.item,
            "name": "Example Electric",
            "city": "San Diego",
            "vertical": "electrician",
            "website_url": "https://example.com",
            "resolved_url": "https://example.com",
            "findings": [{"signal": "template_builder"}],
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


def test_no_client_facing_finding_clears_stale_draft_and_returns_clean_state():
    repo = Repo()
    service = OutreachService(
        repo,
        generator=NeverCalledGenerator(),
        verifier=InternalOnlyVerifier(),
        generation_model="openai/gpt-5-mini",
    )

    result = service.generate_draft(repo.item["id"], expected_version=7)

    assert result["subject"] is None
    assert result["body"] is None
    assert result["status"] == "review_required"
    assert result["verification_status"] == "verified"
    assert result["claim_signal"] == "template_builder"
    assert NO_CLIENT_FACING_FINDING in result["verification_note"]
    assert repo.updated_changes["subject"] is None
    assert repo.updated_changes["body"] is None
