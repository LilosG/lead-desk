from app.integrations.openrouter import CLAIM_TOKEN, OpenRouterClient


def test_missing_verified_finding_slot_is_inserted_inside_note():
    body = (
        "Hi,\n\n"
        "I was on Example Electric's site earlier and saw something I wanted to mention. "
        "If it's already on your list, no worries."
    )

    repaired = OpenRouterClient._insert_verified_finding_slot(body)

    assert repaired.count(CLAIM_TOKEN) == 1
    assert repaired.startswith("Hi,\n\nI was on Example Electric's site earlier")
    assert "earlier. [[VERIFIED_FINDING]] If it's already on your list" in repaired


def test_slot_repair_removes_duplicate_existing_tokens_before_inserting_one():
    body = (
        "Hi,\n\n"
        "I checked the site earlier. [[VERIFIED_FINDING]] "
        "[[VERIFIED_FINDING]] I can point to the exact spot if helpful."
    )

    repaired = OpenRouterClient._insert_verified_finding_slot(body)

    assert repaired.count(CLAIM_TOKEN) == 1
