import json

from app.integrations.openrouter import CLAIM_TOKEN
from app.integrations.openrouter_constrained import ConstrainedOutreachClient
from app.services.outreach_similarity import structural_similarity


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


PROHIBITED_GIMMICKS = (
    "want me to send",
    "want me to tell",
    "would it be useful if",
    "would you be open to",
    "i can point you to",
    "i can send the exact",
    "no need to reply",
    "you can ignore this",
    "just wanted to pass it along",
    "quick note",
    "worth flagging",
)


def assert_professional_audit_copy(body: str) -> None:
    lowered = body.lower()
    assert "audit" in lowered
    assert CLAIM_TOKEN in body
    assert all(phrase not in lowered for phrase in PROHIBITED_GIMMICKS)


def test_model_selects_structure_but_never_writes_recipient_prose(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["payload"] = json
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":1,"greeting":0,"frame":3,"closing":5}'
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
    assert_professional_audit_copy(copy.body)
    assert "loads quickly" not in copy.body.lower()
    assert "mobile" not in copy.body.lower()
    assert "error message" not in copy.body.lower()
    assert "hi richard" not in copy.body.lower()
    assert "Bright Electric Services's" not in copy.body
    assert len(copy.subject) <= 80

    user_payload = json.loads(captured["payload"]["messages"][1]["content"])
    assert user_payload == {"business_name": "Bright Electric Services"}


def test_same_model_tuple_is_decorrelated_per_business(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":3,"greeting":1,"frame":7,"closing":5}'
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
    assert all("audit" in copy.body.lower() for copy in outputs)


def test_mastercraft_and_sal_do_not_share_same_structure(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":3,"greeting":1,"frame":7,"closing":5}'
                }
            }]
        })

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    claim = "Verified application-owned claim"

    mastercraft = client.generate_email(
        business_name="MasterCraft Plumbers",
        city=None,
        vertical=None,
        verified_claim=claim,
    )
    sal = client.generate_email(
        business_name="Sal & Sons Electric Inc",
        city=None,
        vertical=None,
        verified_claim=claim,
    )

    ratio = structural_similarity(
        mastercraft.body,
        candidate_business_name="MasterCraft Plumbers",
        candidate_verified_claim=claim,
        existing_body=sal.body,
        existing_business_name="Sal & Sons Electric Inc",
        existing_verified_claim=claim,
    )

    assert ratio < 0.90


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
    assert_professional_audit_copy(copy.body)
    assert "mobile problem" not in copy.body.lower()
    assert "hi richard" not in copy.body.lower()
    assert "owner is richard" not in copy.body.lower()


def test_renderer_has_no_model_authored_claim_text(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":0,"greeting":2,"frame":0,"closing":0}'
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
    assert_professional_audit_copy(copy.body)


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
        assert len(copy.subject) <= 80
        assert_professional_audit_copy(copy.body)
        assert "loads quickly" not in copy.body.lower()
        assert "visible error" not in copy.body.lower()
        assert "mobile devices" not in copy.body.lower()

    assert len({copy.body for copy in outputs}) >= 4
    assert len({copy.subject for copy in outputs}) >= 4


def test_long_business_name_falls_back_only_when_subject_is_unreasonably_long():
    subject = ConstrainedOutreachClient._render_subject(
        "A Very Long Local Electrical Services Company Name Incorporated With Additional Words",
        0,
    )
    assert subject == "Local search audit"


def test_claim_free_copy_does_not_pretend_an_audit_finding_exists(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"subject":0,"greeting":0,"frame":0,"closing":0}'
                }
            }]
        })

    monkeypatch.setattr("app.integrations.openrouter_constrained.requests.post", fake_post)

    client = ConstrainedOutreachClient(api_key="test", model="qwen/test")
    copy = client.generate_email(
        business_name="TNT Electric",
        city=None,
        vertical=None,
        verified_claim=None,
    )

    assert CLAIM_TOKEN not in copy.body
    assert "attached" not in copy.body.lower()
    assert "audit" not in copy.body.lower()
    assert all(phrase not in copy.body.lower() for phrase in PROHIBITED_GIMMICKS)
