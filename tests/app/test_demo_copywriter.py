import json

import pytest

from app.services.demo_copywriter import DemoCopyError, checked_copy, write_demo_copy
from app.services.demo_sites import DemoSiteError, DemoSiteService

FACTS = {
    "name": "Route 66 Electric", "category": "Electrician", "city": "Tucson",
    "areas": ["Tucson", "Marana"], "services": ["Panel Upgrades", "EV Charger Installation"],
    "audience": "homeowners", "rating": 4.8, "review_count": 126,
    "review_texts": ["Tidy, clear and on time."], "site_summary": "Electrical contractor in Tucson",
}


class FakeResponse:
    def __init__(self, content, ok=True, status=200):
        self.ok, self.status_code, self._content = ok, status, content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _post(content, captured=None, **kw):
    def post(url, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        return FakeResponse(content, **kw)
    return post


def test_good_copy_passes_and_keeps_real_numbers():
    data = {
        "headline": "Tucson's 4.8-star electrician",
        "subheadline": "Route 66 Electric helps homeowners across Tucson and Marana with panels and EV chargers.",
        "about": "Customers on Google describe Route 66 Electric as tidy and clear, with 126 reviews averaging 4.8.",
        "service_blurbs": {"Panel Upgrades": "For older panels that trip or can't keep up.", "Unknown": "x"},
    }
    result = write_demo_copy(FACTS, api_key="k", model="qwen/qwen3-30b-a3b-instruct-2507",
                             post=_post("```json\n" + json.dumps(data) + "\n```"))
    assert result["headline"] == data["headline"]
    assert result["about"] == data["about"]
    assert result["service_blurbs"] == {"Panel Upgrades": data["service_blurbs"]["Panel Upgrades"]}


@pytest.mark.parametrize("text", [
    "Licensed and insured electricians in Tucson",
    "Serving Tucson for over 20 years",
    "Same-day service across Tucson",
    "Tucson's best electrician",
    "We handle every job with care",
    "Rated 5.0 by 300 customers",
    "Free estimates on every panel",
])
def test_unbacked_claims_and_invented_numbers_are_dropped(text):
    result = checked_copy({"headline": text, "subheadline": text, "about": text}, FACTS)
    assert "headline" not in result and "subheadline" not in result and "about" not in result


def test_overlong_fields_are_dropped():
    assert "headline" not in checked_copy({"headline": "Tucson electrician " * 10}, FACTS)


def test_gpt5_requests_use_minimal_reasoning():
    captured = {}
    write_demo_copy(FACTS, api_key="k", model="openai/gpt-5-mini",
                    post=_post(json.dumps({"headline": "Electrician in Tucson"}), captured))
    assert captured["json"]["reasoning"]["effort"] == "minimal"
    assert "temperature" not in captured["json"]


def test_failures_raise_a_clear_error():
    with pytest.raises(DemoCopyError):
        write_demo_copy(FACTS, api_key="k", model="m", post=_post("no json here"))
    with pytest.raises(DemoCopyError):
        write_demo_copy(FACTS, api_key="k", model="m", post=_post("{}", ok=False, status=500))
    with pytest.raises(DemoCopyError):
        write_demo_copy(FACTS, api_key="k", model="m", post=_post(json.dumps({"headline": "Licensed pros"})))


class Repo:
    def get_prospect(self, place_id):
        return {"place_id": place_id, "name": "Route 66 Electric", "vertical": "electrician",
                "primary_type": "electrician", "city": "Tucson", "rating": 4.8, "review_count": 126}


def test_service_write_copy_wraps_errors(monkeypatch):
    from app.services import demo_sites as module

    monkeypatch.setattr(module, "write_demo_copy", lambda facts, **kw: {"headline": facts["name"], "service_blurbs": {}, "model": "m"})
    result = DemoSiteService(Repo(), None).write_copy("p", services=[], service_areas=[], api_key="k", model="m")
    assert result["headline"] == "Route 66 Electric"

    def boom(facts, **kw):
        raise DemoCopyError("bad")
    monkeypatch.setattr(module, "write_demo_copy", boom)
    with pytest.raises(DemoSiteError):
        DemoSiteService(Repo(), None).write_copy("p", services=[], service_areas=[], api_key="k", model="m")


def test_v4_page_uses_ai_about_and_blurbs(tmp_path):
    from tests.app.test_demo_sites_v3 import FakeDemoRepository
    from tests.app.test_demo_sites_v4 import V4Repo

    demo = DemoSiteService(V4Repo(), FakeDemoRepository()).create_demo(
        "p1", template_key="premium-v4", services=["Panel Upgrades"], service_areas=["Vista"],
        headline=None, subheadline=None, about="Customers praise the tidy work.",
        service_blurbs={"Panel Upgrades": "For panels that trip.", "Not listed": "ignored"},
        use_site_branding=False, media_root=tmp_path, media_base_url="https://d.example",
    )
    assert "Customers praise the tidy work." in demo["html_document"]
    assert "For panels that trip." in demo["html_document"]
    assert demo["content_snapshot"]["service_blurbs"] == {"Panel Upgrades": "For panels that trip."}
