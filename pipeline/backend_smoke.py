"""Non-destructive backend parity smoke test.

Uses a PostgreSQL transaction and rolls it back deliberately.

Validates two separate contracts:

1. Runtime write parity:
   runs, businesses, enrichment, scores, and evidence all accept the shapes
   written by Lead Desk.

2. Operational reporting parity:
   latest-run-scoped views remain queryable and do not leak an unfinished
   transactional smoke run into production-facing results.
"""
from __future__ import annotations

import os
import uuid

import psycopg
from psycopg.types.json import Jsonb

DSN = os.environ.get("DATABASE_URL", "")
if not DSN:
    raise SystemExit("DATABASE_URL missing")

run_id = uuid.uuid4()
place_id = f"smoke-{uuid.uuid4()}"
score_id = uuid.uuid4()

with psycopg.connect(DSN) as conn:
    with conn.cursor() as cur:
        # ---------------------------------------------------------------
        # Temporary unfinished run. It must NOT become operational/latest.
        # ---------------------------------------------------------------
        cur.execute(
            """
            insert into runs
                (id, geo_label, verticals, notes, status, stage)
            values (%s,%s,%s,%s,%s,%s)
            """,
            (
                run_id,
                "Smoke Test",
                ["electrician"],
                "rolled back automatically",
                "running",
                "finalize",
            ),
        )

        cur.execute(
            """
            insert into businesses
                (
                    place_id,
                    first_seen_run,
                    last_seen_run,
                    name,
                    vertical,
                    formatted_address,
                    city,
                    state,
                    website_url,
                    review_count,
                    hours_json,
                    raw_places_payload
                )
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                place_id,
                run_id,
                run_id,
                "Lead Desk Smoke Test",
                "electrician",
                "1 Test Way, Carlsbad, CA",
                "Carlsbad",
                "CA",
                "https://example.com",
                25,
                Jsonb({"test": True}),
                Jsonb({"test": True}),
            ),
        )

        cur.execute(
            """
            insert into website_enrichment
                (
                    place_id,
                    is_reachable,
                    has_ssl,
                    emails_found,
                    raw_psi_payload
                )
            values (%s,%s,%s,%s,%s)
            """,
            (
                place_id,
                True,
                True,
                ["test@example.com"],
                Jsonb({"test": True}),
            ),
        )

        cur.execute(
            """
            insert into scores
                (
                    id,
                    place_id,
                    run_id,
                    model_version,
                    total_score,
                    gbp_gap_score,
                    website_gap_score,
                    reachability_score,
                    tier,
                    headline_gap
                )
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                score_id,
                place_id,
                run_id,
                "smoke",
                42,
                40,
                44,
                100,
                "B",
                "Smoke test",
            ),
        )

        cur.execute(
            """
            insert into score_evidence
                (
                    score_id,
                    place_id,
                    category,
                    signal,
                    severity,
                    points,
                    finding,
                    observed
                )
            values (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                score_id,
                place_id,
                "website",
                "smoke",
                "info",
                0,
                "Smoke test",
                Jsonb({"ok": True}),
            ),
        )

        # ---------------------------------------------------------------
        # Validate runtime writes directly.
        # ---------------------------------------------------------------
        cur.execute(
            """
            select
                s.place_id,
                s.total_score,
                b.name,
                w.is_reachable,
                e.signal
            from scores s
            join businesses b
              on b.place_id = s.place_id
            left join website_enrichment w
              on w.place_id = s.place_id
            left join score_evidence e
              on e.score_id = s.id
            where s.id = %s
            """,
            (score_id,),
        )

        row = cur.fetchone()

        expected = (
            place_id,
            42,
            "Lead Desk Smoke Test",
            True,
            "smoke",
        )

        if row != expected:
            raise RuntimeError(
                f"transactional write verification failed: {row!r}"
            )

        # ---------------------------------------------------------------
        # Operational views must NOT expose the unfinished smoke run.
        # ---------------------------------------------------------------
        cur.execute(
            """
            select place_id
            from v_lead_worklist
            where place_id = %s
            """,
            (place_id,),
        )

        leaked = cur.fetchone()

        if leaked is not None:
            raise RuntimeError(
                "unfinished smoke run leaked into v_lead_worklist"
            )

        # ---------------------------------------------------------------
        # Production/reporting views themselves must remain queryable.
        # We do not assert a particular business because production data
        # can legitimately change between runs.
        # ---------------------------------------------------------------
        view_checks = [
            "v_latest_completed_run",
            "v_latest_score",
            "v_lead_findings",
            "v_lead_worklist",
            "v_leads",
            "v_leads_email_list",
            "v_leads_call_list",
            "v_run_summary",
        ]

        for view in view_checks:
            cur.execute(f"select * from {view} limit 1")
            cur.fetchone()

        print(
            "PASS  transactional writes across "
            "runs/businesses/enrichment/scores/evidence"
        )
        print(
            "PASS  unfinished runs are excluded from operational views"
        )
        print("PASS  reporting views query successfully")
        print("PASS  smoke data will be rolled back")

        conn.rollback()
