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

Both scripts are idempotent-ish but **stateful**: running locally rewrites `seen_calls.json` / `mipe_page_hashes.json` / `calls.json` in the working directory, which will suppress the next real run's alerts if committed. Delete or restore those files after local experimentation.

## Architecture

**`funding_radar.py`** — fan-in from two sources into one `FundingCall` dataclass, then diff against state:

1. `fetch_adieuronest_calls()` — downloads a CSV feed from adieuronest.ro (Romania national + RO/MD/UA cross-border).
2. `fetch_eu_sedia_calls()` — one paged POST per keyword against the EU Funding & Tenders Portal SEDIA search API, merged into a dict keyed by call identifier so keyword overlap dedupes and `eu_sedia_language_preference` picks which language variant of a topic wins.
3. New = fetched ids minus `seen_calls.json`. Digest is written to `digests/digest_{date}.md`, an Issue opens only when the new count is non-zero, then **all** fetched ids (not just new ones) are merged into the seen store.

**`mipe_watch.py`** — MIPE (mfe.gov.ro) publishes its call calendar as an unparseable page/PDF, so this intentionally does *not* extract structured data. It strips markup with BeautifulSoup, collapses whitespace, SHA-256s the visible text, and compares to `mipe_page_hashes.json`. Changed → Issue asking a human to look and manually add anything relevant to the radar. Unchanged → a quiet log line, nothing else. Keep this change-detection-only shape; parsing that source is not worth the maintenance.

**`calls_store.py`** — the one module both scripts import, and the only intended exception to the duplication rule below. Both write the same `calls.json` feed, which is what the `web/` dashboard reads; two copies of that merge contract would drift, and drift there silently drops records.

Feed shape: `{"version": FEED_VERSION, "generated_at": ..., "calls": [...]}`, sorted by `call_id` so a commit diff shows real changes rather than dict reordering. Bump `FEED_VERSION` when a record field changes — the frontend refuses a version it does not know rather than rendering blanks. A record is `call_id, source, title, programme, deadline (ISO or null), announced, budget, tags, match_reason, link, first_seen`.

Each script owns its own sources and must never touch the other's rows, but the two owners need **different merge semantics**, which is the easiest thing here to get wrong:

- `funding_radar.py` **replaces** (`write_source_calls(..., owned_sources={"adieuronest", "eu_sedia"})`). It re-fetches its whole feed every run, so what it did not return is genuinely gone.
- `mipe_watch.py` **upserts** (`replace=False`). It reports only the pages that changed on that run, so replacing would pass an empty list on the first quiet day and delete every outstanding alert.

`first_seen` is carried over from the existing entry on both paths — it is when a call was first surfaced, not when it was last re-fetched, and the UI sorts on it. Triage state (status, assignee, note, reminder, snooze) is **not** in this file; it is user-authored and belongs in `triage.json`, keyed by the same `call_id`.

Both scripts share the same `create_resilient_session()` pattern (5 retries, backoff factor 2, jitter, honors `Retry-After`, retries 429/5xx) because neither upstream publishes a rate limit. Apart from `calls_store.py`, their shared helpers are duplicated by design — do not extract a second common module without a reason as concrete as that one.

## Testing

`tests/` runs entirely offline. `tests/conftest.py` puts the repo root on `sys.path` (the scripts are top-level modules, nothing to install) and provides three fixtures: `fake_session` (a URL→response/exception route table; SEDIA routes key on `(url, keyword)`), `fake_response`, and `capture_post` (monkeypatches `requests.post` on a given module and returns the recorded calls). Never let a test reach the network or the real GitHub API — add a route, not a live call.

`main()`-level tests use `monkeypatch.chdir(tmp_path)` because both scripts write state files relative to the working directory. `tests/fixtures/` holds real captured payloads — a trimmed SEDIA response (one topic in en/es/ro, one expired EU4H topic with no English variant) and four unedited CSV rows including the BOM. Rebuild them from a live response rather than hand-editing if a source changes shape.

Every quirk in the section above has a named regression test. These tests were mutation-checked: reintroducing each defect (BOM, GET, trusting `status`, WIDE-in-body, no eligibility gate) makes the suite fail.

The suite is wired to `.github/workflows/tests.yml` on push/PR.

## Filtering behavior

Both sources were calibrated against live responses; the numbers below are from the real feeds and are the baseline to compare against if a change makes the digest swing.

**adieuronest** (`CONFIG` in `funding_radar.py`) — a row must be BOTH applicable AND relevant:

- *Applicable*: `categorii` intersects `{ong, sanatate}` and `stare` is not `inchis`. The live vocabulary is exactly `companii, universitati, autoritati, ong, persoane, scoli, cultura, sanatate` — note `sanatate` appears on only 3 of 1162 rows, so `ong` carries the gate.
- *Relevant*: a CORE keyword anywhere in `titlu + program + solicitanti + finanteaza + conditii`, **or** a WIDE keyword in `titlu + program` only. The two-tier split is load-bearing: WIDE terms like `sănătate` are everywhere in boilerplate scope text (the PowerUp NetZero call matched on "sănătate animală"), so matching them in body prose alone pulled in 32 junk rows. In a title they are signal.
- Result: **37 of 1162 rows**, down from 495 under the old category-OR-keyword rule. Widen by moving a term from WIDE to CORE; narrow by dropping WIDE terms.
- Romanian keywords carry both diacritic and non-diacritic spellings, and match on stems (`oncolog`, `nutriți`) since Romanian inflects — `sănătate` does not match `sănătății`.

**EU SEDIA** — multi-word keywords are quoted. Unquoted, SEDIA does loose OR matching: `patient support` returns 943 junk hits, `"patient support"` returns 0 (the phrase is unused), `"mental health"` returns 9 real ones. Zero-hit phrases are kept on purpose — one request each, and they fire the day such a call appears.

## Source quirks that will bite you

Both parsers are now pinned to captured live payloads in `tests/fixtures/`. These are the non-obvious things that cost a debugging cycle each:

- **The CSV is served with a UTF-8 BOM.** Decode with `utf-8-sig`, or the first header becomes `\ufeffid` and `row.get("id")` silently returns `None` for every row.
- **There is no `descriere` column.** The prose lives in `solicitanti`, `finanteaza`, `conditii`. Deadlines are `termen` (dd.mm.yyyy) / `termen_iso`; the link column is `url`; money is `valoare_min`/`valoare_max`/`alocare`.
- **`cod` is blank on roughly half the feed**, so it cannot be a fallback ID on its own — an ID derived from the URL collides (17 rows share one `mfe.gov.ro` link).
- **The SEDIA API answers GET with 405.** It needs a POST with the filter as a multipart part named `query` containing JSON; free text and paging stay in the query string.
- **SEDIA `status` is unreliable.** `EU4H-2024-PJ-03-5` is still flagged `31094502` ("Open") with a deadline of 2025-01-21. Filter on the deadline, not the status. (`31094501` is Forthcoming, not Open — the old config name had this backwards.)
- **`deadlineDate` can be a list.** Multi-cutoff calls like the EIC Accelerator carry four; take the next one still ahead, not `[0]`.
- **Every topic is indexed once per translation** (~6 languages each, up to 23). Dedupe by `identifier` with a language preference, or the digest comes out in Spanish. An `en`-only filter is worse than `en`+`ro`: 6 of 16 topics have no English variant.
- **`frameworkProgramme` is an opaque numeric id** (`43108390`), and **`budgetOverview` is a multi-kilobyte JSON blob** covering every topic in the parent call.

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
