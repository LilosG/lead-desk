"""The ChatGPT check: parsing, strict matching, caching, the two emails, and routing."""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.campaigns import SEO_WEBSITES
from app.integrations.openai_search import OpenAISearchClient, OpenAISearchError, SearchAnswer
from app.repositories.outreach import OutreachRepository
from app.services import chatgpt_check as cc
from app.services import outreach as outreach_module
from app.services import seo_offer
from app.services.email_angles import angle_options
from app.services.outreach import OutreachBlocked, OutreachService

REPLY = ('{"recommendations": [{"name": "Sparks Electric", "website": "sparkselectric.com"},'
         '{"name": "Yelp", "website": "yelp.com"},'
         '{"name": "Volt Pros LLC", "website": "https://www.voltpros.com/"},'
         '{"name": "Amp Brothers Electrical Services", "website": ""},'
         '{"name": "Thumbtack Top Pros", "website": "thumbtack.com/az/phoenix"}]}')


def _answer(text=REPLY, sources=()):
    return SearchAnswer(text=text, sources=list(sources), model="gpt-test")


class FakeRepo:
    def __init__(self):
        self.rows = {}

    def latest_chatgpt_check(self, vertical, city, state, max_age_days):
        return self.rows.get((vertical, city.lower(), state))

    def save_chatgpt_check(self, *, vertical, city, state, prompt, response, sources, businesses, model):
        row = {"id": f"c{len(self.rows) + 1}", "prompt": prompt, "response": response, "sources": sources,
               "businesses": businesses, "model": model, "checked_at": "2026-11-13 10:00:00+00"}
        self.rows[(vertical, city.lower(), state)] = row
        return row


class FakeClient:
    model = "gpt-test"

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer or _answer(), error, []

    def ask(self, prompt):
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return self.answer


LEAD = {"place_id": "p1", "name": "Five Point Electric LLC", "city": "Phoenix", "state": "az",
        "vertical": "electrician", "website_url": "https://fivepointelectric.com",
        "to_address": "dave@fivepointelectric.com", "campaign_key": SEO_WEBSITES, "site_signals": {}}


def _service(client=None):
    return cc.ChatGPTCheckService(FakeRepo(), client or FakeClient())


# --- parsing and filtering ---

def test_the_reply_is_parsed_and_directories_are_dropped():
    found = cc.parse_businesses(REPLY)
    assert [b["name"] for b in found][:2] == ["Sparks Electric", "Yelp"]
    assert [b["name"] for b in cc.competitors(found)] == [
        "Sparks Electric", "Volt Pros LLC", "Amp Brothers Electrical Services"]


@pytest.mark.parametrize("text", ["", "no json here", '{"recommendations": "none"}', '{"broken": ', "[1, 2]"])
def test_anything_that_is_not_the_expected_json_parses_to_nothing(text):
    assert cc.parse_businesses(text) == []


def test_json_inside_a_code_fence_still_parses():
    assert len(cc.parse_businesses(f"```json\n{REPLY}\n```")) == 5


def test_the_prompt_names_the_trade_city_and_state():
    prompt = cc.build_prompt("electrician", "Phoenix", "AZ")
    assert prompt.startswith("Who are the best electricians in Phoenix, AZ?")
    assert "HVAC companies" in cc.build_prompt("hvac", "Reno", "NV")
    assert cc.trade_phrase("pool_cleaning") == "pool cleanings"


# --- matching: a near miss must count as named ---

@pytest.mark.parametrize("business", [
    {"name": "Five Point Electrical Services", "website": ""},
    {"name": "Five Point Electric", "website": "fivepoint.net"},
    {"name": "Totally Different Name", "website": "https://www.fivepointelectric.com/about"},
])
def test_a_lead_chatgpt_names_slightly_differently_is_still_named(business):
    assert cc.is_named("Five Point Electric LLC", "https://fivepointelectric.com", [business], "", [])


def test_a_lead_cited_only_in_the_sources_is_named():
    sources = [{"url": "https://www.fivepointelectric.com/ev", "title": "Five Point"}]
    assert cc.is_named("Five Point Electric LLC", "fivepointelectric.com", [], "", sources)


def test_a_lead_mentioned_in_the_answer_text_is_named():
    assert cc.is_named("Crazy Electric", None, [], "Crazy Electric & Sons also gets good reviews.", [])


