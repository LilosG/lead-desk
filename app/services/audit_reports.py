from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.repositories.audit_reports import AuditReportRepository
from app.repositories.prospects import ProspectRepository
from app.services.audit_report_policy import (
    IMPACT_LABELS,
    IMPACT_ORDER,
    observed_summary,
    report_policy_for,
)
from app.services import audit_benchmarks
from app.services.outreach_audit_copy import clean_business_name
from pipeline import verticals as vertical_config

MAX_BATCH = 50
_DISPOSITION_ORDER = {"recommended": 0, "review_required": 1, "optional": 2}

# Public, client-safe numbers a finding may carry (used by outreach copy).
_DATA_KEYS = {
    "reviews", "median", "market", "niche", "sample_size", "psi_performance",
    "lcp_ms", "http_status", "linked_url", "photo_count", "sampled", "replied",
    "word_count", "title_length",
}


def _finding_data(observed: Any) -> dict[str, Any]:
    if not isinstance(observed, dict):
        return {}
    return {key: value for key, value in observed.items() if key in _DATA_KEYS and value is not None}


def _finding_order(item: dict[str, Any]) -> tuple[int, int]:
    return (
        IMPACT_ORDER.get(item.get("impact") or "medium", 1),
        _DISPOSITION_ORDER.get(item.get("disposition") or "optional", 9),
    )


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
    state = prospect.get("state")
    scope_city = peers.get("scope_city")
    market = prospect.get("market")
    if scope_city:
        where = ", ".join(part for part in [scope_city, state] if part)
    elif market:
        where = ", ".join(part.strip() for part in market.split(",")[:2])
    else:
        where = prospect.get("city") or "the area"
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
        "Start with the high-impact items; most can be fixed within a few weeks. If you'd "
        "like help, reply to our email and we'll walk through them with you."
    )
    if demo_url:
        text += " We also built a concept homepage to show what an updated site could look like."
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
        length = title_length if title_length is not None else len(title or "")
        if title and 20 <= length <= 65:
            value = f"Homepage title set · {length} characters"
            status = "confirmed"
        elif title:
            value = f"Homepage title is {length} characters"
            status = "attention"
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

    if signal == "no_service_pages":
        observed = source_finding.get("observed") or {}
        sitemap = observed.get("sitemap_urls") if isinstance(observed, dict) else None
        return f"We checked the homepage links and {int(sitemap)} pages listed in the site map." if sitemap else None
    if signal == "no_ssl":
        resolved = audit.get("resolved_url") or prospect.get("website_url")
        return f"Address the site loaded at: {resolved}" if resolved else None
    return None


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _executive_summary(
    business_name: str,
    prospect: dict[str, Any],
    findings: list[dict[str, Any]],
    coverage: list[dict[str, str]],
    comparison: dict[str, Any] | None = None,
    bench: dict[str, Any] | None = None,
    gaps: dict[str, Any] | None = None,
) -> str:
    rating = prospect.get("rating")
    review_count = prospect.get("review_count")
    parts: list[str] = []

    if rating is not None and review_count is not None:
        footprint = (
            f"{business_name} has a {float(rating):.1f}-star rating from "
            f"{int(review_count):,} Google review{'s' if int(review_count) != 1 else ''}"
        )
        if comparison and comparison.get("median_reviews") and not bench:
            median = int(comparison["median_reviews"])
            ahead = int(review_count) >= median
            footprint += (
                f", {'ahead of' if ahead else 'compared with'} a median of {median:,} for "
                f"comparable {comparison['niche']} businesses in {comparison['market']}"
            )
        parts.append(footprint + ".")
    elif review_count is not None:
        parts.append(f"Google shows {int(review_count):,} reviews for {business_name}.")

    if bench and comparison:
        behind = [_BENCH_PHRASES.get(r["metric"], r["metric"].lower())
                  for r in bench.get("rows") or [] if r.get("verdict") == "behind"]
        n = bench.get("sample_size")
        where = f"{n} other {comparison['niche']} businesses in {comparison['market']}"
        if behind:
            parts.append(
                f"Compared with {where}, it's behind on {len(behind)} of {len(bench['rows'])} "
                f"measures, including {_join(behind[:4])}."
            )
        else:
            parts.append(f"Compared with {where}, it's on par or ahead on every measure we compared.")
    if gaps and gaps.get("gaps"):
        top = gaps["gaps"][0]
        parts.append(
            f"{top['count']} of those {gaps['sample_size']} competitors with websites have a separate "
            f"page for {top['label']}; this site doesn't."
        )

    phrases: list[str] = []
    for item in sorted(findings, key=_finding_order):
        phrase = (item.get("phrase") or item.get("title") or "").strip()
        if phrase and phrase not in phrases:
            phrases.append(phrase)
        if len(phrases) == 3:
            break
    if phrases:
        high = sum(1 for item in findings if item.get("impact") == "high")
        if bench:
            first = [
                (item.get("phrase") or item.get("title") or "").strip()
                for item in sorted(findings, key=_finding_order)
                if item.get("impact") == "high"
            ][:2] or phrases[:1]
            parts.append(f"Start with {_join(first)}; the action plan lists everything in order.")
            return " ".join(parts)
        lead = (
            f"The biggest opportunities are {_join(phrases)}."
            if len(phrases) > 1 else f"The biggest opportunity is {phrases[0]}."
        )
        if high:
            lead += (
                f" {high} of the {len(findings)} items in this report are high impact"
                if high != len(findings) else " Each item in this report is high impact"
            ) + " and worth fixing first."
        parts.append(lead)
    else:
        parts.append("We didn't find anything that needs attention right now.")

    return " ".join(parts)


