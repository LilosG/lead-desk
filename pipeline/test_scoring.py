"""
Synthetic test — validate the scoring model ranks sensibly BEFORE spending API
calls or crawler time. Fixtures represent archetypes we expect in the wild.

The bar: the ranking has to match what a competent salesperson would pick if
they looked at these by hand. If it doesn't, the weights are wrong.
"""
from __future__ import annotations

import scoring as S
from enrich import SiteFindings


def biz(pid, name, **kw):
    d = {
        "place_id": pid, "name": name, "vertical": "electrician",
        "city": "Carlsbad", "phone": "(760) 555-0100",
        "website_url": "https://example.com", "rating": 4.6,
        "review_count": 40, "has_hours": True, "photo_count": 12,
        "types": ["electrician", "point_of_interest", "establishment"],
        "primary_type": "electrician",
        "business_status": "OPERATIONAL",
        "last_review_days": 30,
        "recent_reviews_90d": 3,
    }
    d.update(kw)
    return d


def site(pid, **kw):
    f = SiteFindings(place_id=pid)
    f.is_reachable = True
    f.has_ssl = True
    f.title = "Carlsbad Electrician | Residential & Commercial Electrical"
    f.title_length = len(f.title)
    f.meta_description = "Licensed electricians serving Carlsbad and North County."
    f.meta_desc_length = len(f.meta_description)
    f.h1_text = "Carlsbad Electrician"
    f.h1_count = 1
    f.word_count = 900
    f.has_localbusiness_schema = True
    f.has_service_pages = True
    f.has_city_pages = True
    f.has_contact_form = True
    f.contact_page_url = "https://example.com/contact"
    f.emails_found = ["info@example.com"]
    f.phones_found = ["7605550100"]
    f.nap_matches_gbp = True
    f.psi_performance = 78
    f.psi_seo = 95
    f.cms_detected = "wordpress"
    for k, v in kw.items():
        setattr(f, k, v)
    return f


# --- population: 20 average businesses so baselines are realistic ------------
population = [
    biz(f"avg{i}", f"Average Electric {i}", review_count=20 + i * 4, rating=4.4)
    for i in range(20)
]
enrichment = {b["place_id"]: site(b["place_id"]) for b in population}

# --- archetypes --------------------------------------------------------------
cases = [
    # THE dream lead: no website at all, but phone on the GBP so it's workable
    (biz("dream", "Sparks Electric", website_url=None, review_count=31,
         rating=4.8, photo_count=2),
     None,
     "no website, reachable by phone"),

    # Strong business, well-run site — should score LOW (nothing to sell)
    (biz("strong", "Wheyland Electric", review_count=120, rating=4.9,
         photo_count=40),
     site("strong", psi_performance=92),
     "well-optimized, nothing to sell"),

    # Wix site, no schema, terrible mobile — classic rebuild pitch
    (biz("wix", "Coastal Power Co", review_count=18, rating=4.2),
     site("wix", cms_detected="wix", is_template_builder=True,
          has_localbusiness_schema=False, has_city_pages=False,
          has_service_pages=False, psi_performance=22, psi_seo=61,
          word_count=180),
     "template builder, no schema, awful mobile"),

    # Site completely down
    (biz("down", "Voltage Bros", review_count=9, rating=4.0, photo_count=0),
     site("down", is_reachable=False, http_status=503, emails_found=[],
          contact_page_url=None, social_profiles={}),
     "site down, thin profile"),

    # Zero reviews, no hours, no photos — GBP disaster but has a decent site
    (biz("nogbp", "Precision Electrical", review_count=0, rating=None,
         has_hours=False, photo_count=0),
     site("nogbp"),
     "GBP neglected, site fine"),

    # Unreachable: no phone, no email, no form — stays in the list, ranked low
    (biz("unreach", "Ghost Electric", phone=None, website_url=None,
         review_count=0, has_hours=False, photo_count=0, rating=None),
     None,
     "many gaps but NO way to contact"),

    # Dormant: gaps everywhere, but nobody has reviewed it in 3 years.
    # Must rank BELOW an equivalent live business — this is the distinction
    # review-count-as-qualifier could not make.
    (biz("dormant", "Old Wire Electrical", website_url=None, review_count=4,
         rating=4.5, photo_count=1, last_review_days=1150),
     None,
     "same gaps as dream lead but DORMANT (3yr)"),

    # Live business filed under the wrong Google category — Mike's highest-value
    # fix and a 15-minute change for the prospect.
    (biz("miscat", "Reyes Electric Solutions", review_count=64, rating=4.7,
         primary_type="general_contractor", last_review_days=12),
     site("miscat"),
     "name says electric, category says contractor"),

    # Guard case: generic category BUT the name gives no evidence of our trade.
    # We must NOT claim their category is wrong — we have no idea what they do.
    (biz("nocorrob", "Reyes Solutions Group", review_count=58, rating=4.6,
         primary_type="general_contractor", last_review_days=20),
     site("nocorrob"),
     "generic category, name does NOT confirm trade"),

    # NAP mismatch + no schema, otherwise fine
    (biz("nap", "Tri-City Electric", review_count=55, rating=4.5),
     site("nap", nap_matches_gbp=False, nap_phone_on_site="7605559999",
          has_localbusiness_schema=False),
     "NAP mismatch, no schema"),
]