def test_a_lead_nowhere_in_the_answer_is_not_named():
    found = cc.parse_businesses(REPLY)
    assert not cc.is_named("Five Point Electric LLC", "fivepointelectric.com", found, REPLY, [])


# --- the cached lookup ---

def test_one_call_covers_a_whole_market():
    client = FakeClient()
    service = _service(client)
    first = service.evaluate(LEAD)
    second = service.evaluate({**LEAD, "place_id": "p2", "name": "Other Electric", "city": "phoenix"})
    assert len(client.calls) == 1
    assert first["competitors"] == ["Sparks Electric", "Volt Pros LLC", "Amp Brothers Electrical Services"]
    assert first["prospect_named"] is False and second["prospect_named"] is False
    assert first["prompt"] == client.calls[0] and first["response"] == REPLY and first["model"] == "gpt-test"
    service.evaluate({**LEAD, "city": "Tucson"})
    assert len(client.calls) == 2


def test_a_failed_call_gives_no_evidence_and_is_not_cached():
    client = FakeClient(error=OpenAISearchError("boom"))
    service = _service(client)
    assert service.evaluate(LEAD) is None
    assert service.evaluate(LEAD) is None
    assert len(client.calls) == 2


def test_a_lead_without_a_city_or_trade_is_not_checked():
    client = FakeClient()
    assert _service(client).evaluate({**LEAD, "city": None}) is None
    assert _service(client).evaluate({**LEAD, "vertical": ""}) is None
    assert client.calls == []


def test_a_gap_needs_two_real_competitors_and_an_absent_lead():
    assert cc.has_gap({"prospect_named": False, "competitors": ["A", "B"]})
    assert not cc.has_gap({"prospect_named": False, "competitors": ["A"]})
    assert not cc.has_gap({"prospect_named": True, "competitors": ["A", "B", "C"]})
    assert not cc.has_gap(None)
    only_directories = _service(FakeClient(_answer('{"recommendations": [{"name": "Yelp", "website": "yelp.com"}]}')))
    assert not cc.has_gap(only_directories.evaluate(LEAD))


# --- the emails ---

PICK_EVIDENCE = {"competitors": ["Sparks Electric", "Volt Pros LLC", "Amp Brothers Electrical Services", "Fourth Co"],
                 "prospect_named": False, "checked_at": "2026-11-13 10:00:00+00"}


def test_the_chatgpt_pick_email():
    written = seo_offer.write_email({**LEAD, "city": "Phoenix", "chatgpt_evidence": PICK_EVIDENCE}, "chatgpt_pick")
    assert written["subject"] == "five point on chatgpt"
    assert written["angle"] == "chatgpt_pick"
    assert written["body"] == (
        "Hi Dave,\n\n"
        "I asked ChatGPT for the best electricians in Phoenix. It named Sparks Electric, Volt Pros LLC and "
        "Amp Brothers Electrical Services. Five Point didn't come up.\n\n"
        "People are starting to ask it who to call.\n\n"
        "Want me to send over a breakdown of what those businesses are doing that Five Point isn't?"
    )


def test_the_pick_email_refuses_without_a_real_gap():
    base = {**LEAD, "city": "Phoenix"}
    assert seo_offer.write_email(base, "chatgpt_pick") is None
    assert seo_offer.write_email({**base, "chatgpt_evidence": {**PICK_EVIDENCE, "prospect_named": True}}, "chatgpt_pick") is None
    assert seo_offer.write_email({**base, "chatgpt_evidence": {**PICK_EVIDENCE, "competitors": ["Only One"]}}, "chatgpt_pick") is None
    assert seo_offer.write_email({**base, "city": None, "chatgpt_evidence": PICK_EVIDENCE}, "chatgpt_pick") is None


def test_the_pick_email_works_for_a_lead_with_no_website():
    written = seo_offer.write_email({**LEAD, "website_url": None, "to_address": "info@gmail.com", "city": "Phoenix",
                                     "chatgpt_evidence": PICK_EVIDENCE}, "chatgpt_pick")
    assert written["body"].startswith("I asked ChatGPT")


