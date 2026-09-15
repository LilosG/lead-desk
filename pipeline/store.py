"""PostgreSQL persistence for the self-hosted Lead Desk runtime.

This uses a direct local PostgreSQL connection
PostgreSQL connection. Domain behavior is intentionally kept compatible with the
original storage interface so the discovery/scoring pipeline does not need to change.
"""
from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import config as C


JSONB_COLUMNS = {
    "hours_json", "raw_places_payload", "social_profiles", "raw_psi_payload", "observed"
}


class PostgresStore:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not self.dsn:
            raise RuntimeError("DATABASE_URL missing. Load ~/lead-desk/.env before running.")

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _valid_columns(self, table: str) -> set[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select column_name from information_schema.columns
                   where table_schema='public' and table_name=%s""",
                (table,),
            )
            return {r["column_name"] for r in cur.fetchall()}

    @staticmethod
    def _adapt_value(column: str, value):
        if column in JSONB_COLUMNS and value is not None:
            return Jsonb(value)
        return value

    def _clean_rows(self, table: str, rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        valid = self._valid_columns(table)
        unknown = sorted({k for row in rows for k in row if k not in valid})
        for col in unknown:
            print(f"  ! column '{col}' not in {table}; dropping it for this write")
        return [
            {k: self._adapt_value(k, v) for k, v in row.items() if k in valid}
            for row in rows
        ]

    def upsert(self, table: str, rows: list, on_conflict: str | None = None) -> int:
        rows = self._clean_rows(table, rows)
        if not rows:
            return 0
        columns = list(rows[0].keys())
        conflict = [c.strip() for c in (on_conflict or "").split(",") if c.strip()]
        if not conflict:
            raise ValueError("PostgresStore.upsert requires on_conflict")
        update_cols = [c for c in columns if c not in conflict]

        q = sql.SQL("insert into {table} ({cols}) values ({vals}) on conflict ({conflict}) ").format(
            table=sql.Identifier(table),
            cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
            vals=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            conflict=sql.SQL(", ").join(map(sql.Identifier, conflict)),
        )
        if update_cols:
            q += sql.SQL("do update set ") + sql.SQL(", ").join(
                sql.SQL("{c}=excluded.{c}").format(c=sql.Identifier(c)) for c in update_cols
            )
        else:
            q += sql.SQL("do nothing")

        params = [[row.get(c) for c in columns] for row in rows]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(q, params)
        return len(rows)

    def insert(self, table: str, rows: list, returning: bool = False) -> list:
        rows = self._clean_rows(table, rows)
        if not rows:
            return []
        columns = list(rows[0].keys())
        q = sql.SQL("insert into {table} ({cols}) values ({vals})").format(
            table=sql.Identifier(table),
            cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
            vals=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        if returning:
            q += sql.SQL(" returning *")

        out = []
        with self._connect() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute(q, [row.get(c) for c in columns])
                if returning:
                    out.append(cur.fetchone())
        return out

    def select(self, table: str, limit: int = 100) -> list:
        q = sql.SQL("select * from {table} limit %s").format(table=sql.Identifier(table))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(q, (limit,))
            return cur.fetchall()

    def ping(self) -> bool:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("select 1 from runs limit 1")
            return True
        except Exception as e:
            print(f"PostgreSQL ping failed: {e}")
            return False

    def get_active_run(self) -> dict | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select
                    id,
                    started_at,
                    finished_at,
                    geo_label,
                    verticals,
                    status,
                    stage
                from runs
                where status = 'running'
                  and finished_at is null
                order by started_at desc
                limit 1
                """
            )
            return cur.fetchone()

    def abandon_run(self, run_id: str, reason: str = "") -> None:
        now = datetime.now(timezone.utc)

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update runs
                set
                    finished_at = %s,
                    status = 'abandoned',
                    notes = case
                        when %s = '' then notes
                        when coalesce(notes, '') = '' then %s
                        else notes || chr(10) || %s
                    end
                where id = %s
                  and status = 'running'
                  and finished_at is null
                """,
                (
                    now,
                    reason,
                    reason,
                    reason,
                    run_id,
                ),
            )

            if cur.rowcount != 1:
                raise RuntimeError(
                    f"active run not found: {run_id}"
                )

    def start_run(self, geo_label: str, verticals: list, grid_points: int,
                  dry_run: bool = False, notes: str = "") -> str:
        rows = self.insert("runs", [{
            "geo_label": geo_label, "verticals": verticals,
            "grid_points": grid_points, "dry_run": dry_run, "notes": notes,
            "status": "running", "stage": "discovery",
        }], returning=True)
        return str(rows[0]["id"])

    def update_run_progress(self, run_id: str, **fields) -> None:
        allowed = {
            "stage",
            "api_calls_search",
            "api_calls_details",
            "api_calls_psi",
            "est_cost_usd",
            "businesses_discovered",
            "websites_crawled",
            "psi_completed",
            "discovery_finished_at",
            "crawl_finished_at",
            "psi_finished_at",
            "notes",
            "status",
        }

        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported run fields: {sorted(unknown)}")

        values = {k: v for k, v in fields.items() if v is not None}
        if not values:
            return

        assignments = ", ".join(f"{k}=%s" for k in values)
        params = list(values.values()) + [run_id]

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"update runs set {assignments} where id=%s",
                params,
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"run not found: {run_id}")

    def increment_run_counters(
        self,
        run_id: str,
        *,
        search_calls: int = 0,
        details_calls: int = 0,
        psi_calls: int = 0,
    ) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update runs
                set api_calls_search = api_calls_search + %s,
                    api_calls_details = api_calls_details + %s,
                    api_calls_psi = api_calls_psi + %s
                where id = %s
                """,
                (search_calls, details_calls, psi_calls, run_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"run not found: {run_id}")

    def finish_run(self, run_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update runs
                set finished_at=%s,
                    status='completed',
                    stage='completed'
                where id=%s
                """,
                (datetime.now(timezone.utc), run_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"run not found: {run_id}")

    def save_businesses(self, businesses: list, run_id: str) -> int:
        now = datetime.now(timezone.utc)
        rows = []
        memberships = []

        for b in businesses:
            matched_verticals = list(
                dict.fromkeys(
                    b.get("matched_verticals")
                    or [b.get("vertical")]
                )
            )

            r = dict(b)
            r["last_seen_run"] = run_id
            r.setdefault("first_seen_run", run_id)
            r["last_seen_at"] = now
            r.pop("unique_key", None)
            r.pop("matched_verticals", None)
            rows.append(r)

            for vertical in matched_verticals:
                if not vertical:
                    continue
                memberships.append(
                    {
                        "place_id": b["place_id"],
                        "vertical": vertical,
                    }
                )

        saved = self.upsert(
            "businesses",
            rows,
            on_conflict="place_id",
        )

        if memberships:
            with self._connect() as conn, conn.cursor() as cur:
                cur.executemany(
                    """
                    insert into business_vertical_memberships (
                        place_id,
                        vertical,
                        first_seen_run,
                        last_seen_run,
                        first_seen_at,
                        last_seen_at
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (place_id, vertical)
                    do update set
                        last_seen_run = excluded.last_seen_run,
                        last_seen_at = excluded.last_seen_at
                    """,
                    [
                        (
                            item["place_id"],
                            item["vertical"],
                            run_id,
                            run_id,
                            now,
                            now,
                        )
                        for item in memberships
                    ],
                )

        return saved

    def save_enrichment(self, enrichment: dict) -> int:
        rows = []
        for pid, f in enrichment.items():
            d = asdict(f) if is_dataclass(f) else dict(f)
            d["place_id"] = pid
            rows.append(d)
        return self.upsert("website_enrichment", rows, on_conflict="place_id")

    def save_scores(self, scored: list, run_id: str) -> int:
        score_rows = [{
            "place_id": s.place_id, "run_id": run_id,
            "model_version": C.MODEL_VERSION,
            "total_score": s.total_score,
            "gbp_gap_score": s.gbp_gap_score,
            "website_gap_score": s.website_gap_score,
            "reachability_score": s.reachability_score,
            "tier": s.tier, "headline_gap": s.headline_gap,
        } for s in scored]

        inserted = self.insert("scores", score_rows, returning=True)
        by_place = {row["place_id"]: row["id"] for row in inserted}

        ev_rows = []
        for s in scored:
            sid = by_place.get(s.place_id)
            if not sid:
                continue
            for e in s.evidence:
                ev_rows.append({
                    "score_id": sid, "place_id": s.place_id,
                    "category": e.category, "signal": e.signal,
                    "severity": e.severity, "points": e.points,
                    "finding": e.finding, "observed": e.observed,
                })
        self.insert("score_evidence", ev_rows)
        return len(score_rows)

    def save_baselines(self, baselines: dict, run_id: str) -> int:
        rows = [{
            "run_id": run_id, "vertical": b.vertical, "geo_label": b.geo_label,
            "sample_size": b.sample_size, "median_reviews": b.median_reviews,
            "p25_reviews": b.p25_reviews, "p75_reviews": b.p75_reviews,
            "median_rating": b.median_rating, "pct_with_website": b.pct_with_website,
        } for b in baselines.values()]
        return self.upsert("vertical_baselines", rows,
                           on_conflict="run_id,vertical,geo_label")
