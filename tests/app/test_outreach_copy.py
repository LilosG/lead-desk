import pytest

from app.integrations.openrouter import OpenRouterClient, OpenRouterError
from app.services.outreach import PROMPT_VERSION


def test_outreach_prompt_version_is_v3():
    assert PROMPT_VERSION == "outreach-v3"


def test_copy_guardrails_accept_professional_reply_oriented_copy():
    OpenRouterClient._validate_copy(
        subject="Volt Electric website",
        intro="I spent a few minutes looking through Volt Electric online before reaching out.",
        cta="Would it be useful if I sent over exactly what I would change?",
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
    ],
)
def test_copy_guardrails_reject_spammy_or_non_reply_patterns(subject, intro, cta):
    with pytest.raises(OpenRouterError):
        OpenRouterClient._validate_copy(subject=subject, intro=intro, cta=cta)
