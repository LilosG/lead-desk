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
            "vertical": "electrician",
            "market": "San Diego, CA, USA",
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
    # Ordered by impact (medium before low), then by how safe it is to include.
    assert signals == ["no_service_pages", "nap_mismatch", "no_localbusiness_schema", "no_city_pages"]

    schema = result["options"][0]
    assert schema["disposition"] == "recommended"
    assert schema["default_selected"] is True

    by_signal = {item["signal"]: item for item in result["options"]}

    nap = by_signal["nap_mismatch"]
    assert nap["disposition"] == "review_required"
    assert nap["default_selected"] is False
    assert "Website: (619) 555-0101" in nap["evidence"]

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
    assert snapshot["report_version"] == 7
    assert snapshot["business"]["review_count"] == 87
    assert snapshot["findings"][0]["signal"] == "no_localbusiness_schema"
    # No evidence line that only repeats "what we found".
    assert snapshot["findings"][0]["evidence"] is None
    assert snapshot["findings"][0]["impact"] == "low"
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
    assert "We checked" not in snapshot["executive_summary"]
    assert "4.9-star rating from 87 Google reviews" in snapshot["executive_summary"]
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
    assert "Website: (619) 555-0101" in finding["evidence"]


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
    assert page_count >= 3


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

    assert "dedicated service pages" in findings["no_service_pages"]["what_we_found"].lower()
    assert "service-area" in findings["no_city_pages"]["what_we_found"].lower()
    # No sitemap data in this fixture, so no evidence line that would only
    # repeat "what we found".
    assert findings["no_service_pages"]["evidence"] is None
    assert findings["no_city_pages"]["evidence"] is None



# --- v4: wider findings, niche wording, local comparison, next step, batch -----

class PeerProspectRepository(FakeProspectRepository):
    def __init__(self):
        super().__init__()
        self.findings = self.findings + [
            {
                "signal": "reviews_below_median",
                "observed": {"reviews": 87, "median": 140, "market": "San Diego, CA",
                             "niche": "electrician", "sample_size": 42},
                "finding": "internal",
            },
            {
                "signal": "psi_mobile_poor",
                "observed": {"psi_performance": 41, "lcp_ms": 6200},
                "finding": "internal",
            },
            {
                "signal": "title_length",
                "observed": {"title_length": 12, "title": "Home"},
                "finding": "internal",
            },
        ]

    def market_peers(self, place_id, *, vertical, market, city, limit=3):
        assert vertical == "electrician"
        assert market == "San Diego, CA, USA"
        return {
            "sample_size": 42,
            "median_reviews": 140,
            "leaders": [
                {"name": "Big Volt", "rating": 4.8, "review_count": 900, "has_website": True},
                {"name": "Amp Co", "rating": 4.7, "review_count": 610, "has_website": True},
            ],
        }


class FakeDemoRepository:
    def list_for_prospect(self, place_id):
        return [{"status": "published", "public_url": "https://demo.example/x-1/"}]


def test_review_and_speed_findings_are_reportable_with_evidence():
    service = AuditReportService(PeerProspectRepository(), FakeReportRepository())
    options = {o["signal"]: o for o in service.options_for_prospect("place-1")["options"]}

    assert options["reviews_below_median"]["default_selected"] is True
    assert "87 Google reviews; comparable electrician businesses" in options["reviews_below_median"]["evidence"]
    assert "median of 140" in options["reviews_below_median"]["evidence"]
    assert "San Diego, CA" in options["reviews_below_median"]["evidence"]
    assert options["psi_mobile_poor"]["evidence"].startswith("Google mobile speed score: 41/100")
    assert "6.2 seconds" in options["psi_mobile_poor"]["evidence"]
    # Options are ordered priority first.
    dispositions = [o["disposition"] for o in service.options_for_prospect("place-1")["options"]]
    assert dispositions.index("recommended") < dispositions.index("optional")


def test_title_length_wording_matches_the_actual_problem():
    service = AuditReportService(PeerProspectRepository(), FakeReportRepository())
    report = service.create_report("place-1", selected_signals=["title_length"])
    found = report["snapshot"]["findings"][0]["what_we_found"]
    assert "only 12 characters" in found
    assert "longer" not in found


def test_report_includes_local_comparison_and_next_step_with_demo_link():
    service = AuditReportService(
        PeerProspectRepository(), FakeReportRepository(), FakeDemoRepository()
    )
    report = service.create_report("place-1", selected_signals=["reviews_below_median"])
    snapshot = report["snapshot"]

    comparison = snapshot["market_comparison"]
    assert comparison["market"] == "San Diego, CA"
    assert comparison["median_reviews"] == 140
    assert [row["name"] for row in comparison["leaders"]] == ["Big Volt", "Amp Co"]
    assert comparison["business"]["review_count"] == 87
    assert snapshot["next_step"]["demo_url"] == "https://demo.example/x-1/"
    assert "reply" in snapshot["next_step"]["text"].lower()

    pdf = render_audit_report_pdf(report)
    assert pdf.startswith(b"%PDF")


