#!/usr/bin/env python3
"""
Per-organisation matching.
==========================

The whole point of the multi-org restructure lives in this file. Until Phase C
the CORE/WIDE keyword gate ran *inside* `fetch_eu_calls()` and
`fetch_adieuronest_calls()`, so the scrapers did not collect funding calls —
they collected one organisation's funding calls, and everything they rejected
was rejected permanently for every future tenant. Here relevance is a pure
function of `(warehouse call, organisation profile)`, computed after the fact,
so a second organisation is a row insert and a rematch rather than a re-scrape.

`match_call` and `match_all` touch nothing: no network, no clock, no files, no
global config. Same inputs, same output, always. The CLI at the bottom is the
only part that does I/O, and it does nothing but read the warehouse, call these
functions, and write the results back.

When this runs
--------------
**After every scrape, and it rematches every calibrated organisation every
time.** The warehouse changes on every run — calls arrive, calls expire, calls
are withdrawn — so "has this org's profile changed?" is the wrong question to
gate on. Profiles change rarely and the call set changes constantly; skipping a
run because a profile was stable is how an organisation stops being told about
new funding while its dashboard still looks healthy. Matching is pure substring
work over a few thousand rows, so there is nothing worth saving here and a
staleness optimisation could only ever cost an org a call it should have seen.

`profile_hash` is therefore a **stamp**, not a skip condition. It is written on
every match row so it is possible to ask which profile version produced a given
match, and to find rows still carrying an older one.

The two-tier rule, and what it preserves
----------------------------------------
Lifted verbatim from the two gates it replaces, which were calibrated against
live responses and are not to be re-derived:

  * CORE terms match `search_core` — the whole record for a Romanian row
    (title + programme + the eligibility and funding prose), title + callTitle
    for an EU one. A mission term is signal wherever it appears.
  * WIDE terms match `search_wide` only — title + programme for a Romanian row,
    title alone for an EU one. Broad health vocabulary is everywhere in
    boilerplate scope text; in a name it is signal.
  * A **context guard** in `search_wide` cancels the WIDE contribution and
    nothing else. "Health of ecosystems and wild species, predictions and
    impacts on human health" is a biodiversity call, not a health one.

**Guards never veto a CORE match.** That is not a simplification, it is what
`_eu_matches()` did: it returned on a core hit before the guard list was ever
consulted. A call whose own name says `cancer` is not disqualified by the word
`animal` appearing elsewhere in it.

Deliberately NOT here: diacritic folding
----------------------------------------
`sănătate` and `sanatate` are both listed in the seed profile because Romanian
inflects and the feed is inconsistent about diacritics. Folding them here would
look like a tidy-up and would change results twice over: a folded profile
matches strings today's gate does not, and both spellings of a term would then
report as two separate matched terms in the same "De ce a apărut" line. Folding
belongs in `--calibrate` (which only ever writes a proposal) and in cross-source
dedup, neither of which decides what an organisation sees.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass

from warehouse import SOURCE_LANG, Warehouse

log = logging.getLogger("match")

# CORE outranks WIDE, and the tier already records which fired, so the score
# only has to break ties WITHIN a tier — more matched terms is a stronger match.
# The weight is 10 rather than 2 so no realistic number of WIDE hits can lift a
# wide-tier match above a core-tier one in a naive `order by score`.
CORE_WEIGHT = 10


@dataclass(frozen=True)
class Match:
    """One (organisation, call) relevance verdict.

    Frozen because a Match is derived output. Anything that wants to change it
    should change the profile and rematch.
    """

    call_id: str
    tier: str                      # 'core' | 'wide'
    matched_terms: tuple[str, ...]
    match_reason: str
    score: int

    def to_row(self, org_id: str, profile_hash_value: str) -> dict:
        """The `org_call_matches` row.

        `first_matched_at` is omitted on purpose, exactly as `first_seen` is
        omitted from a warehouse upsert: it is when this call became new TO THIS
        ORG, the column the org's inbox sorts on, and a rematch must not reset
        it. PostgREST updates only the columns a request carries — which is what
        makes rematching on every run free of side effects.
        """
        return {
            "org_id": org_id,
            "call_id": self.call_id,
            "tier": self.tier,
            "matched_terms": list(self.matched_terms),
            "match_reason": self.match_reason,
            "score": self.score,
            "profile_hash": profile_hash_value,
        }


def match_reason(matched: list[str] | tuple[str, ...]) -> str:
    """Romanian copy for the dashboard's "De ce a apărut" callout — the office's
    working language, per the design handoff.

    Terms arrive in profile order, not match order or alphabetical order, and
    the first four are shown. That ordering is load-bearing for the Phase C
    acceptance gate: it is what today's digest says.
    """
    if not matched:
        return ""
    terms = ", ".join(f"„{term}”" for term in matched[:4])
    if len(matched) == 1:
        return f"Cuvânt cheie potrivit {terms}."
    return f"Cuvinte cheie potrivite {terms}."


def is_calibrated(profile: dict) -> bool:
    """Whether this profile has been given a matching vocabulary at all.

    Missing and empty are different states and the difference is visible to the
    organisation. A profile with **no** `matching` key has never been calibrated
    — a new signup, whose dashboard says so rather than showing an empty inbox
    that reads as "no funding exists for you". A profile with `matching` present
    but narrow (`{"ro": {"core": []}}`) is a deliberate choice, is matched
    normally, and legitimately returns nothing.
    """
    return "matching" in profile


def profile_hash(profile: dict) -> str:
    """Fingerprint of the parts of a profile that can change what matches.

    Exactly `matching` and `eligible_as`, and nothing else. Editing the mission
    text, the notification email or the notify preferences must not change the
    stamp on a match row — and `--calibrate` writing `suggested_terms` must not
    either, or a proposal nobody has reviewed would look like a profile change.
    """
    material = {
        "matching": profile.get("matching") or {},
        "eligible_as": profile.get("eligible_as") or [],
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _terms(call: dict, profile: dict) -> tuple[list[str], list[str], list[str]]:
    """The three term lists for this call's language.

    Terms are grouped by language rather than by source because they were
    calibrated against text in different languages and are not interchangeable:
    `screening` is CORE in the Romanian list and WIDE in the English one, and
    the English guard `animal` is a substring of Romanian `animală`. A call in a
    language the profile says nothing about matches nothing — which is a narrow
    profile, not a broken one.
    """
    lang = (call.get("lang") or SOURCE_LANG.get(call.get("source", ""), "")).strip()
    bucket = (profile.get("matching") or {}).get(lang) or {}
    return (
        [str(t).lower() for t in bucket.get("core") or []],
        [str(t).lower() for t in bucket.get("wide") or []],
        [str(g).lower() for g in bucket.get("guards") or []],
    )


def _eligible(call: dict, profile: dict) -> bool:
    """Whether this organisation is the kind of applicant the call is open to.

    Fires only when BOTH sides have said something and they do not overlap.

      * An empty `calls.eligible_as` means the source published no applicant
        vocabulary at all — the EU dataset does not — which is "unknown", never
        "open to nobody". Filtering on it would drop the entire EU feed.
      * An absent or empty `profile.eligible_as` means unfiltered, and
        specifically NOT a default of `{ong, sanatate}`. A new tenant must not
        inherit the first tenant's eligibility; that is the exact shape of the
        single-tenancy this phase removes.
    """
    wanted = {str(v).lower() for v in profile.get("eligible_as") or []}
    offered = {str(v).lower() for v in call.get("eligible_as") or []}
    if not wanted or not offered:
        return True
    return bool(wanted & offered)


def match_call(call: dict, profile: dict) -> Match | None:
    """Relevance of one warehouse call to one organisation, or None."""
    if not is_calibrated(profile):
        return None
    if not _eligible(call, profile):
        return None

    core, wide, guards = _terms(call, profile)
    surface_core = (call.get("search_core") or "").lower()
    surface_wide = (call.get("search_wide") or "").lower()

    core_matched = [term for term in core if term in surface_core]
    wide_matched = [term for term in wide if term in surface_wide]
    # reason: the guard cancels the WIDE contribution only. `_eu_matches()`
    # returned on a core hit before it ever looked at the guard list, so a guard
    # that vetoed the whole match would silently drop calls that match today —
    # and would drop them for the strongest reason there is, their own name.
    if wide_matched and any(guard in surface_wide for guard in guards):
        wide_matched = []

    if not core_matched and not wide_matched:
        return None

    matched = core_matched + wide_matched
    return Match(
        call_id=call["call_id"],
        tier="core" if core_matched else "wide",
        matched_terms=tuple(matched),
        match_reason=match_reason(matched),
        score=CORE_WEIGHT * len(core_matched) + len(wide_matched),
    )


def match_all(calls: list[dict], profile: dict) -> list[Match]:
    """Every match for one organisation, in the order the calls arrived.

    An uncalibrated profile returns `[]`. It never falls back to a default term
    list and never borrows another organisation's — a plausible-looking inbox of
    the wrong calls is worse than an empty one, because nothing about it looks
    wrong.
    """
    if not is_calibrated(profile):
        return []
    matches = (match_call(call, profile) for call in calls)
    return [match for match in matches if match is not None]


# ---------------------------------------------------------------------------
# CALIBRATION PROPOSALS
#
# Deterministic, dumb on purpose, and never authoritative. It reads the mission
# prose an organisation typed into the signup form and proposes terms into
# `profile.suggested_terms`, which nothing matches against. An operator reviews
# the proposal and promotes it into `profile.matching`.
#
# This is the seam the deferred AI derivation drops into — `Provider.
# derive_profile_terms(mission)` replaces the body of `suggest_terms` and
# nothing else moves, because the proposal-then-promotion split already exists.
# ---------------------------------------------------------------------------

# Enough to stop the proposal being a list of function words. Not a linguistic
# resource; a longer list would not make an unreviewed proposal safe to promote.
_RO_STOPWORDS = {
    "pentru", "care", "acest", "aceasta", "aceste", "prin", "asupra", "dintre",
    "sunt", "este", "fost", "avea", "avut", "poate", "trebuie", "astfel",
    "precum", "altele", "aceea", "atat", "atât", "cadrul", "domeniul", "scopul",
    "activitati", "activități", "proiect", "proiecte", "organizatie",
    "organizație", "asociatie", "asociație", "fundatie", "fundație",
}


def fold(text: str) -> str:
    """Strip Romanian diacritics. Used by calibration and by nothing that
    decides a match — see this module's docstring."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def suggest_terms(mission: str, limit: int = 12) -> dict:
    """Propose CORE terms from mission prose. A proposal, never a profile."""
    folded_stopwords = {fold(word) for word in _RO_STOPWORDS}
    counts: dict[str, int] = {}
    for token in re.findall(r"[a-zăâîșşțţ]+", mission.lower()):
        if len(token) < 5 or fold(token) in folded_stopwords:
            continue
        # Truncated to a stem because Romanian inflects: the feed carries
        # `sănătății` where the mission says `sănătate`, and a substring gate
        # only sees the shared prefix.
        stem = token[:8]
        counts[stem] = counts.get(stem, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"ro": {"core": [term for term, _ in ranked[:limit]], "wide": [], "guards": []}}


