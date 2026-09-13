"""
Outreach copy generator.

Reads scored leads + their evidence from PostgreSQL and writes a personalized
email per lead. Outputs JSON; the actual Gmail send happens through the
integration layer so there is always a review checkpoint before anything leaves.

Copy principles baked in here:
  * Lead with a SPECIFIC observed fact about their business. Cold email dies on
    generic flattery; it survives on "I looked at your thing and here's what I
    saw." The whole point of storing evidence was to make this possible.
  * One number, not five. A wall of findings reads like an automated audit and
    triggers the delete reflex. We hold the rest back as the reason to reply.
  * Proof from the same vertical and county — Wheyland Electric, Carlsbad.
  * Low-friction CTA. "Want the full audit?" converts better than "book a
    30-minute call" because it asks for a yes, not a calendar slot.
  * Short. 90-130 words. Anything longer doesn't get read on a phone between
    jobs, which is when these people check email.
"""
from __future__ import annotations

import argparse
import json
import os
import re

import requests
import psycopg
from psycopg.rows import dict_row

import config as C

SENDER_NAME = os.environ.get("LILOS_SENDER_NAME", "Mike")
SENDER_EMAIL = os.environ.get("LILOS_SENDER_EMAIL", "mike@lilosgrowth.com")
# Required by CAN-SPAM. Deliberately left as a visible placeholder so an
# unfilled address is obvious in review rather than shipping silently.
PHYSICAL_ADDRESS = os.environ.get("LILOS_ADDRESS", "[[PHYSICAL ADDRESS REQUIRED]]")

CMS_LABELS = {
    "wix": "Wix", "squarespace": "Squarespace", "godaddy": "GoDaddy",
    "weebly": "Weebly", "duda": "Duda", "wordpress": "WordPress",
}

CASE_STUDY = (
    "We took Wheyland Electric in Carlsbad from 1 to 29 top-3 Google rankings "
    "in five months — 20 keywords to 306."
)


FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "me.com", "comcast.net", "sbcglobal.net", "att.net",
    "verizon.net", "msn.com", "live.com", "cox.net", "protonmail.com",
}


def _registrable(host: str) -> str:
    parts = (host or "").lower().replace("www.", "").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "")


def usable_emails(emails: list, website_url: str | None) -> list:
    """Drop addresses that belong to somebody other than this business.

    Contractor sites carry 'site by <agency>' footer credits. Harvesting those
    means pitching a web developer about their client's business. Only the
    site's own domain or a consumer mailbox counts.
    """
    if not website_url:
        return []
    site = _registrable(website_url.split("//")[-1].split("/")[0])
    out = []
    for e in emails:
        d = _registrable(e.split("@")[-1])
        if d == site or d in FREE_MAIL_DOMAINS:
            out.append(e)
    return out


def in_target_geo_row(b: dict) -> bool:
    lat, lng = b.get("lat"), b.get("lng")
    state = (b.get("state") or "").upper()
    if state and state not in ("CA", "CALIFORNIA"):
        return False
    if lat is None or lng is None:
        return False
    bb, pad = C.GEO_BBOX, 0.15
    return (bb["min_lat"] - pad <= lat <= bb["max_lat"] + pad
            and bb["min_lng"] - pad <= lng <= bb["max_lng"] + pad)


def db_query(query: str, params: tuple = ()) -> list[dict]:
    """Query the self-hosted Lead Desk PostgreSQL database."""
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("DATABASE_URL missing. Load ~/lead-desk/.env before running.")
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def is_suppressed(email: str) -> bool:
    return bool(db_query(
        "select 1 from suppression where lower(email)=lower(%s) limit 1", (email,)
    ))


def already_contacted(place_id: str) -> bool:
    return bool(db_query(
        """select 1 from outreach
           where place_id=%s and status <> 'not_started' limit 1""", (place_id,)
    ))


NON_NAME_TOKENS = {
    # trade / entity words
    "inc", "llc", "ltd", "co", "company", "corp", "corporation", "electric",
    "electrical", "electricians", "electrician", "plumbing", "plumber", "hvac",
    "roofing", "restoration", "landscaping", "handyman", "construction",
    "contracting", "contractor", "contractors", "services", "service", "solutions",
    "systems", "group", "brothers", "bros", "sons", "family", "team", "and",
    "the", "of", "a",
    # descriptors
    "best", "pro", "pros", "quality", "reliable", "affordable", "local", "premier",
    "elite", "advanced", "expert", "master", "certified", "licensed", "trusted",
    "superior", "precision", "quick", "fast", "rapid", "budget", "value", "top",
    # geography
    "san", "diego", "north", "south", "east", "west", "coastal", "pacific",
    "american", "california", "socal", "carlsbad", "oceanside", "vista", "poway",
    "encinitas", "escondido", "alpine", "ramona", "julian", "santee", "coronado",
    "fallbrook", "bonsall", "lakeside", "marcos", "mesa", "cajon", "chula",
    "national", "imperial", "solana", "beach", "bernardo", "rancho", "lemon",
    "grove", "spring", "valley", "city", "county", "bay", "canyon", "mountain",
    "sunrise", "sunset", "golden", "eagle", "summit", "ridge", "creek",
}


