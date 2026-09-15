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