# ---------------------------------------------------------------------------
# CLI — the only part of this file that performs I/O
# ---------------------------------------------------------------------------

def run_org(warehouse: Warehouse, org: dict, calls: list[dict]) -> int:
    """Rematch one organisation against the current warehouse, unconditionally.

    There is no "nothing changed, skip" branch, and adding one would be a
    defect rather than an optimisation — see this module's docstring. The only
    organisations skipped are those with no matching vocabulary at all.
    """
    org_id = org["id"]
    name = org.get("name") or org_id
    profile = org.get("profile") or {}

    if not is_calibrated(profile):
        log.info("%s skipped: pending calibration", name)
        return 0

    stamp = profile_hash(profile)
    matches = match_all(calls, profile)
    warehouse.upsert_matches([match.to_row(org_id, stamp) for match in matches])

    # reason: an upsert alone leaves behind every call the previous run matched
    # and this one does not — a call that expired, was withdrawn, or fell out
    # when the profile narrowed. The org would keep seeing rows its own settings
    # now exclude, with nothing on screen to say why they are still there.
    live = {match.call_id for match in matches}
    stale = [row["call_id"] for row in warehouse.fetch_matches(org_id) if row["call_id"] not in live]
    warehouse.delete_matches(org_id, stale)

    log.info("%s: %d match(es), %d dropped (profile %s)", name, len(matches), len(stale), stamp)
    return len(matches)


