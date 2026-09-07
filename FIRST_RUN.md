# First deploy & first run — what to expect

Written 2026-09-03, against commit `164e9b3`. Numbers below come from real runs, not estimates; where something is untested it says so.

Read this before firing `funding-radar.yml` for the first time. The radar's first run is the only one that behaves differently from every run after it, and one of the three watchers is currently broken in a way that looks like success.

---

## Status at a glance

| Thing | State | Evidence |
|---|---|---|
| Test suite in CI | Passing | 64 tests, `tests.yml` |
| Workflow `contents: write` | Confirmed working | run `33747227918` logged `Contents: write` and committed state back |
| Issue labels exist | Fixed 2026-09-03 | `funding-radar`, `mipe-watch` created on the repo |
| `web/` build at `BASE_PATH=/` | Confirmed working in CI | run `33748134678`, built in 6.89s |
| cPanel upload | Never succeeded | blocked on secrets |
| `mipe_watch.py` on CI | **Cannot work — host blocks GitHub IPs** | probe `33773493284`, §3 |
| `funding_radar.py` on CI | Confirmed working | probe pulled 35 + 22 calls from a runner |

---

## 1. The staging deploy

### Before it can work

Four things must exist, none of which are in the repo:

1. The cPanel subdomain and its document root.
2. An FTP account scoped to that docroot **only**.
3. Directory Privacy enabled on the docroot (this is the access control — there is no application-level login).
4. Repo secrets `CPANEL_FTP_HOST`, `CPANEL_FTP_USER`, `CPANEL_FTP_PASS`, and repo variables `STAGING_REMOTE_DIR`, `STAGING_BASE_PATH=/`.

### What a good run looks like

Six steps. The first five are already proven — run `33748134678` got through all of them on a repo with no secrets at all:

```
dist/index.html                   0.47 kB │ gzip:  0.30 kB
dist/assets/index-*.css          16.86 kB │ gzip:  3.63 kB
dist/assets/index-*.js          207.42 kB │ gzip: 63.83 kB
✓ built in 6.89s
```

The asset hashes change on every build; the sizes should not move much. A JS bundle that suddenly doubles means a dependency got pulled into the client bundle by accident.

### Known failure modes, in the order you will hit them

**`mirror: Not connected`** — this is what an unconfigured run produces, and it is what run `33748134678` produced. It means lftp never authenticated. Almost always missing or wrong secrets rather than anything subtle.

**Certificate verification failure.** The workflow sets `ssl:verify-certificate true` on purpose. Shared cPanel hosts routinely present a certificate for `serverN.hostingcompany.com`, not for your domain, so this *will* fail if `CPANEL_FTP_HOST` is set to the pretty hostname. The fix is to point `CPANEL_FTP_HOST` at the hostname the certificate actually covers — **not** to disable verification. If the host offers SFTP on port 22, switching to that is cleaner than either.

**Everything 404s but `index.html` loads.** `STAGING_BASE_PATH` was not set to `/`. Vite writes every asset path relative to `base`, and the default is the GitHub Pages layout `/funding_radar/`.

**The dashboard loads but shows no calls.** Either the repo-root `calls.json` was empty at build time (it is, right now — see §2), or the browser is looking at `web/public/calls.json`, the development sample.

**Auth silently disappears after a deploy.** Should not happen: the upload excludes `.htaccess` and `.htpasswd`, because Directory Privacy writes those into the docroot and `mirror --delete` would otherwise remove them. If you ever edit that exclude list, this is the thing you are protecting.

### After the first success

The workflow fires on any push to `main` touching `web/**` or `calls.json`. Since both watchers commit `calls.json` back to the repo, **a watcher run refreshes the dashboard on its own** — no second action needed. The `concurrency` group means a newer deploy cancels an in-flight older one, so an old build cannot land on top of a newer feed.

---

## 2. The first `funding_radar.py` run

This is the run that behaves unlike all the others, because `seen_calls.json` does not exist on the remote yet.

### Expect one large Issue

Everything the radar finds is "new" on a first run. A real run today produced:

```
adieuronest.ro: 35 matching calls after filtering
EU SEDIA API: 22 unique matching calls after merge
Total fetched: 57 | Already seen: 0 | New: 57
```

So expect a single Issue titled roughly **"Funding Radar: 57 new call(s) — YYYY-MM-DD"**, labelled `funding-radar`, listing all of them grouped by source. Every subsequent run reports only the delta and will normally be a handful or zero. **A first-run Issue with ~57 calls is correct, not a filter bug.** If it reports several hundred, that is the filter regressing — the calibrated baseline is 35–37 of ~1160 CSV rows, and the old category-OR-keyword rule produced 495.

