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
    rec("lajolla", "La Jolla", "CA", 32.8328, -117.2713),   # neighborhood, ~16 km
    rec("tijuana", "Tijuana", "BC", 32.5149, -117.0382),    # other country/state
    rec("phoenix", "Phoenix", "AZ", 33.4484, -112.0740),    # other state
    rec("temecula", "Temecula", "CA", 33.4936, -117.1484),  # same state, ~85 km
]
center = D.market_center(records, SD)
keep = {r["place_id"] for r in records if D.in_market(r, SD, center)}

checks = [
    ("exact city matches are kept", {"a", "b", "c"} <= keep),
    ("neighborhood filed under its own name is kept (La Jolla)", "lajolla" in keep),
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
class FakeClient:
    dry_run = False

    def __init__(self):
        self.calls = []

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


old_depth = C.MAX_SPLIT_DEPTH
C.MAX_SPLIT_DEPTH = 1
client = FakeClient()
found = D._search_area(client, "dentist in Austin, TX, USA", progress=lambda *_: None)
C.MAX_SPLIT_DEPTH = old_depth
ids = [p["id"] for p in found]

checks += [
    ("capped query is split into 4 cells", len(client.calls) == 5),
    ("cells add businesses the capped query hid", len(ids) == 60 + 4 * 5),
    ("duplicates across cells are removed", len(ids) == len(set(ids))),
]

ok = True
for label, passed in checks:
    print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    ok = ok and bool(passed)
print("\n" + ("ALL CHECKS PASSED" if ok else "*** SOME CHECKS FAILED ***"))
raise SystemExit(0 if ok else 1)
