import json

d = json.load(open("discovered.json"))
top = sorted([x for x in d if x.get("review_count")], key=lambda x: -x["review_count"])[:8]
print("business".ljust(34), "reviews".rjust(8), "last_review_days".rjust(18))
for x in top:
    print(x["name"][:32].ljust(34), str(x["review_count"]).rjust(8),
          str(x.get("last_review_days")).rjust(18))

print()
for target in ("Blackwood", "Arce"):
    p = [x for x in d if x["name"].startswith(target)]
    if not p:
        continue
    revs = p[0]["raw_places_payload"].get("reviews") or []
    print(f"{p[0]['name']} — {p[0].get('review_count')} total reviews")
    print("  publishTimes returned by the API, in API order:")
    for r in revs:
        print("   ", r.get("publishTime"), "| rating", r.get("rating"))
    print()