def test_the_profile_email():
    written = seo_offer.write_email(LEAD, "chatgpt_profile")
    assert written["subject"] == "five point chatgpt profile"
    assert written["body"] == (
        "Hi Dave,\n\n"
        "OpenAI is rolling out business profiles in ChatGPT. A business claims its profile, verifies it, "
        "and can see how often ChatGPT mentions it.\n\n"
        "Want me to check whether Five Point has one yet and walk you through claiming it?"
    )
    assert seo_offer.write_email({**LEAD, "website_url": "https://facebook.com/fivepoint"}, "chatgpt_profile") is None


@pytest.mark.parametrize("angle", ["chatgpt_pick", "chatgpt_profile"])
def test_the_chatgpt_emails_have_no_link_or_attachment(angle):
    written = seo_offer.write_email({**LEAD, "city": "Phoenix", "chatgpt_evidence": PICK_EVIDENCE}, angle)
    assert "http" not in written["body"] and "www." not in written["body"]
    assert angle not in seo_offer.ATTACHES_AUDIT


def test_each_angle_gets_its_own_follow_up():
    assert seo_offer.write_follow_up({**LEAD, "angle": "chatgpt_pick"}, 2) == (
        "Hi Dave,\n\nQuick bump on this. Want me to send over the breakdown of what those businesses are "
        "doing on ChatGPT that Five Point isn't?")
    assert seo_offer.write_follow_up({**LEAD, "angle": "chatgpt_profile"}, 2).endswith(
        "Want me to walk you through claiming Five Point's ChatGPT profile?")
    assert "homepage draft" in seo_offer.write_follow_up({**LEAD, "angle": "website_draft"}, 2)


# --- routing ---

SLOW = {"signal": "psi_mobile_critical", "data": {"psi_performance": 22, "lcp_ms": 9200}}
WITH_PROBLEM = {**LEAD, "audit_snapshot": {"findings": [SLOW]}}
NO_PROBLEM = {**LEAD, "audit_snapshot": {"findings": []}}


class StubCheck:
    def __init__(self, evidence):
        self.evidence, self.calls = evidence, 0

    def evaluate(self, context):
        self.calls += 1
        return self.evidence


GAP = {**PICK_EVIDENCE, "prospect_named": False}
NAMED = {**PICK_EVIDENCE, "prospect_named": True}