def main() -> None:
    parser = argparse.ArgumentParser(description="Match warehouse calls to organisation profiles.")
    parser.add_argument("--org", metavar="NAME_OR_ID", help="Match one organisation instead of all.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print matches, write nothing.",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Propose terms from each organisation's mission into profile.suggested_terms. "
             "Never writes the live matching lists.",
    )
    parser.add_argument("--evidence", metavar="DIR", help="Write a provenance manifest to DIR.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Local imports: `match_all` must stay importable — and testable — without
    # dragging in the scrapers or the provenance writer.
    from provenance import Recorder
    import funding_radar

    recorder = Recorder(args.evidence)
    warehouse = Warehouse(
        url=os.environ.get("SUPABASE_URL"),
        service_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        session=funding_radar.create_resilient_session(),
        recorder=recorder,
        user_agent=funding_radar.CONFIG["user_agent"],
        dry_run=args.dry_run,
    )
    if not warehouse.enabled:
        log.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        sys.exit(1)

    orgs = warehouse.fetch_organizations()
    if args.org:
        orgs = [org for org in orgs if args.org in (org.get("id"), org.get("name"))]
        if not orgs:
            log.error("no organisation matching %r", args.org)
            sys.exit(1)

    if args.calibrate:
        for org in orgs:
            profile = dict(org.get("profile") or {})
            mission = profile.get("mission") or ""
            if not mission:
                log.info("%s: no mission text to calibrate from", org.get("name"))
                continue
            profile["suggested_terms"] = suggest_terms(mission)
            if args.dry_run:
                print(json.dumps({org.get("name"): profile["suggested_terms"]},
                                 ensure_ascii=False, indent=2))
            else:
                warehouse.update_org_profile(org["id"], profile)
            log.info("%s: wrote suggested_terms (live lists untouched)", org.get("name"))
        recorder.write()
        return

    calls = warehouse.fetch_open_calls()
    log.info("%d open call(s) in the warehouse, %d organisation(s)", len(calls), len(orgs))

    for org in orgs:
        if args.dry_run:
            matches = match_all(calls, org.get("profile") or {})
            print(f"# {org.get('name')} — {len(matches)} match(es)")
            for match in matches:
                print(f"{match.call_id}\t{match.tier}\t{match.match_reason}")
            continue
        run_org(warehouse, org, calls)

    recorder.write()


if __name__ == "__main__":
    main()
