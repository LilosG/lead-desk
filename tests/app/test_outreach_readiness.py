from app.services.outreach import OutreachService


class FakeRepository:
    def __init__(self, item):
        self.item = item

    def candidate_readiness(self, place_id):
        assert place_id == "place-1"
        return self.item


def service_for(item):
    return OutreachService(FakeRepository(item))


def test_readiness_accepts_viable_email_candidate():
    result = service_for(
        {
            "review_count": 22,
            "email": "owner@example.com",
            "phone": "555-0100",
            "confirmed_trading": True,
            "established": True,
            "needs_manual_check": False,
            "suppressed": False,
            "already_queued": False,
        }
    ).candidate_readiness("place-1")

    assert result["eligible"] is True
    assert result["reasons"] == []
    assert result["preferred_channel"] == "email"
    assert result["strong_review_base"] is True
    assert result["confirmed_trading"] is True


def test_readiness_explains_each_blocker():
    result = service_for(
        {
            "review_count": 4,
            "email": "owner@example.com",
            "phone": None,
            "confirmed_trading": False,
            "established": False,
            "needs_manual_check": True,
            "suppressed": True,
            "already_queued": True,
        }
    ).candidate_readiness("place-1")

    assert result["eligible"] is False

    assert result["reasons"] == [
        "Business has fewer than 10 Google reviews.",
        "Manual verification is required before outreach.",
        "The prospect email address is suppressed.",
        "Prospect is already in the outreach queue.",
    ]


def test_readiness_requires_reachable_contact():
    result = service_for(
        {
            "review_count": 30,
            "email": None,
            "phone": None,
            "confirmed_trading": True,
            "established": True,
            "needs_manual_check": False,
            "suppressed": False,
            "already_queued": False,
        }
    ).candidate_readiness("place-1")

    assert result["eligible"] is False
    assert result["preferred_channel"] is None

    assert result["reasons"] == [
        "No reachable email address or phone number is available."
    ]


def test_readiness_does_not_block_non_established_prospect():
    result = service_for(
        {
            "review_count": 22,
            "email": "owner@example.com",
            "phone": None,
            "confirmed_trading": True,
            "established": False,
            "needs_manual_check": False,
            "suppressed": False,
            "already_queued": False,
        }
    ).candidate_readiness("place-1")

    assert result["eligible"] is True
    assert result["reasons"] == []
    assert result["established"] is False
