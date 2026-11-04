"""The three things we'd do first, written as advice at the top of each audit.

Each rule turns one kind of finding into a move and the reason for it, using
the business's own numbers. A rule says what to do and why, never how, and it
never promises a result. Rules run in priority order, one move per rule, so a
group of related findings becomes a single move.
"""
from __future__ import annotations

from typing import Any

MAX_MOVES = 3
STALE_REVIEW_DAYS = 90


def _data(by_signal: dict[str, dict], *signals: str) -> dict[str, Any]:
    for signal in signals:
        if signal in by_signal:
            data = by_signal[signal].get("data")
            return data if isinstance(data, dict) else {}
    return {}


def _page_count_line(counts: dict[str, Any], label: str) -> str:
    """Their service page count against the best nearby, when that gap is real."""
    yours, best = counts.get("yours"), counts.get("best")
    if yours is None or not best or best <= yours:
        return ""
    noun = label[:-1] if yours == 1 else label
    return f"You have {yours} {noun}, and the best competitor nearby has {best}. "


def _service_pages(
    found: dict, gaps: dict | None, city: str, counts: dict[str, Any], label: str,
) -> tuple[str, str] | None:
    top = (gaps or {}).get("gaps") or []
    if top:
        where = f" in {city}" if city else ""
        return (
            f"Build a dedicated page for {top[0]['label']}, then for your other main services.",
            f"{top[0]['count']} of the {gaps['sample_size']} nearby competitors with websites have "
            f"a page for this. Someone searching for that job{where} needs a page about that job, "
            "and right now that search goes to them.",
        )
    numbers = _page_count_line(counts, label)
    if "no_service_pages" in found or (
        {"thin_service_pages", "service_pages_missing_location"} & set(found)
        and (counts.get("yours") or 0) <= 1
    ):
        return (
            "Give each of your main services its own page.",
            numbers + "A search for one specific job needs a page about that job to land on, or "
            "Google has little reason to show you for it.",
        )
    if {"thin_service_pages", "service_pages_missing_location"} & set(found):
        return (
            f"Build out your {label} so each one can win its search.",
            numbers + "They're too light to answer what someone wants to know before they call, "
            "and they give Google little to work with for searches in your area.",
        )
    return None


def _town_pages(found: dict, town_pages: dict[str, Any]) -> tuple[str, str] | None:
    if "no_city_pages" not in found:
        return None
    having, total = town_pages.get("having"), town_pages.get("total")
    opening = f"{having} of the {total} nearby competitors we checked have them. " if having else ""
    return (
        "Add pages for the towns you serve.",
        opening + "Searches that name a nearby town need a page written for that town, and you "
        "don't have one yet.",
    )


def _homepage(found: dict, city: str) -> tuple[str, str] | None:
    if "homepage_unclear" in found:
        return (
            "Say what you do and where at the top of your homepage.",
            "The opening of your homepage doesn't plainly say it. Visitors decide in seconds, and "
            "Google looks for the same clear signal.",
        )
    if "title_missing_location" in found and city:
        return (
            f"Name {city} in your homepage title.",
            "It's one of the clearest signals of where you work, and it matches what people type "
            "when they search.",
        )
    return None


def _reviews(found: dict, last_review_days: int | None) -> tuple[str, str] | None:
    if "no_reviews" in found:
        return (
            "Get your first Google reviews.",
            "With none showing, you're easy to skip next to competitors who have them. It's one "
            "of the first things people look at on Google.",
        )
    if not {"reviews_bottom_quartile", "reviews_below_median"} & set(found):
        return None
    data = _data(found, "reviews_bottom_quartile", "reviews_below_median")
    opening = (
        f"You have {int(data['reviews']):,} reviews and the typical local competitor has "
        f"{int(data['median']):,}. " if data.get("reviews") and data.get("median") else ""
    )
    closing = (
        f"Your newest is {last_review_days:,} days old, so the first goal is getting them coming in again."
        if last_review_days is not None and last_review_days > STALE_REVIEW_DAYS
        else "It's one of the first things people compare, and one of the signals Google uses for map results."
    )
    return "Start asking every happy customer for a Google review.", opening + closing


def _speed(found: dict) -> tuple[str, str] | None:
    if not {"psi_mobile_critical", "psi_mobile_poor"} & set(found):
        return None
    score = _data(found, "psi_mobile_critical", "psi_mobile_poor").get("psi_performance")
    opening = f"Your site scored {int(score)} out of 100 on Google's phone speed test. " if score else ""
    return (
        "Make your site faster on phones.",
        opening + "Most local searches happen on a phone, and people leave slow pages before they "
        "see what you offer.",
    )


