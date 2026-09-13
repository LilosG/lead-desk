begin;

create unique index if not exists runs_single_active_run_idx
    on runs ((1))
    where status = 'running'
      and finished_at is null;

commit;
