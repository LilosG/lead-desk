"""The Permit Packets emails: three distinct cold email angles (A/B/C test), zero em-dashes."""
from __future__ import annotations

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
    short_name,
)

PROMPT_VERSION = "permit-offer-v8"
_EV_WORDS = re.compile(EV_SERVICE_PATTERN, re.I)
_PERMIT_WORDS = re.compile(PERMIT_JOBS_PATTERN, re.I)

_JOB_PHRASES = {
    "ev_charger": "EV chargers",
    "service_upgrade": "200A panel upgrades",
    "subpanel": "subpanels",
    "appliance_circuit": "240 V circuits",
}


def shown_jobs(context: dict[str, Any]) -> list[str]:
    signals = context.get("site_signals") or {}
    stored = signals.get("permit_jobs")
    if isinstance(stored, list):
        return [slug for slug in PERMIT_JOB_SLUGS if slug in stored]
    return ["ev_charger"] if signals.get("ev_service") else []


def ev_evidence(context: dict[str, Any]) -> str | None:
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


def _joined(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _is_simple_ev_city(ctx: dict[str, Any]) -> bool:
    info = permit_city(ctx.get("city"), ctx.get("state"))
    return bool(info and info.get("fit") == "simple")


def _site_job_focus(ctx: dict[str, Any]) -> str | None:
    simple_ev = _is_simple_ev_city(ctx)
    brands = [] if simple_ev else [b for b in (ctx.get("ev_brands") or []) if b][:2]
    jobs = [j for j in (ctx.get("jobs") or []) if not (simple_ev and j == "ev_charger")]
    parts: list[str] = []
    if brands:
        parts.append(f"{'/'.join(brands)} chargers")
    elif "ev_charger" in jobs:
        parts.append("EV chargers")
    for slug in jobs:
        if slug == "ev_charger":
            continue
        parts.append(_JOB_PHRASES[slug])
    return _joined(parts[:2]) if parts else None


def _sample(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle A: Observation opener + light commercial + sign-off ready + AutoCAD DXF."""
    city, short = ctx["city"], ctx["short"]
    focus = _site_job_focus(ctx)
    where = f" in {city}" if city else ""
    subject = f"{city} permit packets" if city else "electrical permit packets"

    if focus:
        opener = f"Saw {short} handles {focus}{where}."
    else:
        opener = f"Saw {short} runs residential and commercial electrical work{where}."

    checklist_ref = f"{city}'s checklist" if city else "your city's checklist"
    sample_ref = f"sample {city} packet" if city else "sample packet"

    return subject.lower(), [
        opener,
        f"We built a simple tool set up around {checklist_ref} for residential and light commercial jobs. "
        "Enter basic field specs and get a complete packet ready for your sign-off and city submission, "
        "with editable AutoCAD DXF files included, in minutes instead of hours.",
        f"Put together a {sample_ref} so you can verify the drawings. Want me to send it over?",
    ]


def _project(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle B: Workflow/AutoCAD routing question + outside-drafter vs in-house contrast."""
    city, short = ctx["city"], ctx["short"]
    where = f" in {city}" if city else ""
    checklist_ref = f"{city}'s checklist" if city else "local city checklists"

    return f"permits at {short}".lower(), [
        f"Quick question: who handles the site plans, load calcs, and AutoCAD drawings when {short} "
        f"pulls residential or light commercial permits{where}?",
        "Most shops we talk to either wait days on outside drafters or burn nights doing them in-house. "
        f"We built a simple tool configured for {checklist_ref} that generates a packet ready for your "
        "sign-off, with editable AutoCAD DXF files included, in a few minutes.",
        "Happy to send over a sample packet so you can check the quality. Want me to shoot it over?",
    ]


def _origin(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle C: Contractor origin story (stopped passing on jobs due to drawing time)."""
    city, short = ctx["city"], ctx["short"]
    checklist_ref = f"{city}'s checklist" if city else "your city's checklist"
    sample_ref = f"sample {city} packet" if city else "sample packet"
    passed_jobs = (
        "panel upgrades and light commercial jobs"
        if _is_simple_ev_city(ctx)
        else "EV charger and upgrade jobs"
    )

    return f"permit drawings at {short}".lower(), [
        f"One of the electrical contractors we work with told us he was passing on {passed_jobs} "
        "just because the permit drawings took too long.",
        f"We built a simple tool around {checklist_ref} that turns basic job details into a packet "
        "ready for your sign-off and submission, with editable AutoCAD DXF files included, in minutes "
        "instead of hours.",
        f"Put together a {sample_ref} so you can verify the drawings. Want me to send it over?",
    ]


_WRITERS = {
    "sample": _sample,
    "project": _project,
    "origin": _origin,
}


def _facts(context: dict[str, Any]) -> dict[str, Any]:
    signals = context.get("site_signals") or {}
    name = clean_business_name(context.get("name"))
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    city = (context.get("city") or "").strip() or None
    state = (context.get("state") or "").strip().upper() or None
    return {
        "name": name,
        "short": short_name(name),
        "city": city,
        "state": state,
        "first_name": first_name,
        "jobs": shown_jobs(context),
        "ev_brands": signals.get("ev_brands") or [],
    }


def _with_greeting(facts: dict[str, Any], paragraphs: list[str]) -> str:
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
    facts = _facts(context)
    short, city = facts["short"], facts["city"]
    job_choices = (
        "panel upgrades or subpanels"
        if _is_simple_ev_city(facts)
        else "panel upgrades, subpanels, or EV chargers"
    )
    if facts["first_name"]:
        matching = f"a matching {city} sample packet" if city else "a matching sample packet"
        paragraph = (f"Quick bump on this. Which do you pull more permits for at {short} right now, "
                     f"{job_choices}? Happy to send over {matching} (PDF + AutoCAD DXF).")
    else:
        packet = f"a sample {city} packet" if city else "a sample packet"
        paragraph = (f"Quick bump on this. Who handles pulling electrical permits at {short}? "
                     f"Happy to send {packet} (PDF + AutoCAD DXF) their way.")
    return _with_greeting(facts, [paragraph])