def test_niche_wording_follows_the_prospect():
    repo = FakeProspectRepository()
    repo.prospect["vertical"] = "med_spa"
    repo.prospect["primary_type"] = "spa"
    service = AuditReportService(repo, FakeReportRepository())
    report = service.create_report("place-1", selected_signals=["no_service_pages"])
    finding = report["snapshot"]["findings"][0]
    assert finding["title"] == "No individual treatment pages"
    assert "treatment pages" in finding["what_we_found"]
    assert "service" not in finding["what_we_found"]


def test_batch_creates_default_reports_and_skips_unknowns():
    service = AuditReportService(PeerProspectRepository(), FakeReportRepository())
    results = service.create_default_reports(["place-1", "missing", "place-1"])
    assert [r["status"] for r in results] == ["created", "skipped"]
    assert results[1]["place_id"] == "missing"


def test_pdf_scorecard_reads_from_the_snapshot():
    from app.services.audit_report_pdf import _scorecard

    no_site = {
        "business": {"name": "Moxi", "website_url": None, "review_count": 9},
        "market_comparison": {"median_reviews": 66},
        "findings": [
            {"signal": "no_website", "category": "Google Business Profile", "impact": "high"},
            {"signal": "reviews_bottom_quartile", "category": "Reputation", "impact": "high"},
        ],
    }
    tiles = {t["area"]: t for t in _scorecard(no_site)}
    assert tiles["WEBSITE"]["status"] == "No website"
    assert tiles["MOBILE SPEED"]["status"] == "Not tested"
    assert tiles["REVIEWS"]["detail"] == "9 vs. 66 typical locally"
    # no_website is shown under Website, not double-counted under the profile.
    assert tiles["GOOGLE PROFILE"]["status"] == "No issues flagged"

    slow = {
        "business": {"name": "Glow", "website_url": "https://glow.example"},
        "measurements": {"mobile_speed": 92},
        "findings": [{"signal": "no_title", "category": "Website", "impact": "medium"}],
    }
    tiles = {t["area"]: t for t in _scorecard(slow)}
    assert tiles["MOBILE SPEED"]["status"] == "Fast"
    assert tiles["WEBSITE"]["status"] == "Room to improve"


def test_pdf_still_renders_older_saved_snapshots():
    legacy = {
        "title": "Local Visibility Audit",
        "snapshot": {
            "business": {"name": "Old Report Co", "location": "Austin, TX"},
            "findings": [{"signal": "no_title", "title": "Homepage search title",
                          "disposition": "recommended", "what_we_found": "x",
                          "why_it_matters": "y", "recommendation": "z"}],
            "audit_scope": [],
        },
    }
    assert render_audit_report_pdf(legacy).startswith(b"%PDF")


# --- v7: competitive benchmark, content gaps, search snippet -------------------

def _spa_peer(i, reviews, *, psi=None, booking=False, pages=3, titles=None, days=10, schema=True):
    return {
        "place_id": f"peer-{i}", "name": f"Spa {i}", "city": "Scottsdale", "rating": 4.8,
        "review_count": reviews, "has_website": True, "is_reachable": True,
        "last_review_days": days, "has_hours": True, "psi_performance": psi,
        "has_online_booking": booking, "offering_page_count": pages,
        "offering_titles": titles or [], "location_page_count": 0,
        "has_localbusiness_schema": schema,
    }


class BenchmarkRepository(FakeProspectRepository):
    def __init__(self):
        super().__init__()
        self.prospect.update({
            "name": "Glow Aesthetics LLC", "vertical": "med_spa", "city": "Scottsdale",
            "state": "AZ", "market": "Scottsdale, AZ, USA", "rating": 5.0, "review_count": 6,
            "last_review_days": 140, "has_hours": True, "phone": "(480) 555-0100",
            "website_url": "https://glow.example/",
        })
        self.audit.update({
            "is_reachable": True, "title": "Home", "meta_description": None,
            "psi_performance": 22, "has_online_booking": False, "offering_page_count": 0,
            "offering_titles": [], "has_localbusiness_schema": False,
            "resolved_url": "https://www.glow.example/",
        })

    def market_peers(self, place_id, *, vertical, market, city, limit=3):
        titles = [["Botox & Dysport", "Dermal Fillers", "HydraFacial"],
                  ["Botox", "Lip Filler", "Laser Hair Removal"],
                  ["Botox & Dysport", "Microneedling"],
                  ["Dermal Fillers", "Botox & Dysport", "Laser Hair Removal"],
                  ["HydraFacial", "Botox & Dysport"],
                  ["Weight Loss", "Botox & Dysport", "Dermal Fillers"]]
        peers = [_spa_peer(i, r, psi=p, booking=b, titles=t)
                 for i, (r, p, b, t) in enumerate(zip(
                     [66, 120, 40, 300, 80, 55], [55, 61, 48, 70, 52, 66],
                     [True, True, False, True, True, False], titles))]
        return {"sample_size": 7, "median_reviews": 66, "scope_city": "Scottsdale",
                "leaders": [], "peers": peers}


