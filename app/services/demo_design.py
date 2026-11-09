"""Design system for the v4 demo template: styles, fonts, palettes and icons.

Every colour on the page is derived from three inputs (ink, accent, surface),
with contrast checked, so a brand colour pulled from a prospect's site or a
niche palette always produces readable text and buttons.
"""
from __future__ import annotations

import colorsys
import re

HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

# Three looks. Each niche gets one automatically; the builder can override.
STYLES: dict[str, dict[str, str]] = {
    "bold": {
        "label": "Bold",
        "heading_font": "Archivo",
        "body_font": "Inter",
        "font_query": "family=Archivo:wght@600;700;800&family=Inter:wght@400;500;600;700",
        "heading_weight": "800",
        "heading_tracking": "-0.035em",
        "radius": "6px",
        "radius_lg": "10px",
    },
    "clean": {
        "label": "Clean",
        "heading_font": "Plus Jakarta Sans",
        "body_font": "Inter",
        "font_query": "family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600;700",
        "heading_weight": "700",
        "heading_tracking": "-0.03em",
        "radius": "12px",
        "radius_lg": "20px",
    },
    "soft": {
        "label": "Soft premium",
        "heading_font": "Fraunces",
        "body_font": "Inter",
        "font_query": "family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600",
        "heading_weight": "500",
        "heading_tracking": "-0.02em",
        "radius": "16px",
        "radius_lg": "28px",
    },
}
PROFILE_STYLE = {
    "home_service": "bold",
    "auto": "bold",
    "dental": "clean",
    "legal": "clean",
    "generic_local_business": "clean",
    "medical_aesthetic": "soft",
    "wellness_health": "soft",
    "real_estate": "soft",
}


def style_for(profile: str | None, override: str | None = None) -> str:
    if override in STYLES:
        return str(override)
    return PROFILE_STYLE.get(profile or "", "clean")


# --- colour -----------------------------------------------------------------

