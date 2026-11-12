"""The Outreach page's data: every prospect, in exactly one stage.

Queue items take their stage from v_outreach_stage. Prospects not yet in the
queue are placed by what's stopping them. Rows, tab counts and filters all come
from the one CTE, so a tab's count always matches what the tab shows.
"""
from typing import Any

from psycopg_pool import ConnectionPool

from app.campaigns import COOLDOWN_DAYS, EV_PERMITS, PERMIT_JOBS_SQL

# Who the Permit Packets offer can go to. A site that doesn't show permit work
# still gets the email, worded as a question, and ranks after the shops that do.
# Cities with a simple EV permit are included: the other job types still need
# drawings there, and the email makes no city claim for them.
_PERMIT_AUDIENCE = """(
          b.vertical = 'electrician'
          and (b.primary_type = 'electrician' or 'electrician' = any(b.types)
               or b.name ~* 'electric' or jsonb_array_length(coalesce(we.site_signals -> 'permit_jobs', '[]'::jsonb)) > 0)
          and coalesce(w.qualification, '') <> 'franchise'
    )"""
# The job types the site shows, as a json array. Rows read before the
# permit_jobs signal existed have none until the backfill runs.
_PERMIT_JOBS = """(case when jsonb_typeof(we.site_signals -> 'permit_jobs') = 'array'
               then we.site_signals -> 'permit_jobs' else '[]'::jsonb end)"""
# A service page for any job type, not just a blog post that mentions it.
_SERVICE_PAGE = """(we.site_signals ->> 'ev_strength' = 'page'
               or (jsonb_typeof(we.site_signals -> 'permit_job_pages') = 'object'
                   and we.site_signals -> 'permit_job_pages' <> '{}'::jsonb))"""
# Shops that clearly sell permit work get the Permit Packets pitch before the SEO one.
# ev_service covers EV leads read before permit_jobs was recorded.
_PERMIT_ELIGIBLE = f"""(
          {_PERMIT_AUDIENCE}
          and (
                jsonb_array_length({_PERMIT_JOBS}) > 0
                or coalesce((we.site_signals ->> 'ev_service')::boolean, false)
                or concat_ws(' ', array_to_string(we.offering_titles, ' '), we.title, we.meta_description)
                   ~* %(permit_pattern)s
              )
    )"""
_LEAD_RULES = {EV_PERMITS: f"and {_PERMIT_AUDIENCE}"}


def cooldown_join(place: str, campaign: str) -> str:
    """The latest touch from another campaign, while its cooldown is running.

    A Gmail draft counts from the moment it exists: it may go out at any time.
    A reply restarts the clock, so a live conversation doesn't get a second pitch.
    """
    last_touch = ("greatest(oq.contacted_at, oq.gmail_draft_created_at, "
                  "case when oq.status = 'replied' then oq.updated_at end)")
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
            cd.cooldown_until,
            we.site_signals ->> 'ev_strength' as ev_strength,
            we.site_signals -> 'ev_brands' as ev_brands,
            {permit_jobs} as permit_jobs,
            {service_page} as has_service_page,
            {permit_eligible} as permit_eligible,
            coalesce(fu.drafted, 0) as follow_ups_drafted,
            coalesce(fu.open, false) as follow_up_open,
            coalesce(fu.last_sent, q.contacted_at) as last_touch_at,
            {has_audit_q} as has_audit,
            {mockup_q} as mockup_status
        from outreach_queue q
        join v_outreach_stage vs on vs.id = q.id
        join businesses b on b.place_id = q.place_id
        left join v_lead_worklist w on w.place_id = q.place_id
        left join website_enrichment we on we.place_id = q.place_id
        left join lateral (
            select count(*) as drafted,
                   bool_or(f.sent_at is null) as open,
                   max(f.sent_at) as last_sent
            from outreach_follow_ups f
            where f.queue_id = q.id and f.gmail_draft_id is not null
        ) fu on true
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
            cd.cooldown_until,
            we.site_signals ->> 'ev_strength',
            we.site_signals -> 'ev_brands',
            {permit_jobs},
            {service_page},
            {permit_eligible},
            0,
            false,
            null::timestamptz,
            {has_audit_w},
            {mockup_w}
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


