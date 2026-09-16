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
                    "content": '{"greeting":0,"opener":1,"closing":4,"rhythm":1}'
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

    assert copy.subject == "Bright Electric Services"
    assert copy.body.count(CLAIM_TOKEN) == 1
    assert "loads quickly" not in copy.body.lower()
    assert "mobile" not in copy.body.lower()
    assert "error message" not in copy.body.lower()
    assert "hi richard" not in copy.body.lower()
    assert "Bright Electric Services's" not in copy.body

    user_payload = json.loads(captured["payload"]["messages"][1]["content"])
    assert user_payload == {"business_name": "Bright Electric Services"}


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
                    "content": '{"greeting":2,"opener":6,"closing":7,"rhythm":2}'
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

    assert copy.body == (
        f"{CLAIM_TOKEN}\n\nNo need to reply if you already have this covered."
    )
