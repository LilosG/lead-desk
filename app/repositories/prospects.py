import math
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


SITE_REFRESH_COLUMNS = {
    "site_signals", "psi_performance", "psi_seo", "psi_accessibility", "psi_best_practices",
    "psi_lcp_ms", "psi_cls", "psi_mobile_friendly", "raw_psi_payload",
}
JSON_COLUMNS = {"site_signals", "raw_psi_payload"}


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
        qualification: str | None = None,
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

        if qualification:
            conditions.append(sql.SQL("w.qualification = %(qualification)s"))
            params["qualification"] = qualification

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
                    w.scored_at,
                    w.fit_score,
                    w.qualification
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
                coalesce(f.needs_manual_check, false) as needs_manual_check,
                w.fit_score,
                w.qualification,
                w.qualification_reasons,
                b.site_checked_at
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

    def get_google_reviews(self, place_id: str) -> list[dict[str, Any]]:
        """The reviews Google returned for this business in its last sweep."""
        query = "select raw_places_payload -> 'reviews' as reviews from businesses where place_id = %s"
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                row = cur.fetchone()
        return (row or {}).get("reviews") or []

    def get_demo_details(self, place_id: str) -> dict[str, Any] | None:
        """Listing details a demo page can show: opening hours and street address."""
        query = """
            select hours_json, street, formatted_address, postal_code
            from businesses
            where place_id = %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def nearby_towns(
        self,
        lat: float,
        lng: float,
        *,
        exclude: list[str] | None = None,
        radius_km: float = 30.0,
        limit: int = 8,
    ) -> list[str]:
        """Towns of businesses already swept near a point, nearest first.

        Reads only our own table: no Google calls. A bounding box keeps the
        scan small before the exact distance is computed.
        """
        lat_pad = radius_km / 110.574
        lng_pad = radius_km / max(1.0, 111.320 * abs(math.cos(math.radians(lat))))
        query = """
            select city, min(dist_km) as dist_km
            from (
                select initcap(trim(city)) as city,
                       6371 * 2 * asin(sqrt(
                           power(sin(radians(lat - %(lat)s) / 2), 2)
                           + cos(radians(%(lat)s)) * cos(radians(lat))
                             * power(sin(radians(lng - %(lng)s) / 2), 2)
                       )) as dist_km
                from businesses
                where lat between %(lat_lo)s and %(lat_hi)s
                  and lng between %(lng_lo)s and %(lng_hi)s
                  and coalesce(trim(city), '') <> ''
            ) nearby
            where dist_km <= %(radius)s
              and lower(city) <> all(%(exclude)s)
            group by city
            order by min(dist_km)
            limit %(limit)s
        """
        params = {
            "lat": lat, "lng": lng, "radius": radius_km, "limit": limit,
            "lat_lo": lat - lat_pad, "lat_hi": lat + lat_pad,
            "lng_lo": lng - lng_pad, "lng_hi": lng + lng_pad,
            "exclude": [str(x).strip().lower() for x in (exclude or []) if x],
        }
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [row["city"] for row in cur.fetchall()]

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
                site_source,
                raw_psi_payload,
                offering_page_count,
                offering_titles,
                location_page_count,
                sitemap_url_count,
                has_online_booking,
                booking_provider,
                site_signals
            from website_enrichment
            where place_id = %s
        """

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def set_manual_contact(
        self,
        place_id: str,
        *,
        email: str | None,
        site_checked: bool,
    ) -> bool:
        """Record what Mike confirmed by hand. Returns False for an unknown lead."""
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update businesses
                        set manual_email = coalesce(%s, manual_email),
                            site_checked_at = case when %s then now() else site_checked_at end
                        where place_id = %s
                        """,
                        (email, site_checked, place_id),
                    )
                    return cur.rowcount == 1

    def save_site_refresh(self, place_id: str, fields: dict[str, Any]) -> None:
        """Store an on-demand site check. Columns come from SITE_REFRESH_COLUMNS."""
        columns = [c for c in fields if c in SITE_REFRESH_COLUMNS]
        if not columns:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in columns
        )
        values = [Jsonb(fields[c]) if c in JSON_COLUMNS else fields[c] for c in columns]
        query = sql.SQL("update website_enrichment set {} where place_id = %s").format(assignments)
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(query, [*values, place_id])

    def market_peers(
        self,
        place_id: str,
        *,
        vertical: str | None,
        market: str | None,
        city: str | None,
        limit: int = 3,
    ) -> dict[str, Any] | None:
        """Comparable businesses for the local comparison in an audit report.

        Comparable means: same niche, same city, not a franchise, and (when
        there are enough of them) the same Google category, so a med spa isn't
        compared with a resort spa or an IV clinic with 7,000 reviews.
        """
        if not vertical or not (market or city):
            return None

        query = """
            select
                b.place_id,
                b.name,
                b.city,
                b.primary_type,
                b.rating,
                coalesce(b.review_count, 0) as review_count,
                (b.website_url is not null or we.site_source = 'found') as has_website,
                coalesce(b.is_franchise, false) as is_franchise,
                b.last_review_days,
                b.has_hours,
                b.photo_count,
                we.is_reachable,
                we.has_ssl,
                we.psi_performance,
                we.has_online_booking,
                we.has_contact_form,
                we.offering_page_count,
                we.offering_titles,
                we.location_page_count,
                we.has_localbusiness_schema
            from businesses b
            join v_lead_segments seg
              on seg.place_id = b.place_id
            left join website_enrichment we
              on we.place_id = b.place_id
            where exists (
                    select 1
                    from business_vertical_memberships bvm
                    where bvm.place_id = b.place_id
                      and bvm.vertical = %(vertical)s
                )
              and (
                    (%(market)s::text is not null and seg.market = %(market)s)
                    or (%(city)s::text is not null and lower(b.city) = lower(%(city)s))
                  )
            limit 3000
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {"vertical": vertical, "market": market, "city": city})
                rows = cur.fetchall()

        target = next((r for r in rows if r["place_id"] == place_id), None)
        peers = [r for r in rows if not r["is_franchise"]]

        def narrow(candidates, key, value, minimum):
            if not value:
                return candidates
            subset = [r for r in candidates if (r.get(key) or "").lower() == str(value).lower()]
            return subset if len(subset) >= minimum else candidates

        peers = narrow(peers, "city", city, 8)
        primary_type = target.get("primary_type") if target else None
        peers = narrow(peers, "primary_type", primary_type, 5)

        reviews = sorted(int(r["review_count"]) for r in peers)
        if not reviews:
            return None
        mid = len(reviews) // 2
        median = reviews[mid] if len(reviews) % 2 else (reviews[mid - 1] + reviews[mid]) / 2
        leaders = sorted(
            (r for r in peers if r["place_id"] != place_id),
            key=lambda r: (-int(r["review_count"]), r["name"] or ""),
        )[:limit]
        cities = {(r.get("city") or "").strip() for r in peers if r.get("city")}
        return {
            "sample_size": len(peers),
            "median_reviews": median,
            "scope_city": next(iter(cities)) if len(cities) == 1 else None,
            # Every comparable business except this one, with the public
            # signals the report benchmarks against (reviews, speed, pages...).
            "peers": [dict(r) for r in peers if r["place_id"] != place_id],
            "leaders": [
                {
                    "name": r["name"],
                    "rating": r["rating"],
                    "review_count": int(r["review_count"]),
                    "has_website": bool(r["has_website"]),
                }
                for r in leaders
            ],
        }

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
                count(*) filter (where w.qualification = 'qualified') as qualified,
                count(*) filter (where w.qualification = 'call_first') as call_first,
                count(*) filter (where w.qualification = 'verify_first') as verify_first,
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
