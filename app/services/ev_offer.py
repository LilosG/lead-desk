"""The EV Permits emails: short offers written from verified facts.

They're written from fixed copy instead of AI. Every sentence is either true of
the offer as Mike sells it or comes from the lead's own site and its city's
published checklist.

Touch 1 carries no link: it only asks whether they want the sample. Touch 2
sends the sample packet and offers to run one of their past installs free.

Never promise permit approval or a set number of hours. The city decides
approvals, and hours depend on the shop. "Four electrical shops" is Mike's
figure for shops that have used the automation.
"""
from __future__ import annotations

import os
import re
from typing import Any

from app.campaigns import EV_SERVICE_PATTERN, permit_city
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
    team_greeting,
)

PROMPT_VERSION = "ev-offer-v6"
DEFAULT_OVERVIEW_URL = "https://ev-permit-packets.vercel.app/"
_EV_WORDS = re.compile(EV_SERVICE_PATTERN, re.I)


def overview_url() -> str:
    """The sample packet page. EV_OVERVIEW_URL points it at a custom domain."""
    return (os.environ.get("EV_OVERVIEW_URL") or "").strip() or DEFAULT_OVERVIEW_URL


def ev_evidence(context: dict[str, Any]) -> str | None:
    """Where the lead's site shows EV work, or None if it doesn't."""
    signals = context.get("site_signals") or {}
    if signals.get("ev_strength") == "page":
        return f"EV page ({signals.get('ev_page_path')})"
    if signals.get("ev_service"):
        return "site text"
    sources = [("service link", title) for title in context.get("offering_titles") or []]
    sources += [("page title", context.get("site_title")),
                ("page description", context.get("site_description"))]
    for label, text in sources:
        if text and _EV_WORDS.search(text):
            return label
    return None


def _join(names: list[str]) -> str:
    return " and ".join(names[:2])


def _brands_line(ctx: dict[str, Any]) -> str:
    """Proof we looked at their site, when it names the chargers they install."""
    brands = ctx["brands"]
    return f"Saw {ctx['short']} installs {_join(brands)} chargers. " if brands else ""


def _drawings(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    rules = ctx["rules"]
    if rules and rules.get("asks_for"):
        ask = f"{ctx['city']} wants {rules['asks_for']} on every residential charger permit."
    else:
        ask = ("A lot of cities want a site plan, single-line and load calc on residential charger "
               "permits.")
    return f"Who draws {possessive(ctx['short'])} EV site plans?", [
        f"{_brands_line(ctx)}{ask} Who's stuck drawing those at {ctx['short']}, you or the office?",
        "Four electrical shops have stopped doing it by hand. Their tech fills out a quick job form "
        "on site, and the site plan on the actual property, the single-line and the load calc come "
        "back ready to sign and submit.",
        "Want me to send a sample packet so you can judge the drawings?",
    ]


def _desk_work(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    return f"EV permit desk work at {ctx['short']}", [
        f"{_brands_line(ctx)}On a residential EV charger, the install is the easy part. The site "
        "plan, single-line and load calc are the desk work nobody gets paid for.",
        "We built a setup that draws all three from one tech form on site, on the actual property, "
        "ready for your sign-off. Four electrical shops have used it so far.",
        "Want me to send a sample packet so you can see the drawings?",
    ]


_WRITERS = {
    "drawings": _drawings,
    "desk_work": _desk_work,
}


def _facts(context: dict[str, Any]) -> dict[str, Any]:
    city = context.get("city")
    signals = context.get("site_signals") or {}
    name = clean_business_name(context.get("name"))
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    return {
        "name": name,
        "short": short_name(name),
        "city": city,
        "first_name": first_name,
        "brands": [b for b in signals.get("ev_brands") or [] if b],
        "greeting": team_greeting(first_name, name),
        "rules": permit_city(city, context.get("state")),
    }


def write_email(context: dict[str, Any], angle: str) -> dict[str, str]:
    facts = _facts(context)
    subject, paragraphs = _WRITERS[angle](facts)
    rules = facts["rules"]
    note = (f"City line from {context.get('city')}'s published checklist: {rules['source']}"
            if rules and rules.get("asks_for") else "No city-specific permit claim was made.")
    if not facts["first_name"]:
        note += " No contact name found."
    body = "\n\n".join([facts["greeting"], *paragraphs])
    return {"subject": subject, "body": body, "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    facts = _facts(context)
    if step == 2:
        paragraphs = [
            "Figured it's easier to just show you. Here's a full sample packet with the site plan, "
            f"single-line and load calc, all from one tech form: {overview_url()}",
            "If you want to test it against what your office turns in now, reply with the address "
            "and panel size from a past install and I'll run that packet free.",
        ]
    else:
        paragraphs = [
            "Last note from me. If your office still draws EV site plans and load calcs by hand, "
            "reply with a past install and I'll draw it up free. If not, no worries.",
        ]
    return "\n\n".join([facts["greeting"], *paragraphs])
