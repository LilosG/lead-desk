"""The Permit Packets emails: short, link-free offers.

They're written from fixed copy instead of AI. Two first-touch angles run as an
A/B test: "sample" offers a sample packet for the lead's city, and "project"
asks about upcoming jobs and who handles permitting. No first email or
follow-up carries a link or attachment; the sample goes out only after the lead
replies.

There's one follow-up, three days later in the same thread. Leads with a known
first name get asked which job type they permit most; generic inboxes get asked
who handles permits.

The campaign key and claim signal keep their old EV names so existing drafts
and history still work.
"""
from __future__ import annotations

import re
from typing import Any

from app.campaigns import (
    EV_SERVICE_PATTERN,
    PERMIT_JOB_LABELS,
    PERMIT_JOB_SLUGS,
    PERMIT_JOBS_PATTERN,
)
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    short_name,
)

PROMPT_VERSION = "permit-offer-v2"
_EV_WORDS = re.compile(EV_SERVICE_PATTERN, re.I)
_PERMIT_WORDS = re.compile(PERMIT_JOBS_PATTERN, re.I)

def shown_jobs(context: dict[str, Any]) -> list[str]:
    """The job types the lead's site shows, in campaign order.

    Leads read before permit_jobs existed only have the EV signal, so that
    counts as an EV charger job until the backfill has run.
    """
    signals = context.get("site_signals") or {}
    stored = signals.get("permit_jobs")
    if isinstance(stored, list):
        return [slug for slug in PERMIT_JOB_SLUGS if slug in stored]
    return ["ev_charger"] if signals.get("ev_service") else []


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


def permit_evidence(context: dict[str, Any]) -> str | None:
    """Where the lead's site shows permit work of any of the four kinds, or None."""
    jobs = shown_jobs(context)
    if jobs:
        names = ", ".join(PERMIT_JOB_LABELS[slug] for slug in jobs)
        return f"{names} on site"
    sources = [("service link", title) for title in context.get("offering_titles") or []]
    sources += [("page title", context.get("site_title")),
                ("page description", context.get("site_description"))]
    for label, text in sources:
        if text and _PERMIT_WORDS.search(text):
            return label
    return None


def _sample(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    city = ctx["city"]
    subject = f"{city} permit packets" if city else "electrical permit packets"
    packets = f"{city}-specific electrical permit packets" if city else "local electrical permit packets"
    sample = f"Mocked up a sample packet for {city}" if city else "Mocked up a sample packet"
    return subject.lower(), [
        f"We put together {packets} (scaled aerial site plan, one-line diagram, NEC 220.82 load calc, "
        "and local inspector flags) for EV chargers, panel/service upgrades, subpanels and 240 V circuits.",
        f"{sample} so you can see the drawings. Want me to send it over?",
    ]


def _project(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    city, short = ctx["city"], ctx["short"]
    where = f" in {city}" if city else ""
    packets = f"{city} permit packets" if city else "permit packets"
    return f"permits at {short}".lower(), [
        f"Have any panel upgrades, EV chargers or subpanels coming up{where} at {short}?",
        f"We build ready-to-submit {packets} (load calcs, scaled site plans, one-lines and local code "
        "flags) so your electricians stay in the field instead of doing desk work.",
        "Are you the best person to send a sample packet to, or who handles permitting on your end?",
    ]


_WRITERS = {
    "sample": _sample,
    "project": _project,
}


def _facts(context: dict[str, Any]) -> dict[str, Any]:
    signals = context.get("site_signals") or {}
    name = clean_business_name(context.get("name"))
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    city = (context.get("city") or "").strip() or None
    return {
        "name": name,
        "short": short_name(name),
        "city": city,
        "first_name": first_name,
        "jobs": shown_jobs(context),
    }


def _with_greeting(facts: dict[str, Any], paragraphs: list[str]) -> str:
    """"Hi Dave," when there's a name; generic inboxes open straight on the first line."""
    greeting = [f"Hi {facts['first_name']},"] if facts["first_name"] else []
    return "\n\n".join([*greeting, *paragraphs])


def write_email(context: dict[str, Any], angle: str) -> dict[str, str]:
    facts = _facts(context)
    subject, paragraphs = _WRITERS[angle](facts)
    note = "No links or attachments; the sample goes out after they reply."
    if not facts["jobs"]:
        note += " Site doesn't show permit work."
    if not facts["first_name"]:
        note += " No contact name found, so there's no greeting."
    return {"subject": subject, "body": _with_greeting(facts, paragraphs), "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    """The one follow-up. Named contacts get a job-type question, generic inboxes a routing one."""
    facts = _facts(context)
    short, city = facts["short"], facts["city"]
    if facts["first_name"]:
        matching = f"a matching {city} sample packet" if city else "a matching sample packet"
        paragraph = (f"Which do you pull the most permits for at {short}: EV chargers, panel upgrades "
                     f"or subpanels? Happy to send over {matching}.")
    else:
        packet = f"a sample {city} packet" if city else "a sample packet"
        paragraph = (f"Quick bump on this. Who handles pulling electrical permits at {short}? "
                     f"Happy to send {packet} their way.")
    return _with_greeting(facts, [paragraph])