def test_report_benchmarks_against_real_local_competitors():
    service = AuditReportService(BenchmarkRepository(), FakeReportRepository())
    snapshot = service.create_report("place-1", selected_signals=["no_service_pages"])["snapshot"]

    rows = {r["metric"]: r for r in snapshot["benchmarks"]["rows"]}
    assert rows["Google reviews"]["you"] == "6"
    assert rows["Google reviews"]["note"] == "#7 of 7 nearby"
    assert rows["Google reviews"]["verdict"] == "behind"
    assert rows["Mobile speed score"]["typical"] == "58/100"
    assert rows["Online booking"]["typical"] == "67% offer it"
    assert rows["Newest Google review"]["verdict"] == "behind"
    assert rows["Treatment pages"]["verdict"] == "behind"

    gaps = [g["label"] for g in snapshot["page_gaps"]["gaps"]]
    assert gaps[0] == "Botox & Dysport"
    assert "Dermal Fillers" in gaps

    snip = snapshot["search_snippet"]
    assert snip["current_title"] == "Home"
    assert snip["suggested_title"] == "Glow Aesthetics | Med Spa in Scottsdale, AZ"
    assert snip["suggested_description"].startswith("Glow Aesthetics is a med spa in Scottsdale, AZ.")
    assert "(480) 555-0100" in snip["suggested_description"]
    # Never suggests offerings the business hasn't shown it provides.
    assert "Botox" not in snip["suggested_title"] + snip["suggested_description"]

    summary = snapshot["executive_summary"]
    assert "Compared with 6 other med spa businesses in Scottsdale, AZ, it's behind on" in summary
    assert "competitors with websites have a separate page for Botox & Dysport" in summary

    finding = snapshot["findings"][0]
    assert "Competitors nearby link separate pages for Botox & Dysport" in finding["evidence"]

    pdf = render_audit_report_pdf({"title": "x", "snapshot": snapshot})
    assert pdf.startswith(b"%PDF")


def test_location_pages_not_pitched_when_competitors_dont_have_them():
    service = AuditReportService(BenchmarkRepository(), FakeReportRepository())
    options = {o["signal"]: o for o in service.options_for_prospect("place-1")["options"]}
    assert options["no_city_pages"]["default_selected"] is False


def test_site_missing_from_google_is_reported_as_unlinked_not_missing():
    from app.services.audit_report_pdf import _scorecard
    from app.services.outreach_audit_copy import audit_email_paragraph

    repo = FakeProspectRepository()
    repo.prospect.update({"name": "AAA Goforth Plumbing & Drain Service", "website_url": None})
    repo.audit.update({"site_source": "found",
                       "resolved_url": "https://www.aaagoforthplumbinganddrainservice.com/"})
    repo.findings = [{"signal": "website_not_on_gbp",
                      "observed": {"found_url": "https://www.aaagoforthplumbinganddrainservice.com/"},
                      "finding": "internal"}]
    service = AuditReportService(repo, FakeReportRepository())
    snapshot = service.create_report("place-1", selected_signals=["website_not_on_gbp"])["snapshot"]

    assert snapshot["business"]["website_url"] == "https://www.aaagoforthplumbinganddrainservice.com/"
    assert snapshot["business"]["site_on_google"] is False
    finding = snapshot["findings"][0]
    assert finding["title"] == "Website isn't linked on the Google profile"
    assert "Website we found: https://www.aaagoforthplumbinganddrainservice.com/" in finding["evidence"]
    tiles = {t["area"]: t for t in _scorecard(snapshot)}
    assert tiles["WEBSITE"]["status"] == "Not on Google"
    paragraph, subject = audit_email_paragraph(snapshot, "AAA Goforth Plumbing & Drain Service")
    assert "doesn't link to your website" in paragraph
    assert "no website" not in paragraph.lower()
