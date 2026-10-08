import pytest

from app.integrations.openrouter import OpenRouterError
from app.integrations.openrouter_constrained import ConstrainedOutreachClient


def test_constrained_client_refuses_claim_free_email():
    """No finding, no email: a generic cold email has nothing useful to say.

    Volume comes from audit-report grounding instead (any lead with a generated
    report can be drafted), not from substance-free copy.
    """
    client = ConstrainedOutreachClient(
        api_key="test-key",
        model="qwen/qwen3-30b-a3b-instruct-2507",
    )

    with pytest.raises(OpenRouterError, match="No verified client-facing finding"):
        client.generate_email(
            business_name="Zana Electric",
            city="Poway",
            vertical="electrician",
            verified_claim=None,
        )
