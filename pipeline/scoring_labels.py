"""Lead label names and gap signals shared by scoring, the API and the UI.

No imports on purpose: the FastAPI app imports this directly.
"""

# Signals that count as a real, visible marketing gap (mirrors v_lead_segments).
REAL_GAP_SIGNALS = {
    "no_localbusiness_schema", "no_city_pages", "no_service_pages",
    "psi_mobile_critical", "psi_mobile_poor", "thin_content",
    "template_builder", "no_contact_form", "no_ssl", "no_title",
    "category_generic", "category_mismatch", "no_website", "site_down", "broken_profile_link", "website_not_on_gbp",
    "no_services_listed", "no_business_description", "no_review_replies",
    "noindex_homepage", "ai_crawlers_blocked", "js_only_content",
    "no_service_city_pages", "title_missing_location",
}

# Human-readable names for every label, shared with the API and UI.
LABEL_NAMES = {
    "established": "Established",
    "trading": "Recently active",
    "strong_reviews": "Strong reviews",
    "no_website": "No website",
    "site_down": "Site or link broken",
    "site_not_on_google": "Site not on Google",
    "verify_first": "Verify first",
    "email_found": "Email found",
    "phone_only": "Phone only",
    "no_contact": "No contact found",
    "online_booking": "Online booking",
    "franchise": "Franchise",
    "no_reviews": "No reviews yet",
    "low_rating": "Rating under 4.0",
    "template_site": "Site builder",
}
