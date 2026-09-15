import json

import pytest

from app.integrations.openrouter import OpenRouterClient, OpenRouterError
from app.services.outreach import PROMPT_VERSION


def test_outreach_prompt_version_is_v4():
    assert PROMPT_VERSION == "outreach-v4"


def test_copy_guardrails_accept_claim_aligned_reply_oriented_copy():
    OpenRouterClient._validate_copy(
        subject="Volt Electric website",
        intro="I took a look at Volt Electric's website before reaching out.",
        cta="Want me to send over the fix I'd make?",
        verified_claim="I noticed the homepage does not appear to include LocalBusiness schema markup.",
    )


def test_copy_guardrails_reject_context_not_supported_by_claim():
    with pytest.raises(OpenRouterError, match="context not supported"):
        OpenRouterClient._validate_copy(
            subject="Sunnydale Electric search",
            intro="I was looking at Sunnydale Electric in local search before reaching out.",
            cta="Want me to send over the recommendation?",
            verified_claim="I noticed the homepage does not appear to include LocalBusiness schema markup.",
        )


@pytest.mark.parametrize(
    "subject,intro,cta",
    [
        (
            "Quick note for Volt Electric",
            "I came across your business and wanted to reach out.",
            "Would you like to book a call?",
        ),
        (
            "RE: Volt Electric",
            "I reviewed Volt Electric online before reaching out.",
            "Would you like the details?",
        ),
        (
            "Volt Electric website",
            "I reviewed Volt Electric online before reaching out!",
            "Would you like the details?",
        ),
        (
            "Volt Electric website",
            "I reviewed Volt Electric online before reaching out.",
            "I can send the details.",
        ),
        (
            "Volt Electric website",
            "I reviewed Volt Electric's online presence before reaching out.",
            "Would you be open to me sending the exact change I'd recommend?",
        ),
    ],
)
def test_copy_guardrails_reject_spammy_or_non_reply_patterns(subject, intro, cta):
    with pytest.raises(OpenRouterError):
        OpenRouterClient._validate_copy(
            subject=subject,
            intro=intro,
            cta=cta,
            verified_claim="I noticed the homepage does not appear to include LocalBusiness schema markup.",
        )


def test_generation_prompt_receives_verified_claim_for_context(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "Sunnydale Electric website",
                                    "intro": "I took a look at Sunnydale Electric's website before reaching out.",
                                    "cta": "Want me to send over the fix I'd make?",
                                }
                            )
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        captured.update(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr("app.integrations.openrouter.requests.post", fake_post)
    claim = "I noticed the homepage does not appear to include LocalBusiness schema markup."
    client = OpenRouterClient(api_key="test", model="test/model")

    result = client.generate_email(
        business_name="Sunnydale Electric",
        city="Ramona",
        vertical="electrician",
        verified_claim=claim,
    )

    user_message = captured["messages"][1]["content"]
    assert claim in user_message
    assert result.subject == "Sunnydale Electric website"
