"""The email angles each campaign can send, and how a lead gets one."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from app.campaigns import EV_PERMITS, SEO_WEBSITES

ROTATE = "rotate"


@dataclass(frozen=True)
class Angle:
    key: str
    label: str
    summary: str


ANGLES: dict[str, tuple[Angle, ...]] = {
    EV_PERMITS: (
        Angle("free_packet", "Free packet", "Offers to build their next EV packet for free."),
        Angle("drawings", "Who draws your plans", "Leads with the site plan and one-line."),
        Angle("time_back", "Hours back", "Asks how long a packet takes, then the 90% number."),
        Angle("guarantee", "30-day guarantee", "Money back if the packets aren't good enough to submit."),
    ),
    SEO_WEBSITES: (
        Angle("local_gap", "Local comparison", "Their biggest gap against local peers. No attachment."),
        Angle("competitor", "Named competitor", "Names the local leader's numbers next to theirs."),
        Angle("free_homepage", "Free homepage", "Links the mockup. Needs a published demo site."),
        Angle("audit_attached", "Audit attached", "The comparison with the audit PDF attached."),
    ),
}
# What Rotate splits between. Two arms reach a readable result fastest.
ROTATION = {
    EV_PERMITS: ("free_packet", "drawings"),
    SEO_WEBSITES: ("local_gap", "competitor"),
}


def angle_options(campaign: str) -> list[dict[str, Any]]:
    return [asdict(angle) for angle in ANGLES[campaign]]


def angle_label(campaign: str, key: str | None) -> str:
    for angle in ANGLES[campaign]:
        if angle.key == key:
            return angle.label
    return "Original email"


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
