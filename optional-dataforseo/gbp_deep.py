"""
Optional deep GBP enrichment via DataForSEO.

Adds three qualifiers the official Google APIs cannot provide for a business you
don't manage:

  * whether the GBP "Services" list is filled out
  * whether the owner wrote a business description
  * whether the owner replies to reviews

Design decisions worth knowing before you touch this:

1. PAID, SO IT NEVER RUNS BY DEFAULT. Nothing in the free pipeline calls this.
   You enrich a shortlist you're about to contact, not a market you're surveying.

2. CACHED AGGRESSIVELY. Services lists and descriptions change rarely; review
   replies change slowly. Re-fetching the same profile weekly is the only way
   this gets expensive, so results are cached with a timestamp and skipped inside
   CACHE_DAYS. Month two should cost almost nothing.

3. VERIFY BEFORE TRUSTING. Run `--verify "Some Business Name"` first. It prints
   the RAW response so field paths can be confirmed against reality rather than
   against my assumptions. Four separate false-positive classes in this project
   came from trusting a field I hadn't actually looked at. Do not skip this.

4. FAILS SOFT. If the provider is down, changes its response shape, or the
   account runs out of credit, the free pipeline keeps working unchanged. Deep
   signals only ever ADD to a score; their absence is never treated as a finding.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import time
from datetime import datetime, timezone

import requests

import config as C

API_BASE = "https://api.dataforseo.com/v3"
CACHE_FILE = "gbp_deep_cache.json"
CACHE_DAYS = 30

# Roughly $1.50-$3.00 per 1,000 profiles. Deliberately using the pessimistic end
# so printed estimates are never a pleasant-surprise-in-reverse.
COST_PER_PROFILE = 0.003
COST_PER_REVIEWS_CALL = 0.003

LOGIN = os.environ.get("DATAFORSEO_LOGIN", "")
PASSWORD = os.environ.get("DATAFORSEO_PASSWORD", "")


def _auth_header() -> dict:
    if not LOGIN or not PASSWORD:
        raise RuntimeError(
            "DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD missing. "
            "Add them to the dataforseo-gbp-enrich skill credentials."
        )
    tok = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "Content-Type": "application/json"}


def _post(path: str, payload: list) -> dict:
    r = requests.post(f"{API_BASE}/{path}", headers=_auth_header(),
                      data=json.dumps(payload), timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"DataForSEO {path} HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("status_code") not in (20000, None):
        raise RuntimeError(f"DataForSEO {path} status {body.get('status_code')}: "
                           f"{body.get('status_message')}")
    return body


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE) as fh:
        return json.load(fh)


def save_cache(cache: dict) -> None:
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cache, fh, indent=1, default=str)
    os.replace(tmp, CACHE_FILE)


def is_fresh(entry: dict, days: int = CACHE_DAYS) -> bool:
    ts = entry.get("fetched_at")
    if not ts:
        return False
    try:
        got = datetime.fromisoformat(ts)
    except Exception:
        return False
    if got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - got).days < days


# ---------------------------------------------------------------------------
# Requests
#
# NOTE: the exact request shape and response field paths below follow
# DataForSEO's documented structure, but they have NOT been executed against a
# live account. Run `--verify` once after signup and correct anything that
# doesn't match. Everything is written with defensive .get() chains so a wrong
# path yields None rather than a crash — which is safer but also means a silently
# wrong path looks like "no data". That's exactly why --verify exists.
# ---------------------------------------------------------------------------
def fetch_business_info(name: str, city: str, state: str = "CA") -> dict:
    payload = [{
        "keyword": f"{name} {city} {state}".strip(),
        "location_name": f"{city},{state},United States",
        "language_code": "en",
    }]
    return _post("business_data/google/my_business_info/live", payload)


def fetch_reviews(name: str, city: str, state: str = "CA", depth: int = 20) -> dict:
    payload = [{
        "keyword": f"{name} {city} {state}".strip(),
        "location_name": f"{city},{state},United States",
        "language_code": "en",
        "depth": depth,
        "sort_by": "newest",
    }]
    return _post("business_data/google/reviews/live", payload)


def _first_item(body: dict) -> dict:
    try:
        return (body["tasks"][0]["result"][0]["items"][0]) or {}
    except Exception:
        pass
    try:
        return (body["tasks"][0]["result"][0]) or {}
    except Exception:
        return {}


def _items(body: dict) -> list:
    try:
        return body["tasks"][0]["result"][0].get("items") or []
    except Exception:
        return []


def extract(info_body: dict, reviews_body: dict | None) -> dict:
    """Pull the three qualifiers out of the raw payloads."""
    item = _first_item(info_body)

    services = item.get("services") or item.get("service_items") or []
    description = (item.get("description") or "").strip()

    out = {
        "services_count": len(services) if isinstance(services, list) else 0,
        "services_have_descriptions": False,
        "description_present": bool(description),
        "description_length": len(description),
        "is_claimed": item.get("is_claimed"),
        "category": item.get("category"),
        "total_photos": item.get("total_photos"),
        "reviews_sampled": 0,
        "reviews_with_owner_reply": 0,
        "owner_reply_rate": None,
        "newest_review_iso": None,
    }

    if isinstance(services, list):
        out["services_have_descriptions"] = any(
            (s or {}).get("snippet") or (s or {}).get("description")
            for s in services if isinstance(s, dict)
        )

    if reviews_body:
        revs = _items(reviews_body)
        out["reviews_sampled"] = len(revs)
        replied = sum(
            1 for r in revs
            if (r or {}).get("owner_answer") or (r or {}).get("original_owner_answer")
        )
        out["reviews_with_owner_reply"] = replied
        if revs:
            out["owner_reply_rate"] = round(replied / len(revs), 3)
            stamps = [r.get("timestamp") for r in revs if r.get("timestamp")]
            if stamps:
                out["newest_review_iso"] = max(stamps)

    return out


def enrich_one(b: dict, with_reviews: bool = True) -> dict:
    info = fetch_business_info(b.get("name") or "", b.get("city") or "")
    revs = None
    if with_reviews:
        try:
            revs = fetch_reviews(b.get("name") or "", b.get("city") or "")
        except Exception as e:
            print(f"    reviews lookup failed for {b.get('name')}: {e}")
    d = extract(info, revs)
    d["fetched_at"] = datetime.now(timezone.utc).isoformat()
    d["place_id"] = b["place_id"]
    d["name"] = b.get("name")
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Optional paid GBP deep enrichment")
    ap.add_argument("--verify", metavar="BUSINESS_NAME",
                    help="One lookup, printing the RAW response. Do this first.")
    ap.add_argument("--place-ids", nargs="*", help="Specific leads to enrich")
    ap.add_argument("--segment", choices=["established", "top"],
                    help="Enrich a working segment instead of naming ids")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--all", action="store_true", help="Enrich every business (costly)")
    ap.add_argument("--no-reviews", action="store_true",
                    help="Skip the reviews call (halves cost, loses reply data)")
    ap.add_argument("--max-spend", type=float, default=2.00,
                    help="Refuse to start if the estimate exceeds this")
    ap.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    ap.add_argument("--city", default="Carlsbad", help="City for --verify lookups")
    args = ap.parse_args()

    # -- verify mode: look at reality before trusting any field path ----------
    if args.verify:
        print("Raw my_business_info response:")
        info = fetch_business_info(args.verify, args.city)
        print(json.dumps(info, indent=2)[:6000])
        print("\nRaw reviews response:")
        try:
            revs = fetch_reviews(args.verify, args.city, depth=5)
            print(json.dumps(revs, indent=2)[:6000])
        except Exception as e:
            print(f"  reviews call failed: {e}")
            revs = None
        print("\nParsed by extract():")
        print(json.dumps(extract(info, revs), indent=2))
        print("\nIf any value above is None/0 but visibly present in the raw JSON,")
        print("the field path in extract() is wrong — fix it before running a batch.")
        return 0

    businesses = json.load(open("discovered.json"))
    by_id = {b["place_id"]: b for b in businesses}

    # -- choose targets ------------------------------------------------------
    if args.place_ids:
        targets = [by_id[p] for p in args.place_ids if p in by_id]
    elif args.all:
        targets = businesses
    else:
        # Default to the segment that can actually pay: recently active, at or
        # above the local median on reviews, with real gaps.
        from dataclasses import fields as _fields
        import scoring as S
        from enrich import SiteFindings
        valid = {f.name for f in _fields(SiteFindings)}
        raw = json.load(open("enrichment_cache.json"))
        cache_e = {k: SiteFindings(**{a: b for a, b in v.items() if a in valid})
                   for k, v in raw.items()}
        scored, _ = S.score_all(businesses, cache_e)
        picked = []
        for s in scored:
            b = by_id.get(s.place_id)
            if not b:
                continue
            if args.segment == "top":
                picked.append(b)
            elif "established" in s.labels or (
                "trading" in s.labels and "strong_reviews" in s.labels
            ):
                picked.append(b)
            if len(picked) >= args.limit:
                break
        targets = picked

    cache = load_cache()
    todo = [b for b in targets
            if not is_fresh(cache.get(b["place_id"], {}))][: args.limit if not args.all else None]
    skipped = len(targets) - len(todo)

    per = COST_PER_PROFILE + (0 if args.no_reviews else COST_PER_REVIEWS_CALL)
    est = len(todo) * per

    print(f"targets      {len(targets)}")
    print(f"cached fresh {skipped} (skipped, <{CACHE_DAYS}d old)")
    print(f"to fetch     {len(todo)}")
    print(f"estimate     ${est:.2f}  (${per:.4f} each)")

    if not todo:
        print("nothing to do — everything is cached")
        return 0
    if est > args.max_spend:
        print(f"\nABORTED: estimate ${est:.2f} exceeds --max-spend ${args.max_spend:.2f}")
        return 1
    if not args.yes:
        print("\nRe-run with --yes to proceed.")
        return 0

    for i, b in enumerate(todo, 1):
        try:
            cache[b["place_id"]] = enrich_one(b, with_reviews=not args.no_reviews)
            d = cache[b["place_id"]]
            print(f"  [{i}/{len(todo)}] {b.get('name')[:34]:<36}"
                  f"services={d['services_count']} desc={'y' if d['description_present'] else 'n'} "
                  f"replies={d['reviews_with_owner_reply']}/{d['reviews_sampled']}")
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {b.get('name')} FAILED: {e}")
        if i % 5 == 0:
            save_cache(cache)
        time.sleep(0.3)
    save_cache(cache)
    print(f"\ncached -> {CACHE_FILE}  |  spent ~${len(todo) * per:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
