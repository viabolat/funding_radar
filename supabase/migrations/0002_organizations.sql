-- 0002_organizations.sql — tenants, membership, and the per-org tables.

-- ---------------------------------------------------------------------------
-- organizations
-- ---------------------------------------------------------------------------
-- `profile` is JSONB so a new signup-form field never needs a migration. Every
-- key is optional. The shape actually read by the matcher and the notifier:
--
--   mission             text, free prose
--   notification_email  text
--   notify              { weekly_digest: bool, deadline_reminders: [int, ...] }
--   eligible_as         [text]      absent = unfiltered, NOT a default of {ong}
--   geography           { countries: [], regions: [], cross_border: [] }
--   matching            { <lang>: { core: [], wide: [], guards: [] } }
--   suggested_terms     same shape as `matching`, written by --calibrate,
--                       never read by the matcher, promoted by an operator
--
-- ABSENCE OF `matching` IS MEANINGFUL: the org is pending calibration and the
-- matcher skips it. An EMPTY list inside `matching` is a different thing — a
-- deliberately narrow profile that legitimately matches nothing. Do not
-- collapse the two, and do not default `matching` to '{}' at the column level.
create table if not exists public.organizations (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  created_at timestamptz not null default now(),
  profile    jsonb not null default '{}'
);

-- ---------------------------------------------------------------------------
-- organization_members — Supabase Auth users, one org each
-- ---------------------------------------------------------------------------
create table if not exists public.organization_members (
  org_id     uuid not null references public.organizations(id) on delete cascade,
  user_id    uuid not null references auth.users(id)           on delete cascade,
  role       text not null default 'member' check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id),
  -- One org per user. This is what makes current_org_id() single-valued and
  -- every RLS policy one comparison instead of a set membership test.
  unique (user_id)
);

create index if not exists org_members_user_idx on public.organization_members (user_id);

-- ---------------------------------------------------------------------------
-- org_call_matches — the materialised output of match.py
-- ---------------------------------------------------------------------------
create table if not exists public.org_call_matches (
  org_id           uuid not null references public.organizations(id) on delete cascade,
  call_id          text not null references public.calls(call_id)    on delete cascade,
  tier             text not null check (tier in ('core', 'wide')),
  matched_terms    text[] not null default '{}',
  match_reason     text   not null default '',   -- Romanian, the „De ce a apărut" copy
  score            int    not null default 0,

  -- When this call became new TO THIS ORG. Deliberately not calls.first_seen,
  -- which is when the warehouse first saw it and is identical for every org. A
  -- call that has sat in the warehouse for a year but matches a newly onboarded
  -- org today is new to that org, and its inbox has to say so.
  first_matched_at date not null default current_date,

  -- Which profile version produced this row. If an org's current profile hashes
  -- differently, its rows are stale and match.py rematches it. That is the
  -- entire recompute trigger — no queue, no worker, no webhook.
  profile_hash     text not null,
  computed_at      timestamptz not null default now(),
  primary key (org_id, call_id)
);

create index if not exists org_matches_org_idx   on public.org_call_matches (org_id, first_matched_at desc);
create index if not exists org_matches_stale_idx on public.org_call_matches (org_id, profile_hash);

-- ---------------------------------------------------------------------------
-- org_call_triage — user-authored, per org
-- ---------------------------------------------------------------------------
-- Triage moves here from triage.json / localStorage. It is still never written
-- by a watcher and still never lands in calls.json: the watchers rewrite that
-- file, so anything user-authored in it is lost on the next run.
create table if not exists public.org_call_triage (
  org_id     uuid not null references public.organizations(id) on delete cascade,
  call_id    text not null references public.calls(call_id)    on delete cascade,
  status     text not null default 'new'
               check (status in ('new', 'relevant', 'applied', 'not_relevant', 'review')),
  assignee   text,
  note       text    not null default '',
  reminder   boolean not null default false,
  snoozed    boolean not null default false,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id),
  primary key (org_id, call_id)
);

-- ---------------------------------------------------------------------------
-- org_notifications — the send log, and the idempotency guarantee
-- ---------------------------------------------------------------------------
-- The unique constraint IS the guarantee. A retried or double-scheduled run
-- gets a 409 from PostgREST instead of sending a second email. Application
-- logic is not trusted with this: email is the first channel in this project
-- that reaches someone who is not watching a GitHub repo, and the first mistake
-- that sends a client's contact list a duplicate blast is unrecoverable.
create table if not exists public.org_notifications (
  id         uuid primary key default gen_random_uuid(),
  org_id     uuid not null references public.organizations(id) on delete cascade,
  kind       text not null check (kind in ('weekly_digest', 'deadline_reminder')),
  dedupe_key text not null,   -- '2026-W37' for a digest; '<call_id>:14' for a reminder
  call_count int  not null default 0,
  resend_id  text,
  sent_at    timestamptz not null default now(),
  unique (org_id, kind, dedupe_key)
);

create index if not exists org_notifications_org_idx on public.org_notifications (org_id, sent_at desc);
