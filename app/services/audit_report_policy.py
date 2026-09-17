from dataclasses import dataclass
from typing import Any, Literal


ReportDisposition = Literal["recommended", "optional", "review_required"]


@dataclass(frozen=True)
class AuditReportPolicyItem:
    signal: str
    title: str
    disposition: ReportDisposition
    default_selected: bool
    category: str
    what_we_found: str
    why_it_matters: str
    recommendation: str


POLICY: dict[str, AuditReportPolicyItem] = {
    "no_localbusiness_schema": AuditReportPolicyItem(
        signal="no_localbusiness_schema",
        title="Structured business data",
        disposition="recommended",
        default_selected=True,
        category="Website",
        what_we_found=(
            "Recognized LocalBusiness structured data was not detected on the homepage "
            "when the website was checked."
        ),
        why_it_matters=(
            "Structured business data can give search engines clearer, explicit context "
            "about the business entity represented by the website."
        ),
        recommendation=(
            "Review the site's structured data and add appropriate schema.org business "
            "markup using verified company information where appropriate."
        ),
    ),
    "no_ssl": AuditReportPolicyItem(
        signal="no_ssl",
        title="Secure website connection",
        disposition="recommended",
        default_selected=True,
        category="Website",
        what_we_found=(
            "The website did not resolve over a secure HTTPS connection when checked."
        ),
        why_it_matters=(
            "HTTPS protects visitor traffic and is a baseline trust and technical quality "
            "signal for modern websites."
        ),
        recommendation=(
            "Configure a valid TLS certificate and redirect all HTTP traffic to HTTPS."
        ),
    ),
    "no_title": AuditReportPolicyItem(
        signal="no_title",
        title="Homepage search title",
        disposition="recommended",
        default_selected=True,
        category="Website",
        what_we_found=(
            "A usable homepage title element was not detected when the page was checked."
        ),
        why_it_matters=(
            "The page title helps search engines and searchers understand the primary "
            "topic of the page."
        ),
        recommendation=(
            "Add a concise, descriptive homepage title that reflects the business and its "
            "primary service area."
        ),
    ),
    "title_length": AuditReportPolicyItem(
        signal="title_length",
        title="Homepage search title",
        disposition="optional",
        default_selected=False,
        category="Website",
        what_we_found=(
            "The homepage title is longer than the typical range used for a concise search result title."
        ),
        why_it_matters=(
            "Very long titles can be truncated in search results and can make the page's "
            "main topic less clear at a glance."
        ),
        recommendation=(
            "Review the title for clarity and remove unnecessary wording while preserving "
            "the business name, primary service, and useful local context."
        ),
    ),
    "no_gbp_link": AuditReportPolicyItem(
        signal="no_gbp_link",
        title="Website and Business Profile connection",
        disposition="optional",
        default_selected=False,
        category="Local search",
        what_we_found=(
            "A direct link from the website to the Google Business Profile was not detected during the audit."
        ),
        why_it_matters=(
            "Consistent connections between owned web properties and public business listings "
            "can make the business's online presence easier for users and systems to reconcile."
        ),
        recommendation=(
            "Consider adding a natural link to the verified Google Business Profile where it "
            "is useful for customers, such as a directions or reviews link."
        ),
    ),
    "category_generic": AuditReportPolicyItem(
        signal="category_generic",
        title="Google Business Profile primary category",
        disposition="review_required",
        default_selected=False,
        category="Google Business Profile",
        what_we_found=(
            "The primary Google Business Profile category observed during the audit may not "
            "be the most specific match for the business's primary service."
        ),
        why_it_matters=(
            "The primary category is one of the signals Google uses to understand the main "
            "type of business represented by a profile."
        ),
        recommendation=(
            "Confirm the business's primary service and review whether the current primary "
            "category is the most accurate available option."
        ),
    ),
    "nap_mismatch": AuditReportPolicyItem(
        signal="nap_mismatch",
        title="Business contact consistency",
        disposition="review_required",
        default_selected=False,
        category="Local consistency",
        what_we_found=(
            "Contact information observed on the website differs from information associated "
            "with the Google Business Profile."
        ),
        why_it_matters=(
            "Differences can be intentional, such as tracking or forwarding numbers, so the "
            "underlying business information should be confirmed before making changes."
        ),
        recommendation=(
            "Verify whether the differing contact information is intentional and confirm that "
            "the business's primary customer-facing information is consistent where appropriate."
        ),
    ),
}


def report_policy_for(signal: str | None) -> AuditReportPolicyItem | None:
    if not signal:
        return None
    return POLICY.get(signal)


def observed_summary(signal: str, observed: Any) -> str | None:
    """Return restrained evidence text without exposing internal scoring data."""
    if observed in (None, "", [], {}):
        return None

    if signal == "category_generic":
        if isinstance(observed, dict):
            value = observed.get("primary_type") or observed.get("category") or observed.get("value")
            return f"Observed primary category: {value}" if value else None
        return f"Observed primary category: {observed}"

    if signal == "nap_mismatch" and isinstance(observed, dict):
        website_phone = observed.get("website_phone") or observed.get("site_phone")
        gbp_phone = observed.get("gbp_phone") or observed.get("google_phone")
        if website_phone and gbp_phone:
            return f"Website phone: {website_phone} · Business Profile phone: {gbp_phone}"
        return None

    if signal == "title_length":
        if isinstance(observed, dict):
            value = observed.get("title_length") or observed.get("length") or observed.get("value")
        else:
            value = observed
        return f"Observed title length: {value} characters" if value is not None else None

    return None
