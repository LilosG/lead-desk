import json
from datetime import datetime, timezone
from decimal import Decimal

from app.services.audit_report_pdf import render_audit_report_pdf
from app.services.audit_reports import AuditReportError, AuditReportService


class FakeProspectRepository:
    def __init__(self):
        self.prospect = {
            "place_id": "place-1",
            "name": "Example Electric",
            "city": "San Diego",
            "state": "CA",
            "phone": "(619) 555-0101",
            "website_url": "https://example.com",
            "primary_type": "electrician",
            "rating": 4.9,
            "review_count": 87,
            "last_review_days": 12,
            "confirmed_trading": True,
            "established": True,
            "scored_at": datetime(2026, 9, 16, tzinfo=timezone.utc),
            "total_score": 99,
            "tier": "A",
        }
        self.findings = [
            {
                "signal": "no_localbusiness_schema",
                "observed": None,
                "finding": "internal raw finding",
            },
            {
                "signal": "no_service_pages",
                "observed": None,
                "finding": "internal raw service-page finding",
            },
            {
                "signal": "no_city_pages",
                "observed": None,
                "finding": "internal raw city-page finding",
            },
            {
                "signal": "nap_mismatch",
                "observed": {
                    "website_phone": "(619) 555-0101",
                    "gbp_phone": "(619) 555-0102",
                },
                "finding": "internal raw NAP claim",
            },
            {
                "signal": "email_found",
                "observed": "owner@example.com",
                "finding": "internal reachability finding",
            },
        ]
        self.audit = {
            "checked_at": datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc),
            "resolved_url": "https://example.com/",
            "is_reachable": True,
            "has_ssl": True,
            "title": "Example Electric | San Diego Electrician",
            "title_length": 40,
            "has_localbusiness_schema": False,
            "has_contact_form": True,
            "has_service_pages": False,
            "has_city_pages": False,
            "has_gbp_link": False,
            "nap_matches_gbp": False,
        }

    def get_prospect(self, place_id):
        return dict(self.prospect) if place_id == "place-1" else None

    def get_findings(self, place_id):
        return list(self.findings)

    def get_website_audit(self, place_id):
        return dict(self.audit)


class FakeReportRepository:
    def __init__(self):
        self.created = None

    def create_report(self, **kwargs):
        self.created = kwargs
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "place_id": kwargs["place_id"],
            "report_version": 1,
            "status": "generated",
            "title": kwargs["title"],
            "selected_signals": kwargs["selected_signals"],
            "snapshot": kwargs["snapshot"],
            "source_checked_at": kwargs["source_checked_at"],
            "created_at": datetime(2026, 9, 16, 20, 1, tzinfo=timezone.utc),
        }

    def get_report(self, report_id):
        return None

    def list_for_prospect(self, place_id):
        return []


def test_options_only_expose_allowlisted_client_safe_findings():
    service = AuditReportService(FakeProspectRepository(), FakeReportRepository())

    result = service.options_for_prospect("place-1")

    signals = [item["signal"] for item in result["options"]]
    assert signals == ["no_localbusiness_schema", "no_service_pages", "no_city_pages", "nap_mismatch"]

    schema = result["options"][0]
    assert schema["disposition"] == "recommended"
    assert schema["default_selected"] is True

    by_signal = {item["signal"]: item for item in result["options"]}

    nap = by_signal["nap_mismatch"]
    assert nap["disposition"] == "review_required"
    assert nap["default_selected"] is False
    assert "Website phone" in nap["evidence"]

    assert by_signal["no_service_pages"]["disposition"] == "recommended"
    assert by_signal["no_service_pages"]["default_selected"] is True
    assert by_signal["no_city_pages"]["disposition"] == "recommended"
    assert by_signal["no_city_pages"]["default_selected"] is True


def test_snapshot_excludes_internal_scores_and_raw_findings():
    repo = FakeReportRepository()
    service = AuditReportService(FakeProspectRepository(), repo)

    report = service.create_report(
        "place-1",
        selected_signals=["no_localbusiness_schema"],
    )

    snapshot = report["snapshot"]
    serialized = str(snapshot).lower()

    assert "total_score" not in serialized
    assert "tier" not in serialized
    assert "internal raw finding" not in serialized
    assert snapshot["report_version"] == 3
    assert snapshot["business"]["review_count"] == 87
    assert snapshot["findings"][0]["signal"] == "no_localbusiness_schema"
    assert "Homepage scan" in snapshot["findings"][0]["evidence"]
    assert repo.created["selected_signals"] == ["no_localbusiness_schema"]


