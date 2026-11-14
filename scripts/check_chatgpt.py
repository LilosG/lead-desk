"""Run the ChatGPT check for one market and print what it found. Uses the cache like the app does.

Usage (from the lead-desk folder, venv active):
  python scripts/check_chatgpt.py electrician "Phoenix" AZ
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.core.database import open_pool, pool  # noqa: E402
from app.integrations.openai_search import OpenAISearchClient, OpenRouterSearchClient  # noqa: E402
from app.repositories.outreach import OutreachRepository  # noqa: E402
from app.services.chatgpt_check import ChatGPTCheckService  # noqa: E402


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    vertical, city, state = sys.argv[1:4]
    open_pool()
    settings = get_settings()
    if settings.openai_api_key:
        client = OpenAISearchClient(api_key=settings.openai_api_key, model=settings.openai_search_model)
    elif settings.openrouter_api_key:
        client = OpenRouterSearchClient(api_key=settings.openrouter_api_key, model=settings.openrouter_search_model)
    else:
        print("Neither OPENAI_API_KEY nor OPENROUTER_API_KEY is set in .env")
        return 1
    service = ChatGPTCheckService(OutreachRepository(pool), client)
    evidence = service.evaluate({"vertical": vertical, "city": city, "state": state,
                                 "name": "Nobody In Particular Co", "website_url": None})
    if evidence is None:
        print(f"The check failed (model {client.model}). See the service log for the error.")
        return 1
    print("Model:       ", evidence["model"])
    print("Checked at:  ", evidence["checked_at"])
    print("Question:    ", evidence["prompt"])
    print("Competitors: ", ", ".join(evidence["competitors"]) or "(none parsed)")
    print("Sources:     ", len(evidence["sources"]))
    print("\nAnswer:\n", evidence["response"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
