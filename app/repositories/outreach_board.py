"""The Outreach page's data: every prospect, in exactly one stage.

Queue items take their stage from v_outreach_stage. Prospects not yet in the
queue are placed by what's stopping them. Rows, tab counts and filters all come
from the one CTE, so a tab's count always matches what the tab shows.
"""
from typing import Any

from psycopg_pool import ConnectionPool

_BOARD_CTE = """
    with board as (
        select
            'queue' as kind,
            q.id::text as id,
            q.place_id,
            vs.stage,
            q.status,
            q.channel,
            coalesce(q.to_address, w.emails_found[1]) as email,
            coalesce(b.phone, w.phone) as phone,
            b.name,
            b.city,
            b.vertical,
            b.market,
            w.tier,
            w.total_score,
            w.fit_score,
            w.qualification,
            w.headline_gap,
            b.review_count,
            q.subject is not null and q.body is not null as has_draft,
            q.verification_status,
            q.verification_note,
            q.gmail_draft_created_at,
            q.gmail_message_id,
            q.gmail_draft_left_at,
            q.contacted_at,
            q.updated_at,
            q.version
        from outreach_queue q
        join v_outreach_stage vs on vs.id = q.id
        join businesses b on b.place_id = q.place_id
        left join v_lead_worklist w on w.place_id = q.place_id

        union all

        select
            'candidate',
            null,
            w.place_id,
            case
                when coalesce(f.needs_manual_check, false) then 'verify'
                when cardinality(coalesce(w.emails_found, '{}'::text[])) > 0 then 'to_prep'
                else 'call'
            end,
            null,
            null,
            w.emails_found[1],
            w.phone,
            w.name,
            w.city,
            w.vertical,
            b.market,
            w.tier,
            w.total_score,
            w.fit_score,
            w.qualification,
            w.headline_gap,
            w.review_count,
            false,
            null,
            null,
            null::timestamptz,
            null,
            null::timestamptz,
            null::timestamptz,
            w.scored_at,
            null
        from v_lead_worklist w
        join businesses b on b.place_id = w.place_id
        left join v_lead_findings f on f.place_id = w.place_id
        where not exists (select 1 from outreach_queue q where q.place_id = w.place_id)
          and (w.qualification is null or w.qualification <> 'no_contact')
          and (
                coalesce(f.needs_manual_check, false)
                or cardinality(coalesce(w.emails_found, '{}'::text[])) > 0
                or w.phone is not null
              )
          and not exists (
                select 1 from suppression s
                where lower(s.email) = lower(coalesce(w.emails_found[1], ''))
              )
    )
"""

_ORDER_BY = {
    "in_gmail": "gmail_draft_created_at desc nulls last",
    "contacted": "contacted_at desc nulls last",
    "replied": "updated_at desc",
    "closed": "updated_at desc",
}
_DEFAULT_ORDER = (
    "case when qualification = 'qualified' then 0 else 1 end, "
    "total_score desc nulls last, review_count desc nulls last, name"
)


class OutreachBoardRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    @staticmethod
    def _filters(
        *,
        q: str | None,
        vertical: str | None,
        market: str | None,
        qualified_only: bool,
    ) -> tuple[str, dict[str, Any]]:
        where = ["true"]
        params: dict[str, Any] = {}
        if q:
            where.append("(name ilike %(q)s or city ilike %(q)s or email ilike %(q)s or phone ilike %(q)s)")
            params["q"] = f"%{q}%"
        if vertical:
            where.append("vertical = %(vertical)s")
            params["vertical"] = vertical
        if market:
            where.append("market = %(market)s")
            params["market"] = market
        if qualified_only:
            # Only narrows the list to work next; later stages are already committed to.
            where.append("(stage <> 'to_prep' or qualification = 'qualified')")
        return " and ".join(where), params

    def board(
        self,
        *,
        stage: str,
        q: str | None,
        vertical: str | None,
        market: str | None,
        qualified_only: bool,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        where, params = self._filters(q=q, vertical=vertical, market=market, qualified_only=qualified_only)
        order = _ORDER_BY.get(stage, _DEFAULT_ORDER)
        rows_query = f"""
            {_BOARD_CTE}
            select *
            from board
            where stage = %(stage)s and {where}
            order by {order}
            limit %(limit)s offset %(offset)s
        """
        counts_query = f"""
            {_BOARD_CTE}
            select stage, count(*) as count
            from board
            where {where}
            group by stage
        """
        facets_query = f"""
            {_BOARD_CTE}
            select
                array_agg(distinct vertical order by vertical)
                    filter (where vertical is not null) as verticals,
                array_agg(distinct market order by market)
                    filter (where market is not null) as markets
            from board
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(rows_query, {
                    **params, "stage": stage, "limit": page_size,
                    "offset": (page - 1) * page_size,
                })
                rows = cur.fetchall()
                cur.execute(counts_query, params)
                counts = {r["stage"]: r["count"] for r in cur.fetchall()}
                cur.execute(facets_query)
                facets = cur.fetchone()
        return {
            "rows": rows,
            "counts": counts,
            "verticals": facets["verticals"] or [],
            "markets": facets["markets"] or [],
        }

    def item(self, item_id: str) -> dict[str, Any] | None:
        query = """
            select
                q.id::text as id, q.place_id, q.channel, q.status, q.to_address,
                q.subject, q.body, q.claim_signal, q.verification_status,
                q.verification_note, q.generation_model, q.draft_generated_at,
                q.gmail_draft_id, q.gmail_message_id, q.gmail_draft_created_at,
                q.gmail_draft_left_at, q.contacted_at, q.version, q.updated_at,
                b.name, b.city, vs.stage,
                exists (
                    select 1 from gmail_draft_operations o
                    where o.queue_id = q.id and o.state = 'pending'
                ) as gmail_draft_pending,
                exists (
                    select 1 from suppression s
                    where lower(s.email) = lower(coalesce(q.to_address, ''))
                ) as suppressed
            from outreach_queue q
            join v_outreach_stage vs on vs.id = q.id
            join businesses b on b.place_id = q.place_id
            where q.id = %s::uuid
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (item_id,))
                return cur.fetchone()
