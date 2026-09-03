# web/ — Radar Finanțări dashboard

The staff-facing UI for the calls the two Python watchers surface. React + Vite
+ TypeScript, no CSS framework, no backend. Built from the design handoff
(screens **2a** desktop workspace, **3a** mobile inbox, **3b** mobile call
detail). All interface copy is Romanian — the office's working language.

## Commands

```bash
npm install
npm run dev        # http://localhost:5173/funding_radar/
npm run typecheck  # tsc --noEmit
npm run build      # tsc -b && vite build → dist/
npm run preview    # serve dist/
```

The dev server serves under `/funding_radar/` because that is the GitHub Pages
base path. Set `BASE_PATH` to host it anywhere else.

## Where the data comes from

`calls.json`, fetched at `${BASE_URL}calls.json`. It is written by
`calls_store.py` and committed by both watcher workflows; `.github/workflows/pages.yml`
copies the repo-root file into `public/` at build time. The copy checked in at
`public/calls.json` is a real captured feed kept for local development.

`src/types.ts` mirrors that record shape and pins `SUPPORTED_FEED_VERSION`. If
the Python side bumps `FEED_VERSION`, the app refuses the feed with a message
rather than rendering blanks — update both together.

## Triage state

Triage (status, assignee, note, reminder, snooze) is **user-authored and never
written to `calls.json`** — the watchers rewrite that file and would erase it.
It lives behind the `TriageStore` interface in `src/storage/`:

- `local.ts` — localStorage, per browser. The active adapter.
- `github.ts` — **stubbed**. Reads `triage.json` from the repo; writes throw
  until GitHub OAuth exists, which is why `writable` is `false`. Finishing it
  means keeping the blob `sha` from the read and re-applying the patch on a 409
  rather than forcing the write.

Swapping adapters is one line in `src/App.tsx`. Writes are optimistic: the UI
updates on click and the store call follows.

## Layout

`useMediaQuery(MOBILE_QUERY)` switches at 900px — below that the three desktop
panes cannot sit side by side, so the app renders 3a and, once a call is
opened, 3b.

## Styling

`src/styles/nocturne.css` is the design system's stylesheet, copied verbatim
from the handoff — treat it as vendored and do not edit it. Everything the
design added on top lives in `src/styles/app.css`: the semantic tokens
(`--color-urgent`, `--color-soon`, `--color-success`, `--color-panel`) and the
`.fr-*` component classes. Do not hard-code a hex outside `app.css`.

Deadline colouring is a single rule, in `src/lib/deadline.ts`: ≤14 days urgent,
≤45 days soon, else default. MIPE alerts have no deadline and show the amber
"verifică" prompt instead.

## Not built yet

- GitHub OAuth, and with it `triage.json` write-back.
- "Rezumat" (the weekly digest page, screen 2b) and "Surse" — the nav links are
  present but inert.
- The funnel chip in the desktop filter row.
