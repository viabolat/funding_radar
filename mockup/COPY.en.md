# What the mockups say, in English

The mockups are Romanian because the prospects are Romanian institutions. This file is
the gloss, so the claims can be checked without reading Romanian. **It is maintained by
hand — if you change Romanian copy in `build_variants.py` or `template.src.html`, change
the English here in the same edit, or this file quietly becomes a lie.**

## The brand block — the claims you are making

| Romanian (in `BRAND`) | English |
|---|---|
| ViaBolat | — |
| Urmărim automat sursele de finanțare europene și naționale și vă semnalăm doar apelurile care se potrivesc organizației dumneavoastră. | "We automatically track European and national funding sources and flag only the calls that match your organisation." |
| Programați o demonstrație | "Book a demonstration" (the CTA button) |
| ViaBolat — solicitare demonstrație | "ViaBolat — demonstration request" (the email subject the button composes) |
| Pasul următor: o discuție de 30 de minute în care configurăm profilul organizației dumneavoastră și vă arătăm apelurile reale, deschise în acest moment. | "Next step: a 30-minute conversation in which we configure your organisation's profile and show you the real calls open right now." |

These commit you to two things: that tracking is **automatic**, and that a 30-minute call
ends with **real open calls** on screen. No frequency is claimed — deliberately, because
the radar currently runs weekly and the MIPE watcher's schedule is commented out (which
is also why MIPE is no longer named as a source anywhere in the mockups).

## The honesty notice

> Machetă de prezentare — apelurile, termenele și bugetele de mai sus sunt exemple
> ilustrative. În aplicație, lista se actualizează automat, săptămânal, din sursele
> oficiale și este filtrată după profilul organizației dumneavoastră.

"Presentation mockup — the calls, deadlines and budgets above are illustrative examples.
In the application, the list updates automatically, weekly, from the official sources and
is filtered against your organisation's profile."

This scopes to the **data**: the rows on screen are examples, not live calls. That is the
one claim worth making, because a prospect could otherwise read the sample rows as calls
open to them today. It says nothing about which features ship — see the last section.

"Weekly" is the real cadence — `.github/workflows/funding-radar.yml` is `cron: "0 5 * * 1"`.
This is the sentence that keeps the demo honest. Do not remove it.

## Header and chrome

| Romanian | English |
|---|---|
| ViaBolat | the product name (header h1 and app nav) |
| radar de finanțări nerambursabile | "non-reimbursable funding radar" (lowercase descriptor under the name) |
| Machetă · date fictive | "Mockup · fictitious data" (badge, top right) |
| Profilul organizației | "The organisation's profile" |
| profil configurabil | "configurable profile" |
| Apeluri / Rezumat / Surse | "Calls / Summary / Sources" (nav) |
| Primite | "Inbox" (mobile back label) |

## Row and detail labels

| Romanian | English |
|---|---|
| Termen | "Deadline" |
| Buget | "Budget" |
| buget total al apelului | "the call's total budget" |
| De ce a apărut | "Why this appeared" (the match explanation) |
| detectat prima dată | "first detected" |
| Note pentru echipă | "Notes for the team" |
| Responsabil | "Owner / assignee" |
| Memento | "Reminder" |
| cu 7 zile înainte de termen | "7 days before the deadline" |
| peste N zile / mâine este termenul / astăzi este termenul | "in N days" / "the deadline is tomorrow" / "the deadline is today" |

## One word for the customer, throughout

Every client-facing string says **organizație** (`organizației dumneavoastră`, `profilul
organizației`, `PROFILUL ORGANIZAȚIEI`) — never *instituție*. It reads correctly for an
NGO, a city hall and a university alike, whereas *instituție* is a stretch for an NGO.
The one exception is a segment's own official category name, which is a label rather than
the product's voice: the university variant's profile still reads "Instituție de
învățământ superior". Keep both rules if you edit.

## Statuses and filters

| Romanian | English |
|---|---|
| Nou / Relevant / Depus / Nerelevant / De verificat | "New / Relevant / Submitted / Not relevant / To check" |
| Toate / Noi / Relevante / Depuse | "All / New / Relevant / Submitted" (the four filter tabs, each with a count) |

## Buttons

