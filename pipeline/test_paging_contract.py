#!/usr/bin/env python3
from __future__ import annotations

from unittest.mock import patch

import config as C
from discover import CostLedger, GridPoint, PlacesClient


def main() -> int:
    ledger = CostLedger()
    client = PlacesClient("test-key", ledger)
    calls: list[dict] = []

    first_page = {
        "places": [{"id": f"p-{i}"} for i in range(C.RESULTS_PER_PAGE)],
        "nextPageToken": "next-token",
    }
    second_page = {
        "places": [{"id": "p-final"}],
    }
    responses = [first_page, second_page]

    def fake_post(payload: dict) -> dict:
        calls.append(payload)
        return responses.pop(0)

    client._post = fake_post  # type: ignore[method-assign]
    point = GridPoint(lat=32.8, lng=-117.1, radius_m=5000)

    with patch("discover.time.sleep", return_value=None):
        places = list(client.text_search("electrician in San Diego", point=point, max_pages=3))

    assert len(places) == C.RESULTS_PER_PAGE + 1
    assert len(calls) == 2

    initial = calls[0]
    paged = calls[1]
    assert initial["textQuery"] == "electrician in San Diego"
    assert initial["pageSize"] == C.RESULTS_PER_PAGE
    assert "locationBias" in initial

    # This is the load-bearing Google Places contract: every original search
    # parameter must be repeated with pageToken. Token-only paging returns 400.
    assert paged["textQuery"] == initial["textQuery"]
    assert paged["pageSize"] == initial["pageSize"]
    assert paged["locationBias"] == initial["locationBias"]
    assert paged["pageToken"] == "next-token"
    assert ledger.search_calls == 2

    print("PASS Places paging repeats original request parameters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
