import json

from app.integrations.openrouter import CLAIM_TOKEN, GeneratedCopy, OpenRouterError
from app.integrations.openrouter_structured import (
    OUTREACH_RESPONSE_SCHEMA,
    StructuredOpenRouterClient,
)


def test_structured_schema_requires_subject_and_body_only():
    assert OUTREACH_RESPONSE_SCHEMA["required"] == ["subject", "body"]
    assert OUTREACH_RESPONSE_SCHEMA["additionalProperties"] is False


def test_structured_parser_accepts_plain_json_text():
    parsed = StructuredOpenRouterClient._parse_structured_content(
        json.dumps({"subject": "Example Electric", "body": "Hi there"})
    )
    assert parsed == {"subject": "Example Electric", "body": "Hi there"}


def test_structured_parser_accepts_typed_text_content_array():
    parsed = StructuredOpenRouterClient._parse_structured_content(
        [{"type": "text", "text": '{"subject":"Example Electric","body":"Hi there"}'}]
    )
    assert parsed == {"subject": "Example Electric", "body": "Hi there"}


def test_structured_request_uses_schema_minimal_reasoning_and_completion_budget(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "Example Electric",
                                    "body": "Hi, I was on Example Electric's website earlier. [[VERIFIED_FINDING]] I can point to the exact spot if useful.",
                                }
                            )
                        }
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.integrations.openrouter_structured.requests.post", fake_post)

    client = StructuredOpenRouterClient(
        api_key="test-key",
        model="openai/gpt-5-mini",
    )
    subject, body = client._request_copy(
        system="system",
        user="user",
        temperature=0.45,
    )

    assert subject == "Example Electric"
    assert "[[VERIFIED_FINDING]]" in body
    assert captured["payload"]["max_completion_tokens"] == 500
    assert captured["payload"]["reasoning"] == {
        "effort": "minimal",
        "exclude": True,
    }
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["payload"]["response_format"]["json_schema"]["strict"] is True
    assert captured["payload"]["provider"]["require_parameters"] is True
    assert "temperature" not in captured["payload"]


def test_structured_generation_blocks_when_no_client_facing_finding_exists():
    client = StructuredOpenRouterClient(
        api_key="test-key",
        model="openai/gpt-5-mini",
    )

    try:
        client.generate_email(
            business_name="Example Electric",
            city="San Diego",
            vertical="electrician",
            verified_claim=None,
        )
    except OpenRouterError as exc:
        assert "No approved client-facing finding" in str(exc)
    else:
        raise AssertionError("claim-free first-touch generation must be blocked")


def test_structured_validator_rejects_model_signature_and_site_profile_language():
    body = (
        "Hi, I looked at Example Electric's website earlier. "
        f"{CLAIM_TOKEN} If you'd like, I can point to the exact place I mean "
        "or send a screenshot so you can see what I am referring to.\n\n"
        "Thanks,\nMike at LILOs Growth"
    )

    try:
        StructuredOpenRouterClient._validate_copy(
            subject="Example Electric",
            body=body,
            has_verified_claim=True,
            business_name="Example Electric",
            city="San Diego",
            vertical="electrician",
        )
    except OpenRouterError as exc:
        assert "signature" in str(exc).lower()
    else:
        raise AssertionError("model-generated signatures must be rejected")

    body = (
        "Hi, I looked at Example Electric's site/profile earlier. "
        f"{CLAIM_TOKEN} If you'd like, I can point to the exact place I mean "
        "or send a screenshot so you can see what I am referring to."
    )
    try:
        StructuredOpenRouterClient._validate_copy(
            subject="Example Electric",
            body=body,
            has_verified_claim=True,
            business_name="Example Electric",
            city="San Diego",
            vertical="electrician",
        )
    except OpenRouterError as exc:
        assert "site/profile" in str(exc)
    else:
        raise AssertionError("site/profile wording must be rejected")


def test_structured_generation_removes_duplicate_token_punctuation(monkeypatch):
    def fake_parent_generate(self, **kwargs):
        return GeneratedCopy(
            subject="Example Electric",
            body=(
                "Hi, I looked at Example Electric's website earlier. "
                f"{CLAIM_TOKEN}. If you'd like, I can point to the exact place "
                "I mean or send a screenshot so you can see it."
            ),
            model="openai/gpt-5-mini",
        )

    monkeypatch.setattr(
        "app.integrations.openrouter.OpenRouterClient.generate_email",
        fake_parent_generate,
    )

    client = StructuredOpenRouterClient(
        api_key="test-key",
        model="openai/gpt-5-mini",
    )
    copy = client.generate_email(
        business_name="Example Electric",
        city="San Diego",
        vertical="electrician",
        verified_claim=(
            "The homepage isn't currently using structured business markup to identify the company to Google."
        ),
    )

    assert f"{CLAIM_TOKEN}." not in copy.body
    assert copy.body.count(CLAIM_TOKEN) == 1
