from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.repositories.audit_reports import AuditReportRepository
from app.repositories.prospects import ProspectRepository
from app.services.audit_report_policy import observed_summary, report_policy_for


class AuditReportError(Exception):
    pass


def _json_safe(value: Any) -> Any:
    """Convert database-native values into JSON-native snapshot values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _coverage_item(
    *,
    label: str,
    value: str,
    status: str,
    category: str,
) -> dict[str, str]:
    return {
        "label": label,
        "value": value,
        "status": status,
        "category": category,
    }


def _audit_coverage(prospect: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, str]]:
    """Build client-safe audit coverage without exposing internal scores or heuristics."""
    items: list[dict[str, str]] = []

    reachable = audit.get("is_reachable")
    if reachable is not None:
        items.append(
            _coverage_item(
                label="Website availability",
                value="Reachable" if reachable else "Not reachable when checked",
                status="confirmed" if reachable else "attention",
                category="Website",
            )
        )

    ssl = audit.get("has_ssl")
    if ssl is not None:
        items.append(
            _coverage_item(
                label="Secure connection",
                value="HTTPS active" if ssl else "HTTPS not confirmed",
                status="confirmed" if ssl else "attention",
                category="Website",
            )
        )

    title = audit.get("title")
    title_length = audit.get("title_length")
    if title is not None or title_length is not None:
        if title:
            length_note = f" · {title_length} characters" if title_length is not None else ""
            value = f"Homepage title detected{length_note}"
            status = "confirmed"
        else:
            value = "Homepage title not detected"
            status = "attention"
        items.append(
            _coverage_item(
                label="Homepage search title",
                value=value,
                status=status,
                category="Search presentation",
            )
        )

    schema = audit.get("has_localbusiness_schema")
    if schema is not None:
        items.append(
            _coverage_item(
                label="Structured business data",
                value="LocalBusiness markup detected" if schema else "LocalBusiness markup not detected",
                status="confirmed" if schema else "attention",
                category="Website",
            )
        )

    contact_form = audit.get("has_contact_form")
    if contact_form is not None:
        items.append(
            _coverage_item(
                label="Contact path",
                value="Contact form detected" if contact_form else "Contact form not detected",
                status="confirmed" if contact_form else "context",
                category="Conversion",
            )
        )

    service_pages = audit.get("has_service_pages")
    if service_pages is not None:
        items.append(
            _coverage_item(
                label="Service content",
                value="Service pages detected" if service_pages else "Service pages not detected",
                status="confirmed" if service_pages else "context",
                category="Website",
            )
        )

    city_pages = audit.get("has_city_pages")
    if city_pages is not None:
        items.append(
            _coverage_item(
                label="Local landing pages",
                value="City/local pages detected" if city_pages else "City/local pages not detected",
                status="confirmed" if city_pages else "context",
                category="Local search",
            )
        )

    gbp_link = audit.get("has_gbp_link")
    if gbp_link is not None:
        items.append(
            _coverage_item(
                label="Business Profile connection",
                value="Direct profile link detected" if gbp_link else "No direct profile link detected",
                status="confirmed" if gbp_link else "attention",
                category="Local search",
            )
        )

    nap_match = audit.get("nap_matches_gbp")
    if nap_match is not None:
        items.append(
            _coverage_item(
                label="Business contact consistency",
                value="Website information matches profile" if nap_match else "Difference detected — verify before changing",
                status="confirmed" if nap_match else "review",
                category="Local consistency",
            )
        )

    primary_type = prospect.get("primary_type")
    if primary_type:
        items.append(
            _coverage_item(
                label="Primary business category",
                value=str(primary_type).replace("_", " ").title(),
                status="context",
                category="Google Business Profile",
            )
        )

    return items


def _evidence_for_signal(
    signal: str,
    source_finding: dict[str, Any],
    prospect: dict[str, Any],
    audit: dict[str, Any],
) -> str | None:
    observed = observed_summary(signal, source_finding.get("observed"))
    if observed:
        return observed

    if signal == "no_localbusiness_schema":
        return "Homepage scan: recognized LocalBusiness structured data was not detected."
    if signal == "no_gbp_link":
        return "Website crawl: no direct Google Business Profile link was detected."
    if signal == "no_ssl":
        resolved = audit.get("resolved_url") or prospect.get("website_url")
        return f"Resolved website checked: {resolved}" if resolved else "HTTPS was not confirmed during the website check."
    if signal == "no_title":
        return "Homepage HTML check: a usable title element was not detected."

    return None


def _executive_summary(
    business_name: str,
    prospect: dict[str, Any],
    findings: list[dict[str, Any]],
    coverage: list[dict[str, str]],
) -> str:
    rating = prospect.get("rating")
    review_count = prospect.get("review_count")
    footprint = ""
    if rating is not None and review_count is not None:
        footprint = (
            f"Google currently shows {business_name} at {float(rating):.1f} stars across "
            f"{int(review_count):,} reviews. "
        )
    elif review_count is not None:
        footprint = f"Google currently shows {int(review_count):,} reviews for {business_name}. "

    checked = len(coverage)
    return (
        f"{footprint}We reviewed the business's public profile context and core website signals, "
        f"covering {checked} client-facing checks in this snapshot. "
        f"The report below focuses on {len(findings)} selected finding"
        f"{'s' if len(findings) != 1 else ''} that warrant attention or follow-up. "
        "The goal is to make the observed issues easy to verify and prioritize without relying on hidden scores or speculative ranking claims."
    )


class AuditReportService:
    def __init__(
        self,
        prospect_repository: ProspectRepository,
        report_repository: AuditReportRepository,
    ):
        self.prospect_repository = prospect_repository
        self.report_repository = report_repository

    def options_for_prospect(self, place_id: str) -> dict[str, Any]:
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise AuditReportError("prospect not found")

        findings = self.prospect_repository.get_findings(place_id)
        options: list[dict[str, Any]] = []

        for finding in findings:
            signal = finding.get("signal")
            policy = report_policy_for(signal)
            if policy is None:
                continue
            options.append(
                {
                    "signal": policy.signal,
                    "title": policy.title,
                    "category": policy.category,
                    "disposition": policy.disposition,
                    "default_selected": policy.default_selected,
                    "evidence": observed_summary(policy.signal, finding.get("observed")),
                }
            )

        return {
            "place_id": place_id,
            "business_name": prospect.get("name") or "Prospect",
            "options": options,
        }

    def create_report(self, place_id: str, *, selected_signals: list[str]) -> dict[str, Any]:
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise AuditReportError("prospect not found")

        findings = self.prospect_repository.get_findings(place_id)
        website_audit = self.prospect_repository.get_website_audit(place_id) or {}
        findings_by_signal = {
            finding.get("signal"): finding
            for finding in findings
            if finding.get("signal")
        }

        normalized_signals: list[str] = []
        report_findings: list[dict[str, Any]] = []

        for signal in selected_signals:
            if signal in normalized_signals:
                continue
            policy = report_policy_for(signal)
            source_finding = findings_by_signal.get(signal)
            if policy is None or source_finding is None:
                raise AuditReportError(f"finding is not reportable: {signal}")

            normalized_signals.append(signal)
            report_findings.append(
                {
                    "signal": policy.signal,
                    "title": policy.title,
                    "category": policy.category,
                    "disposition": policy.disposition,
                    "what_we_found": policy.what_we_found,
                    "why_it_matters": policy.why_it_matters,
                    "recommendation": policy.recommendation,
                    "evidence": _evidence_for_signal(
                        policy.signal,
                        source_finding,
                        prospect,
                        website_audit,
                    ),
                }
            )

        if not report_findings:
            raise AuditReportError("select at least one reportable finding")

        source_checked_at = website_audit.get("checked_at") or prospect.get("scored_at")
        business_name = prospect.get("name") or "Business"
        location = ", ".join(
            part for part in [prospect.get("city"), prospect.get("state")] if part
        )
        coverage = _audit_coverage(prospect, website_audit)

        snapshot = _json_safe(
            {
                "report_kind": "local_visibility_audit",
                "report_version": 2,
                "business": {
                    "name": business_name,
                    "location": location or None,
                    "website_url": prospect.get("website_url"),
                    "phone": prospect.get("phone"),
                    "rating": prospect.get("rating"),
                    "review_count": prospect.get("review_count"),
                    "last_review_days": prospect.get("last_review_days"),
                    "confirmed_trading": prospect.get("confirmed_trading"),
                    "established": prospect.get("established"),
                },
                "source_checked_at": source_checked_at,
                "executive_summary": _executive_summary(
                    business_name,
                    prospect,
                    report_findings,
                    coverage,
                ),
                "audit_scope": coverage,
                "findings": report_findings,
                "methodology_note": (
                    "This audit is a point-in-time review of public business information and technical website signals available to Lead Desk at the evidence date shown. "
                    "Selected findings are presented as observable conditions and practical review items; the report does not expose internal scoring logic and does not guarantee search placement or business performance."
                ),
            }
        )

        title = f"Local Visibility Audit — {business_name}"
        return self.report_repository.create_report(
            place_id=place_id,
            title=title,
            selected_signals=normalized_signals,
            snapshot=snapshot,
            source_checked_at=source_checked_at,
        )

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        return self.report_repository.get_report(report_id)

    def list_for_prospect(self, place_id: str) -> list[dict[str, Any]]:
        return self.report_repository.list_for_prospect(place_id)
