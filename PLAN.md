# PLAN.md — Phase E/F, responsive dashboard, and a notification pipeline

> **Nothing in this document has been built.** It is a proposal, written against a verified
> reading of the repo as of 2026-09-10 (branch `staging`, HEAD `c7a923e`). No code, config or
> migration was changed to produce it.
>
> It supersedes a proposal for a mobile-first PWA with Web Push, Tailwind, TanStack
> Query/Virtual and a Twilio SMS/WhatsApp channel. Why it supersedes it — and why each route
> was chosen over the alternatives — is in **§ Why these routes**, at the end.

---

## Context

Funding Radar today is two Python watchers plus a **read-only, single-user** React dashboard.
The watchers run as scheduled GitHub Actions, notify by opening GitHub Issues, and write a flat
`calls.json` (58 matched records, feed version 1) that the dashboard fetches. Triage state —
status, note, assignee, reminder, snooze — lives in one browser's `localStorage`, so two people
in the same organisation cannot see each other's work and clearing site data destroys it.

Phases A–C of the approved multi-org migration
(`~/.claude-professional/plans/harmonic-fluttering-hamming.md`) are committed and pushed: schema
+ RLS (`5110585`), `warehouse.py` dual-write (`ed47498`), org-agnostic scraping with `match.py`
(`e2060a9`). **Phases D, E, F and G have not started** — there is no `notify.py`, no
Supabase-backed dashboard, no signup, no auth.

Two commercial documents landed during this session and raise the stakes on notification:
`PRICING.md` makes *delivery frequency* the tier discriminator (€29 weekly → €799 real-time),
and `CONTRACTS.md` commits to white-label customisation and a self-hosted Docker hand-off.

### Decisions taken

| Decision | Choice |
|---|---|
| **Scope** | Approved Phase E + F first. Responsive work ships *inside* E as CSS. PWA + Web Push become Phase H, planned but not built here. |
| **Tenancy** | Ship single-org. `unique (user_id)` stays; multi-org is written up as its own costed phase so PRICING Tier 3/4 has a path but is not sold ahead of the schema. |
| **Styling** | No Tailwind. `nocturne.css` stays vendored and untouched; real `@media` breakpoints and 48×48 touch targets go into `app.css`. Zero new styling dependencies. |
| **Compute** | Scheduled GitHub Actions, as the approved Phase F specifies. Ceiling is weekly digest + daily deadline reminders, hours-imprecise. "Instant" as sold is flagged, not built. |

---

## What the earlier proposal assumed that is not true today

Verified against the repo, not inferred.

| Assumption | Reality |
|---|---|
| `web/` uses Tailwind CSS | No Tailwind. `web/package.json` has exactly three runtime deps: `react`, `react-dom`, `@phosphor-icons/react`. |
| `web/` uses `@supabase/supabase-js` | Not installed. The dashboard fetches a static `calls.json` and has no network write path. |
| TanStack Query / TanStack Virtual are in use | Neither is installed. |
| Bundle budget "< 220 KB gzipped" | Current shipped bundle is **64 KB gz JS + 3.6 KB gz CSS**. A 220 KB cap permits a 3.4× regression rather than preventing one. |
| Web Push serves "immediate corrigenda diffs" | `corrigend*` appears **only in `PRICING.md`** — no code, no schema, no line in the approved plan produces a corrigenda diff. The notification has no producer. |
| AI applicant-guide parsing feeds alerts | No code matches `ghidul` / `solicitantului`. That is Phase D's unstarted `ai_enrich.py`. |
| Virtualization is needed | 58 records. `@tanstack/react-virtual` would window a list that fits on two screens. Revisit past ~500 matches for one tenant. |

### Supabase schema — verified

| Proposal | Reality in `supabase/migrations/` |
|---|---|
| `org_notifications` unique `(org_id, notification_type, call_id, sent_date)` | Table is `0002_organizations.sql:101-110`; constraint is **`unique (org_id, kind, dedupe_key)`**. None of those four columns exist. |
| Add push as a notification type | `kind` is **CHECK-constrained to `('weekly_digest','deadline_reminder')`**. Any new kind needs a migration altering the check. |
| Store `push_subscription` in `organization_members.notification_settings` | That column does not exist, **and** `0003_rls.sql:95-97` deliberately gives `authenticated` **no UPDATE policy** on `organization_members` (prevents self-promotion to `owner`). A browser cannot write its own subscription there under any circumstance. |
| Enable Realtime on `org_call_triage` / `org_call_matches` | **Not configured anywhere** — no `alter publication supabase_realtime`, no `replica identity full`, no `supabase/config.toml`. An unbuilt dependency, not a toggle. |
| RLS isolates on `organization_members.org_id` | Correct, but *indirectly*: every policy compares against SECURITY DEFINER `public.current_org_id()` (`0003_rls.sql:18-26`). Inline subqueries would recurse on that table. |