def _has_audit(place: str) -> str:
    return (f"exists (select 1 from prospect_audit_reports ar "
            f"where ar.place_id = {place} and ar.status = 'generated')")


def _mockup(place: str) -> str:
    """'published', 'ready' (built, not yet published) or null."""
    return (f"(select case when bool_or(ds.status = 'published') then 'published' else 'ready' end "
            f"from prospect_demo_sites ds where ds.place_id = {place} "
            f"and ds.status in ('published', 'ready_for_review'))")


def board_cte(campaign: str) -> str:
    return (
        _BOARD_CTE
        .replace("{has_audit_q}", _has_audit("q.place_id"))
        .replace("{mockup_q}", _mockup("q.place_id"))
        .replace("{has_audit_w}", _has_audit("w.place_id"))
        .replace("{mockup_w}", _mockup("w.place_id"))
        .replace("{queue_cooldown}", cooldown_join("q.place_id", "%(campaign)s"))
        .replace("{candidate_cooldown}", cooldown_join("w.place_id", "%(campaign)s"))
        .replace("{lead_rule}", _LEAD_RULES.get(campaign, ""))
        .replace("{permit_jobs}", _PERMIT_JOBS)
        .replace("{service_page}", _SERVICE_PAGE)
        .replace("{permit_eligible}", _PERMIT_ELIGIBLE)
    )


_ORDER_BY = {
    "in_gmail": "gmail_draft_created_at desc nulls last",
    "contacted": ("case when follow_up_open then 2 when follow_ups_drafted >= 2 then 3 "
                  "when last_touch_at + make_interval(days => "
                  "case when follow_ups_drafted = 0 then 3 else 4 end) <= now() then 0 else 1 end, "
                  "last_touch_at"),
    "replied": "updated_at desc",
    "closed": "updated_at desc",
}
_DEFAULT_ORDER = (
    "case when qualification = 'qualified' then 0 else 1 end, "
    "total_score desc nulls last, review_count desc nulls last, name"
)
# Permit leads get pitched Permit Packets first, so they drop behind leads only SEO can reach.
_SEO_ORDER = f"case when permit_eligible then 1 else 0 end, {_DEFAULT_ORDER}"
# The SEO score rewards a weak site, which says nothing about buying permit
# automation. The best lead is a busy shop that clearly sells several permit jobs.
_EV_ORDER = (
    "case when permit_eligible then 0 else 1 end, "
    "jsonb_array_length(coalesce(permit_jobs, '[]'::jsonb)) desc, "
    "case when has_service_page then 0 else 1 end, "
    "case when jsonb_array_length(coalesce(ev_brands, '[]'::jsonb)) > 0 then 0 else 1 end, "
    "fit_score desc nulls last, review_count desc nulls last, name"
)


def default_order(campaign: str) -> str:
    return _EV_ORDER if campaign == EV_PERMITS else _SEO_ORDER


def _scope(campaign: str) -> dict[str, Any]:
    return {
        "campaign": campaign,
        "cooldown_days": COOLDOWN_DAYS,
        "permit_pattern": PERMIT_JOBS_SQL,
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
        # Automate review thresholds: 50+ for Permit Packets, 25+ for SEO & Websites
        min_reviews = 25
        where.append(f"(kind <> 'candidate' or coalesce(review_count, 0) >= {min_reviews} or ({campaign == 'ev_permits'} and coalesce(review_count, 0) >= 10 and jsonb_array_length(coalesce(we.site_signals -> 'permit_jobs', '[]'::jsonb)) > 0))")

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
        order = _ORDER_BY.get(stage, default_order(campaign))
        if stage == "to_prep":
            # Leads you've already started (audit built or mockup made) come first.
            order = f"case when has_audit or mockup_status is not null then 0 else 1 end, {order}"
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
                q.campaign_key, q.angle, q.generation_prompt_version,
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

    def angle_results(self, campaign: str) -> list[dict[str, Any]]:
        query = """
            select
                q.angle,
                count(*) as sent,
                count(*) filter (where q.status = 'replied') as replied
            from outreach_queue q
            where q.campaign_key = %s
              and (q.contacted_at is not null or q.status in ('contacted', 'replied'))
            group by 1
            order by sent desc
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (campaign,))
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
