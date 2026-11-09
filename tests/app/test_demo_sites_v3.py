from datetime import datetime, timezone

from app.services.demo_site_renderer_v3 import render_demo_site_v3
from app.services.demo_sites import DemoSiteService, showcase_reviews


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
    assert "Ready to get started?" in html
    assert "Why Pool Pros" in html or "choose" in html
    assert 'class="site-footer"' in html and "Areas served" in html
    assert "Frequently asked questions" in html
    assert "5.0 Google rating" in html
    assert "13 Google reviews" in html
    assert "Spa Installations and Upgrades" in html
    assert "Fallbrook" in html
    assert '"@type":"LocalBusiness"' in html
    # Google reviews are not marked up as the business's own reviews.
    assert "aggregateRating" not in html
    assert "★★★★★" in html  # 5.0 rating renders five filled stars

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



class LowRatedMedSpaRepository(FakeProspectRepository):
    def get_prospect(self, place_id):
        row = super().get_prospect("volt-place")
        row.update({
            "place_id": place_id, "name": "Glow Aesthetics", "vertical": "med_spa",
            "primary_type": "medical_spa", "rating": 3.6, "review_count": 41,
            "market": "Scottsdale, AZ, USA", "city": "Scottsdale",
        })
        return row

    def get_website_audit(self, place_id):
        return {"offering_titles": ["Botox", "Dermal Fillers", "HydraFacial"]}


def test_stars_match_the_real_rating_and_copy_fits_the_niche():
    service = DemoSiteService(LowRatedMedSpaRepository(), FakeDemoRepository())
    demo = service.create_demo(
        "spa-place", template_key="trade-modern-v3", services=[], service_areas=[],
        headline=None, subheadline=None,
    )
    html = demo["html_document"]
    assert "★★★★☆" in html and "★★★★★" not in html
    # Auto-filled from the prospect's own site navigation and market.
    for item in ("Botox", "Dermal Fillers", "HydraFacial"):
        assert item in html
    lowered = html.lower()
    assert "homeowner" not in lowered
    assert "treatment" in lowered
    assert "book a consultation" in lowered or "call (760)" in lowered


def test_demo_options_prefill_services_and_areas():
    service = DemoSiteService(LowRatedMedSpaRepository(), FakeDemoRepository())
    defaults = service.options_for_prospect("spa-place")["defaults"]
    # Their own three first, then the med spa core offerings not already listed.
    assert defaults["services"] == [
        "Botox", "Dermal Fillers", "HydraFacial",
        "Laser Hair Removal", "Chemical Peels", "Microneedling",
    ]
    assert defaults["service_areas"] == ["Scottsdale"]


PALETTE = {"ink": "#102033", "accent": "#f0b22c", "surface": "#f4f6f7"}


def _google_review(name, rating, text, when="2026-08-14T17:02:11Z"):
    return {
        "rating": rating,
        "text": {"text": text},
        "publishTime": when,
        "googleMapsUri": "https://www.google.com/maps/reviews/data=abc",
        "authorAttribution": {
            "displayName": name,
            "uri": "https://www.google.com/maps/contrib/1",
            "photoUri": "https://lh3.googleusercontent.com/a/1",
        },
    }


def test_showcase_keeps_the_best_real_reviews_with_their_attribution():
    picked = showcase_reviews([
        _google_review("Low Rating", 2, "This was a disappointing visit from start to finish."),
        _google_review("Too Short", 5, "Great!"),
        _google_review("Older Five", 5, "Showed up on time and fixed the panel the same day.", "2025-01-01T00:00:00Z"),
        _google_review("Newer Five", 5, "Honest pricing and clean work, would hire them again."),
        _google_review("Four Star", 4, "Good work overall, the crew was friendly and careful."),
        _google_review("No Text", 5, ""),
    ])
    assert [r["author"] for r in picked] == ["Newer Five", "Older Five", "Four Star"]
    assert picked[0]["date"] == "August 2026"
    assert picked[0]["author_url"] == "https://www.google.com/maps/contrib/1"


def test_reviews_render_escaped_attributed_and_in_the_nav():
    source = {"name": "Volt Electric", "city": "Vista", "state": "CA", "rating": 4.8, "review_count": 13,
              "google_maps_uri": "https://maps.google.com/?cid=1",
              "reviews": [{"author": "Ann <b>Lee</b>", "rating": 5, "text": "A <script>tag</script> and more " * 20,
                           "date": "August 2026", "url": "https://www.google.com/maps/reviews/1"}]}
    html = render_demo_site_v3(source=source, content={}, brand={"palette": PALETTE})
    assert 'href="#reviews"' in html and 'id="reviews"' in html
    assert "Ann &lt;b&gt;Lee&lt;/b&gt;" in html
    assert "<script>tag" not in html
    assert "Posted on Google" in html and "August 2026" in html
    assert "Read all 13 on Google" in html
    assert "…" in html


def test_without_review_text_the_page_keeps_only_the_rating():
    source = {"name": "Volt Electric", "city": "Vista", "state": "CA", "rating": 4.8, "review_count": 13}
    html = render_demo_site_v3(source=source, content={}, brand={"palette": PALETTE})
    assert 'href="#reviews"' not in html
    assert 'class="review-card"' not in html
    assert "rating-panel" in html


def test_service_cards_describe_the_job_not_the_business_name():
    source = {"name": "Fast Plumbing", "city": "Las Vegas", "state": "NV", "rating": 4.7, "review_count": 13}
    content = {"services": ["Water Heater Repair & Installation", "Sewer Line Repair & Replacement",
                            "Commercial Plumbing Maintenance", "Emergency Plumbing Services"]}
    html = render_demo_site_v3(source=source, content=content, brand={"palette": PALETTE})
    assert "Talk to Fast Plumbing about" not in html
    assert "No hot water, a leaking tank" in html
    assert "Upkeep and repairs for offices" in html


def test_unknown_services_get_varied_lines_with_the_right_word():
    from app.services.demo_service_copy import describe_service

    lines = {describe_service("Lip Filler", i, "treatment") for i in range(3)}
    assert len(lines) == 3
    assert any("right treatment" in line for line in lines)
    assert describe_service("Tankless Water Heater") == describe_service("Water Heater Repair")
    assert describe_service("Pest Control") != describe_service("Lock Change")