all_biz = population + [c[0] for c in cases]
for b, s, _ in cases:
    enrichment[b["place_id"]] = s

scored, baselines = S.score_all(all_biz, enrichment, "San Diego County")

# --- optional paid enrichment: must ADD signal, never penalise its absence ----
deep_fixture = {
    "miscat": {"services_count": 0, "services_have_descriptions": False,
               "description_present": False, "description_length": 0,
               "is_claimed": True, "reviews_sampled": 20,
               "reviews_with_owner_reply": 0, "owner_reply_rate": 0.0},
}
scored_deep, _ = S.score_all(all_biz, enrichment, "San Diego County", deep_fixture)
sd = {x.place_id: x for x in scored_deep}
s_nodeep = {x.place_id: x for x in scored}

base = S.baseline_for(baselines, "electrician", "San Diego County")
print(f"BASELINE  n={base.sample_size}  median_reviews={base.median_reviews:.0f}  "
      f"p25={base.p25_reviews:.0f}  median_rating={base.median_rating:.1f}  "
      f"with_website={base.pct_with_website:.0f}%\n")

labels = {c[0]["place_id"]: c[2] for c in cases}
by_id = {b["place_id"]: b for b in all_biz}

print(f"{'rank':<5}{'tier':<6}{'score':<7}{'gbp':<5}{'site':<6}{'reach':<7}{'activity':<11}{'name':<24}note")
print("-" * 122)
for i, s in enumerate(scored, 1):
    if s.place_id.startswith("avg"):
        continue
    b = by_id[s.place_id]
    print(f"{i:<5}{s.tier:<6}{s.total_score:<7}{s.gbp_gap_score:<5}"
          f"{str(s.website_gap_score):<6}{s.reachability_score:<7}{s.activity:<11}"
          f"{b['name'][:22]:<24}{labels.get(s.place_id,'')}")

avg_scores = [s.total_score for s in scored if s.place_id.startswith("avg")]
print(f"\n(20 average businesses scored {min(avg_scores)}-{max(avg_scores)}, "
      f"mean {sum(avg_scores)/len(avg_scores):.0f})")

print("\nHEADLINE GAPS (these become email subject lines)")
print("-" * 108)
for s in scored[:6]:
    if s.place_id.startswith("avg"):
        continue
    print(f"  [{s.tier}] {by_id[s.place_id]['name']}")
    print(f"      {s.headline_gap}")

