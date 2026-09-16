alter table outreach_queue
  drop constraint if exists outreach_queue_status_valid;

alter table outreach_queue
  add constraint outreach_queue_status_valid
  check (
    status in (
      'queued',
      'researching',
      'review_required',
      'no_outreach_finding',
      'draft_ready',
      'approved',
      'contacted',
      'replied',
      'archived',
      'suppressed'
    )
  );
