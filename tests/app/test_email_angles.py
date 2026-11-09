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
from app.services.outreach import OutreachBlocked, OutreachService, looks_like_email, uses_old_copy
from app.services.outreach_board import OutreachBoardService, gmail_block_reason
from app.services.outreach_bulk import fast_track

LEAD = {"place_id": "p1", "city": "Oro Valley", "state": "AZ", "name": "Five Point Electric LLC", "vertical": "electrician",
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
def test_every_ev_first_touch_is_short_personal_and_link_free(angle):
    written = ev_offer.write_email(LEAD, angle)
    assert written["body"].startswith("Hi Aaron,")
    assert "Five Point" in written["subject"] + written["body"]
    assert _words(written["body"]) <= 115
    assert len(written["subject"]) <= 40
    assert "http" not in written["body"]
    assert "Want me to send a sample packet" in written["body"]
    assert "Four electrical shops" in written["body"]


def test_ev_copy_uses_what_the_site_and_city_actually_say():
    body = ev_offer.write_email(LEAD, "drawings")["body"]
    assert ("Saw Five Point installs Tesla and ChargePoint chargers. Oro Valley wants a site plan, "
            "one-line diagram and load calculation on every residential charger permit.") in body
    assert "Who's stuck drawing those at Five Point, you or the office?" in body
    desk = ev_offer.write_email(LEAD, "desk_work")["body"]
    assert desk.startswith("Hi Aaron,\n\nSaw Five Point installs Tesla and ChargePoint chargers. On a residential")
    assert "Oro Valley" not in desk  # the city's checklist is Angle A's line, not repeated here


@pytest.mark.parametrize("angle", [a.key for a in ANGLES[EV_PERMITS]])
def test_no_ev_proof_and_no_city_rules_means_no_claim_about_either(angle):
    lead = {**LEAD, "city": "Fresno", "state": "CA", "site_signals": {},
            "name": "Allied Electric a Buckles-Smith Company"}
    written = ev_offer.write_email(lead, angle)
    assert "Saw " not in written["body"]
    assert "Fresno" not in written["body"]
    assert "If Allied" not in written["body"]
    assert "Buckles" not in written["subject"]
    assert "No city-specific permit claim" in written["note"]


def test_ev_subjects_fit_on_a_phone():
    assert ev_offer.write_email(LEAD, "drawings")["subject"] == "Who draws Five Point's EV site plans?"
    assert ev_offer.write_email(LEAD, "desk_work")["subject"] == "EV permit desk work at Five Point"


def test_ev_sample_link_can_point_at_a_custom_domain(monkeypatch):
    assert ev_offer.overview_url() == "https://ev-permit-packets.vercel.app/"
    monkeypatch.setenv("EV_OVERVIEW_URL", "https://permits.example.com/")
    assert "https://permits.example.com/" in ev_offer.write_follow_up(LEAD, 2)


def test_ev_follow_ups_send_the_sample_then_close():
    second = ev_offer.write_follow_up(LEAD, 2)
    assert "https://ev-permit-packets.vercel.app/" in second
    assert "address and panel size from a past install" in second
    third = ev_offer.write_follow_up(LEAD, 3)
    assert third.startswith("Hi Aaron,\n\nLast note from me.")
    assert "http" not in third


def test_short_name_drops_trailing_detail():
    assert ev_offer.short_name("Fuse Service HVAC, Electrical & Appliance Repair Fresno") == "Fuse Service HVAC"


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
    assert written["subject"] == "Calls going to Sparks"
    assert ("Checked electricians in Henderson. Sparks Electric is out front on Google Maps with 640 "
            "reviews to your 38.") in written["body"]
    assert "Want me to send the plan for how I'd get Five Point those calls in Henderson?" in written["body"]


def test_seo_page_gap_is_credited_to_city_peers_not_the_leader():
    gaps = {"gaps": [{"label": "EV charger installation", "count": 6}]}
    body = _seo("competitor", page_gaps=gaps)["body"]
    assert ("640 reviews to your 38, and 6 other electricians there have a dedicated EV charger "
            "installation page that Five Point's site is missing.") in body
    assert "Sparks Electric has" not in body


def test_seo_proof_credits_wheyland_only_where_it_should():
    body = _seo("competitor")["body"]
    assert "We rebuilt Wheyland Electric's site and local search setup in March." in body
    assert "about 60 calls and quote requests a month" in body
    assert "Google's AI answers for 20 searches" in body
    assert "month-to-month" in body
    neighbor = seo_offer.write_email({**LEAD, "city": "Carlsbad", "state": "CA", "vertical": "electrician",
                                      "audit_snapshot": SNAPSHOT}, "competitor")["body"]
    assert "a North County electrical shop's site" in neighbor and "Wheyland" not in neighbor
    spa = seo_offer.write_email({**LEAD, "vertical": "med_spa", "audit_snapshot": SNAPSHOT}, "competitor")["body"]
    assert "a local electrical contractor's site" in spa and "Wheyland" not in spa


def test_seo_local_gap_gets_the_proof_and_the_calls_ask_without_the_scanner_line():
    written = _seo("local_gap")
    assert "I compared" not in written["body"]
    assert "Checked Five Point Electric against the other electricians in Henderson." in written["body"]
    assert "Wheyland Electric" in written["body"]
    assert "those calls in Henderson?" in written["body"]
    assert written["subject"] == "Five Point on Google Maps in Henderson"


def test_seo_local_gap_opens_on_the_missing_page_unless_calls_are_leaking_now():
    gaps = {"gaps": [{"label": "panel upgrade", "count": 7}]}
    slow = _seo("local_gap", page_gaps=gaps, findings=[{"signal": "psi_mobile_poor"}], benchmarks={})["body"]
    assert "Checked electricians in Henderson. 7 other electricians there have a dedicated panel upgrade page" in slow
    assert "mobile speed" not in slow
    leak = _seo("local_gap", page_gaps=gaps, findings=[{"signal": "website_not_on_gbp"}], benchmarks={})["body"]
    assert "doesn't link to your website" in leak


def test_seo_touch_two_gives_away_the_fastest_fix():
    snapshot = {**SNAPSHOT, "findings": [{"signal": "psi_mobile_poor"}, {"signal": "website_not_on_gbp"}]}
    body = seo_offer.write_follow_up({**LEAD, "audit_snapshot": snapshot}, 2)
    assert "Quick one regardless: your Google Maps listing doesn't link to your website" in body
    assert "I'll send the rest of the Henderson plan." in body
    gap = {**SNAPSHOT, "page_gaps": {"gaps": [{"label": "panel upgrade", "count": 5}]}}
    assert "5 other electricians in Henderson have a dedicated panel upgrade page" in \
        seo_offer.write_follow_up({**LEAD, "audit_snapshot": gap}, 2)
    both = {**gap, "findings": [{"signal": "no_hours"}]}
    told = seo_offer.write_follow_up({**LEAD, "angle": "competitor", "audit_snapshot": both}, 2)
    assert "business hours" in told and "panel upgrade" not in told
    # Findings outside the fix list still beat repeating Touch 1's missing page.
    other = {**gap, "findings": [{"signal": "no_photos"}, {"signal": "no_service_pages"}]}
    fell = seo_offer.write_follow_up({**LEAD, "angle": "local_gap", "audit_snapshot": other}, 2)
    assert "Quick one regardless: I'd start with photos on your Google listing." in fell
    assert "panel upgrade" not in fell and "first thing I'd fix" not in fell
    only_gap = {**gap, "findings": [{"signal": "no_service_pages"}]}
    assert "panel upgrade" in seo_offer.write_follow_up(
        {**LEAD, "angle": "competitor", "audit_snapshot": only_gap}, 2)
    bare = seo_offer.write_follow_up(LEAD, 2)
    assert "Quick follow-up." in bare and "Quick one regardless" not in bare
    last = seo_offer.write_follow_up(LEAD, 3)
    assert 'reply "plan"' in last and "30" not in last


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


def test_only_the_angles_that_attach_the_pdf_say_attached():
    assert "attached PDF" in _seo("audit_attached")["body"]
    assert "attached a short audit" in _seo("free_homepage")["body"]


def _seo_service():
    class Repo:
        @staticmethod
        def latest_audit_report(place_id):
            return {"name": "Five Point Electric", "snapshot": {"findings": []}}

    return OutreachService(Repo())


def test_best_fit_uses_the_published_mockup_and_attaches_the_audit(monkeypatch):
    from app.services import outreach as outreach_module
    monkeypatch.setattr("app.services.audit_report_pdf.render_audit_report_pdf", lambda report: b"%PDF-1.4")
    service = _seo_service()
    context = {**LEAD, "campaign_key": SEO_WEBSITES, "audit_snapshot": {**SNAPSHOT, "next_step": {}},
               "demo_url": "https://demo.example.com/live-mockup"}
    written = service.write_seo_draft(context, "best")
    assert written["angle"] == "free_homepage"
    assert "https://demo.example.com/live-mockup" in written["body"]
    assert "attached a short audit" in written["body"]
    item = {"claim_signal": "audit_report", "place_id": "p1", "angle": written["angle"]}
    assert service.audit_attachments(item)[0][1] == b"%PDF-1.4"
    assert outreach_module.BEST == "best"


def test_best_fit_without_a_mockup_sends_the_audit_attached_email():
    written = _seo_service().write_seo_draft(
        {**LEAD, "campaign_key": SEO_WEBSITES, "audit_snapshot": {**SNAPSHOT, "next_step": {}}}, "best")
    assert written["angle"] == "audit_attached"
    assert "demo.example.com" not in written["body"]
    assert "attached PDF" in written["body"]


def test_a_mockup_published_after_the_audit_still_gets_linked():
    # The audit snapshot has no demo_url; the live published mockup is used.
    written = seo_offer.write_email({**LEAD, "audit_snapshot": {**SNAPSHOT, "next_step": {}},
                                     "demo_url": "https://demo.example.com/after"}, "free_homepage")
    assert written["angle"] == "free_homepage" and "https://demo.example.com/after" in written["body"]


def test_best_fit_on_ev_falls_back_to_the_rotation():
    service = OutreachService(object())
    written = service.write_ev_draft({**LEAD, "campaign_key": EV_PERMITS}, "best")
    assert written["angle"] in ROTATION[EV_PERMITS]


def test_rotation_is_stable_and_stays_inside_the_campaign():
    assert resolve_angle(EV_PERMITS, "p1", None, None) == resolve_angle(EV_PERMITS, "p1", "rotate", None)
    picks = {resolve_angle(EV_PERMITS, f"p{i}", None, None) for i in range(40)}
    assert picks == set(ROTATION[EV_PERMITS])
    assert resolve_angle(EV_PERMITS, "p1", "desk_work", "drawings") == "desk_work"
    assert resolve_angle(EV_PERMITS, "p1", None, "desk_work") == "desk_work"
    # A lead still on a retired angle moves into the current rotation.
    assert resolve_angle(EV_PERMITS, "p1", None, "free_packet") in ROTATION[EV_PERMITS]


def test_angle_labels_cover_old_rows():
    assert angle_label(SEO_WEBSITES, None) == "Original email"
    assert angle_label(SEO_WEBSITES, "competitor") == "Calls going to the leader"
    assert angle_label(EV_PERMITS, "free_packet") == "Free packet"


def test_audit_pdf_only_goes_on_the_attached_angle():
    class Repo:
        @staticmethod
        def latest_audit_report(place_id):
            raise AssertionError("no PDF should be built")

    service = OutreachService(Repo())
    assert service.audit_attachments({"claim_signal": "audit_report", "place_id": "p", "angle": "local_gap"}) is None


def test_an_incomplete_address_is_caught():
    assert looks_like_email("info@ampereelectricnv.com")
    assert not looks_like_email("info@southwest")


def _ready_item(**changes):
    return {"campaign_key": EV_PERMITS, "status": "draft_ready", "channel": "email", "stage": "review",
            "to_address": "a@sparks.com", "subject": "s", "body": "b", "verification_status": "verified",
            "claim_signal": "ev_permit_offer", "generation_prompt_version": ev_offer.PROMPT_VERSION,
            **changes}


def test_gmail_is_blocked_for_a_bad_address_and_for_old_copy():
    assert gmail_block_reason(_ready_item(), gmail_connected=True) is None
    assert "complete email" in gmail_block_reason(_ready_item(to_address="info@southwest"), gmail_connected=True)
    old = _ready_item(generation_prompt_version="ev-offer-v3")
    assert uses_old_copy(old)
    assert "old email" in gmail_block_reason(old, gmail_connected=True)


def test_ai_written_notes_without_an_audit_are_not_called_old():
    assert not uses_old_copy({"claim_signal": "no_ssl", "generation_prompt_version": "outreach-v12"})
    assert uses_old_copy({"claim_signal": "audit_report", "generation_prompt_version": "outreach-v12"})


def test_bulk_prep_rewrites_old_copy_but_leaves_current_drafts_alone():
    class Repo:
        def __init__(self, version):
            self.item = {"id": "q", "place_id": "p", "body": "Old", "subject": "S", "status": "draft_ready",
                         "claim_signal": "ev_permit_offer", "version": 1, "gmail_draft_id": None,
                         "generation_prompt_version": version}

        def find_email_item(self, place_id, campaign_key):
            return self.item

        def get_item(self, item_id):
            return self.item

    class Service:
        def __init__(self, version):
            self.repository = Repo(version)
            self.regenerated = 0

        def cooldown_block(self, place_id, campaign_key):
            return None

        def create_item(self, place_id, channel, to_address, campaign_key):
            return self.repository.item

        def generate_draft(self, item_id, *, expected_version, angle=None):
            self.regenerated += 1
            return {**self.repository.item, "body": "New"}

    old = Service("ev-offer-v3")
    assert fast_track(old, None, "p", gmail=False, campaign_key=EV_PERMITS)["ok"]
    assert old.regenerated == 1
    current = Service(ev_offer.PROMPT_VERSION)
    assert fast_track(current, None, "p", gmail=False, campaign_key=EV_PERMITS)["ok"]
    assert current.regenerated == 0


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


def test_the_cleanup_replaces_bad_addresses_only_on_unsent_items(pool, item):
    sql = open("sql/migrations/025_fix_bad_queue_addresses.sql").read()
    with pool.connection() as conn:
        conn.execute("""insert into website_enrichment (place_id, emails_found)
                        values ('fu-1', '{real@fivepoint.com}')
                        on conflict (place_id) do update set emails_found = excluded.emails_found""")
        conn.execute("""update outreach_queue set to_address = 'info@southwest', contacted_at = null,
                        status = 'draft_ready' where id = %s::uuid""", (item,))
        conn.execute(sql)
        fixed = conn.execute("select to_address from outreach_queue where id = %s::uuid", (item,)).fetchone()
        conn.execute("""update outreach_queue set to_address = 'info@southwest', contacted_at = now()
                        where id = %s::uuid""", (item,))
        conn.execute(sql)
        sent = conn.execute("select to_address from outreach_queue where id = %s::uuid", (item,)).fetchone()
        conn.execute("delete from website_enrichment where place_id = 'fu-1'")
    assert fixed["to_address"] == "real@fivepoint.com"
    assert sent["to_address"] == "info@southwest"


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
    assert "https://ev-permit-packets.vercel.app/" in draft["body"]


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


def test_a_deleted_draft_can_be_moved_back_to_review(pool, item):
    gmail_repo = OutreachGmailRepository(pool)
    with pool.connection() as conn:
        conn.execute("""update outreach_queue set status = 'draft_ready', contacted_at = null,
                        gmail_draft_id = 'gone-draft', gmail_message_id = 'm-gone',
                        gmail_draft_created_at = now() - interval '1 hour' where id = %s::uuid""", (item,))
    assert gmail_repo.mark_draft_left_gmail(item, "gone-draft")
    assert gmail_repo.reopen_unsent(item)
    with pool.connection() as conn:
        row = conn.execute("""select q.status, q.contacted_at, q.gmail_draft_id, q.gmail_draft_left_at, s.stage
                              from outreach_queue q join v_outreach_stage s on s.id = q.id
                              where q.id = %s::uuid""", (item,)).fetchone()
        event = conn.execute("""select 1 from outreach_queue_events
                                where queue_id = %s::uuid and event_type = 'gmail_draft_not_sent'""", (item,)).fetchone()
    assert row["stage"] == "review" and row["status"] == "draft_ready"
    assert row["contacted_at"] is None and row["gmail_draft_id"] is None and row["gmail_draft_left_at"] is None
    assert event is not None
    # Once reopened there's nothing left to undo.
    assert not gmail_repo.reopen_unsent(item)


def test_only_unconfirmed_sends_without_follow_ups_can_be_reopened(pool, item):
    gmail_repo = OutreachGmailRepository(pool)
    # Marked contacted by hand, not by the Gmail check.
    assert not gmail_repo.reopen_unsent(item)
    with pool.connection() as conn:
        conn.execute("update outreach_queue set gmail_draft_left_at = now() where id = %s::uuid", (item,))
    OutreachService(OutreachRepository(pool), gmail=Gmail()).draft_follow_up(item)
    # A follow-up exists, so the first email really went.
    assert not gmail_repo.reopen_unsent(item)


def test_board_reopen_reports_each_item(pool, item):
    from app.repositories.outreach_board import OutreachBoardRepository
    service = OutreachBoardService(OutreachBoardRepository(pool), gmail_repository=OutreachGmailRepository(pool), gmail=None)
    result = service.reopen_unsent([item])
    assert result["reopened"] == 0 and result["results"][0]["detail"]