**The tenancy blocker:** `organization_members` carries `unique (user_id)` (`0002:39`), and
`current_org_id()` depends on it being single-valued — `create_organization()` even documents
that a second call from the same user fails there by design. **A user belongs to exactly one
organisation, permanently.** That contradicts PRICING Tier 3 (*"up to 25 distinct client
profiles"*, €499) and Tier 4 (*"unlimited"*, €799). Deferred deliberately — see Phase I.

Two further gaps that affect signup and seats:

- `create_organization()` (`0003_rls.sql:151-188`) **allowlists the profile to three keys** —
  `mission`, `notification_email`, `notify`. Anything else sent at signup is silently dropped.
  This is the guarantee behind "keyword lists are never on the signup form", not just UI.
- `add_member(p_email)` (`0003_rls.sql:200-227`) is **not an invite flow** — the target must
  already exist in `auth.users`, otherwise `'could not add that address'`. No pending-invitation
  table, token or email dispatch exists. Seat-based tiers need one built.

Useful as-is: RLS on all six tables, every policy targets `authenticated` only, clients have
**no** write path to `org_notifications` or `org_call_matches` (service-role written), and
`org_call_triage` already carries the INSERT/UPDATE policies plus a `status` CHECK matching the
five statuses the UI uses.

### Frontend — verified

20 files, ~1,780 lines, three runtime deps.

**The one real defect.** There is no mutation error path at all. `App.tsx:85` fires
`void store.save(callId, changes, current)` and never awaits it, so a rejected write becomes an
unhandled rejection while the UI silently keeps the optimistic value. Harmless against
`localStorage`; **unacceptable over a network** — a Supabase adapter without mutation state
loses a user's triage silently.

Worse once writes go over the wire: the note `<textarea>` calls `patch()` on **every keystroke**,
and `local.ts:save()` re-serialises the whole triage map each time. That is one request per
character. Needs debouncing before any remote adapter.

**Responsiveness.** `app.css` has **zero `@media` queries** — the entire strategy is
`useMediaQuery(MOBILE_QUERY)` at 900px swapping component trees. That switch is sound (three
panes cannot stack) and stays. What is missing is everything *within* each branch: the desktop
list pane is a fixed `390px` and the rail `230px` with no adaptation between 900–1200px, and
`.fr-m-subnav .fr-iconbtn` is `34px` square — below any touch-target guideline. The mobile sheet
is already correct (`env(safe-area-inset-bottom)` at `app.css:242`).

**The seam that already exists.** `web/src/storage/types.ts` defines `TriageStore` with
`load()` / `save()` and a `writable` flag, explicitly so an adapter can be swapped "without
touching a component"; `App.tsx:15-17` marks the swap point. `storage/github.ts` (whose `save()`
unconditionally throws, imported nowhere) should be **deleted**, not finished — the approved
Phase E says Supabase replaces both adapters.

**And:** `web/` has **no tests of any kind**, and `.github/workflows/tests.yml` runs pytest only,
so CI never builds or type-checks the frontend.

### Backend / ops — verified

- **Roughly half the earlier proposal is outside the approved contract.** Keyword audit over the
  approved plan's 938 lines: *web push*, *PWA*, *service worker*, *VAPID*, *Twilio*, *SMS*,
  *WhatsApp*, *Tailwind*, *TanStack*, *virtualization* — **0 occurrences each**. Resend email is
  the only added channel it sanctions.
- **The idempotency substrate is already built and tested.** `warehouse.claim_notification()`
  (`warehouse.py:503`) claims into `org_notifications` *before* sending and branches on
  `SQLSTATE_UNIQUE_VIOLATION = "23505"` — matching the SQLSTATE, not PostgREST's prose, and
  re-raising other 409s (a foreign-key violation is not a duplicate). `match.py` already has
  `--dry-run` and `--calibrate`. Phase F is smaller than it looks.
