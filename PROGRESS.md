# PROGRESS.md — multi-org migration handoff

**Read this before touching anything.** It exists so a session with no memory of the work can
answer *what is already true, what is still open, and what not to redo* in under a minute.

- **Plan (the contract):** `~/.claude-professional/plans/harmonic-fluttering-hamming.md` — approved, seven phases.
- **Branch:** `staging`, tracking `origin/staging`. Pushed and up to date.
- **HEAD:** `71e9ee9`. `main` is still at `90903e2` (pre-migration) and is **not** merged.
- **Suite:** 143 passing, fully offline. Run `python3 -m pytest tests -q`. (`python` is not on PATH — use `python3`.)

---

## 1. Phase status

| Phase | What it is | Status | Commit |
|---|---|---|---|
| **A** | Schema + RLS (6 tables, policies, 2 `SECURITY DEFINER` RPCs, VF seed row) | **Committed, pushed** | `5110585` |
| **B** | `warehouse.py`, both watchers dual-writing, de-tenanted User-Agents | **Committed, pushed** | `ed47498` |
| **C** | Org-agnostic scraping, `match.py`, docstring de-tenanting | **Committed, pushed** | `e2060a9` |
| — | `CLAUDE.md` filtering section rewritten (pulled forward from G) | **Committed, pushed** | `71e9ee9` |
| **D** | `mipe_calendar` source, cross-source dedup, Romanian output, `ai_enrich.py` | **Not started** — zero code | — |
| **E** | Dashboard on Supabase, signup, vitest infra | **Not started** | — |
| **F** | `notify.py` / Resend email | **Not started** | — |
| **G** | `README.md` / `CLAUDE.md` / `FIRST_RUN.md` rewrite | **Not started** (except `71e9ee9` above) | — |

**On disk:** `match.py`, `warehouse.py`, `supabase/migrations/0001`–`0005` exist.
`notify.py`, `ai_enrich.py`, `web/src/storage/supabase.ts`, `web/vitest.config.ts`,
`tests/fixtures/mfe_calendar_sample.html` do **not**.

Migration `0005_calls_eligible_as.sql` is not in the plan's file list — it was added during
Phase C to move the `{ong, sanatate}` gate out of the fetcher and into `profile.eligible_as`.

---

## 2. Verified vs. not

### Verified — Phase C's acceptance gate PASSES

Measured live **2026-09-09** against the real feeds, EU dataset sha256 `7f98fff9…`
(129,780,383 bytes, `last_modified: Tue, 08 Sep 2026 15:01:20 GMT`):

| Source | Collected (org-agnostic) | Matched (seed profile) | Pre-refactor code, same bytes | Id sets |
|---|---|---|---|---|
| EU | 626 (11,160 → 10,161 grants → 635 open/forthcoming → 626 deadline ahead) | **24** | **24** | **identical** |
| adieuronest | 1,124 of 1,131 rows | **34** | **34** | **identical** |
| total | 1,750 | **58** (23 core, 35 wide) | — | — |

Method: pinned one dataset snapshot, ran `ed47498` (pre-refactor) and `e2060a9` in a `git
worktree` against the *same bytes*, compared `set(old) == set(new)`. Empty both ways.

> **Do not re-run this as a bare count comparison.** Absolute counts drift — the Romanian feed
> shrank 1,162 → 1,131 rows and the documented baseline of `37` is now `34` on *both* old and
> new code. Pin a snapshot via `fetch_eu_calls(session, dataset_path=…)`, prove both runs parsed
> the same bytes with the receipt's `sha256`, and **compare id sets, not totals.**

Also verified: `cd web && npm run typecheck` clean; `--no-state` leaves `calls.json`,
`seen_calls.json` and `digests/` untouched (confirmed via `git status` after a live run).

### Not verified — blocked

| Item | Blocker |
|---|---|
| `match.py --org vertical-freedom --dry-run` | `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` unset. `match.py` **exits 1** without them by design. |
| Ingest row counts (`select source, status, count(*)`) | Same. No Supabase project reachable from this environment. |
| Migrations actually applied (`0001`–`0005`) | Same. Written and committed, never run against a live database. |
| **RLS policies (plan verification step 4)** | Requires anon key + a real user JWT. Plan states outright this **cannot be tested offline** — it is a manual step and must not be skipped. |
| `mipe_calendar` ≈330-row baseline | Phase D not built. The plan's step-2 ingest check is a **two-source** check until then. |
| `mipe_watch.py` scheduled runs | Hosting unresolved — **the host blocks GitHub IPs** (`FIRST_RUN.md` §3, probe `33773493284`), so every scheduled run would be red. Cron is **commented out** in `mipe-watch.yml`; `workflow_dispatch` only. `funding_radar.py` on CI is confirmed working. |

**No workflow references `SUPABASE_*`, `RESEND_*` or `BRIGHTDATA_*` yet.** Only `GITHUB_TOKEN`
(both watchers) and `CPANEL_FTP_*` (deploy). Scheduled crons run **only on the default branch**,
so nothing on `staging` can fire one.

---

## 3. Deviations from the plan

**Do not re-derive these — read `CLAUDE.md` § "Multi-org migration — deviations from the
approved plan".** That section is the record; this is only the headline.

- **Matching terms are per-language, not flat.** The plan specified flat `core_keywords` /
  `wide_keywords` / `context_guards`. Built instead as
  `profile.matching.{ro,en}.{core,wide,guards}` plus a `calls.lang` column.
