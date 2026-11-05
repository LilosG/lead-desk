"""Campaigns keep offers apart, and share the rules that protect a business.

Runs against real SQL, because the separation lives in the board's queries.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from bs4 import BeautifulSoup
from psycopg_pool import ConnectionPool

PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import scoring as S  # noqa: E402
import site_signals  # noqa: E402
from enrich import SiteFindings  # noqa: E402
from store import PostgresStore  # noqa: E402

from app.campaigns import EV_PERMITS, EV_SERVICE_SQL, SEO_WEBSITES  # noqa: E402
from app.integrations.gmail import GmailDraftResult  # noqa: E402
from app.repositories.outreach import OutreachRepository  # noqa: E402
from app.repositories.outreach_board import OutreachBoardRepository  # noqa: E402
from app.repositories.outreach_gmail import OutreachGmailRepository  # noqa: E402
from app.services.ev_offer import ev_evidence, write_email  # noqa: E402
from app.services.outreach import OutreachBlocked, OutreachService  # noqa: E402
from app.services.outreach_board import OutreachBoardService, gmail_block_reason, next_step  # noqa: E402
from app.services.outreach_bulk import fast_track  # noqa: E402
from app.services.outreach_draft_sync import OutreachDraftSyncService  # noqa: E402

OVERVIEW = "https://demo.example.com/ev"
PHOENIX = "Oro Valley, AZ, USA"
EV_TITLES = ["Panel Upgrades", "EV Charger Installation"]


def _biz(pid: str, city: str = "Oro Valley", state: str = "AZ", **kw) -> dict:
    row = {
        "place_id": pid, "name": f"{pid} Electric LLC", "vertical": "electrician",
        "matched_verticals": ["electrician"], "market": PHOENIX, "city": city, "state": state,
        "primary_type": "electrician", "types": ["electrician"],
        "business_status": "OPERATIONAL", "phone": "(520) 555-0100",
        "website_url": f"https://{pid}.example.com", "rating": 4.7, "review_count": 60,
        "has_hours": True, "photo_count": 10, "last_review_days": 20,
        "recent_reviews_90d": 2, "is_franchise": False,
    }
    row.update(kw)
    return row


def _site(pid: str, *, titles: list[str] | None = None, ev_signal: bool = False) -> SiteFindings:
    f = SiteFindings(place_id=pid)
    f.is_reachable = True
    f.has_ssl = True
    f.title = "Local Electrician"
    f.title_length = len(f.title)
    f.meta_description = "Residential and commercial electrical work."
    f.h1_count = 1
    f.word_count = 800
    f.contact_page_url = f"https://{pid}.example.com/contact"
    f.emails_found = [f"hello@{pid}.example.com"]
    f.offering_titles = titles or []
    f.site_signals = {"ev_service": ev_signal}
    return f


@pytest.fixture(scope="module")
def pool():
    dsn = os.environ.get("DATABASE_URL")
    store = PostgresStore(dsn)
    if not store.ping():
        pytest.skip("PostgreSQL not available")
    if store.get_active_run():
        pytest.skip("another run is active in this database")
    leads = {
        "camp-title": (_biz("camp-title"), _site("camp-title", titles=EV_TITLES)),
        "camp-signal": (_biz("camp-signal"), _site("camp-signal", ev_signal=True)),
        "camp-noev": (_biz("camp-noev"), _site("camp-noev", titles=["Panel Upgrades"])),
        "camp-plumber": (_biz("camp-plumber", vertical="plumber", primary_type="plumber",
                              types=["plumber"], matched_verticals=["plumber"]),
                         _site("camp-plumber", titles=EV_TITLES)),
        "camp-frisco": (_biz("camp-frisco", city="Frisco", state="TX"),
                        _site("camp-frisco", titles=EV_TITLES)),
        "camp-franchise": (_biz("camp-franchise", is_franchise=True),
                           _site("camp-franchise", titles=EV_TITLES)),
    }
    businesses = [biz for biz, _ in leads.values()]
    enrichment = {pid: site for pid, (_, site) in leads.items()}
    run_id = store.start_run(PHOENIX, ["electrician"], 0)
    try:
        scored, baselines = S.score_all(businesses, enrichment)
        store.save_businesses(businesses, run_id)
        store.save_enrichment(enrichment)
        store.save_baselines(baselines, run_id)
        store.save_scores(scored, run_id)
        store.finish_run(run_id)
    except Exception:
        store.abandon_run(run_id, "campaign seed failed")
        raise
    with ConnectionPool(dsn, open=True, kwargs={"row_factory": psycopg.rows.dict_row}) as connection_pool:
        yield connection_pool
        with connection_pool.connection() as conn:
            for table in ("outreach_queue_events", "outreach_queue", "score_evidence", "scores",
                          "website_enrichment", "business_vertical_memberships", "businesses"):
                conn.execute(f"delete from {table} where place_id like 'camp-%'")


@pytest.fixture(autouse=True)
def clean_queue(request):
    yield
    if "pool" not in request.fixturenames:
        return
    pool = request.getfixturevalue("pool")
    with pool.connection() as conn:
        conn.execute("delete from outreach_queue where place_id like 'camp-%'")
        conn.execute("delete from suppression where email like '%.example.com'")


@pytest.fixture
def outreach(pool):
    return OutreachService(OutreachRepository(pool), ev_overview_url=OVERVIEW)


@pytest.fixture
def board(pool):
    return OutreachBoardService(
        OutreachBoardRepository(pool), gmail_repository=OutreachGmailRepository(pool), gmail=None,
    )


def _names(board_service, campaign, stage="to_prep"):
    data = board_service.board(campaign=campaign, stage=stage, page=1, page_size=100,
                               q="camp-", vertical=None, market=None, qualified_only=False)
    return {row["place_id"]: row for row in data["items"]}


def _touch(pool, item_id, **columns):
    sets = ", ".join(f"{key} = %s" for key in columns)
    with pool.connection() as conn:
        conn.execute(f"update outreach_queue set {sets} where id = %s::uuid",
                     [*columns.values(), item_id])


def test_ev_campaign_only_lists_electricians_that_show_ev_work(board):
    assert set(_names(board, EV_PERMITS)) == {"camp-title", "camp-signal"}


def test_qualified_filter_does_not_hide_ev_leads(board):
    data = board.board(campaign=EV_PERMITS, stage="to_prep", page=1, page_size=100,
                       q="camp-", vertical=None, market=None, qualified_only=True)
    assert {row["place_id"] for row in data["items"]} == {"camp-title", "camp-signal"}


def test_seo_campaign_is_unchanged_by_the_ev_rules(board):
    assert {"camp-noev", "camp-plumber", "camp-frisco"} <= set(_names(board, SEO_WEBSITES))


def test_a_business_moves_through_each_campaign_separately(outreach, board):
    ev = fast_track(outreach, None, "camp-title", gmail=False, campaign_key=EV_PERMITS)
    assert ev["ok"], ev
    assert "audit" not in ev["steps"]

    assert "camp-title" not in _names(board, EV_PERMITS)
    assert "camp-title" in _names(board, SEO_WEBSITES)
    assert "camp-title" in _names(board, EV_PERMITS, "review") or \
        "camp-title" in _names(board, EV_PERMITS, "attention")

    seo = outreach.create_item("camp-title", "email", None, SEO_WEBSITES)
    assert seo["id"] != ev["item_id"]
    assert outreach.create_item("camp-title", "email", None, EV_PERMITS)["id"] == ev["item_id"]


def test_the_ev_email_says_only_what_is_verified(outreach):
    result = fast_track(outreach, None, "camp-title", gmail=False, campaign_key=EV_PERMITS)
    item = outreach.repository.get_item(result["item_id"])

    assert item["subject"] == "Cutting EV permit paperwork at camp-title Electric"
    assert item["body"].startswith("Hi there,\n\nOro Valley wants a site plan, one-line diagram and load calculation on EV jobs.")
    assert "gives you back 26 hours a month" in item["body"]
    assert OVERVIEW in item["body"]
    assert "no thanks" in item["body"]
    assert item["claim_signal"] == "ev_permit_offer"
    assert item["verification_status"] == "verified"
    assert "orovalleyaz.gov" in item["verification_note"]


def test_ev_drafts_wait_for_the_overview_page(pool):
    outreach = OutreachService(OutreachRepository(pool))
    result = fast_track(outreach, None, "camp-title", gmail=False, campaign_key=EV_PERMITS)
    assert result["failed_step"] == "draft"
    assert "EV_OVERVIEW_URL" in result["detail"]


def test_a_lead_without_ev_evidence_cannot_get_the_ev_email(outreach):
    result = fast_track(outreach, None, "camp-noev", gmail=False, campaign_key=EV_PERMITS)
    assert result["failed_step"] == "draft"
    assert "doesn't show EV work" in result["detail"]


def test_only_electricians_can_get_the_ev_email(outreach):
    result = fast_track(outreach, None, "camp-plumber", gmail=False, campaign_key=EV_PERMITS)
    assert result["failed_step"] == "draft"
    assert "only for electricians" in result["detail"]


def test_regenerating_a_synced_ev_draft_updates_gmail_without_ai(pool, outreach):
    class Gmail:
        calls = []

        def update_draft(self, draft_id, **kwargs):
            self.calls.append(kwargs)
            return GmailDraftResult(draft_id=draft_id, message_id="m2")

    result = fast_track(outreach, None, "camp-title", gmail=False, campaign_key=EV_PERMITS)
    item = outreach.repository.get_item(result["item_id"])
    _touch(pool, item["id"], gmail_draft_id="d1", gmail_message_id="m1", body="edited", status="approved")
    item = outreach.repository.get_item(item["id"])
    outreach.gmail = Gmail()

    updated = OutreachDraftSyncService(
        outreach=outreach, gmail_repository=OutreachGmailRepository(pool),
    ).regenerate(item["id"], expected_version=item["version"])

    assert updated["claim_signal"] == "ev_permit_offer"
    assert "drafts the full permit packet" in updated["body"]
    assert Gmail.calls[0]["attachments"] is None


def test_contact_in_one_campaign_holds_the_other_for_30_days(pool, outreach, board):
    seo = outreach.create_item("camp-signal", "email", None, SEO_WEBSITES)
    _touch(pool, seo["id"], status="contacted", contacted_at=datetime.now(timezone.utc))

    row = _names(board, EV_PERMITS)["camp-signal"]
    assert row["next_step"].startswith("Already in SEO + Websites outreach. Wait until")

    result = fast_track(outreach, None, "camp-signal", gmail=False, campaign_key=EV_PERMITS)
    assert result["failed_step"] == "cooldown"

    _touch(pool, seo["id"], contacted_at=datetime.now(timezone.utc) - timedelta(days=31))
    assert fast_track(outreach, None, "camp-signal", gmail=False, campaign_key=EV_PERMITS)["ok"]


def test_a_draft_sitting_in_gmail_also_holds_the_other_campaign(pool, outreach):
    seo = outreach.create_item("camp-signal", "email", None, SEO_WEBSITES)
    _touch(pool, seo["id"], status="approved", gmail_draft_id="d9",
           gmail_draft_created_at=datetime.now(timezone.utc))
    assert outreach.cooldown_block("camp-signal", EV_PERMITS)
    assert outreach.cooldown_block("camp-signal", SEO_WEBSITES) is None


def test_do_not_contact_covers_every_campaign(pool, outreach, board):
    seo = outreach.create_item("camp-signal", "email", "hello@camp-signal.example.com", SEO_WEBSITES)
    ev = outreach.create_item("camp-signal", "email", "hello@camp-signal.example.com", EV_PERMITS)

    assert outreach.repository.do_not_contact(seo["id"])["updated"] == 2

    assert outreach.repository.get_item(ev["id"])["status"] == "suppressed"
    assert outreach.repository.is_suppressed("Hello@camp-signal.example.com")
    assert "camp-signal" in _names(board, EV_PERMITS, "closed")
    with pytest.raises(OutreachBlocked):
        outreach.create_item("camp-signal", "phone", None, SEO_WEBSITES)


def test_do_not_contact_removes_a_lead_with_no_stored_email_from_other_campaigns(outreach, board):
    item = outreach.create_item("camp-title", "email", None, SEO_WEBSITES)
    outreach.repository.do_not_contact(item["id"])

    assert "camp-title" not in _names(board, EV_PERMITS)
    with pytest.raises(OutreachBlocked):
        outreach.create_item("camp-title", "email", None, EV_PERMITS)


def test_reply_rates_are_kept_per_campaign(pool, outreach, board):
    now = datetime.now(timezone.utc)
    first = outreach.create_item("camp-title", "email", None, EV_PERMITS)
    second = outreach.create_item("camp-signal", "email", None, EV_PERMITS)
    _touch(pool, first["id"], status="replied", contacted_at=now)
    _touch(pool, second["id"], status="contacted", contacted_at=now)

    rows = {row["key"]: row for row in board.campaigns()}
    assert (rows[EV_PERMITS]["sent"], rows[EV_PERMITS]["replied"], rows[EV_PERMITS]["reply_rate"]) == (2, 1, 50.0)
    assert rows[EV_PERMITS]["prep_label"] == "Email + Gmail draft"

    assert board.campaign_results(EV_PERMITS) == [{
        "market": PHOENIX, "vertical": "electrician", "sent": 2, "replied": 1, "reply_rate": 50.0,
    }]


def test_campaign_routes(client, pool):
    assert [c["key"] for c in client.get("/api/outreach/campaigns").json()["campaigns"]][:2] == [
        SEO_WEBSITES, EV_PERMITS,
    ]
    assert client.get("/api/outreach/board", params={"campaign": "nope"}).status_code == 404
    assert client.get("/api/outreach/campaigns/nope/results").status_code == 404
    response = client.get("/api/outreach/board", params={"campaign": EV_PERMITS, "q": "camp-"})
    assert response.status_code == 200
    assert {row["place_id"] for row in response.json()["items"]} == {"camp-title", "camp-signal"}
    assert client.post("/api/outreach/fast-track/camp-title", json={"campaign": "nope"}).status_code == 404


@pytest.mark.parametrize("text,expected", [
    ("EV charger installation", True),
    ("EV Chargers", True),
    ("Tesla Wall Connector charging", True),
    ("electric vehicle charging stations", True),
    ("Level 2 charger for your EV", True),
    ("EVSE install", True),
    ("every charge", False),
    ("Levy charge notice", False),
    ("Service charge may apply", False),
    ("Panel upgrades", False),
    ("Electric car charger install", True),
    ("Car charging at home", True),
    ("Vehicle charging for your garage", True),
    ("Charging stations", True),
    ("Level 2 chargers", True),
    ("Wall Connector setup", True),
    ("EV installation", True),
    ("Electric vehicle ready homes", True),
    ("Car audio repair", False),
    ("We take charge of your wiring", False),
    ("Credit card charge", False),
    ("Level 2 technician", False),
    ("Every install is inspected", False),
    ("Seven outlets", False),
])
def test_site_signal_and_board_filter_agree(pool, text, expected):
    assert bool(site_signals.EV_SERVICE.search(text)) is expected
    with pool.connection() as conn:
        row = conn.execute("select %s ~* %s as match", (text, EV_SERVICE_SQL)).fetchone()
    assert row["match"] is expected


def test_collect_reads_ev_work_from_the_homepage():
    html = "<html><title>Sparks</title><body><p>We install EV chargers at home.</p></body></html>"
    signals = site_signals.collect(
        business={"name": "Sparks", "city": "Tucson", "vertical": "electrician"},
        soup=BeautifulSoup(html, "html.parser"), html=html,
        final_url="https://sparks.example.com/", headers={}, word_count=6, robots=None,
        has_sitemap=False, offering_paths=[], location_paths=[], offering_words=[],
    )
    assert signals["ev_service"] is True


def test_collect_reads_ev_work_from_a_link_with_no_text():
    html = '<html><title>Sparks</title><body><a href="/services/ev-charger-installation/"><img src="a.png"></a></body></html>'
    signals = site_signals.collect(
        business={"name": "Sparks", "city": "Tucson", "vertical": "electrician"},
        soup=BeautifulSoup(html, "html.parser"), html=html,
        final_url="https://sparks.example.com/", headers={}, word_count=1, robots=None,
        has_sitemap=False, offering_paths=[], location_paths=[], offering_words=[],
    )
    assert signals["ev_service"] is True


def test_ev_evidence_uses_every_source_on_file():
    assert ev_evidence({"site_signals": {"ev_service": True}}) == "homepage text"
    assert ev_evidence({"offering_titles": EV_TITLES}) == "service link"
    assert ev_evidence({"site_description": "We add EV chargers."}) == "page description"
    assert ev_evidence({"site_title": "Sparks Electric"}) is None


def test_unknown_cities_get_no_permit_claim():
    written = write_email({"place_id": "p", "city": "Boise", "state": "ID", "name": "Sparks"}, OVERVIEW)
    assert "Boise" not in written["body"]
    assert written["body"].startswith("Hi there,\n\nEvery EV install means permit paperwork")
    assert written["subject"] == "Cutting EV permit paperwork at Sparks"


def test_ev_copy_has_no_price_or_approval_promise():
    written = write_email({"place_id": "p", "city": "Brea", "state": "CA", "name": "Sparks"}, OVERVIEW)
    assert not re.search(r"\$|guarantee|approv", written["body"], re.I)


def test_block_reason_and_next_step_use_the_campaign():
    item = {"campaign_key": EV_PERMITS, "status": "draft_ready", "channel": "email",
            "stage": "review", "to_address": "a@b.co", "subject": "s", "body": "b",
            "verification_status": "verified", "claim_signal": "audit_report",
            "gmail_draft_id": None, "pending_operation": False}
    assert "campaign's email" in (gmail_block_reason(item, gmail_connected=True) or "")
    assert next_step({"stage": "to_prep", "campaign_key": EV_PERMITS}) == "Draft the email"


def test_ev_leads_rank_by_ev_proof_not_the_seo_score(pool, board):
    with pool.connection() as conn:
        conn.execute("""update website_enrichment
                        set site_signals = site_signals || '{"ev_service": true, "ev_strength": "page",
                                                              "ev_brands": ["Tesla"]}'::jsonb
                        where place_id = 'camp-signal'""")
    try:
        data = board.board(campaign=EV_PERMITS, stage="to_prep", page=1, page_size=100,
                           q=None, vertical=None, market=None, qualified_only=False)
        assert data["items"][0]["place_id"] == "camp-signal"
        assert data["items"][0]["lead_note"].startswith("EV page · Tesla")
    finally:
        with pool.connection() as conn:
            conn.execute("""update website_enrichment set site_signals = '{"ev_service": true}'::jsonb
                            where place_id = 'camp-signal'""")


def test_the_seo_board_flags_leads_that_should_get_ev_first(board):
    data = board.board(campaign=SEO_WEBSITES, stage="to_prep", page=1, page_size=100,
                       q=None, vertical=None, market=None, qualified_only=False)
    by_id = {row["place_id"]: row for row in data["items"]}
    assert by_id["camp-title"]["lead_note"] == "Shows EV work: pitch EV Permits first"
    assert by_id["camp-noev"]["lead_note"] is None
    ids = [row["place_id"] for row in data["items"]]
    assert ids.index("camp-noev") < ids.index("camp-title")
