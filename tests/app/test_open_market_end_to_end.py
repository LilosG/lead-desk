"""End to end: two non-trade niches in two markets, through scoring, storage,
the prospects API, batch audit reports and the PDF.

Seeds a completed run directly through the pipeline's own scoring and
PostgresStore, so the views, labels, market filter and peer comparison are
exercised against real SQL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import scoring as S  # noqa: E402
from enrich import SiteFindings  # noqa: E402
from store import PostgresStore  # noqa: E402


AUSTIN = "Austin, TX, USA"
SCOTTSDALE = "Scottsdale, AZ, USA"


def _biz(pid: str, name: str, vertical: str, market: str, city: str, state: str, **kw) -> dict:
    row = {
        "place_id": pid,
        "name": name,
        "vertical": vertical,
        "matched_verticals": [vertical],
        "market": market,
        "city": city,
        "state": state,
        "primary_type": "dentist" if vertical == "dentist" else "spa",
        "types": ["dentist"] if vertical == "dentist" else ["spa"],
        "business_status": "OPERATIONAL",
        "phone": "(512) 555-0100",
        "website_url": f"https://{pid}.example.com",
        "rating": 4.7,
        "review_count": 60,
        "has_hours": True,
        "photo_count": 10,
        "last_review_days": 20,
        "recent_reviews_90d": 2,
        "is_franchise": False,
    }
    row.update(kw)
    return row


def _site(pid: str, **kw) -> SiteFindings:
    f = SiteFindings(place_id=pid)
    f.is_reachable = True
    f.has_ssl = True
    f.title = "Example Practice | Austin"
    f.title_length = len(f.title)
    f.meta_description = "A local practice."
    f.h1_count = 1
    f.word_count = 800
    f.has_localbusiness_schema = True
    f.has_service_pages = True
    f.has_city_pages = True
    f.has_contact_form = True
    f.contact_page_url = f"https://{pid}.example.com/contact"
    f.emails_found = [f"hello@{pid}.example.com"]
    f.nap_matches_gbp = True
    f.psi_performance = 80
    for key, value in kw.items():
        setattr(f, key, value)
    return f


@pytest.fixture(scope="module")
def seeded_run():
    dsn = os.environ.get("DATABASE_URL")
    store = PostgresStore(dsn)
    if not store.ping():
        pytest.skip("PostgreSQL not available")
    if store.get_active_run():
        pytest.skip("another run is active in this database")

    businesses = []
    enrichment = {}
    for i in range(9):
        pid = f"e2e-dent-{i}"
        businesses.append(_biz(pid, f"Austin Dental {i}", "dentist", AUSTIN, "Austin", "TX",
                               review_count=100 + i * 20))
        enrichment[pid] = _site(pid)
    for i in range(9):
        pid = f"e2e-spa-{i}"
        businesses.append(_biz(pid, f"Desert Glow {i}", "med_spa", SCOTTSDALE, "Scottsdale", "AZ",
                               review_count=20 + i * 5))
        enrichment[pid] = _site(pid)

    # The lead under test: an established dentist (at/above median, recently
    # reviewed) with real gaps, in Austin.
    target = _biz("e2e-target", "Lakeline Family Dentistry", "dentist", AUSTIN, "Austin", "TX",
                  review_count=190, rating=4.8)
    businesses.append(target)
    enrichment["e2e-target"] = _site(
        "e2e-target",
        has_localbusiness_schema=False,
        has_service_pages=False,
        has_city_pages=False,
        offering_titles=["Dental Implants", "Invisalign", "Teeth Whitening"],
        psi_performance=38,
        psi_lcp_ms=5400,
    )
    # A franchise med spa with no website: kept, labelled, not dropped.
    businesses.append(_biz("e2e-franchise", "LaserAway Scottsdale", "med_spa", SCOTTSDALE,
                           "Scottsdale", "AZ", website_url=None, is_franchise=True,
                           review_count=3))

    run_id = store.start_run("Austin, TX • Scottsdale, AZ", ["dentist", "med_spa"], 0)
    try:
        scored, baselines = S.score_all(businesses, enrichment)
        store.save_businesses(businesses, run_id)
        store.save_enrichment(enrichment)
        store.save_baselines(baselines, run_id)
        store.save_scores(scored, run_id)
        store.finish_run(run_id)
    except Exception:
        store.abandon_run(run_id, "e2e seed failed")
        raise
    return {s.place_id: s for s in scored}


def test_franchise_and_no_website_leads_are_kept_and_labelled(client, seeded_run):
    response = client.get("/api/prospects", params={"label": "franchise", "page_size": 100})
    assert response.status_code == 200
    items = {item["place_id"]: item for item in response.json()["items"]}
    assert "e2e-franchise" in items
    assert {"franchise", "no_website"} <= set(items["e2e-franchise"]["labels"])
    assert items["e2e-franchise"]["market"] == SCOTTSDALE


def test_market_filter_and_established_label(client, seeded_run):
    response = client.get("/api/prospects", params={"market": AUSTIN, "page_size": 100})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items and all(item["market"] == AUSTIN for item in items)

    target = next(item for item in items if item["place_id"] == "e2e-target")
    assert target["established"] is True
    assert "established" in target["labels"]

    meta = client.get("/api/prospects/meta").json()
    assert AUSTIN in meta["markets"] and SCOTTSDALE in meta["markets"]
    assert meta["labels"]["established"] == "Established"


def test_findings_use_niche_and_own_market(client, seeded_run):
    detail = client.get("/api/prospects/e2e-target").json()
    findings = {f["signal"]: f for f in detail["findings"]}
    assert "procedure pages" in findings["no_service_pages"]["finding"]
    assert detail["website_audit"]["offering_titles"] == [
        "Dental Implants", "Invisalign", "Teeth Whitening",
    ]

    spa = seeded_run["e2e-spa-0"]
    for e in spa.evidence:
        if e.signal.startswith("reviews_"):
            assert "Scottsdale, AZ" in e.finding
            assert "Austin" not in e.finding


def test_batch_audit_reports_with_local_comparison_and_pdf(client, seeded_run):
    response = client.post(
        "/api/audit-reports/batch",
        json={"place_ids": ["e2e-target", "e2e-franchise", "e2e-dent-1"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    by_place = {item["place_id"]: item for item in body["items"]}
    assert by_place["e2e-target"]["status"] == "created"
    assert by_place["e2e-franchise"]["status"] == "created"  # no-website finding

    report_id = by_place["e2e-target"]["report_id"]
    report = client.get(f"/api/audit-reports/{report_id}").json()
    snapshot = report["snapshot"]
    signals = {f["signal"] for f in snapshot["findings"]}
    assert {"no_service_pages", "psi_mobile_poor"} <= signals

    comparison = snapshot["market_comparison"]
    assert comparison["market"] == "Austin, TX"
    assert comparison["niche"] == "dentist"
    assert comparison["sample_size"] == 10
    assert all("Desert Glow" not in leader["name"] for leader in comparison["leaders"])
    assert snapshot["next_step"]["text"]

    pdf = client.get(f"/api/audit-reports/{report_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_demo_defaults_are_prefilled_for_one_click_mockups(client, seeded_run):
    response = client.get("/api/demo-sites/prospects/e2e-target/options")
    assert response.status_code == 200, response.text
    defaults = response.json()["defaults"]
    # The dentist's own services first, then core dental services to fill six cards.
    assert defaults["services"][:3] == ["Dental Implants", "Invisalign", "Teeth Whitening"]
    assert len(defaults["services"]) == 6
    assert "General Dentistry" in defaults["services"]
    assert defaults["service_areas"][0] == "Austin"


def test_set_website_by_hand_rescores_and_audits_the_site(client, seeded_run, monkeypatch):
    import enrich as E

    def fake_crawl(business, session=None):
        f = _site(business["place_id"])
        f.resolved_url = business["website_url"]
        return f

    monkeypatch.setattr(E, "crawl_site", fake_crawl)
    monkeypatch.setattr(E, "run_psi", lambda url, key: None)
    monkeypatch.setattr("threading.Thread.start", lambda self: None)  # no background run in tests

    bad = client.post("/api/prospects/e2e-franchise/website", json={"url": "not a site"})
    assert bad.status_code == 422

    response = client.post("/api/prospects/e2e-franchise/website",
                           json={"url": "realspa.example.com"})
    assert response.status_code == 200, response.text
    assert response.json()["website_url"] == "https://realspa.example.com"

    detail = client.get("/api/prospects/e2e-franchise").json()
    signals = {f["signal"] for f in detail["findings"]}
    assert "website_not_on_gbp" in signals and "no_website" not in signals
    assert detail["website_audit"]["site_source"] == "manual"

    created = client.post("/api/audit-reports/batch", json={"place_ids": ["e2e-franchise"]}).json()
    item = created["items"][0]
    assert item["status"] == "created", item
    report_id = item["report_id"]
    snapshot = client.get(f"/api/audit-reports/{report_id}").json()["snapshot"]
    assert snapshot["business"]["website_url"] == "https://realspa.example.com"
    assert snapshot["business"]["site_on_google"] is False


def test_a_site_that_blocks_crawlers_can_still_be_linked_by_hand(client, seeded_run, monkeypatch):
    import enrich as E

    def blocked_crawl(business, session=None):
        return E.SiteFindings(place_id=business["place_id"], http_status=403,
                              crawl_error="blocked_403",
                              resolved_url=business["website_url"])

    monkeypatch.setattr(E, "crawl_site", blocked_crawl)
    monkeypatch.setattr("threading.Thread.start", lambda self: None)  # no background run in tests

    response = client.post("/api/prospects/e2e-franchise/website",
                           json={"url": "https://tucson-site.example"})
    assert response.status_code == 200, response.text
    assert response.json()["blocked"] is True

    detail = client.get("/api/prospects/e2e-franchise").json()
    signals = {f["signal"] for f in detail["findings"]}
    assert {"crawl_blocked", "website_not_on_gbp"} <= signals
    assert "no_website" not in signals and "site_down" not in signals
    assert detail["website_audit"]["site_source"] == "manual"


def test_a_dead_address_is_still_refused(client, seeded_run, monkeypatch):
    import enrich as E

    monkeypatch.setattr(E, "crawl_site", lambda business, session=None: E.SiteFindings(
        place_id=business["place_id"], crawl_error="dns_failure"))
    response = client.post("/api/prospects/e2e-franchise/website", json={"url": "https://gone.example"})
    assert response.status_code == 422


def test_run_figures_cover_only_the_markets_that_sweep_searched(client, seeded_run):
    """Earlier markets are re-scored by a merged sweep but aren't its results."""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        run_id = conn.execute(
            "select run_id from scores where place_id = 'e2e-franchise' "
            "order by scored_at limit 1"
        ).fetchone()["run_id"]
        counts = conn.execute(
            "select count(*) as everything, count(*) filter (where market = %s) as swept "
            "from scores where run_id = %s", (AUSTIN, run_id),
        ).fetchone()
        job = conn.execute(
            "insert into sweep_jobs (run_id, verticals, cities) values (%s, %s, %s) returning id",
            (run_id, ["dentist"], [AUSTIN]),
        ).fetchone()["id"]
        conn.commit()
    assert 0 < counts["swept"] < counts["everything"]
    try:
        assert client.get(f"/api/runs/{run_id}").json()["businesses_scored"] == counts["swept"]
        assert client.get(f"/api/runs/{run_id}/funnel").json()["total"] == counts["swept"]
    finally:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute("delete from sweep_jobs where id = %s", (job,))
            conn.commit()


