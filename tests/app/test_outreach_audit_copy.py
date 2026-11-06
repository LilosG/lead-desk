import base64
import email

from app.integrations.gmail import GmailDraftClient
from app.services.outreach import OutreachService
from app.services.outreach_audit_copy import audit_email_paragraph, clean_business_name


def test_keyword_stuffed_google_names_are_cleaned():
    assert clean_business_name("Waterfront Plumbing | 24/7 Emergency Plumbers in Vista") == "Waterfront Plumbing"
    assert clean_business_name("Ascend Plumbing - San Diego CA") == "Ascend Plumbing"
    assert clean_business_name("Smith Electrical Contractors, Inc.") == "Smith Electrical Contractors"
    assert clean_business_name("Repipe & Water Heaters 4 Less Inc. | San Diego") == "Repipe & Water Heaters 4 Less"
    assert clean_business_name("1st Choice Plumbing, Flood & Restoration") == "1st Choice Plumbing, Flood & Restoration"


def test_broken_profile_link_leads_and_sets_subject():
    snapshot = {"findings": [
        {"signal": "no_localbusiness_schema", "phrase": "x"},
        {"signal": "broken_profile_link", "phrase": "the website link on the Google profile"},
    ]}
    paragraph, subject = audit_email_paragraph(snapshot, "Aesthetic Assets")
    assert paragraph.startswith("The website link on Aesthetic Assets' Google listing opens an error page")
    assert "The homepage itself loads fine" in paragraph
    assert subject == "Aesthetic Assets website link on Google"


def test_single_review_count_gets_no_misleading_praise():
    snapshot = {
        "business": {"rating": 5.0, "review_count": 1},
        "market_comparison": {"market": "Scottsdale, AZ", "niche": "med spa", "median_reviews": 66},
        "findings": [{"signal": "reviews_bottom_quartile",
                      "data": {"reviews": 1, "median": 66, "market": "Scottsdale, AZ", "niche": "med spa"}}],
    }
    paragraph, _ = audit_email_paragraph(snapshot, "NMD Scottsdale Med Spa")
    assert "has 1 Google review;" in paragraph
    assert "the typical med spa in Scottsdale has about 66" in paragraph
    assert "excellent" not in paragraph and "great" not in paragraph


def test_gmail_message_carries_pdf_attachment():
    client = GmailDraftClient.__new__(GmailDraftClient)
    client.sender_email = "mike@lilosgrowth.com"
    raw = client._raw_message(
        to_address="owner@example.com", subject="Test", body="Body",
        attachments=[("Glow - Local Visibility Audit.pdf", b"%PDF-1.4 test")],
    )
    message = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    parts = [p for p in message.walk() if p.get_filename()]
    assert parts and parts[0].get_filename() == "Glow - Local Visibility Audit.pdf"
    assert parts[0].get_content_type() == "application/pdf"


class _Repo:
    def latest_audit_report(self, place_id):
        return {"id": "r1", "title": "Local Visibility Audit", "name": "Glow Med Spa | Scottsdale",
                "snapshot": {"business": {"name": "Glow Med Spa"}, "findings": [], "audit_scope": []}}


def test_audit_grounded_drafts_attach_the_report_and_others_do_not():
    service = OutreachService(_Repo())
    attached = service.audit_attachments({"claim_signal": "audit_report", "place_id": "p1"})
    assert attached and attached[0][0] == "Glow Med Spa - Local Visibility Audit.pdf"
    assert attached[0][1].startswith(b"%PDF")
    assert service.audit_attachments({"claim_signal": "no_ssl", "place_id": "p1"}) is None


