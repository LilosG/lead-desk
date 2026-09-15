create table if not exists integration_credentials (
    provider text primary key,
    account_email text not null,
    refresh_token_ciphertext bytea not null,
    scopes text[] not null default '{}'::text[],
    connected_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists integration_oauth_states (
    state_hash text primary key,
    provider text not null,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists idx_integration_oauth_states_expiry
    on integration_oauth_states (expires_at)
    where consumed_at is null;
