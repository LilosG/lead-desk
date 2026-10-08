from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class ProspectRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def list_prospects(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        tier: str | None,
        city: str | None,
        vertical: str | None,
        contact: str | None,
        trading: bool | None,
        established: bool | None,
        category_opportunity: bool | None,
        label: str | None = None,
        market: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[sql.Composable] = []
        params: dict[str, Any] = {}

        if search:
            conditions.append(
                sql.SQL(
                    """
                    (
                        w.name ilike %(search)s
                        or w.city ilike %(search)s
                        or w.phone ilike %(search)s
                        or w.formatted_address ilike %(search)s
                    )
                    """
                )
            )
            params["search"] = f"%{search}%"

        if tier:
            conditions.append(sql.SQL("w.tier = %(tier)s"))
            params["tier"] = tier

        if city:
            conditions.append(sql.SQL("w.city = %(city)s"))
            params["city"] = city

        if vertical:
            conditions.append(
                sql.SQL(
                    """
                    exists (
                        select 1
                        from business_vertical_memberships bvm
                        where bvm.place_id = w.place_id
                          and bvm.vertical = %(vertical)s
                    )
                    """
                )
            )
            params["vertical"] = vertical

        if contact == "email":
            conditions.append(
                sql.SQL(
                    "cardinality(coalesce(w.emails_found, '{}'::text[])) > 0"
                )
            )
        elif contact == "phone":
            conditions.append(
                sql.SQL(
                    """
                    w.phone is not null
                    and cardinality(coalesce(w.emails_found, '{}'::text[])) = 0
                    """
                )
            )
        elif contact == "none":
            conditions.append(
                sql.SQL(
                    """
                    w.phone is null
                    and cardinality(coalesce(w.emails_found, '{}'::text[])) = 0
                    """
                )
            )

        if trading is not None:
            conditions.append(sql.SQL("seg.confirmed_trading = %(trading)s"))
            params["trading"] = trading

        if established is not None:
            conditions.append(sql.SQL("seg.established = %(established)s"))
            params["established"] = established

        if category_opportunity is not None:
            conditions.append(
                sql.SQL("seg.category_opportunity = %(category_opportunity)s")
            )
            params["category_opportunity"] = category_opportunity

        if label:
            conditions.append(sql.SQL("%(label)s = any(seg.labels)"))
            params["label"] = label

        if market:
            conditions.append(sql.SQL("seg.market = %(market)s"))
            params["market"] = market

        where_clause = (
            sql.SQL(" where ") + sql.SQL(" and ").join(conditions)
            if conditions
            else sql.SQL("")
        )

        base = sql.SQL(
            """
            from v_lead_worklist w
            join businesses b
              on b.place_id = w.place_id
            join v_lead_segments seg
              on seg.place_id = w.place_id
            left join v_lead_findings f
              on f.place_id = w.place_id
            """
        )

        count_query = sql.SQL("select count(*) ") + base + where_clause

        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size

        list_query = (
            sql.SQL(
                """
                select
                    w.place_id,
                    w.name,
                    w.city,
                    w.vertical,
                    w.total_score,
                    w.tier,
                    w.headline_gap,
                    w.phone,
                    w.emails_found[1] as email,
                    w.website_url,
                    w.rating,
                    w.review_count,
                    w.psi_performance,
                    w.cms_detected,
                    b.business_status,
                    b.last_review_days,
                    b.recent_reviews_90d,
                    seg.confirmed_trading,
                    seg.category_opportunity,
                    seg.established,
                    seg.real_gap_count,
                    seg.labels,
                    seg.market,
                    coalesce(f.needs_manual_check, false) as needs_manual_check,
                    w.scored_at
                """
            )
            + base
            + where_clause
            + sql.SQL(
                """
                order by
                    w.total_score desc,
                    w.review_count desc nulls last,
                    w.name asc nulls last
                limit %(limit)s
                offset %(offset)s
                """
            )
        )

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(count_query, params)
                total = cur.fetchone()["count"]
                cur.execute(list_query, params)
                rows = cur.fetchall()

        return rows, total

    def get_prospect(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                b.place_id,
                b.name,
                b.vertical,
                b.primary_type,
                b.types,
                b.business_status,
                b.formatted_address,
                b.city,
                b.state,
                b.postal_code,
                b.lat,
                b.lng,
                b.phone,
                w.emails_found[1] as email,
                b.website_url,
                b.google_maps_uri,
                b.rating,
                b.review_count,
                b.last_review_days,
                b.recent_reviews_90d,
                b.has_hours,
                b.photo_count,
                w.total_score,
                w.tier,
                w.headline_gap,
                w.gbp_gap_score,
                w.website_gap_score,
                w.reachability_score,
                w.scored_at,
                seg.confirmed_trading,
                seg.category_opportunity,
                seg.established,
                seg.real_gap_count,
                seg.labels,
                seg.market,
                f.what_to_fix,
                coalesce(f.major_issues, 0) as major_issues,
                coalesce(f.needs_manual_check, false) as needs_manual_check
            from v_lead_worklist w
            join businesses b
              on b.place_id = w.place_id
            join v_lead_segments seg
              on seg.place_id = w.place_id
            left join v_lead_findings f
              on f.place_id = w.place_id
            where w.place_id = %s
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def get_website_audit(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                checked_at,
                resolved_url,
                http_status,
                is_reachable,
                has_ssl,
                redirects_to,
                title,
                title_length,
                meta_description,
                meta_desc_length,
                h1_text,
                h1_count,
                word_count,
                page_count_estimate,
                has_localbusiness_schema,
                schema_types,
                nap_phone_on_site,
                nap_address_on_site,
                nap_matches_gbp,
                has_service_pages,
                has_city_pages,
                has_gbp_link,
                has_contact_form,
                contact_page_url,
                emails_found,
                phones_found,
                social_profiles,
                cms_detected,
                is_template_builder,
                psi_performance,
                psi_seo,
                psi_accessibility,
                psi_best_practices,
                psi_lcp_ms,
                psi_cls,
                psi_mobile_friendly,
                crawl_error,
                offering_page_count,
                offering_titles,
                location_page_count,
                sitemap_url_count,
                has_online_booking,
                booking_provider
            from website_enrichment
            where place_id = %s
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def market_peers(
        self,
        place_id: str,
        *,
        vertical: str | None,
        market: str | None,
        city: str | None,
        limit: int = 3,
    ) -> dict[str, Any] | None:
        """Same-niche businesses in the same searched market, for comparison.

        Uses the searched market when known, else the business's own city.
        Returns the market median, sample size and the top businesses by
        review count (excluding the prospect itself).
        """
        if not vertical or not (market or city):
            return None

        if market:
            scope = "seg.market = %(market)s"
        else:
            scope = "w.city = %(city)s"

        query = f"""
            with peers as (
                select
                    w.place_id,
                    w.name,
                    w.rating,
                    coalesce(w.review_count, 0) as review_count,
                    w.website_url is not null as has_website
                from v_lead_worklist w
                join v_lead_segments seg
                  on seg.place_id = w.place_id
                where exists (
                        select 1
                        from business_vertical_memberships bvm
                        where bvm.place_id = w.place_id
                          and bvm.vertical = %(vertical)s
                    )
                  and {scope}
            )
            select
                (select count(*) from peers) as sample_size,
                (select percentile_cont(0.5) within group (order by review_count)
                   from peers) as median_reviews,
                coalesce(
                    (
                        select json_agg(t order by t.review_count desc, t.name)
                        from (
                            select name, rating, review_count, has_website
                            from peers
                            where place_id <> %(place_id)s
                            order by review_count desc, name
                            limit %(limit)s
                        ) t
                    ),
                    '[]'::json
                ) as leaders
        """
        params = {
            "vertical": vertical,
            "market": market,
            "city": city,
            "place_id": place_id,
            "limit": limit,
        }
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def get_findings(self, place_id: str) -> list[dict[str, Any]]:
        query = """
            select
                category,
                severity,
                points,
                finding,
                signal,
                observed
            from v_lead_audit_detail
            where place_id = %s
            order by
                case severity
                    when 'critical' then 1
                    when 'high' then 2
                    when 'medium' then 3
                    when 'low' then 4
                    else 5
                end,
                points desc,
                category,
                signal
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchall()

    def get_workflow(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                status,
                priority,
                owner,
                next_action,
                next_action_at,
                notes,
                version,
                created_at,
                updated_at
            from prospect_workflow
            where place_id = %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def get_workflow_events(
        self,
        place_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = """
            select
                id::text as id,
                event_type,
                changes,
                created_at
            from prospect_workflow_events
            where place_id = %s
            order by created_at desc, id desc
            limit %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id, limit))
                return cur.fetchall()

    def update_workflow(
        self,
        place_id: str,
        *,
        changes: dict[str, Any],
        expected_version: int,
    ) -> tuple[dict[str, Any] | None, bool]:
        editable = {
            "status",
            "priority",
            "owner",
            "next_action",
            "next_action_at",
            "notes",
        }
        safe_changes = {
            key: value for key, value in changes.items() if key in editable
        }

        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "select 1 from businesses where place_id = %s",
                        (place_id,),
                    )
                    if cur.fetchone() is None:
                        return None, False

                    cur.execute(
                        """
                        select
                            status,
                            priority,
                            owner,
                            next_action,
                            next_action_at,
                            notes,
                            version,
                            created_at,
                            updated_at
                        from prospect_workflow
                        where place_id = %s
                        for update
                        """,
                        (place_id,),
                    )
                    current = cur.fetchone()

                    if current is None:
                        if expected_version != 0:
                            return None, True

                        state = {
                            "status": "new",
                            "priority": "normal",
                            "owner": None,
                            "next_action": None,
                            "next_action_at": None,
                            "notes": None,
                        }
                        state.update(safe_changes)

                        cur.execute(
                            """
                            insert into prospect_workflow (
                                place_id,
                                status,
                                priority,
                                owner,
                                next_action,
                                next_action_at,
                                notes
                            ) values (%s, %s, %s, %s, %s, %s, %s)
                            returning
                                status,
                                priority,
                                owner,
                                next_action,
                                next_action_at,
                                notes,
                                version,
                                created_at,
                                updated_at
                            """,
                            (
                                place_id,
                                state["status"],
                                state["priority"],
                                state["owner"],
                                state["next_action"],
                                state["next_action_at"],
                                state["notes"],
                            ),
                        )
                        updated = cur.fetchone()
                        event_type = "created"
                    else:
                        if current["version"] != expected_version:
                            return current, True

                        state = dict(current)
                        state.update(safe_changes)
                        cur.execute(
                            """
                            update prospect_workflow
                            set
                                status = %s,
                                priority = %s,
                                owner = %s,
                                next_action = %s,
                                next_action_at = %s,
                                notes = %s,
                                version = version + 1,
                                updated_at = now()
                            where place_id = %s
                            returning
                                status,
                                priority,
                                owner,
                                next_action,
                                next_action_at,
                                notes,
                                version,
                                created_at,
                                updated_at
                            """,
                            (
                                state["status"],
                                state["priority"],
                                state["owner"],
                                state["next_action"],
                                state["next_action_at"],
                                state["notes"],
                                place_id,
                            ),
                        )
                        updated = cur.fetchone()
                        event_type = "updated"

                    cur.execute(
                        """
                        insert into prospect_workflow_events (
                            place_id,
                            event_type,
                            changes
                        ) values (%s, %s, %s)
                        """,
                        (place_id, event_type, Jsonb(safe_changes)),
                    )

        return updated, False

    def filter_meta(self) -> dict[str, Any]:
        query = """
            select
                array_agg(distinct w.city order by w.city) filter (
                    where w.city is not null and w.city <> ''
                ) as cities,
                array_agg(distinct w.vertical order by w.vertical) filter (
                    where w.vertical is not null and w.vertical <> ''
                ) as verticals,
                array_agg(distinct seg.market order by seg.market) filter (
                    where seg.market is not null and seg.market <> ''
                ) as markets,
                count(*) as total_prospects
            from v_lead_worklist w
            join v_lead_segments seg
              on seg.place_id = w.place_id
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

        return {
            "cities": row["cities"] or [],
            "verticals": row["verticals"] or [],
            "markets": row["markets"] or [],
            "tiers": ["A", "B", "C", "D"],
            "total_prospects": row["total_prospects"],
        }

    def overview_counts(self) -> dict[str, Any]:
        query = """
            select
                count(*) as prospects,
                count(*) filter (where w.tier = 'A') as tier_a,
                count(*) filter (where w.tier = 'B') as tier_b,
                count(*) filter (where w.tier = 'C') as tier_c,
                count(*) filter (where w.tier = 'D') as tier_d,
                count(*) filter (
                    where cardinality(coalesce(w.emails_found, '{}'::text[])) > 0
                ) as emailable,
                count(*) filter (
                    where w.phone is not null
                      and cardinality(coalesce(w.emails_found, '{}'::text[])) = 0
                ) as phone_only,
                count(*) filter (
                    where w.phone is null
                      and cardinality(coalesce(w.emails_found, '{}'::text[])) = 0
                ) as no_contact,
                count(*) filter (where w.website_url is null) as no_website,
                count(*) filter (where seg.confirmed_trading) as confirmed_trading,
                count(*) filter (where seg.category_opportunity) as category_opportunity,
                count(*) filter (where seg.established) as established,
                count(*) filter (
                    where coalesce(f.needs_manual_check, false)
                ) as manual_check,
                count(*) filter (
                    where seg.established
                      and cardinality(coalesce(w.emails_found, '{}'::text[])) > 0
                ) as established_emailable,
                count(*) filter (
                    where seg.established
                      and w.phone is not null
                      and cardinality(coalesce(w.emails_found, '{}'::text[])) = 0
                ) as established_phone_only
            from v_lead_worklist w
            join v_lead_segments seg
              on seg.place_id = w.place_id
            left join v_lead_findings f
              on f.place_id = w.place_id
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()
