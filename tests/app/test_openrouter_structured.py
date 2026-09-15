import json

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
                                    "body": "Hi, I was on Example Electric's site earlier. [[VERIFIED_FINDING]] I can point to the exact spot if useful.",
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