- **No always-on compute exists.** One active cron (`funding-radar.yml`, `0 5 * * 1`), and
  `CLAUDE.md` records scheduled runs starting **4h15m–5h12m late, consistently** — GitHub defers
  scheduled workflows under load, and tightening the cron does not help. `mipe-watch.yml`'s cron
  is **commented out** because mfe.gov.ro blocks GitHub runner IP ranges (probe `33773493284`:
  12 ms from a dev machine, silent 15 s timeout from a runner). Whether the cPanel host offers
  shell/cron and Python 3 is `FIRST_RUN.md` open item 1 — *"one fact this repo does not record"*.
  **PRICING's "Daily / Instant" tiers have no infrastructure behind them.**
- **Scheduled crons fire only on the default branch**, and all migration work is on `staging`.
  Phase F's workflow cannot fire until this lands on `main`.
- **`CLAUDE.md:7` and `README.md:20-22` still forbid the channel Phase F adds** — *"exclusively
  by opening GitHub Issues … Do not add other delivery channels; that is a deliberate design
  constraint."* `PROGRESS.md` §5 flags this as an ordering hazard: shipping F before G's doc
  rewrite makes `CLAUDE.md` actively wrong, so the amendment note must land **in the same commit**.

---

## Approach

Four stages. Stages 1–3 are the deliverable; Stage 4 is specified so the follow-on work has a
shape, and is not built here.

### Stage 1 — Make the write path survivable, and make the layout responsive

No new dependencies. Ships independently of Supabase and is the prerequisite for it.

**1a. Mutation state on `TriageStore`.** Extend the seam rather than replace it —
`web/src/storage/types.ts` keeps `load`/`save`/`writable`; `App.tsx` gains a `useTriage` hook
(new `web/src/lib/useTriage.ts`) that owns the optimistic map, awaits `save()`, and on rejection
rolls back to `current` and surfaces an error. The rollback value is already in hand at the call
site (`App.tsx:81` computes `current`), so this is a local change.

- `patch()` stops being fire-and-forget: `void store.save(...)` becomes an awaited call inside
  the hook with a `.catch` that reverts that one call's entry and sets a per-call error flag.
- A dismissible inline notice (`.fr-*` class in `app.css`) reports "Modificarea nu s-a salvat";
  no toast library.
- **Debounce the note field.** `CallDetail.tsx` / `MobileDetail.tsx` keep the textarea value in
  local state and flush through `patch()` on a 600 ms idle timer plus on blur. Status, assignee,
  reminder and snooze stay immediate — they are single clicks.

**1b. Real breakpoints in `app.css`** (never `nocturne.css`).

- `@media (max-width: 1180px)` — desktop list pane `390px → 320px`, rail `230px → 200px`,
  `.fr-detail` padding tightened. Below that the 900px JS switch already takes over.
- `@media (max-width: 899px)` — mobile-branch sizing that is currently implicit: `.fr-m-scroll`
  bottom padding vs. the sheet height, chip row scroll affordance.
- `@media (max-width: 380px)` — small-phone: tag rows wrap, `.fr-sheet-chips` stack two-up.
- **Touch targets:** every interactive `.fr-*` control reaches ≥ 44×44 CSS px on the mobile
  branch (48×48 where layout allows), including `.fr-m-subnav .fr-iconbtn` (currently 34px) and
  `.fr-chip`. Enlarge the hit area with padding, not the icon glyph.
- `@media (prefers-reduced-motion: reduce)` for the sheet transition.

**1c. Frontend CI.** Add vitest + `@testing-library/react` + jsdom (the approved Phase E already
books this as a scope addition) and extend `.github/workflows/tests.yml` with a `web` job running
`npm ci && npm run typecheck && npm run build && npm test`. First tests cover exactly the
regressions Stage 1 introduces risk for: rollback-on-rejected-save, note debounce flushes once,
feed version refusal.

### Stage 2 — Phase E: Supabase-backed dashboard

Follows the approved plan; no deviations proposed.

- Add `@supabase/supabase-js` (~35 KB gz). **Budget: ≤ 120 KB gz JS**, enforced by a size check
  in the `web` CI job — a real cap over today's 64 KB, not the earlier 220 KB.