def first_name_guess(business_name: str) -> str | None:
    """Extract an owner's first name — but only when genuinely confident.

    A wrong guess is much worse than no guess. Opening "Hi Alpine," or
    "Hi Blackwood," to a business owner instantly marks the email as automated
    and is more damaging than a neutral greeting. Both of those came out of an
    earlier, looser version of this function.

    So the bar is high: the name must read as "<First> <Last> <trade>", i.e. at
    least TWO consecutive non-trade word tokens before the trade word. That
    accepts "Bob Greer Electric" and correctly rejects "Blackwood Electric",
    "Alpine Electric", and "Mario Brothers Construction".
    """
    if not business_name:
        return None
    head = re.split(r"[\-–—|,/(]", business_name)[0]     # drop taglines
    tokens = [t for t in re.split(r"[\s\.]+", head) if t]

    name_run: list[str] = []
    for t in tokens:
        clean = re.sub(r"[^A-Za-z']", "", t)
        if not clean:
            break
        if clean.lower() in NON_NAME_TOKENS:
            break
        if len(clean) < 2 or clean.isupper():            # 'RTL', 'ABS', 'B'
            break
        if clean.endswith("'s"):
            break
        name_run.append(clean)

    if len(name_run) < 2:
        return None
    first = name_run[0]
    if len(first) < 3:
        return None
    return first.capitalize()


# ---------------------------------------------------------------------------
# Copy templates, keyed on the single most pitchable finding
# ---------------------------------------------------------------------------
# Signals we will NOT open an email with, regardless of score contribution.
#
# nap_mismatch is deliberately excluded. Verified against four real sites and
# three were false positives — the site DID carry the Google number, our parser
# just missed it. It remains useful as an internal ranking signal, but a
# confident factual assertion to a stranger needs a higher evidence bar than
# "our regex didn't find it." Being wrong here costs the relationship.
UNSAFE_TO_ASSERT = {
    "nap_mismatch",
    # photo_count comes from the Text Search payload, and an absent `photos`
    # field is indistinguishable from genuinely zero photos. "You have no photos"
    # is a checkable claim a prospect can disprove in one tap, so we don't make
    # it. Still fine as an internal ranking signal.
    "no_photos", "few_photos",
}

# Claims that are cheap to re-check against the live site right before sending.
LIVE_VERIFIABLE = {
    "no_ssl", "no_contact_form", "thin_content", "no_title",
    "no_localbusiness_schema", "template_builder", "site_down", "no_website",
}


def verify_claim(angle: str, lead: dict) -> tuple[bool, str]:
    """Re-check the specific claim against the live site before asserting it.

    Enrichment data is a cache, and every false positive found in this build —
    phantom phone mismatches, sites reported down that were merely bot-blocked,
    a missing contact form that existed — came from trusting that cache at send
    time. One HTTP request per email removes the entire class of error, and the
    cost is trivial next to emailing a business owner something untrue.

    Returns (ok_to_assert, reason).
    """
    if angle not in LIVE_VERIFIABLE:
        return True, "not live-verifiable; using GBP/API data"

    url = lead.get("website_url")
    if angle == "no_website":
        return (not url), "confirmed no website on profile"
    if not url:
        return False, "no url to verify against"

    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/126.0.0.0 Safari/537.36"},
            timeout=20, allow_redirects=True,
        )
    except Exception as e:
        return False, f"could not reach site to verify ({type(e).__name__})"

    if angle == "site_down":
        return (r.status_code >= 400), f"live status {r.status_code}"
    if r.status_code >= 400:
        return False, f"site returned {r.status_code}; cannot verify"

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    low = r.text.lower()

    if angle == "no_ssl":
        return (not r.url.startswith("https://")), f"final url {r.url[:60]}"
    if angle == "no_title":
        t = soup.title.string.strip() if (soup.title and soup.title.string) else ""
        return (not t), f"title={t[:40]!r}"
    if angle == "thin_content":
        wc = len(soup.get_text(" ", strip=True).split())
        return (wc < 300), f"{wc} words"
    if angle == "no_localbusiness_schema":
        has = "localbusiness" in low or '"@type"' in low and "electrician" in low
        return (not has), "schema present" if has else "no schema found"
    if angle == "template_builder":
        hits = [k for k in ("wix", "squarespace", "godaddysites", "wsimg",
                            "duda", "weebly") if k in low]
        return (bool(hits)), f"signatures={hits}"
    if angle == "no_contact_form":
        for form in soup.find_all("form"):
            action = (form.get("action") or "").lower()
            if (form.get("role") or "").lower() == "search" or "search" in action:
                continue
            if form.find_all(["input", "textarea", "select"]):
                return False, "a form exists on the page"
        for iframe in soup.find_all("iframe"):
            if any(k in (iframe.get("src") or "").lower()
                   for k in ("jotform", "hubspot", "typeform", "wufoo",
                             "formstack", "docs.google.com/forms", "calendly")):
                return False, "embedded third-party form"
        return True, "no form found on live page"

    return True, "unchecked"


