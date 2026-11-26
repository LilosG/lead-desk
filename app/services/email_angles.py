"""The email angles each campaign can send, and how a lead gets one."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from app.campaigns import EV_PERMITS, SEO_WEBSITES

ROTATE = "rotate"
BEST = "best"


@dataclass(frozen=True)
class Angle:
    key: str
    label: str
    summary: str


ANGLES: dict[str, tuple[Angle, ...]] = {
    EV_PERMITS: (
        Angle("sample", "Sample packet", "City-specific permit checklist + offers a 1-page sample. No link."),
        Angle("project", "Project + routing", "Asks about upcoming jobs and who handles permitting. No link."),
    Angle("origin", "Origin story", "Peer contractor story about passing on permit-heavy jobs until drawing time dropped. No link."),
        Angle("pro_starter", "Pro 1-free + 3-for-1", "Offers 1 free packet credit to test on a live job and mentions the 3-for-1 starter pack. No link."),
    ),
    SEO_WEBSITES: (
        Angle("chatgpt_pick", "ChatGPT pick", "Names competitors ChatGPT recommends in their city and offers the 3-bullet fix. No link."),
        Angle("competitor_gap", "Competitor gap", "Compares their local service pages/reviews to the #1 competitor in town. No link."),
        Angle("website_draft", "Website draft", "Flags one undeniable Maps/SSL/mobile issue and offers a free mockup. No link."),
    ),
}

RETIRED_LABELS: dict[str, dict[str, str]] = {
    EV_PERMITS: {
        "free_packet": "Free packet", "time_back": "Hours back", "guarantee": "30-day guarantee",
        "who_pulls": "Submittal checklist", "drawings": "EV & panel permits", "desk_work": "Permit desk work",
    },
    SEO_WEBSITES: {
        "audit_attached": "Audit attached", "leader_vs_you": "Leader vs you",
        "ai_search": "AI / ChatGPT search", "competitor": "Competitor gap", "local_gap": "Local gap",
        "free_homepage": "Website mockup", "chatgpt_profile": "ChatGPT profile",
    },
}

ROTATION = {
    EV_PERMITS: ("sample", "project"),
    SEO_WEBSITES: ("chatgpt_pick", "competitor_gap", "website_draft"),
}


def profile_offer_enabled() -> bool:
    return False


def angle_options(campaign: str) -> list[dict[str, Any]]:
    return [asdict(angle) for angle in ANGLES[campaign]]


def angle_label(campaign: str, key: str | None) -> str:
    for angle in ANGLES[campaign]:
        if angle.key == key:
            return angle.label
    return RETIRED_LABELS.get(campaign, {}).get(key or "", "Original email")


def stable_pick(place_id: str, options: tuple[str, ...]) -> str:
    """The same lead always lands on the same option."""
    return options[int(hashlib.sha256(place_id.encode()).hexdigest(), 16) % len(options)]


def is_known(campaign: str, key: str) -> bool:
    return any(angle.key == key for angle in ANGLES[campaign])


def resolve_angle(campaign: str, place_id: str, requested: str | None, current: str | None) -> str:
    """A chosen angle wins, then the lead's existing one, then the rotation."""
    if requested and requested != ROTATE:
        return requested
    if current and not requested and is_known(campaign, current):
        return current
    return stable_pick(place_id, ROTATION[campaign])