def normalize_hex(value: str | None) -> str | None:
    if not value:
        return None
    match = HEX.match(value.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return f"#{digits.lower()}"


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = normalize_hex(hex_color) or "#000000"
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, amount: float) -> str:
    """`amount` of b mixed into a."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * amount for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def hls(hex_color: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*_rgb(hex_color))


def _until_contrast(color: str, against: str, target: float, toward: str) -> str:
    current = color
    for step in range(1, 21):
        if contrast(current, against) >= target:
            return current
        current = mix(color, toward, step / 20)
    return current


def is_brand_usable(hex_color: str | None) -> bool:
    """A colour worth building a palette on: not grey, not near white."""
    color = normalize_hex(hex_color)
    if not color:
        return False
    _, lightness, saturation = hls(color)
    return saturation >= 0.28 and 0.12 <= lightness <= 0.82


def palette_with_brand(base: dict[str, str], brand_color: str | None) -> dict[str, str]:
    """Fold a prospect's brand colour into the niche palette.

    A dark brand colour (navy, forest) becomes the ink; anything else becomes
    the accent. The niche palette fills whatever the brand doesn't cover.
    """
    palette = dict(base)
    color = normalize_hex(brand_color)
    if not color or not is_brand_usable(color):
        return palette
    _, lightness, _ = hls(color)
    if lightness < 0.32:
        palette["ink"] = color
    else:
        palette["accent"] = color
    palette["brand"] = color
    return palette


def design_tokens(palette: dict[str, str]) -> dict[str, str]:
    """Every colour the page uses, contrast-checked."""
    ink = normalize_hex(palette.get("ink")) or "#16222b"
    accent = normalize_hex(palette.get("accent")) or "#c9984f"
    surface = normalize_hex(palette.get("surface")) or "#f5f4f1"
    # Body text must be dark: a light "ink" would make the page unreadable.
    if contrast(ink, "#ffffff") < 7:
        ink = _until_contrast(ink, "#ffffff", 7, "#000000")
    dark = mix(ink, "#000000", 0.35)
    on_accent = "#ffffff" if contrast(accent, "#ffffff") >= contrast(accent, "#111111") else "#111111"
    # Accent used as text on white (links, numbers, icons) needs 4.5:1.
    accent_text = _until_contrast(accent, "#ffffff", 4.5, "#000000")
    # Accent used as text on the dark sections needs 4.5:1 the other way.
    accent_on_dark = _until_contrast(accent, dark, 4.5, "#ffffff")
    return {
        "ink": ink,
        "accent": accent,
        "surface": surface,
        "dark": dark,
        "on_accent": on_accent,
        "accent_text": accent_text,
        "accent_on_dark": accent_on_dark,
        "accent_soft": mix(accent, "#ffffff", 0.86),
        "muted": mix(ink, "#ffffff", 0.42),
        "line": mix(ink, "#ffffff", 0.86),
        "muted_on_dark": mix(dark, "#ffffff", 0.72),
        "line_on_dark": mix(dark, "#ffffff", 0.16),
    }


# --- icons ------------------------------------------------------------------
# Simple 24px line icons drawn for these pages, matched to a service by keyword.

_ICON_PATHS: dict[str, str] = {
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "plug": '<path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5"/>',
    "light": '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V16h8v-1.3A7 7 0 0 0 12 2z"/>',
    "car": '<path d="M3 13l2-6h14l2 6v5h-3v-2H6v2H3zM3 13h18"/><circle cx="7.5" cy="13.5" r="1"/><circle cx="16.5" cy="13.5" r="1"/>',
    "drop": '<path d="M12 2.5S5 10 5 14.5a7 7 0 0 0 14 0C19 10 12 2.5 12 2.5z"/>',
    "flame": '<path d="M12 22a7 7 0 0 0 7-7c0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-4-2 2-5 5-5 8a7 7 0 0 0 7 7z"/>',
    "snow": '<path d="M12 2v20M4.9 6l14.2 12M19.1 6 4.9 18M9 3.5 12 6l3-2.5M9 20.5 12 18l3 2.5"/>',
    "fan": '<circle cx="12" cy="12" r="2"/><path d="M12 10c0-4 1-7 4-7 2 0 3 2 2 4l-4 3M14 12c4 0 7 1 7 4 0 2-2 3-4 2l-3-4M12 14c0 4-1 7-4 7-2 0-3-2-2-4l4-3M10 12c-4 0-7-1-7-4 0-2 2-3 4-2l3 4"/>',
    "roof": '<path d="M2 12 12 3l10 9M5 10v11h14V10M10 21v-6h4v6"/>',
    "home": '<path d="M3 11 12 4l9 7v10H3zM9 21v-6h6v6"/>',
    "leaf": '<path d="M5 19C5 9 11 4 20 4c0 9-5 15-15 15zM5 19l8-8"/>',
    "tree": '<path d="M12 22v-6M12 2 5 12h4l-3 4h12l-3-4h4z"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0 5 5L22 14l-8 8-2.3-2.3a4 4 0 0 0-5-5L2 10l8-8z"/>',
    "brush": '<path d="M18 2 9 11M7 13a3 3 0 0 0-3 3c0 2-2 3-2 3s5 1 7-1a3 3 0 0 0-2-5zM9 11l4 4"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    "tooth": '<path d="M7 3c-3 0-4 3-3 6s1 5 2 9c.5 2 2 3 3 1l1-4c.4-1.5 3.6-1.5 4 0l1 4c1 2 2.5 1 3-1 1-4 1-6 2-9s0-6-3-6c-2 0-3 1-5 1S9 3 7 3z"/>',
    "spine": '<path d="M12 2v20M8 5h8M7 10h10M8 15h8M9 20h6"/>',
    "scale": '<path d="M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M11 12 21 2M17 6l3 3M14 9l2 2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "shield": '<path d="M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-5-5"/>',
    "tent": '<path d="M12 3 2 21h20zM12 3v18M8 21l4-7 4 7"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "phone": '<path d="M5 3h4l2 5-3 2a12 12 0 0 0 6 6l2-3 5 2v4a2 2 0 0 1-2 2A18 18 0 0 1 3 5a2 2 0 0 1 2-2z"/>',
    "pin": '<path d="M12 22s7-7 7-12a7 7 0 0 0-14 0c0 5 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
}
_ICON_RULES: list[tuple[str, str]] = [
    (r"ev\b|charger|charging", "plug"),
    (r"panel|breaker|electric|wiring|rewir|generator|outlet|surge", "bolt"),
    (r"light", "light"),
    (r"water heater|tankless|furnace|heat|fire|smoke", "flame"),
    (r"\bac\b|air cond|cool|hvac", "snow"),
    (r"duct|vent|air quality|mold", "fan"),
    (r"drain|leak|pipe|repip|plumb|water|sewer|sewage|faucet|toilet|irrigation|sprinkler|pool", "drop"),
    (r"roof|gutter|shingle", "roof"),
    (r"tree|shrub", "tree"),
    (r"lawn|landscap|garden|yard|hardscap|paver", "leaf"),
    (r"paint|drywall|botox|filler|inject", "brush"),
    (r"facial|peel|laser|skin|microneedl|spa|whiten|cosmetic|glow", "sparkle"),
    (r"\bdent|teeth|tooth|implant|orthodont|invisalign|crown|exam", "tooth"),
    (r"chiro|spine|back pain|neck|posture|adjust|sports injur|auto injur", "spine"),
    (r"accident|injur|attorney|law|legal|claim|death|bite|slip", "scale"),
    (r"buy|sell|home valu|listing|real estate|first-time|relocat|invest", "key"),
    (r"brake|oil|engine|tire|alignment|transmission|auto|vehicle|car\b", "car"),
    (r"tent|canop|bounce|table|chair|linen|event|party", "tent"),
    (r"inspect|diagnos|detect|assess", "search"),
    (r"emergenc|24|urgent|storm", "shield"),
    (r"maintenance|tune|plan|schedul|appointment", "calendar"),
    (r"repair|fix|install|replace|assembl|door|window", "wrench"),
    (r"home|house|remodel|renovat", "home"),
]


def icon_name(service: str) -> str:
    text = service.lower()
    for pattern, name in _ICON_RULES:
        if re.search(pattern, text):
            return name
    return "check"


def icon_svg(name: str, *, size: int = 24) -> str:
    path = _ICON_PATHS.get(name) or _ICON_PATHS["check"]
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{path}</svg>'
    )