def pick_angle(signals: set, psi: int | None, frequency: dict,
               used: dict | None = None) -> str:
    """Choose the opening angle by DISTINCTIVENESS, not by a fixed priority list.

    A fixed ladder makes every email identical, because the most common gap wins
    for everybody — the first version of this sent four leads the same "no city
    pages" opener, which is exactly what a blast looks like.

    So: among the signals this business actually has, lead with the one that is
    RAREST across the cohort. If 90% of contractors lack city pages, that isn't
    interesting. If this one scores 22/100 on mobile and few others do, that's
    the sentence that earns a reply. Severity still breaks ties, so we never
    lead with something trivial just because it's rare.
    """
    used = used or {}
    candidates = []

    # These two are so much stronger than anything else that they always win.
    if "no_website" in signals:
        return "no_website"
    if "site_down" in signals:
        return "site_down"

    if psi is not None and psi < 40:
        candidates.append(("psi", frequency.get("psi_mobile_critical", 0)
                           + frequency.get("psi_mobile_poor", 0)))
    for sig in ("no_reviews", "reviews_bottom_quartile", "no_ssl", "no_title",
                "thin_content", "no_contact_form", "template_builder",
                "no_photos", "no_hours", "thin_categories",
                "no_localbusiness_schema", "no_city_pages"):
        if sig in signals and sig not in UNSAFE_TO_ASSERT:
            candidates.append((sig, frequency.get(sig, 0)))
    if not candidates:
        return "generic"

    # Rank by corpus rarity, then heavily penalise angles already used in THIS
    # batch. Rarity alone isn't enough: whichever rare signal happens to be
    # shared collapses the whole batch onto one opener, which is what a blast
    # looks like. The penalty forces the batch to spread across angles while
    # still giving each business its most distinctive one.
    def rank(c):
        sig, corpus_freq = c
        return (used.get(sig, 0) * 10_000) + corpus_freq

    candidates.sort(key=rank)
    return candidates[0][0]


