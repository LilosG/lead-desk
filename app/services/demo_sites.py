import re
import secrets
from pathlib import Path
from typing import Any

from app.repositories.demo_sites import DemoSiteRepository
from app.repositories.prospects import ProspectRepository
from app.services.demo_site_renderer import palette_for, render_demo_site, template_options


class DemoSiteError(Exception):
    pass


def _normalize_list(values: list[str], *, max_items: int) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in result:
            continue
        result.append(item)
        if len(result) >= max_items:
            break
    return result


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "prospect"
    return f"{base[:48]}-{secrets.token_hex(3)}"


def _display_type(value: str | None) -> str:
    return (value or "home service professional").replace("_", " ").title()


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
        return {
            "place_id": place_id,
            "business_name": business_name,
            "templates": template_options(),
            "defaults": {
                "headline": f"{primary_type} serving {city}",
                "subheadline": (
                    f"A cleaner, more conversion-focused homepage concept for {business_name}, "
                    "built from confirmed business information and public reputation signals."
                ),
                "services": [],
                "service_areas": [prospect.get("city")] if prospect.get("city") else [],
            },
        }

    def create_demo(
        self,
        place_id: str,
        *,
        template_key: str,
        services: list[str],
        service_areas: list[str],
        headline: str | None,
        subheadline: str | None,
    ) -> dict[str, Any]:
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise DemoSiteError("prospect not found")
        if template_key not in {item["key"] for item in template_options()}:
            raise DemoSiteError("unsupported demo template")

        primary_type_display = _display_type(prospect.get("primary_type"))
        business_name = prospect.get("name") or "Business"
        city = prospect.get("city") or "your area"
        normalized_services = _normalize_list(services, max_items=6)
        normalized_areas = _normalize_list(service_areas, max_items=8)

        source_snapshot = {
            "place_id": place_id,
            "name": business_name,
            "city": prospect.get("city"),
            "state": prospect.get("state"),
            "phone": prospect.get("phone"),
            "website_url": prospect.get("website_url"),
            "primary_type": prospect.get("primary_type"),
            "primary_type_display": primary_type_display,
            "rating": float(prospect["rating"]) if prospect.get("rating") is not None else None,
            "review_count": int(prospect["review_count"]) if prospect.get("review_count") is not None else None,
            "scored_at": prospect.get("scored_at").isoformat() if prospect.get("scored_at") else None,
        }
        content_snapshot = {
            "headline": (headline or f"{primary_type_display} serving {city}").strip(),
            "subheadline": (
                subheadline
                or f"A polished local-service homepage concept for {business_name}, built from confirmed business information and public reputation signals."
            ).strip(),
            "services": normalized_services,
            "service_areas": normalized_areas,
        }
        brand_snapshot = {
            "template_key": template_key,
            "palette": palette_for(prospect.get("primary_type")),
        }
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
            self.demo_repository.mark_build_failed(demo_id, error=str(exc))
            raise DemoSiteError(f"demo publication failed: {exc}") from exc

        public_url = f"{base_url.rstrip('/')}/{demo['slug']}/"
        result = self.demo_repository.mark_published(
            demo_id,
            published_path=str(target),
            public_url=public_url,
        )
        if result is None:
            raise DemoSiteError("demo publication state changed before completion")
        return result
