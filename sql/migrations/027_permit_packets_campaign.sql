-- EV Permits now covers four job types, so it is renamed Permit Packets.
-- The key (ev_permits) stays: queue rows, drafts and history point at it.
-- Safe to run twice: it sets the same values again.

begin;

update campaigns
set name = 'Permit Packets',
    description = 'Permit paperwork automation for electricians: EV chargers, panel and service upgrades, subpanels and 240 V circuits'
where key = 'ev_permits';

commit;