- `web/src/lib/supabase.ts` — client from `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
  (build-time public values; RLS is the protection, not secrecy).
- **Auth: magic link.** New `web/src/components/AuthGate.tsx` wrapping `App`.
- `web/src/storage/supabase.ts` implements the existing `TriageStore` against `org_call_triage`
  (upsert on `(org_id, call_id)`; RLS supplies `org_id`, the client never sends one).
  **Delete `web/src/storage/local.ts` and `web/src/storage/github.ts`**, per the approved plan.
- `feed.ts` reads `org_call_matches?select=*,calls(*)` instead of `calls.json`; `first_matched_at`
  drives the "new to this org" sort that `first_seen` currently approximates.
- **Signup is three fields** — organisation name, mission prose, notification email — calling
  `create_organization(name, profile)`. Keyword lists are never on the form; the RPC allowlist
  enforces it.
- `pending_calibration` state (profile with no `core_keywords` key) renders an explicit message,
  not an empty inbox.
- `useOrganization.ts` + `OrgSubtitle.tsx` exactly as the approved plan specifies — `orgName` is
  a required non-nullable `string`, no `??` on that path.

### Stage 3 — Phase F: Resend email

- `notify.py`, run by a new scheduled Actions workflow. **No Edge Function, no SMTP server.**
- **Weekly digest** — orgs with `profile.notify.weekly_digest`, matches whose `first_matched_at`
  is within 7 days, rendered in Romanian, `POST`ed to `https://api.resend.com/emails`.
  `dedupe_key` is the ISO week (`2026-W37`).
- **Deadline reminders** — for each `profile.notify.deadline_reminders` offset (default 14, 3),
  calls at exactly that distance whose triage is `relevant`/`applied` or has `reminder = true`.
  `dedupe_key` is `<call_id>:<offset>`.
- **Reuse `warehouse.claim_notification()` unchanged.** Claim first, send second. Do not add
  application-side de-dup bookkeeping; the unique constraint is the guarantee.
- Sender `radar@viabolat.com` from `RESEND_FROM`, no fallback. Missing `RESEND_API_KEY` → log and
  **exit 0** — email is additive and must never fail a run that scraped correctly.
- `pending_calibration` orgs get no digest.
- Schedule: digest weekly after the radar run; reminders daily. Both inherit the documented
  4–5 h queueing delay — the workflow comment must say so, as `funding-radar.yml` does for UTC.
- **In the same commit:** amend `CLAUDE.md:7` and `README.md:20-22`. The Issues-only constraint
  becomes "GitHub Issues for the operator; Resend email for the tenant", with the deviation
  recorded under `CLAUDE.md` § *Multi-org migration — deviations*. `PROGRESS.md` §5 requires this.
- **Flag, do not build:** `PRICING.md`'s €199 "Daily/Instant" and €499 "instant SMS/WhatsApp
  corrigenda" are not deliverable on Actions. Record the gap in `PRICING.md` or resolve
  `FIRST_RUN.md` open item 1 (cPanel shell/cron/Python 3) before selling either.

### Stage 4 — specified, not built

**Phase H — PWA + Web Push.** Prerequisites, all currently missing: (1) an icon set — `web/public/`
holds exactly one file, `calls.json`; there is no favicon, no `theme-color`, no manifest link in
`index.html`, and `CONTRACTS.md`'s white-label promise makes per-tenant manifest name/icons a
design requirement; (2) `nocturne.css:2` pulls Inter from `fonts.googleapis.com` at runtime — a
service worker must self-host or precache it or the installed app loses its typeface offline;
(3) a migration adding `organization_members.push_subscription` **plus a narrow UPDATE policy
scoped to that column only** (the table's blanket no-UPDATE rule exists to stop self-promotion to
`owner`, so a `with check` on `role` is mandatory); (4) a migration widening the
`org_notifications.kind` CHECK. iOS requires 16.4+ *and* home-screen install before push works at
all — material to any tier sold on push.

**Phase I — multi-org tenancy.** Drop `unique (user_id)`, add an org selection mechanism, rewrite
`current_org_id()` and every RLS policy derived from it, migrate live tenant rows. Larger than
Stages 1–3 combined. **Do not sell PRICING Tier 3/4 before this ships.**

**Not planned:** Twilio SMS/WhatsApp (no producer for the corrigenda event that justifies it),
Supabase Realtime (unconfigured, and 58 rows on a weekly cadence do not need live push),
TanStack Query/Virtual, Tailwind.

---

## Verification

**Stage 1** — offline, no credentials needed.
```bash
cd web && npm ci && npm run typecheck && npm run build && npm test
```
- Bundle size printed by `vite build` stays ≤ 120 KB gz JS (Stage 1 should not move it at all).
- A vitest case forces `store.save()` to reject and asserts the triage entry reverts to
  `current` and the error notice renders.
- A vitest case types 5 characters into the note and asserts `save()` fires **once**.
- Manual: DevTools device emulation at 1180 / 900 / 390 / 360 px; confirm no horizontal scroll,
  and that every mobile control measures ≥ 44×44 in the box model.
