from datetime import datetime, timezone

from app.services.demo_site_renderer_v3 import render_demo_site_v3
from app.services.demo_sites import DemoSiteService


class FakeProspectRepository:
    def get_prospect(self, place_id):
        if place_id != "volt-place":
            return None
        return {
            "place_id": place_id,
            "name": "Volt Electric",
            "city": "Vista",
            "state": "CA",
            "phone": "(760) 229-3096",
            "website_url": "https://example.com",
            "primary_type": "electrician",
            "rating": 5.0,
            "review_count": 13,
            "scored_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
        }


class FakeDemoRepository:
    def create_demo(self, **kwargs):
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "place_id": kwargs["place_id"],
            "demo_version": 1,
            "status": "ready_for_review",
            "template_key": kwargs["template_key"],
            "slug": kwargs["slug"],
            "source_snapshot": kwargs["source_snapshot"],
            "content_snapshot": kwargs["content_snapshot"],
            "brand_snapshot": kwargs["brand_snapshot"],
            "published_path": None,
            "public_url": None,
            "build_error": None,
            "created_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "published_at": None,
            "html_document": kwargs["html_document"],
        }


def test_v3_is_first_controlled_template_option():
    service = DemoSiteService(FakeProspectRepository(), FakeDemoRepository())
    options = service.options_for_prospect("volt-place")
    assert options["templates"][0]["key"] == "trade-modern-v3"


def test_v3_renders_complete_local_service_homepage_without_invented_credentials():
    service = DemoSiteService(FakeProspectRepository(), FakeDemoRepository())
    demo = service.create_demo(
        "volt-place",
        template_key="trade-modern-v3",
        services=[
            "Spa Installations and Upgrades",
            "Electrical Repairs",
            "Panel Upgrades",
            "Home Safety Inspections",
        ],
        service_areas=["Vista", "Fallbrook", "San Marcos", "Escondido", "Carlsbad"],
        headline="Local electrician service for Vista",
        subheadline="Explore Volt Electric's services and get in touch directly for help in Vista and nearby areas.",
    )
    html = demo["html_document"]

    for section_id in ('id="services"', 'id="about"', 'id="areas"', 'id="faq"', 'id="contact"'):
        assert section_id in html
    assert "Getting started" in html
    assert "Have a project in mind?" in html
    assert "What customers need to know" in html
    assert "Local reputation" in html
    assert "Frequently asked questions" in html
    assert "5.0 Google rating" in html
    assert "13 Google reviews" in html
    assert "Spa Installations and Upgrades" in html
    assert "Fallbrook" in html
    assert '"@type":"LocalBusiness"' in html
    assert '"ratingValue":5.0' in html
    assert '"reviewCount":13' in html

    lowered = html.lower()
    for unsupported_claim in ("licensed", "insured", "bonded", "years of experience", "guaranteed", "24/7"):
        assert unsupported_claim not in lowered


def test_v3_uses_all_three_optional_image_slots_without_adding_more_media_inputs():
    service = DemoSiteService(FakeProspectRepository(), FakeDemoRepository())
    demo = service.create_demo(
        "volt-place",
        template_key="trade-modern-v3",
        services=["Electrical Repairs", "Panel Upgrades"],
        service_areas=["Vista", "San Marcos"],
        headline=None,
        subheadline=None,
        hero_image_url="https://images.example/hero.jpg",
        work_image_url="https://images.example/work.jpg",
        secondary_image_url="https://images.example/local.jpg",
    )
    html = demo["html_document"]
    assert 'src="https://images.example/hero.jpg"' in html
    assert 'src="https://images.example/work.jpg"' in html
    assert 'src="https://images.example/local.jpg"' in html
    assert 'class="photo-band"' in html


def test_v3_keeps_indexing_disabled_and_escapes_content():
    html = render_demo_site_v3(
        source={
            "name": "Example & Sons </script><script>alert(1)</script>",
            "city": "Vista",
            "state": "CA",
            "phone": "(760) 555-0100",
            "primary_type_display": "Electrician",
            "rating": 4.9,
            "review_count": 20,
        },
        content={
            "headline": '<img src=x onerror="alert(1)">',
            "subheadline": "Safe & local",
            "services": ["Panel <Upgrades>"],
            "service_areas": ["Vista & nearby"],
            "hero_image_url": None,
            "work_image_url": None,
            "secondary_image_url": None,
        },
        brand={"palette": {"ink": "#102033", "accent": "#f0b22c", "surface": "#f4f6f7"}},
    )
    assert '<meta name="robots" content="noindex,nofollow,noarchive" />' in html
    assert "</script><script>alert(1)</script>" not in html
    assert "<\\/script><script>alert(1)<\\/script>" in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "Panel &lt;Upgrades&gt;" in html
