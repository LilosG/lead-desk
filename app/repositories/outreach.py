from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class OutreachOperationLocked(RuntimeError):
    pass


class OutreachRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    _CANDIDATE_FROM_WHERE = """
        from v_lead_worklist w
        join v_lead_segments seg
          on seg.place_id = w.place_id
        left join v_lead_findings f
          on f.place_id = w.place_id
        where coalesce(f.needs_manual_check, false) = false
          and (
                cardinality(coalesce(w.emails_found, '{}'::text[])) > 0
                or w.phone is not null
              )
          and not exists (
                select 1
                from outreach_queue q
                where q.place_id = w.place_id
              )
          and (
                cardinality(coalesce(w.emails_found, '{}'::text[])) = 0
                or not exists (
                    select 1
                    from suppression s
                    where lower(s.email) = lower(coalesce(w.emails_found[1], ''))
                )
              )
    """

    _CANDIDATE_ORDER_BY = """
        order by
            case when cardinality(coalesce(w.emails_found, '{}'::text[])) > 0 then 0 else 1 end,
            -- Volume first, quality on top: nothing is excluded for a small
            -- review count; qualified, established and well-reviewed leads
            -- simply sort ahead of the rest.
            case when w.qualification = 'qualified' then 0 else 1 end,
            case when seg.established then 0 else 1 end,
            case when coalesce(w.review_count, 0) >= 15 then 0 else 1 end,
            w.total_score desc,
            w.review_count desc nulls last,
            w.name asc nulls last
    """

    def list_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        query = f"""
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
                w.review_count,
                seg.confirmed_trading,
                seg.established,
                seg.labels,
                seg.market,
                false as needs_manual_check,
                false as suppressed,
                false as already_queued
            {self._CANDIDATE_FROM_WHERE}
            {self._CANDIDATE_ORDER_BY}
            limit %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return cur.fetchall()

    def count_candidates(self) -> int:
        query = f"""
            select count(*) as count
            {self._CANDIDATE_FROM_WHERE}
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

        return int(row["count"])

    def candidate_readiness(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                w.place_id,
                w.name,
                w.review_count,
                w.phone,
                w.emails_found[1] as email,
                seg.confirmed_trading,
                seg.established,
                coalesce(f.needs_manual_check, false) as needs_manual_check,
                exists (
                    select 1
                    from suppression s
                    where lower(s.email) = lower(coalesce(w.emails_found[1], ''))
                ) as suppressed,
                exists (
                    select 1
                    from outreach_queue q
                    where q.place_id = w.place_id
                ) as already_queued
            from v_lead_worklist w
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

    def list_items(self, status: str | None = None) -> tuple[list[dict[str, Any]], int]:
        where = "where q.status = %s" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        query = f"""
            select
                q.id::text as id,
                q.place_id,
                b.name,
                b.city,
                b.vertical,
                w.total_score,
                w.tier,
                w.headline_gap,
                b.phone,
                we.emails_found[1] as email,
                q.channel,
                q.status,
                q.to_address,
                q.subject,
                q.body,
                q.claim_signal,
                q.verification_status,
                q.verification_note,
                q.generation_model,
                q.generation_prompt_version,
                q.draft_generated_at,
                q.gmail_draft_id,
                q.gmail_message_id,
                q.gmail_draft_created_at,
                exists (
                    select 1
                    from suppression s
                    where lower(s.email) = lower(coalesce(q.to_address, we.emails_found[1], ''))
                ) as suppressed,
                exists (
                    select 1
                    from gmail_draft_operations gdo
                    where gdo.queue_id = q.id and gdo.state = 'pending'
                ) as gmail_draft_pending,
                coalesce(f.needs_manual_check, false) as needs_manual_check,
                q.version,
                q.created_at,
                q.updated_at
            from outreach_queue q
            join businesses b on b.place_id = q.place_id
            left join v_lead_worklist w on w.place_id = q.place_id
            left join website_enrichment we on we.place_id = q.place_id
            left join v_lead_findings f on f.place_id = q.place_id
            {where}
            order by
                case q.status
                    when 'review_required' then 1
                    when 'draft_ready' then 2
                    when 'researching' then 3
                    when 'queued' then 4
                    else 5
                end,
                w.total_score desc nulls last,
                q.updated_at desc
        """
        count_query = f"select count(*) from outreach_queue q {where}"
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                cur.execute(count_query, params)
                total = cur.fetchone()['count']
        return rows, total

    def recent_generated_drafts(
        self,
        *,
        limit: int = 25,
        exclude_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            select
                q.id::text as id,
                b.name,
                q.body,
                q.claim_signal,
                q.verification_note,
                q.draft_generated_at,
                q.updated_at
            from outreach_queue q
            join businesses b
              on b.place_id = q.place_id
            where q.status in ('review_required', 'draft_ready', 'approved')
              and q.body is not null
              and (%s is null or q.id <> %s::uuid)
            order by
                q.draft_generated_at desc nulls last,
                q.updated_at desc
            limit %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        exclude_id,
                        exclude_id,
                        limit,
                    ),
                )
                return cur.fetchall()

    def prospect_context(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select
                b.place_id,
                b.name,
                b.phone,
                case
                    when b.manual_email is not null
                        then array_prepend(b.manual_email, coalesce(we.emails_found, '{}'::text[]))
                    else we.emails_found
                end as emails_found,
                coalesce(f.needs_manual_check, false) as needs_manual_check
            from businesses b
            left join website_enrichment we on we.place_id = b.place_id
            left join v_lead_findings f on f.place_id = b.place_id
            where b.place_id = %s
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def draft_context(self, item_id: str) -> dict[str, Any] | None:
        query = """
            select
                q.id::text as id,
                q.place_id,
                q.channel,
                q.status,
                q.to_address,
                q.version,
                b.name,
                b.city,
                b.vertical,
                b.website_url,
                w.headline_gap,
                w.total_score,
                w.tier,
                we.resolved_url,
                we.contact_page_url,
                we.crawl_error,
                coalesce(f.needs_manual_check, false) as needs_manual_check,
                audit.snapshot as audit_snapshot,
                audit.source_checked_at as audit_source_checked_at
            from outreach_queue q
            join businesses b on b.place_id = q.place_id
            left join v_lead_worklist w on w.place_id = q.place_id
            left join website_enrichment we on we.place_id = q.place_id
            left join v_lead_findings f on f.place_id = q.place_id
            left join lateral (
                select par.snapshot, par.source_checked_at
                from prospect_audit_reports par
                where par.place_id = q.place_id
                  and par.status = 'generated'
                order by par.created_at desc
                limit 1
            ) audit on true
            where q.id = %s::uuid
        """
        findings_query = """
            select signal, finding, observed, severity, points
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
                signal
            limit 12
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (item_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                result = dict(row)
                cur.execute(findings_query, (row['place_id'],))
                result['findings'] = cur.fetchall()
                return result

    def is_suppressed(self, email: str | None) -> bool:
        if not email:
            return False
        query = "select 1 from suppression where lower(email) = lower(%s) limit 1"
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (email,))
                return cur.fetchone() is not None

    def create_item(self, place_id: str, channel: str, to_address: str | None) -> dict[str, Any]:
        insert_query = """
            insert into outreach_queue (place_id, channel, to_address)
            values (%s, %s, %s)
            on conflict (place_id, channel) do nothing
            returning id::text as id, place_id, channel, status, to_address,
                      subject, body, claim_signal, verification_status,
                      verification_note, version, created_at, updated_at
        """
        select_query = """
            select id::text as id, place_id, channel, status, to_address,
                   subject, body, claim_signal, verification_status,
                   verification_note, version, created_at, updated_at
            from outreach_queue
            where place_id = %s and channel = %s
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(insert_query, (place_id, channel, to_address))
                    row = cur.fetchone()
                    if row is not None:
                        cur.execute(
                            """
                            insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                            values (%s::uuid, %s, 'queued', %s)
                            """,
                            (row['id'], place_id, Jsonb({'channel': channel, 'to_address': to_address})),
                        )
                        return row

                    # Queue creation is idempotent. Existing rows are never
                    # silently mutated by a second create request; edits go
                    # through the versioned update path.
                    cur.execute(select_query, (place_id, channel))
                    return cur.fetchone()

    def latest_audit_report(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select par.id::text as id, par.title, par.snapshot, b.name
            from prospect_audit_reports par
            join businesses b on b.place_id = par.place_id
            where par.place_id = %s and par.status = 'generated'
            order by par.created_at desc
            limit 1
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        query = """
            select id::text as id, place_id, channel, status, to_address,
                   subject, body, claim_signal, verification_status,
                   verification_note, generation_model,
                   generation_prompt_version, draft_generated_at,
                   gmail_draft_id, gmail_message_id, gmail_draft_created_at,
                   version, created_at, updated_at
            from outreach_queue
            where id = %s::uuid
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (item_id,))
                return cur.fetchone()

    def has_pending_gmail_operation(self, item_id: str) -> bool:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select 1
                    from gmail_draft_operations
                    where queue_id = %s::uuid and state = 'pending'
                    limit 1
                    """,
                    (item_id,),
                )
                return cur.fetchone() is not None

    @staticmethod
    def _assert_no_pending_gmail_operation(cur, item_id: str) -> None:
        cur.execute(
            """
            select 1
            from gmail_draft_operations
            where queue_id = %s::uuid and state = 'pending'
            limit 1
            """,
            (item_id,),
        )
        if cur.fetchone() is not None:
            raise OutreachOperationLocked(
                'outreach item is locked while Gmail draft creation is being reconciled'
            )

    def update_item(self, item_id: str, *, changes: dict[str, Any], expected_version: int) -> tuple[dict[str, Any] | None, bool]:
        editable = {
            'status', 'to_address', 'subject', 'body', 'claim_signal',
            'verification_status', 'verification_note'
        }
        safe = {key: value for key, value in changes.items() if key in editable}

        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, channel, status, to_address,
                               subject, body, claim_signal, verification_status,
                               verification_note, version, created_at, updated_at
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (item_id,),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None, False
                    if current['version'] != expected_version:
                        return current, True
                    self._assert_no_pending_gmail_operation(cur, item_id)

                    state = dict(current)
                    state.update(safe)
                    cur.execute(
                        """
                        update outreach_queue
                        set status=%s, to_address=%s, subject=%s, body=%s,
                            claim_signal=%s, verification_status=%s,
                            verification_note=%s, version=version+1,
                            contacted_at=case
                                when %s = 'contacted' then coalesce(contacted_at, now())
                                else contacted_at
                            end,
                            updated_at=now()
                        where id=%s::uuid
                        returning id::text as id, place_id, channel, status,
                                  to_address, subject, body, claim_signal,
                                  verification_status, verification_note,
                                  generation_model, generation_prompt_version,
                                  draft_generated_at, gmail_draft_id,
                                  gmail_message_id, gmail_draft_created_at,
                                  version, created_at, updated_at
                        """,
                        (
                            state['status'], state['to_address'], state['subject'],
                            state['body'], state['claim_signal'],
                            state['verification_status'], state['verification_note'],
                            state['status'],
                            item_id,
                        ),
                    )
                    updated = cur.fetchone()
                    cur.execute(
                        """
                        insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                        values (%s::uuid, %s, 'updated', %s)
                        """,
                        (item_id, updated['place_id'], Jsonb(safe)),
                    )
        return updated, False

    def record_no_outreach_finding(
        self,
        item_id: str,
        *,
        expected_version: int,
        claim_signal: str | None,
        verification_status: str,
        verification_note: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Persist the no-finding state and clear stale draft-generation metadata atomically."""
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, version
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (item_id,),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None, False
                    if current["version"] != expected_version:
                        return current, True

                    self._assert_no_pending_gmail_operation(cur, item_id)

                    cur.execute(
                        """
                        update outreach_queue
                        set subject = null,
                            body = null,
                            claim_signal = %s,
                            verification_status = %s,
                            verification_note = %s,
                            status = 'no_outreach_finding',
                            generation_model = null,
                            generation_prompt_version = null,
                            draft_generated_at = null,
                            gmail_draft_id = null,
                            gmail_message_id = null,
                            gmail_draft_created_at = null,
                            version = version + 1,
                            updated_at = now()
                        where id = %s::uuid
                        returning id::text as id, place_id, channel, status,
                                  to_address, subject, body, claim_signal,
                                  verification_status, verification_note,
                                  generation_model, generation_prompt_version,
                                  draft_generated_at, gmail_draft_id,
                                  gmail_message_id, gmail_draft_created_at,
                                  version, created_at, updated_at
                        """,
                        (
                            claim_signal,
                            verification_status,
                            verification_note,
                            item_id,
                        ),
                    )
                    updated = cur.fetchone()

                    cur.execute(
                        """
                        insert into outreach_queue_events (
                            queue_id, place_id, event_type, changes
                        )
                        values (%s::uuid, %s, 'no_outreach_finding', %s)
                        """,
                        (
                            item_id,
                            updated["place_id"],
                            Jsonb(
                                {
                                    "claim_signal": claim_signal,
                                    "verification_status": verification_status,
                                    "generation_model": None,
                                    "generation_prompt_version": None,
                                    "draft_generated_at": None,
                                }
                            ),
                        ),
                    )

        return updated, False

    def record_generated_draft(
        self,
        item_id: str,
        *,
        expected_version: int,
        subject: str,
        body: str,
        claim_signal: str | None,
        verification_status: str,
        verification_note: str,
        generation_model: str,
        prompt_version: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, version
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (item_id,),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None, False
                    if current['version'] != expected_version:
                        return current, True
                    self._assert_no_pending_gmail_operation(cur, item_id)

                    cur.execute(
                        """
                        update outreach_queue
                        set subject = %s,
                            body = %s,
                            claim_signal = %s,
                            verification_status = %s,
                            verification_note = %s,
                            status = 'review_required',
                            generation_model = %s,
                            generation_prompt_version = %s,
                            draft_generated_at = now(),
                            gmail_draft_id = null,
                            gmail_message_id = null,
                            gmail_draft_created_at = null,
                            version = version + 1,
                            updated_at = now()
                        where id = %s::uuid
                        returning id::text as id, place_id, channel, status,
                                  to_address, subject, body, claim_signal,
                                  verification_status, verification_note,
                                  generation_model, generation_prompt_version,
                                  draft_generated_at, gmail_draft_id,
                                  gmail_message_id, gmail_draft_created_at,
                                  version, created_at, updated_at
                        """,
                        (
                            subject,
                            body,
                            claim_signal,
                            verification_status,
                            verification_note,
                            generation_model,
                            prompt_version,
                            item_id,
                        ),
                    )
                    updated = cur.fetchone()
                    cur.execute(
                        """
                        insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                        values (%s::uuid, %s, 'draft_generated', %s)
                        """,
                        (
                            item_id,
                            updated['place_id'],
                            Jsonb({
                                'claim_signal': claim_signal,
                                'verification_status': verification_status,
                                'generation_model': generation_model,
                                'prompt_version': prompt_version,
                            }),
                        ),
                    )
        return updated, False

    def begin_gmail_draft_operation(
        self,
        item_id: str,
        *,
        expected_version: int,
        message_id_header: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Persist intent before the external Gmail side effect.

        Returns (operation, version_conflict). Existing operations for the same
        queue/version are returned instead of creating a second side effect.
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, place_id, version, gmail_draft_id
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (item_id,),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None, False
                    if current['version'] != expected_version:
                        return {'queue_version': current['version']}, True

                    cur.execute(
                        """
                        select id::text as id, queue_id::text as queue_id,
                               queue_version, message_id_header, state,
                               gmail_draft_id, gmail_message_id, error_message,
                               created_at, updated_at, completed_at
                        from gmail_draft_operations
                        where queue_id = %s::uuid and queue_version = %s
                        order by created_at desc
                        limit 1
                        """,
                        (item_id, expected_version),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        operation = dict(existing)
                        operation['created_now'] = False
                        return operation, False

                    if current.get('gmail_draft_id'):
                        raise OutreachOperationLocked('a Gmail draft already exists for this queue item')

                    cur.execute(
                        """
                        insert into gmail_draft_operations (
                            queue_id, queue_version, message_id_header
                        ) values (%s::uuid, %s, %s)
                        returning id::text as id, queue_id::text as queue_id,
                                  queue_version, message_id_header, state,
                                  gmail_draft_id, gmail_message_id, error_message,
                                  created_at, updated_at, completed_at
                        """,
                        (item_id, expected_version, message_id_header),
                    )
                    operation = dict(cur.fetchone())
                    operation['created_now'] = True
                    cur.execute(
                        """
                        insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                        values (%s::uuid, %s, 'gmail_draft_pending', %s)
                        """,
                        (
                            item_id,
                            current['place_id'],
                            Jsonb({
                                'operation_id': operation['id'],
                                'message_id_header': message_id_header,
                                'queue_version': expected_version,
                            }),
                        ),
                    )
                    return operation, False

    def reopen_gmail_draft_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update gmail_draft_operations
                        set state = 'pending', error_message = null, updated_at = now()
                        where id = %s::uuid and state = 'failed'
                        returning id::text as id, queue_id::text as queue_id,
                                  queue_version, message_id_header, state,
                                  gmail_draft_id, gmail_message_id, error_message,
                                  created_at, updated_at, completed_at
                        """,
                        (operation_id,),
                    )
                    return cur.fetchone()

    def record_gmail_operation_error(
        self,
        operation_id: str,
        *,
        error_message: str,
        uncertain: bool,
    ) -> None:
        state = 'pending' if uncertain else 'failed'
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update gmail_draft_operations
                        set state = %s, error_message = %s, updated_at = now()
                        where id = %s::uuid and state <> 'created'
                        """,
                        (state, error_message[:1000], operation_id),
                    )

    def complete_gmail_draft_operation(
        self,
        operation_id: str,
        *,
        draft_id: str,
        message_id: str | None,
    ) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select id::text as id, queue_id::text as queue_id,
                               queue_version, message_id_header, state,
                               gmail_draft_id, gmail_message_id
                        from gmail_draft_operations
                        where id = %s::uuid
                        for update
                        """,
                        (operation_id,),
                    )
                    operation = cur.fetchone()
                    if operation is None:
                        return None

                    cur.execute(
                        """
                        select id::text as id, place_id, channel, status,
                               to_address, subject, body, claim_signal,
                               verification_status, verification_note,
                               generation_model, generation_prompt_version,
                               draft_generated_at, gmail_draft_id,
                               gmail_message_id, gmail_draft_created_at,
                               version, created_at, updated_at
                        from outreach_queue
                        where id = %s::uuid
                        for update
                        """,
                        (operation['queue_id'],),
                    )
                    current = cur.fetchone()
                    if current is None:
                        return None

                    if operation['state'] == 'created':
                        return current
                    if operation['state'] != 'pending':
                        raise OutreachOperationLocked(
                            'Gmail draft operation is not pending and cannot be completed'
                        )

                    # The queue is locked against edits while an operation is
                    # pending, so the payload associated with queue_version is
                    # still the exact payload that was sent to Gmail.
                    cur.execute(
                        """
                        update outreach_queue
                        set gmail_draft_id = %s,
                            gmail_message_id = %s,
                            gmail_draft_created_at = now(),
                            version = version + 1,
                            updated_at = now()
                        where id = %s::uuid
                        returning id::text as id, place_id, channel, status,
                                  to_address, subject, body, claim_signal,
                                  verification_status, verification_note,
                                  generation_model, generation_prompt_version,
                                  draft_generated_at, gmail_draft_id,
                                  gmail_message_id, gmail_draft_created_at,
                                  version, created_at, updated_at
                        """,
                        (draft_id, message_id, operation['queue_id']),
                    )
                    updated = cur.fetchone()

                    cur.execute(
                        """
                        update gmail_draft_operations
                        set state = 'created',
                            gmail_draft_id = %s,
                            gmail_message_id = %s,
                            error_message = null,
                            completed_at = now(),
                            updated_at = now()
                        where id = %s::uuid
                        """,
                        (draft_id, message_id, operation_id),
                    )
                    cur.execute(
                        """
                        insert into outreach_queue_events (queue_id, place_id, event_type, changes)
                        values (%s::uuid, %s, 'gmail_draft_created', %s)
                        """,
                        (
                            operation['queue_id'],
                            updated['place_id'],
                            Jsonb({
                                'operation_id': operation_id,
                                'gmail_draft_id': draft_id,
                                'gmail_message_id': message_id,
                                'message_id_header': operation['message_id_header'],
                            }),
                        ),
                    )
                    return updated

    def find_email_item(self, place_id: str) -> dict[str, Any] | None:
        query = """
            select id::text as id, status, body, claim_signal, gmail_draft_id, version
            from outreach_queue
            where place_id = %s and channel = 'email'
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (place_id,))
                return cur.fetchone()