# --- assertions: the model must satisfy these or the weights are wrong -------
print("\nSANITY CHECKS")
pos = {s.place_id: i for i, s in enumerate(scored)}
sc = {s.place_id: s for s in scored}
checks = [
    ("no-website lead beats well-optimized incumbent",
     pos["dream"] < pos["strong"]),
    ("well-optimized incumbent is NOT tier A",
     sc["strong"].tier != "A"),
    ("unreachable lead is KEPT, labelled no_contact, and ranks below the dream lead",
     "unreach" in sc and "no_contact" in sc["unreach"].labels
     and pos["dream"] < pos["unreach"]),
    ("wix/no-schema/slow site outranks the healthy incumbent",
     pos["wix"] < pos["strong"]),
    ("down site scores higher than healthy site",
     sc["down"].total_score > sc["strong"].total_score),
    ("neglected GBP with good site still surfaces",
     sc["nogbp"].total_score > sc["strong"].total_score),
    ("active no-website lead stays tier A or B", sc["dream"].tier in ("A", "B")),
    ("live business outranks an identical DORMANT one",
     pos["dream"] < pos["dormant"]),
    ("dormant listing is discounted below tier A",
     sc["dormant"].tier != "A"),
    ("wrong-category business surfaces above a healthy one",
     pos["miscat"] < pos["strong"]),
    ("category claim fires when the name confirms the trade",
     any(e.signal.startswith("category_") for e in sc["miscat"].evidence)),
    ("category claim SUPPRESSED when the name gives no corroboration",
     not any(e.signal.startswith("category_") for e in sc["nocorrob"].evidence)),
    ("deep enrichment RAISES the score of a neglected profile",
     sd["miscat"].total_score > s_nodeep["miscat"].total_score),
    ("deep enrichment emits the unanswered-reviews finding",
     any(e.signal == "no_review_replies" for e in sd["miscat"].evidence)),
    ("un-enriched leads are UNCHANGED when others are enriched",
     sd["strong"].total_score == s_nodeep["strong"].total_score),
    ("no-website lead is labelled no_website and phone_only",
     {"no_website", "phone_only"} <= set(sc["dream"].labels)),
    ("established label: trading + at/above median reviews + 2 real gaps",
     "established" in S.score_lead(
         biz("est", "Est Electric", review_count=90, last_review_days=20),
         site("est", has_localbusiness_schema=False, has_city_pages=False),
         base).labels
     and "established" not in sc["strong"].labels
     and "established" not in sc["wix"].labels),
    ("NAP mismatch is labelled verify_first",
     "verify_first" in sc["nap"].labels),
]

# --- open niche / open geo regressions ----------------------------------------
# Bot-blocked site: ranks on the profile alone, not halved by a 0 website axis.
blocked_b = biz("blocked", "Shielded Electric", review_count=3, has_hours=False, photo_count=0)
blocked_open_b = biz("blocked_open", "Open Electric", review_count=3, has_hours=False, photo_count=0)
blocked_site = SiteFindings(place_id="blocked", crawl_error="blocked_403", http_status=403)
pop2 = population + [blocked_b, blocked_open_b]
enr2 = dict(enrichment)
enr2["blocked"] = blocked_site
enr2["blocked_open"] = site("blocked_open", emails_found=[], contact_page_url=None)
sc2 = {x.place_id: x for x in S.score_all(pop2, enr2, "San Diego County")[0]}
checks.append(("bot-blocked site is NOT halved (website axis left out, not zeroed)",
               sc2["blocked"].website_gap_score is None
               and sc2["blocked"].total_score >= sc2["blocked_open"].total_score))
checks.append(("bot-blocked site is labelled verify_first",
               "verify_first" in sc2["blocked"].labels))

# Franchise: kept and labelled, priority discounted.
fr = biz("fr", "Mister Sparky of Carlsbad", website_url=None, is_franchise=True)
indep = biz("indep", "Sparky Independent", website_url=None)
sc3 = {x.place_id: x for x in S.score_all(population + [fr, indep], enrichment, "San Diego County")[0]}
checks.append(("franchise is kept, labelled, and ranked below an identical independent",
               "franchise" in sc3["fr"].labels and sc3["fr"].total_score < sc3["indep"].total_score))

# Per-market baselines: a business is compared against its OWN market.
big = [biz(f"nyc{i}", f"NYC Electric {i}", review_count=300 + i, market="New York, NY, USA")
       for i in range(10)]
small = [biz(f"tow{i}", f"Town Electric {i}", review_count=5 + i, market="Ely, NV, USA")
         for i in range(10)]
probe = biz("probe", "Probe Electric", review_count=40, market="Ely, NV, USA")
mixed = big + small + [probe]
enr4 = {b["place_id"]: site(b["place_id"]) for b in mixed}
sc4, bl4 = S.score_all(mixed, enr4)
p4 = {x.place_id: x for x in sc4}
checks.append(("40 reviews is NOT 'below median' in a small market just because NYC is in the run",
               not any(e.signal.startswith("reviews_") for e in p4["probe"].evidence)))
checks.append(("review findings name the lead's own market",
               all("Ely, NV" in e.finding for e in p4["tow0"].evidence
                   if e.signal.startswith("reviews_") or e.signal == "no_reviews")))

