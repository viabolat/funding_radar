# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two standalone Python scripts that watch Romanian and EU funding sources on behalf of Vertical Freedom (an NGO supporting cancer patients: complementary/integrative therapies, psychotherapy, emotional support, nutrition, prevention). Both run only as scheduled GitHub Actions and notify **exclusively by opening GitHub Issues** — no Slack, no Telegram, no SMTP. GitHub's own "watching" emails are the entire notification path. Do not add other delivery channels; that is a deliberate design constraint.

Neither script is a package or module — each is a self-contained `main()` with a `--create-issue` flag. There is no linter config and no build step; `requirements-dev.txt` covers both runtime deps and pytest.

## Commands

```bash
pip install -r requirements-dev.txt          # runtime deps + pytest

python funding_radar.py                      # local: writes digests/digest_<date>.md, no Issue
python mipe_watch.py                         # local: logs only, no Issue

# Run one scraper alone, touch no state, and keep a receipt (see Provenance):
python funding_radar.py --source adieuronest --no-state --evidence evidence/ro
python funding_radar.py --source eu          --no-state --evidence evidence/eu
python funding_radar.py --source eu --cache-dir .cache  # revalidate with a 304 instead of re-downloading
python mipe_watch.py --no-state --evidence evidence/mipe

# Only meaningful inside Actions (or with a real token):
GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo python funding_radar.py --create-issue

python -m pytest tests -q                    # full suite
python -m pytest tests/test_mipe_watch.py -q # one file
python -m pytest tests -q -k baseline        # one test by name substring

cd web && npm install                        # dashboard, first time only
cd web && npm run dev                        # http://localhost:5173/funding_radar/
cd web && npm run typecheck                  # tsc --noEmit
cd web && npm run build                      # tsc -b && vite build -> web/dist
```

Both scripts are idempotent-ish but **stateful**: running locally rewrites `seen_calls.json` / `mipe_page_hashes.json` / `calls.json` in the working directory, which will suppress the next real run's alerts if committed. Delete or restore those files after local experimentation — or use `--no-state`, which exists precisely so a verification run cannot poison the next scheduled one. `--no-state` and `--create-issue` are mutually exclusive and the parser rejects the pair.

## Architecture

**`funding_radar.py`** — fan-in from two sources into one `FundingCall` dataclass, then diff against state:

1. `fetch_adieuronest_calls()` — downloads a CSV feed from adieuronest.ro (Romania national + RO/MD/UA cross-border).
2. `fetch_eu_calls()` — the EU Funding & Tenders Portal, in two halves that use the two endpoints listed on the portal's own [API page](https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/support/apis) for the jobs each is good at.
   - **Discovery** streams the bulk reference dataset (`data/referenceData/grantsTenders.json`, ~130 MB, ~11,160 records, refreshed daily) with `ijson` and filters it locally: grants only, Open/Forthcoming, deadline still ahead, then a CORE/WIDE keyword gate. Coverage is an *enumeration*, not a relevance ranking.
   - **Enrichment** then sends one small POST per matched topic to the search index (`api.tech.ec.europa.eu/search-api/prod/rest/search`) for the budget and the canonical topic URL, which the bulk file does not carry. `enrich_eu_call` never raises: a search-index failure costs a budget line, not a call. That asymmetry is the entire point of the split — discovery must not depend on the index.

   Net traffic is one conditional GET plus ~24 small POSTs, replacing up to 33 broad keyword POSTs.
3. New = fetched ids minus `seen_calls.json`. Digest is written to `digests/digest_{date}.md`, an Issue opens only when the new count is non-zero, then **all** fetched ids (not just new ones) are merged into the seen store.

**`mipe_watch.py`** — MIPE (mfe.gov.ro) publishes its call calendar as an unparseable page/PDF, so this intentionally does *not* extract structured data. It strips markup with BeautifulSoup, collapses whitespace, SHA-256s the visible text, and compares to `mipe_page_hashes.json`. Changed → Issue asking a human to look and manually add anything relevant to the radar. Unchanged → a quiet log line, nothing else. Keep this change-detection-only shape; parsing that source is not worth the maintenance.

**`calls_store.py`** — the first of two modules both scripts import, and an intended exception to the duplication rule below. Both write the same `calls.json` feed, which is what the `web/` dashboard reads; two copies of that merge contract would drift, and drift there silently drops records.

