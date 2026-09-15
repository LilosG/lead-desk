alter table outreach_queue
    add column if not exists generation_model text,
    add column if not exists generation_prompt_version text,
    add column if not exists draft_generated_at timestamptz,
    add column if not exists gmail_draft_id text,
    add column if not exists gmail_message_id text,
    add column if not exists gmail_draft_created_at timestamptz;

create index if not exists idx_outreach_queue_gmail_draft_id
    on outreach_queue (gmail_draft_id)
    where gmail_draft_id is not null;
