"""The EV Permits emails: short offers written from verified facts.

They're written from fixed copy instead of AI. Every sentence is either true of
the offer as Mike sells it or comes from the lead's own site and its city's
published checklist. No links or attachments in the first email.

Never promise permit approval or a set number of hours. The city decides
approvals, and hours depend on the shop. "About 90%" is Mike's figure for
residential EV charger packets.
"""
from __future__ import annotations

import re
from typing import Any

from app.campaigns import EV_SERVICE_PATTERN, permit_city
from app.services.email_angles import stable_pick
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
    team_greeting,
)

PROMPT_VERSION = "ev-offer-v4"
_EV_WORDS = re.compile(EV_SERVICE_PATTERN, re.I)


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


def _proof_line(name: str, signals: dict[str, Any], city: str | None) -> str:
    """What we saw on their own site, as specific as the site allows."""
    where = f" in {city}" if city else ""  # Callers pass no city when the next line names it.
    brands = signals.get("ev_brands") or []
    if brands:
        return f"Saw {name} installs {_join(brands)} chargers{where}."
    if signals.get("ev_strength") == "page":
        return f"Saw the EV charger page on {possessive(name)} site."
    return f"Saw {name} does EV charger installs{where}."


def _paperwork_line(rules: dict[str, str] | None, city: str | None) -> str:
    if rules and rules.get("asks_for"):
        return f"{city} wants {rules['asks_for']} on those jobs."
    return "Each one means a load calc, drawings and checking what the city wants."


_FREE_PACKET_ASKS = (
    "Send me your next EV job and I'll build the whole packet for free. If your office could've done "
    "better, you've lost nothing.",
    "Send me a recent EV job and I'll build that packet for free, so you can compare it with what "
    "your office does now.",
)
_DRAWINGS_ASKS = (
    "Want to see it on a real job? Send me a recent EV job and I'll build it for free.",
    "Send me one recent EV job and I'll draw it up for free.",
)


def _free_packet(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    return f"{possessive(ctx['short'])} next EV permit", [
        f"{ctx['proof']} {ctx['paperwork']}",
        "We built a system that does about 90% of that packet. Your tech fills out one short form, and "
        "it handles the city research, drawings and load calc and flags anything missing. Your office "
        "just reviews and submits, so it gets that time back on every install.",
        stable_pick(ctx["place_id"], _FREE_PACKET_ASKS),
    ]


def _drawings(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    rules = ctx["rules"]
    opener = (f"{ctx['city']} wants {rules['asks_for']} on EV jobs. Who draws those at {ctx['short']}?"
              if rules and rules.get("asks_for")
              else f"Who draws the site plans and one-lines on {possessive(ctx['short'])} EV jobs?")
    return "Who draws your EV site plans?", [
        opener,
        "We built a system that does it from one short job form. It draws the site plan on the actual "
        "property, the one-line diagram and the load calc, then builds the rest of the packet and "
        "flags anything missing.",
        "Your team reviews and signs off, so nothing goes to the city without them.",
        stable_pick(ctx["place_id"], _DRAWINGS_ASKS),
    ]


def _time_back(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    return f"Time on EV permits at {ctx['short']}", [
        "How long does your office spend putting together one EV permit packet?",
        f"{ctx['proof']} Whatever that number is, we can take about 90% of it off your plate. One short "
        "form from your tech, and the city research, load calc, drawings and packet are done and "
        "waiting for review.",
        "That's office time back on every install, without adding staff.",
        "What's your number? A rough guess is fine.",
    ]


def _guarantee(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    return "30-day EV permit test", [
        f"{ctx['proof']} {ctx['paperwork']}",
        "We set up a system around the cities you work in. From one short job form it builds about 90% "
        "of the packet: site plan, one-line, load calc and the rest, ready for your team to review.",
        "If it isn't producing packets you'd be comfortable submitting within the first 30 days, you get "
        "your initial payment back.",
        "Worth a look?",
    ]


_WRITERS = {
    "free_packet": _free_packet,
    "drawings": _drawings,
    "time_back": _time_back,
    "guarantee": _guarantee,
}


def _facts(context: dict[str, Any]) -> dict[str, Any]:
    city = context.get("city")
    signals = context.get("site_signals") or {}
    name = clean_business_name(context.get("name"))
    rules = permit_city(city, context.get("state"))
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    named_city = bool(rules and rules.get("asks_for"))
    return {
        "place_id": context["place_id"],
        "name": name,
        "short": short_name(name),
        "city": city,
        "first_name": first_name,
        "greeting": team_greeting(first_name, name),
        "proof": _proof_line(short_name(name), signals, None if named_city else city),
        "paperwork": _paperwork_line(rules, city),
        "rules": rules,
    }


def write_email(context: dict[str, Any], angle: str) -> dict[str, str]:
    facts = _facts(context)
    subject, paragraphs = _WRITERS[angle](facts)
    rules = facts["rules"]
    note = (f"City line from {context.get('city')}'s published checklist: {rules['source']}"
            if rules and rules.get("asks_for") else "No city-specific permit claim was made.")
    if not facts["first_name"]:
        note += " No contact name found."
    return {"subject": subject, "body": "\n\n".join([facts["greeting"], *paragraphs]), "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    facts = _facts(context)
    if step == 2:
        paragraphs = [
            "Easiest way to judge this: I can send a 1-minute demo and a sample packet, so you can see "
            "the actual drawings.",
            "Want me to send them over?",
        ]
    else:
        paragraphs = [
            f"Last note on this from me. If EV permits aren't a time sink at {facts['short']}, no problem "
            "and I'll leave you alone.",
            "If they are, reply with one EV job and I'll build the packet for free.",
        ]
    return "\n\n".join([facts["greeting"], *paragraphs])