- `python3 -m pytest tests -q` still reports **143 passed** (Stage 1 touches no Python).

**Stage 2** — needs a live Supabase project; RLS **cannot be verified offline** and the approved
plan says so outright. Manual and mandatory:
1. Apply migrations `0001`–`0005`; confirm `select * from pg_policies where schemaname='public'` lists policies on all six tables.
2. Sign up org A and org B through the form. Confirm each sees only its own `org_call_matches`
   rows with the **anon key + a real user JWT**, not the service-role key.
3. From org A's session, attempt `update organization_members set role='owner'` → must fail.
4. From org A's session, attempt to write `org_call_matches` or `org_notifications` → must fail.
5. Confirm `create_organization` drops a `matching` key sent in the profile body.
6. Triage a call in org A; reload in a second browser signed in as another org-A member; the
   state is there. That is the whole point of the migration.
7. Close Phase C's open half while credentials are in hand:
   ```bash
   SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python3 funding_radar.py --no-state --evidence evidence/all
   SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python3 match.py --org "Vertical Freedom" --dry-run
   ```
   Expect **58** matched (23 core / 35 wide) — compare **id sets, not totals**.

**Stage 3** — offline first, then one live send.
- pytest coverage for `notify.py` following `tests/conftest.py`'s `fake_session` route table:
  digest window boundaries, reminder offsets, `pending_calibration` skip, missing
  `RESEND_API_KEY` → exit 0, and **a re-run sends nothing** (second `claim_notification` returns
  False on `23505`). No test may reach the network.
- Live: run once against a real org, confirm the email arrives, then run **again immediately**
  and confirm `org_notifications` gained no row and no second email arrived.
- Confirm the Phase F workflow runs only on the default branch, and that `CLAUDE.md` /
  `README.md` no longer forbid the channel now in use.

**Service-role safety, standing.** The key bypasses RLS entirely: Actions secrets only. It must
never reach `web/`, a committed file, or a provenance receipt — do not add `apikey` or
`Authorization` to `provenance.SAFE_REQUEST_HEADERS`, which is an allowlist precisely for this.

---

## Why these routes

Four decisions shaped this plan. Each is recorded with what was rejected and why, so a later
session can reverse one deliberately rather than by drift.

### 1. Scope — Phase E + F first; PWA and push deferred to Phase H

**Rejected: "PWA + push only, on the current app."** It is the fastest visible result and it
delivers nothing. A service worker and a manifest wrapped around today's build would produce an
installable app that is still single-user, still `localStorage`-backed, still reading a static
`calls.json`, with **no server to push from and nowhere to store a subscription**. The push
notification would have no producer at either end.

**Rejected: one long plan covering E → F → PWA → push.** Sound in dependency order, but it
front-loads a large unreviewed surface. Phases E and F are already reviewed and approved; the
PWA work is not, and it turns out to need two migrations of its own (see Phase H). Bundling
approved and unapproved scope into one plan makes the approved half harder to ship.

**Chosen: E + F first.** Both are on the approved contract. Between them they turn a single-user
browser tool into a multi-tenant product with a real notification channel — which is the actual
gap between what exists and what `PRICING.md` sells at the entry tier. Push has value *after*
there is an account to attach a subscription to and a scheduled job to fire one.

The audit that settled it: across the approved plan's 938 lines, *web push*, *PWA*, *service
worker*, *VAPID*, *Twilio*, *SMS*, *WhatsApp*, *Tailwind*, *TanStack* and *virtualization* appear
**zero times each**. Roughly half the earlier proposal was net-new scope against a reviewed
contract, and it sequenced the two hardest dependencies last.

### 2. Tenancy — ship single-org, plan multi-org as Phase I

**Rejected: rework tenancy now.** `unique (user_id)` is not an incidental constraint. It is what
makes `current_org_id()` single-valued, and that function is what every RLS policy on all six
tables compares against. Dropping it means an org-selection mechanism, a rewrite of the function,
a rewrite of eleven policies, and a change to `create_organization()`'s documented failure mode —
before any of Phase E's user-visible work starts. It is larger than Stages 1–3 combined, and
doing it first delays every deliverable behind the riskiest change in the project.

**Rejected: drop Tier 3/4 from `PRICING.md`.** Premature. The tiers are not wrong, they are
unbuilt, and nothing about the current schema forecloses them.

