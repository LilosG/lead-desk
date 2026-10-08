import re
import secrets
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.repositories.demo_sites import DemoSiteRepository
from app.repositories.prospects import ProspectRepository
from app.services.demo_site_renderer import palette_for, render_demo_site, template_options
from app.services.demo_site_renderer_v3 import V3_TEMPLATE_OPTION, render_demo_site_v3
from pipeline import verticals as vertical_config


class DemoSiteError(Exception):
    pass


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


def _auto_services(audit: dict[str, Any] | None) -> list[str]:
    """Offering names read from the prospect's own site navigation."""
    titles = (audit or {}).get("offering_titles") or []
    return _normalize_list([str(t) for t in titles], max_items=6)


def _auto_areas(prospect: dict[str, Any]) -> list[str]:
    areas = [prospect.get("city"), _market_city(prospect.get("market"))]
    return _normalize_list([a for a in areas if a], max_items=8)


def _template_options() -> list[dict[str, str]]:
    return [dict(V3_TEMPLATE_OPTION), *template_options()]


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
                "headline": f"{primary_type} in {city}",
                "subheadline": (
                    f"See what {business_name} offers, where it serves, and the quickest way "
                    "to get in touch."
                ),
                # Pre-filled from the prospect's own site and market so a demo
                # can be generated in one click; still editable before saving.
                "services": _auto_services(audit),
                "service_areas": _auto_areas(prospect),
                "hero_image_url": None,
                "work_image_url": None,
                "secondary_image_url": None,
            },
        }

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
    ) -> dict[str, Any]:
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise DemoSiteError("prospect not found")
        if template_key not in {item["key"] for item in _template_options()}:
            raise DemoSiteError("unsupported demo template")

        primary_type_display = _display_type(prospect.get("primary_type"))
        business_name = prospect.get("name") or "Business"
        city = prospect.get("city") or "your area"
        normalized_services = _normalize_list(services, max_items=6)
        normalized_areas = _normalize_list(service_areas, max_items=8)
        if not normalized_services:
            normalized_services = _auto_services(self._website_audit(place_id))
        if not normalized_areas:
            normalized_areas = _auto_areas(prospect)

        source_snapshot = {
            "place_id": place_id,
            "name": business_name,
            "city": prospect.get("city"),
            "state": prospect.get("state"),
            "phone": prospect.get("phone"),
            "website_url": prospect.get("website_url"),
            "primary_type": prospect.get("primary_type"),
            "primary_type_display": primary_type_display,
            "vertical": prospect.get("vertical"),
            "niche_profile": vertical_config.vertical_profile(prospect.get("vertical") or ""),
            "rating": float(prospect["rating"]) if prospect.get("rating") is not None else None,
            "review_count": int(prospect["review_count"]) if prospect.get("review_count") is not None else None,
            "scored_at": prospect.get("scored_at").isoformat() if prospect.get("scored_at") else None,
        }
        content_snapshot = {
            "headline": (headline or f"{primary_type_display} in {city}").strip(),
            "subheadline": (
                subheadline
                or f"See what {business_name} offers, where it serves, and the quickest way to get in touch."
            ).strip(),
            "services": normalized_services,
            "service_areas": normalized_areas,
            "hero_image_url": _normalize_media_url(hero_image_url),
            "work_image_url": _normalize_media_url(work_image_url),
            "secondary_image_url": _normalize_media_url(secondary_image_url),
        }
        brand_snapshot = {
            "template_key": template_key,
            "palette": palette_for(prospect.get("primary_type")),
        }
        if template_key == V3_TEMPLATE_OPTION["key"]:
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
