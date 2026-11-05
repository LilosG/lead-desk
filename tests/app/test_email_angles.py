"""The angles and follow-ups: what each email says, and how a sequence runs."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.campaigns import EV_PERMITS, SEO_WEBSITES
from app.integrations.gmail import GmailDraftResult
from app.repositories.outreach import OutreachRepository
from app.repositories.outreach_board import OutreachBoardRepository
from app.repositories.outreach_gmail import OutreachGmailRepository
from app.services import ev_offer, seo_offer
from app.services.email_angles import ANGLES, ROTATION, angle_label, resolve_angle
from app.services.outreach import OutreachBlocked, OutreachService
from app.services.outreach_board import OutreachBoardService

LEAD = {"place_id": "p1", "city": "Oro Valley", "state": "AZ", "name": "Five Point Electric LLC",
        "to_address": "aaron@fivepoint.com",
        "site_signals": {"ev_service": True, "ev_strength": "page", "ev_page_path": "/ev",
                         "ev_brands": ["Tesla", "ChargePoint"]}}
SNAPSHOT = {
    "findings": [{"signal": "reviews_bottom_quartile", "phrase": "reviews",
                  "data": {"reviews": 38, "median": 112}}],
    "business": {"rating": 4.9, "review_count": 38},
    "market_comparison": {
        "market": "Henderson, NV", "niche": "electrician", "median_reviews": 112,
        "business": {"name": "Five Point Electric LLC", "review_count": 38},
        "leaders": [{"name": "Five Point Electric", "review_count": 38},
                    {"name": "Sparks Electric, Inc.", "review_count": 640}],
    },
    "benchmarks": {"sample_size": 29, "rows": [{"metric": "Mobile speed score", "typical": "70"}]},
    "next_step": {"demo_url": "https://demo.example.com/five-point"},
}


def _words(text: str) -> int:
    return len(text.split())


@pytest.mark.parametrize("angle", [a.key for a in ANGLES[EV_PERMITS]])
def test_every_ev_angle_is_short_personal_and_link_free(angle):
    written = ev_offer.write_email(LEAD, angle)
    assert written["body"].startswith("Hi Aaron,")
    assert "Five Point" in written["subject"] + written["body"]
    assert _words(written["body"]) <= 100
    assert len(written["subject"]) <= 40
    assert "http" not in written["body"]


def test_ev_copy_uses_what_the_site_and_city_actually_say():
    body = ev_offer.write_email(LEAD, "free_packet")["body"]
    assert "Saw Five Point installs Tesla and ChargePoint chargers." in body
    assert "Oro Valley wants a site plan, one-line diagram and load calculation" in body
    assert "about 90%" in body
    assert "for free" in body


def test_ev_proof_falls_back_when_the_site_says_less():
    page = {**LEAD, "site_signals": {"ev_service": True, "ev_strength": "page"}}
    assert "Saw the EV charger page on Five Point's site." in ev_offer.write_email(page, "free_packet")["body"]
    mention = {**LEAD, "city": "Boise", "state": "ID", "site_signals": {"ev_service": True}}
    assert "Saw Five Point does EV charger installs in Boise." in ev_offer.write_email(mention, "free_packet")["body"]


def test_ev_subject_uses_a_short_name_that_fits_on_a_phone():
    assert ev_offer.write_email(LEAD, "free_packet")["subject"] == "Five Point's next EV permit"


def test_an_unknown_name_says_so_in_the_note():
    written = ev_offer.write_email({**LEAD, "to_address": "info@fivepoint.com"}, "drawings")
    assert written["body"].startswith("Hi Five Point team,")
    assert "No contact name found." in written["note"]


def test_the_site_owner_name_reaches_the_greeting():
    signals = {**LEAD["site_signals"], "owner_name": "Dave Ruiz"}
    written = ev_offer.write_email({**LEAD, "to_address": "info@fivepoint.com", "site_signals": signals}, "drawings")
    assert written["body"].startswith("Hi Dave,")


def _seo(angle, **changes):
    return seo_offer.write_email({**LEAD, "audit_snapshot": {**SNAPSHOT, **changes}}, angle)


def test_seo_competitor_names_the_real_local_leader_not_the_lead_itself():
    written = _seo("competitor")
    assert written["angle"] == "competitor"
    assert written["subject"] == "Sparks vs Five Point"
    assert "Sparks Electric shows 640 reviews next to your 38" in written["body"]


def test_seo_competitor_falls_back_without_a_clear_leader():
    written = _seo("competitor", market_comparison={**SNAPSHOT["market_comparison"], "leaders": []})
    assert written["angle"] == "local_gap"


def test_seo_free_homepage_needs_a_published_demo():
    assert "https://demo.example.com/five-point" in _seo("free_homepage")["body"]
    written = _seo("free_homepage", next_step={})
    assert written["angle"] == "local_gap"
    assert "http" not in written["body"]


def test_seo_first_touch_is_link_free_and_does_not_promise_an_attachment():
    for angle in ("local_gap", "competitor"):
        body = _seo(angle)["body"]
        assert "http" not in body
        assert "attached" not in body.lower()
        assert "audit" not in body.lower()


def test_only_the_attached_angle_says_attached():
    assert "attached PDF" in _seo("audit_attached")["body"]


def test_rotation_is_stable_and_stays_inside_the_campaign():
    assert resolve_angle(EV_PERMITS, "p1", None, None) == resolve_angle(EV_PERMITS, "p1", "rotate", None)
    picks = {resolve_angle(EV_PERMITS, f"p{i}", None, None) for i in range(40)}
    assert picks == set(ROTATION[EV_PERMITS])
    assert resolve_angle(EV_PERMITS, "p1", "guarantee", "drawings") == "guarantee"
    assert resolve_angle(EV_PERMITS, "p1", None, "time_back") == "time_back"


def test_angle_labels_cover_old_rows():
    assert angle_label(SEO_WEBSITES, None) == "Original email"
    assert angle_label(SEO_WEBSITES, "competitor") == "Named competitor"


def test_audit_pdf_only_goes_on_the_attached_angle():
    class Repo:
        @staticmethod
        def latest_audit_report(place_id):
            raise AssertionError("no PDF should be built")

    service = OutreachService(Repo())
    assert service.audit_attachments({"claim_signal": "audit_report", "place_id": "p", "angle": "local_gap"}) is None


# --- follow-ups, against real SQL ---

class Gmail:
    def __init__(self):
        self.created = []

    def find_draft_by_message_id(self, message_id):
        return None

    def create_draft(self, **kwargs):
        self.created.append(kwargs)
        return GmailDraftResult(draft_id=f"fu{len(self.created)}", message_id=f"m{len(self.created)}")

    def list_draft_ids(self):
        return set()


@pytest.fixture(scope="module")
def pool():
    dsn = os.environ.get("DATABASE_URL")
    with ConnectionPool(dsn, open=True, kwargs={"row_factory": psycopg.rows.dict_row}) as connection_pool:
        with connection_pool.connection() as conn:
            conn.execute("""insert into businesses (place_id, name, city, state, vertical)
                            values ('fu-1', 'Five Point Electric', 'Oro Valley', 'AZ', 'electrician')
                            on conflict (place_id) do nothing""")
        yield connection_pool
        with connection_pool.connection() as conn:
            conn.execute("delete from outreach_queue_events where place_id = 'fu-1'")
            conn.execute("delete from outreach_queue where place_id = 'fu-1'")
            conn.execute("delete from businesses where place_id = 'fu-1'")


@pytest.fixture
def item(pool):
    days_ago = datetime.now(timezone.utc) - timedelta(days=4)
    with pool.connection() as conn:
        conn.execute("delete from outreach_queue where place_id = 'fu-1'")
        row = conn.execute(
            """insert into outreach_queue (place_id, channel, to_address, campaign_key, status, subject,
                                           contacted_at, gmail_thread_id, angle)
               values ('fu-1', 'email', 'aaron@fivepoint.com', 'ev_permits', 'contacted',
                       'Who draws your EV site plans?', %s, 'thread-1', 'drawings')
               returning id::text as id""", (days_ago,)).fetchone()
    return row["id"]


def test_a_saved_draft_keeps_its_angle_so_the_pdf_rule_holds(pool, item):
    assert OutreachRepository(pool).get_item(item)["angle"] == "drawings"


def test_a_follow_up_is_a_threaded_gmail_draft_with_the_opt_out(pool, item):
    gmail = Gmail()
    service = OutreachService(OutreachRepository(pool), gmail=gmail)
    assert service.draft_follow_up(item)["step"] == 2
    draft = gmail.created[0]
    assert draft["subject"] == "Re: Who draws your EV site plans?"
    assert draft["thread_id"] == "thread-1"
    assert draft["body"].startswith("Hi Aaron,")
    assert "no thanks" in draft["body"]


def test_a_sequence_stops_at_three_emails_and_waits_for_each_send(pool, item):
    gmail = Gmail()
    service = OutreachService(OutreachRepository(pool), gmail=gmail)
    gmail_repo = OutreachGmailRepository(pool)
    service.draft_follow_up(item)
    with pytest.raises(OutreachBlocked, match="still in Gmail"):
        service.draft_follow_up(item)

    follow_up = gmail_repo.open_follow_ups()[0]
    gmail_repo.mark_follow_up_left_gmail(follow_up["id"])
    with pytest.raises(OutreachBlocked, match="due on"):
        service.draft_follow_up(item)

    later = datetime.now(timezone.utc) + timedelta(days=5)
    assert service.draft_follow_up(item, now=later)["step"] == 3
    gmail_repo.mark_follow_up_left_gmail(gmail_repo.open_follow_ups()[0]["id"])
    with pytest.raises(OutreachBlocked, match="every follow-up"):
        service.draft_follow_up(item, now=later + timedelta(days=9))
    assert "Last note" in gmail.created[1]["body"]


def test_a_lead_who_replied_gets_no_follow_up(pool, item):
    with pool.connection() as conn:
        conn.execute("update outreach_queue set status = 'replied' where id = %s::uuid", (item,))
    service = OutreachService(OutreachRepository(pool), gmail=Gmail())
    with pytest.raises(OutreachBlocked, match="haven't replied"):
        service.draft_follow_up(item)


def test_a_follow_up_is_not_due_too_early(pool, item):
    with pool.connection() as conn:
        conn.execute("update outreach_queue set contacted_at = now() where id = %s::uuid", (item,))
    service = OutreachService(OutreachRepository(pool), gmail=Gmail())
    with pytest.raises(OutreachBlocked, match="due on"):
        service.draft_follow_up(item)


def test_reply_rates_split_by_angle(pool, item):
    board = OutreachBoardService(OutreachBoardRepository(pool),
                                 gmail_repository=OutreachGmailRepository(pool), gmail=None)
    assert board.angle_results(EV_PERMITS) == [
        {"angle": "Who draws your plans", "sent": 1, "replied": 0, "reply_rate": 0.0},
    ]