# (signal that triggers it, the move, why it matters)
_SIMPLE_BEFORE_PAGES = [
    ("no_website", "Get a real website connected to your Google profile.",
     "People who find you on Google Maps have nowhere to go to see your work or what you offer. "
     "I'd fix this before anything else."),
    ("site_down", "Get your website loading again.",
     "It didn't load when we checked, so anyone trying to reach you from Google hit a dead end."),
    ("broken_profile_link", "Fix the website link on your Google profile.",
     "It leads to an error page, so people tapping it from Google hit a dead end even though "
     "your site works."),
    ("noindex_homepage", "Let search engines see your homepage.",
     "It's marked to stay out of search results, and that holds back everything else on this list."),
    ("website_not_on_gbp", "Add your website to your Google profile.",
     "You have a site, but people on Google Maps can't get to it. It's a small change that "
     "connects the two things customers use to check you out."),
]
_SIMPLE_AFTER_REVIEWS = [
    ("no_ssl", "Fix the \"Not secure\" warning on your site.",
     "Browsers show it before people see anything about your business. It's usually a small "
     "fix, and it removes an easy reason to leave."),
]
_SIMPLE_AFTER_HOMEPAGE = [
    ("no_service_city_pages", "Add pages for your main services in your main towns.",
     "Many local searches name a service and a town together, and you have no page that "
     "answers both."),
    ("no_contact_form", "Give people a way to reach you without calling.",
     "Many people won't call, especially after hours. Without a form or booking option, they "
     "move on to someone who has one."),
    ("no_click_to_call", "Make your phone number tappable.",
     "Most local searches happen on a phone. If people have to copy your number, some of them "
     "won't call."),
    ("no_review_replies", "Start replying to your Google reviews.",
     "People reading your reviews notice when no one answers, and a reply shows them someone is "
     "paying attention."),
    ("few_review_replies", "Reply to more of your Google reviews.",
     "People reading your reviews notice when no one answers, and a reply shows them someone is "
     "paying attention."),
    ("nap_mismatch", "Use one phone number everywhere.",
     "Your website and Google profile show different numbers, which can send calls to the wrong "
     "place and makes your details harder for Google to trust."),
    ("no_photos", "Add recent photos to your Google profile.",
     "Photos are one of the first things people look at on a listing, and they show you're "
     "active and real."),
    ("few_photos", "Add recent photos to your Google profile.",
     "Photos are one of the first things people look at on a listing, and they show you're "
     "active and real."),
    ("no_hours", "Add your hours to your Google profile.",
     "People want to know you're open before they call, and a listing without hours gives them "
     "a reason to try the next one."),
    ("no_services_listed", "List your services on your Google profile.",
     "It tells Google and customers what you do, and it's a quick way to show up for more of "
     "the work you want."),
    ("no_business_description", "Add a business description to your Google profile.",
     "It's your chance to say what you do and where, in your own words, right on the listing."),
]


def already_competitive(findings: list[dict[str, Any]], benchmarks: dict[str, Any] | None) -> bool:
    """On par or ahead of every local measure, with nothing seriously wrong."""
    if not benchmarks or benchmarks.get("behind"):
        return False
    return not any(f.get("impact") == "high" for f in findings)


def top_moves(
    findings: list[dict[str, Any]],
    *,
    gaps: dict[str, Any] | None,
    city: str | None,
    last_review_days: int | None,
    page_counts: dict[str, Any] | None = None,
    town_pages: dict[str, Any] | None = None,
    offering_label: str = "service pages",
) -> list[dict[str, str]]:
    found = {f["signal"]: f for f in findings if f.get("signal")}

    def simple(rules: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
        return [(move, why) for signal, move, why in rules if signal in found]

    candidates = [
        *simple(_SIMPLE_BEFORE_PAGES),
        _service_pages(found, gaps, city or "", page_counts or {}, offering_label),
        _reviews(found, last_review_days),
        *simple(_SIMPLE_AFTER_REVIEWS),
        _speed(found),
        _town_pages(found, town_pages or {}),
        _homepage(found, city or ""),
        *simple(_SIMPLE_AFTER_HOMEPAGE),
    ]
    moves: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate is None or any(m["move"] == candidate[0] for m in moves):
            continue
        moves.append({"move": candidate[0], "why": candidate[1]})
        if len(moves) == MAX_MOVES:
            break
    return moves
