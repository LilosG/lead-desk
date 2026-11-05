"""The SEO + Websites emails, written from the lead's audit report.

Every number comes from the audit snapshot, the same way the PDF's do. The offer
is real work already done: the fixes in the audit, or a homepage mockup. Only the
Audit attached angle carries a file, because a first email with a PDF is more
likely to land in spam.
"""
from __future__ import annotations

from typing import Any

from app.services.email_angles import stable_pick
from app.services.outreach_audit_copy import (
    _plural_niche,
    audit_email_paragraph,
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
    team_greeting,
)

PROMPT_VERSION = "seo-offer-v1"
AUDIT_ATTACHED = "audit_attached"
_OUTCOME = "Gaps like these decide who gets the call when someone nearby searches."
_FIXES_ASKS = (
    "I wrote up what I'd fix first, in order. Should I send it over?",
    "I put together what I'd fix first, in order. Want a copy?",
    "I wrote out the fixes I'd start with, in order. Want me to send them?",
)


def _leader(snapshot: dict[str, Any], name: str) -> dict[str, Any] | None:
    """The most-reviewed local peer, when it's a real gap and not this business."""
    comparison = snapshot.get("market_comparison") or {}
    mine = int((comparison.get("business") or {}).get("review_count") or 0)
    own = clean_business_name((comparison.get("business") or {}).get("name") or name).lower()
    for row in comparison.get("leaders") or []:
        rival = clean_business_name(row.get("name"))
        if rival.lower() != own and int(row.get("review_count") or 0) >= max(mine * 2, 20):
            return {"name": rival, "reviews": int(row["review_count"]), "mine": mine}
    return None


def _city(snapshot: dict[str, Any]) -> str | None:
    market = (snapshot.get("market_comparison") or {}).get("market")
    place = (market or "").split(",")[0].strip()
    return None if not place or place == "the area" else place


def _competitor_line(snapshot: dict[str, Any], name: str) -> tuple[str, str] | None:
    leader = _leader(snapshot, name)
    city = _city(snapshot)
    if not (leader and city):
        return None
    line = (f"On Google Maps in {city}, {leader['name']} shows {leader['reviews']:,} reviews next to "
            f"your {leader['mine']:,}. That's often the first thing people compare before they call.")
    gaps = (snapshot.get("page_gaps") or {}).get("gaps") or []
    if gaps:
        niche = _plural_niche((snapshot.get("market_comparison") or {}).get("niche"))
        line += (f"\n\n{gaps[0]['count']} other {niche} there also have their own {gaps[0]['label']} "
                 "page; your site doesn't.")
    return line, f"{short_name(leader['name'])} vs {short_name(name)}"


def write_email(context: dict[str, Any], angle: str) -> dict[str, str] | None:
    """(subject, body, angle) for this lead, or None if the audit has nothing to say."""
    snapshot = context.get("audit_snapshot")
    if not isinstance(snapshot, dict):
        return None
    name = clean_business_name(context.get("name"))
    rendered = audit_email_paragraph(snapshot, name, with_demo=False)
    if rendered is None:
        return None
    finding, subject = rendered
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    greeting = team_greeting(first_name, name)
    ask = stable_pick(context["place_id"], _FIXES_ASKS)
    subject = subject.replace(name, short_name(name))
    demo_url = (snapshot.get("next_step") or {}).get("demo_url")

    if angle == "competitor":
        rival = _competitor_line(snapshot, name)
        if rival is None:
            angle = "local_gap"
        else:
            finding, subject = rival
    elif angle == "free_homepage" and not demo_url:
        angle = "local_gap"

    if angle == "free_homepage":
        subject = f"New homepage for {name}"
        paragraphs = [
            f"I built a new homepage for {name}. It's yours to look at, no strings: {demo_url}",
            finding,
            "If you like it, tell me what you'd change. If not, no harm done.",
        ]
    elif angle == AUDIT_ATTACHED:
        paragraphs = [finding, "The attached PDF has the full comparison and what I'd fix first, in order."]
    else:
        paragraphs = [finding, _OUTCOME, ask]
    return {
        "subject": subject[:70],
        "body": "\n\n".join([greeting, *paragraphs]),
        "angle": angle,
        "note": "No contact name found." if not first_name else "",
    }


def write_follow_up(context: dict[str, Any], step: int) -> str:
    name = clean_business_name(context.get("name"))
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    greeting = team_greeting(first_name, name)
    attached = context.get("angle") in {AUDIT_ATTACHED, None}
    if step == 2:
        paragraphs = [
            ("One thing on the audit I sent: " if attached else "One thing on those fixes: ")
            + f"you don't need me to use them. Anyone working on {possessive(name)} site can follow them.",
            ("Want me to walk you through the first one?" if attached else "Want the list?")
            + " A one-word reply works.",
        ]
    else:
        paragraphs = [
            f"Last note on this from me. If getting {name} found on Google isn't a priority right now, "
            "no problem and I'll leave you alone.",
            "If it becomes one, reply here and I'll pick it up from what I found.",
        ]
    return "\n\n".join([greeting, *paragraphs])
