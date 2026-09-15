from app.integrations.openrouter import CLAIM_TOKEN, OpenRouterClient, OpenRouterError


def test_rejects_prospect_list_language_and_unsupported_consequence():
    body = (
        "Hi, I was looking at your site while checking out electricians in Oceanside "
        f"and noticed something that might be worth a quick fix. {CLAIM_TOKEN} "
        "It's a small thing, but it could help people get the right info faster. "
        "Let me know if you'd like me to point out exactly where it shows up, or just leave it here."
    )

    try:
        OpenRouterClient._validate_copy(
            subject="TNT Electric website",
            body=body,
            has_verified_claim=True,
            business_name="TNT Electric",
            city="Oceanside",
            vertical="electrician",
        )
    except OpenRouterError:
        pass
    else:
        raise AssertionError("prospect-list framing and unsupported consequences must be rejected")


def test_rejects_second_unverified_observation_before_finding():
    body = (
        "Hi, I just looked at your website and noticed something specific about how "
        f"your service areas are listed. {CLAIM_TOKEN} I can point you to the exact spot "
        "if that's helpful, or send a screenshot. No need to respond unless you want to."
    )

    try:
        OpenRouterClient._validate_copy(
            subject="TNT Electric",
            body=body,
            has_verified_claim=True,
            business_name="TNT Electric",
            city="Oceanside",
            vertical="electrician",
        )
    except OpenRouterError as exc:
        assert "unverified observation" in str(exc)
    else:
        raise AssertionError("a second website observation must never pass validation")


def test_allows_grounded_one_business_note():
    OpenRouterClient._validate_copy(
        subject="TNT Electric",
        body=(
            "Hi, I was on TNT Electric's site earlier and wanted to mention one technical item. "
            f"{CLAIM_TOKEN} If you handle the site internally, I can point you to the exact spot "
            "I mean. If not, no need to do anything with this."
        ),
        has_verified_claim=True,
        business_name="TNT Electric",
        city="Oceanside",
        vertical="electrician",
    )


def test_safe_fallback_contains_only_the_verified_finding_slot():
    subject, body = OpenRouterClient._safe_fallback(
        business_name="TNT Electric",
        has_verified_claim=True,
    )

    assert subject == "TNT Electric"
    assert body.count(CLAIM_TOKEN) == 1
    assert "service area" not in body.lower()
    assert "could help" not in body.lower()
    OpenRouterClient._validate_copy(
        subject=subject,
        body=body,
        has_verified_claim=True,
        business_name="TNT Electric",
        city="Oceanside",
        vertical="electrician",
    )
