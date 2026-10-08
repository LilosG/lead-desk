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
    "no_service_pages": AuditReportPolicyItem(
        signal="no_service_pages",
        title="{Offering_label} coverage",
        disposition="recommended",
        default_selected=True,
        category="Search coverage",
        what_we_found=(
            "Dedicated {offering_label} were not detected during the website review."
        ),
        why_it_matters=(
            "A page for each {offering_singular} gives prospective customers and search "
            "engines clearer information, and a relevant place to land for searches about "
            "that specific {offering_singular}."
        ),
        recommendation=(
            "List the business's main offerings and give the most important ones their own "
            "substantive page."
        ),
    ),
    "no_city_pages": AuditReportPolicyItem(
        signal="no_city_pages",
        title="Local market coverage",
        disposition="recommended",
        default_selected=True,
        category="Local search",
        what_we_found=(
            "Dedicated {location_label} were not detected during the website review."
        ),
        why_it_matters=(
            "For businesses serving multiple communities, useful location pages can provide "
            "clearer geographic relevance and more specific information for customers in those markets."
        ),
        recommendation=(
            "Review the verified service territory and determine whether important markets warrant "
            "unique, substantive location pages."
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


def _item(signal, title, disposition, default_selected, category,
          what_we_found, why_it_matters, recommendation) -> AuditReportPolicyItem:
    return AuditReportPolicyItem(
        signal=signal, title=title, disposition=disposition,
        default_selected=default_selected, category=category,
        what_we_found=what_we_found, why_it_matters=why_it_matters,
        recommendation=recommendation,
    )


_REVIEW_WHY = (
    "Review volume is one of the things searchers compare when choosing between "
    "nearby businesses, and it is a visible signal of how active a business is."
)
_REVIEW_FIX = (
    "Set up a simple, consistent way to ask recent customers for a Google review, "
    "such as a short follow-up message with a direct review link."
)
_PSI_WHY = (
    "Most local searches happen on phones. Slow mobile pages lose visitors before "
    "they see the business's offer or contact details."
)
_PSI_FIX = (
    "Review the largest images, scripts and third-party widgets on the homepage, "
    "then re-test with Google PageSpeed Insights to confirm the improvement."
)

POLICY.update({
    # --- profile and reputation ---------------------------------------------
    "no_website": _item(
        "no_website", "Website link on the Google profile", "recommended", True,
        "Google Business Profile",
        "No website is linked from the Google Business Profile.",
        "Customers who find the business on Google Maps have nowhere to learn more "
        "or get in touch online, and Google has no website to connect to the listing.",
        "If the business has a website, add it to the profile. If it doesn't, a "
        "simple site with services, service area and contact details is the first step.",
    ),
    "no_reviews": _item(
        "no_reviews", "Google reviews", "recommended", True, "Reputation",
        "The Google Business Profile had no reviews when checked.",
        _REVIEW_WHY, _REVIEW_FIX,
    ),
    "reviews_bottom_quartile": _item(
        "reviews_bottom_quartile", "Review volume vs. local competitors", "recommended",
        True, "Reputation",
        "The profile has fewer Google reviews than most comparable businesses in the same market.",
        _REVIEW_WHY, _REVIEW_FIX,
    ),
    "reviews_below_median": _item(
        "reviews_below_median", "Review volume vs. local competitors", "recommended",
        True, "Reputation",
        "The profile has fewer Google reviews than the typical comparable business in the same market.",
        _REVIEW_WHY, _REVIEW_FIX,
    ),
    "no_hours": _item(
        "no_hours", "Business hours", "recommended", True, "Google Business Profile",
        "Business hours were not listed on the Google Business Profile when checked.",
        "Searchers use hours to decide whether to call or visit now, and incomplete "
        "profiles give them less reason to choose the business.",
        "Add regular hours to the profile, plus special hours for holidays.",
    ),
    "no_photos": _item(
        "no_photos", "Profile photos", "recommended", True, "Google Business Profile",
        "No photos were found on the Google Business Profile when checked.",
        "Photos help searchers judge the business at a glance before they call or click.",
        "Add recent photos of the team, work, location or products.",
    ),
    "few_photos": _item(
        "few_photos", "Profile photos", "optional", False, "Google Business Profile",
        "Only a few photos were found on the Google Business Profile when checked.",
        "Photos help searchers judge the business at a glance before they call or click.",
        "Add a fuller set of recent photos of the team, work, location or products.",
    ),
    "no_review_replies": _item(
        "no_review_replies", "Replies to reviews", "recommended", True, "Reputation",
        "None of the recent Google reviews sampled had a reply from the business.",
        "Prospective customers read owner replies as well as reviews, and replies show "
        "the business is attentive.",
        "Reply to new reviews as they come in, and work back through recent ones.",
    ),
    "few_review_replies": _item(
        "few_review_replies", "Replies to reviews", "optional", False, "Reputation",
        "Only a small share of recent Google reviews sampled had a reply from the business.",
        "Prospective customers read owner replies as well as reviews.",
        "Reply to new reviews as they come in.",
    ),
    "no_services_listed": _item(
        "no_services_listed", "Services on the Google profile", "recommended", True,
        "Google Business Profile",
        "No services were listed on the Google Business Profile when checked.",
        "Listed services describe what the business offers in its own words, directly "
        "on the profile customers see in Maps.",
        "Add each core service with a short description in plain customer language.",
    ),
    "no_business_description": _item(
        "no_business_description", "Business description", "recommended", True,
        "Google Business Profile",
        "The Google Business Profile had no business description when checked.",
        "The description is the business's own summary of what it does and where.",
        "Write a clear description covering the main services and the area served.",
    ),
    "unclaimed_profile": _item(
        "unclaimed_profile", "Profile ownership", "review_required", False,
        "Google Business Profile",
        "Public data suggested the Google Business Profile may not be claimed by the business.",
        "An unclaimed profile can't be edited, posted to, or replied from by the owner.",
        "Confirm whether the profile is verified in Google Business Profile Manager, and "
        "claim it if not.",
    ),
    # --- website -------------------------------------------------------------
    "site_down": _item(
        "site_down", "Website availability", "review_required", False, "Website",
        "The website linked from the profile did not load successfully when checked.",
        "Visitors from Google who reach an error page usually leave.",
        "Confirm the site loads from a phone and a desktop; if it doesn't, check hosting, "
        "domain renewal and SSL certificate status.",
    ),
    "psi_mobile_critical": _item(
        "psi_mobile_critical", "Mobile page speed", "recommended", True, "Website",
        "The homepage scored in the lowest range on Google PageSpeed Insights for mobile.",
        _PSI_WHY, _PSI_FIX,
    ),
    "psi_mobile_poor": _item(
        "psi_mobile_poor", "Mobile page speed", "recommended", True, "Website",
        "The homepage scored below 50 on Google PageSpeed Insights for mobile.",
        _PSI_WHY, _PSI_FIX,
    ),
    "psi_seo_low": _item(
        "psi_seo_low", "Technical SEO checks", "optional", False, "Website",
        "The homepage scored below 80 on Lighthouse's SEO checks.",
        "Lighthouse flags basic technical issues that can make a page harder for search "
        "engines to read.",
        "Run the page through PageSpeed Insights and work through the items listed under SEO.",
    ),
    "no_contact_form": _item(
        "no_contact_form", "Online contact option", "optional", False, "Conversion",
        "No contact form or online booking was detected on the pages reviewed.",
        "Some visitors won't call; a short form or booking link captures them instead.",
        "Add a short contact or booking form to the homepage and contact page.",
    ),
    "no_meta_description": _item(
        "no_meta_description", "Search result description", "optional", False, "Website",
        "The homepage had no meta description when checked.",
        "Without one, Google chooses its own snippet text for the search result.",
        "Write a concise description of the business, its main offer and its area.",
    ),
    "no_h1": _item(
        "no_h1", "Homepage main heading", "optional", False, "Website",
        "No main (H1) heading was detected on the homepage.",
        "The main heading tells visitors and search engines what the page is about.",
        "Add one clear main heading naming the business's primary offer and area.",
    ),
    "thin_content": _item(
        "thin_content", "Homepage content depth", "optional", False, "Website",
        "The homepage had relatively little text when checked.",
        "A short homepage gives visitors and search engines less to understand the "
        "business by.",
        "Expand the homepage with what the business offers, who it serves and where.",
    ),
})


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

    if signal in {"no_reviews", "reviews_bottom_quartile", "reviews_below_median"} and isinstance(observed, dict):
        median = observed.get("median")
        reviews = observed.get("reviews")
        market = observed.get("market")
        niche = observed.get("niche")
        n = observed.get("sample_size")
        if median is None or reviews is None:
            return None
        peers = f"{n} {niche} businesses" if n and niche else "comparable businesses"
        where = f" in {market}" if market else ""
        return f"{int(reviews):,} reviews vs. a median of {float(median):.0f} across {peers}{where}"

    if signal in {"psi_mobile_critical", "psi_mobile_poor"} and isinstance(observed, dict):
        score = observed.get("psi_performance")
        lcp = observed.get("lcp_ms")
        if score is None:
            return None
        text = f"Google PageSpeed Insights, mobile: {int(score)}/100"
        if lcp:
            text += f" · largest content loaded in {float(lcp) / 1000:.1f}s"
        return text

    if signal == "psi_seo_low" and isinstance(observed, dict) and observed.get("psi_seo") is not None:
        return f"Lighthouse SEO score: {int(observed['psi_seo'])}/100"

    if signal in {"no_review_replies", "few_review_replies"} and isinstance(observed, dict):
        sampled = observed.get("sampled")
        replied = observed.get("replied")
        if sampled:
            return f"{int(replied or 0)} of the last {int(sampled)} reviews sampled had an owner reply"
        return None

    if signal == "few_photos" and isinstance(observed, dict) and observed.get("photo_count") is not None:
        return f"Photos found on the profile: {int(observed['photo_count'])}"

    if signal == "thin_content" and isinstance(observed, dict) and observed.get("word_count") is not None:
        return f"About {int(observed['word_count']):,} words of text on the homepage"

    if signal == "site_down" and isinstance(observed, dict):
        status = observed.get("http_status")
        return f"Response when checked: HTTP {status}" if status else "No response when checked"

    if signal == "title_length":
        if isinstance(observed, dict):
            value = observed.get("title_length") or observed.get("length") or observed.get("value")
        else:
            value = observed
        return f"Observed title length: {value} characters" if value is not None else None

    return None
