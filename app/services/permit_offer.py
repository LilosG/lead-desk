"""The Permit Packets emails: short, link-free offers for the electrical permit packet system."""
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

PROMPT_VERSION = "permit-offer-v4"
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


def _default_job_list(ctx: dict[str, Any]) -> str:
    if _is_simple_ev_city(ctx):
        return "panel upgrades, subpanels and 240 V circuits"
    return "panel upgrades, subpanels, EV chargers and 240 V circuits"


def _sample(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    city, short = ctx["city"], ctx["short"]
    focus = _site_job_focus(ctx)
    simple_ev = _is_simple_ev_city(ctx)
    city_info = permit_city(city, ctx["state"])
    where = f" in {city}" if city else ""
    opener = f"Saw {short} handles {focus}{where}. " if focus else ""
    sample = f"Put together a sample {city} packet" if city else "Put together a sample packet"
    subject = f"{city} permit packets" if city else "electrical permit packets"

    if city and not simple_ev and city_info and city_info.get("fit") == "full" and city_info.get("asks_for"):
        body_1 = (
            f"{opener}We built a permit packet system set up around {city}'s checklist ({city_info['asks_for']}, "
            "plus AutoCAD DXF drawings) for residential and commercial panel upgrades, subpanels, EV chargers "
            "and 240 V circuits."
        )
    else:
        area = f"{city} and surrounding service areas" if city else "your service cities"
        body_1 = (
            f"{opener}We built an electrical permit system configured around {area} that turns job specs into "
            f"submittable packets (scaled parcel site plan, one-line/riser diagrams, NEC 220.82 load calc, "
            f"and AutoCAD DXF export) for {_default_job_list(ctx)}."
        )
    return subject.lower(), [
        body_1,
        f"{sample} so you can see the PDF and CAD sheets—want me to send it over?",
    ]


def _project(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    city, short = ctx["city"], ctx["short"]
    where = f" in {city}" if city else ""
    area = f"{city} checklists" if city else "local city checklists"
    job_ask = _site_job_focus(ctx) or _default_job_list(ctx)
    return f"permits at {short}".lower(), [
        f"Pulling many permits for {job_ask}{where} at {short}?",
        f"We built an electrical permit platform configured for {area} that generates submittable packets "
        "(NEC 220.82 load calcs, scaled parcel site plans, one-lines, and AutoCAD DXF files) for residential "
        "and commercial jobs without the back-office bottleneck.",
        "Are you the right person to send a sample packet to, or who handles permitting on your end?",
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
        paragraph = (f"Quick bump—which do you pull more permits for at {short} right now, "
                     f"{job_choices}? Happy to send over {matching}.")
    else:
        packet = f"a sample {city} packet" if city else "a sample packet"
        paragraph = (f"Quick bump on this—who handles pulling electrical permits at {short}? "
                     f"Happy to send {packet} their way.")
    return _with_greeting(facts, [paragraph])
