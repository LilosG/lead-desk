from app.core.database import pool


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

MAUZY_PLACE_ID = "ChIJOUNgSehU2YARadzzd7bpc68"


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
        assert body[key] == expected, f"{key}: expected {expected}, got {body[key]}"
    assert body["tier_a"] == 4
    assert body["tier_b"] == 47
    assert body["tier_c"] == 40
    assert body["tier_d"] == 160


def test_confirmed_trading_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 1, "trading": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 164
    assert body["items"][0]["confirmed_trading"] is True


def test_established_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 1, "established": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 59
    assert body["items"][0]["established"] is True


def test_category_opportunity_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 1, "category_opportunity": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 19
    assert body["items"][0]["category_opportunity"] is True


def test_pagination_is_server_side(client):
    response = client.get(
        "/api/prospects",
        params={"page": 2, "page_size": 25},
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
    response = client.get("/api/prospects/not-a-real-place-id")
    assert response.status_code == 404


def test_runs_contract(client):
    response = client.get(
        "/api/runs",
        params={"page": 1, "page_size": 5},
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
    response = client.get(f"/api/prospects/{MAUZY_PLACE_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Mauzy Cooling Heating Plumbing Electrical"
    assert body["confirmed_trading"] is True
    assert body["established"] is True
    assert body["real_gap_count"] >= 2
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


def test_vertical_filter(client):
    response = client.get(
        "/api/prospects",
        params={"page": 1, "page_size": 25, "vertical": "electrician"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 251
    assert all(item["vertical"] == "electrician" for item in body["items"])


def test_workflow_update_and_optimistic_concurrency(client):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from prospect_workflow_events where place_id = %s",
                (MAUZY_PLACE_ID,),
            )
            cur.execute(
                "delete from prospect_workflow where place_id = %s",
                (MAUZY_PLACE_ID,),
            )
        conn.commit()

    try:
        detail = client.get(f"/api/prospects/{MAUZY_PLACE_ID}")
        assert detail.status_code == 200
        assert detail.json()["workflow"]["version"] == 0

        response = client.patch(
            f"/api/prospects/{MAUZY_PLACE_ID}/workflow",
            json={
                "status": "qualified",
                "priority": "high",
                "next_action": "Prepare verified outreach draft",
                "notes": "API contract test",
                "expected_version": 0,
            },
        )
        assert response.status_code == 200
        state = response.json()
        assert state["status"] == "qualified"
        assert state["priority"] == "high"
        assert state["version"] == 1

        stale = client.patch(
            f"/api/prospects/{MAUZY_PLACE_ID}/workflow",
            json={"status": "contacted", "expected_version": 0},
        )
        assert stale.status_code == 409

        refreshed = client.get(f"/api/prospects/{MAUZY_PLACE_ID}")
        assert refreshed.status_code == 200
        body = refreshed.json()
        assert body["workflow"]["version"] == 1
        assert body["workflow_events"][0]["event_type"] == "created"
    finally:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from prospect_workflow_events where place_id = %s",
                    (MAUZY_PLACE_ID,),
                )
                cur.execute(
                    "delete from prospect_workflow where place_id = %s",
                    (MAUZY_PLACE_ID,),
                )
            conn.commit()