| Romanian | English |
|---|---|
| Deschide pe portal / Deschide portalul | "Open on the portal" (desktop / mobile) |
| Distribuie | "Share" |
| Arhivează | "Archive" |

## Toasts — shown on click

Neutral phrasing: each describes the feature, without asserting what does or does not ship
today. That is deliberate — a mockup shows the product being sold, and volunteering
limitations to a prospect is not the mockup's job. Keep them tense-free if you edit.

| Romanian | English |
|---|---|
| Căutare după titlu, program, motivul potrivirii și etichete. | "Search by title, programme, match reason and tags." |
| Se deschide pagina oficială a apelului pe portalul finanțatorului. | "The call's official page opens on the funder's portal." |
| Linkul apelului se copiază în clipboard; lista vizibilă se exportă în CSV. | "The call's link is copied to the clipboard; the visible list exports to CSV." |
| Apelul este arhivat; îl puteți reactiva oricând. | "The call is archived; you can reactivate it at any time." |
| Responsabil actualizat. | "Owner updated." |
| Status actualizat. | "Status updated." |
| Memento actualizat. | "Reminder updated." |

## Per-segment copy

**general** — profile "Organizație neguvernamentală" (NGO). Subtitle: "Tracks and triages
in one place the funding calls from European and national sources, filtered against your
organisation's profile." Sample calls: digitalisation of local public services; vocational
training and green skills; social economy and active inclusion; support for NGOs and
community initiatives; urban regeneration and green public spaces.

**sanatate** — profile "Organizație neguvernamentală din domeniul sănătății" (health-sector
NGO), profile bar terms "cancer · terapii complementare · psihoterapie · nutriție".
Subtitle: "Configured for health-sector organisations: tracks and triages in one place the
patient-support, mental-health and prevention calls from European and national sources."
Sample calls: strengthening cancer screening and early detection (EU4Health); psychosocial
support and quality of life for cancer survivors (Horizon Europe Cancer Mission);
development of palliative and home-care services (Programul Operațional Sănătate);
community mental-health and emotional-support services (PNRR); nutrition and complementary
therapy programmes for oncology patients (adieuronest). Terms are drawn from
`funding_radar.SEED_PROFILE` so the demo matches what the matcher actually does.

**primarii** — profile "Autoritate publică locală" (local public authority). Subtitle:
"Configured for local public administration: tracks and triages in one place the urban
regeneration, mobility and infrastructure calls from European and national sources."
Sample calls: urban regeneration of degraded areas; sustainable urban mobility;
modernisation of water and sewerage networks; energy retrofit of public buildings;
pedestrian zones and cycle lanes.

**universitati** — profile "Instituție de învățământ superior" (higher education
institution). Subtitle: "Configured for higher education: tracks and triages in one place
the Erasmus+, research and educational infrastructure calls from European and national
sources." Sample calls: higher education cooperation partnerships; international mobility
for students and teaching staff; digital infrastructure for university research; doctoral
research grants; equipping teaching and research laboratories.

## Two names appear in the demo data

"Ana M." and "Dan P." are fictional colleagues shown as assignees, and "AM" is the avatar
in the navigation bar. They are placeholders, not real people.

## Where the mockup runs ahead of the product

Checked against the code on 2026-09-09. None of this makes the mockup wrong — it depicts
the product being sold. It is here so nobody walks into a demo call unprepared for the
question, and so a future edit does not accidentally turn a depiction into a written
promise. Two things were corrected in the copy because accuracy cost nothing: the export
is **CSV, not PDF**, and the cadence is **weekly**.

- **No email exists anywhere in the product.** Phase F (`notify.py` / Resend) is not
  started; `notify.py` is absent. Alerts reach people as GitHub Issue notifications.
- **Triage is per-browser.** Status, notes and assignee live in one browser's
  localStorage. Two colleagues do not see each other's work. The in-app label
  "Note pentru echipă" ("Notes for the team") overstates this **in the real product**,
  not only in the mockup — worth fixing there too.
- **No accounts.** `CURRENT_USER` is the hardcoded string "Ana M." (`web/src/App.tsx:18`).
- **"Arhivează" is really a snooze toggle**, with no separate archive view.
