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
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Iterator

import requests

import config as C
import verticals as V


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
    # Results Google returned that we left out, by reason. Shown on the run page.
    dropped: dict = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def est_usd(self) -> float:
        return (
            self.search_calls / 1000 * C.COST_PER_1K["text_search_enterprise"]
            + self.details_calls / 1000 * C.COST_PER_1K["place_details_enterprise"]
        )

    def est_usd_after_free_tier(self) -> float:
        """Free tier is per-SKU per-month and does not roll over."""
        billable_search = max(0, self.search_calls - C.FREE_TIER_MONTHLY["enterprise"])
        billable_details = max(0, self.details_calls - C.FREE_TIER_MONTHLY["enterprise"])
        return (
            billable_search / 1000 * C.COST_PER_1K["text_search_enterprise"]
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
        self.budget: int | None = None   # max billable search calls; None = no cap
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
            if r.status_code in (429, 503):
                time.sleep(backoff)
                backoff *= 2
                continue
            raise RuntimeError(f"Places API {r.status_code}: {r.text[:400]}")
        raise RuntimeError("Places API: exhausted retries after rate limiting")

    def text_search(
        self,
        query: str,
        point: GridPoint | None = None,
        max_pages: int | None = None,
        rectangle: dict | None = None,
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
        base_payload: dict = {"textQuery": query, "pageSize": C.RESULTS_PER_PAGE, "minRating": 3.5}
        if rectangle:
            # Hard restriction, used when a dense market is split into cells.
            base_payload["locationRestriction"] = {
                "rectangle": {
                    "low": {"latitude": rectangle["min_lat"], "longitude": rectangle["min_lng"]},
                    "high": {"latitude": rectangle["max_lat"], "longitude": rectangle["max_lng"]},
                }
            }
        elif point:
            base_payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": point.lat, "longitude": point.lng},
                    "radius": float(point.radius_m),
                }
            }
        payload = dict(base_payload)

        for page in range(max_pages):
            if self.budget is not None and self.ledger.search_calls >= self.budget:
                return
            if self.dry_run:
                self.ledger.search_calls += 1
                return
            data = self._post(payload)
            self.ledger.search_calls += 1

            places = data.get("places", [])
            for p in places:
                yield p

            # Google's pages are often short (15, 11, 10), so only a missing
            # token means the results have run out.
            token = data.get("nextPageToken")
            if not token:
                return
            payload = dict(base_payload, pageToken=token)
            time.sleep(0.6)


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


def in_target_geo(rec: dict, bbox: dict | None = None) -> bool:
    """Legacy grid mode only: keep results inside an explicit bounding box."""
    bb = bbox or C.GEO_BBOX
    if not bb:
        return True
    lat, lng = rec.get("lat"), rec.get("lng")
    if lat is None or lng is None:
        return False
    pad = 0.15
    if not (bb["min_lat"] - pad <= lat <= bb["max_lat"] + pad):
        return False
    if not (bb["min_lng"] - pad <= lng <= bb["max_lng"] + pad):
        return False
    return True