Also expect **no Issue at all on a quiet run**. That is deliberate and not a failure.

### What gets committed back

- `seen_calls.json` — from this point on it suppresses re-reporting. Never commit a locally generated copy; it will silence the next real run.
- `calls.json` — the feed the dashboard reads. Goes from 0 rows to 57.
- `digests/digest_<date>.md` — a human-readable copy of the same content.

Commit message ends with `[skip ci]` so the state commit does not re-trigger the watchers, but it **does** match `deploy-staging.yml`'s path filter, so the dashboard redeploys. That is intended.

### Feed shape you should see afterwards

Of the 57 rows, as of 2026-09-03: 47 carry a deadline, 55 carry a budget, all 57 `call_id`s are unique. By the dashboard's colour rule that lands as 17 urgent (≤14 days), 9 soon (15–45), 21 normal, 10 with no deadline at all. A feed where *nothing* has a deadline means the date parsing broke; a feed where every row is urgent means the deadline filter is letting expired calls through.

### Scheduling

`0 5 * * 1` — Mondays, 05:00 **UTC**. That is 08:00 Bucharest in summer, 07:00 in winter. GitHub Actions cron has no timezone support and silently ignores a `timezone:` key, so this drifts by an hour twice a year by design. Do not "fix" it.

**In practice it runs 4–5 hours later than that.** The first scheduled run fired at 09:59 UTC on 2026-09-07, not 05:00, and the four MIPE runs before it were late by 4h15m to 5h12m. GitHub queues scheduled workflows at low priority and defers them under load. A late run is not a missed run — expect the radar nearer 13:00 Bucharest than 08:00, and do not tighten the cron to compensate.

The first run has already happened, unattended and on schedule — see open item 3.

---

## 3. `mipe_watch.py` — unmonitored, because runners cannot reach the host

**Nothing here needs a code change any more.** Both code-side problems below are
fixed; what is left is a hosting decision (open item 1).

Run `33747227918` reported success at every step. It did no work at all:

```
[WARNING] Retrying (Retry(total=4, ...)) after connection broken by
  'NewConnectionError("HTTPSConnection(host='mfe.gov.ro', port=443):
   Failed to establish a new connection: [Errno 101] Network is unreachable")'
   ... ×5
[ERROR] Failed to fetch calendar_apeluri_general (https://mfe.gov.ro/calendar-apeluri-de-proiecte/)
[INFO] No pages changed — skipping issue creation (no noise for a no-op run).
```

All five retries failed to connect, the only watched page was skipped, `mipe_page_hashes.json` was committed as `{}`, and the script exited 0.

Two separate problems. Connectivity probe run `33773493284` settled both.

**a) mfe.gov.ro blocks GitHub's IP ranges. Confirmed, and not fixable in this repo.**

The probe connected to each resolved address separately, from a runner and from a developer machine:

| | developer machine | GitHub runner |
|---|---|---|
| outbound IPv6 | none | none |
| `mfe.gov.ro` `193.151.29.8` (A) | connected, 12ms | **timed out after 15s** |
| `mfe.gov.ro` `2a00:5dc2::8` (AAAA) | ENETUNREACH | ENETUNREACH |
| `adieuronest.ro` | connected | connected |
| `api.tech.ec.europa.eu` | connected | connected |

Neither machine has IPv6, so the unreachable AAAA is normal and is not the cause — it fails identically in both columns. The difference is the **IPv4** address: 12ms locally, a silent 15-second timeout from the runner. Dropped, not refused. That is a firewall filtering cloud IP ranges, and no amount of retrying, backoff or forcing IPv4 will get past it.

**The original error message was actively misleading.** urllib3 walks the getaddrinfo list and reports only the last error, so the IPv6 `ENETUNREACH` masked the IPv4 timeout underneath it and made this look like an IPv6 problem. If you see `Network is unreachable` from a dual-stack host, check each address family separately before believing it.

Fixing this means running `mipe_watch.py` from somewhere that is not a GitHub runner — the cPanel host is Romanian and already in the picture, so a cron job there is the obvious candidate; a self-hosted runner is the other. **Until then, treat MIPE as unmonitored.**

