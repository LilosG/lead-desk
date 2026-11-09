import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.repositories.demo_sites import DemoSiteRepository
from app.repositories.prospects import ProspectRepository
from app.services import audit_benchmarks
from app.services.demo_autofill import MAX_AREAS, MAX_SERVICES, suggested_areas, suggested_services
from app.services.demo_site_renderer import palette_for, render_demo_site, template_options
from app.services.demo_brand import extract_brand
from app.services.demo_copywriter import DemoCopyError, write_demo_copy
from app.services.demo_design import palette_with_brand, style_for
from app.services.demo_site_renderer_v3 import V3_TEMPLATE_OPTION, niche_copy, render_demo_site_v3
from app.services.demo_site_renderer_v4 import V4_KEYS, V4_TEMPLATE_OPTIONS, render_demo_site_v4, style_override
from pipeline import verticals as vertical_config


REVIEW_MIN_CHARS = 40


class DemoSiteError(Exception):
    pass


def _https_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _normalize_list(values: list[str], *, max_items: int) -> list[str]:
    result: list[str] = []
    for value in values:
        for raw_item in re.split(r"[\n,;]+", str(value)):
            item = raw_item.strip()
            if not item or item in result:
                continue
            result.append(item)
            if len(result) >= max_items:
                return result
    return result


