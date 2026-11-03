"""Copy guardrails for the current (v9) first-touch email validator."""
import pytest

from app.integrations.openrouter import CLAIM_TOKEN, OpenRouterClient, OpenRouterError
from app.services.outreach import PROMPT_VERSION


def _body(prefix: str = "Hi,", suffix: str = "") -> str:
    tail = suffix or (
        "If that is useful, I can put the specific change in writing for your team "
        "so it is easy to hand off. Either way, thanks for reading this note today."
    )
    return f"{prefix}\n\n{CLAIM_TOKEN}\n\n{tail}"


def test_prompt_version_is_current():
    assert PROMPT_VERSION == "outreach-v12"


def test_validator_accepts_short_claim_slot_copy():
    OpenRouterClient._validate_copy(
        subject="Volt Electric website",
        body=_body(),
        has_verified_claim=True,
        business_name="Volt Electric",
    )


@pytest.mark.parametrize(
    "subject,body,message",
    [
        ("A subject line that is far too long", _body(), "subject"),
        ("Volt Electric website", "Hi,\n\nToo short.", "length"),
        ("Volt Electric website", _body().replace(CLAIM_TOKEN, "no slot"), "slot"),
        ("Volt Electric website", _body(prefix="Hi, I noticed your reviews and hours,"), "unverified observation"),
    ],
)
def test_validator_rejects_structural_problems(subject, body, message):
    with pytest.raises(OpenRouterError):
        OpenRouterClient._validate_copy(
            subject=subject, body=body, has_verified_claim=True,
        )


@pytest.mark.parametrize(
    "phrase",
    ["https://example.com", "book a call", "free audit", "online presence", "skyrocket"],
)
def test_validator_rejects_spam_and_link_phrases(phrase):
    body = _body(suffix=(
        f"I can share more detail here, {phrase}, and keep it short for your team "
        "so the change is easy to hand off whenever it suits you."
    ))
    with pytest.raises(OpenRouterError):
        OpenRouterClient._validate_copy(
            subject="Volt Electric website", body=body, has_verified_claim=True,
        )


def test_validator_rejects_slot_when_no_claim_was_verified():
    with pytest.raises(OpenRouterError):
        OpenRouterClient._validate_copy(
            subject="Volt Electric website", body=_body(), has_verified_claim=False,
        )
