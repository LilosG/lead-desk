from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool


RUN_SELECT = """
    select
        r.id,
        r.started_at,
        r.finished_at,
        coalesce(
            (
                select nullif(array_to_string(sj.cities, ' • '), '')
                from sweep_jobs sj
                where sj.run_id = r.id
                order by sj.created_at desc
                limit 1
            ),
            r.geo_label
        ) as geo_label,
        r.verticals,
        r.grid_points,
        r.status,
        r.stage,
        r.dry_run,
        r.notes,

        r.businesses_discovered,
        count(distinct s.place_id) as businesses_scored,
        r.websites_crawled,
        r.psi_completed,

        count(*) filter (where s.tier = 'A') as tier_a,
        count(*) filter (where s.tier = 'B') as tier_b,
        count(*) filter (where s.tier = 'C') as tier_c,
        count(*) filter (where s.tier = 'D') as tier_d,

        round(avg(s.total_score), 1) as avg_score,

        r.api_calls_search,
        r.api_calls_details,
        r.api_calls_psi,
        r.est_cost_usd,

        r.discovery_finished_at,
        r.crawl_finished_at,
        r.psi_finished_at

    from runs r
    left join scores s
      on s.run_id = r.id
"""


RUN_GROUP_BY = """
    group by
        r.id,
        r.started_at,
        r.finished_at,
        r.geo_label,
        r.verticals,
        r.grid_points,
        r.status,
        r.stage,
        r.dry_run,
        r.notes,
        r.businesses_discovered,
        r.websites_crawled,
        r.psi_completed,
        r.api_calls_search,
        r.api_calls_details,
        r.api_calls_psi,
        r.est_cost_usd,
        r.discovery_finished_at,
        r.crawl_finished_at,
        r.psi_finished_at
"""


class RunRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def latest_completed(self) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from v_latest_completed_run limit 1")
                row = cur.fetchone()
                if row is None:
                    return None

                cur.execute(
                    """
                    select cities
                    from sweep_jobs
                    where run_id = %s
                    order by created_at desc
                    limit 1
                    """,
                    (row["id"],),
                )
                sweep = cur.fetchone()

                if sweep and sweep.get("cities"):
                    row = dict(row)
                    row["geo_label"] = " • ".join(sweep["cities"])

                return row

    def list_runs(
        self,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * page_size

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from runs where kind = 'sweep'")
                total = cur.fetchone()["count"]

                cur.execute(
                    RUN_SELECT
                    + " where r.kind = 'sweep' "
                    + RUN_GROUP_BY
                    + """
                      order by r.started_at desc
                      limit %s offset %s
                      """,
                    (page_size, offset),
                )
                rows = cur.fetchall()

        return rows, total

    def funnel(self, run_id: UUID) -> dict[str, Any] | None:
        """Where a sweep's leads ended up, and why the rest aren't qualified."""
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select discovery_stats from runs where id = %s", (run_id,))
                run = cur.fetchone()
                if run is None:
                    return None
                # Latest verdict per lead, so a rescore updates older sweeps too.
                cur.execute(
                    """
                    select coalesce(latest.qualification, 'unscored') as qualification,
                           count(*) as count
                    from scores s
                    join v_latest_score latest on latest.place_id = s.place_id
                    where s.run_id = %s
                    group by 1
                    """,
                    (run_id,),
                )
                verdicts = {r["qualification"]: r["count"] for r in cur.fetchall()}
                cur.execute(
                    """
                    select
                        count(*) filter (where w.crawl_error = 'blocked_crawl_hang') as stalled,
                        count(*) filter (where left(w.crawl_error, 8) = 'blocked_'
                                           and w.crawl_error <> 'blocked_crawl_hang') as blocked,
                        count(*) filter (where cardinality(coalesce(w.emails_found, '{}'::text[])) > 0) as with_email
                    from scores s
                    join website_enrichment w on w.place_id = s.place_id
                    where s.run_id = %s
                    """,
                    (run_id,),
                )
                crawl = cur.fetchone()
        return {
            "total": sum(verdicts.values()),
            "verdicts": verdicts,
            "dropped": run["discovery_stats"] or {},
            "crawl": dict(crawl),
        }

    def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    RUN_SELECT
                    + """
                      where r.id = %s
                      """
                    + RUN_GROUP_BY,
                    (run_id,),
                )
                return cur.fetchone()
