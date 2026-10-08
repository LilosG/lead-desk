"""
Discovery regressions for open geo: market matching and dense-market splitting.
No API calls — a fake Places client stands in for Google.
"""
from __future__ import annotations

import config as C
import discover as D

SD = "San Diego, CA, USA"


def rec(pid, city, state, lat, lng):
    return {"place_id": pid, "city": city, "state": state, "lat": lat, "lng": lng}


records = [
    rec("a", "San Diego", "CA", 32.7157, -117.1611),
    rec("b", "San Diego", "CA", 32.7500, -117.1500),
    rec("c", "San Diego", "CA", 32.7000, -117.1700),
    rec("hillcrest", "Hillcrest", "CA", 32.7480, -117.1640),  # neighborhood, ~3 km
    rec("tijuana", "Tijuana", "BC", 32.5149, -117.0382),    # other country/state
    rec("phoenix", "Phoenix", "AZ", 33.4484, -112.0740),    # other state
    rec("temecula", "Temecula", "CA", 33.4936, -117.1484),  # same state, ~85 km
]
center = D.market_center(records, SD)
keep = {r["place_id"] for r in records if D.in_market(r, SD, center)}

checks = [
    ("exact city matches are kept", {"a", "b", "c"} <= keep),
    ("neighborhood filed under its own name is kept (Hillcrest)", "hillcrest" in keep),
    ("other state is rejected", "phoenix" not in keep and "tijuana" not in keep),
    ("same-state town far outside the market is rejected", "temecula" not in keep),
    ("run label comes from the searched cities",
     D.run_geo_label(["Austin, TX, USA", "Dallas, TX, USA"]) == "Austin, TX • Dallas, TX"),
    ("no default region: sweep without cities is an error", False),
]
try:
    D.sweep(["dentist"], cities=[], dry_run=True)
except ValueError:
    checks[-1] = (checks[-1][0], True)


# --- dense market splitting ----------------------------------------------------
class FakeLedger:
    search_calls = 0


class FakeClient:
    dry_run = False

    def __init__(self):
        self.calls = []
        self.ledger = FakeLedger()

    def text_search(self, query, point=None, rectangle=None):
        self.calls.append(rectangle)
        if rectangle is None:
            # Saturated: Google's 60-result cap, spread over a box.
            for i in range(60):
                yield {"id": f"p{i}", "location": {"latitude": 30.20 + i * 0.004,
                                                   "longitude": -97.80 + i * 0.004}}
        else:
            # Each cell reveals a few more businesses the capped query hid.
            key = f"{rectangle['min_lat']:.3f}"
            for i in range(5):
                yield {"id": f"cell-{key}-{rectangle['min_lng']:.3f}-{i}",
                       "location": {"latitude": rectangle["min_lat"] + 0.001,
                                    "longitude": rectangle["min_lng"] + 0.001}}
            yield {"id": "p0", "location": {"latitude": 30.20, "longitude": -97.80}}  # dup


checks.append(("splitting is OFF by default (no surprise spend)", C.SPLIT_SATURATED_QUERIES is False))
off_client = FakeClient()
D._search_area(off_client, "dentist in Austin, TX, USA", progress=lambda *_: None)
checks.append(("with splitting off, a capped query makes no extra calls", len(off_client.calls) == 1))

old_depth, old_split = C.MAX_SPLIT_DEPTH, C.SPLIT_SATURATED_QUERIES
C.MAX_SPLIT_DEPTH, C.SPLIT_SATURATED_QUERIES = 1, True
client = FakeClient()
found = D._search_area(client, "dentist in Austin, TX, USA", progress=lambda *_: None)
C.MAX_SPLIT_DEPTH, C.SPLIT_SATURATED_QUERIES = old_depth, old_split
ids = [p["id"] for p in found]

checks += [
    ("capped query is split into 4 cells", len(client.calls) == 5),
    ("cells add businesses the capped query hid", len(ids) == 60 + 4 * 5),
    ("duplicates across cells are removed", len(ids) == len(set(ids))),
]

# --- hard spend cap equals the Sweeps page's "max with pagination" -------------
checks.append(("spend cap = queries x cities x 3 pages",
               D.max_search_calls(["med_spa"], 1) == 9))


class CountingPlaces(D.PlacesClient):
    def _post(self, payload):
        # Every page full, so pagination would continue if not capped.
        return {"places": [{"id": f"x{self.ledger.search_calls}-{i}"} for i in range(20)],
                "nextPageToken": "t"}


C.GOOGLE_API_KEY = C.GOOGLE_API_KEY or "test-key"  # fake client, no real calls
real_client = D.PlacesClient
D.PlacesClient = CountingPlaces
D.time.sleep = lambda *_: None
try:
    _, led = D.sweep(["med_spa"], cities=["Scottsdale, AZ, USA"], progress=lambda *_: None)
finally:
    D.PlacesClient = real_client
checks.append(("a sweep never makes more calls than the on-screen max",
               led.search_calls <= D.max_search_calls(["med_spa"], 1)))

ok = True
for label, passed in checks:
    print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    ok = ok and bool(passed)
print("\n" + ("ALL CHECKS PASSED" if ok else "*** SOME CHECKS FAILED ***"))
raise SystemExit(0 if ok else 1)