def test_email_leads_with_the_local_benchmark():
    snapshot = {
        "business": {"rating": 5.0, "review_count": 11},
        "market_comparison": {"market": "Scottsdale, AZ", "niche": "med spa", "median_reviews": 64,
                              "leaders": [{"review_count": 412}]},
        "benchmarks": {"sample_size": 29, "behind": 6, "rows": [
            {"metric": "Mobile speed score", "typical": "50/100", "verdict": "behind"},
            {"metric": "Online booking", "typical": "59% offer it", "verdict": "behind"},
        ]},
        "page_gaps": {"sample_size": 29, "gaps": [{"label": "Botox & Dysport", "count": 22}]},
        "findings": [
            {"signal": "psi_mobile_critical", "data": {"psi_performance": 23, "lcp_ms": 13800}},
            {"signal": "reviews_bottom_quartile", "data": {"reviews": 11, "median": 64}},
        ],
    }
    paragraph, subject = audit_email_paragraph(snapshot, "Desert Bloom Aesthetics LLC")
    assert subject == "How Desert Bloom Aesthetics compares in Scottsdale"
    # Reviews lead now; a speed score only leads when nothing better is wrong.
    assert paragraph.startswith("Checked Desert Bloom Aesthetics against the other med spas in Scottsdale. "
                                "The biggest gap is reviews: you have 11 on Google")
    assert "I compared" not in paragraph and "/100" not in paragraph
    assert "22 of them also have their own Botox & Dysport page; your site doesn't." in paragraph
    assert "star rating is strong" not in paragraph  # one supporting fact keeps it short
    assert len(paragraph.split()) < 90


def test_niche_plurals_read_naturally():
    from app.services.outreach_audit_copy import _plural_niche
    assert _plural_niche("med spa") == "med spas"
    assert _plural_niche("real estate agent") == "real estate agents"
    assert _plural_niche("personal injury attorney") == "personal injury attorneys"
    assert _plural_niche("auto repair") == "auto repair shops"
    assert _plural_niche("tree service") == "tree service businesses"


def test_postal_address_is_optional_and_configurable():
    from app.services.outreach import _footer
    assert "Columbia" not in _footer(None)
    assert "no thanks" in _footer(None)
    assert "PO Box 123, San Diego, CA 92101" in _footer("PO Box 123,  San Diego, CA 92101")


def test_weak_finding_does_not_lead_when_competitors_have_pages_it_lacks():
    snapshot = {
        "business": {"rating": 5.0, "review_count": 40},
        "market_comparison": {"market": "Scottsdale, AZ", "niche": "med spa", "median_reviews": 64},
        "benchmarks": {"sample_size": 24, "behind": 2, "rows": [
            {"metric": "Online booking", "typical": "60% offer it", "verdict": "behind"}]},
        "page_gaps": {"sample_size": 24, "gaps": [{"label": "Weight Loss", "count": 10}]},
        "findings": [{"signal": "no_city_pages", "impact": "low", "phrase": "location pages"}],
    }
    paragraph, _ = audit_email_paragraph(snapshot, "Bloom Wellness Clinics, LLC")
    assert "location pages" not in paragraph
    assert "The clearest gap: 10 of them have their own Weight Loss page" in paragraph
    assert "60% of them also take bookings online" in paragraph


def test_greeting_uses_a_first_name_only_when_it_is_certainly_one():
    from app.services.outreach_audit_copy import contact_first_name, personal_greeting

    assert contact_first_name("corey@lcvhandyman.com") == "Corey"
    assert contact_first_name("aaron.smith@five.com") == "Aaron"
    assert contact_first_name("info@dave.com", "Dave's Electric") == "Dave"
    assert contact_first_name("info@five.com", "Five Point Electric") is None
    assert contact_first_name("jsmith@five.com") is None
    assert personal_greeting("Hi there,\n\nBody", "Corey") == "Hi Corey,\n\nBody"
    assert personal_greeting("Hello,\n\nBody", None) == "Hello,\n\nBody"


def test_published_mockup_is_offered_in_the_email():
    from app.services.outreach_audit_copy import audit_email_paragraph

    snapshot = {
        "findings": [{"signal": "no_ssl", "phrase": "x"}],
        "next_step": {"demo_url": "https://demo.lilosgrowth.com/acme/"},
    }
    paragraph, _ = audit_email_paragraph(snapshot, "Acme Plumbing")
    assert "https://demo.lilosgrowth.com/acme/" in paragraph
