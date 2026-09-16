import json

from app.integrations.openrouter import CLAIM_TOKEN
from app.integrations.openrouter_constrained import ConstrainedOutreachClient


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


def test_model_selects_style_but_never_writes_recipient_prose(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["payload"] = json
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":1,"greeting":0,"opener":3,"closing":5,"rhythm":1}'
                }
            }]
        })

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    copy = client.generate_email(
        business_name="Bright Electric Services",
        city="San Diego",
        vertical="electrician",
        verified_claim="Verified application-owned claim",
    )

    assert copy.model == "qwen/test"
    assert copy.body.count(CLAIM_TOKEN) == 1
    assert "loads quickly" not in copy.body.lower()
    assert "mobile" not in copy.body.lower()
    assert "error message" not in copy.body.lower()
    assert "hi richard" not in copy.body.lower()
    assert "Bright Electric Services's" not in copy.body
    assert len(copy.subject) <= 55
    assert len(copy.subject.split()) <= 5

    user_payload = json.loads(captured["payload"]["messages"][1]["content"])
    assert user_payload == {"business_name": "Bright Electric Services"}


def test_same_model_tuple_is_decorrelated_per_business(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":3,"greeting":1,"opener":7,"closing":12,"rhythm":2}'
                }
            }]
        })

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    businesses = ["TNT Electric", "Sparks Electric", "Voltage Bros"]

    outputs = [
        client.generate_email(
            business_name=business,
            city=None,
            vertical=None,
            verified_claim="Verified application-owned claim",
        )
        for business in businesses
    ]

    assert len({copy.body for copy in outputs}) == len(outputs)
    assert all(copy.body.count(CLAIM_TOKEN) == 1 for copy in outputs)
    assert all(copy.model == "qwen/test" for copy in outputs)


def test_invalid_model_payload_falls_back_to_application_owned_copy(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": "I found a mobile problem and the owner is Richard"
                }
            }]
        })

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    copy = client.generate_email(
        business_name="Richard Olinger Electric",
        city="San Diego",
        vertical="electrician",
        verified_claim="Verified application-owned claim",
    )

    assert copy.model == "application/constrained-outreach"
    assert copy.body.count(CLAIM_TOKEN) == 1
    assert "mobile problem" not in copy.body.lower()
    assert "hi richard" not in copy.body.lower()
    assert "owner is richard" not in copy.body.lower()


def test_renderer_has_no_model_authored_claim_text(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":0,"greeting":2,"opener":0,"closing":0,"rhythm":0}'
                }
            }]
        })

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    copy = client.generate_email(
        business_name="TNT Electric",
        city=None,
        vertical=None,
        verified_claim="Verified application-owned claim",
    )

    assert copy.body.count(CLAIM_TOKEN) == 1
    assert "Verified application-owned claim" not in copy.body


def test_subjects_and_bodies_stay_bounded_across_fallback_styles(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({}, ok=False)

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    businesses = [
        "Bright Electric Services",
        "TNT Electric",
        "Richard Olinger Electric",
        "Cano Electric",
        "Coastal Power Co",
        "A Very Long Local Electrical Services Company Name Incorporated",
    ]

    outputs = []
    for business in businesses:
        copy = client.generate_email(
            business_name=business,
            city=None,
            vertical=None,
            verified_claim="Verified application-owned claim",
        )
        outputs.append(copy)
        assert copy.body.count(CLAIM_TOKEN) == 1
        assert len(copy.subject) <= 55
        assert len(copy.subject.split()) <= 5
        assert "loads quickly" not in copy.body.lower()
        assert "visible error" not in copy.body.lower()
        assert "mobile devices" not in copy.body.lower()

    assert len({copy.body for copy in outputs}) >= 4
    assert len({copy.subject for copy in outputs}) >= 4
