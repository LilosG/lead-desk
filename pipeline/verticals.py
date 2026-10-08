"""Vertical registry helpers.

Configured verticals are presets, not an allow-list. Lead Desk must be able to
search any operator-supplied local-business vertical without a code change.

Known presets keep their curated query expansion, priority, case studies, and
verified category semantics. Unknown/custom verticals use the normalized label
itself as the discovery query and fall back to generic-safe behavior.
"""
from __future__ import annotations

import re

try:
    from . import config as C
except ImportError:  # pipeline scripts are also executed directly
    import config as C


CUSTOM_VERTICAL_PRIORITY = 100
MAX_VERTICAL_LENGTH = 80


def normalize_vertical_key(value: str) -> str:
    """Return a stable storage key for an operator-entered vertical."""
    value = (value or "").strip().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")

    if not value:
        raise ValueError("vertical cannot be blank")
    if len(value) > MAX_VERTICAL_LENGTH:
        raise ValueError(
            f"vertical must be {MAX_VERTICAL_LENGTH} characters or fewer after normalization"
        )

    return value


def vertical_label(vertical: str) -> str:
    return normalize_vertical_key(vertical).replace("_", " ")


def is_preset(vertical: str) -> bool:
    return normalize_vertical_key(vertical) in C.VERTICALS


def vertical_queries(vertical: str) -> list[str]:
    """Curated preset expansion, or the custom label itself for open verticals."""
    key = normalize_vertical_key(vertical)
    spec = C.VERTICALS.get(key)
    if spec:
        return list(spec["queries"])
    return [key.replace("_", " ")]


def vertical_priority(vertical: str) -> int:
    key = normalize_vertical_key(vertical)
    spec = C.VERTICALS.get(key)
    if spec:
        return int(spec["priority"])
    return CUSTOM_VERTICAL_PRIORITY


GENERIC_PROFILE = "generic_local_business"


def vertical_profile(vertical: str) -> str:
    """Name of the niche profile for a vertical; custom niches are generic-safe."""
    try:
        key = normalize_vertical_key(vertical)
    except ValueError:
        return GENERIC_PROFILE
    spec = C.VERTICALS.get(key)
    if spec:
        profile = str(spec.get("profile") or "home_service")
        return profile if profile in C.NICHE_PROFILES else GENERIC_PROFILE
    return GENERIC_PROFILE


def niche_profile(vertical: str | None) -> dict:
    """Profile dict (offering words, wording labels) for any vertical."""
    return C.NICHE_PROFILES[vertical_profile(vertical or "")]


def is_home_service(vertical: str | None) -> bool:
    return vertical_profile(vertical or "") == "home_service"


def case_study(vertical: str | None) -> str | None:
    """Optional proof line for a niche. None means: say nothing."""
    try:
        key = normalize_vertical_key(vertical or "")
    except ValueError:
        return None
    spec = C.VERTICALS.get(key) or {}
    return spec.get("case_study") or None


def ordered_verticals(verticals: list[str]) -> list[str]:
    normalized = {normalize_vertical_key(value) for value in verticals}
    if not normalized:
        raise ValueError("at least one vertical is required")
    return sorted(
        normalized,
        key=lambda key: (vertical_priority(key), key),
    )
