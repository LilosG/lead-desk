"""The SEO + Websites emails, written from the lead's audit report.

Every number about the lead comes from the audit snapshot, the same way the
PDF's do. The proof is Wheyland Electric, Mike's own results: about 60 calls and
quote requests a month from the first month after the March relaunch, and 20
Google AI Overview spots by summer. The ask is calls, not a fix list.

Only the Audit attached angle carries a file, because a first email with a PDF
is more likely to land in spam.
"""
from __future__ import annotations

from typing import Any

from app.services.outreach_audit_copy import (
    LEAD_PRIORITY,
    _email_phrase,
    _plural_niche,
    audit_email_paragraph,
    clean_business_name,
    contact_first_name,
    possessive,
    short_name,
    team_greeting,
)

PROMPT_VERSION = "seo-offer-v2"
AUDIT_ATTACHED = "audit_attached"

# Wheyland's own neighbors get the case study without the name.
_WHEYLAND_NEIGHBORS = {"carlsbad", "vista", "oceanside", "encinitas", "san marcos"}


def _proof_subject(context: dict[str, Any]) -> str:
    """Who the Wheyland results are credited to for this lead."""
    if context.get("vertical") != "electrician":
        return "a local electrical contractor"
    city = (context.get("city") or "").strip().lower()
    state = (context.get("state") or "").strip().upper()
    if state == "CA" and city in _WHEYLAND_NEIGHBORS:
        return "a North County electrical shop"
    return "Wheyland Electric"


def proof_paragraph(context: dict[str, Any]) -> str:
    who = _proof_subject(context)
    return (f"We rebuilt {possessive(who)} site and local search setup in March. From the first month "
            "they got about 60 calls and quote requests a month from Google. By summer they were "
            "showing up in Google's AI answers for 20 searches. It's all month-to-month, so if the "
            "phone doesn't ring, you walk.")


def _ask(short: str, city: str | None) -> str:
    where = f" in {city}" if city else ""
    return f"Want me to send the plan for how I'd get {short} those calls{where}?"


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


def _niche(snapshot: dict[str, Any]) -> str:
    return _plural_niche((snapshot.get("market_comparison") or {}).get("niche"))


