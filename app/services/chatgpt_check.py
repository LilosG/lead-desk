"""Does ChatGPT recommend this lead? One cached lookup per market, strict matching.

The question is asked once per (trade, city, state) and reused for 14 days, so
a market of 40 leads costs one search call. A lead only gets the "you didn't
come up" email when ChatGPT named at least two real local competitors and
nothing in its answer points at the lead, by name or by website. When in doubt
the lead counts as named: wrongly telling an owner they're missing is the
error that costs credibility.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse

from app.integrations.openai_search import OpenAISearchError, SearchAnswer

log = logging.getLogger(__name__)

CACHE_DAYS = 14
MIN_COMPETITORS = 2
MAX_NAMED = 3

_TRADE_PLURALS = {
    "electrician": "electricians",
    "plumber": "plumbers",
    "hvac": "HVAC companies",
    "roofing": "roofers",
    "restoration": "water damage restoration companies",
    "landscaping": "landscapers",
    "party_rentals": "party rental companies",
    "handyman": "handymen",
    "real_estate_agent": "real estate agents",
    "med_spa": "med spas",
    "dentist": "dentists",
    "chiropractor": "chiropractors",
    "personal_injury_attorney": "personal injury attorneys",
    "auto_repair": "auto repair shops",
}

# Lists and aggregators, never a competitor to name.
_DIRECTORY_DOMAINS = {
    "yelp.com", "angi.com", "angieslist.com", "thumbtack.com", "homeadvisor.com", "bbb.org",
    "nextdoor.com", "yellowpages.com", "mapquest.com", "porch.com", "houzz.com", "expertise.com",
    "facebook.com", "instagram.com", "google.com", "reddit.com", "fixr.com", "networx.com",
    "buildzoom.com", "superpages.com", "manta.com", "tripadvisor.com", "zocdoc.com", "healthgrades.com",
    "avvo.com", "justia.com", "zillow.com", "realtor.com", "trulia.com", "carfax.com", "repairpal.com",
    "linkedin.com", "youtube.com", "yahoo.com", "bing.com", "mapquest.com", "chamberofcommerce.com",
}
_DIRECTORY_NAMES = {
    "yelp", "angi", "angie's list", "thumbtack", "homeadvisor", "bbb", "better business bureau",
    "nextdoor", "yellow pages", "yellowpages", "google maps", "google", "porch", "houzz", "expertise",
    "facebook", "reddit", "fixr", "networx", "buildzoom", "zocdoc", "healthgrades", "avvo",
}
# Words that don't tell two businesses apart.
_FILLER = {
    "llc", "inc", "co", "corp", "corporation", "company", "the", "and", "of", "services", "service",
    "electric", "electrical", "electrician", "electricians", "plumbing", "plumber", "plumbers", "hvac",
    "heating", "air", "cooling", "roofing", "roofers", "roofer", "contractors", "contractor",
    "solutions", "group", "pros", "pro",
}


def trade_phrase(vertical: str | None) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", (vertical or "").lower()).strip("_")
    if key in _TRADE_PLURALS:
        return _TRADE_PLURALS[key]
    label = key.replace("_", " ") or "local businesses"
    return label if label.endswith("s") else f"{label}s"


def build_prompt(vertical: str | None, city: str, state: str | None) -> str:
    place = f"{city}, {state}" if state else city
    return (
        f"Who are the best {trade_phrase(vertical)} in {place}? Look it up and recommend a few "
        "local businesses. Reply with only JSON, no other text, in this shape: "
        '{"recommendations": [{"name": "Business Name", "website": "example.com"}]}'
    )


def registered_domain(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    host = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else None


def _tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and "))
    tokens = cleaned.split()
    core = [t for t in tokens if t not in _FILLER]
    return core or [t for t in tokens if t not in {"the", "and", "of"}] or tokens


def _is_directory(name: str, website: str | None) -> bool:
    if (name or "").strip().lower() in _DIRECTORY_NAMES:
        return True
    return registered_domain(website) in _DIRECTORY_DOMAINS


def parse_businesses(text: str) -> list[dict[str, str]]:
    """The recommendations in the model's JSON reply. Anything else parses to nothing."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    rows = data.get("recommendations") if isinstance(data, dict) else None
    out: list[dict[str, str]] = []
    for row in rows or []:
        if isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"].strip():
            website = row.get("website")
            out.append({"name": row["name"].strip(),
                        "website": website.strip() if isinstance(website, str) else ""})
    return out