Feed shape: `{"version": FEED_VERSION, "generated_at": ..., "calls": [...]}`, sorted by `call_id` so a commit diff shows real changes rather than dict reordering. Bump `FEED_VERSION` when a record field changes — the frontend refuses a version it does not know rather than rendering blanks. A record is `call_id, source, title, programme, deadline (ISO or null), announced, budget, tags, match_reason, link, first_seen`.

Each script owns its own sources and must never touch the other's rows, but the two owners need **different merge semantics**, which is the easiest thing here to get wrong:

- `funding_radar.py` **replaces** (`write_source_calls(..., owned_sources={"adieuronest", "eu_sedia"})`). It re-fetches its whole feed every run, so what it did not return is genuinely gone.
- `mipe_watch.py` **upserts** (`replace=False`). It reports only the pages that changed on that run, so replacing would pass an empty list on the first quiet day and delete every outstanding alert.

`first_seen` is carried over from the existing entry on both paths — it is when a call was first surfaced, not when it was last re-fetched, and the UI sorts on it. Triage state (status, assignee, note, reminder, snooze) is **not** in this file; it is user-authored and belongs in `triage.json`, keyed by the same `call_id`.

**`provenance.py`** — the second, and the second exception, for the same shape of reason: a receipt is only worth anything if every producer emits the *identical* format, since the whole point is that two runs from two machines can be compared field for field. `Recorder(None)` is a fully working no-op, so wiring it into a code path cannot change what that path does. Do not add a third shared module without a reason as concrete as these two; every other shared helper is duplicated by design.

Both scripts share the same `create_resilient_session()` pattern (5 retries, backoff factor 2, jitter, honors `Retry-After`, retries 429/5xx) because neither upstream publishes a rate limit. Both also call `assert_trusted(response)` before treating a body as data: `response.url` is the URL *after* redirects, and everything fetched is unauthenticated public data, so the final host is checked against `CONFIG["allowed_hosts"]` over HTTPS. State files (`calls.json`, `seen_calls.json`, `mipe_page_hashes.json`) are written through `calls_store.atomic_write_text` — a truncated seen store is not a detectable error, it parses as "we have seen fewer calls" and silently re-reports them all.

**A source that failed must never be named in `owned_sources`.** `merge_calls` deletes every row of a source it is given, so passing a failed source's name erases its rows from `calls.json` while the run still exits 0. `funding_radar.main()` tracks per-source success and passes only what actually succeeded; a run where *every* source failed exits non-zero. This is the same silent-green failure fixed for `mipe_watch` in `6712dfe`.

## Provenance

Nothing in a digest distinguishes "these rows came off the wire" from "these rows came out of a file someone put there". `--evidence DIR` closes that without requiring anyone to trust the run: it writes `manifest.json` with, per request, the URL, status, `response_bytes`, the **sha256 of the exact bytes that were parsed** (hashed chunk by chunk during the stream, not re-serialised afterwards), the upstream server's own `Date`/`ETag`/`Last-Modified`, and elapsed ms — plus a bounded raw sample under `raw/`. `--evidence-full` keeps whole bodies (opt-in: the EU dataset is ~130 MB).

Each source also emits a **funnel** (`records → grants → open_or_forthcoming → deadline_ahead → keyword_matched → emitted`), which is what makes the final count re-derivable by hand from the raw body.

Two rules about it:

- Request headers in a receipt are an **allowlist**, not a denylist (`provenance.SAFE_REQUEST_HEADERS`). `GITHUB_TOKEN` rides in an `Authorization` header and a receipt is an artifact people pass around.
- Evidence is **gitignored and never committed** — it is uploaded as an Actions artifact instead. The repo is the watchers' state store; this is not state.

Independent check: re-fetch the URL yourself, `sha256sum` it, and compare to the manifest. A fabricated row cannot produce a matching hash against a live re-fetch.

## Testing

`tests/` runs entirely offline. `tests/conftest.py` puts the repo root on `sys.path` (the scripts are top-level modules, nothing to install) and provides: `fake_session` (a URL→response/exception route table; POST routes key on `(url, text-param)`), `fake_response` (which also streams via `iter_content`, works as a context manager, and carries `url`/`headers`/`request`), `eu_reference_path`, `sedia_payload`, `adieuronest_csv_bytes`, and `capture_post` (monkeypatches `requests.post` on a given module and returns the recorded calls). A `fake_response` given `json_data` serialises real bytes into `.content`, because production code hashes the body *before* parsing it. Never let a test reach the network or the real GitHub API — add a route, not a live call.

