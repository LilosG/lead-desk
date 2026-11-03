"""Client-facing wording for every finding an audit report (and email) may use.

Rules for this copy:
  * Plain English a business owner understands without an SEO glossary.
  * State only what was observed, with the number when there is one.
  * Every finding carries an impact level so the report reads as a plan
    (fix this first), not a flat list of "Priority" items.
  * `phrase` is the short noun phrase used in summaries and outreach emails.

Templates may use {offering_label}, {Offering_label}, {offering_singular} and
{location_label}; the report service fills them from the prospect's niche.
"""
from dataclasses import dataclass
from typing import Any, Literal


ReportDisposition = Literal["recommended", "optional", "review_required"]
Impact = Literal["high", "medium", "low"]

IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
IMPACT_LABELS = {"high": "High impact", "medium": "Medium impact", "low": "Quick win"}


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
    impact: Impact = "medium"
    phrase: str = ""


def _item(signal: str, title: str, *, impact: Impact, disposition: ReportDisposition,
          default: bool, category: str, phrase: str, found: str, why: str,
          fix: str) -> AuditReportPolicyItem:
    return AuditReportPolicyItem(
        signal=signal, title=title, disposition=disposition,
        default_selected=default, category=category, what_we_found=found,
        why_it_matters=why, recommendation=fix, impact=impact, phrase=phrase,
    )


_REVIEW_WHY = (
    "When people compare businesses on Google, review count is one of the first things "
    "they see. It is also one of the signals Google uses to decide which businesses to "
    "show in the map results."
)
_REVIEW_FIX = (
    "Ask every happy customer for a review, at the moment they're happiest. A short text "
    "or email with a direct review link, sent the same day, is usually enough to change "
    "the pace within a few months."
)
_SPEED_WHY = (
    "Most people searching for a local business are on a phone. When a page takes this "
    "long to appear, many of them go back to the search results and pick someone else."
)
_SPEED_FIX = (
    "Compress and resize the largest images, remove scripts and widgets the page doesn't "
    "need, and re-test in Google PageSpeed Insights. Template sites often need a lighter "
    "theme or rebuild to get into a good range."
)


