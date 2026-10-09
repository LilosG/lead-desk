from app.outreach_policy import CLIENT_FACING_CLAIMS
from app.services.outreach import PROMPT_VERSION
from app.services.outreach_similarity import (
    DEFAULT_SIMILARITY_THRESHOLD,
    is_too_similar,
    normalize_outreach_note,
    structural_similarity,
)


CLAIM = CLIENT_FACING_CLAIMS["no_localbusiness_schema"]


def test_prompt_version_advances_for_human_copy_architecture():
    assert PROMPT_VERSION == "outreach-v11"


def test_similarity_threshold_is_strict_enough_for_batch_diversity():
    assert DEFAULT_SIMILARITY_THRESHOLD == 0.80


def test_normalization_removes_business_and_verified_finding():
    body = (
        "Hi,\n\nI looked at Bright Electric Services before reaching out. "
        + CLAIM
        + "\n\nI can send the exact page location if useful."
    )
    normalized = normalize_outreach_note(
        body,
        business_name="Bright Electric Services",
        verified_claim=CLAIM,
    )

    assert "bright electric services" not in normalized
    assert "structured business markup" not in normalized
    assert "[business]" in normalized
    assert "[finding]" in normalized


def test_benchmark_mass_generated_skeleton_is_blocked():
    bright = (
        "Hi,\n\nI was on Bright Electric Services website earlier. "
        + CLAIM
        + "\n\nIf you want, I can point to the exact place I'm referring to or send a screenshot. "
        "No need to reply if it's already on your list."
    )
    tnt = (
        "Hi,\n\nI was on TNT Electric website earlier. "
        + CLAIM
        + "\n\nIf you want, I can point to the exact place I'm referring to or send a screenshot. "
        "No need to reply if it's already on your list."
    )

    blocked, ratio, matched = is_too_similar(
        tnt,
        candidate_business_name="TNT Electric",
        candidate_verified_claim=CLAIM,
        recent_drafts=[("Bright Electric Services", bright, CLAIM)],
    )

    assert blocked is True
    assert ratio > 0.95
    assert matched == "Bright Electric Services"


def test_public_evidence_does_not_hide_duplicate_structure():
    bright_claim = (
        "Google shows Bright Electric Services at 4.9 stars across 40 reviews. "
        "On the website, though, " + CLAIM[0].lower() + CLAIM[1:]
    )
    tnt_claim = (
        "Google shows TNT Electric at 4.8 stars across 63 reviews. "
        "On the website, though, " + CLAIM[0].lower() + CLAIM[1:]
    )
    bright = "Hi,\n\n" + bright_claim + "\n\nThat is all I wanted to pass along."
    tnt = "Hi,\n\n" + tnt_claim + "\n\nThat is all I wanted to pass along."

    ratio = structural_similarity(
        tnt,
        candidate_business_name="TNT Electric",
        candidate_verified_claim=tnt_claim,
        existing_body=bright,
        existing_business_name="Bright Electric Services",
        existing_verified_claim=bright_claim,
    )

    assert ratio > 0.95


def test_materially_different_note_is_not_blocked():
    first = (
        "Hi,\n\n" + CLAIM + "\n\n"
        "I can send the page location I checked if you want to see it."
    )
    second = (
        "The TNT Electric website has one item I wanted to mention.\n\n"
        + CLAIM
        + "\n\nAlready have that covered? No reply needed."
    )

    ratio = structural_similarity(
        second,
        candidate_business_name="TNT Electric",
        candidate_verified_claim=CLAIM,
        existing_body=first,
        existing_business_name="Bright Electric Services",
        existing_verified_claim=CLAIM,
    )

    assert ratio < DEFAULT_SIMILARITY_THRESHOLD


def test_structural_similarity_is_order_independent():
    sal_claim = (
        "Google shows Sal & Sons Electric Inc at 5.0 stars across 365 reviews. "
        "On the website, though, " + CLAIM[0].lower() + CLAIM[1:]
    )
    wehrly_claim = (
        "Google shows Wehrly Electric at 5.0 stars across 220 reviews. "
        "On the website, though, " + CLAIM[0].lower() + CLAIM[1:]
    )
    sal = (
        "I had Sal & Sons Electric Inc open and wanted to pass this along.\n\n"
        + sal_claim
        + "\n\nNo need to respond if you already have it covered."
    )
    wehrly = (
        "Hi,\n\nI had one thing from Wehrly Electric I wanted to send over.\n\n"
        + wehrly_claim
        + "\n\nNo need to respond if you already have it covered."
    )

    sal_to_wehrly = structural_similarity(
        sal,
        candidate_business_name="Sal & Sons Electric Inc",
        candidate_verified_claim=sal_claim,
        existing_body=wehrly,
        existing_business_name="Wehrly Electric",
        existing_verified_claim=wehrly_claim,
    )
    wehrly_to_sal = structural_similarity(
        wehrly,
        candidate_business_name="Wehrly Electric",
        candidate_verified_claim=wehrly_claim,
        existing_body=sal,
        existing_business_name="Sal & Sons Electric Inc",
        existing_verified_claim=sal_claim,
    )

    assert sal_to_wehrly == wehrly_to_sal
    assert sal_to_wehrly >= DEFAULT_SIMILARITY_THRESHOLD
