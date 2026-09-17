from __future__ import annotations

import sys
from pathlib import Path

from app.api.routes.sweeps import SweepCreateRequest
from app.services.sweep_locations import suggest_us_cities


class FakeResponse:
    ok = True
    status_code = 200

    def json(self):
        return {
            "suggestions": [
                {
                    "placePrediction": {
                        "placeId": "austin-place",
                        "text": {"text": "Austin, TX, USA"},
                    }
                },
                {
                    "placePrediction": {
                        "placeId": "austin-place-2",
                        "text": {"text": "Austin, TX, USA"},
                    }
                },
            ]
        }


def test_sweep_request_accepts_city_outside_configured_market():
    payload = SweepCreateRequest(
        verticals=["electrician"],
        cities=["Austin, TX, USA"],
    )

    assert payload.cities == ["Austin, TX, USA"]


def test_city_lookup_uses_google_city_collection(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.services.sweep_locations.requests.post", fake_post)

    items = suggest_us_cities("Austin", api_key="test-key")

    assert items == [{"place_id": "austin-place", "label": "Austin, TX, USA"}]
    assert captured["json"]["includedPrimaryTypes"] == ["(cities)"]
    assert captured["json"]["includedRegionCodes"] == ["us"]
    assert captured["headers"]["X-Goog-Api-Key"] == "test-key"


def test_dynamic_city_geo_filter_matches_city_and_state():
    pipeline_dir = Path(__file__).resolve().parents[2] / "pipeline"
    sys.path.insert(0, str(pipeline_dir))
    try:
        import discover

        assert discover.in_requested_city(
            {"city": "Austin", "state": "TX"},
            "Austin, TX, USA",
        )
        assert not discover.in_requested_city(
            {"city": "Austin", "state": "MN"},
            "Austin, TX, USA",
        )
        assert not discover.in_requested_city(
            {"city": "Dallas", "state": "TX"},
            "Austin, TX, USA",
        )
    finally:
        sys.path.remove(str(pipeline_dir))
