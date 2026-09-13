from typing import Any

from psycopg import sql
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
        contact: str | None,
        trading: bool | None,
        established: bool | None,
        category_opportunity: bool | None,
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
            conditions.append(
                sql.SQL("seg.confirmed_trading = %(trading)s")
            )
            params["trading"] = trading

        if established is not None:
            conditions.append(
                sql.SQL("seg.established = %(established)s")
            )
            params["established"] = established

        if category_opportunity is not None:
            conditions.append(
                sql.SQL(
                    "seg.category_opportunity = %(category_opportunity)s"
                )
            )
            params["category_opportunity"] = category_opportunity

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

                    coalesce(
                        f.needs_manual_check,
                        false
                    ) as needs_manual_check,

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

                f.what_to_fix,
                coalesce(f.major_issues, 0) as major_issues,
                coalesce(
                    f.needs_manual_check,
                    false
                ) as needs_manual_check

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

                crawl_error

            from website_enrichment
            where place_id = %s
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
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

    def filter_meta(self) -> dict[str, Any]:
        query = """
            select
                array_agg(
                    distinct w.city
                    order by w.city
                ) filter (
                    where w.city is not null
                      and w.city <> ''
                ) as cities,

                array_agg(
                    distinct w.vertical
                    order by w.vertical
                ) filter (
                    where w.vertical is not null
                      and w.vertical <> ''
                ) as verticals,

                count(*) as total_prospects

            from v_lead_worklist w
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

        return {
            "cities": row["cities"] or [],
            "verticals": row["verticals"] or [],
            "tiers": ["A", "B", "C", "D"],
            "total_prospects": row["total_prospects"],
        }

    def overview_counts(self) -> dict[str, Any]:
        query = """
            select
                count(*) as prospects,

                count(*) filter (
                    where w.tier = 'A'
                ) as tier_a,

                count(*) filter (
                    where w.tier = 'B'
                ) as tier_b,

                count(*) filter (
                    where w.tier = 'C'
                ) as tier_c,

                count(*) filter (
                    where w.tier = 'D'
                ) as tier_d,

                count(*) filter (
                    where cardinality(
                        coalesce(w.emails_found, '{}'::text[])
                    ) > 0
                ) as emailable,

                count(*) filter (
                    where w.phone is not null
                      and cardinality(
                          coalesce(w.emails_found, '{}'::text[])
                      ) = 0
                ) as phone_only,

                count(*) filter (
                    where w.phone is null
                      and cardinality(
                          coalesce(w.emails_found, '{}'::text[])
                      ) = 0
                ) as no_contact,

                count(*) filter (
                    where w.website_url is null
                ) as no_website,

                count(*) filter (
                    where seg.confirmed_trading
                ) as confirmed_trading,

                count(*) filter (
                    where seg.category_opportunity
                ) as category_opportunity,

                count(*) filter (
                    where seg.established
                ) as established,

                count(*) filter (
                    where coalesce(f.needs_manual_check, false)
                ) as manual_check,

                count(*) filter (
                    where seg.established
                      and cardinality(
                          coalesce(w.emails_found, '{}'::text[])
                      ) > 0
                ) as established_emailable,

                count(*) filter (
                    where seg.established
                      and w.phone is not null
                      and cardinality(
                          coalesce(w.emails_found, '{}'::text[])
                      ) = 0
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