`main()`-level tests use `monkeypatch.chdir(tmp_path)` because both scripts write state files relative to the working directory. `tests/fixtures/` holds real captured payloads — a trimmed SEDIA response (one topic in en/es/ro, one expired EU4H topic with no English variant), four unedited CSV rows including the BOM, and `eu_reference_sample.json`: seven records cut unedited from the live 129,759,798-byte reference dataset (an open cancer grant, a forthcoming one, a WIDE-tier match, a closed grant, a multi-cutoff grant, a context-guarded biodiversity/human-health grant, and a procurement tender). Rebuild them from a live response rather than hand-editing if a source changes shape. `fetch_eu_calls(session, dataset_path=...)` takes a path so the EU source runs end to end offline without stubbing a 130 MB stream.

Every quirk in the section above has a named regression test. These tests were mutation-checked: reintroducing each defect makes the suite fail — BOM, GET, trusting `status`, WIDE-in-body, no eligibility gate, and on the EU side dropping the context guard, taking `deadline[0]`, reading epoch as seconds, matching against `tags`, replacing all owned sources regardless of success, exiting 0 on total failure, dropping the host allowlist, dropping the download size ceiling, and letting an enrichment failure drop its call.

The suite is wired to `.github/workflows/tests.yml` on push/PR.

## Filtering behavior

Both sources were calibrated against live responses; the numbers below are from the real feeds and are the baseline to compare against if a change makes the digest swing.

**adieuronest** (`CONFIG` in `funding_radar.py`) — a row must be BOTH applicable AND relevant:

- *Applicable*: `categorii` intersects `{ong, sanatate}` and `stare` is not `inchis`. The live vocabulary is exactly `companii, universitati, autoritati, ong, persoane, scoli, cultura, sanatate` — note `sanatate` appears on only 3 of 1162 rows, so `ong` carries the gate.
- *Relevant*: a CORE keyword anywhere in `titlu + program + solicitanti + finanteaza + conditii`, **or** a WIDE keyword in `titlu + program` only. The two-tier split is load-bearing: WIDE terms like `sănătate` are everywhere in boilerplate scope text (the PowerUp NetZero call matched on "sănătate animală"), so matching them in body prose alone pulled in 32 junk rows. In a title they are signal.
- Result: **37 of 1162 rows**, down from 495 under the old category-OR-keyword rule. Widen by moving a term from WIDE to CORE; narrow by dropping WIDE terms.
- Romanian keywords carry both diacritic and non-diacritic spellings, and match on stems (`oncolog`, `nutriți`) since Romanian inflects — `sănătate` does not match `sănătății`.

**EU** (`eu_core_keywords` / `eu_wide_keywords` / `eu_context_guards` in `CONFIG`) — the gate is local now, so changing a keyword costs no network round-trip. Same two-tier shape as adieuronest, one layer down:

- *CORE* matches `title + callTitle` — the topic's own name and its parent call's.
- *WIDE* matches `title` only, and only when no **context guard** fires. The guard list (`soil`, `animal`, `ecosystem`, `crime`, `forest`, `biodivers`, …) is the generalisation of the "sănătate animală" lesson: "Health of ecosystems and wild species, predictions and impacts on human health" is a biodiversity call, not a health one.
- **`tags` and `keywords` are never matched against.** They are a ~40-term marketing keyword dump ("opportunities", "funding", "partners"); matching them made "mental health" hit a call about eradicating invasive species and "nutrition" hit livestock feed.
- Bare substrings were the other trap: `health` matched soil/plant/crime/fire calls, and `mental` is a substring of *environmental*, *experimental* and *fundamental* — it matched a quantum-computing pilot line. WIDE terms are therefore phrases (`mental well`, `public health`, `human health`).
- Live funnel, 2026-09-08: **11,160 records → 10,161 grants → 647 Open/Forthcoming → 627 with a deadline still ahead → 24 matched.** Comparable in volume to the 22 the keyword search returned, with far better precision and a receipt behind it.

The search index is still queried, but only for enrichment, one identifier at a time. Its quirks are listed below and now cost at most a budget line.

## Multi-org migration — deviations from the approved plan

The migration to a multi-org Supabase warehouse is being built in phases against an approved
written plan. Where the implementation departs from that plan, the departure is recorded here
rather than absorbed silently — the plan is the thing that was reviewed, so a change to it is a
change to what was agreed.

