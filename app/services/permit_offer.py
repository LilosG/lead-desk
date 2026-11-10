"""The Permit Packets emails: short offers written from verified facts.

They're written from fixed copy instead of AI. Every sentence is either true of
the offer as Mike sells it or comes from the lead's own site and, for EV
chargers only, its city's published checklist. No other job type gets a city
claim.

The campaign started as EV Permits and now covers four job types: EV chargers,
panel and service upgrades, subpanels and 240 V circuits. Its key, claim signal
and angle keys keep their old names so existing drafts and history still work.

Touch 1 links the sample packet page unless PERMIT_LINK_IN_FIRST_EMAIL=0, in
which case it only asks whether they want the sample and touch 2 sends it.

Never promise permit approval or a set number of hours. The city decides
approvals, and hours depend on the shop. "Four electrical shops" is Mike's
figure for shops that have used the automation (EV charger version).
"""
from __future__ import annotations

import os
import re
from typing import Any

from app.campaigns import (
    EV_SERVICE_PATTERN,
    PERMIT_JOB_LABELS,
    PERMIT_JOB_SLUGS,
    PERMIT_JOBS_PATTERN,
    permit_city,
)
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
    team_greeting,
)

PROMPT_VERSION = "permit-offer-v1"
DEFAULT_OVERVIEW_URL = "https://ev-permit-packets.vercel.app/"
_EV_WORDS = re.compile(EV_SERVICE_PATTERN, re.I)
_PERMIT_WORDS = re.compile(PERMIT_JOBS_PATTERN, re.I)

# How a job reads in "Saw {short} does ..." and in "On a ..., the install is the easy part".
_PLURAL = {
    "ev_charger": "EV charger installs",
    "service_upgrade": "panel and service upgrades",
    "subpanel": "subpanels",
    "appliance_circuit": "240 V circuits",
}
_SINGULAR = {
    "ev_charger": "EV charger",
    "service_upgrade": "panel upgrade",
    "subpanel": "subpanel",
    "appliance_circuit": "240 V circuit",
}
_ANY_JOB = "panel upgrade, EV charger or subpanel"
_ASK_GENERIC = ("A lot of cities want a site plan, single-line and load calc with the permit on "
                "jobs like these.")
_COVERS = ("It now covers panel and service upgrades, subpanels and 240 V circuits too.")


def overview_url() -> str:
    """The sample packet page. PERMIT_OVERVIEW_URL (or the older EV_OVERVIEW_URL) points it elsewhere."""
    for name in ("PERMIT_OVERVIEW_URL", "EV_OVERVIEW_URL"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return DEFAULT_OVERVIEW_URL


def link_in_first_email() -> bool:
    """PERMIT_LINK_IN_FIRST_EMAIL=0 holds the sample link back until touch 2."""
    return (os.environ.get("PERMIT_LINK_IN_FIRST_EMAIL") or "1").strip() != "0"


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


def _join(names: list[str]) -> str:
    return " and ".join(names[:2])


def _proof_line(ctx: dict[str, Any]) -> str:
    """Proof we looked at their site: the chargers they install, else the work they do."""
    if ctx["brands"]:
        return f"Saw {ctx['short']} installs {_join(ctx['brands'])} chargers. "
    if ctx["jobs"]:
        return f"Saw {ctx['short']} does {_join([_PLURAL[slug] for slug in ctx['jobs']])}. "
    return ""


def _ask_line(ctx: dict[str, Any]) -> str:
    """The city's own checklist is EV-only, so it is only quoted for EV charger work."""
    rules = ctx["rules"]
    if "ev_charger" in ctx["jobs"] and rules and rules.get("asks_for"):
        return f"{ctx['city']} wants {rules['asks_for']} on every residential charger permit."
    return _ASK_GENERIC


def _close(ctx: dict[str, Any], *, with_link: str, without_link: str) -> list[str]:
    if link_in_first_email():
        return [f"Here's what a finished packet looks like: {overview_url()}", with_link]
    return [without_link]


def _drawings(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    return f"Who draws {possessive(ctx['short'])} permit plans?", [
        f"{_proof_line(ctx)}{_ask_line(ctx)} Who's stuck drawing those at {ctx['short']}, you or the office?",
        "Four electrical shops have used the EV charger version. A tech fills out a quick job form "
        "on site, and the site plan on the actual property, the single-line and the load calc come "
        f"back ready to sign and submit. {_COVERS}",
        *_close(ctx, with_link="Want me to run one of your past jobs through it?",
                without_link="Want me to send a sample packet so you can see the drawings?"),
    ]


def _desk_work(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    job = _SINGULAR[ctx["jobs"][0]] if ctx["jobs"] else _ANY_JOB
    job = f"{'an' if job.startswith('EV') else 'a'} {job}"
    return f"Permit desk work at {ctx['short']}", [
        f"{_proof_line(ctx)}On {job}, the install is the easy part. The site plan, single-line "
        "and load calc are the desk work nobody gets paid for.",
        "We built a setup that draws all three from one tech form on site, on the actual property, "
        f"ready for your sign-off. Four electrical shops have used the EV charger version, and it "
        f"now covers panel and service upgrades, subpanels and 240 V circuits too.",
        *_close(ctx, with_link="Want me to run one of your past jobs through it?",
                without_link="Want me to send a sample packet so you can see the drawings?"),
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
        "jobs": shown_jobs(context),
        "brands": [b for b in signals.get("ev_brands") or [] if b],
        "greeting": team_greeting(first_name, name),
        "rules": permit_city(city, context.get("state")),
    }


def write_email(context: dict[str, Any], angle: str) -> dict[str, str]:
    facts = _facts(context)
    subject, paragraphs = _WRITERS[angle](facts)
    rules = facts["rules"]
    if "ev_charger" in facts["jobs"] and rules and rules.get("asks_for"):
        note = f"City line from {context.get('city')}'s published checklist: {rules['source']}"
    else:
        note = "No city-specific permit claim was made."
    if not facts["jobs"]:
        note += " Site doesn't show permit work, so the email asks instead of assuming."
    if not facts["first_name"]:
        note += " No contact name found."
    body = "\n\n".join([facts["greeting"], *paragraphs])
    return {"subject": subject, "body": body, "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    facts = _facts(context)
    if step == 2:
        test = ("To test it against what your office turns in now, reply with the address and panel "
                "size from a past job (an EV charger, a panel upgrade, a subpanel or a hot tub) and "
                "I'll run that packet free.")
        if link_in_first_email():
            intro = ("Following up on the sample packet. In case it got buried, here it is again: "
                     f"{overview_url()}")
        else:
            intro = ("Figured it's easier to just show you. Here's a full sample packet with the site "
                     f"plan, single-line and load calc, all from one tech form: {overview_url()}")
        paragraphs = [intro, test]
    else:
        paragraphs = [
            "Last note from me. If your office still draws permit site plans and load calcs by hand, "
            "reply with a past job and I'll draw it up free. If not, no worries.",
        ]
    return "\n\n".join([facts["greeting"], *paragraphs])
