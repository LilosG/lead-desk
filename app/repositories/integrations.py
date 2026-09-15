from __future__ import annotations

from datetime import datetime, timedelta, timezone

from psycopg_pool import ConnectionPool


class IntegrationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def get_credential(self, provider: str) -> dict | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select provider, account_email, refresh_token_ciphertext,
                           scopes, connected_at, updated_at
                    from integration_credentials
                    where provider = %s
                    """,
                    (provider,),
                )
                return cur.fetchone()

    def upsert_credential(
        self,
        provider: str,
        *,
        account_email: str,
        refresh_token_ciphertext: bytes,
        scopes: list[str],
    ) -> dict:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into integration_credentials (
                            provider,
                            account_email,
                            refresh_token_ciphertext,
                            scopes
                        )
                        values (%s, %s, %s, %s)
                        on conflict (provider) do update
                        set account_email = excluded.account_email,
                            refresh_token_ciphertext = excluded.refresh_token_ciphertext,
                            scopes = excluded.scopes,
                            updated_at = now()
                        returning provider, account_email, scopes, connected_at, updated_at
                        """,
                        (
                            provider,
                            account_email,
                            refresh_token_ciphertext,
                            scopes,
                        ),
                    )
                    return cur.fetchone()

    def delete_credential(self, provider: str) -> bool:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "delete from integration_credentials where provider = %s",
                        (provider,),
                    )
                    return cur.rowcount > 0

    def create_oauth_state(
        self,
        provider: str,
        *,
        state_hash: str,
        ttl_minutes: int = 10,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        delete from integration_oauth_states
                        where expires_at < now() or consumed_at is not null
                        """
                    )
                    cur.execute(
                        """
                        insert into integration_oauth_states (
                            state_hash,
                            provider,
                            expires_at
                        ) values (%s, %s, %s)
                        """,
                        (state_hash, provider, expires_at),
                    )

    def consume_oauth_state(self, provider: str, *, state_hash: str) -> bool:
        with self.pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update integration_oauth_states
                        set consumed_at = now()
                        where state_hash = %s
                          and provider = %s
                          and consumed_at is null
                          and expires_at >= now()
                        returning state_hash
                        """,
                        (state_hash, provider),
                    )
                    return cur.fetchone() is not None
