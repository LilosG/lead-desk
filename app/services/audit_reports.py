from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.repositories.audit_reports import AuditReportRepository
from app.repositories.prospects import ProspectRepository
from app.services.audit_report_policy import observed_summary, report_policy_for
from pipeline import verticals as vertical_config

MAX_BATCH = 50
_DISPOSITION_ORDER = {"recommended": 0, "review_required": 1, "optional": 2}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _niche_context(prospect: dict[str, Any], finding: dict[str, Any] | None = None) -> dict[str, str]:
    profile = vertical_config.niche_profile(prospect.get("vertical"))
    observed = (finding or {}).get("observed") or {}
    offering_label = (
        observed.get("label") if isinstance(observed, dict) and finding
        and finding.get("signal") == "no_service_pages" and observed.get("label")
        else profile["offering_label"]
    )
    location_label = (
        observed.get("label") if isinstance(observed, dict) and finding
        and finding.get("signal") == "no_city_pages" and observed.get("label")
        else profile["location_label"]
    )
    return {
        "offering_label": offering_label,
        "Offering_label": offering_label[:1].upper() + offering_label[1:],
        "offering_singular": profile["offering_singular"],
        "location_label": location_label,
    }


def _render(text: str, ctx: dict[str, str]) -> str:
    return text.format_map(_SafeDict(ctx)) if "{" in text else text


def _title_length_found(observed: Any) -> str | None:
    length = observed.get("title_length") if isinstance(observed, dict) else observed
    try:
        length = int(length)
    except (TypeError, ValueError):
        return None
    if length < 20:
        return (
            f"The homepage title is only {length} characters, shorter than the range "
            "typically used to describe a business and its main offer."
        )
    return (
        f"The homepage title is {length} characters, longer than the range that "
        "usually displays in full in search results."
    )