def test_snapshot_includes_broad_client_safe_audit_coverage():
    service = AuditReportService(FakeProspectRepository(), FakeReportRepository())

    report = service.create_report(
        "place-1",
        selected_signals=["no_localbusiness_schema"],
    )

    snapshot = report["snapshot"]
    coverage = {item["label"]: item for item in snapshot["audit_scope"]}

    assert coverage["Website availability"]["value"] == "Reachable"
    assert coverage["Secure connection"]["value"] == "HTTPS active"
    assert coverage["Structured business data"]["status"] == "attention"
    assert coverage["Service content"]["status"] == "attention"
    assert coverage["Local landing pages"]["status"] == "attention"
    assert coverage["Contact path"]["status"] == "confirmed"
    assert coverage["Business Profile connection"]["status"] == "attention"
    assert coverage["Business contact consistency"]["status"] == "review"
    assert coverage["Primary business category"]["value"] == "Electrician"
    assert "public profile and core website signals" in snapshot["executive_summary"]
    assert "opportunity" in snapshot["executive_summary"].lower()
    assert "hidden scores" not in snapshot["executive_summary"].lower()
    assert "internal scoring" not in snapshot["methodology_note"].lower()


def test_snapshot_normalizes_database_native_values_for_jsonb():
    prospects = FakeProspectRepository()
    prospects.prospect["rating"] = Decimal("4.9")
    reports = FakeReportRepository()
    service = AuditReportService(prospects, reports)

    report = service.create_report(
        "place-1",
        selected_signals=["no_localbusiness_schema"],
    )

    snapshot = report["snapshot"]
    assert snapshot["business"]["rating"] == 4.9
    assert snapshot["source_checked_at"] == "2026-09-16T20:00:00+00:00"
    json.dumps(snapshot)


def test_review_required_finding_must_be_explicitly_selected():
    repo = FakeReportRepository()
    service = AuditReportService(FakeProspectRepository(), repo)

    report = service.create_report(
        "place-1",
        selected_signals=["nap_mismatch"],
    )

    finding = report["snapshot"]["findings"][0]
    assert finding["disposition"] == "review_required"
    assert "Website phone" in finding["evidence"]


def test_unreportable_signal_is_rejected():
    service = AuditReportService(FakeProspectRepository(), FakeReportRepository())

    try:
        service.create_report("place-1", selected_signals=["email_found"])
    except AuditReportError as exc:
        assert "not reportable" in str(exc)
    else:
        raise AssertionError("unreportable signal should be rejected")


def test_pdf_renderer_produces_two_page_outreach_report():
    service = AuditReportService(FakeProspectRepository(), FakeReportRepository())
    report = service.create_report(
        "place-1",
        selected_signals=[
            "no_localbusiness_schema",
            "no_service_pages",
            "no_city_pages",
            "nap_mismatch",
        ],
    )

    pdf = render_audit_report_pdf(report)

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 5000
    page_count = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    assert page_count == 2


def test_report_snapshot_is_detached_from_later_prospect_changes():
    prospects = FakeProspectRepository()
    reports = FakeReportRepository()
    service = AuditReportService(prospects, reports)

    report = service.create_report(
        "place-1",
        selected_signals=["no_localbusiness_schema"],
    )
    original_name = report["snapshot"]["business"]["name"]
    original_coverage = list(report["snapshot"]["audit_scope"])

    prospects.prospect["name"] = "Changed Later"
    prospects.findings[0]["finding"] = "changed later"
    prospects.audit["has_ssl"] = False

    assert report["snapshot"]["business"]["name"] == original_name
    assert report["snapshot"]["audit_scope"] == original_coverage
    assert "changed later" not in str(report["snapshot"])


def test_service_and_local_page_gaps_are_client_safe_report_opportunities():
    service = AuditReportService(FakeProspectRepository(), FakeReportRepository())

    options = service.options_for_prospect("place-1")
    by_signal = {item["signal"]: item for item in options["options"]}

    assert by_signal["no_service_pages"]["disposition"] == "recommended"
    assert by_signal["no_service_pages"]["default_selected"] is True
    assert by_signal["no_city_pages"]["disposition"] == "recommended"
    assert by_signal["no_city_pages"]["default_selected"] is True

    report = service.create_report(
        "place-1",
        selected_signals=["no_service_pages", "no_city_pages"],
    )

    findings = {
        item["signal"]: item
        for item in report["snapshot"]["findings"]
    }

    assert "service pages were not detected" in findings["no_service_pages"]["what_we_found"].lower()
    assert "service-area" in findings["no_city_pages"]["what_we_found"].lower()
    assert "website crawl" in findings["no_service_pages"]["evidence"].lower()
    assert "website crawl" in findings["no_city_pages"]["evidence"].lower()
