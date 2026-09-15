from math import ceil

from pipeline import config as market_config


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["app"] == "Lead Desk"


def test_overview_invariants(client):
    response = client.get("/api/overview")
    assert response.status_code == 200
    body = response.json()

    count_keys = {
        "prospects",
        "tier_a",
        "tier_b",
        "tier_c",
        "tier_d",
        "emailable",
        "phone_only",
        "no_contact",
        "no_website",
        "confirmed_trading",
        "category_opportunity",
        "established",
        "manual_check",
        "established_emailable",
        "established_phone_only",
        "outreach_candidates",
    }

    for key in count_keys:
        assert isinstance(body[key], int)
        assert body[key] >= 0

    assert body["prospects"] == (
        body["tier_a"]
        + body["tier_b"]
        + body["tier_c"]
        + body["tier_d"]
    )
    assert body["outreach_candidates"] <= body["prospects"]


def test_confirmed_trading_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 25, "trading": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["confirmed_trading"] is True for item in body["items"])


def test_established_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 25, "established": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["established"] is True for item in body["items"])


def test_category_opportunity_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 25, "category_opportunity": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["category_opportunity"] is True for item in body["items"])


def test_pagination_is_server_side(client):
    first = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 25},
    )
    assert first.status_code == 200
    first_body = first.json()
    total = first_body["pagination"]["total"]

    second = client.get(
        "/api/prospects",
        params={"page": 2, "page_size": 25},
    )
    assert second.status_code == 200
    body = second.json()
    assert len(body["items"]) <= 25
    assert body["pagination"] == {
        "page": 2,
        "page_size": 25,
        "total": total,
        "total_pages": ceil(total / 25) if total else 0,
    }


def test_unknown_prospect_returns_404(client):
    response = client.get("/api/prospects/not-a-real-place-id")
    assert response.status_code == 404


def test_runs_contract(client):
    response = client.get(
        "/api/runs",
        params={"page": 1, "page_size": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] >= len(body["items"])
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["page_size"] == 5
    assert len(body["items"]) <= 5
    assert all("status" in item for item in body["items"])


def test_prospect_filter_meta_uses_configured_market(client):
    response = client.get("/api/prospects/meta")
    assert response.status_code == 200
    body = response.json()

    unfiltered = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 1},
    )
    assert unfiltered.status_code == 200

    assert body["total_prospects"] == unfiltered.json()["pagination"]["total"]
    assert body["tiers"] == ["A", "B", "C", "D"]
    assert set(market_config.TARGET_CITIES).issubset(body["cities"])
    assert set(market_config.VERTICALS).issubset(body["verticals"])


def test_real_prospect_detail_from_operational_inventory(client):
    listing = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 1},
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items, "operational inventory should contain at least one prospect"

    place_id = items[0]["place_id"]
    response = client.get(f"/api/prospects/{place_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["place_id"] == place_id
    assert isinstance(body["findings"], list)
    assert body["workflow"]["status"] in {
        "new",
        "researching",
        "qualified",
        "outreach_ready",
        "contacted",
        "replied",
        "won",
        "lost",
        "disqualified",
    }
    assert isinstance(body["workflow_events"], list)


def test_vertical_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 25, "vertical": "electrician"},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["vertical"] == "electrician" for item in body["items"])
