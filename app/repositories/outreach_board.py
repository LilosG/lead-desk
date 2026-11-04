"""The Outreach page's data: every prospect, in exactly one stage.

Queue items take their stage from v_outreach_stage. Prospects not yet in the
queue are placed by what's stopping them. Rows, tab counts and filters all come
from the one CTE, so a tab's count always matches what the tab shows.
"""
from typing import Any

from psycopg_pool import ConnectionPool

from app.campaigns import COOLDOWN_DAYS, EV_PERMITS, EV_SERVICE_SQL, simple_permit_cities

_LEAD_RULES = {
    EV_PERMITS: """
          and b.vertical = 'electrician'
          and coalesce(w.qualification, '') <> 'franchise'
          and (coalesce(b.city, '') || ', ' || coalesce(b.state, '')) <> all(%(simple_cities)s)
          and (
                coalesce((we.site_signals ->> 'ev_service')::boolean, false)
                or concat_ws(' ', array_to_string(we.offering_titles, ' '), we.title, we.meta_description)
                   ~* %(ev_pattern)s
              )
    """,
}


def cooldown_join(place: str, campaign: str) -> str:
    """The latest touch from another campaign, while its cooldown is running.

    A Gmail draft counts from the moment it exists: it may go out at any time.
    """
    last_touch = "coalesce(oq.contacted_at, oq.gmail_draft_created_at)"
    return f"""
        left join lateral (
            select c.name as cooldown_campaign,
                   {last_touch} + make_interval(days => %(cooldown_days)s) as cooldown_until
            from outreach_queue oq
            join campaigns c on c.key = oq.campaign_key
            where oq.place_id = {place}
              and oq.campaign_key <> {campaign}
              and {last_touch} > now() - make_interval(days => %(cooldown_days)s)
              and (oq.contacted_at is not null or oq.status not in ('archived', 'suppressed'))
            order by {last_touch} desc
            limit 1
        ) cd on true
    """


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
            q.version,
            cd.cooldown_campaign,
            cd.cooldown_until
        from outreach_queue q
        join v_outreach_stage vs on vs.id = q.id
        join businesses b on b.place_id = q.place_id
        left join v_lead_worklist w on w.place_id = q.place_id
        {queue_cooldown}
        where q.campaign_key = %(campaign)s

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
            null,
            cd.cooldown_campaign,
            cd.cooldown_until
        from v_lead_worklist w
        join businesses b on b.place_id = w.place_id
        left join v_lead_findings f on f.place_id = w.place_id
        left join website_enrichment we on we.place_id = w.place_id
        {candidate_cooldown}
        where not exists (
                select 1 from outreach_queue q
                where q.place_id = w.place_id and q.campaign_key = %(campaign)s
              )
          and not exists (
                select 1 from outreach_queue q
                where q.place_id = w.place_id and q.status = 'suppressed'
              )
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
          {lead_rule}
    )
"""


def board_cte(campaign: str) -> str:
    return (
        _BOARD_CTE
        .replace("{queue_cooldown}", cooldown_join("q.place_id", "%(campaign)s"))
        .replace("{candidate_cooldown}", cooldown_join("w.place_id", "%(campaign)s"))
        .replace("{lead_rule}", _LEAD_RULES.get(campaign, ""))
    )


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


def _scope(campaign: str) -> dict[str, Any]:
    return {
        "campaign": campaign,
        "cooldown_days": COOLDOWN_DAYS,
        "simple_cities": simple_permit_cities(),
        "ev_pattern": EV_SERVICE_SQL,
    }


class OutreachBoardRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    @staticmethod
    def _filters(
        *,
        campaign: str,
        q: str | None,
        vertical: str | None,
        market: str | None,
        qualified_only: bool,
    ) -> tuple[str, dict[str, Any]]:
        where = ["true"]
        params = _scope(campaign)
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
        campaign: str,
        stage: str,
        q: str | None,
        vertical: str | None,
        market: str | None,
        qualified_only: bool,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        where, params = self._filters(
            campaign=campaign, q=q, vertical=vertical, market=market, qualified_only=qualified_only,
        )
        order = _ORDER_BY.get(stage, _DEFAULT_ORDER)
        cte = board_cte(campaign)
        rows_query = f"""
            {cte}
            select *
            from board
            where stage = %(stage)s and {where}
            order by {order}
            limit %(limit)s offset %(offset)s
        """
        counts_query = f"""
            {cte}
            select stage, count(*) as count
            from board
            where {where}
            group by stage
        """
        facets_query = f"""
            {cte}
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
                cur.execute(facets_query, _scope(campaign))
                facets = cur.fetchone()
        return {
            "rows": rows,
            "counts": counts,
            "verticals": facets["verticals"] or [],
            "markets": facets["markets"] or [],
        }

    def item(self, item_id: str) -> dict[str, Any] | None:
        query = f"""
            select
                q.id::text as id, q.place_id, q.channel, q.status, q.to_address,
                q.subject, q.body, q.claim_signal, q.verification_status,
                q.verification_note, q.generation_model, q.draft_generated_at,
                q.gmail_draft_id, q.gmail_message_id, q.gmail_draft_created_at,
                q.gmail_draft_left_at, q.contacted_at, q.version, q.updated_at,
                q.campaign_key,
                b.name, b.city, vs.stage, cd.cooldown_campaign, cd.cooldown_until,
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
            {cooldown_join("q.place_id", "q.campaign_key")}
            where q.id = %(id)s::uuid
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {"id": item_id, "cooldown_days": COOLDOWN_DAYS})
                return cur.fetchone()

    def campaigns(self) -> list[dict[str, Any]]:
        query = """
            select
                c.key, c.name, c.description,
                count(q.id) filter (where q.contacted_at is not null
                                       or q.status in ('contacted', 'replied')) as sent,
                count(q.id) filter (where q.status = 'replied') as replied,
                count(q.id) filter (where q.status = 'suppressed') as opted_out
            from campaigns c
            left join outreach_queue q on q.campaign_key = c.key
            where c.active
            group by c.key, c.name, c.description, c.sort_order
            order by c.sort_order
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()

    def campaign_results(self, campaign: str) -> list[dict[str, Any]]:
        query = """
            select
                coalesce(b.market, 'No market') as market,
                coalesce(b.vertical, 'unknown') as vertical,
                count(*) as sent,
                count(*) filter (where q.status = 'replied') as replied
            from outreach_queue q
            join businesses b on b.place_id = q.place_id
            where q.campaign_key = %s
              and (q.contacted_at is not null or q.status in ('contacted', 'replied'))
            group by 1, 2
            order by sent desc, market, vertical
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (campaign,))
                return cur.fetchall()