_BENCH_PHRASES = {
    "Google reviews": "review count",
    "Google rating": "star rating",
    "Newest Google review": "how recently it got a review",
    "Hours on Google": "hours on Google",
    "Mobile speed score": "mobile speed",
    "Online booking": "online booking",
    "Business details for Google (schema)": "business details for Google",
}


def _location_pages_common(peers: dict[str, Any] | None) -> bool | None:
    """Whether location pages are normal for this niche here (None = unknown)."""
    rows = [p for p in (peers or {}).get("peers") or []
            if p.get("is_reachable") and p.get("location_page_count") is not None]
    if len(rows) < audit_benchmarks.MIN_PEERS:
        return None
    return sum(1 for p in rows if (p.get("location_page_count") or 0) > 0) / len(rows) >= 0.25


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
        location_pages_common = None
        if any(f.get("signal") == "no_city_pages" for f in findings):
            location_pages_common = _location_pages_common(self._peers(prospect))

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
                    "impact": policy.impact,
                    "default_selected": (
                        policy.default_selected
                        and not (policy.signal == "no_city_pages" and location_pages_common is False)
                    ),
                    "evidence": _evidence_for_signal(
                        policy.signal, finding, prospect, {}
                    ),
                }
            )

        options.sort(key=_finding_order)
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
        site_on_google = bool(prospect.get("website_url"))
        if not site_on_google and website_audit.get("site_source") == "found":
            # Real site, just not on the Google profile: audit it as their site.
            prospect = {**prospect, "website_url": website_audit.get("resolved_url")}
        findings_by_signal = {
            finding.get("signal"): finding
            for finding in findings
            if finding.get("signal")
        }

        normalized_signals: list[str] = []
        report_findings: list[dict[str, Any]] = []
        peers = self._peers(prospect)
        peer_rows = (peers or {}).get("peers") or []
        gaps = audit_benchmarks.page_gaps(prospect, website_audit, peer_rows)

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
                    "impact": policy.impact,
                    "impact_label": IMPACT_LABELS[policy.impact],
                    "phrase": _render(policy.phrase, ctx),
                    "data": _finding_data(source_finding.get("observed")),
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

        report_findings.sort(key=_finding_order)

        source_checked_at = website_audit.get("checked_at") or prospect.get("scored_at")
        business_name = prospect.get("name") or "Business"
        location = ", ".join(
            part for part in [prospect.get("city"), prospect.get("state")] if part
        )
        if gaps:
            for item in report_findings:
                if item["signal"] == "no_service_pages":
                    named = ", ".join(g["label"] for g in gaps["gaps"][:3])
                    item["evidence"] = (
                        f"{(item.get('evidence') or '').rstrip('.')}. "
                        f"Competitors nearby link separate pages for {named}."
                    ).lstrip(". ")
        coverage = _audit_coverage(prospect, website_audit)
        comparison = market_comparison(prospect, peers)
        niche_ctx = _niche_context(prospect)
        bench = audit_benchmarks.benchmarks(
            prospect, website_audit, peer_rows, offering_label=niche_ctx["offering_label"],
        )
        snippet = audit_benchmarks.search_snippet(
            prospect, website_audit, clean_business_name(prospect.get("name")),
        )
        psi_payload = website_audit.get("raw_psi_payload") or {}
        screenshot = psi_payload.get("screenshot") if isinstance(psi_payload, dict) else None

        snapshot = _json_safe(
            {
                "report_kind": "local_visibility_audit",
                "report_version": 7,
                "business": {
                    "name": business_name,
                    "location": location or None,
                    "website_url": prospect.get("website_url"),
                    "site_on_google": site_on_google,
                    "phone": prospect.get("phone"),
                    "rating": prospect.get("rating"),
                    "review_count": prospect.get("review_count"),
                    "last_review_days": prospect.get("last_review_days"),
                    "confirmed_trading": prospect.get("confirmed_trading"),
                    "established": prospect.get("established"),
                },
                "source_checked_at": source_checked_at,
                "executive_summary": _executive_summary(
                    clean_business_name(business_name),
                    prospect,
                    report_findings,
                    coverage,
                    comparison,
                    bench,
                    gaps,
                ),
                "audit_scope": coverage,
                "measurements": {
                    "mobile_speed": website_audit.get("psi_performance"),
                    "lcp_ms": website_audit.get("psi_lcp_ms"),
                    "reachable": website_audit.get("is_reachable"),
                    "screenshot": screenshot if isinstance(screenshot, str) else None,
                },
                "benchmarks": bench,
                "page_gaps": gaps,
                "search_snippet": snippet,
                "strengths": [
                    item for item in coverage
                    if item.get("status") == "confirmed"
                ],
                "findings": report_findings,
                "market_comparison": comparison,
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