def market_comparison(
    prospect: dict[str, Any],
    peers: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Client-safe local comparison: public Google numbers only."""
    if not peers or int(peers.get("sample_size") or 0) < 3:
        return None
    leaders = [
        {
            "name": row.get("name"),
            "rating": row.get("rating"),
            "review_count": int(row.get("review_count") or 0),
            "has_website": bool(row.get("has_website")),
        }
        for row in (peers.get("leaders") or [])
        if row.get("name")
    ]
    market = prospect.get("market")
    where = (
        ", ".join(part.strip() for part in market.split(",")[:2])
        if market else (prospect.get("city") or "the area")
    )
    return {
        "market": where,
        "niche": vertical_config.vertical_label(prospect.get("vertical") or "local business"),
        "sample_size": int(peers.get("sample_size") or 0),
        "median_reviews": round(float(peers.get("median_reviews") or 0)),
        "business": {
            "name": prospect.get("name"),
            "rating": prospect.get("rating"),
            "review_count": int(prospect.get("review_count") or 0),
            "has_website": bool(prospect.get("website_url")),
        },
        "leaders": leaders,
    }


def next_step(demo_url: str | None) -> dict[str, Any]:
    text = (
        "If you'd like help with any of these, reply to the email this report came "
        "with and we'll walk through the priority items together."
    )
    if demo_url:
        text += " We also put together a concept homepage to show what an updated site could look like."
    return {"text": text, "demo_url": demo_url}


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
    booking = audit.get("has_online_booking")
    if booking:
        provider = audit.get("booking_provider")
        items.append(
            _coverage_item(
                label="Contact path",
                value=f"Online booking detected ({provider})" if provider else "Online booking detected",
                status="confirmed",
                category="Conversion",
            )
        )
    elif contact_form is not None:
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
                value=(
                    f"{_niche_context(prospect)['Offering_label']} detected"
                    if service_pages
                    else f"{_niche_context(prospect)['Offering_label']} not detected"
                ),
                status="confirmed" if service_pages else "attention",
                category="Website",
            )
        )

    city_pages = audit.get("has_city_pages")
    if city_pages is not None:
        items.append(
            _coverage_item(
                label="Local landing pages",
                value=(
                    f"{_niche_context(prospect)['location_label'].capitalize()} detected"
                    if city_pages
                    else f"{_niche_context(prospect)['location_label'].capitalize()} not detected"
                ),
                status="confirmed" if city_pages else "attention",
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
    ctx = _niche_context(prospect, source_finding)
    if signal == "no_service_pages":
        observed = source_finding.get("observed") or {}
        sitemap = observed.get("sitemap_urls") if isinstance(observed, dict) else None
        note = f" ({int(sitemap)} pages in the sitemap reviewed)" if sitemap else ""
        return f"Website crawl: dedicated {ctx['offering_label']} were not detected{note}."
    if signal == "no_city_pages":
        return f"Website crawl: dedicated {ctx['location_label']} were not detected."
    if signal == "no_website":
        return "Google Business Profile: no website field when checked."
    if signal == "no_hours":
        return "Google Business Profile: no regular hours listed when checked."
    if signal == "no_photos":
        return "Google Business Profile: no photos returned when checked."
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
        footprint = (
            f"Google currently shows {int(review_count):,} reviews for {business_name}. "
        )

    checked = len(coverage)
    finding_count = len(findings)

    labels = [
        str(item.get("title")).strip()
        for item in findings
        if item.get("title")
    ]

    if labels:
        if len(labels) == 1:
            focus = labels[0]
        elif len(labels) == 2:
            focus = f"{labels[0]} and {labels[1]}"
        else:
            focus = f"{', '.join(labels[:-1])}, and {labels[-1]}"

        opportunity_text = (
            f"The review identified {finding_count} "
            f"{'opportunity' if finding_count == 1 else 'opportunities'} worth reviewing: "
            f"{focus}."
        )
    else:
        opportunity_text = "No client-facing opportunities were selected for this report."

    return (
        f"{footprint}We reviewed the business's public profile and core website signals "
        f"across {checked} checks. {opportunity_text}"
    )


class AuditReportService:
    def __init__(
        self,
        prospect_repository: ProspectRepository,
        report_repository: AuditReportRepository,
        demo_repository: Any | None = None,
    ):
        self.prospect_repository = prospect_repository
        self.report_repository = report_repository
        self.demo_repository = demo_repository

    def _published_demo_url(self, place_id: str) -> str | None:
        if self.demo_repository is None:
            return None
        try:
            demos = self.demo_repository.list_for_prospect(place_id)
        except Exception:
            return None
        for demo in demos or []:
            if demo.get("status") == "published" and demo.get("public_url"):
                return demo["public_url"]
        return None

    def _peers(self, prospect: dict[str, Any]) -> dict[str, Any] | None:
        lookup = getattr(self.prospect_repository, "market_peers", None)
        if lookup is None:
            return None
        try:
            return lookup(
                prospect["place_id"],
                vertical=prospect.get("vertical"),
                market=prospect.get("market"),
                city=prospect.get("city"),
            )
        except Exception:
            return None

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
            ctx = _niche_context(prospect, finding)
            options.append(
                {
                    "signal": policy.signal,
                    "title": _render(policy.title, ctx),
                    "category": policy.category,
                    "disposition": policy.disposition,
                    "default_selected": policy.default_selected,
                    "evidence": _evidence_for_signal(
                        policy.signal, finding, prospect, {}
                    ),
                }
            )

        options.sort(key=lambda o: _DISPOSITION_ORDER.get(o["disposition"], 9))
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
            ctx = _niche_context(prospect, source_finding)
            what_we_found = _render(policy.what_we_found, ctx)
            if signal == "title_length":
                what_we_found = _title_length_found(source_finding.get("observed")) or what_we_found
            report_findings.append(
                {
                    "signal": policy.signal,
                    "title": _render(policy.title, ctx),
                    "category": policy.category,
                    "disposition": policy.disposition,
                    "what_we_found": what_we_found,
                    "why_it_matters": _render(policy.why_it_matters, ctx),
                    "recommendation": _render(policy.recommendation, ctx),
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

        report_findings.sort(
            key=lambda item: _DISPOSITION_ORDER.get(item["disposition"], 9)
        )

        source_checked_at = website_audit.get("checked_at") or prospect.get("scored_at")
        business_name = prospect.get("name") or "Business"
        location = ", ".join(
            part for part in [prospect.get("city"), prospect.get("state")] if part
        )
        coverage = _audit_coverage(prospect, website_audit)

        snapshot = _json_safe(
            {
                "report_kind": "local_visibility_audit",
                "report_version": 4,
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
                "strengths": [
                    item for item in coverage
                    if item.get("status") == "confirmed"
                ],
                "findings": report_findings,
                "market_comparison": market_comparison(prospect, self._peers(prospect)),
                "next_step": next_step(self._published_demo_url(place_id)),
                "methodology_note": (
                    "Point-in-time review of public business information and website signals as of the evidence date shown. "
                    "Findings should be rechecked before implementation."
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

    def create_default_reports(self, place_ids: list[str]) -> list[dict[str, Any]]:
        """One report per prospect using its default-selected findings.

        For volume: skips (rather than fails) prospects with nothing
        reportable, and reports why.
        """
        results: list[dict[str, Any]] = []
        for place_id in list(dict.fromkeys(place_ids))[:MAX_BATCH]:
            try:
                options = self.options_for_prospect(place_id)["options"]
                selected = [o["signal"] for o in options if o["default_selected"]][:12]
                if not selected:
                    results.append({"place_id": place_id, "status": "skipped",
                                    "detail": "no default findings to report"})
                    continue
                report = self.create_report(place_id, selected_signals=selected)
                results.append({"place_id": place_id, "status": "created",
                                "report_id": report["id"]})
            except AuditReportError as exc:
                results.append({"place_id": place_id, "status": "skipped",
                                "detail": str(exc)})
        return results

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        return self.report_repository.get_report(report_id)

    def list_for_prospect(self, place_id: str) -> list[dict[str, Any]]:
        return self.report_repository.list_for_prospect(place_id)