def _normalize_media_url(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DemoSiteError("demo image URLs must use http or https")
    return candidate


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "prospect"
    return f"{base[:48]}-{secrets.token_hex(3)}"


def _display_type(value: str | None) -> str:
    return (value or "local business").replace("_", " ").title()


def _market_city(market: str | None) -> str | None:
    if not market:
        return None
    first = market.split(",")[0].strip()
    return first or None


def _site_services(audit: dict[str, Any] | None) -> list[str]:
    """Offering names read from the prospect's own site navigation."""
    return _normalize_list(audit_benchmarks.offering_titles(audit or {}), max_items=MAX_SERVICES)


def _auto_services(prospect: dict[str, Any], audit: dict[str, Any] | None) -> list[str]:
    """Their own services first, topped up with the niche's core offerings."""
    return suggested_services(_site_services(audit), prospect.get("vertical"))


def _review_month(published: Any) -> str | None:
    try:
        return datetime.fromisoformat(str(published)[:10]).strftime("%B %Y")
    except ValueError:
        return None


def showcase_reviews(reviews: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """The strongest real Google reviews, keeping Google's attribution with each."""
    usable = []
    for review in reviews:
        text = " ".join(str((review.get("text") or {}).get("text") or "").split())
        author = review.get("authorAttribution") or {}
        rating = int(review.get("rating") or 0)
        if rating < 4 or len(text) < REVIEW_MIN_CHARS or not author.get("displayName"):
            continue
        usable.append({
            "author": author["displayName"],
            "author_url": _https_or_none(author.get("uri")),
            "author_photo": _https_or_none(author.get("photoUri")),
            "rating": rating,
            "text": text,
            "date": _review_month(review.get("publishTime")),
            "published": str(review.get("publishTime") or ""),
            "url": _https_or_none(review.get("googleMapsUri")),
        })
    usable.sort(key=lambda r: (r["rating"], r["published"]), reverse=True)
    return [{k: v for k, v in r.items() if k != "published"} for r in usable[:limit]]


def _own_areas(prospect: dict[str, Any]) -> list[str]:
    areas = [prospect.get("city"), _market_city(prospect.get("market"))]
    return _normalize_list([a for a in areas if a], max_items=MAX_AREAS)


def _template_options() -> list[dict[str, str]]:
    """What the builder offers, recommended first. Older templates stay valid for existing demos."""
    classic = {**V3_TEMPLATE_OPTION, "name": "Classic homepage (v3)"}
    return [*(dict(item) for item in V4_TEMPLATE_OPTIONS), classic]


def _valid_template_keys() -> set[str]:
    return {V3_TEMPLATE_OPTION["key"], *V4_KEYS, *(item["key"] for item in template_options())}


def _default_headline(prospect: dict[str, Any], category: str, city: str) -> str:
    rating, reviews = prospect.get("rating"), prospect.get("review_count") or 0
    if rating is not None and float(rating) >= 4.5 and reviews >= 10 and prospect.get("city"):
        return f"{city}'s {float(rating):.1f}-star {category.lower()}"
    return f"{category} in {city}"


def _default_subheadline(prospect: dict[str, Any], city: str) -> str:
    audience = niche_copy(vertical_config.vertical_profile(prospect.get("vertical") or ""))["audience"]
    name = prospect.get("name") or "We"
    return f"{name} works with {audience} across {city} and nearby communities. Get in touch to talk through what you need."


class DemoSiteService:
    def __init__(
        self,
        prospect_repository: ProspectRepository,
        demo_repository: DemoSiteRepository,
    ):
        self.prospect_repository = prospect_repository
        self.demo_repository = demo_repository

    def options_for_prospect(self, place_id: str) -> dict[str, Any]:
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise DemoSiteError("prospect not found")

        primary_type = _display_type(prospect.get("primary_type"))
        city = prospect.get("city") or "your area"
        business_name = prospect.get("name") or "Business"
        audit = self._website_audit(place_id)
        return {
            "place_id": place_id,
            "business_name": business_name,
            "templates": _template_options(),
            "defaults": {
                "headline": _default_headline(prospect, primary_type, city),
                "subheadline": _default_subheadline(prospect, city),
                # Pre-filled from the prospect's own site and market so a demo
                # can be generated in one click; still editable before saving.
                "services": _auto_services(prospect, audit),
                "service_areas": self._auto_areas(prospect),
                "hero_image_url": None,
                "work_image_url": None,
                "secondary_image_url": None,
            },
        }

    def _google_reviews(self, place_id: str) -> list[dict[str, Any]]:
        lookup = getattr(self.prospect_repository, "get_google_reviews", None)
        if lookup is None:
            return []
        try:
            return lookup(place_id)
        except Exception:
            return []

    def _auto_areas(self, prospect: dict[str, Any]) -> list[str]:
        """Their own town, then nearby towns from businesses already swept."""
        own = _own_areas(prospect)
        lookup = getattr(self.prospect_repository, "nearby_towns", None)
        lat, lng = prospect.get("lat"), prospect.get("lng")
        nearby: list[str] = []
        if lookup is not None and lat is not None and lng is not None:
            try:
                nearby = lookup(float(lat), float(lng), exclude=own, limit=MAX_AREAS)
            except Exception:
                nearby = []
        return suggested_areas(own, nearby)

    def _demo_details(self, place_id: str) -> dict[str, Any]:
        lookup = getattr(self.prospect_repository, "get_demo_details", None)
        if lookup is None:
            return {}
        try:
            return lookup(place_id) or {}
        except Exception:
            return {}

    @staticmethod
    def _site_brand(
        prospect: dict[str, Any],
        place_id: str,
        *,
        enabled: bool,
        root: Path | None,
        base_url: str | None,
    ) -> dict[str, Any]:
        """Logo and brand colour from their current site; empty when unavailable."""
        website = prospect.get("website_url")
        if not enabled or not website or root is None or not base_url:
            return {}
        try:
            return extract_brand(
                website, place_id=place_id, business_name=prospect.get("name"), root=root, base_url=base_url,
            )
        except Exception:
            return {}

    def _website_audit(self, place_id: str) -> dict[str, Any] | None:
        lookup = getattr(self.prospect_repository, "get_website_audit", None)
        if lookup is None:
            return None
        try:
            return lookup(place_id)
        except Exception:
            return None

    def create_demo(
        self,
        place_id: str,
        *,
        template_key: str,
        services: list[str],
        service_areas: list[str],
        headline: str | None,
        subheadline: str | None,
        hero_image_url: str | None = None,
        work_image_url: str | None = None,
        secondary_image_url: str | None = None,
        about: str | None = None,
        service_blurbs: dict[str, str] | None = None,
        use_site_branding: bool = True,
        media_root: Path | None = None,
        media_base_url: str | None = None,
    ) -> dict[str, Any]:
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise DemoSiteError("prospect not found")
        if template_key not in _valid_template_keys():
            raise DemoSiteError("unsupported demo template")

        primary_type_display = _display_type(prospect.get("primary_type"))
        business_name = prospect.get("name") or "Business"
        city = prospect.get("city") or "your area"
        normalized_services = _normalize_list(services, max_items=6)
        normalized_areas = _normalize_list(service_areas, max_items=8)
        if not normalized_services:
            normalized_services = _auto_services(prospect, self._website_audit(place_id))
        if not normalized_areas:
            normalized_areas = self._auto_areas(prospect)

        source_snapshot = {
            "place_id": place_id,
            "name": business_name,
            "city": prospect.get("city"),
            "state": prospect.get("state"),
            "phone": prospect.get("phone"),
            "website_url": prospect.get("website_url"),
            "google_maps_uri": prospect.get("google_maps_uri"),
            "primary_type": prospect.get("primary_type"),
            "primary_type_display": primary_type_display,
            "vertical": prospect.get("vertical"),
            "niche_profile": vertical_config.vertical_profile(prospect.get("vertical") or ""),
            "rating": float(prospect["rating"]) if prospect.get("rating") is not None else None,
            "review_count": int(prospect["review_count"]) if prospect.get("review_count") is not None else None,
            "scored_at": prospect.get("scored_at").isoformat() if prospect.get("scored_at") else None,
            "reviews": showcase_reviews(self._google_reviews(place_id)),
        }
        content_snapshot = {
            "headline": (headline or _default_headline(prospect, primary_type_display, city)).strip(),
            "subheadline": (subheadline or _default_subheadline(prospect, city)).strip(),
            "services": normalized_services,
            "service_areas": normalized_areas,
            "hero_image_url": _normalize_media_url(hero_image_url),
            "work_image_url": _normalize_media_url(work_image_url),
            "secondary_image_url": _normalize_media_url(secondary_image_url),
            "about": (about or "").strip() or None,
            "service_blurbs": {
                name: " ".join(str(text).split())
                for name, text in (service_blurbs or {}).items()
                if name in normalized_services and str(text).strip()
            },
        }
        brand_snapshot = {
            "template_key": template_key,
            "palette": palette_for(prospect.get("primary_type"), source_snapshot["niche_profile"]),
        }
        if template_key in V4_KEYS:
            details = self._demo_details(place_id)
            source_snapshot.update({
                "hours": details.get("hours_json"),
                "street": details.get("street"),
                "address": details.get("formatted_address"),
            })
            site_brand = self._site_brand(
                prospect, place_id, enabled=use_site_branding, root=media_root, base_url=media_base_url,
            )
            brand_snapshot.update({
                "style": style_for(source_snapshot["niche_profile"], style_override(template_key)),
                "palette": palette_with_brand(brand_snapshot["palette"], site_brand.get("color")),
                "logo_url": site_brand.get("logo_url"),
                "logo_on_dark": bool(site_brand.get("logo_on_dark")),
                "brand_color": site_brand.get("color"),
                "brand_source": site_brand.get("source"),
            })
            html_document = render_demo_site_v4(
                source=source_snapshot,
                content=content_snapshot,
                brand=brand_snapshot,
            )
        elif template_key == V3_TEMPLATE_OPTION["key"]:
            html_document = render_demo_site_v3(
                source=source_snapshot,
                content=content_snapshot,
                brand=brand_snapshot,
            )
        else:
            html_document = render_demo_site(
                source=source_snapshot,
                content=content_snapshot,
                brand=brand_snapshot,
            )
        return self.demo_repository.create_demo(
            place_id=place_id,
            template_key=template_key,
            slug=_slugify(business_name),
            source_snapshot=source_snapshot,
            content_snapshot=content_snapshot,
            brand_snapshot=brand_snapshot,
            html_document=html_document,
        )

    def write_copy(
        self,
        place_id: str,
        *,
        services: list[str],
        service_areas: list[str],
        api_key: str,
        model: str,
    ) -> dict[str, Any]:
        """Suggested headline, intro, about and service lines; nothing is saved."""
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise DemoSiteError("prospect not found")
        audit = self._website_audit(place_id)
        normalized_services = _normalize_list(services, max_items=MAX_SERVICES) or _auto_services(prospect, audit)
        normalized_areas = _normalize_list(service_areas, max_items=MAX_AREAS) or self._auto_areas(prospect)
        profile = vertical_config.vertical_profile(prospect.get("vertical") or "")
        reviews = showcase_reviews(self._google_reviews(place_id), limit=3)
        facts = {
            "name": prospect.get("name") or "Business",
            "category": _display_type(prospect.get("primary_type")),
            "city": prospect.get("city") or (normalized_areas[0] if normalized_areas else ""),
            "areas": normalized_areas,
            "services": normalized_services,
            "audience": niche_copy(profile)["audience"],
            "rating": float(prospect["rating"]) if prospect.get("rating") is not None else None,
            "review_count": int(prospect["review_count"]) if prospect.get("review_count") is not None else None,
            "review_texts": [r["text"] for r in reviews],
            "site_summary": (audit or {}).get("meta_description") or (audit or {}).get("h1_text"),
        }
        try:
            return write_demo_copy(facts, api_key=api_key, model=model)
        except DemoCopyError as exc:
            raise DemoSiteError(f"couldn't write copy: {exc}") from exc

    def get_demo(self, demo_id: str) -> dict[str, Any] | None:
        return self.demo_repository.get_demo(demo_id)

    def get_preview_html(self, demo_id: str) -> str | None:
        demo = self.demo_repository.get_demo(demo_id, include_html=True)
        return demo.get("html_document") if demo else None

    def list_for_prospect(self, place_id: str) -> list[dict[str, Any]]:
        return self.demo_repository.list_for_prospect(place_id)

    def publish_demo(
        self,
        demo_id: str,
        *,
        root: Path,
        base_url: str,
    ) -> dict[str, Any]:
        demo = self.demo_repository.get_demo(demo_id, include_html=True)
        if demo is None:
            raise DemoSiteError("demo site not found")
        if demo["status"] != "ready_for_review":
            raise DemoSiteError("demo site is not ready for publication")

        root = root.resolve()
        target = (root / demo["slug"]).resolve()
        if root not in target.parents:
            raise DemoSiteError("invalid demo publish path")

        try:
            target.mkdir(parents=True, exist_ok=False)
            (target / "index.html").write_text(demo["html_document"], encoding="utf-8")
            (target / "robots.txt").write_text(
                "User-agent: *\nDisallow: /\n",
                encoding="utf-8",
            )
        except Exception as exc:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            self.demo_repository.mark_build_failed(demo_id, error=str(exc))
            raise DemoSiteError(f"demo publication failed: {exc}") from exc

        public_url = f"{base_url.rstrip('/')}/{demo['slug']}/"
        try:
            result = self.demo_repository.mark_published(
                demo_id,
                published_path=str(target),
                public_url=public_url,
            )
        except Exception as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise DemoSiteError(f"demo publication state update failed: {exc}") from exc

        if result is None:
            shutil.rmtree(target, ignore_errors=True)
            raise DemoSiteError("demo publication state changed before completion")
        return result
