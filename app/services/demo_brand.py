"""Pulls a prospect's logo and brand colour from their current website.

Runs once, when a v4 demo is created, so the mockup reads as their own site
redesigned. Every step is optional: any failure returns what was found so far
and the page falls back to the niche palette and a text wordmark. The logo is
copied to the demo host so a published demo never hotlinks their site.
"""
from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from app.services.demo_design import is_brand_usable, normalize_hex

USER_AGENT = "Mozilla/5.0 (compatible; LilosGrowthDemoBuilder/1.0)"
PAGE_LIMIT = 2_000_000
LOGO_LIMIT = 1_500_000
TIMEOUT = 8
LOGO_MAX_HEIGHT = 160
LOGO_MIN_WIDTH = 60

Fetcher = Callable[[str, int], bytes | None]


def _fetch(url: str, limit: int) -> bytes | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    try:
        with requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True, allow_redirects=True,
        ) as response:
            if not response.ok:
                return None
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > limit:
                    return None
            return bytes(body)
    except requests.RequestException:
        return None


_BADGE_WORDS = ("bbb", "angi", "homeadvisor", "yelp", "google", "facebook", "houzz", "thumbtack",
                "nextdoor", "porch", "badge", "award", "partner", "certified", "visa", "mastercard")


def _name_tokens(name: str | None) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) >= 4]


def _logo_candidates(soup: BeautifulSoup, base_url: str, business_name: str | None = None) -> list[str]:
    """Image URLs that look like the site's own logo, header ones first.

    Outside the header a logo only counts when it carries the business's name,
    so review-site badges and partner logos in a footer are never picked.
    """
    tokens = _name_tokens(business_name)
    scored: list[tuple[int, str]] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        srcset = img.get("srcset") or ""
        if not src and srcset:
            src = srcset.split(",")[0].strip().split(" ")[0]
        if not src or src.startswith("data:"):
            continue
        attrs = " ".join(
            str(v) for v in (
                src, img.get("alt"), img.get("id"), " ".join(img.get("class") or []),
                img.parent.get("id") if img.parent else "",
                " ".join(img.parent.get("class") or []) if img.parent else "",
            ) if v
        ).lower()
        if "logo" not in attrs or any(word in attrs for word in _BADGE_WORDS):
            continue
        in_header = img.find_parent(["header", "nav"]) is not None
        if not in_header and not any(token in attrs for token in tokens):
            continue
        score = (0 if in_header else 1, 0 if "logo" in src.lower() else 1)
        scored.append((score[0] * 2 + score[1], urljoin(base_url, src)))
    seen: list[str] = []
    for _, url in sorted(scored, key=lambda item: item[0]):
        if url not in seen and not url.lower().split("?")[0].endswith(".svg"):
            seen.append(url)
    return seen[:3]


def _theme_color(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", attrs={"name": re.compile("^theme-color$", re.I)})
    color = normalize_hex((tag.get("content") if tag else "") or "")
    return color if is_brand_usable(color) else None


def _logo_colors(image: Image.Image) -> tuple[str | None, bool]:
    """(dominant brand colour, logo is mostly light)."""
    rgba = image.convert("RGBA")
    rgba.thumbnail((200, 200))
    raw = rgba.tobytes()
    pixels = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4) if raw[i + 3] > 200]
    if not pixels:
        return None, False
    mean_light = sum((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 for r, g, b, _ in pixels) / len(pixels)
    buckets: dict[tuple[int, int, int], int] = {}
    for r, g, b, _ in pixels:
        color = f"#{r:02x}{g:02x}{b:02x}"
        if not is_brand_usable(color):
            continue
        key = (r // 24, g // 24, b // 24)
        buckets[key] = buckets.get(key, 0) + 1
    if not buckets or max(buckets.values()) < len(pixels) * 0.04:
        return None, mean_light > 0.78
    r, g, b = max(buckets, key=buckets.get)
    return f"#{r * 24 + 12:02x}{g * 24 + 12:02x}{b * 24 + 12:02x}", mean_light > 0.78


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        alpha = image.convert("RGBA").getchannel("A")
        return alpha.getextrema()[0] < 250
    return False


def extract_brand(
    website_url: str | None,
    *,
    place_id: str,
    business_name: str | None = None,
    root: Path,
    base_url: str,
    fetch: Fetcher = _fetch,
) -> dict[str, Any]:
    """{"color", "logo_url", "logo_on_dark", "source"}; empty values on any miss."""
    result: dict[str, Any] = {"color": None, "logo_url": None, "logo_on_dark": False, "source": website_url}
    if not website_url:
        return result
    try:
        html = fetch(website_url, PAGE_LIMIT)
        if not html:
            return result
        soup = BeautifulSoup(html, "html.parser")
        result["color"] = _theme_color(soup)
        for logo_url in _logo_candidates(soup, website_url, business_name):
            data = fetch(logo_url, LOGO_LIMIT)
            if not data:
                continue
            try:
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    if image.width < LOGO_MIN_WIDTH or image.width / max(1, image.height) > 12:
                        continue
                    color, light = _logo_colors(image)
                    transparent = _has_transparency(image)
                    logo = image.convert("RGBA")
            except (UnidentifiedImageError, OSError, ValueError):
                continue
            if logo.height > LOGO_MAX_HEIGHT:
                logo = logo.resize(
                    (round(logo.width * LOGO_MAX_HEIGHT / logo.height), LOGO_MAX_HEIGHT), Image.LANCZOS,
                )
            key = hashlib.sha256(place_id.encode("utf-8")).hexdigest()[:16]
            media_dir = root / "_media" / key
            media_dir.mkdir(parents=True, exist_ok=True)
            name = f"logo-{hashlib.sha256(data).hexdigest()[:12]}.png"
            out = BytesIO()
            logo.save(out, "PNG", optimize=True)
            (media_dir / name).write_bytes(out.getvalue())
            result["logo_url"] = f"{base_url.rstrip('/')}/_media/{key}/{name}"
            # A light logo with a see-through background needs a dark backing.
            result["logo_on_dark"] = bool(light and transparent)
            result["color"] = result["color"] or color
            break
    except Exception:
        return result
    return result
