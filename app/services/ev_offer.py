"""The EV Permits email: a short offer written from verified facts.

It's written from fixed copy instead of AI. Every sentence is either true of
the offer or comes from the lead's own site and its city's published checklist.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.campaigns import permit_city
from app.services.outreach_audit_copy import clean_business_name, contact_first_name

PROMPT_VERSION = "ev-offer-v2"
_EV_WORDS = re.compile(
    r"\b(ev|evs|electric vehicles?|tesla)\b.{0,30}charg|charg.{0,30}\b(ev|evs|electric vehicles?)\b|\bevse\b",
    re.I,
)
_CLOSES = (
    "Want me to build one from a recent job of yours? It's free, so you can see the result "
    "before deciding anything.",
    "Want to see it on one of your own jobs? I'll build the first packet for free.",
    "Would a free packet from one of your recent jobs be useful? You'd see exactly what you'd "
    "get before deciding anything.",
)


def ev_evidence(context: dict[str, Any]) -> str | None:
    """Where the lead's site shows EV work, or None if it doesn't."""
    if (context.get("site_signals") or {}).get("ev_service"):
        return "homepage text"
    sources = [("service link", title) for title in context.get("offering_titles") or []]
    sources += [("page title", context.get("site_title")),
                ("page description", context.get("site_description"))]
    for label, text in sources:
        if text and _EV_WORDS.search(text):
            return label
    return None


def _variant(place_id: str, options: tuple[str, ...]) -> str:
    return options[int(hashlib.sha256(place_id.encode()).hexdigest(), 16) % len(options)]


def write_email(context: dict[str, Any], overview_url: str) -> dict[str, str]:
    city, state = context.get("city"), context.get("state")
    rules = permit_city(city, state)
    first_name = contact_first_name(context.get("to_address"), context.get("name"))
    greeting = f"Hi {first_name}," if first_name else "Hi there,"
    business = clean_business_name(context.get("name"))
    if rules and rules.get("asks_for"):
        opener = (f"{city} wants {rules['asks_for']} on EV jobs. Since {business} does EV installs, "
                  "someone on your team is likely retyping the same job details into each one.")
        note = f"Grounded in {city}'s published checklist: {rules['source']}"
    else:
        opener = (f"Since {business} does EV installs, someone on your team is likely retyping the "
                  "same job details into every permit form and document.")
        note = "No city-specific permit claim was made."
    body = (
        f"{greeting}\n\n{opener}\n\n"
        "I build a system for electrical companies that takes the job details once and drafts the "
        "full permit packet, ready for your team to review and submit.\n\n"
        f"{_variant(context['place_id'], _CLOSES)}\n\n"
        f"Here's how it works, with a sample packet: {overview_url}"
    )
    subject = f"{city} EV permits" if city else "EV permit paperwork"
    return {"subject": subject, "body": body, "note": note}
