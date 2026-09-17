from typing import Any

from app.repositories.audit_reports import AuditReportRepository
from app.repositories.prospects import ProspectRepository
from app.services.audit_report_policy import observed_summary, report_policy_for


class AuditReportError(Exception):
    pass


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
        website_audit = self.prospect_repository.get_website_audit(place_id)
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
                    "evidence": observed_summary(policy.signal, source_finding.get("observed")),
                }
            )

        if not report_findings:
            raise AuditReportError("select at least one reportable finding")

        source_checked_at = (website_audit or {}).get("checked_at") or prospect.get("scored_at")
        business_name = prospect.get("name") or "Business"
        location = ", ".join(
            part for part in [prospect.get("city"), prospect.get("state")] if part
        )

        snapshot = {
            "report_kind": "local_visibility_audit",
            "report_version": 1,
            "business": {
                "name": business_name,
                "location": location or None,
                "website_url": prospect.get("website_url"),
                "rating": prospect.get("rating"),
                "review_count": prospect.get("review_count"),
                "confirmed_trading": prospect.get("confirmed_trading"),
                "established": prospect.get("established"),
            },
            "source_checked_at": source_checked_at.isoformat() if hasattr(source_checked_at, "isoformat") else source_checked_at,
            "findings": report_findings,
            "methodology_note": (
                "This report summarizes selected observations from public business information and "
                "a technical review of the business website. It is a point-in-time review, not a "
                "guarantee of search placement or business performance."
            ),
        }

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
