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
        Angle("sample", "Sample packet", "What the packets include for their city, then offers the sample. No link."),
        Angle("project", "Project + routing", "Asks about upcoming jobs and who handles permitting. No link."),
    ),
    SEO_WEBSITES: (
        Angle("website_draft", "Website draft", "A real detail from their site, 1-2 phone-checkable problems, offers a free draft. No link."),
        Angle("free_homepage", "Website mockup", "Offers the published mockup. Needs a published demo site."),
        Angle("chatgpt_pick", "ChatGPT pick", "Names the competitors ChatGPT recommends in their city and notes they didn't come up. Offers a breakdown."),
        Angle("chatgpt_profile", "ChatGPT profile", "Offers to walk them through claiming a ChatGPT business profile. Off until ENABLE_CHATGPT_PROFILE_OFFER is set."),
    ),
}
# Angles that were retired from the menu. Old sends still report under their real name.
RETIRED_LABELS: dict[str, dict[str, str]] = {
    EV_PERMITS: {"free_packet": "Free packet", "time_back": "Hours back", "guarantee": "30-day guarantee",
                 "who_pulls": "Submittal checklist", "drawings": "EV & panel permits", "desk_work": "Permit desk work"},
    SEO_WEBSITES: {"audit_attached": "Audit attached", "leader_vs_you": "Leader vs you",
                   "ai_search": "AI / ChatGPT search", "competitor": "Competitor gap", "local_gap": "Local gap"},
}
# What Rotate splits between.
ROTATION = {
    EV_PERMITS: ("sample", "project"),
    SEO_WEBSITES: ("website_draft", "chatgpt_pick"),
}
# Angles that stay out of the menu and the automatic routing until switched on.
PROFILE_ANGLE = "chatgpt_profile"


def profile_offer_enabled() -> bool:
    try:
        from app.core.config import get_settings
        return bool(get_settings().enable_chatgpt_profile_offer)
    except Exception:  # settings unavailable (e.g. a bare unit test): the offer stays off
        return False


def angle_options(campaign: str) -> list[dict[str, Any]]:
    return [asdict(angle) for angle in ANGLES[campaign]
            if angle.key != PROFILE_ANGLE or profile_offer_enabled()]


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