POLICY: dict[str, AuditReportPolicyItem] = {item.signal: item for item in [
    # --- website availability ------------------------------------------------
    _item(
        "no_website", "No website on the Google profile",
        impact="high", disposition="recommended", default=True,
        category="Google Business Profile", phrase="a website for the Google listing",
        found="The Google profile doesn't link to a website.",
        why="People who find the business on Google Maps have nowhere to see services, "
            "photos or pricing, and Google has no website to connect to the listing.",
        fix="If there is a website, add it to the profile. If not, a simple site with "
            "{offering_label}, service area and contact details is the first step.",
    ),
    _item(
        "website_not_on_gbp", "Website isn't linked on the Google profile",
        impact="high", disposition="recommended", default=True,
        category="Google Business Profile", phrase="getting your website onto your Google listing",
        found="The business has a website, but the Google profile doesn't link to it.",
        why="People who find the business on Google Maps can't tap through to the site, "
            "and Google can't connect the site to the listing. Both cost calls.",
        fix="In Google Business Profile, open Edit profile, then Contact, and add the "
            "website address. It usually shows up within a day.",
    ),
    _item(
        "broken_profile_link", "Website link on Google leads to an error page",
        impact="high", disposition="recommended", default=True,
        category="Google Business Profile", phrase="the website link on the Google profile",
        found="The website link on the Google profile opens an error page, although the "
              "homepage itself loads.",
        why="Everyone who taps 'Website' on the Google listing lands on a dead page "
            "instead of the business's site.",
        fix="Update the website link in Google Business Profile to the working homepage "
            "(or the correct page), then tap it from a phone to confirm.",
    ),
    _item(
        "site_down", "Website didn't load",
        impact="high", disposition="review_required", default=False,
        category="Website", phrase="the website not loading",
        found="The website linked from the Google profile didn't load when we checked it.",
        why="Visitors who reach an error page almost always leave.",
        fix="Check the site from a phone and a computer. If it's down, check hosting, "
            "domain renewal and the security certificate.",
    ),
    _item(
        "psi_mobile_critical", "Very slow on phones",
        impact="high", disposition="recommended", default=True,
        category="Website", phrase="how slowly the site loads on phones",
        found="The homepage scored in the lowest range on Google's mobile speed test.",
        why=_SPEED_WHY, fix=_SPEED_FIX,
    ),
    _item(
        "psi_mobile_poor", "Slow on phones",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="mobile page speed",
        found="The homepage scored below 50 out of 100 on Google's mobile speed test.",
        why=_SPEED_WHY, fix=_SPEED_FIX,
    ),
    _item(
        "no_ssl", "Site isn't secure (no HTTPS)",
        impact="high", disposition="recommended", default=True,
        category="Website", phrase="the browser 'Not secure' warning",
        found="The website loads without HTTPS, so browsers mark it 'Not secure'.",
        why="Visitors see a security warning before they see the business, and Google "
            "treats HTTPS as a baseline for trustworthy sites.",
        fix="Install an SSL certificate (most hosts include one free) and redirect all "
            "pages to the https:// version.",
    ),
    # --- reputation -----------------------------------------------------------
    _item(
        "no_reviews", "No Google reviews yet",
        impact="high", disposition="recommended", default=True,
        category="Reputation", phrase="Google reviews",
        found="The Google profile had no reviews when we checked.",
        why=_REVIEW_WHY, fix=_REVIEW_FIX,
    ),
    _item(
        "reviews_bottom_quartile", "Far fewer reviews than local competitors",
        impact="high", disposition="recommended", default=True,
        category="Reputation", phrase="review count compared with nearby competitors",
        found="The profile has fewer Google reviews than three out of four comparable "
              "businesses in the same area.",
        why=_REVIEW_WHY, fix=_REVIEW_FIX,
    ),
    _item(
        "reviews_below_median", "Fewer reviews than the typical local competitor",
        impact="medium", disposition="recommended", default=True,
        category="Reputation", phrase="review count compared with nearby competitors",
        found="The profile has fewer Google reviews than the typical comparable business "
              "in the same area.",
        why=_REVIEW_WHY, fix=_REVIEW_FIX,
    ),
    _item(
        "no_review_replies", "Reviews aren't being answered",
        impact="medium", disposition="recommended", default=True,
        category="Reputation", phrase="replies to reviews",
        found="None of the recent Google reviews we looked at had a reply from the business.",
        why="People read the owner's replies as closely as the reviews, and replying "
            "shows Google the profile is actively managed.",
        fix="Reply to every new review within a few days, and work back through recent ones.",
    ),
    _item(
        "few_review_replies", "Most reviews aren't answered",
        impact="low", disposition="optional", default=False,
        category="Reputation", phrase="replies to reviews",
        found="Only a small share of recent Google reviews had a reply from the business.",
        why="People read the owner's replies as closely as the reviews.",
        fix="Reply to every new review within a few days.",
    ),
    # --- Google profile completeness ------------------------------------------
    _item(
        "no_hours", "No business hours on Google",
        impact="medium", disposition="recommended", default=True,
        category="Google Business Profile", phrase="the hours on the Google profile",
        found="The Google profile doesn't list business hours.",
        why="People use hours to decide whether to call now, and incomplete profiles give "
            "them a reason to pick a competitor.",
        fix="Add regular hours in Google Business Profile, plus holiday hours when they change.",
    ),
    _item(
        "no_photos", "No photos on the Google profile",
        impact="medium", disposition="recommended", default=True,
        category="Google Business Profile", phrase="photos on the Google profile",
        found="No photos were found on the Google profile.",
        why="Photos are the first thing many people look at before they call or visit.",
        fix="Add recent photos of the team, the work, the location or the products, and "
            "keep adding a few each month.",
    ),
    _item(
        "few_photos", "Only a few photos on Google",
        impact="low", disposition="optional", default=False,
        category="Google Business Profile", phrase="photos on the Google profile",
        found="Only a few photos were found on the Google profile.",
        why="Photos are the first thing many people look at before they call or visit.",
        fix="Add a fuller set of recent photos and keep adding a few each month.",
    ),
    _item(
        "no_services_listed", "No services listed on Google",
        impact="medium", disposition="recommended", default=True,
        category="Google Business Profile", phrase="the services listed on the Google profile",
        found="The Google profile has no services filled in.",
        why="The services list tells people, in the business's own words, exactly what it "
            "offers, right on the listing they see in Maps.",
        fix="Add each core {offering_singular} with a one- or two-sentence description.",
    ),
    _item(
        "no_business_description", "No business description on Google",
        impact="low", disposition="recommended", default=True,
        category="Google Business Profile", phrase="the Google profile description",
        found="The Google profile has no business description.",
        why="The description is the business's own short pitch on its listing.",
        fix="Write a clear description of what the business does, for whom and where.",
    ),
    _item(
        "unclaimed_profile", "Google profile may not be claimed",
        impact="high", disposition="review_required", default=False,
        category="Google Business Profile", phrase="ownership of the Google profile",
        found="Public data suggests the Google profile may not be claimed by the business.",
        why="An unclaimed profile can't be edited, posted to or replied from by the owner.",
        fix="Check Google Business Profile Manager and claim and verify the listing if needed.",
    ),
    _item(
        "category_generic", "Google category may be too general",
        impact="medium", disposition="review_required", default=False,
        category="Google Business Profile", phrase="the main Google category",
        found="The main Google category may not be the most specific match for what the "
              "business does.",
        why="The main category is one of the strongest signals Google uses to decide which "
            "searches a listing appears for.",
        fix="Confirm the business's main service and choose the most specific category "
            "Google offers for it.",
    ),
    # --- AI search ------------------------------------------------------------
    _item(
        "noindex_homepage", "Homepage is hidden from search engines",
        impact="high", disposition="recommended", default=True,
        category="AI search", phrase="the setting hiding your homepage from search engines",
        found="The homepage carries a 'noindex' instruction, which tells search engines to "
              "leave it out of their results.",
        why="A page with this setting can't show in Google, and it can't be used in Google's "
            "AI Overviews either. It's often left on by accident after a site launch.",
        fix="Remove the noindex tag or header, then request indexing in Google Search Console.",
    ),
    _item(
        "ai_crawlers_blocked", "AI search tools are blocked from the site",
        impact="high", disposition="recommended", default=True,
        category="AI search", phrase="the block keeping AI search tools off your site",
        found="The site's robots.txt file tells AI search crawlers not to read it.",
        why="ChatGPT, Perplexity and similar tools read websites to answer questions like "
            "'who should I call near me?'. A site they can't read "
            "can't be used as a source. Some hosts turn this block on by default.",
        fix="Update robots.txt to allow the search crawlers listed above. Blocking training-only "
            "crawlers such as GPTBot is a separate choice and doesn't affect this.",
    ),
    _item(
        "js_only_content", "Page text only appears after JavaScript runs",
        impact="high", disposition="recommended", default=True,
        category="AI search", phrase="page text that AI tools can't read",
        found="The homepage HTML contains almost no text. It's added by JavaScript in the browser.",
        why="Google can usually handle this, but many AI crawlers don't run JavaScript, so "
            "they see a nearly empty page.",
        fix="Turn on server-side rendering or pre-rendering so the text is in the HTML.",
    ),
    _item(
        "homepage_unclear", "Homepage doesn't say what you do and where",
        impact="medium", disposition="recommended", default=True,
        category="AI search", phrase="a clear opening line on your homepage",
        found="The opening of the homepage doesn't state plainly what the business does and "
              "which area it serves.",
        why="Visitors decide in seconds, and search and AI tools lean on clear, direct "
            "statements to work out what a business offers and where.",
        fix="Open the homepage with one plain sentence: what you do, for whom, and where.",
    ),
    _item(
        "no_faq_content", "No answers to common customer questions",
        impact="low", disposition="recommended", default=True,
        category="AI search", phrase="answers to common customer questions",
        found="We didn't find a questions section on the homepage.",
        why="People ask AI tools and Google full questions. Clear, honest answers on your site "
            "give them something accurate to find, and save your team the same phone calls.",
        fix="Add the 5 to 8 questions customers really ask, such as pricing, timing and "
            "service area, with short, direct answers.",
    ),
    _item(
        "no_service_schema", "Services aren't in the site's structured data",
        impact="low", disposition="optional", default=False,
        category="AI search", phrase="your services in structured data",
        found="The site's structured data doesn't list its services.",
        why="Structured data states your services in a format software reads reliably. "
            "It supports your content; it doesn't replace it.",
        fix="Add Service markup that matches what each page actually offers.",
    ),
    _item(
        "no_schema_profile_links", "Your online profiles aren't connected",
        impact="low", disposition="optional", default=False,
        category="AI search", phrase="links between your website and your other profiles",
        found="The site's structured data doesn't link to the business's other profiles.",
        why="Linking your site, Google profile and social pages helps software treat them as "
            "one business.",
        fix="Add your official profile links to the 'sameAs' field of your business markup.",
    ),
    # --- website content ------------------------------------------------------
    _item(
        "no_service_city_pages", "No pages for a service in a specific town",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="pages for your services in each town",
        found="The site has {offering_label}, but none aimed at one {offering_singular} in one town.",
        why="Searches like '{offering_singular} in [town]' are usually made by people ready to "
            "buy. A page written for that exact need is what can rank for it.",
        fix="Start with your top 3 {offering_label} in your top 3 towns. Make each page useful "
            "with real local detail; don't just swap the town name.",
    ),
    _item(
        "thin_service_pages", "Service pages are very short",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="how little your service pages say",
        found="Most of the {offering_label} we read are very short.",
        why="A short page can't answer what someone wants to know before they call, so it "
            "struggles to rank and to convert.",
        fix="Cover what's included, who it's for, how it works, typical questions, and how to "
            "get started.",
    ),
    _item(
        "service_pages_missing_location", "Service pages don't name your town",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="your town on your service pages",
        found="Most of the {offering_label} we read don't name the town in the title or main heading.",
        why="The title and main heading are the strongest on-page clues to what a page is about "
            "and who it's for.",
        fix="Add the main town to each page's title and main heading, in natural wording.",
    ),
    _item(
        "title_missing_location", "Homepage title doesn't name your town",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="your town in the homepage title",
        found="Neither the homepage title nor its main heading names the town you serve.",
        why="For a local business, this is one of the clearest signals of where it operates.",
        fix="Add your main {offering_singular} and town to the homepage title and main heading.",
    ),
    _item(
        "no_click_to_call", "Phone number isn't tappable on mobile",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="a tap-to-call phone number",
        found="The phone number on the homepage isn't a tap-to-call link.",
        why="Most local searches happen on phones. If people have to copy a number, some of "
            "them won't call.",
        fix="Make every phone number on the site a tel: link, and keep one in the mobile header.",
    ),
    _item(
        "no_analytics", "No analytics found",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="analytics on your site",
        found="We didn't find a common analytics tool on the homepage.",
        why="Without it, there's no reliable way to see where calls and leads come from.",
        fix="Install Google Analytics 4 and track calls and form submissions as conversions.",
    ),
    _item(
        "images_missing_alt", "Most images have no text description",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="text descriptions on your images",
        found="Most homepage images have no alt text.",
        why="Alt text is how screen readers and search tools understand an image.",
        fix="Add a short, accurate description to each meaningful image.",
    ),
    _item(
        "no_service_pages", "No individual {offering_label}",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="{offering_label}",
        found="We didn't find dedicated {offering_label} on the website.",
        why="A page for each {offering_singular} gives people searching for that specific "
            "{offering_singular} a page that answers them, and gives Google something to "
            "show for those searches.",
        fix="Give each important {offering_singular} its own page describing what it is, "
            "who it's for, and how to book or get a quote.",
    ),
    _item(
        "no_city_pages", "No {location_label}",
        impact="low", disposition="recommended", default=True,
        category="Website", phrase="{location_label}",
        found="We didn't find {location_label} on the website.",
        why="If the business serves several towns or neighborhoods, a useful page for each "
            "helps people searching in those places find it.",
        fix="Create a page for each main area served, with genuinely local details rather "
            "than copied text.",
    ),
    _item(
        "no_title", "Homepage has no search title",
        impact="medium", disposition="recommended", default=True,
        category="Website", phrase="the homepage's search title",
        found="The homepage doesn't have a page title, the headline Google shows in search results.",
        why="Without one, Google has to guess what to show as the business's headline in "
            "search results.",
        fix="Add a title naming the business, its main {offering_singular} and its area, "
            "in under about 60 characters.",
    ),
    _item(
        "title_length", "Homepage search title needs work",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="the homepage's search title",
        found="The homepage's search title is outside the usual length range.",
        why="Very short titles miss useful words; very long ones get cut off in results.",
        fix="Keep the business name, main {offering_singular} and area, in under about 60 characters.",
    ),
    _item(
        "no_localbusiness_schema", "Search engines can't read the business details",
        impact="low", disposition="recommended", default=True,
        category="Website", phrase="business details search engines can read",
        found="The homepage doesn't include structured business information (schema markup) "
              "that tells search engines the name, address, phone and hours.",
        why="It helps Google connect the website to the Google profile with confidence.",
        fix="Add LocalBusiness schema markup with the same name, address, phone and hours "
            "as the Google profile.",
    ),
    _item(
        "no_gbp_link", "Website doesn't link to the Google profile",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="the link from the website to the Google profile",
        found="We didn't find a link from the website to the Google profile.",
        why="A reviews or directions link makes it easy for visitors to find and leave "
            "reviews.",
        fix="Add a 'Leave us a review' or 'Get directions' link to the Google profile.",
    ),
    _item(
        "nap_mismatch", "Phone number differs between website and Google",
        impact="medium", disposition="review_required", default=False,
        category="Consistency", phrase="the phone number on the website vs. Google",
        found="The phone number on the website is different from the one on the Google profile.",
        why="Sometimes this is intentional (call tracking). If it isn't, mismatched details "
            "make the business harder for Google to trust and for customers to reach.",
        fix="Confirm which number is right and make it consistent, unless the difference "
            "is a deliberate tracking number.",
    ),
    _item(
        "no_contact_form", "No online contact or booking option",
        impact="medium", disposition="optional", default=False,
        category="Website", phrase="an online contact or booking option",
        found="We didn't find a contact form or online booking on the pages we checked.",
        why="Many people won't call, especially after hours; a short form or booking link "
            "catches them.",
        fix="Add a short contact or booking form to the homepage and contact page.",
    ),
    _item(
        "psi_seo_low", "Basic technical SEO issues",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="basic technical SEO",
        found="The homepage scored below 80 out of 100 on Google Lighthouse's SEO checks.",
        why="Lighthouse flags basic issues that make a page harder for search engines to read.",
        fix="Run the page through PageSpeed Insights and work through the SEO section.",
    ),
    _item(
        "no_meta_description", "No search result description",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="the search result description",
        found="The homepage has no meta description, the short summary shown under the "
              "title in search results.",
        why="Without one, Google picks its own snippet, which is often less persuasive.",
        fix="Write a one- or two-sentence description of the business and its area.",
    ),
    _item(
        "no_h1", "Homepage has no main heading",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="the homepage's main heading",
        found="The homepage has no main (H1) heading.",
        why="The main heading tells visitors and search engines what the page is about.",
        fix="Add one clear main heading naming the main {offering_singular} and area.",
    ),
    _item(
        "thin_content", "Very little text on the homepage",
        impact="low", disposition="optional", default=False,
        category="Website", phrase="the amount of text on the homepage",
        found="The homepage has relatively little text.",
        why="A thin homepage gives visitors and search engines less to understand the "
            "business by.",
        fix="Explain what the business offers, who it serves, where, and why to choose it.",
    ),
]}