def _route(context, evidence, requested=None, profile=False, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(outreach_module, "profile_offer_enabled", lambda: profile)
    return OutreachService(object(), chatgpt_check=StubCheck(evidence))._seo_route(context, requested)


def test_a_lead_with_only_website_problems_gets_the_website_draft(monkeypatch):
    assert _route(WITH_PROBLEM, NAMED, monkeypatch=monkeypatch) == ("website_draft", None)


def test_a_lead_with_only_a_chatgpt_gap_gets_the_pick(monkeypatch):
    assert _route(NO_PROBLEM, GAP, monkeypatch=monkeypatch) == ("chatgpt_pick", GAP)


def test_a_lead_with_both_is_split_between_the_two_and_stays_put(monkeypatch):
    picks = {_route({**WITH_PROBLEM, "place_id": f"p{i}"}, GAP, monkeypatch=monkeypatch)[0] for i in range(40)}
    assert picks == {"website_draft", "chatgpt_pick"}
    first = _route(WITH_PROBLEM, GAP, monkeypatch=monkeypatch)
    assert first == _route(WITH_PROBLEM, GAP, monkeypatch=monkeypatch)


def test_nothing_verified_means_no_email_and_the_profile_stays_off(monkeypatch):
    assert _route(NO_PROBLEM, NAMED, monkeypatch=monkeypatch) == (None, None)
    assert _route(NO_PROBLEM, None, monkeypatch=monkeypatch) == (None, None)


def test_the_profile_offer_only_appears_once_switched_on(monkeypatch):
    assert _route(NO_PROBLEM, NAMED, profile=True, monkeypatch=monkeypatch) == ("chatgpt_profile", None)
    # It never displaces an email the lead actually qualifies for.
    assert _route(WITH_PROBLEM, NAMED, profile=True, monkeypatch=monkeypatch)[0] == "website_draft"
    assert _route(NO_PROBLEM, GAP, profile=True, monkeypatch=monkeypatch)[0] == "chatgpt_pick"


def test_without_an_openai_key_the_routing_is_the_website_draft_only():
    service = OutreachService(object())
    assert service._seo_route(WITH_PROBLEM, None) == ("website_draft", None)
    assert service._seo_route(NO_PROBLEM, None)[0] is None


def test_a_chosen_pick_is_refused_without_a_gap(monkeypatch):
    with pytest.raises(OutreachBlocked, match="didn't show a gap"):
        _route(WITH_PROBLEM, NAMED, requested="chatgpt_pick", monkeypatch=monkeypatch)
    assert _route(NO_PROBLEM, GAP, requested="chatgpt_pick", monkeypatch=monkeypatch) == ("chatgpt_pick", GAP)


def test_a_chosen_profile_is_refused_while_it_is_off(monkeypatch):
    with pytest.raises(OutreachBlocked, match="switched off"):
        _route(NO_PROBLEM, GAP, requested="chatgpt_profile", profile=False, monkeypatch=monkeypatch)
    assert _route(NO_PROBLEM, GAP, requested="chatgpt_profile", profile=True, monkeypatch=monkeypatch)[0] == "chatgpt_profile"


def test_an_existing_website_angle_is_kept(monkeypatch):
    stub = StubCheck(GAP)
    service = OutreachService(object(), chatgpt_check=stub)
    assert service._seo_route({**WITH_PROBLEM, "angle": "website_draft"}, None) == ("website_draft", None)
    assert stub.calls == 0


def test_the_written_pick_draft_carries_its_evidence(monkeypatch):
    monkeypatch.setattr(outreach_module, "profile_offer_enabled", lambda: False)
    service = OutreachService(object(), chatgpt_check=StubCheck(GAP))
    written = service.write_seo_draft({**NO_PROBLEM, "city": "Phoenix"}, None)
    assert written["angle"] == "chatgpt_pick"
    assert written["chatgpt_evidence"] == GAP
    assert written["prompt_version"] == seo_offer.PROMPT_VERSION
    assert "named Sparks Electric, Volt Pros LLC, Amp Brothers Electrical Services" in written["verification_note"]
    assert "I asked ChatGPT" in written["body"] and written["body"].rstrip().endswith("reach out again.")


def test_the_profile_angle_is_hidden_from_the_menu_until_switched_on(monkeypatch):
    from app.services import email_angles
    monkeypatch.setattr(email_angles, "profile_offer_enabled", lambda: False)
    assert "chatgpt_profile" not in [a["key"] for a in angle_options(SEO_WEBSITES)]
    assert "chatgpt_pick" in [a["key"] for a in angle_options(SEO_WEBSITES)]
    monkeypatch.setattr(email_angles, "profile_offer_enabled", lambda: True)
    assert "chatgpt_profile" in [a["key"] for a in angle_options(SEO_WEBSITES)]


# --- the OpenAI call ---

PAYLOAD = {"model": "gpt-5.4-mini-2026", "output": [
    {"type": "web_search_call", "id": "ws_1"},
    {"type": "message", "content": [{"type": "output_text", "text": REPLY, "annotations": [
        {"type": "url_citation", "url": "https://sparkselectric.com", "title": "Sparks"},
        {"type": "url_citation", "url": "https://sparkselectric.com", "title": "Sparks again"},
        {"type": "url_citation", "url": "https://voltpros.com", "title": "Volt"}]}]}]}


def test_the_responses_payload_gives_text_and_unique_sources():
    answer = OpenAISearchClient.parse(PAYLOAD, "gpt-5.4-mini")
    assert answer.text == REPLY
    assert [s["url"] for s in answer.sources] == ["https://sparkselectric.com", "https://voltpros.com"]
    assert answer.model == "gpt-5.4-mini-2026"
    with pytest.raises(OpenAISearchError):
        OpenAISearchClient.parse({"output": []}, "m")


def test_the_call_sends_a_web_search_request_and_reports_errors(monkeypatch):
    seen = {}

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._body, self.text = code, body, str(body)

        def json(self):
            return self._body

    def post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return Resp(*seen.get("reply", (200, PAYLOAD)))

    monkeypatch.setattr("app.integrations.openai_search.requests.post", post)
    client = OpenAISearchClient(api_key="k", model="gpt-5.4-mini")
    assert client.ask("q").text == REPLY
    assert seen["url"].endswith("/v1/responses") and seen["headers"]["Authorization"] == "Bearer k"
    assert seen["json"] == {"model": "gpt-5.4-mini", "tools": [{"type": "web_search"}], "input": "q"}
    seen["reply"] = (401, {"error": "bad key"})
    with pytest.raises(OpenAISearchError, match="401"):
        client.ask("q")


# --- against real SQL ---

@pytest.fixture(scope="module")
def pool():
    dsn = os.environ.get("DATABASE_URL")
    with ConnectionPool(dsn, open=True, kwargs={"row_factory": psycopg.rows.dict_row}) as connection_pool:
        with connection_pool.connection() as conn:
            conn.execute("delete from chatgpt_checks where vertical = 'test-trade'")
        yield connection_pool
        with connection_pool.connection() as conn:
            conn.execute("delete from chatgpt_checks where vertical = 'test-trade'")


def test_checks_are_saved_and_found_by_market_until_they_go_stale(pool):
    repo = OutreachRepository(pool)
    assert repo.latest_chatgpt_check("test-trade", "Phoenix", "AZ", 14) is None
    saved = repo.save_chatgpt_check(vertical="test-trade", city="Phoenix", state="AZ", prompt="q", response="r",
                                    sources=[{"url": "u", "title": "t"}], businesses=[{"name": "A", "website": ""}],
                                    model="m")
    found = repo.latest_chatgpt_check("test-trade", "phoenix", "AZ", 14)
    assert found["id"] == saved["id"] and found["businesses"] == [{"name": "A", "website": ""}]
    assert repo.latest_chatgpt_check("test-trade", "Phoenix", "NV", 14) is None
    with pool.connection() as conn:
        conn.execute("update chatgpt_checks set checked_at = now() - interval '15 days' where id = %s::uuid", (saved["id"],))
    assert repo.latest_chatgpt_check("test-trade", "Phoenix", "AZ", 14) is None


def test_the_evidence_is_stored_on_the_queue_item(pool):
    repo = OutreachRepository(pool)
    with pool.connection() as conn:
        conn.execute("""insert into businesses (place_id, name, city, state, vertical)
                        values ('cg-1', 'Five Point Electric', 'Phoenix', 'AZ', 'electrician')
                        on conflict (place_id) do nothing""")
        row = conn.execute("""insert into outreach_queue (place_id, channel, to_address, campaign_key, status)
                              values ('cg-1', 'email', 'a@fivepoint.com', 'seo_websites', 'queued')
                              returning id::text as id, version""").fetchone()
    try:
        updated, conflict = repo.record_generated_draft(
            row["id"], expected_version=row["version"], subject="s", body="b", claim_signal="audit_report",
            verification_status="not_required", verification_note="n", generation_model="fixed copy",
            prompt_version="seo-offer-v5", angle="chatgpt_pick", chatgpt_evidence=GAP)
        assert not conflict
        stored = repo.get_item(row["id"])
        context = repo.draft_context(row["id"])
        assert context["chatgpt_evidence"]["competitors"] == GAP["competitors"]
        assert context["state"] == "AZ" and context["angle"] == "chatgpt_pick"
        assert stored["angle"] == "chatgpt_pick"
        # Regenerating without evidence clears the old evidence.
        repo.record_generated_draft(
            row["id"], expected_version=updated["version"], subject="s", body="b", claim_signal="audit_report",
            verification_status="not_required", verification_note="n", generation_model="fixed copy",
            prompt_version="seo-offer-v5", angle="website_draft")
        assert repo.draft_context(row["id"])["chatgpt_evidence"] is None
    finally:
        with pool.connection() as conn:
            conn.execute("delete from outreach_queue_events where place_id = 'cg-1'")
            conn.execute("delete from outreach_queue where place_id = 'cg-1'")
            conn.execute("delete from businesses where place_id = 'cg-1'")


def test_openrouter_search_reply_is_parsed():
    from app.integrations.openai_search import OpenRouterSearchClient
    answer = OpenRouterSearchClient.parse({
        "model": "openai/gpt-5.2",
        "choices": [{"message": {"content": '{"recommendations": []}', "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://a.com/x", "title": "A"}},
            {"type": "url_citation", "url_citation": {"url": "https://a.com/x", "title": "A"}}]}}],
    }, "openai/gpt-5.2")
    assert answer.text == '{"recommendations": []}'
    assert answer.sources == [{"url": "https://a.com/x", "title": "A"}]