**Chosen: keep the constraint, phase the rework.** Founding-client Phase 1 (five anchor deals) is
single-org by nature — a municipality, a university, an NGO each want their own inbox, not a
portfolio view. Shipping against the schema as designed is correct for that cohort. Writing
Phase I up separately means the multi-org path is costed and visible rather than discovered
mid-sprint, and the one hard rule attached to it — **do not sell Tier 3/4 before it ships** — is
recorded where a future session will read it.

The risk accepted: live tenant rows will exist when Phase I lands, so the constraint drop becomes
a data migration rather than a schema edit. That is a known, bounded cost, and it is smaller than
the cost of blocking Phases E and F behind it.

### 3. Styling — media queries in `app.css`, no Tailwind

**Rejected: full Tailwind rewrite.** `web/src/styles/nocturne.css` is "copied verbatim from the
handoff — treat it as vendored and do not edit it" (`CLAUDE.md`, and `web/README.md`). It is 294
lines defining 51 design tokens plus its own `*, *::before, *::after` reset and element-level
`body`, `h1`–`h6`, `a`, `img` rules. Tailwind's preflight is a competing reset; adopting it means
re-expressing 64 tokens and 89 hand-authored classes as utilities and discarding the design
handoff — against an explicit standing constraint, for no functional gain.

**Rejected: Tailwind with `preflight: false`.** It avoids the reset collision and leaves two
styling systems side by side: tokens in CSS custom properties, new markup in utilities, and no
rule for which a later contributor should reach for. Mixed idiom is a durable cost.

**Chosen: real breakpoints in `app.css`.** The 900px JS switch is not a shortcut standing in for
media queries — it renders genuinely different component trees (`DesktopWorkspace` vs.
`MobileInbox`/`MobileDetail`), because a three-pane split inbox does not stack into a phone. That
decision is sound and stays. What is actually missing is the sizing *inside* each branch: the
desktop list pane is a hard-coded `390px` and the rail `230px` with nothing between 900 and
1200px, and `.fr-m-subnav .fr-iconbtn` is `34px` — too small to hit reliably on a phone. Those
are CSS problems with CSS answers. Zero new dependencies, bundle unchanged at ~64 KB gz, and the
vendored stylesheet is never touched.

### 4. Compute — plan for GitHub Actions, flag the gap honestly

**Rejected: assume a small VPS.** It would make instant alerts and MIPE both feasible and matches
`CONTRACTS.md`'s Docker hand-off. But this repo has deliberately avoided always-on
infrastructure — no server, no queue, no worker, and `org_call_matches.profile_hash` is
documented as "the entire recompute trigger — no queue, no worker, no webhook". Assuming a VPS
into a plan is assuming a hosting decision, an ops surface and a monthly cost that were never
agreed.

**Rejected: block on verifying cPanel first.** It is the right question — it also unblocks
`mipe_watch.py`, which is unmonitored because mfe.gov.ro drops GitHub runner IPs — but it is one
unanswered fact, and Phases E and F do not depend on it. Blocking three stages of work on it
would trade delivery for a detail that can be answered in parallel.

**Chosen: build Phase F exactly as approved, on Actions, and state the ceiling.** What that
honestly delivers is a weekly digest and daily deadline reminders, both landing hours after their
cron time — `CLAUDE.md` records every scheduled run so far starting 4h15m to 5h12m late, and
notes that tightening the cron does not help because the delay is not proportional to the time
requested. That is genuinely enough for the €29 weekly tier and for 14-day and 3-day deadline
reminders, which is what the approved plan specifies.

It is **not** enough for `PRICING.md`'s €199 "Daily/Instant" or €499 "instant SMS/WhatsApp
corrigenda". Rather than quietly building toward a promise the infrastructure cannot keep, the
plan flags it: either resolve `FIRST_RUN.md` open item 1 (does the cPanel host give shell, cron
and Python 3?) or narrow the pricing language. Selling "instant" on a queue that runs four hours
late is the one failure here that reaches a paying client.

### A note on what the earlier proposal got right

One thing, and it did not argue for it. There is **no mutation error path anywhere in the
dashboard** — `App.tsx:85` fires `void store.save(...)` and never awaits it. Against
`localStorage` that is harmless and the code says so. Against a network it means a user triages a
call, sees the UI update, and loses the change with no indication. Any Supabase adapter dropped
into the existing `TriageStore` seam without fixing this would silently lose data on the first
flaky connection. That is why Stage 1 comes before Stage 2 rather than inside it.

The related defect the proposal did not catch: the note `<textarea>` calls `patch()` on every
keystroke and `local.ts:save()` re-serialises the entire triage map each time. As a local write
that is invisible. As a network write it is one request per character.
