from discover import wrong_vertical

CASES = [
    (
        "Mauzy multi-trade stays",
        {
            "name": "Mauzy Cooling, Heating, Plumbing, and Electrical",
            "primary_type": "service",
            "types": ["plumber", "electrician", "general_contractor", "service"],
        },
        "electrician",
        False,
    ),
    (
        "Baker ambiguous stays",
        {
            "name": "Baker Home Energy",
            "primary_type": "service",
            "types": ["roofing_contractor", "general_contractor", "service"],
        },
        "electrician",
        False,
    ),
    (
        "Beach plumbing excluded",
        {
            "name": "Beach Plumbing & Service",
            "primary_type": "plumber",
            "types": ["plumber", "service", "establishment"],
        },
        "electrician",
        True,
    ),
    (
        "Standard Plumbing excluded",
        {
            "name": "Standard Plumbing",
            "primary_type": "plumber",
            "types": ["plumber", "service", "establishment"],
        },
        "electrician",
        True,
    ),
    (
        "All American Plumbing excluded",
        {
            "name": "All American Plumbing Inc.",
            "primary_type": "plumber",
            "types": ["plumber", "service", "establishment"],
        },
        "electrician",
        True,
    ),
    (
        "generic contractor stays",
        {
            "name": "A&G Handyman Services English/Spanish",
            "primary_type": "general_contractor",
            "types": ["general_contractor", "service", "establishment"],
        },
        "electrician",
        False,
    ),
    (
        "explicit electrician stays despite handyman name",
        {
            "name": "Figueroa Handyman",
            "primary_type": "general_contractor",
            "types": ["electrician", "general_contractor", "service"],
        },
        "electrician",
        False,
    ),
    (
        "public charger excluded by type",
        {
            "name": "Electrify America",
            "primary_type": "electric_vehicle_charging_station",
            "types": ["electric_vehicle_charging_station", "point_of_interest"],
        },
        "electrician",
        True,
    ),
    (
        "public charger excluded by name",
        {
            "name": "Tesla Supercharger",
            "primary_type": "service",
            "types": ["service", "establishment"],
        },
        "electrician",
        True,
    ),
    (
        "electrician who sells chargers stays",
        {
            "name": "Sparks EV Charging Stations",
            "primary_type": "electrician",
            "types": ["electrician", "service"],
        },
        "electrician",
        False,
    ),
    (
        "auto shop excluded",
        {
            "name": "Pacific Auto Electric",
            "primary_type": "car_repair",
            "types": ["car_repair", "service", "establishment"],
        },
        "electrician",
        True,
    ),
]

failed = 0

for label, rec, vertical, expected in CASES:
    actual = wrong_vertical(rec, vertical)
    status = "PASS" if actual == expected else "FAIL"
    print(f"{status}  {label}: expected={expected} actual={actual}")
    if actual != expected:
        failed += 1

if failed:
    raise SystemExit(f"{failed} vertical-filter test(s) failed")

print("ALL CHECKS PASSED")
