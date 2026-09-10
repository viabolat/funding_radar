# Radar Finanțări

Watches Romanian and EU funding sources, matches every open call against an
organisation's configurable profile, and reports what fits by opening a GitHub
Issue. Scraping is organisation-agnostic; matching is a separate per-profile
step, so one deployment can serve several organisations.

The first tenant — and the profile the numbers in `CLAUDE.md` are calibrated
against — is **Vertical Freedom**, an NGO supporting cancer patients
(complementary and integrative therapies, psychotherapy, emotional support,
nutrition, prevention). Its profile lives in
`supabase/migrations/0004_seed_vertical_freedom.sql`, the only file that names it.

Two scheduled GitHub Actions do the watching; a small dashboard reads what they
found.

## What runs

| | Schedule | What it does |
|---|---|---|
| `funding_radar.py` | Mondays 05:00 UTC | Fetches the adieuronest.ro CSV feed and the EU Funding & Tenders (SEDIA) API, matches every open call against the exporting organisation's profile (the seed profile targets an oncology NGO), writes a digest and opens an Issue for anything new. |
| `mipe_watch.py` | Daily 04:00 UTC | Hashes the visible text of the MIPE call calendar. If it changed, opens an Issue asking a human to look. It deliberately does not parse that page. |
| `web/` | On push | React dashboard for reading and triaging what was reported. |

Notifications are **GitHub Issues only** — watching this repo is the entire
delivery path. No Slack, no Telegram, no email. That is a deliberate constraint,
not an omission.

## Running it locally

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q

cd web && npm install && npm run dev   # http://localhost:5173/funding_radar/
```

Both watchers write their state (`seen_calls.json`, `mipe_page_hashes.json`,
`calls.json`) into the working directory, so run them from a scratch folder
rather than the repo — a stale state file committed here will suppress the next
real run's alerts.

```bash
mkdir -p /tmp/radar && cd /tmp/radar
python /path/to/funding_radar.py    # hits the live sources, opens no Issue
```

## Where things are documented

- `CLAUDE.md` — architecture, the filtering rules and the numbers they were
  calibrated against, and every source quirk that has cost a debugging cycle.
- `web/README.md` — the dashboard, its two cross-language contracts, and what
  is still stubbed.
- `FIRST_RUN.md` — what the first deploy and the first watcher run actually do,
  the numbers to sanity-check them against, and the failures to expect. Read it
  before firing `funding-radar.yml` for the first time.