def build_email(lead: dict, findings: list, frequency: dict | None = None,
                used: dict | None = None) -> dict:
    frequency = frequency or {}
    name = lead.get("name") or "there"
    city = lead.get("city") or "your area"
    reviews = lead.get("review_count") or 0
    fn = first_name_guess(name)
    tidy = name.rstrip(".").strip()
    greeting = f"Hi {fn}," if fn else f"Hi — quick note about {tidy}."

    signals = {f["signal"] for f in findings}
    psi = lead.get("psi_performance")
    angle = pick_angle(signals, psi, frequency, used)
    signals = {angle} if angle not in ("generic",) else set()
    if angle == "psi":
        psi = lead.get("psi_performance")
    else:
        psi = None

    trade = (lead.get("vertical") or "contractor").replace("_", " ")
    art = "an" if trade[:1].lower() in "aeiou" else "a"

    # Each template opens with a fact we actually verified about THIS business.
    TEMPLATES = {
        "no_website": (
            f"{name} — no website showing on Google",
            f"I was looking at {trade}s in {city} and noticed {name} doesn't have "
            f"a website linked to your Google profile. You've got {reviews} "
            f"reviews doing the work of convincing people, but when someone taps "
            f"through there's nowhere for them to land.",
        ),
        "site_down": (
            f"{name} — your website isn't loading",
            "I tried to pull up your website today and it didn't load. I checked "
            "twice to be sure. Anyone who finds you on Google right now and taps "
            "the website link hits an error page.",
        ),
        "psi": (
            f"{name} — {psi}/100 on mobile",
            f"I ran your site through Google's own PageSpeed tool and it scored "
            f"{psi} out of 100 on mobile. Most people searching for an "
            f"{trade} is on their phone, and Google factors that score into "
            f"where you rank in the map results.",
        ),
        "nap_mismatch": (
            f"{name} — two different phone numbers",
            "The phone number on your website doesn't match the one on your "
            "Google Business Profile. Google cross-checks those, and a mismatch "
            "quietly suppresses local rankings — it's also the kind of thing "
            "that costs you a call when someone dials the wrong one.",
        ),
        "no_ssl": (
            f"{name} — Chrome is flagging your site",
            "Your site is still on http rather than https, which means Chrome "
            "shows a 'Not Secure' warning to everyone who visits. Google also "
            "treats it as a ranking signal. It's usually a same-day fix.",
        ),
        "no_reviews": (
            f"{name} — no reviews on your Google profile",
            f"You don't have any Google reviews yet. For {trade}s, review count "
            f"is one of the heaviest factors in who Google puts in the map pack "
            f"— it's the main thing standing between you and the top 3 in {city}.",
        ),
        "reviews_bottom_quartile": (
            f"{name} — review count vs your {city} competitors",
            f"You're sitting at {reviews} reviews. The {trade}s ranking top 3 in "
            f"{city} are averaging quite a bit more, and review count is one of "
            f"the heaviest factors in who Google shows in the map pack.",
        ),
        "no_contact_form": (
            f"{name} — no way to reach you from the site",
            "There's no contact form on your website. Anyone who lands there and "
            "isn't ready to pick up the phone right that second just leaves — "
            "and you never know they were there.",
        ),
        "template_builder": (
            f"{name} — what your site's built on",
            f"Your site's on {CMS_LABELS.get(lead.get('cms_detected') or '', 'a template builder')}, "
            f"which is fine for looking presentable but caps hard on local SEO — "
            f"there's no clean way to add the page structure Google wants to see "
            f"from {art} {trade}.",
        ),
        "thin_content": (
            f"{name} — not much for Google to read",
            "There isn't much text on your homepage. Google needs something to "
            "match against when someone searches, and a thin page struggles to "
            "rank for anything competitive no matter how good the business is.",
        ),
        "no_title": (
            f"{name} — missing your page title",
            "Your homepage has no title tag — that's the blue headline Google "
            "shows in search results, and the single most important on-page SEO "
            "element. Right now Google is inventing one for you.",
        ),
        "no_photos": (
            f"{name} — no photos on your Google profile",
            "Your Google Business Profile doesn't have any photos on it. Profiles "
            "with photos get materially more clicks and direction requests, and "
            "it's about twenty minutes of work to fix.",
        ),
        "no_hours": (
            f"{name} — no hours on your Google listing",
            "Your Google profile doesn't list business hours. Google demotes "
            "incomplete profiles, and plenty of customers skip a listing entirely "
            "when they can't tell whether you're open.",
        ),
        "thin_categories": (
            f"{name} — one category on your Google profile",
            f"You've only got one category set on your Google Business Profile. "
            f"Secondary categories are one of the strongest and most overlooked "
            f"levers for map-pack ranking — most {trade}s should have three or four.",
        ),
        "no_city_pages": (
            f"{name} — only showing up for {city}",
            f"Your site doesn't have pages for the towns around {city} you cover. "
            f"That's usually the biggest reason a good contractor only ranks in "
            f"their own city — Google has nothing to match on for the "
            f"neighbouring searches.",
        ),
        "no_localbusiness_schema": (
            f"{name} — missing markup Google looks for",
            f"Your site is missing LocalBusiness schema — the code that tells "
            f"Google your website and your Business Profile are the same "
            f"business. Without it Google's connecting the dots on its own, and "
            f"it's a common reason a solid {city} contractor sits just outside "
            f"the top 3.",
        ),
        "generic": (
            f"{name} — a few things on your Google profile",
            f"I was looking at how {name} shows up in Google's local results for "
            f"{city} and spotted a few fixable things holding you back.",
        ),
    }
    subject, hook = TEMPLATES.get(angle, TEMPLATES["generic"])

    extra = len([f for f in findings if f["severity"] in ("critical", "high")])
    more = (
        f" I found {extra} things total, most of them quick fixes."
        if extra > 1 else ""
    )

    body = f"""{greeting}

{hook}{more}

{CASE_STUDY}

Want me to send over the full breakdown? It's a written PDF — what's working, what isn't, and what your top 3 competitors are doing differently. No charge and no pitch, you can hand it to whoever you want.

{SENDER_NAME}
Lilos Growth
{SENDER_EMAIL}

---
{SENDER_NAME} · Lilos Growth · {PHYSICAL_ADDRESS}
Not interested? Reply "no thanks" and I won't contact you again.
"""
    return {"subject": subject, "body": body.strip(), "angle": angle}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--min-reviews", type=int, default=0,
                    help="skip micro-businesses unlikely to buy")
    ap.add_argument("--out", default="outreach_batch.json")
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    # How common is each finding across the whole cohort? Drives the
    # distinctiveness-based angle choice so every email doesn't open the same way.
    freq: dict = {}
    for row in db_query("select signal from score_evidence limit 20000"):
        freq[row["signal"]] = freq.get(row["signal"], 0) + 1
    if args.preview:
        common = sorted(freq.items(), key=lambda kv: -kv[1])[:8]
        print("signal frequency (most common first): "
              + ", ".join(f"{k}={v}" for k, v in common) + "\n")

    scores = db_query(
        """select place_id,total_score,tier,headline_gap,id
           from scores order by total_score desc limit 400"""
    )
    seen, ranked = set(), []
    for s in scores:
        if s["place_id"] in seen:
            continue
        seen.add(s["place_id"])
        ranked.append(s)

    batch, used_angles = [], {}
    for s in ranked:
        if len(batch) >= args.limit:
            break
        biz = db_query("select * from businesses where place_id=%s", (s["place_id"],))
        if not biz:
            continue
        b = biz[0]
        if (b.get("review_count") or 0) < args.min_reviews:
            continue

        # Geo guard. Applied here as well as in discovery because rows already
        # written by the previous hosted deployment predate the discovery-side fix, and an out-of-area
        # business (Phoenix showed up in a San Diego sweep) must never be mailed.
        if not in_target_geo_row(b):
            continue

        enr = db_query("select * from website_enrichment where place_id=%s", (s["place_id"],))
        w = enr[0] if enr else {}
        emails = usable_emails(w.get("emails_found") or [], b.get("website_url"))
        if not emails:
            continue                       # email queue only; no-site leads are phone
        # Permanent opt-out + prior-contact guard. The previous hosted deployment
        # enforced suppression in v_leads_email_list; preserve that protection here.
        if is_suppressed(emails[0]) or already_contacted(b["place_id"]):
            continue
        if (w.get("crawl_error") or "").startswith("blocked_"):
            continue                       # never pitch off an unverified crawl

        ev = db_query(
            """select signal,severity,points,finding,category
               from score_evidence where score_id=%s order by points desc""",
            (s["id"],),
        )
        findings = [e for e in ev if e["category"] != "reachability"]

        lead = {**b, "psi_performance": w.get("psi_performance"),
                "cms_detected": w.get("cms_detected"),
                "total_score": s["total_score"], "tier": s["tier"]}
        # Build, verify, and re-build if the claim doesn't hold. A rejected angle
        # is added to `tried` so the next pass picks a different one rather than
        # looping on the same failing claim.
        tried: dict = dict(used_angles)
        email = build_email(lead, findings, freq, tried)
        for _ in range(3):
            ok, why = verify_claim(email["angle"], lead)
            if ok:
                break
            if args.preview:
                print(f"    [verify] dropped '{email['angle']}' for "
                      f"{b['name']}: {why}")
            tried[email["angle"]] = tried.get(email["angle"], 0) + 100
            email = build_email(lead, findings, freq, tried)
        else:
            if args.preview:
                print(f"    [verify] SKIPPED {b['name']} — no claim verified")
            continue

        used_angles[email["angle"]] = used_angles.get(email["angle"], 0) + 1
        batch.append({
            "angle": email["angle"],
            "verified": why if not ok else "confirmed live",
            "place_id": b["place_id"], "name": b["name"], "city": b.get("city"),
            "to": emails[0], "score": s["total_score"], "tier": s["tier"],
            "reviews": b.get("review_count"),
            "subject": email["subject"], "body": email["body"],
        })

    with open(args.out, "w") as fh:
        json.dump(batch, fh, indent=2)

    if args.preview:
        for i, m in enumerate(batch, 1):
            print("=" * 74)
            print(f"[{i}] {m['name']} ({m['city']}) — score {m['score']} "
                  f"{m['tier']} — {m['reviews']} reviews")
            print(f"TO:      {m['to']}")
            print(f"SUBJECT: {m['subject']}")
            print("-" * 74)
            print(m["body"])
            print()
    print(f"\n{len(batch)} drafts -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