def report_policy_for(signal: str | None) -> AuditReportPolicyItem | None:
    if not signal:
        return None
    return POLICY.get(signal)


def _num(value: Any) -> str:
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value)


def observed_summary(signal: str, observed: Any) -> str | None:
    """Evidence with the actual numbers. Never internal scores."""
    if observed in (None, "", [], {}):
        return None

    if signal == "category_generic":
        if isinstance(observed, dict):
            value = observed.get("primary_type") or observed.get("category") or observed.get("value")
            value = str(value).replace("_", " ") if value else None
            return f"Main Google category: {value}" if value else None
        return f"Main Google category: {observed}"

    if signal == "nap_mismatch" and isinstance(observed, dict):
        website_phone = observed.get("website_phone") or observed.get("site_phone")
        gbp_phone = observed.get("gbp_phone") or observed.get("google_phone")
        if website_phone and gbp_phone:
            return f"Website: {website_phone}. Google profile: {gbp_phone}."
        return None

    if signal in {"no_reviews", "reviews_bottom_quartile", "reviews_below_median"} and isinstance(observed, dict):
        median = observed.get("median")
        reviews = observed.get("reviews")
        if median is None or reviews is None:
            return None
        market = observed.get("market")
        niche = observed.get("niche")
        where = f" in {market}" if market and market != "the area" else " nearby"
        peers = f"{niche} businesses" if niche else "comparable businesses"
        return f"{_num(reviews)} Google reviews; comparable {peers}{where} have a median of {_num(median)}."

    if signal in {"psi_mobile_critical", "psi_mobile_poor"} and isinstance(observed, dict):
        score = observed.get("psi_performance")
        lcp = observed.get("lcp_ms")
        if score is None:
            return None
        text = f"Google mobile speed score: {int(score)}/100"
        if lcp:
            text += f". Main content took {float(lcp) / 1000:.1f} seconds to appear on a phone"
        return text + "."

    if signal == "psi_seo_low" and isinstance(observed, dict) and observed.get("psi_seo") is not None:
        return f"Lighthouse SEO score: {int(observed['psi_seo'])}/100."

    if signal in {"no_review_replies", "few_review_replies"} and isinstance(observed, dict):
        sampled = observed.get("sampled")
        replied = observed.get("replied")
        if sampled:
            return f"{int(replied or 0)} of the last {int(sampled)} reviews we looked at had an owner reply."
        return None

    if signal == "few_photos" and isinstance(observed, dict) and observed.get("photo_count") is not None:
        return f"Photos found on the profile: {int(observed['photo_count'])}."

    if signal == "thin_content" and isinstance(observed, dict) and observed.get("word_count") is not None:
        return f"About {_num(observed['word_count'])} words of text on the homepage."

    if signal == "site_down" and isinstance(observed, dict):
        status = observed.get("http_status")
        return f"Error {status} when we loaded it." if status else "No response when we loaded it."

    if signal == "website_not_on_gbp" and isinstance(observed, dict) and observed.get("found_url"):
        return f"Website we found: {observed['found_url']}. Website on the Google profile: none."

    if signal == "broken_profile_link" and isinstance(observed, dict):
        linked = observed.get("linked_url")
        status = observed.get("http_status")
        if linked:
            return f"Link on Google: {linked} (error {status})." if status else f"Link on Google: {linked}."
        return None

    if signal == "ai_crawlers_blocked" and isinstance(observed, dict) and observed.get("blocked"):
        return f"Blocked in robots.txt: {', '.join(observed['blocked'])}."

    if signal == "no_service_city_pages" and isinstance(observed, dict) and observed.get("offering_pages"):
        return f"Service pages found: {_num(observed['offering_pages'])}. Pages for a service in a specific town: 0."

    if signal == "thin_service_pages" and isinstance(observed, dict) and observed.get("sampled"):
        return f"{_num(observed.get('thin'))} of the {_num(observed['sampled'])} pages we read have under 200 words."

    if signal == "service_pages_missing_location" and isinstance(observed, dict) and observed.get("sampled"):
        return f"{_num(observed.get('unlocated'))} of the {_num(observed['sampled'])} pages we read don't name the town."

    if signal == "images_missing_alt" and isinstance(observed, dict) and observed.get("images"):
        return f"{_num(observed.get('missing'))} of {_num(observed['images'])} homepage images have no alt text."

    if signal == "title_length":
        if isinstance(observed, dict):
            value = observed.get("title_length") or observed.get("length") or observed.get("value")
        else:
            value = observed
        return f"Current title length: {value} characters." if value is not None else None

    return None
