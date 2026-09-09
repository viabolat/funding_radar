-- 0005_calls_eligible_as.sql — who a call is open to.
--
-- The adieuronest feed publishes an applicant vocabulary per row (`categorii`:
-- companii, universitati, autoritati, ong, persoane, scoli, cultura, sanatate).
-- Until Phase C that vocabulary was consumed inside the fetcher, which dropped
-- every row not tagged {ong, sanatate} — the seed organisation's answer to an
-- organisation question, applied to the whole warehouse.
--
-- "Can WE apply for this" is a property of the pair (call, organisation), so
-- the call keeps the facts and the profile keeps the answer:
--   calls.eligible_as              what the source says the call is open to
--   organizations.profile.eligible_as   what an org declares itself to be
-- and match.py intersects them. An EMPTY array means the source published no
-- applicant vocabulary at all (the EU dataset does not), which is not the same
-- as "open to nobody" — the matcher treats it as "this dimension is unknown for
-- this call" and does not filter on it. An absent `eligible_as` on the PROFILE
-- side likewise means unfiltered, and specifically NOT a default of {ong}: a
-- new tenant must not inherit the seed organisation's eligibility.
--
-- Not folded into search_core/search_wide, which are substring surfaces. This
-- is a set intersection over a closed vocabulary, and burying it in prose would
-- make `ong` match `congres`.

alter table public.calls
  add column if not exists eligible_as text[] not null default '{}';

-- GIN, because every query against this column is an overlap test
-- (eligible_as && '{ong,sanatate}'), not an equality one.
create index if not exists calls_eligible_as_idx on public.calls using gin (eligible_as);
