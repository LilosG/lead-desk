from datetime import datetime, timezone
from pathlib import Path

from app.services.demo_site_renderer import render_demo_site
from app.services.demo_sites import DemoSiteError, DemoSiteService


class FakeProspectRepository:
    def __init__(self):
        self.prospect = {
            "place_id": "place-1",
            "name": "Example Electric",
            "city": "Poway",
            "state": "CA",
            "phone": "(858) 555-0100",
            "website_url": "https://example.com",
            "primary_type": "electrician",
            "rating": 4.9,
            "review_count": 71,
            "scored_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "total_score": 99,
            "tier": "A",
        }

    def get_prospect(self, place_id):
        return dict(self.prospect) if place_id == "place-1" else None


class FakeDemoRepository:
    def __init__(self):
        self.created = None
        self.demo = None
        self.published = None
        self.failed = None

    def create_demo(self, **kwargs):
        self.created = kwargs
        self.demo = {
            "id": "11111111-1111-1111-1111-111111111111",
            "place_id": kwargs["place_id"],
            "demo_version": 1,
            "status": "ready_for_review",
            "template_key": kwargs["template_key"],
            "slug": kwargs["slug"],
            "source_snapshot": kwargs["source_snapshot"],
            "content_snapshot": kwargs["content_snapshot"],
            "brand_snapshot": kwargs["brand_snapshot"],
            "html_document": kwargs["html_document"],
            "published_path": None,
            "public_url": None,
            "build_error": None,
            "created_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "published_at": None,
        }
        return dict(self.demo)

    def get_demo(self, demo_id, *, include_html=False):
        if not self.demo or demo_id != self.demo["id"]:
            return None
        result = dict(self.demo)
        if not include_html:
            result.pop("html_document", None)
        return result

    def list_for_prospect(self, place_id, *, limit=10):
        if not self.demo or self.demo["place_id"] != place_id:
            return []
        result = dict(self.demo)
        for key in ("source_snapshot", "content_snapshot", "brand_snapshot", "html_document", "published_path"):
            result.pop(key, None)
        return [result]

    def mark_published(self, demo_id, *, published_path, public_url):
        if not self.demo or self.demo["id"] != demo_id or self.demo["status"] != "ready_for_review":
            return None
        self.demo["status"] = "published"
        self.demo["published_path"] = published_path
        self.demo["public_url"] = public_url
        self.demo["published_at"] = datetime(2026, 9, 17, tzinfo=timezone.utc)
        self.published = {
            "id": demo_id,
            "place_id": self.demo["place_id"],
            "demo_version": 1,
            "status": "published",
            "template_key": self.demo["template_key"],
            "slug": self.demo["slug"],
            "public_url": public_url,
            "build_error": None,
            "created_at": self.demo["created_at"],
            "updated_at": self.demo["updated_at"],
            "published_at": self.demo["published_at"],
        }
        return dict(self.published)

    def mark_build_failed(self, demo_id, *, error):
        self.failed = (demo_id, error)
        if self.demo and self.demo["id"] == demo_id:
            self.demo["status"] = "build_failed"


def _create_demo(repository=None):
    repo = repository or FakeDemoRepository()
    service = DemoSiteService(FakeProspectRepository(), repo)
    demo = service.create_demo(
        "place-1",
        template_key="trade-modern-v1",
        services=["Panel Upgrades", "EV Charger Installation"],
        service_areas=["Poway", "San Diego"],
        headline="Poway electrical service with a clearer local experience",
        subheadline="A concept homepage built from confirmed business information.",
    )
    return service, repo, demo


def test_demo_is_manual_review_state_and_snapshots_only_client_safe_facts():
    _, repo, demo = _create_demo()

    assert demo["status"] == "ready_for_review"
    assert demo["public_url"] is None
    assert repo.created["source_snapshot"]["name"] == "Example Electric"
    assert repo.created["source_snapshot"]["rating"] == 4.9
    assert repo.created["source_snapshot"]["review_count"] == 71
    serialized = str(repo.created["source_snapshot"]).lower()
    assert "total_score" not in serialized
    assert "tier" not in serialized
    assert repo.created["content_snapshot"]["services"] == [
        "Panel Upgrades",
        "EV Charger Installation",
    ]