def competitors(businesses: list[dict[str, str]]) -> list[dict[str, str]]:
    """Real local businesses: no directories, no repeats."""
    seen: set[tuple[str, ...]] = set()
    kept: list[dict[str, str]] = []
    for row in businesses:
        if _is_directory(row["name"], row.get("website")):
            continue
        key = tuple(_tokens(row["name"]))
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _names_match(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small) >= 2 and set(small) <= set(large)


def is_named(name: str, website: str | None, businesses: list[dict[str, str]],
             response: str, sources: list[dict[str, str]]) -> bool:
    """Any sign of the lead in ChatGPT's answer counts, so a near miss is never reported as absent."""
    domain = registered_domain(website)
    if domain:
        if any(registered_domain(b.get("website")) == domain for b in businesses):
            return True
        if any(registered_domain(s.get("url")) == domain for s in sources):
            return True
    if any(_names_match(name, b["name"]) for b in businesses):
        return True
    core = " ".join(_tokens(name))
    flat = " ".join(re.sub(r"[^a-z0-9 ]+", " ", (response or "").lower().replace("&", " and ")).split())
    return bool(core) and re.search(rf"\b{re.escape(core)}\b", flat) is not None


class SearchClient(Protocol):
    model: str

    def ask(self, prompt: str) -> SearchAnswer: ...


class ChatGPTCheckService:
    def __init__(self, repository: Any, client: SearchClient, *, now: Any = None) -> None:
        self.repository = repository
        self.client = client
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _market_check(self, vertical: str, city: str, state: str) -> dict[str, Any] | None:
        cached = self.repository.latest_chatgpt_check(vertical, city, state, CACHE_DAYS)
        if cached:
            return cached
        prompt = build_prompt(vertical, city, state)
        try:
            answer = self.client.ask(prompt)
        except OpenAISearchError as exc:
            log.warning("ChatGPT check failed for %s / %s, %s: %s", vertical, city, state, exc)
            return None
        if not answer.sources:
            # No links back means we can't show it came from a real search. Don't cache it or use it.
            log.warning("ChatGPT check for %s / %s, %s came back with no sources; ignored", vertical, city, state)
            return None
        return self.repository.save_chatgpt_check(
            vertical=vertical, city=city, state=state, prompt=prompt, response=answer.text,
            sources=answer.sources, businesses=parse_businesses(answer.text), model=answer.model or self.client.model,
        )

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """The evidence for this lead, or None when the check couldn't run."""
        vertical, city = context.get("vertical"), context.get("city")
        if not vertical or not city:
            return None
        state = (context.get("state") or "").strip().upper()
        check = self._market_check(vertical, city.strip(), state)
        if check is None:
            return None
        rivals = competitors(check["businesses"])
        website = context.get("resolved_url") or context.get("website_url")
        named = is_named(context.get("name") or "", website, check["businesses"],
                         check["response"], check["sources"])
        return {
            "check_id": check["id"],
            "checked_at": check["checked_at"],
            "model": check["model"],
            "prompt": check["prompt"],
            "response": check["response"],
            "sources": check["sources"],
            "competitors": [r["name"] for r in rivals],
            "prospect_named": named,
        }


def has_gap(evidence: dict[str, Any] | None) -> bool:
    """ChatGPT named real competitors and nothing in its answer points at the lead."""
    return bool(evidence and not evidence["prospect_named"]
                and len(evidence["competitors"]) >= MIN_COMPETITORS)
