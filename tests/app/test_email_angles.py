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
from app.services import permit_offer, seo_offer
from app.services.email_angles import ANGLES, ROTATION, angle_label, resolve_angle
from app.services.outreach import OutreachBlocked, OutreachService, looks_like_email, uses_old_copy
from app.services.outreach_board import OutreachBoardService, gmail_block_reason
from app.services.outreach_bulk import fast_track

LEAD = {"place_id": "p1", "city": "Oro Valley", "state": "AZ", "name": "Five Point Electric LLC", "vertical": "electrician",
        "to_address": "aaron@fivepoint.com",
        "site_signals": {"ev_service": True, "ev_strength": "page", "ev_page_path": "/ev",
                         "ev_brands": ["Tesla", "ChargePoint"],
                         "permit_jobs": ["ev_charger", "service_upgrade"]}}
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


def _lead(*jobs, **changes):
    signals = {k: v for k, v in LEAD["site_signals"].items() if k not in {"ev_brands", "permit_jobs"}}
    return {**LEAD, "site_signals": {**signals, "permit_jobs": list(jobs)}, **changes}


@pytest.mark.parametrize("angle", [a.key for a in ANGLES[EV_PERMITS]])
def test_every_permit_first_touch_is_short_link_free_and_greets_by_name(angle):
    written = permit_offer.write_email(LEAD, angle)
    assert written["body"].startswith("Hi Aaron,\n\n")
    assert _words(written["body"]) <= 90
    assert len(written["subject"]) <= 40
    assert written["subject"] == written["subject"].lower()
    assert "http" not in written["body"] and "www." not in written["body"]
    assert "None" not in written["body"] + written["subject"]


def test_the_sample_angle():
    written = permit_offer.write_email(LEAD, "sample")
    assert written["subject"] == "oro valley permit packets"
    assert written["body"] == (
        "Hi Aaron,\n\n"
        "We put together Oro Valley-specific electrical permit packets (scaled aerial site plan, one-line "
        "diagram, NEC 220.82 load calc, and local inspector flags) for EV chargers, panel/service upgrades, "
        "subpanels and 240 V circuits.\n\n"
        "Mocked up a sample packet for Oro Valley so you can see the drawings. Want me to send it over?"
    )


def test_the_project_angle():
    written = permit_offer.write_email(LEAD, "project")
    assert written["subject"] == "permits at five point"
    assert written["body"] == (
        "Hi Aaron,\n\n"
        "Have any panel upgrades, EV chargers or subpanels coming up in Oro Valley at Five Point?\n\n"
        "We build ready-to-submit Oro Valley permit packets (load calcs, scaled site plans, one-lines and "
        "local code flags) so your electricians stay in the field instead of doing desk work.\n\n"
        "Are you the best person to send a sample packet to, or who handles permitting on your end?"
    )


@pytest.mark.parametrize("angle", [a.key for a in ANGLES[EV_PERMITS]])
def test_a_generic_inbox_gets_no_greeting(angle):
    written = permit_offer.write_email({**LEAD, "to_address": "info@fivepoint.com"}, angle)
    assert not written["body"].startswith("Hi")
    assert "team," not in written["body"]
    assert "No contact name found" in written["note"]


@pytest.mark.parametrize("angle", [a.key for a in ANGLES[EV_PERMITS]])
def test_no_city_never_renders_none(angle):
    for city in (None, "", "  "):
        written = permit_offer.write_email({**LEAD, "city": city}, angle)
        assert "None" not in written["subject"] + written["body"]
        assert "  " not in written["body"] and " ," not in written["body"]
    assert permit_offer.write_email({**LEAD, "city": None}, "sample")["subject"] == "electrical permit packets"
    sample = permit_offer.write_email({**LEAD, "city": None}, "sample")["body"]
    assert "local electrical permit packets" in sample
    assert "Mocked up a sample packet so you can see the drawings." in sample
    project = permit_offer.write_email({**LEAD, "city": None}, "project")["body"]
    assert "coming up at Five Point?" in project
    assert "ready-to-submit permit packets" in project


def test_the_follow_up_asks_a_named_contact_which_job_they_permit_most():
    assert permit_offer.write_follow_up(LEAD, 2) == (
        "Hi Aaron,\n\n"
        "Which do you pull the most permits for at Five Point: EV chargers, panel upgrades or subpanels? "
        "Happy to send over a matching Oro Valley sample packet."
    )


def test_the_follow_up_asks_a_generic_inbox_who_handles_permits():
    assert permit_offer.write_follow_up({**LEAD, "to_address": "info@fivepoint.com"}, 2) == (
        "Quick bump on this. Who handles pulling electrical permits at Five Point? "
        "Happy to send a sample Oro Valley packet their way."
    )


def test_the_follow_up_has_no_link_and_handles_no_city():
    for lead in (LEAD, {**LEAD, "to_address": "info@fivepoint.com"}):
        for city in ("Oro Valley", None):
            text = permit_offer.write_follow_up({**lead, "city": city}, 2)
            assert "http" not in text and "None" not in text
    assert permit_offer.write_follow_up({**LEAD, "city": None}, 2).endswith("a matching sample packet.")