def test_renderer_disables_indexing_and_contains_concept_disclosure():
    _, repo, _ = _create_demo()
    html = repo.created["html_document"]

    assert '<meta name="robots" content="noindex,nofollow,noarchive" />' in html
    assert "Concept website prepared by LILOs Growth for demonstration purposes." in html
    assert "Not affiliated with or endorsed by Example Electric." in html
    assert "4.9 Google rating · 71 reviews" in html
    assert "Panel Upgrades" in html
    assert "EV Charger Installation" in html


def test_renderer_escapes_user_supplied_content():
    html = render_demo_site(
        source={
            "name": "Example & Sons <script>",
            "city": "Poway",
            "state": "CA",
            "phone": "(858) 555-0100",
            "primary_type_display": "Electrician",
        },
        content={
            "headline": '<img src=x onerror="alert(1)">',
            "subheadline": "Safe & local",
            "services": ["EV <Fast>"],
            "service_areas": ["Poway & nearby"],
        },
        brand={"palette": {"ink": "#132238", "accent": "#e4a72f", "surface": "#f4f6f8"}},
    )

    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "EV &lt;Fast&gt;" in html


def test_service_caps_manual_services_and_service_areas():
    repo = FakeDemoRepository()
    service = DemoSiteService(FakeProspectRepository(), repo)
    demo = service.create_demo(
        "place-1",
        template_key="trade-modern-v1",
        services=[f"Service {index}" for index in range(10)],
        service_areas=[f"Area {index}" for index in range(12)],
        headline=None,
        subheadline=None,
    )

    assert len(demo["content_snapshot"]["services"]) == 6
    assert len(demo["content_snapshot"]["service_areas"]) == 8


def test_publish_requires_explicit_ready_for_review_state(tmp_path: Path):
    service, repo, demo = _create_demo()
    repo.demo["status"] = "published"

    try:
        service.publish_demo(
            demo["id"],
            root=tmp_path,
            base_url="https://demo.lilosgrowth.com",
        )
    except DemoSiteError as exc:
        assert "not ready for publication" in str(exc)
    else:
        raise AssertionError("publish should reject a demo that is not ready for review")

    assert list(tmp_path.iterdir()) == []


def test_publish_writes_static_unindexed_artifact_only_after_approval(tmp_path: Path):
    service, repo, demo = _create_demo()

    result = service.publish_demo(
        demo["id"],
        root=tmp_path,
        base_url="https://demo.lilosgrowth.com",
    )

    target = tmp_path / demo["slug"]
    assert result["status"] == "published"
    assert result["public_url"] == f"https://demo.lilosgrowth.com/{demo['slug']}/"
    assert target.is_dir()
    assert (target / "index.html").is_file()
    assert (target / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert "noindex,nofollow,noarchive" in (target / "index.html").read_text()


def test_publish_path_is_derived_from_server_slug_not_user_path(tmp_path: Path):
    service, repo, demo = _create_demo()
    repo.demo["slug"] = "../escape"

    try:
        service.publish_demo(
            demo["id"],
            root=tmp_path,
            base_url="https://demo.lilosgrowth.com",
        )
    except DemoSiteError as exc:
        assert "invalid demo publish path" in str(exc)
    else:
        raise AssertionError("path traversal should be rejected")

    assert not (tmp_path.parent / "escape").exists()


def test_unknown_template_is_rejected():
    service = DemoSiteService(FakeProspectRepository(), FakeDemoRepository())

    try:
        service.create_demo(
            "place-1",
            template_key="freeform-ai",
            services=[],
            service_areas=[],
            headline=None,
            subheadline=None,
        )
    except DemoSiteError as exc:
        assert "unsupported demo template" in str(exc)
    else:
        raise AssertionError("unsupported template should be rejected")
