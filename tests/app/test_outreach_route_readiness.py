import pytest
from fastapi import HTTPException

from app.api.routes import outreach as outreach_route
from app.schemas.outreach import OutreachCreate


class FakeService:
    def __init__(self, readiness):
        self.readiness = readiness
        self.create_calls = []

    def candidate_readiness(self, place_id):
        assert place_id == "place-1"
        return self.readiness

    def create_item(self, place_id, channel, to_address):
        self.create_calls.append((place_id, channel, to_address))
        return {"id": "queue-1", "place_id": place_id, "channel": channel}


def test_queue_route_blocks_prospect_that_fails_readiness(monkeypatch):
    service = FakeService(
        {
            "eligible": False,
            "reasons": ["Business has fewer than 10 Google reviews."],
            "preferred_channel": "email",
        }
    )
    monkeypatch.setattr(outreach_route, "get_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        outreach_route.queue_outreach(
            "place-1",
            OutreachCreate(channel="email"),
        )

    assert exc_info.value.status_code == 422
    assert "fewer than 10 Google reviews" in str(exc_info.value.detail)
    assert service.create_calls == []


def test_queue_route_allows_ready_prospect(monkeypatch):
    service = FakeService(
        {
            "eligible": True,
            "reasons": [],
            "preferred_channel": "email",
        }
    )
    monkeypatch.setattr(outreach_route, "get_service", lambda: service)

    result = outreach_route.queue_outreach(
        "place-1",
        OutreachCreate(channel="email"),
    )

    assert result["id"] == "queue-1"
    assert service.create_calls == [("place-1", "email", None)]


def test_queue_route_preserves_idempotent_existing_queue(monkeypatch):
    service = FakeService(
        {
            "eligible": False,
            "reasons": ["Prospect is already in the outreach queue."],
            "preferred_channel": "email",
        }
    )
    monkeypatch.setattr(outreach_route, "get_service", lambda: service)

    result = outreach_route.queue_outreach(
        "place-1",
        OutreachCreate(channel="email"),
    )

    assert result["id"] == "queue-1"
    assert service.create_calls == [("place-1", "email", None)]
