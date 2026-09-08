-- 0003_rls.sql — row-level security, and the two RPCs RLS cannot express.
--
-- RLS is the ENTIRE security boundary of this system. There is no FastAPI, no
-- Express, no Edge Function behind which a bad policy could be caught. Read
-- every policy here as if it were the only thing standing between two tenants,
-- because it is.

-- ---------------------------------------------------------------------------
-- The one lookup every policy is built on.
-- ---------------------------------------------------------------------------
-- SECURITY DEFINER is load-bearing and not a convenience: this function is
-- called BY the policy on organization_members, so if it ran as the caller it
-- would re-enter that policy and recurse forever. Running as the owner skips
-- RLS on the read. `search_path` is pinned so the definer's rights cannot be
-- pointed at an attacker-supplied schema.
--
-- Single-valued because organization_members has unique(user_id).
create or replace function public.current_org_id()
  returns uuid
  language sql
  stable
  security definer
  set search_path = public, pg_temp
as $$
  select org_id from public.organization_members where user_id = auth.uid()
$$;

create or replace function public.current_user_is_owner()
  returns boolean
  language sql
  stable
  security definer
  set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.organization_members
     where user_id = auth.uid() and role = 'owner'
  )
$$;

revoke all on function public.current_org_id()        from public;
revoke all on function public.current_user_is_owner() from public;
grant execute on function public.current_org_id()        to authenticated;
grant execute on function public.current_user_is_owner() to authenticated;

-- ---------------------------------------------------------------------------
-- calls — shared reference data: every authenticated org reads it, nobody writes
-- ---------------------------------------------------------------------------
alter table public.calls enable row level security;

create policy calls_read_all on public.calls
  for select to authenticated
  using (true);

-- There is deliberately NO insert/update/delete policy on this table. With RLS
-- enabled, a role with no policy for an operation cannot perform it — the
-- absence below is the mechanism, not an omission. The watchers write with the
-- service_role key, which bypasses RLS entirely.

-- ---------------------------------------------------------------------------
-- organizations — your own row, and only an owner may change it
-- ---------------------------------------------------------------------------
alter table public.organizations enable row level security;

create policy organizations_read_own on public.organizations
  for select to authenticated
  using (id = public.current_org_id());

create policy organizations_update_own on public.organizations
  for update to authenticated
  using      (id = public.current_org_id() and public.current_user_is_owner())
  with check (id = public.current_org_id() and public.current_user_is_owner());

-- No insert policy: an organisation is created only through
-- create_organization() below. RLS cannot express "insert a row you are not yet
-- a member of" — you cannot be a member of a row that does not exist.

-- ---------------------------------------------------------------------------
-- organization_members
-- ---------------------------------------------------------------------------
alter table public.organization_members enable row level security;

create policy members_read_own_org on public.organization_members
  for select to authenticated
  using (org_id = public.current_org_id());

create policy members_insert_by_owner on public.organization_members
  for insert to authenticated
  with check (org_id = public.current_org_id() and public.current_user_is_owner());

create policy members_delete_by_owner on public.organization_members
  for delete to authenticated
  using (org_id = public.current_org_id() and public.current_user_is_owner());

-- No UPDATE policy, on purpose: with one, a member could set their own role to
-- 'owner'. Changing a role means delete plus insert, both of which already
-- require being an owner.

-- ---------------------------------------------------------------------------
-- org_call_matches — read-only to the org; written by match.py (service_role)
-- ---------------------------------------------------------------------------
alter table public.org_call_matches enable row level security;

create policy matches_read_own on public.org_call_matches
  for select to authenticated
  using (org_id = public.current_org_id());

-- ---------------------------------------------------------------------------
-- org_call_triage — the only table a user actually writes
-- ---------------------------------------------------------------------------
alter table public.org_call_triage enable row level security;

create policy triage_read_own on public.org_call_triage
  for select to authenticated
  using (org_id = public.current_org_id());

create policy triage_insert_own on public.org_call_triage
  for insert to authenticated
  with check (org_id = public.current_org_id());

create policy triage_update_own on public.org_call_triage
  for update to authenticated
  using      (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

-- No delete policy: triage is a record of what the team decided. Clearing a
-- decision is setting status back to 'new', which is an update.

-- ---------------------------------------------------------------------------
-- org_notifications — the org can see what it was sent; only notify.py writes
-- ---------------------------------------------------------------------------
alter table public.org_notifications enable row level security;

create policy notifications_read_own on public.org_notifications
  for select to authenticated
  using (org_id = public.current_org_id());

-- ---------------------------------------------------------------------------
-- RPC: create_organization
-- ---------------------------------------------------------------------------
-- The one thing PostgREST + RLS genuinely cannot do. Inserts the organisation
-- and the caller's owner membership in one transaction.
--
-- The profile is ALLOWLISTED, not passed through. Signup collects three fields;
-- a request body carrying `matching` or `suggested_terms` is ignored rather
-- than stored. The form not showing those fields is UI — this is the guarantee.
-- Keyword lists are a calibrated instrument (the CORE/WIDE split exists because
-- 'sănătate' in body prose pulled 32 junk rows and 'mental' is a substring of
-- 'environmental'); a badly filled list does not fail loudly, it produces a
-- plausible inbox of the wrong calls.
create or replace function public.create_organization(p_name text, p_profile jsonb default '{}')
  returns uuid
  language plpgsql
  security definer
  set search_path = public, pg_temp
as $$
declare
  v_user uuid := auth.uid();
  v_org  uuid;
  v_safe jsonb;
begin
  if v_user is null then
    raise exception 'not authenticated';
  end if;

  if p_name is null or btrim(p_name) = '' then
    raise exception 'organisation name is required';
  end if;

  v_safe := jsonb_strip_nulls(jsonb_build_object(
    'mission',            p_profile -> 'mission',
    'notification_email', p_profile -> 'notification_email',
    'notify',             coalesce(p_profile -> 'notify',
                                   '{"weekly_digest": true, "deadline_reminders": [14, 3]}'::jsonb)
  ));

  insert into public.organizations (name, profile)
       values (btrim(p_name), v_safe)
    returning id into v_org;

  -- unique(user_id) makes a second call from the same user fail here, which is
  -- the "one org per user" rule enforced by the schema rather than by a check.
  insert into public.organization_members (org_id, user_id, role)
       values (v_org, v_user, 'owner');

  return v_org;
end;
$$;

revoke all on function public.create_organization(text, jsonb) from public;
grant execute on function public.create_organization(text, jsonb) to authenticated;

-- ---------------------------------------------------------------------------
-- RPC: add_member
-- ---------------------------------------------------------------------------
-- Owner-only. The failure message is deliberately identical whether the address
-- has no account or already belongs to another organisation: this function is
-- callable by any authenticated user, so a specific error would turn it into an
-- oracle for "does this person have an account here".
create or replace function public.add_member(p_email text)
  returns void
  language plpgsql
  security definer
  set search_path = public, pg_temp
as $$
declare
  v_org    uuid := public.current_org_id();
  v_target uuid;
begin
  if v_org is null or not public.current_user_is_owner() then
    raise exception 'not permitted';
  end if;

  select id into v_target from auth.users where lower(email) = lower(btrim(p_email));

  if v_target is null then
    raise exception 'could not add that address';
  end if;

  begin
    insert into public.organization_members (org_id, user_id, role)
         values (v_org, v_target, 'member');
  exception when unique_violation then
    raise exception 'could not add that address';
  end;
end;
$$;

revoke all on function public.add_member(text) from public;
grant execute on function public.add_member(text) to authenticated;
