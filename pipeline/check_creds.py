"""Production connectivity diagnostic for self-hosted Lead Desk.

Never prints secret values. Verifies the three runtime dependencies used by the
migrated backend: local PostgreSQL, Google Places API (New), and PageSpeed.
"""
from __future__ import annotations

import os
import requests
import psycopg

print("=" * 60)
print("LEAD DESK CONNECTIVITY CHECK")
print("=" * 60)

key = os.environ.get("GOOGLE_API_KEY", "")
dsn = os.environ.get("DATABASE_URL", "")


def present(label: str, value: str) -> bool:
    if not value:
        print(f"  MISSING   {label}")
        return False
    print(f"  PRESENT   {label}  (length {len(value)})")
    return True


print("\n1. Runtime configuration")
ok_key = present("GOOGLE_API_KEY", key)
ok_db = present("DATABASE_URL", dsn)

print("\n2. Local PostgreSQL")
if ok_db:
    try:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select current_database(), current_user")
            db, user = cur.fetchone()
            cur.execute("select count(*) from information_schema.tables where table_schema='public'")
            table_count = cur.fetchone()[0]
            cur.execute("select count(*) from information_schema.views where table_schema='public'")
            view_count = cur.fetchone()[0]
        print(f"  WORKS     database={db} user={user} tables={table_count} views={view_count}")
    except Exception as exc:
        print(f"  FAILED    {type(exc).__name__}: {exc}")
else:
    print("  SKIPPED   DATABASE_URL missing")

print("\n3. Google Places API (New) — 1 real request")
if ok_key:
    try:
        r = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.id,places.displayName",
            },
            json={"textQuery": "electrician in Carlsbad CA", "pageSize": 1},
            timeout=30,
        )
        if r.status_code == 200:
            print(f"  WORKS     returned {len(r.json().get('places', []))} result(s)")
        else:
            print(f"  FAILED    HTTP {r.status_code}")
            print(f"            {r.text[:400]}")
    except Exception as exc:
        print(f"  ERROR     {type(exc).__name__}: {exc}")
else:
    print("  SKIPPED   GOOGLE_API_KEY missing")

print("\n4. PageSpeed Insights — 1 real request")
if ok_key:
    try:
        r = requests.get(
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            params={"url": "https://example.com", "strategy": "mobile", "key": key},
            timeout=90,
        )
        if r.status_code == 200:
            print("  WORKS     HTTP 200")
        else:
            print(f"  FAILED    HTTP {r.status_code}")
            print(f"            {r.text[:400]}")
    except Exception as exc:
        print(f"  ERROR     {type(exc).__name__}: {exc}")
else:
    print("  SKIPPED   GOOGLE_API_KEY missing")

print("\n" + "=" * 60)
