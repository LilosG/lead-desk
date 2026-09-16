import pytest

from app.integrations.openrouter import CLAIM_TOKEN, OpenRouterClient, OpenRouterError


def test_rejects_prospect_list_language_and_unsupported_consequence():
    body = (
        "Hi, I was looking at your site while checking out electricians in Oceanside "
        f"and noticed something that might be worth a quick fix. {CLAIM_TOKEN} "
        "It's a small thing, but it could help people get the right info faster. "
        "Let me know if you'd like me to point out exactly where it shows up, or just leave it here."
    )

    with pytest.raises(OpenRouterError):
        OpenRouterClient._validate_copy(
            subject="TNT Electric website",
            body=body,
            has_verified_claim=True,
            business_name="TNT Electric",
            city="Oceanside",
            vertical="electrician",
        )


def test_rejects_second_unverified_observation_before_finding():
    body = (
        "Hi, I just looked at your website and noticed something specific about how "
        f"your service areas are listed. {CLAIM_TOKEN} I can point you to the exact spot "
        "if that's helpful, or send a screenshot. No need to respond unless you want to."
    )

    with pytest.raises(OpenRouterError, match="unverified observation"):
        OpenRouterClient._validate_copy(
            subject="TNT Electric",
            body=body,
            has_verified_claim=True,
            business_name="TNT Electric",
            city="Oceanside",
            vertical="electrician",
        )


def test_allows_grounded_individual_note_without_prospecting_context():
    OpenRouterClient._validate_copy(
        subject="TNT Electric",
        body=(
            f"Hi,\n\n{CLAIM_TOKEN}\n\n"
            "If you want the exact page location I checked, I can send that over. "
            "If it's already on your radar, no reply needed."
        ),
        has_verified_claim=True,
        business_name="TNT Electric",
        city="Oceanside",
        vertical="electrician",
    )


def test_style_brief_is_stable_but_differs_across_benchmark_businesses():
    bright = OpenRouterClient._style_brief("Bright Electric Services")
    tnt = OpenRouterClient._style_brief("TNT Electric")
    blackwood = OpenRouterClient._style_brief("Blackwood Electric")

    assert bright == OpenRouterClient._style_brief("Bright Electric Services")
    assert bright != tnt
    assert bright != blackwood


def test_missing_finding_slot_fails_closed_after_repair(monkeypatch):
    client = OpenRouterClient(api_key="test", model="test/model")

    monkeypatch.setattr(
        client,
        "_request_copy",
        lambda **kwargs: ("Example Electric", "Hi, this body never includes the required finding token."),
    )

    with pytest.raises(OpenRouterError, match="could not preserve"):
        client._ensure_finding_slot(
            subject="Example Electric",
            body="Hi, no token here.",
            system="system",
            user="user",
            has_verified_claim=True,
        )
