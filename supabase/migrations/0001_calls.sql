-- 0001_calls.sql — the warehouse table.
--
-- Holds EVERY live call from every source, unfiltered by organisation. What
-- calls.json holds today is one organisation's view of this table; per-org
-- relevance is computed separately into org_call_matches.
--
-- Nothing here is ever deleted. A call that vanishes from its source becomes
-- status='withdrawn'; a call whose deadline passes becomes 'expired'. This
-- deliberately reverses calls_store.py's rule ("a call that disappears from its
-- source is dropped from the feed"), which was correct when the feed WAS the
-- store: a dashboard listing dead calls is worse than one that forgets them.
-- The warehouse keeps both properties by filtering status='open' at read time
-- instead of destroying the row, so historical calls survive and triage written
-- against a withdrawn call is not orphaned.

create table if not exists public.calls (
  call_id           text primary key,
  source            text        not null,   -- eu_sedia | adieuronest | mipe_calendar | mipe
  title             text        not null,
  programme         text        not null default '',
  deadline          date,
  announced         boolean     not null default false,
  budget            text        not null default '',
  tags              text[]      not null default '{}',
  match_reason      text        not null default '',
  link              text        not null default '',
  raw               jsonb       not null default '{}',

  -- The language the title and prose are written in, set at ingest. Matching
  -- terms are per-language (see organizations.profile.matching): the EU feed is
  -- English and the two Romanian feeds are Romanian, and a term list calibrated
  -- for one is noise against the other. 'screening' is CORE in the Romanian list
  -- and WIDE in the English one; applying either list to both changes what
  -- matches.
  lang              text        not null default 'ro' check (lang in ('ro', 'en')),

  -- Matching surfaces, precomputed at ingest by the fetcher that knows the
  -- source's shape. This is what lets ONE source-agnostic matcher preserve the
  -- calibrated two-tier distinction: a mission term is signal anywhere in the
  -- record, a broad term like 'sănătate' is signal only in a name. Matching the
  -- broad terms against body prose pulled 32 junk rows during calibration.
  search_core       text        not null default '',   -- title + callTitle + eligibility prose
  search_wide       text        not null default '',   -- title + programme only

  status            text        not null default 'open'
                      check (status in ('open', 'expired', 'withdrawn')),

  -- When the WAREHOUSE first saw this call — the same for every organisation.
  -- The per-org "new to us" date is org_call_matches.first_matched_at.
  first_seen        date        not null default current_date,

  last_seen_at      timestamptz not null default now(),
  -- Which run last returned this row. A withdrawal sweep marks everything from
  -- one source that this run did NOT return; comparing against the run id is
  -- what makes that a single statement rather than a diff.
  last_seen_run_id  uuid,
  withdrawn_at      timestamptz,
  updated_at        timestamptz not null default now()
);

create index if not exists calls_status_idx        on public.calls (status);
create index if not exists calls_source_run_idx    on public.calls (source, last_seen_run_id);
create index if not exists calls_open_deadline_idx on public.calls (deadline) where status = 'open';
create index if not exists calls_lang_idx          on public.calls (lang);
