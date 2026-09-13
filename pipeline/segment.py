"""Report the 'established and neglected' segment.

Mike's actual buyer is not the biggest gap — it's a business that demonstrably
trades (recent review activity, review count at or above the local median) whose
marketing surface is unmanaged. That combination is what review-count filtering
alone could never express.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import fields

import config as C
import scoring as S
from enrich import SiteFindings

biz = json.load(open("discovered.json"))
valid = {f.name for f in fields(SiteFindings)}
raw = json.load(open("enrichment_cache.json"))
cache = {k: SiteFindings(**{a: b for a, b in v.items() if a in valid})
         for k, v in raw.items()}

scored, baselines = S.score_all(biz, cache, C.GEO_LABEL)
by = {b["place_id"]: b for b in biz}

# Don't hardcode a vertical here — this script was written during the
# electrician pilot and a plumber sweep died on KeyError: 'electrician'. Use
# whichever verticals the sweep actually contains, weighting each business
# against its OWN trade's median rather than a single global number.
_medians = {k: v.median_reviews for k, v in baselines.items()}
if not _medians:
    raise SystemExit("no baselines — run finalize first")
med_by_vertical = _medians
med = statistics.median(list(_medians.values()))

LIVE = {"active", "steady"}
NEGLECT_SIGNALS = {
    "no_localbusiness_schema", "no_city_pages", "no_service_pages",
    "psi_mobile_critical", "psi_mobile_poor", "thin_content",
    "template_builder", "no_contact_form", "no_ssl", "no_title",
    "category_generic", "category_mismatch", "no_website", "site_down",
}

seg = []
for s in scored:
    b = by[s.place_id]
    if s.activity not in LIVE:
        continue
    _m = med_by_vertical.get(b.get("vertical"))
    _m = _m.median_reviews if hasattr(_m, "median_reviews") else (_m if _m is not None else med)
    if (b.get("review_count") or 0) < _m:
        continue
    hits = [e for e in s.evidence if e.signal in NEGLECT_SIGNALS]
    if len(hits) < 2:
        continue
    seg.append((s, b, hits))

print(f"Local median review count ({', '.join(sorted(med_by_vertical))}): {med:.0f}")
print(f"Confirmed-live businesses: {sum(1 for s in scored if s.activity in LIVE)}")
print(f"ESTABLISHED + ACTIVE + NEGLECTED: {len(seg)}\n")
print("scr T  business                        city          rev  last  gaps")
print("-" * 104)
for s, b, hits in seg[:22]:
    e = cache.get(s.place_id)
    em = (getattr(e, "emails_found", None) or [None])[0]
    print(f"{s.total_score:>3} {s.tier}  {b['name'][:30]:<32}{(b.get('city') or '')[:12]:<14}"
          f"{b.get('review_count') or 0:>4} {str(b.get('last_review_days'))+'d':>6}  "
          f"{', '.join(h.signal for h in hits[:4])}")
    print(f"      {'  ' + (em or b.get('phone') or 'no contact'):<34}"
          f"{(b.get('website_url') or 'NO WEBSITE')[:52]}")