- **Why it was forced:** a merged list *cannot* satisfy Phase C's exact-match gate. `screening`
  is CORE in Romanian and WIDE in English; the English guard `animal` is a substring of Romanian
  `animală`, so a shared guard vetoes Romanian rows the calibration accepts. Merging changes the
  result set in both directions.
- The eight plan-vs-`CLAUDE.md` conflicts (Issues-only notifications, `merge_calls` hard delete,
  `owned_sources`, triage location, two-shared-modules rule, single-secret claim, filtering
  section, `mipe_watch` shape) are recorded in **Phase G**, not yet written.

---

## 4. Rejected / deferred — do not propose again

| Proposal | Verdict | Reason |
|---|---|---|
| Directory-level `SKIP_DIRS` exemptions in `tests/test_detenanting.py` (skip `tests/`, `supabase/migrations/`) | **Rejected** | Too broad: would exempt `conftest.py`, migrations `0001`–`0003`, and every file added later, none justified. Use **named-file** exemptions, each backed by an assertion. `test_the_exempt_tests_name_the_tenant_only_to_assert_its_absence` is the pattern — it also fails if a file *stops* needing its exemption. |
| Flat keyword profile shape | **Rejected** | Breaks Phase C's exact-match gate. See §3. |
| AI-derived onboarding (`derive_profile_terms(mission)`) | **Deferred** | Not needed yet. Seam is `profile.suggested_terms` + operator promotion; `match.py --calibrate` writes it and **never** the live lists. |
| `supabase-py` | **Rejected in plan** | Plain `requests` on PostgREST; `create_resilient_session()` already handles retry/backoff. (`@supabase/supabase-js` *is* used in `web/`.) |
| Re-adding `timezone:` to workflow crons | **Rejected** | Actions is UTC-only and silently ignores the key. |

Also standing, from `CLAUDE.md`: never let a test reach the network or the real GitHub API;
`web/src/styles/nocturne.css` is vendored, do not edit; keep `mipe_watch.py`
change-detection-only; a source that failed must never be named in `owned_sources`.

---

## 5. Known-stale docs

Both scheduled for **Phase G**:

- `CLAUDE.md` § "What this is" still frames the repo as **Vertical Freedom's** ("two standalone
  Python scripts … on behalf of Vertical Freedom"). False since Phase C — scraping is
  org-agnostic. `README.md` has the same framing.
- The same paragraph still states notification is **"exclusively by opening GitHub Issues — no
  Slack, no Telegram, no SMTP … Do not add other delivery channels."** The plan deliberately
  overrides this with Resend email as an *additive* channel.

> ⚠️ **Ordering hazard.** If **Phase F (email) ships before Phase G's doc rewrite**, `CLAUDE.md`
> becomes *actively wrong* — it will forbid, as a deliberate design constraint, a channel the
> code is using. Either land the "What this is" rewrite with Phase F, or add an explicit
> amendment note there in the same commit. Do not leave the interim gap unmarked; the constraint
> reads as binding to anyone who has not read the plan.

`FEED_VERSION` is still `1` in `calls_store.py`; it and `SUPPORTED_FEED_VERSION` go to **2**
together when `mipe_calendar` enters the `Source` union (Phase D/E).

---

## 6. Immediate next step

**Phase D has not started — there is no partial work to resume.** Confirmed: no
`fetch_mipe_calendar_calls`, no dedup code (`merged_into` / „Apare și în" absent from
`funding_radar.py`), no `tests/fixtures/mfe_calendar_sample.html`. The only trace is
`warehouse.py`'s `WAREHOUSE_SOURCES` / `SOURCE_LANG`, which already name `mipe_calendar` —
scaffolding from Phase B, not an implementation.

Next concrete action, in order:

1. **Capture the fixture first.** `GET https://mfe.gov.ro/calendar-apeluri-de-finantare/`, cut
   `tests/fixtures/mfe_calendar_sample.html` from the live body unedited. The page is WAF'd —
   if it returns `WAF Forbidden` or times out, that is the Bright Data path (`BRIGHTDATA_API_TOKEN`
   + `BRIGHTDATA_ZONE`, neither configured yet). **No token → the source is skipped and named as
   skipped, never faked.**
2. Write `fetch_mipe_calendar_calls()` parsing the `var RAW = [...]` array (~1,079 records).
   A missing `var RAW` marker must **raise** — a shape change has to look like a failure, not
   like "nothing matched". `call_id = mipe_calendar:<mca_call_key>` (verified unique).
3. Stamp `lang="ro"` and build `search_core` / `search_wide` at ingest, same as the other two
   sources. Empty `eligible_as` means *unknown*, not closed.
4. Then cross-source dedup (plan Phase D): Rule 1 EU-link collapse, Rule 2 folded title **plus**
   identical deadline, precedence `eu_sedia > adieuronest > mipe_calendar`, collapsed rows marked
   `withdrawn` with `raw.merged_into` — **never deleted**.

Before any of it: `python3 -m pytest tests -q` should report **143 passed**. If it does not, fix
that first — something has drifted.

**If the operator supplies `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`,** close the open half of
Phase C's gate first — it is cheap and it is the thing currently unproven:

```bash
SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python3 funding_radar.py --no-state --evidence evidence/all
SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python3 match.py --org vertical-freedom --dry-run
```

The service-role key **bypasses RLS entirely** — Actions secrets only. It must never reach
`web/`, a committed file, or a provenance receipt (`provenance.SAFE_REQUEST_HEADERS` is an
allowlist precisely for this; do not add `apikey` / `Authorization` to it).
