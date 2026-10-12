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

import pytest

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
    assert defaults["services"] == ["Dental Implants", "Invisalign", "Teeth Whitening"]
    assert defaults["service_areas"] == ["Austin"]


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