The eight conflicts between that plan and decisions already documented in this file (the
GitHub-Issues-only notification constraint, `merge_calls`'s hard delete, the `owned_sources`
rule, triage's location, the two-shared-modules rule, the single-secret claim, this filtering
section, and `mipe_watch`'s change-detection-only shape) are recorded in Phase G, when the
sections they contradict are rewritten. This section is for the other class: places where the
plan itself turned out to be wrong.

**1. Per-language matching terms, not one flat list. (2026-09-08, Phase A.)**

*The plan specified* an organisation profile carrying flat `core_keywords`, `wide_keywords` and
`context_guards` arrays — one set of terms, applied to every call regardless of source.

*Why that does not hold.* The plan's own acceptance gate for Phase C is that matching Vertical
Freedom's profile against the warehouse returns **exactly** the call_ids today's
`funding_radar.py --no-state` returns. Merging the Romanian and English lists cannot satisfy
that gate, because the two were calibrated independently against text in two different
languages and are not interchangeable:

- `screening` is a **CORE** term in the adieuronest list and a **WIDE** term in the EU list. As
  one merged CORE list it starts matching EU `callTitle`, which widens the EU feed past its
  calibrated 24.
- `animal` is an EU **context guard** — the generalisation of the "sănătate animală" lesson —
  and is a substring of the Romanian `animală`. As a shared guard it would veto Romanian rows
  the current code accepts.
- `holistic` and `tumor` are Romanian CORE terms that also match English prose, so merging them
  changes the EU result set in the other direction.

*What was built instead.* `organizations.profile.matching` is keyed by language:
`{ "ro": { core, wide, guards }, "en": { core, wide, guards } }`. `public.calls` gains a `lang`
column (`'ro' | 'en'`, `not null default 'ro'`), stamped at ingest — `eu_sedia` is `en`, the two
Romanian sources are `ro`. `warehouse.SOURCE_LANG` is the fallback for a record that does not
carry one, because the language of a source is a property of the source. The matcher selects the
term set by the call's `lang`.

The two-tier CORE/WIDE split, the diacritic and non-diacritic spellings, and the stem matching
are all unchanged — this splits the lists by language, it does not re-calibrate them. Terms are
still copied verbatim out of `CONFIG` into `0004_seed_vertical_freedom.sql`, so the Phase C
comparison stays meaningful.

## Source quirks that will bite you

Both parsers are now pinned to captured live payloads in `tests/fixtures/`. These are the non-obvious things that cost a debugging cycle each:

- **The CSV is served with a UTF-8 BOM.** Decode with `utf-8-sig`, or the first header becomes `\ufeffid` and `row.get("id")` silently returns `None` for every row.
- **There is no `descriere` column.** The prose lives in `solicitanti`, `finanteaza`, `conditii`. Deadlines are `termen` (dd.mm.yyyy) / `termen_iso`; the link column is `url`; money is `valoare_min`/`valoare_max`/`alocare`.
- **`cod` is blank on roughly half the feed**, so it cannot be a fallback ID on its own — an ID derived from the URL collides (17 rows share one `mfe.gov.ro` link).
**EU reference dataset** (discovery — `grantsTenders.json`):

- **Dates are epoch *milliseconds***, as int or as string, in `deadlineDatesLong`. Reading them as seconds puts every deadline in 1970, which expires the whole EU feed and looks exactly like "nothing matched".
- **`deadlineDatesLong` is a list.** Multi-cutoff calls carry several (EDF-EDIP three, the EIC Accelerator four); take the next one still ahead, not `[0]`.
- **`type` is exactly two values**, confirmed by counting all 11,160 records: `1` = grant topic (10,161), `0` = procurement tender (999). Not strings, and not the search index's vocabulary — the old `["1","2","8"]` was a guess against a different one.
- **Grant records carry no `url`.** Only tenders do. The topic page is built from `identifier` via `eu_topic_url`.
- **The status is currently consistent with the deadlines** in this dataset — unlike the search index — but the deadline is still checked separately and always. Status is a claim; the deadline is a date.
- **No gzip**, and the body is ~130 MB, so it is streamed to a temp file with a hard size ceiling (`eu_reference_max_bytes`) and parsed with `ijson`. `json.load` on it peaks past 1.5 GB.
- **Conditional GET works** (`If-None-Match` → 304, 0 bytes), but it is opt-in behind `--cache-dir` and off by default: sending `If-None-Match` with no local body to fall back on turns a 304 into an outage, and a CI checkout is fresh every time anyway.

**SEDIA search index** (enrichment only — these now cost at most a budget line):

- **The SEDIA API answers GET with 405.** It needs a POST with the filter as a multipart part named `query` containing JSON; free text and paging stay in the query string.
- **SEDIA `status` is unreliable.** `EU4H-2024-PJ-03-5` is still flagged `31094502` ("Open") with a deadline of 2025-01-21. (`31094501` is Forthcoming, not Open — the old config name had this backwards.)
- **Every topic is indexed once per translation** (~6 languages each, up to 23), so `enrich_eu_call` picks the most preferred language rather than the first result, or the digest comes out in Spanish.
- **`frameworkProgramme` is an opaque numeric id** (`43108390`) — which is why the *named* object in the reference dataset is what `programme` comes from — and **`budgetOverview` is a multi-kilobyte JSON blob** covering every topic in the parent call, which `_sedia_budget` reduces to this topic's contribution range.

## The dashboard (`web/`)

React + Vite + TypeScript, no backend, deployed to GitHub Pages by `.github/workflows/pages.yml`. It reads `calls.json` and nothing else — the Issues stay the notification path, this is the surface for reading and triaging what was already reported. Screens are the handoff's 2a (desktop split inbox), 3a (mobile inbox) and 3b (mobile detail); `useMediaQuery` switches at 900px.

Two contracts cross the language boundary and will break silently if only one side moves:

- `web/src/types.ts` mirrors the `calls_store.py` record and pins `SUPPORTED_FEED_VERSION`. Bump `FEED_VERSION` in Python and this together, or the app refuses the feed.
- **Triage state never goes into `calls.json`.** The watchers rewrite that file; anything user-authored in it is lost on the next run. It goes through the `TriageStore` interface in `web/src/storage/` — `local.ts` (localStorage, active) or `github.ts` (`triage.json` in the repo, stubbed pending OAuth).

`web/src/styles/nocturne.css` is vendored from the design handoff — do not edit it. Everything this product added sits in `app.css`. See `web/README.md`.

## Staging deploy

The dashboard is **not** on GitHub Pages. The repo is private under a free-plan org, which cannot publish Pages, so `pages.yml` exists with its push trigger commented out and is inert — leave it that way unless the repo goes public.

The live surface is a cPanel staging subdomain, deployed by `.github/workflows/deploy-staging.yml` on any push to `main` touching `web/**` or `calls.json`, so a watcher's state commit refreshes the dashboard on its own. cPanel was chosen over Vercel for one reason: access is host-level **Directory Privacy** (htpasswd), which cPanel does natively and Vercel charges for. Basic auth does not break the app — `calls.json` is fetched same-origin, so the browser replays the credentials.

Three things about that workflow are load-bearing:

- `BASE_PATH=/` (the `STAGING_BASE_PATH` variable). Vite writes every asset path relative to `base`; the default `/funding_radar/` is the Pages layout and would 404 everything at a subdomain root.
- `calls.json` is copied from the repo root into `web/public/` **before** the build. The copy checked into `web/public/` is a development sample and is what ships if that step is skipped.
- The upload excludes `.htaccess`/`.htpasswd`. Directory Privacy writes those on the host; a `mirror --delete` that did not exclude them would silently remove the auth on every deploy.

This is the project's first secret beyond the automatic `GITHUB_TOKEN` (`CPANEL_FTP_HOST` / `_USER` / `_PASS`). Scope that FTP account to the staging docroot only.

## Workflow caveats

Schedules are **UTC-only** — GitHub Actions has no `timezone:` support and silently ignores that key. Crons are therefore written in UTC (`0 5 * * 1` for the radar, `0 4 * * *` for the watcher), which lands at 07:00/06:00 Bucharest in winter and an hour later in summer. Do not "fix" this by re-adding `timezone:`.

**Scheduled runs start 4–5 hours late, consistently.** Every scheduled run so far began well after its cron time: the four MIPE runs (`0 4 * * *`) started 08:15, 08:34, 08:45 and 09:12 UTC, and the first radar run (`0 5 * * 1`) at 09:59 UTC — 4h15m to 5h12m late. GitHub queues scheduled workflows at low priority and defers them under load; nothing in this repo controls it. So the radar lands nearer 13:00 Bucharest than the 08:00 the cron implies. A late run is not a missed run, and tightening the cron does not help — the delay is not proportional to the time requested.

Both workflows commit state back to the repo with `[skip ci]` and need `contents: write` + `issues: write`. `mipe_watch.py` seeds its hash map from the previous run and prunes keys no longer in `WATCHED_PAGES`, so a page that fails to fetch keeps its baseline instead of resetting to a first check.
