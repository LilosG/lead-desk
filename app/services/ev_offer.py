"""The EV Permits email: a short offer written from verified facts.

It's written from fixed copy instead of AI. Every sentence is either true of
the offer or comes from the lead's own site and its city's published checklist.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.campaigns import permit_city
from app.services.outreach_audit_copy import contact_first_name

PROMPT_VERSION = "ev-offer-v1"
_EV_WORDS = re.compile(
    r"\b(ev|evs|electric vehicles?|tesla)\b.{0,30}charg|charg.{0,30}\b(ev|evs|electric vehicles?)\b|\bevse\b",
    re.I,
)
_CLOSES = (
    "Send me a recent EV job and I'll build the full packet for free, so you can see if it's worth using.",
    "If you send me one recent EV install, I'll build the full packet for free so you can judge it yourself.",
    "Want to see it on a real job? Send me a recent EV install and I'll build the packet for free.",
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
    if rules and rules.get("asks_for"):
        opener = (f"I saw you install EV chargers. {city} asks for {rules['asks_for']} on these "
                  "jobs, which is a lot of office time for one install.")
        note = f"Grounded in {city}'s published checklist: {rules['source']}"
    else:
        opener = "I saw you install EV chargers. The permit paperwork can take a lot of office time for one install."
        note = "No city-specific permit claim was made."
    body = (
        f"{greeting}\n\n{opener}\n\n"
        "The information is the same every time, but someone still has to retype it into every "
        "form and document. I build systems that do that part, so your team only reviews and submits.\n\n"
        f"{_variant(context['place_id'], _CLOSES)} Here's a sample: {overview_url}"
    )
    subject = f"{city} EV permits" if city else "EV permit paperwork"
    return {"subject": subject, "body": body, "note": note}