def test_an_email_added_by_hand_comes_first_and_regrades_the_lead(client, seeded_run):
    """A hand-found email outranks the crawl and survives into outreach."""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        place = conn.execute(
            """
            select w.place_id
            from v_lead_worklist w
            left join v_lead_findings f on f.place_id = w.place_id
            where not coalesce(f.needs_manual_check, false)
              and not exists (select 1 from outreach_queue q where q.place_id = w.place_id)
            order by w.place_id
            limit 1
            """
        ).fetchone()
    assert place, "seed data should include a lead outside the queue"
    pid = place["place_id"]

    assert client.post(f"/api/prospects/{pid}/contact", json={"email": "nope"}).status_code == 422
    assert client.post(f"/api/prospects/{pid}/contact", json={}).status_code == 422
    assert client.post(f"/api/prospects/{pid}/contact",
                       json={"email": "Owner@Example.com"}).status_code == 200

    assert client.get(f"/api/prospects/{pid}").json()["email"] == "owner@example.com"
    board = client.get("/api/outreach/board?stage=to_prep&q=owner@example.com").json()
    assert [row["place_id"] for row in board["items"]] == [pid]

    runs = client.get("/api/runs?page_size=100").json()["items"]
    assert not any(r["geo_label"].startswith("Contact updated") for r in runs)


def test_premium_v4_demo_builds_through_the_api(client, seeded_run, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_SITE_ROOT", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        options = client.get("/api/demo-sites/prospects/e2e-target/options").json()
        assert options["templates"][0]["key"] == "premium-v4"
        response = client.post("/api/demo-sites/prospects/e2e-target", json={
            "template_key": "premium-v4", "services": [], "service_areas": [], "use_site_branding": False,
        })
        assert response.status_code == 201, response.text
        demo = response.json()
        assert demo["brand_snapshot"]["style"] == "clean"  # a dentist
        preview = client.get(f"/api/demo-sites/{demo['id']}/preview")
        assert preview.status_code == 200 and 'class="style-clean"' in preview.text
        assert "Dental Implants" in preview.text
    finally:
        get_settings.cache_clear()