def test_permit_evidence_uses_every_source_on_file():
    assert permit_offer.permit_evidence(_lead("service_upgrade", "subpanel")) == "Panel upgrades, Subpanels on site"
    assert permit_offer.permit_evidence({"offering_titles": ["Hot tub wiring"]}) == "service link"
    assert permit_offer.permit_evidence({"site_description": "We do panel upgrades."}) == "page description"
    assert permit_offer.permit_evidence({"site_title": "Sparks Electric"}) is None


def test_short_name_drops_trailing_detail():
    assert permit_offer.short_name("Fuse Service HVAC, Electrical & Appliance Repair Fresno") == "Fuse Service HVAC"


def test_the_site_owner_name_reaches_the_greeting():
    signals = {**LEAD["site_signals"], "owner_name": "Dave Ruiz"}
    written = permit_offer.write_email({**LEAD, "to_address": "info@fivepoint.com", "site_signals": signals}, "project")
    assert written["body"].startswith("Hi Dave,")


WEB = {**LEAD, "to_address": "dave@crazyelectricaz.com", "name": "Crazy Electric LLC", "city": "Phoenix",
       "state": "AZ", "website_url": "https://www.crazyelectricaz.com/",
       "site_signals": {"has_viewport": False, "has_click_to_call": True,
                        "site_hook": {"kind": "license", "value": "CR-11"}}}
SLOW = {"signal": "psi_mobile_critical", "data": {"psi_performance": 22, "lcp_ms": 9200}}


def _web(angle="website_draft", findings=(SLOW,), **changes):
    return seo_offer.write_email({**WEB, "audit_snapshot": {**SNAPSHOT, "findings": list(findings)}, **changes}, angle)


def test_the_website_draft_email():
    written = _web()
    assert written["subject"] == "crazy electric website"
    assert written["angle"] == "website_draft"
    assert written["body"] == (
        "Hi Dave,\n\n"
        "Was on crazyelectricaz.com and saw you're a licensed CR-11 contractor. That's worth leading with.\n\n"
        "A couple of things are probably costing you calls, though. On a weaker phone signal it takes about "
        "9 seconds before anything shows up, and most people are gone by then. On a phone the page shows up "
        "desktop-sized, so people have to pinch and zoom to read it.\n\n"
        "I put together a draft of a faster, mobile-friendly version. Want me to send it over?"
    )


def test_website_email_has_no_link_attachment_or_review_comparison():
    body = _web()["body"]
    assert "http" not in body and "attached" not in body.lower()
    assert "reviews" not in body and "Wheyland" not in body
    assert _words(body) <= 100


@pytest.mark.parametrize("kind,value,line", [
    ("since", "1996", "saw you've been around since 1996."),
    ("years", "20", "saw 20+ years in business."),
    ("experience", "15", "saw 15+ years of experience."),
    ("response", "2", "saw you offer 2-hour response."),
    ("family", "family-owned", "saw you're family-owned."),
])
def test_each_homepage_detail_reads_as_a_sentence(kind, value, line):
    signals = {**WEB["site_signals"], "site_hook": {"kind": kind, "value": value}}
    assert f"Was on crazyelectricaz.com and {line} That's worth leading with." in _web(site_signals=signals)["body"]


def test_no_homepage_detail_opens_on_the_site():
    signals = {**WEB["site_signals"], "site_hook": None}
    written = _web(site_signals=signals)
    assert "Looked through crazyelectricaz.com on my phone today." in written["body"]
    assert "No homepage detail found" in written["note"]


def test_problems_are_verified_and_capped_at_two_most_serious_first():
    findings = [SLOW, {"signal": "no_ssl"}, {"signal": "broken_profile_link"}, {"signal": "no_click_to_call"}]
    body = _web(findings=findings)["body"]
    assert "opens an error page" in body and "Not secure" in body
    assert "9 seconds" not in body and "tappable" not in body
    one = _web(findings=[{"signal": "no_click_to_call"}],
               site_signals={**WEB["site_signals"], "has_viewport": True, "has_click_to_call": None})["body"]
    assert "One thing is probably costing you calls, though. Your phone number isn't tappable" in one


def test_slow_without_a_load_time_says_slow_without_a_number():
    body = _web(findings=[{"signal": "psi_mobile_poor", "data": {"psi_performance": 41}}],
                site_signals={**WEB["site_signals"], "has_viewport": True})["body"]
    assert "It's slow to load on a phone" in body and "seconds" not in body


def test_nothing_verified_means_no_email():
    assert _web(findings=[], site_signals={"has_viewport": True, "has_click_to_call": True}) is None


def test_a_generic_inbox_gets_no_greeting():
    written = _web(to_address="info@crazyelectricaz.com")
    assert written["body"].startswith("Was on crazyelectricaz.com")
    assert "No contact name found" in written["note"]


