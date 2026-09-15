"""
Discovery — sweep Google Places (New) Text Search across a geo grid.

Key design point: we pull Enterprise-tier fields *in the search call*, so each
billable request returns up to 20 fully-detailed businesses. Place Details is
NOT called during the sweep; it's reserved as a targeted fallback.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Iterator

import requests

import config as C


# ---------------------------------------------------------------------------
# Geo grid
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GridPoint:
    lat: float
    lng: float
    radius_m: int


def build_grid(bbox: dict, spacing_km: float) -> list[GridPoint]:
    """Tile a bounding box into search points.

    Longitude degrees shrink as you move away from the equator, so we scale by
    cos(latitude). Skipping this is a classic bug that makes cells too wide at
    high latitudes and quietly leaves gaps in coverage.
    """
    km_per_deg_lat = 110.574
    lat_step = spacing_km / km_per_deg_lat

    points: list[GridPoint] = []
    lat = bbox["min_lat"]
    while lat <= bbox["max_lat"]:
        km_per_deg_lng = 111.320 * math.cos(math.radians(lat))
        lng_step = spacing_km / km_per_deg_lng

        lng = bbox["min_lng"]
        while lng <= bbox["max_lng"]:
            # Circle radius that comfortably covers a square cell (half-diagonal),
            # so adjacent circles overlap rather than leaving diamond-shaped holes.
            radius_m = int((spacing_km * 1000 * math.sqrt(2)) / 2)
            points.append(GridPoint(round(lat, 6), round(lng, 6), radius_m))
            lng += lng_step
        lat += lat_step
    return points


# ---------------------------------------------------------------------------
# Cost accounting
# ---------------------------------------------------------------------------
@dataclass
class CostLedger:
    search_calls: int = 0
    details_calls: int = 0
    psi_calls: int = 0

    def est_usd(self) -> float:
        return (
            self.search_calls  / 1000 * C.COST_PER_1K["text_search_enterprise"]
            + self.details_calls / 1000 * C.COST_PER_1K["place_details_enterprise"]
        )

    def est_usd_after_free_tier(self) -> float:
        """Free tier is per-SKU per-month and does not roll over."""
        billable_search  = max(0, self.search_calls  - C.FREE_TIER_MONTHLY["enterprise"])
        billable_details = max(0, self.details_calls - C.FREE_TIER_MONTHLY["enterprise"])
        return (
            billable_search  / 1000 * C.COST_PER_1K["text_search_enterprise"]
            + billable_details / 1000 * C.COST_PER_1K["place_details_enterprise"]
        )

    def summary(self) -> str:
        return (
            f"search={self.search_calls} details={self.details_calls} psi={self.psi_calls} "
            f"| gross=${self.est_usd():.2f} after_free_tier=${self.est_usd_after_free_tier():.2f}"
        )


# ---------------------------------------------------------------------------
# Places client
# ---------------------------------------------------------------------------
class PlacesClient:
    def __init__(self, api_key: str, ledger: CostLedger, dry_run: bool = False):
        if not api_key and not dry_run:
            raise RuntimeError("GOOGLE_API_KEY missing. Run via RunWithCredentials.")
        self.api_key = api_key
        self.ledger = ledger
        self.dry_run = dry_run
        self.session = requests.Session()

    def _post(self, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": C.SEARCH_FIELD_MASK,
        }
        backoff = 1.0
        for attempt in range(5):
            r = self.session.post(
                C.PLACES_SEARCH_URL, headers=headers, json=payload, timeout=30
            )
            if r.status_code == 200:
                return r.json()
            # Google's exact QPS ceiling isn't published, so back off rather
            # than assume we're under it.
            if r.status_code in (429, 503):
                time.sleep(backoff)
                backoff *= 2
                continue
            raise RuntimeError(f"Places API {r.status_code}: {r.text[:400]}")
        raise RuntimeError("Places API: exhausted retries after rate limiting")

    def text_search(
        self, query: str, point: GridPoint | None = None, max_pages: int | None = None
    ) -> Iterator[dict]:
        """Yield raw place dicts for a query, following pagination up to the cap.

        CRITICAL: paging requests must REPEAT every parameter from the initial
        request alongside pageToken. Sending pageToken alone returns
        HTTP 400 "Request parameters for paging requests must match the initial
        SearchText request", which truncated every 20+ result query at 20 for
        every sweep before 2026-08-13. Verified empirically; do not "simplify"
        the paging payload back to pageToken-only.
        """
        max_pages = max_pages or C.MAX_PAGES_PER_QUERY
        base_payload: dict = {"textQuery": query, "pageSize": C.RESULTS_PER_PAGE}
        if point:
            base_payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": point.lat, "longitude": point.lng},
                    "radius": float(point.radius_m),
                }
            }
        payload = dict(base_payload)

        for page in range(max_pages):
            if self.dry_run:
                self.ledger.search_calls += 1
                return
            data = self._post(payload)
            self.ledger.search_calls += 1

            places = data.get("places", [])
            for p in places:
                yield p

            token = data.get("nextPageToken")
            # Each page is a separate billable request, so only paginate when the
            # page came back full — a partial page means there's nothing more.
            if not token or len(places) < C.RESULTS_PER_PAGE:
                return
            # Repeat the original parameters, not just the token.
            payload = dict(base_payload, pageToken=token)
            time.sleep(0.6)  # nextPageToken needs a beat to become valid


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _component(place: dict, ctype: str, short: bool = False) -> str | None:
    for comp in place.get("addressComponents", []) or []:
        if ctype in (comp.get("types") or []):
            return comp.get("shortText") if short else comp.get("longText")
    return None


def is_chain(name: str) -> bool:
    low = (name or "").lower()
    return any(pat in low for pat in C.CHAIN_NAME_PATTERNS)


def in_target_geo(rec: dict) -> bool:
    """Reject results outside the target area.

    Text Search is a semantic matcher, not a geofence: querying "electrician in
    Alpine, CA" happily returned Alpine Electric of Ahwatukee, PHOENIX — a
    company 350 miles away that matched on name rather than location. The
    locationBias is a hint, not a constraint. So we verify coordinates against
    the bounding box ourselves and drop anything outside it.
    """
    lat, lng = rec.get("lat"), rec.get("lng")
    if lat is None or lng is None:
        return False                      # unplaceable -> not usable as a local lead
    bb = C.GEO_BBOX
    pad = 0.15                            # ~16km grace at the county edges
    if not (bb["min_lat"] - pad <= lat <= bb["max_lat"] + pad):
        return False
    if not (bb["min_lng"] - pad <= lng <= bb["max_lng"] + pad):
        return False
    state = (rec.get("state") or "").upper()
    if state and state not in ("CA", "CALIFORNIA"):
        return False
    return True


# Types that mean "this is a different business entirely", not "this is our
# trade filed under the wrong label". Pacific Auto Electric (car_repair) and
# Manzanita Supply (hardware_store) both matched an electrician query — they are
# noise, not mis-categorized prospects, and pitching them wastes everyone's time.
FOREIGN_TYPES = {
    "car_repair", "car_dealer", "hardware_store", "home_improvement_store",
    "electronics_store", "home_goods_store", "plumbing_supply_store", "school", "lawyer", "insurance_agency", "real_estate_agency",
    "restaurant", "lodging", "gym", "storage", "moving_company",
}


def wrong_vertical(rec: dict, vertical: str) -> bool:
    """True when evidence shows the result belongs to another trade.

    Keep legitimate multi-trade businesses whenever Google's returned types
    explicitly include the requested vertical. Exclude only when the requested
    vertical is absent AND a taxonomy-verified competing trade is present AND
    the business name corroborates that competing trade.

    Generic categories such as general_contractor are intentionally not enough
    to exclude a business because they can describe real trade businesses.
    """
    types = set(rec.get("types") or [])
    name = (rec.get("name") or "").lower()

    # Strong positive evidence for the requested trade always wins.
    target_types = set(C.VERTICAL_EXPECTED_TYPES.get(vertical, set()))
    if types & target_types:
        return False

    # Preserve the older explicit non-trade noise guard.
    ptype = rec.get("primary_type") or ""
    if ptype in FOREIGN_TYPES:
        words = C.VERTICAL_SITE_WORDS.get(vertical, [])
        competing_noise = (
            "auto", "car", "vehicle", "marine", "boat", "rv", "supply",
            "hardware", "parts", "wholesale", "motor",
        )
        if not (
            any(w in name for w in words)
            and not any(cw in name for cw in competing_noise)
        ):
            return True

    # Exclude only when another taxonomy-verified trade is explicitly represented
    # AND the business name independently corroborates that competing trade.
    for other in C.CATEGORY_SIGNAL_VERIFIED:
        if other == vertical:
            continue

        other_types = set(C.VERTICAL_EXPECTED_TYPES.get(other, set()))
        if not (types & other_types):
            continue

        other_words = C.VERTICAL_SITE_WORDS.get(other, [])
        if any(word in name for word in other_words):
            return True

    return False


def review_activity(place: dict) -> dict:
    """Extract liveness from review timestamps.

    This is the dormant-vs-alive discriminator. Review COUNT cannot tell a
    listing nobody has touched since 2019 from a working business that simply
    never asks for reviews — but the date of the most recent review can.

    IMPORTANT: Google returns the 5 most RELEVANT reviews, not the 5 most
    recent — verified by inspecting raw payloads, where publishTimes come back
    out of chronological order. So `last_review_days` is a LOWER BOUND on
    recency: a recent date proves the business is active, but an old date does
    NOT prove dormancy, since newer reviews may simply not be in the sample.
    Scoring treats the two directions asymmetrically for exactly this reason.
    """
    import re as _re
    from datetime import datetime, timezone
    revs = place.get("reviews") or []
    times = []
    for r in revs:
        t = r.get("publishTime")
        if not t:
            continue
        # Google emits NANOSECOND precision (".857842623"). Python 3.9's
        # fromisoformat accepts only 3 or 6 fractional digits and raises on 9 —
        # which a bare try/except swallows, silently turning every timestamp
        # into "no data". Truncate to microseconds before parsing.
        t = _re.sub(r"\.(\d{6})\d+", r".\1", t.replace("Z", "+00:00"))
        try:
            times.append(datetime.fromisoformat(t))
        except Exception:
            pass
    if not times:
        return {"last_review_days": None, "recent_90d": 0, "sampled_reviews": 0}
    now = datetime.now(timezone.utc)
    times.sort(reverse=True)
    return {
        "last_review_days": (now - times[0]).days,
        "recent_90d": sum(1 for t in times if (now - t).days <= 90),
        "sampled_reviews": len(times),
    }


def normalize(place: dict, vertical: str) -> dict:
    """Flatten a Places payload into our businesses-table shape."""
    name = (place.get("displayName") or {}).get("text")
    loc = place.get("location") or {}
    hours = place.get("regularOpeningHours") or {}
    act = review_activity(place)

    return {
        "place_id": place.get("id"),
        "name": name,
        "vertical": vertical,
        "matched_verticals": [vertical],
        "primary_type": place.get("primaryType"),
        "types": place.get("types") or [],
        "business_status": place.get("businessStatus"),
        "formatted_address": place.get("formattedAddress"),
        "street": " ".join(
            x for x in [
                _component(place, "street_number"),
                _component(place, "route"),
            ] if x
        ) or None,
        "city": _component(place, "locality")
                or _component(place, "administrative_area_level_3"),
        "state": _component(place, "administrative_area_level_1", short=True),
        "postal_code": _component(place, "postal_code"),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "phone": place.get("nationalPhoneNumber"),
        "website_url": place.get("websiteUri"),
        "google_maps_uri": place.get("googleMapsUri"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "has_hours": bool(hours.get("weekdayDescriptions")),
        "hours_json": hours or None,
        "photo_count": len(place.get("photos") or []),
        "last_review_days": act["last_review_days"],
        "recent_reviews_90d": act["recent_90d"],
        "raw_places_payload": place,
    }


def merge_vertical_memberships(
    existing: dict,
    candidate: dict,
) -> dict:
    """Merge duplicate Places results without losing vertical membership."""

    memberships = set(
        existing.get("matched_verticals")
        or [existing.get("vertical")]
    )
    memberships.update(
        candidate.get("matched_verticals")
        or [candidate.get("vertical")]
    )
    memberships.discard(None)

    ordered = sorted(
        memberships,
        key=lambda vertical: (
            C.VERTICALS[vertical]["priority"],
            vertical,
        ),
    )

    existing_reviews = existing.get("review_count") or 0
    candidate_reviews = candidate.get("review_count") or 0

    richer = candidate if candidate_reviews > existing_reviews else existing
    merged = dict(richer)

    merged["matched_verticals"] = ordered
    merged["vertical"] = ordered[0]

    return merged


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------
def sweep(
    verticals: list[str],
    cities: list[str] | None = None,
    use_grid: bool = False,
    dry_run: bool = False,
    ledger: CostLedger | None = None,
    progress=print,
    checkpoint=None,
) -> tuple[dict[str, dict], CostLedger]:
    """Run discovery. Returns {place_id: normalized_business} and the cost ledger.

    Two sweep strategies:
      * city mode (default) — "electrician in Carlsbad CA". Fewer calls, higher
        precision, matches how Google actually understands local intent.
      * grid mode — lat/lng bias tiles. Slower and pricier, but catches
        businesses whose listings don't name a city we thought to ask for.

    City mode first; grid mode is the completeness backstop when a vertical
    looks under-collected.
    """
    ledger = ledger or CostLedger()
    client = PlacesClient(C.GOOGLE_API_KEY, ledger, dry_run=dry_run)
    found: dict[str, dict] = {}
    cities = cities or C.TARGET_CITIES

    for vertical in verticals:
        spec = C.VERTICALS[vertical]
        for query_term in spec["queries"]:
            if use_grid:
                targets = [(f"{query_term}", pt)
                           for pt in build_grid(C.GEO_BBOX, C.GRID_SPACING_KM)]
            else:
                targets = [(f"{query_term} in {city}, CA", None) for city in cities]

            for query, point in targets:
                try:
                    n_new = 0
                    for place in client.text_search(query, point):
                        pid = place.get("id")
                        if not pid:
                            continue
                        rec = normalize(place, vertical)

                        if rec["business_status"] in C.EXCLUDE_BUSINESS_STATUS:
                            continue
                        if is_chain(rec["name"] or ""):
                            continue
                        if not in_target_geo(rec):
                            continue
                        if wrong_vertical(rec, vertical):
                            continue

                        if pid in found:
                            # Same business surfaced by another query. Keep the
                            # richer record rather than blindly overwriting.
                            if (rec.get("review_count") or 0) > (found[pid].get("review_count") or 0):
                                found[pid] = rec
                        else:
                            found[pid] = rec
                            n_new += 1
                    progress(f"  {query:<55} +{n_new:<3} total={len(found)}")

                    if checkpoint is not None:
                        checkpoint(len(found), ledger)
                except Exception as e:
                    progress(f"  !! {query}: {e}")

    return found, ledger


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--verticals", nargs="*", default=C.PILOT_VERTICALS)
    ap.add_argument("--cities", nargs="*", default=None)
    ap.add_argument("--out", default="discovered.json")
    ap.add_argument("--merge", action="store_true",
                    help="union with existing --out file; counters Google's result churn")
    args = ap.parse_args()

    if args.dry_run:
        grid = build_grid(C.GEO_BBOX, C.GRID_SPACING_KM)
        cities = args.cities or C.TARGET_CITIES
        n_queries = sum(len(C.VERTICALS[v]["queries"]) for v in args.verticals)
        targets = len(grid) if args.grid else len(cities)
        worst = n_queries * targets * C.MAX_PAGES_PER_QUERY
        typical = int(worst * 0.45)   # most queries return <60 and stop early

        print(f"Grid points ({C.GRID_SPACING_KM}km over {C.GEO_LABEL}): {len(grid)}")
        print(f"Mode: {'grid' if args.grid else 'city'}  targets={targets}  "
              f"verticals={args.verticals}  query terms={n_queries}")
        print(f"Search calls — worst case {worst}, typical ~{typical}")
        for label, calls in (("worst", worst), ("typical", typical)):
            l = CostLedger(search_calls=calls)
            print(f"  {label:<8} {l.summary()}")
        print(f"Max businesses discoverable: ~{worst * C.RESULTS_PER_PAGE:,} "
              f"(before dedupe; real yield is far lower)")
        raise SystemExit(0)

    store = None
    run_id = None

    from store import PostgresStore
    from run_state import load_current_run, save_current_run

    store = PostgresStore()

    if not store.ping():
        raise SystemExit(
            "PostgreSQL unavailable; discovery requires a tracked database run."
        )

    pointer = load_current_run()

    if pointer:
        raise SystemExit(
            "active run pointer already exists "
            f"(run_id={pointer.get('run_id')}); "
            "resolve it before starting another discovery"
        )

    active = store.get_active_run()

    if active:
        raise SystemExit(
            "PostgreSQL already has an active run "
            f"(run_id={active['id']}, stage={active['stage']}); "
            "resolve it before starting another discovery"
        )

    grid_points = (
        len(build_grid(C.GEO_BBOX, C.GRID_SPACING_KM))
        if args.grid else 0
    )

    run_id = store.start_run(
        C.GEO_LABEL,
        sorted(args.verticals),
        grid_points,
        notes=f"model={C.MODEL_VERSION} staged",
    )

    try:
        save_current_run(
            run_id,
            C.GEO_LABEL,
            list(args.verticals),
        )
    except Exception:
        store.abandon_run(
            run_id,
            "Run pointer creation failed after database run creation",
        )
        raise

    print(f"run_id={run_id}")

    def persist_discovery_progress(
        businesses_observed: int,
        current_ledger: CostLedger,
    ) -> None:
        store.update_run_progress(
            run_id,
            stage="discovery",
            businesses_discovered=businesses_observed,
            api_calls_search=current_ledger.search_calls,
            api_calls_details=current_ledger.details_calls,
            est_cost_usd=round(
                current_ledger.est_usd(),
                4,
            ),
        )

    results, ledger = sweep(
        args.verticals,
        cities=args.cities,
        use_grid=args.grid,
        checkpoint=persist_discovery_progress,
    )

    # Results DRIFT over days, but are stable within a session. Measured:
    # two identical sweeps minutes apart returned the exact same 256 businesses
    # (0 new on merge), while a sweep 18 hours earlier differed by 34 gained /
    # 22 lost — including a 1,740-review company that vanished from the later
    # run. So re-running immediately buys nothing; re-running across days
    # accumulates real coverage. --merge unions into the output file, keyed on
    # place_id, which is what makes a weekly sweep additive rather than a
    # replacement that silently drops businesses Google didn't surface today.
    if args.merge and os.path.exists(args.out):
        with open(args.out) as f:
            prior = {b["place_id"]: b for b in json.load(f)}
        before = len(prior)
        gained = 0
        for pid, rec in results.items():
            if pid not in prior:
                gained += 1
            # Prefer the record with more reviews — the richer observation.
            if (pid not in prior
                    or (rec.get("review_count") or 0) >= (prior[pid].get("review_count") or 0)):
                prior[pid] = rec
        results = prior
        print(f"\nmerged: {before} prior + {gained} new = {len(results)} total")

    with open(args.out, "w") as f:
        json.dump(list(results.values()), f, indent=2, default=str)
    print(f"\n{len(results)} unique businesses -> {args.out}")
    print(ledger.summary())

    if store is not None and run_id is not None:
        store.update_run_progress(
            run_id,
            stage="crawl",
            api_calls_search=ledger.search_calls,
            api_calls_details=ledger.details_calls,
            est_cost_usd=round(ledger.est_usd(), 4),
            discovery_finished_at=datetime.now(timezone.utc),
        )