**The daily schedule is disabled as of 2026-09-07.** Once a total fetch failure
started exiting non-zero, the 04:00 cron would have gone red every single day
for a cause this repo cannot reach — and a failure email a day is how a team
learns to ignore CI. The `schedule:` block in `mipe-watch.yml` is commented out
with the reason inline; `workflow_dispatch` still works, so you can run it by
hand any time, and it will still fail from a runner. Uncomment that block when
the watcher moves to a host that can reach mfe.gov.ro. It was **not** fixed by
teaching the script to tolerate the failure quietly: that is the silent-green
bug from (b) rebuilt under a new name.

**b) A total fetch failure exited 0. Fixed 2026-09-03.** The watcher now exits non-zero when *every* watched page fails, so CI shows red instead of a green quiet run. A partial failure still exits 0 — the pages that did fetch were genuinely checked, and failing the run on one dead page would mean noise on every run until it came back. State handling is unchanged: baselines are still kept for pages that failed, no Issue, no feed rows. Two regression tests cover both directions (suite is now 66 tests).

The baseline-seeding behaviour was correct throughout: a page that fails to fetch keeps its previous hash rather than resetting, so nothing was corrupted by the failed runs — there is simply no baseline yet.

**`adieuronest.ro` and the SEDIA API both work from a GitHub runner.** The probe pulled 35 and 22 calls from CI, matching the local numbers exactly. The Monday radar schedule is safe; only MIPE is affected.

---

## 4. First load of the dashboard

Assuming a deploy succeeded and the radar has run once:

- The browser prompts for the Directory Privacy credentials first. After that, `calls.json` is fetched same-origin and the browser replays the credentials automatically — basic auth does not break the app.
- Every call shows as **Nou**, because triage state starts empty. Sorted newest `first_seen` first, so on a first run the ordering within the group is by deadline.
- MIPE rows would default to **De verificat** rather than **Nou** — a change alert is something to look at, not something to apply for. There will not be any yet (see §3).
- Triage is stored in **localStorage**, per browser. It is not shared between people and does not survive clearing site data. Sharing it needs the GitHub OAuth adapter, which is stubbed (`web/src/storage/github.ts`, `writable: false`).
- `CURRENT_USER` is hardcoded to `"Ana M."` in `App.tsx` and the staff roster in `web/src/staff.ts` is placeholder data.
- The *Rezumat* and *Surse* nav links and the funnel chip are inert.
- The `reminder` flag is stored but nothing reads it — no reminder will ever fire.
- If the app refuses the feed with a version error, `FEED_VERSION` in `calls_store.py` and `SUPPORTED_FEED_VERSION` in `web/src/types.ts` have drifted apart. They must be bumped together.

---

## 5. Things that will look wrong and are not

- **No Issue after a watcher run.** Correct when nothing is new. Both scripts stay quiet on purpose.
- **`pages.yml` never runs.** Its push trigger is commented out. A private repo on a free-plan org cannot publish Pages; the file is kept in case the repo goes public.
- **Two commits per watcher run.** The state commit is separate from anything else and carries `[skip ci]`.
- **The dashboard redeploying by itself.** A watcher committing `calls.json` matches the deploy path filter. Intended.
- **A call vanishing from the dashboard.** `funding_radar` replaces its own rows every run, so a call withdrawn upstream disappears. It was already reported as an Issue; the Issue is the durable record, the dashboard is not.
- **Romanian diacritics look fine in the app but mangled in Excel.** They should not — the CSV export writes a BOM specifically to stop Excel reading UTF-8 as Latin-1. If they are mangled, that BOM was lost.

---

## 6. Open items

1. Decide where `mipe_watch.py` runs, since GitHub-hosted runners are blocked: cron on the cPanel host, or a self-hosted runner. Its GitHub schedule is off until then, so MIPE is checked by nobody — this is the only open item that loses coverage while it waits. Deciding needs one fact this repo does not record: whether the cPanel plan gives shell/cron access and a Python 3 runtime, or only the FTP account `deploy-staging.yml` uses.
2. Delete `.github/workflows/connectivity-probe.yml` — it has answered its questions.
3. ~~Fire the first `funding-radar.yml` run manually and watch it.~~ **Done 2026-09-07**, though not manually — the Monday cron fired it (~5h late, see §2) before anyone got to it. 58 calls matched: 36 adieuronest + 22 SEDIA, against a probe expectation of 35 and 22 and a calibrated 37. Opened Issue #1, committed `seen_calls.json` (58 ids), `calls.json` and `digests/digest_2026-09-07.md`. Both sources landed inside their expected bands; nothing to investigate.
4. Complete the cPanel setup and get one green `deploy-staging` run.
5. Replace the placeholder staff roster and `CURRENT_USER`.
6. Shared triage via GitHub OAuth — this also unblocks reminders.
