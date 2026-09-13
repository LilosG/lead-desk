"""Empirically test the claimed Places API paging bug. Costs 4 search calls."""
import json
import time

import requests

import config as C

H = {"Content-Type": "application/json", "X-Goog-Api-Key": C.GOOGLE_API_KEY,
     "X-Goog-FieldMask": "places.id,places.displayName,nextPageToken"}
URL = C.PLACES_SEARCH_URL
Q = "plumber in San Diego, CA"


def post(payload):
    r = requests.post(URL, headers=H, json=payload, timeout=30)
    return r.status_code, r.json()


print("PAGE 1")
sc, d1 = post({"textQuery": Q, "pageSize": 20})
tok = d1.get("nextPageToken")
print(f"  status={sc} places={len(d1.get('places', []))} nextPageToken={'yes' if tok else 'no'}")

if not tok:
    raise SystemExit("no page token; cannot test")

time.sleep(1)
print("\nPAGE 2 — variant A: pageToken ONLY (the shipped code)")
sc, dA = post({"pageToken": tok})
print(f"  status={sc} places={len(dA.get('places', []))}")
if sc != 200:
    print(f"  error: {json.dumps(dA)[:300]}")

time.sleep(1)
print("\nPAGE 2 — variant B: original params REPEATED + pageToken (the fix)")
sc, dB = post({"textQuery": Q, "pageSize": 20, "pageToken": tok})
print(f"  status={sc} places={len(dB.get('places', []))}")
if sc != 200:
    print(f"  error: {json.dumps(dB)[:300]}")

ids1 = {p["id"] for p in d1.get("places", [])}
idsA = {p["id"] for p in dA.get("places", [])}
idsB = {p["id"] for p in dB.get("places", [])}
print("\nRESULT")
print(f"  page1 unique ids            {len(ids1)}")
print(f"  variantA new ids beyond p1  {len(idsA - ids1)}")
print(f"  variantB new ids beyond p1  {len(idsB - ids1)}")
if len(idsB - ids1) > len(idsA - ids1):
    print("\n  CONFIRMED: paging requires the original params. The shipped code")
    print("  silently truncated every query at 20 results.")
elif len(idsA - ids1) > 0:
    print("\n  NOT CONFIRMED: pageToken-only paging works fine.")
else:
    print("\n  INCONCLUSIVE: neither variant returned new results.")