def _geo_token(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _city_parts(target_city: str) -> tuple[str, str]:
    """('city token', 'ST') from 'City, ST, USA' (state may be '')."""
    parts = [part.strip() for part in target_city.split(",") if part.strip()]
    city = _geo_token(parts[0]) if parts else ""
    state = parts[1].strip().upper() if len(parts) >= 2 else ""
    return city, (state if len(state) == 2 else "")


def _state_ok(rec: dict, wanted_state: str) -> bool:
    actual = str(rec.get("state") or "").strip().upper()
    return not wanted_state or not actual or actual == wanted_state


def in_requested_city(rec: dict, target_city: str) -> bool:
    """Exact locality match against an operator-selected U.S. city label."""
    wanted_city, wanted_state = _city_parts(target_city)
    if not wanted_city or _geo_token(rec.get("city")) != wanted_city:
        return False
    return _state_ok(rec, wanted_state)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _median(values: list[float]) -> float:
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def market_center(records: list[dict], target_city: str) -> tuple[float, float] | None:
    """Center of a searched market, from the results that match it exactly.

    Falls back to every same-state result when nothing matches the locality
    exactly (common when Google files a whole metro under neighborhood names).
    """
    _, wanted_state = _city_parts(target_city)
    exact = [r for r in records if in_requested_city(r, target_city)
             and r.get("lat") is not None and r.get("lng") is not None]
    pool = exact or [r for r in records if _state_ok(r, wanted_state)
                     and r.get("lat") is not None and r.get("lng") is not None]
    if not pool:
        return None
    return _median([r["lat"] for r in pool]), _median([r["lng"] for r in pool])


def in_market(rec: dict, target_city: str, center: tuple[float, float] | None,
              radius_km: float | None = None) -> bool:
    """Exact city match, or a same-state business near the market's center.

    Strict locality matching dropped real businesses filed under a suburb or
    neighborhood name; distance to the market center keeps them without
    letting Text Search's semantic drift pull in other states.
    """
    if in_requested_city(rec, target_city):
        return True
    _, wanted_state = _city_parts(target_city)
    if not _state_ok(rec, wanted_state) or not rec.get("state"):
        return False
    if center is None or rec.get("lat") is None or rec.get("lng") is None:
        return False
    radius = radius_km if radius_km is not None else C.NEARBY_RADIUS_KM
    return haversine_km(rec["lat"], rec["lng"], center[0], center[1]) <= radius


def split_rectangle(records: list[dict]) -> list[dict]:
    """Split the area covered by a saturated result set into 4 cells."""
    lats = [r["lat"] for r in records if r.get("lat") is not None]
    lngs = [r["lng"] for r in records if r.get("lng") is not None]
    if len(lats) < 2:
        return []
    min_lat, max_lat, min_lng, max_lng = min(lats), max(lats), min(lngs), max(lngs)
    pad_lat = max((max_lat - min_lat) * 0.1, 0.01)
    pad_lng = max((max_lng - min_lng) * 0.1, 0.01)
    min_lat, max_lat = min_lat - pad_lat, max_lat + pad_lat
    min_lng, max_lng = min_lng - pad_lng, max_lng + pad_lng
    mid_lat, mid_lng = (min_lat + max_lat) / 2, (min_lng + max_lng) / 2
    return [
        {"min_lat": a, "max_lat": b, "min_lng": c, "max_lng": d}
        for a, b in ((min_lat, mid_lat), (mid_lat, max_lat))
        for c, d in ((min_lng, mid_lng), (mid_lng, max_lng))
    ]


FOREIGN_TYPES = {
    "car_repair", "car_dealer", "hardware_store", "home_improvement_store",
    "electronics_store", "home_goods_store", "plumbing_supply_store", "school", "lawyer", "insurance_agency", "real_estate_agency",
    "restaurant", "lodging", "gym", "storage", "moving_company",
}


CHARGING_STATION = "electric_vehicle_charging_station"
CHARGING_NAMES = re.compile(r"supercharger|charging station|destination charger", re.I)


def wrong_vertical(rec: dict, vertical: str) -> bool:
    """True when evidence shows the result belongs to another trade.

    Preset verticals retain the verified trade-noise logic. Custom verticals
    intentionally do not use a home-service-centric exclusion list: Google text
    relevance plus geo validation is safer than dropping a dentist, restaurant,
    attorney, gym, or any other operator-requested category as "foreign".
    """
    if not V.is_preset(vertical):
        return False
    # The exclusion lists below were built for trades. Applying them to a dental,
    # legal, real-estate or med-spa preset would drop legitimate businesses.
    if not V.is_home_service(vertical):
        return False

    types = set(rec.get("types") or [])
    name = (rec.get("name") or "").lower()

    target_types = set(C.VERTICAL_EXPECTED_TYPES.get(vertical, set()))
    if types & target_types:
        return False

    # A public charger is a place to plug in, not a business to pitch.
    ptype = rec.get("primary_type") or ""
    if CHARGING_STATION in types or ptype == CHARGING_STATION or CHARGING_NAMES.search(name):
        return True

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

    IMPORTANT: Google returns the 5 most RELEVANT reviews, not the 5 most recent.
    The newest returned timestamp therefore proves recent activity when present,
    but an old sample does not prove dormancy.
    """
    import re as _re
    from datetime import datetime, timezone

    revs = place.get("reviews") or []
    times = []
    for r in revs:
        t = r.get("publishTime")
        if not t:
            continue
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
    vertical = V.normalize_vertical_key(vertical)
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
        "is_franchise": is_chain(name or ""),
        # The searched market this business was found in ("City, ST, USA").
        # Set by sweep(); local comparisons are made within this market.
        "market": None,
        "raw_places_payload": place,
    }


def merge_vertical_memberships(existing: dict, candidate: dict) -> dict:
    """Merge duplicate Places results without losing vertical membership."""
    memberships = set(
        existing.get("matched_verticals") or [existing.get("vertical")]
    )
    memberships.update(
        candidate.get("matched_verticals") or [candidate.get("vertical")]
    )
    memberships.discard(None)

    ordered = sorted(
        memberships,
        key=lambda vertical: (V.vertical_priority(vertical), vertical),
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
def _search_area(
    client: "PlacesClient",
    query: str,
    *,
    point: GridPoint | None = None,
    rectangle: dict | None = None,
    depth: int = 0,
    progress=print,
    budget: int | None = None,
) -> list[dict]:
    """Run one query; if Google's 60-result cap is hit, split and search again."""
    if budget is not None and client.ledger.search_calls >= budget:
        return []
    places = [p for p in client.text_search(query, point, rectangle=rectangle) if p.get("id")]
    cap = C.GOOGLE_RESULT_CAP
    if (
        not C.SPLIT_SATURATED_QUERIES
        or client.dry_run
        or len(places) < cap
        or depth >= C.MAX_SPLIT_DEPTH
    ):
        return places

    located = []
    for p in places:
        loc = p.get("location") or {}
        if loc.get("latitude") is not None:
            located.append({"lat": loc["latitude"], "lng": loc.get("longitude")})
    cells = split_rectangle(located)
    if not cells:
        return places
    progress(f"    {query}: hit the {cap}-result cap, splitting into {len(cells)} areas")

    seen = {p["id"] for p in places}
    out = list(places)
    for cell in cells:
        for p in _search_area(client, query, rectangle=cell, depth=depth + 1,
                              progress=progress, budget=budget):
            if p["id"] not in seen:
                seen.add(p["id"])
                out.append(p)
    return out


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

    Nothing is dropped for being small, new, quiet or a franchise: those become
    labels at scoring time. Only permanently closed listings, results outside
    the searched market, and (for trade presets) clear wrong-trade noise are
    left out.
    """
    ledger = ledger or CostLedger()
    client = PlacesClient(C.GOOGLE_API_KEY, ledger, dry_run=dry_run)
    found: dict[str, dict] = {}
    cities = [c.strip() for c in (cities or []) if c and c.strip()]
    if not use_grid and not cities:
        raise ValueError("at least one city is required (e.g. 'Austin, TX, USA')")
    if use_grid and not C.GEO_BBOX:
        raise ValueError("grid mode needs an explicit GEO_BBOX in config")
    verticals = V.ordered_verticals(verticals)

    # Never spend more than the estimate the operator saw before starting.
    n_targets = len(build_grid(C.GEO_BBOX, C.GRID_SPACING_KM)) if use_grid else len(cities)
    budget = max_search_calls(verticals, n_targets)
    client.budget = ledger.search_calls + budget

    for vertical in verticals:
        for query_term in V.vertical_queries(vertical):
            if ledger.search_calls >= client.budget:
                progress(f"  search budget reached ({budget} calls) — stopping discovery")
                return found, ledger
            if use_grid:
                targets = [
                    (f"{query_term}", pt, None)
                    for pt in build_grid(C.GEO_BBOX, C.GRID_SPACING_KM)
                ]
            else:
                targets = [
                    (f"{query_term} in {city}", None, city)
                    for city in cities
                ]

            for query, point, target_city in targets:
                try:
                    raw = _search_area(client, query, point=point, progress=progress,
                                       budget=client.budget)
                    records = []
                    for place in raw:
                        rec = normalize(place, vertical)
                        if rec["business_status"] in C.EXCLUDE_BUSINESS_STATUS:
                            ledger.drop("closed")
                            continue
                        if (rec.get("review_count") or 0) < 10:
                            ledger.drop("too_few_reviews")
                            continue
                        records.append(rec)

                    center = (
                        market_center(records, target_city)
                        if target_city else None
                    )

                    n_new = 0
                    for rec in records:
                        pid = rec["place_id"]
                        if target_city is None:
                            if not in_target_geo(rec):
                                continue
                            rec["market"] = C.DEFAULT_GEO_LABEL
                        elif not in_market(rec, target_city, center):
                            ledger.drop("outside_market")
                            continue
                        else:
                            rec["market"] = target_city
                        if wrong_vertical(rec, vertical):
                            ledger.drop("wrong_niche")
                            continue

                        if pid in found:
                            merged = merge_vertical_memberships(found[pid], rec)
                            merged["market"] = found[pid].get("market") or rec["market"]
                            found[pid] = merged
                        else:
                            found[pid] = rec
                            n_new += 1
                    progress(f"  {query:<55} +{n_new:<3} total={len(found)}")

                    if checkpoint is not None:
                        checkpoint(len(found), ledger)
                except Exception as e:
                    progress(f"  !! {query}: {e}")

    return found, ledger


def max_search_calls(verticals: list[str], n_targets: int) -> int:
    """The 'max with pagination' figure the Sweeps page shows: hard spend cap."""
    n_queries = sum(len(V.vertical_queries(v)) for v in verticals)
    return n_queries * max(n_targets, 0) * C.MAX_PAGES_PER_QUERY


def run_geo_label(cities: list[str] | None) -> str:
    """Human label for a run, built from the cities actually searched."""
    cleaned = [c.strip() for c in (cities or []) if c and c.strip()]
    if not cleaned:
        return C.DEFAULT_GEO_LABEL
    short = [", ".join(part.strip() for part in c.split(",")[:2]) for c in cleaned]
    label = " • ".join(short[:4])
    if len(short) > 4:
        label += f" +{len(short) - 4} more"
    return label


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
    args.verticals = V.ordered_verticals(args.verticals)

    if not args.grid and not args.cities:
        raise SystemExit("--cities is required, e.g. --cities 'Austin, TX, USA' 'Dallas, TX, USA'")
    geo_label = run_geo_label(args.cities)

    if args.dry_run:
        grid = build_grid(C.GEO_BBOX, C.GRID_SPACING_KM) if (args.grid and C.GEO_BBOX) else []
        cities = args.cities or []
        n_queries = sum(len(V.vertical_queries(v)) for v in args.verticals)
        targets = len(grid) if args.grid else len(cities)
        worst = n_queries * targets * C.MAX_PAGES_PER_QUERY
        typical = int(worst * 0.45)

        print(f"Market: {geo_label}  grid points: {len(grid)}")
        print(f"Mode: {'grid' if args.grid else 'city'}  targets={targets}  "
              f"verticals={args.verticals}  query terms={n_queries}")
        print(f"Search calls — hard cap {worst}, typical ~{typical}")
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
        if (args.grid and C.GEO_BBOX) else 0
    )

    run_id = store.start_run(
        geo_label,
        sorted(args.verticals),
        grid_points,
        notes=f"model={C.MODEL_VERSION} staged",
    )

    try:
        save_current_run(run_id, geo_label, list(args.verticals))
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
            est_cost_usd=round(current_ledger.est_usd(), 4),
        )

    results, ledger = sweep(
        args.verticals,
        cities=args.cities,
        use_grid=args.grid,
        checkpoint=persist_discovery_progress,
    )

    if args.merge and os.path.exists(args.out):
        with open(args.out) as f:
            prior = {b["place_id"]: b for b in json.load(f)}
        before = len(prior)
        gained = 0
        for pid, rec in results.items():
            if pid not in prior:
                prior[pid] = rec
                gained += 1
            else:
                prior[pid] = merge_vertical_memberships(prior[pid], rec)
        results = prior
        print(f"\nmerged: {before} prior + {gained} new = {len(results)} total")

    with open(args.out, "w") as f:
        json.dump(list(results.values()), f, indent=2, default=str)
    print(f"\n{len(results)} unique businesses -> {args.out}")
    print(ledger.summary())

    from pipeline import prune_cache  # the sibling pipeline.py, which imports this module

    print(f"cleared {prune_cache()} stale crawl results")

    if store is not None and run_id is not None:
        store.update_run_progress(
            run_id,
            stage="crawl",
            api_calls_search=ledger.search_calls,
            api_calls_details=ledger.details_calls,
            est_cost_usd=round(ledger.est_usd(), 4),
            discovery_finished_at=datetime.now(timezone.utc),
            discovery_stats=ledger.dropped,
        )
