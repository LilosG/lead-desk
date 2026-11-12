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
        Angle("who_pulls", "Submittal checklist", "Asks whoever handles submittals, cites local checklist, offers a sample packet."),
        Angle("drawings", "EV & panel permits", "Asks how much time is spent drawing site plans, single-lines and load calcs."),
        Angle("desk_work", "Permit desk work", "The install is easy; the permit drawings are unpaid desk work."),
    ),
    SEO_WEBSITES: (
        Angle("local_gap", "Local gap", "Calls out their top missing service page or site leak and offers a 1-page breakdown."),
        Angle("competitor", "Competitor gap", "Shows the local market leader's review/search edge and offers 3 fixes to capture those calls."),
        Angle("free_homepage", "Website mockup", "Permission-based pitch for the mobile-optimized homepage mockup (zero links in Touch 1)."),
        Angle("ai_search", "AI / ChatGPT search", "Flags their invisibility in ChatGPT & AI search recommendations vs local competitors."),
    ),
}

RETIRED_LABELS: dict[str, dict[str, str]] = {
    EV_PERMITS: {"free_packet": "Free packet", "time_back": "Hours back", "guarantee": "30-day guarantee"},
    SEO_WEBSITES: {
        "audit_attached": "Audit attached (retired)",
        "leader_vs_you": "Leader vs you (retired)",
    },
}

ROTATION = {
    EV_PERMITS: ("who_pulls", "drawings", "desk_work"),
    SEO_WEBSITES: ("ai_search", "competitor", "local_gap"),
}


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