def _top_gap(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    gaps = (snapshot.get("page_gaps") or {}).get("gaps") or []
    top = gaps[0] if gaps else None
    return top if top and top.get("count") and top.get("label") else None


def _competitor_line(snapshot: dict[str, Any], name: str) -> tuple[str, str] | None:
    """The leader's reviews next to theirs. The page gap counts city peers, not the leader."""
    leader = _leader(snapshot, name)
    city = _city(snapshot)
    if not (leader and city):
        return None
    niche = _niche(snapshot)
    short = short_name(name)
    yours = (f"to your {leader['mine']:,}" if leader["mine"] else
             f"while {short} doesn't have any yet")
    line = (f"Checked {niche} in {city}. {leader['name']} is out front on Google Maps with "
            f"{leader['reviews']:,} reviews {yours}")
    gap = _top_gap(snapshot)
    if gap:
        line += (f", and {gap['count']} other {niche} there have a dedicated {gap['label']} page "
                 f"that {possessive(short)} site is missing.")
    else:
        line += "."
    return line, f"Calls going to {short_name(leader['name'])}"


# Findings that beat a missing service page as the opener: the lead is losing calls today.
_HARD_GAPS = {"noindex_homepage", "website_not_on_gbp", "broken_profile_link", "no_website", "no_ssl",
              "no_reviews", "reviews_bottom_quartile"}


def _local_gap_line(snapshot: dict[str, Any], short: str, city: str | None) -> str | None:
    """The missing service page, unless the audit found something that costs calls sooner."""
    gap = _top_gap(snapshot)
    found = {f.get("signal") for f in snapshot.get("findings") or [] if isinstance(f, dict)}
    if not (gap and city) or found & _HARD_GAPS:
        return None
    niche = _niche(snapshot)
    return (f"Checked {niche} in {city}. {gap['count']} other {niche} there have a dedicated "
            f"{gap['label']} page that {possessive(short)} site is missing, and that page is how they "
            "show up when someone searches for that service.")


def write_email(context: dict[str, Any], angle: str) -> dict[str, str] | None:
    """(subject, body, angle) for this lead, or None if the audit has nothing to say."""
    snapshot = context.get("audit_snapshot")
    if not isinstance(snapshot, dict):
        return None
    name = clean_business_name(context.get("name"))
    short = short_name(name)
    rendered = audit_email_paragraph(snapshot, name, with_demo=False)
    if rendered is None:
        return None
    finding, subject = rendered
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    greeting = team_greeting(first_name, name)
    city = _city(snapshot) or context.get("city")
    subject = subject.replace(name, short)
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
    elif angle == "competitor":
        paragraphs = [finding, proof_paragraph(context), _ask(short, city)]
    else:
        subject = f"{short} on Google Maps in {city}" if city else f"{short} on Google Maps"
        paragraphs = [_local_gap_line(snapshot, short, city) or finding, proof_paragraph(context),
                      _ask(short, city)]
    return {
        "subject": subject[:70],
        "body": "\n\n".join([greeting, *paragraphs]),
        "angle": angle,
        "note": "No contact name found." if not first_name else "",
    }


# Touch 2 gives the fastest fix away. Each line is true whenever its finding is.
_FIX_LINES = {
    "website_not_on_gbp": ("your Google Maps listing doesn't link to your website, so anyone who taps "
                           "it hits a dead end. Add it under Edit profile → Contact → Website. It takes "
                           "a minute."),
    "broken_profile_link": ("the website link on your Google Maps listing opens an error page, so anyone "
                            "who taps it hits a dead end. Fix it under Edit profile → Contact → Website. "
                            "It takes a minute."),
    "noindex_homepage": ("your homepage has a setting that tells Google not to show it in search. "
                         "Removing that one tag is the fastest win you have."),
    "no_ssl": ("your site shows a \"Not secure\" warning before it loads, and a lot of people back out "
               "right there. A free SSL certificate fixes it."),
    "no_click_to_call": ("your phone number isn't tappable on mobile, so people on their phones have to "
                         "copy it to call you. Making it a tap-to-call link takes five minutes."),
    "no_hours": ("your Google listing has no business hours, so Google is less likely to show you to "
                 "people searching right now. Add them under Edit profile → Hours."),
    "ai_crawlers_blocked": ("your site is blocking AI search tools like ChatGPT from reading it, so they "
                            "can't recommend you. It's one line in your robots.txt file."),
    "title_missing_location": ("your homepage title doesn't mention your town, and it's one of the first "
                               "things Google reads to decide where to show you."),
    "no_review_replies": ("none of your Google reviews have a reply. Replying, even briefly, is one of "
                          "the easier ways to move up on Maps."),
}
_FIX_ORDER = ("website_not_on_gbp", "broken_profile_link", "noindex_homepage", "no_ssl", "page_gap",
              "no_click_to_call", "no_hours", "ai_crawlers_blocked", "title_missing_location",
              "no_review_replies")


def fix_one(snapshot: dict[str, Any] | None, short: str, *, gap_already_named: bool = False) -> str | None:
    """The single fastest fix for this lead, from its own audit.

    When Touch 1 already named the missing page, Touch 2 gives something new first.
    """
    if not isinstance(snapshot, dict):
        return None
    findings = [f for f in snapshot.get("findings") or [] if isinstance(f, dict) and f.get("signal")]
    found = {f["signal"] for f in findings}
    gap = _top_gap(snapshot)
    city = _city(snapshot)
    where = f" in {city}" if city else ""
    gap_line = (f"{gap['count']} other {_niche(snapshot)}{where} have a dedicated {gap['label']} page "
                f"and {possessive(short)} site doesn't. That page is how you show up when someone "
                "searches for that exact service.") if gap else None
    for key in _FIX_ORDER:
        if key == "page_gap":
            if gap_line and not gap_already_named:
                return gap_line
            continue
        if key in found:
            return _FIX_LINES[key]
    ordered = sorted(findings, key=lambda f: LEAD_PRIORITY.index(f["signal"])
                     if f["signal"] in LEAD_PRIORITY else 99)
    for item in ordered:
        if gap_already_named and item["signal"] in {"no_service_pages", "no_service_city_pages"}:
            continue
        phrase = _email_phrase(item)
        if phrase:
            return f"I'd start with {phrase}. It's a quick fix and it's costing you calls right now."
    return gap_line


def write_follow_up(context: dict[str, Any], step: int) -> str:
    name = clean_business_name(context.get("name"))
    short = short_name(name)
    signals = context.get("site_signals") or {}
    first_name = contact_first_name(context.get("to_address"), context.get("name"),
                                    signals.get("owner_name"))
    greeting = team_greeting(first_name, name)
    snapshot = context.get("audit_snapshot")
    city = (_city(snapshot) if isinstance(snapshot, dict) else None) or context.get("city")
    plan = f"the rest of the {city} plan" if city else "the rest of the plan"
    if step == 2:
        fix = fix_one(snapshot, short, gap_already_named=context.get("angle") in {"competitor", "local_gap"})
        if fix:
            paragraphs = [
                f"Quick one regardless: {fix}",
                f"That's the fastest leak. If filling the schedule without Google Ads is on your radar "
                f"this month, I'll send {plan}.",
            ]
        else:
            paragraphs = [
                f"Quick follow-up. If filling the schedule without Google Ads is on your radar this "
                f"month, I'll send the plan I mapped out for {short}.",
            ]
    else:
        paragraphs = [
            "Last note from me. If more local calls without paying for Google Ads isn't on the radar "
            f"right now, I'll get out of your hair. If it is, reply \"plan\" and I'll send what I "
            f"mapped out for {short}.",
        ]
    return "\n\n".join([greeting, *paragraphs])
