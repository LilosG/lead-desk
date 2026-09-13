EXPECTED = {
    "prospects": 251,
    "confirmed_trading": 164,
    "category_opportunity": 19,
    "established": 59,
    "emailable": 93,
    "no_website": 59,
    "manual_check": 11,
    "established_emailable": 41,
    "established_phone_only": 18,
}


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["app"] == "Lead Desk"


def test_overview_parity(client):
    response = client.get("/api/overview")

    assert response.status_code == 200

    body = response.json()

    for key, expected in EXPECTED.items():
        assert body[key] == expected, (
            f"{key}: expected {expected}, got {body[key]}"
        )

    assert body["tier_a"] == 4
    assert body["tier_b"] == 47
    assert body["tier_c"] == 40
    assert body["tier_d"] == 160


def test_confirmed_trading_filter(client):
    response = client.get(
        "/api/prospects",
        params={
            "page": 1,
            "page_size": 1,
            "trading": "true",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["pagination"]["total"] == 164
    assert body["items"][0]["confirmed_trading"] is True


def test_established_filter(client):
    response = client.get(
        "/api/prospects",
        params={
            "page": 1,
            "page_size": 1,
            "established": "true",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["pagination"]["total"] == 59
    assert body["items"][0]["established"] is True


def test_category_opportunity_filter(client):
    response = client.get(
        "/api/prospects",
        params={
            "page": 1,
            "page_size": 1,
            "category_opportunity": "true",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["pagination"]["total"] == 19
    assert body["items"][0]["category_opportunity"] is True


def test_pagination_is_server_side(client):
    response = client.get(
        "/api/prospects",
        params={
            "page": 2,
            "page_size": 25,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body["items"]) == 25

    assert body["pagination"] == {
        "page": 2,
        "page_size": 25,
        "total": 251,
        "total_pages": 11,
    }


def test_unknown_prospect_returns_404(client):
    response = client.get(
        "/api/prospects/not-a-real-place-id"
    )

    assert response.status_code == 404


def test_runs_contract(client):
    response = client.get(
        "/api/runs",
        params={
            "page": 1,
            "page_size": 5,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["pagination"]["total"] == 2

    latest = body["items"][0]

    assert latest["businesses_scored"] == 251
    assert latest["tier_a"] == 4
    assert latest["tier_b"] == 47
    assert latest["tier_c"] == 40
    assert latest["tier_d"] == 160


def test_prospect_filter_meta(client):
    response = client.get("/api/prospects/meta")

    assert response.status_code == 200

    body = response.json()

    assert body["total_prospects"] == 251
    assert body["tiers"] == ["A", "B", "C", "D"]
    assert "El Cajon" in body["cities"]
    assert "electrician" in body["verticals"]


def test_real_prospect_detail(client):
    response = client.get(
        "/api/prospects/ChIJOUNgSehU2YARadzzd7bpc68"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["name"] == "Mauzy Cooling Heating Plumbing Electrical"
    assert body["confirmed_trading"] is True
    assert body["established"] is True
    assert body["real_gap_count"] >= 2
    assert isinstance(body["findings"], list)


def test_real_run_detail(client):
    response = client.get(
        "/api/runs/6acf0d2b-cb19-4004-9c0f-292c83cccde1"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "completed"
    assert body["businesses_scored"] == 251
    assert body["tier_a"] == 4
    assert body["tier_b"] == 47
    assert body["tier_c"] == 40
    assert body["tier_d"] == 160