def test_social_only_listings_get_no_website_email():
    for url in ("https://www.facebook.com/crazyelectric", "https://linktr.ee/crazy", "https://m.yelp.com/biz/x"):
        assert _web(website_url=url) is None


def test_toast_built_sites_get_the_toast_line_and_other_builders_do_not():
    toast = _web(site_signals={**WEB["site_signals"], "site_builder": "toast"})["body"]
    assert "I moved a restaurant group's sites off Toast's builder onto their own fast site and kept ordering on Toast." in toast
    square = _web(site_signals={**WEB["site_signals"], "site_builder": "square"})["body"]
    assert "Toast" not in square


def test_the_website_follow_up():
    assert seo_offer.write_follow_up(WEB, 2) == (
        "Hi Dave,\n\nQuick bump on this. Want me to send over that mobile-friendly homepage draft for "
        "Crazy Electric so you can take a look?"
    )
    generic = seo_offer.write_follow_up({**WEB, "to_address": "info@crazyelectricaz.com"}, 2)
    assert generic.startswith("Quick bump on this.") and "http" not in generic


def test_free_homepage_still_needs_a_published_demo():
    assert _web("free_homepage", demo_url=None, audit_snapshot={**SNAPSHOT, "next_step": {}, "findings": [SLOW]})["angle"] == "website_draft"
    assert _web("free_homepage", demo_url="https://demo.example.com/x")["angle"] == "free_homepage"


def test_best_fit_and_rotation_use_the_website_draft():
    service = OutreachService(object())
    written = service.write_seo_draft({**WEB, "campaign_key": SEO_WEBSITES,
                                       "audit_snapshot": {**SNAPSHOT, "findings": [SLOW]}}, "best")
    assert written["angle"] == "website_draft"
    assert written["claim_signal"] == "audit_report"
    assert ROTATION[SEO_WEBSITES] == ("website_draft",)
    assert service.audit_attachments({"claim_signal": "audit_report", "place_id": "p", "angle": "website_draft"}) is None


def test_best_fit_on_ev_falls_back_to_the_rotation():
    service = OutreachService(object())
    written = service.write_ev_draft({**LEAD, "campaign_key": EV_PERMITS}, "best")
    assert written["angle"] in ROTATION[EV_PERMITS]


def test_rotation_is_stable_and_stays_inside_the_campaign():
    assert resolve_angle(EV_PERMITS, "p1", None, None) == resolve_angle(EV_PERMITS, "p1", "rotate", None)
    picks = {resolve_angle(EV_PERMITS, f"p{i}", None, None) for i in range(40)}
    assert picks == set(ROTATION[EV_PERMITS])
    assert resolve_angle(EV_PERMITS, "p1", "project", "sample") == "project"
    assert resolve_angle(EV_PERMITS, "p1", None, "project") == "project"
    # A lead still on a retired angle moves into the current rotation.
    for retired in ("free_packet", "who_pulls", "drawings", "desk_work"):
        assert resolve_angle(EV_PERMITS, "p1", None, retired) in ROTATION[EV_PERMITS]
    assert ROTATION[EV_PERMITS] == ("sample", "project")
    assert "ai_search" not in ROTATION[SEO_WEBSITES]


def test_angle_labels_cover_old_rows():
    assert angle_label(SEO_WEBSITES, None) == "Original email"
    assert angle_label(SEO_WEBSITES, "competitor") == "Competitor gap"
    assert angle_label(EV_PERMITS, "free_packet") == "Free packet"
    assert angle_label(EV_PERMITS, "drawings") == "EV & panel permits"
    assert angle_label(EV_PERMITS, "sample") == "Sample packet"


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
            "claim_signal": "ev_permit_offer", "generation_prompt_version": permit_offer.PROMPT_VERSION,
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
    current = Service(permit_offer.PROMPT_VERSION)
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
    assert draft["body"].startswith("Hi Aaron,\n\nWhich do you pull the most permits for at Five Point")
    assert "no thanks" in draft["body"]
    assert "http" not in draft["body"] and "lilosgrowth.com" not in draft["body"]


def test_a_sequence_stops_after_one_follow_up_and_waits_for_it_to_send(pool, item):
    gmail = Gmail()
    service = OutreachService(OutreachRepository(pool), gmail=gmail)
    gmail_repo = OutreachGmailRepository(pool)
    service.draft_follow_up(item)
    with pytest.raises(OutreachBlocked, match="every follow-up"):
        service.draft_follow_up(item)

    follow_up = gmail_repo.open_follow_ups()[0]
    gmail_repo.mark_follow_up_left_gmail(follow_up["id"])
    later = datetime.now(timezone.utc) + timedelta(days=30)
    with pytest.raises(OutreachBlocked, match="every follow-up"):
        service.draft_follow_up(item, now=later)
    assert len(gmail.created) == 1


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
        {"angle": "EV & panel permits", "sent": 1, "replied": 0, "reply_rate": 0.0},
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
