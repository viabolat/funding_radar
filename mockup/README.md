# Mockups for prospects

Client-facing demo of the Radar Finanțări dashboard, one file per prospect segment.
Not part of the watchers — nothing here is imported by `funding_radar.py` or the tests.

```
mockup/
  COPY.en.md           # English gloss of every client-facing string
  build_variants.py    # BRAND config + per-segment sample data; run this
  template.src.html    # the page (markup + component logic), before substitution
  dist/                # generated, gitignored — one sendable HTML file per segment
```

## Use

1. Fill in `BRAND` at the top of `build_variants.py`. Placeholders are written in
   `[square brackets]` and the build warns about any left unfilled.
2. `python3 mockup/build_variants.py`
3. Send `dist/Radar Finanțări - <segment>.html`.

Each file is self-contained — fonts, React and the icon set are embedded, so it opens
with no network access. It needs JavaScript.

## Adding a segment

Add an entry to `VARIANTS`: `org_type` and `profile_terms` drive the profile bar,
`subtitle` the header, `calls` the five sample rows. Segments are written to be sent to
*many* organisations of one kind — keep the copy about the category, never one named
institution.

## Why deadlines are offsets

`days` is an offset from today, not a date, and is formatted at render time. A file
mailed in March would otherwise show expired calls when opened in September — the exact
failure the product is sold to prevent. `seenDays` works the same way for "detectat
prima dată". Nothing needs re-running to stay current.

## Assets

`build_variants.py` copies the fonts and libraries out of the base bundle
(`../Radar Finanțări - machetă.html`) and only swaps the template block, so that file
has to stay put. It is the asset donor, not an output — edit `template.src.html`.

That bundle is **gitignored** — 6.9 MB of embedded fonts and React is not worth carrying
in every clone. A fresh clone therefore cannot build until it is put back at the repo
root; `build_variants.py` fails loudly rather than emitting a file with no assets.
