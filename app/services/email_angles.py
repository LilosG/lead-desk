"""The email angles each campaign can send, and how a lead gets one."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from app.campaigns import EV_PERMITS, SEO_WEBSITES

ROTATE = "rotate"
# Uses what's been built for the lead: the mockup link when one is published,
# and the audit PDF attached. Resolved by the campaign's writer.
BEST = "best"


@dataclass(frozen=True)
class Angle:
    key: str
    label: str
    summary: str


ANGLES: dict[str, tuple[Angle, ...]] = {
    EV_PERMITS: (
        Angle("who_pulls", "Submittal checklist", "Asks whoever pulls permits, then offers a sample built on their city. The ask needs only a yes."),
        Angle("drawings", "EV & panel permits", "Asks who's stuck drawing the site plans, single-lines and load calcs."),
        Angle("desk_work", "Permit desk work", "The install is easy; the permit drawings are unpaid desk work."),
    ),
    SEO_WEBSITES: (
        Angle("local_gap", "Local gap", "Their biggest gap, the Wheyland results and a calls ask. No attachment."),
        Angle("competitor", "Competitor gap", "The local leader's reviews next to theirs, then the Wheyland results."),
        Angle("free_homepage", "Website mockup", "Links the mockup. Needs a published demo site."),
        Angle("ai_search", "AI / ChatGPT search", "Flags their invisibility in ChatGPT & AI search vs local competitors."),
    ),
}
# Angles that were retired from the menu. Old sends still report under their real name.
RETIRED_LABELS: dict[str, dict[str, str]] = {
    EV_PERMITS: {"free_packet": "Free packet", "time_back": "Hours back", "guarantee": "30-day guarantee"},
    SEO_WEBSITES: {"audit_attached": "Audit attached", "leader_vs_you": "Leader vs you"},
}
# What Rotate splits between. Two arms reach a readable result fastest.
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