# Niche wording: a med spa is told about treatment pages, not "service" pages.
spa = biz("spa", "Glow Med Spa", vertical="med_spa", primary_type="spa", types=["spa"])
spa_pop = [biz(f"spa{i}", f"Spa {i}", vertical="med_spa") for i in range(10)] + [spa]
enr5 = {b["place_id"]: site(b["place_id"]) for b in spa_pop}
enr5["spa"] = site("spa", has_service_pages=False, has_city_pages=False)
p5 = {x.place_id: x for x in S.score_all(spa_pop, enr5, "Scottsdale, AZ, USA")[0]}
offer = [e for e in p5["spa"].evidence if e.signal == "no_service_pages"]
checks.append(("med spa finding talks about treatment pages",
               bool(offer) and "treatment pages" in offer[0].finding))
checks.append(("online booking counts as a contact path (no 'no contact form' claim)",
               not any(e.signal == "no_contact_form" for e in S.score_lead(
                   spa, site("spa", has_contact_form=False, contact_page_url=None,
                             has_online_booking=True, booking_provider="Vagaro"),
                   S.baseline_for(S.compute_baselines(spa_pop), "med_spa", None)).evidence)))

# --- model v3: fit AND opportunity ---------------------------------------------
# The exact pair that exposed v2: the buyer Mike wants was graded below a dead listing.
solid_site = site("solid", has_localbusiness_schema=False, has_city_pages=False,
                  psi_performance=45, has_gbp_link=False)
solid = S.score_lead(biz("solid", "Solid Electric", review_count=85, rating=4.8,
                         last_review_days=20), solid_site, base)
dead = S.score_lead(biz("dead", "Old Wire Two", website_url=None, review_count=2,
                        rating=4.5, photo_count=1, last_review_days=900), None, base)
checks.append(("established business with a weak site is tier A", solid.tier == "A"))
checks.append(("established business with a weak site outranks a dormant micro listing",
               solid.total_score > dead.total_score))
checks.append(("established business with a weak site and email is QUALIFIED",
               solid.qualification == "qualified"))
checks.append(("dormant micro listing is not qualified, and stays in the list",
               dead.qualification == "low_fit"))
checks.append(("every lead carries a reason", all(x.qualification_reasons for x in scored)))
checks.append(("healthy incumbent has high fit but nothing to pitch ranks low",
               sc["strong"].fit_score >= 80 and sc["strong"].tier in ("C", "D")))

no_email = site("noem", emails_found=[], has_localbusiness_schema=False, has_city_pages=False)
checks.append(("good fit without an email is call_first, not dropped",
               S.score_lead(biz("noem", "No Email Electric", review_count=85), no_email,
                            base).qualification == "call_first"))
checks.append(("blocked site with a good profile is verify_first, with a reason",
               S.score_lead(biz("blk", "Blocked Electric", review_count=85, photo_count=2),
                            SiteFindings(place_id="blk", crawl_error="blocked_403", http_status=403),
                            base).qualification == "verify_first"))
hand_set = S.score_lead(biz("hnd", "Linked Electric", review_count=85, photo_count=2, website_url=None),
                        SiteFindings(place_id="hnd", crawl_error="blocked_403", http_status=403,
                                     site_source="manual", resolved_url="https://linked.example"), base)
checks.append(("a blocked site linked by hand doesn't wait for another manual check",
               hand_set.qualification == "call_first"))
checks.append(("a blocked site linked by hand still reports the Google gap",
               any(e.signal == "website_not_on_gbp" for e in hand_set.evidence)))
checks.append(("franchise verdict wins over fit",
               S.score_lead(biz("frq", "Mr Rooter", review_count=200, is_franchise=True),
                            site("frq", has_localbusiness_schema=False), base).qualification == "franchise"))
# Old review sample can't sink a well-reviewed business with a working site.
quiet = S.score_lead(biz("old", "Old Sample Electric", review_count=85, last_review_days=900),
                     site("old", has_localbusiness_schema=False), base)
checks.append(("stale review sample doesn't disqualify a well-reviewed live business",
               quiet.qualification == "qualified"))

ok = True
for label, passed in checks:
    print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    ok = ok and passed
print("\n" + ("ALL CHECKS PASSED" if ok else "*** SOME CHECKS FAILED ***"))
