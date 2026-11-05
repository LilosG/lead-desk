"""The EV Permits email: a short offer written from verified facts.

It's written from fixed copy instead of AI. Every sentence is either true of
the offer or comes from the lead's own site and its city's published checklist.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.campaigns import EV_SERVICE_PATTERN, permit_city
from app.services.outreach_audit_copy import clean_business_name, contact_first_name

PROMPT_VERSION = "ev-offer-v3"
_EV_WORDS = re.compile(EV_SERVICE_PATTERN, re.I)
_CLOSES = (
    "Want to see it on one of your own jobs? I'll build the first packet for free so you can compare.",
    "Want me to run one of your recent jobs through it? The first packet is free, so you can compare.",
    "Would a free packet from one of your recent jobs be useful? You could compare it with what your "
    "office does today.",
)
_WHAT_IT_DOES = (
    "I build an automated system for electrical companies that handles that work. Your tech fills "
    "out a short form on site. The system checks your city's requirements, runs the numbers, drafts "
    "the full permit packet and flags anything missing. Your team just reviews it and submits."
)
# The example figures from the overview page's calculator: 8 permits x 3.25 hours.
_TIME_SAVED = (
    "For example, if a packet takes your office 4 hours and you pull 8 permits a month, getting each "
    "one down to a 45-minute review gives you back 26 hours a month."
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
        opener = (f"{city} wants {rules['asks_for']} on EV jobs. That's a lot of office time for one "
                  "install, and most of it is retyping the same job details.")
        note = f"Grounded in {city}'s published checklist: {rules['source']}"
    else:
        opener = ("Every EV install means permit paperwork: checking what the city wants, running the "
                  "load calculation, then building the site plan and diagrams. Most of it is retyping "
                  "the same job details.")
        note = "No city-specific permit claim was made."
    body = (
        f"{greeting}\n\n{opener}\n\n{_WHAT_IT_DOES}\n\n{_TIME_SAVED}\n\n"
        f"{_variant(context['place_id'], _CLOSES)}\n\n"
        f"Here's how it works, with a sample packet: {overview_url}"
    )
    subject = f"Cutting EV permit paperwork at {business}"
    return {"subject": subject, "body": body, "note": note}
