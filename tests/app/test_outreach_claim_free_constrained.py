from app.integrations.openrouter import CLAIM_TOKEN
from app.integrations.openrouter_constrained import ConstrainedOutreachClient


def test_constrained_client_renders_claim_free_email(monkeypatch):
    client = ConstrainedOutreachClient(
        api_key="test-key",
        model="qwen/qwen3-30b-a3b-instruct-2507",
    )

    monkeypatch.setattr(
        client,
        "_choose_style",
        lambda business_name: (client._deterministic_choice(business_name), False),
    )

    result = client.generate_email(
        business_name="Zana Electric",
        city="Poway",
        vertical="electrician",
        verified_claim=None,
    )

    assert result.subject
    assert result.body
    assert "Zana Electric" in result.body
    assert CLAIM_TOKEN not in result.body
    assert result.model == "application/constrained-outreach"
