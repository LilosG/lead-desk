begin;

create table sweep_jobs (
    id uuid primary key default gen_random_uuid(),
    run_id uuid references runs(id) on delete set null,

    status text not null default 'queued',
    stage text not null default 'queued',

    verticals text[] not null,
    cities text[],
    use_grid boolean not null default false,
    merge_results boolean not null default true,

    crawl_batch integer not null default 80,
    psi_batch integer not null default 20,

    cancel_requested boolean not null default false,
    worker_pid integer,
    child_pid integer,

    error_message text,

    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    updated_at timestamptz not null default now(),

    constraint sweep_jobs_status_valid check (
        status in (
            'queued',
            'running',
            'completed',
            'failed',
            'cancelled'
        )
    ),

    constraint sweep_jobs_stage_valid check (
        stage in (
            'queued',
            'discovery',
            'crawl',
            'psi',
            'finalize',
            'completed',
            'failed',
            'cancelled'
        )
    ),

    constraint sweep_jobs_crawl_batch_positive
        check (crawl_batch > 0),

    constraint sweep_jobs_psi_batch_positive
        check (psi_batch > 0)
);

create unique index sweep_jobs_single_active_idx
    on sweep_jobs ((1))
    where status in ('queued', 'running');

create index sweep_jobs_created_at_idx
    on sweep_jobs (created_at desc);

create index sweep_jobs_run_id_idx
    on sweep_jobs (run_id);

commit;
