"""MyElectricalPermit.com contractor emails: 4 distinct cold-email angles (A/B/C/D test), zero links, zero DXF claims."""
from __future__ import annotations

from typing import Any

from app.campaigns import PERMIT_JOB_LABELS, PERMIT_JOB_SLUGS, permit_city
from app.services.outreach_audit_copy import (
    clean_business_name,
    contact_first_name,
    short_name,
)
from app.services.permit_offer import permit_evidence, shown_jobs

PROMPT_VERSION = "mep-offer-v2"

_MEP_JOB_PHRASES = {
    "ev_charger": "EV chargers",
    "service_upgrade": "200A panel upgrades",
    "subpanel": "subpanels",
    "generator_ess": "backup generators",
    "appliance_circuit": "240V circuits",
}


def _joined(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _is_simple_ev_city(ctx: dict[str, Any]) -> bool:
    info = permit_city(ctx.get("city"), ctx.get("state"))
    return bool(info and info.get("fit") == "simple")


def _mep_job_focus(ctx: dict[str, Any]) -> str | None:
    simple_ev = _is_simple_ev_city(ctx)
    brands = [] if simple_ev else [b for b in (ctx.get("ev_brands") or []) if b][:2]
    jobs = [
        j for j in (ctx.get("jobs") or [])
        if j in _MEP_JOB_PHRASES and not (simple_ev and j == "ev_charger")
    ]
    parts: list[str] = []
    if brands:
        parts.append(f"{'/'.join(brands)} chargers")
    elif "ev_charger" in jobs:
        parts.append("EV chargers")
    for slug in jobs:
        if slug == "ev_charger":
            continue
        parts.append(_MEP_JOB_PHRASES[slug])
    return _joined(parts[:2]) if parts else None


def _safe_subject(candidate: str, fallback: str) -> str:
    low = candidate.lower().strip()
    return low if len(low) <= 40 else fallback.lower()


def _pro_starter(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle 1: 1 free packet credit on a live job + 3-for-1 starter pack."""
    city, short = ctx["city"], ctx["short"]
    focus = _mep_job_focus(ctx) or "EV chargers and 200A panel upgrades"
    where = f" in {city}" if city else ""
    for_city = f" for {city}" if city else ""
    subject = _safe_subject(
        f"free {city} permit packet" if city else "free permit packet",
        "free permit packet",
    )
    return subject, [
        f"Saw {short} handles {focus}{where}.",
        f"I built a pay-per-packet tool that generates residential permit plans{for_city} "
        "(aerial parcel site plan, single-line diagram, NEC 220 load calc, and UL cut sheets) "
        "with your company name and license number in the title block.",
        "Want to test it on a live job? Reply and I'll send 1 free packet credit plus "
        "details on our 3-for-1 contractor starter pack.",
    ]


def _ahj_checklist(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle 2: Hyper-local AHJ submittal + company license title-block sign-off."""
    city, short = ctx["city"], ctx["short"]
    focus = _mep_job_focus(ctx) or "residential service upgrades and EV chargers"
    where = f" in {city}" if city else ""
    dept = f"the {city} building department" if city else "the building department"
    subject = _safe_subject(
        f"{city} permit drawings" if city else f"permits at {short}",
        "electrical permit drawings",
    )
    return subject, [
        f"Saw {short} handles {focus}{where}.",
        f"Quick question: when {dept} asks for a scaled parcel site plan, single-line diagram, "
        "NEC 220 load calc, and UL cut sheets, are you drafting those in-house or outsourcing them?",
        "I built a tool that compiles the full PDF with your company name and license number "
        "in the title block in under 5 minutes. Mind if I send you 1 free packet credit to test?",
    ]


def _panel_closer(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle 3: 100A-to-200A panel upgrade & NEC 220 load calc sales closer."""
    city, short = ctx["city"], ctx["short"]
    where = f" in {city}" if city else ""
    subject = _safe_subject(
        f"{city} panel upgrades" if city else "nec 220 load calcs",
        "nec 220 load calcs",
    )
    return subject, [
        f"When {short} quotes a 100A-to-200A service upgrade or EV charger{where}, "
        "handing the homeowner a clean NEC 220 load calculation and panel schedule "
        "closes the bid fast and covers the city submittal.",
        "We built a zero-subscription tool that turns one address into the full permit PDF "
        "(site plan, single-line, NEC 220 sheet, and cut sheets) with your license in the title block.",
        "Open to 1 free packet credit to try on an upcoming job?",
    ]


def _night_drafting(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Angle 4: Stop burning evenings drafting plans / pay-per-packet vs $300+ drafters."""
    city, short = ctx["city"], ctx["short"]
    where = f" in {city}" if city else ""
    subject = _safe_subject(
        f"permit plans at {short}",
        "residential permit plans",
    )
    return subject, [
        f"Most electrical shops{where} either wait days on outside drafters or burn "
        "evenings drawing residential permit plans themselves.",
        "We built a pay-per-packet generator (no monthly subscription) that drafts the parcel "
        "site plan, single-line diagram, NEC 220 load calc, and UL cut sheets in minutes, "
        "ready for your review and sign-off.",
        "Want me to set aside 1 free packet credit and our 3-for-1 starter offer so you can test a real address?",
    ]


_WRITERS = {
    "pro_starter": _pro_starter,
    "ahj_checklist": _ahj_checklist,
    "panel_closer": _panel_closer,
    "night_drafting": _night_drafting,
}


def _facts(context: dict[str, Any]) -> dict[str, Any]:
    signals = context.get("site_signals") or {}
    name = clean_business_name(context.get("name"))
    first_name = contact_first_name(
        context.get("to_address"), context.get("name"), signals.get("owner_name")
    )
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
    note = "No links or attachments; free credit link and 3-for-1 starter details go out after they reply."
    if not facts["jobs"]:
        note += " Site doesn't show permit work."
    if not facts["first_name"]:
        note += " No contact name found, so there's no greeting."
    return {"subject": subject, "body": _with_greeting(facts, paragraphs), "note": note}


def write_follow_up(context: dict[str, Any], step: int) -> str:
    facts = _facts(context)
    short, city = facts["short"], facts["city"]
    for_city = f" {city}" if city else ""
    if facts["first_name"]:
        paragraph = (
            f"Quick bump in case you're buried in jobs at {short}. Still happy to set aside "
            f"1 free contractor credit (no subscription) so you can test a real{for_city} "
            "EV charger, subpanel, or 200A upgrade address and see the single-line and NEC 220 sheets. "
            "Want me to send the credit over?"
        )
    else:
        paragraph = (
            f"Quick bump on this. Who handles residential permit drawings at {short}? "
            f"Happy to send over 1 free{for_city} packet credit (no subscription) so they can test "
            "the parcel site plan, single-line diagram, and NEC 220 calc on a live job."
        )
    return _with_greeting(facts, [paragraph])
