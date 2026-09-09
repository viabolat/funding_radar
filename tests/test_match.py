"""Phase C regression tests — the matcher, and the two things it must reproduce.

`match.py` is pure: no network, no clock, no database. So most of what is below
needs no fixture at all, which is the point of extracting it. The two tests that
do read fixtures are the ones that matter most, and they are gates rather than
unit tests:

  * `test_seed_profile_matches_the_migration_verbatim` — `funding_radar.SEED_PROFILE`
    and `0004_seed_vertical_freedom.sql` must hold the same terms in the same
    order. Two copies of a calibrated instrument that can disagree is exactly the
    drift the profile indirection exists to prevent.
  * `test_the_golden_call_set_is_reproduced` — the refactor's acceptance gate.
    The tags and reasons in `fixtures/golden_vf_matches.json` were captured from
    the pre-refactor code, so any divergence is a defect in the move rather than
    a new product decision.
"""

import json
import re
from pathlib import Path

import pytest

import funding_radar as fr
import match


FIXTURES = Path(__file__).parent / "fixtures"
MIGRATION = Path(__file__).parent.parent / "supabase" / "migrations" / "0004_seed_vertical_freedom.sql"


def call(**overrides):
    """A warehouse row, which is the only shape the matcher ever sees."""
    row = {
        "call_id": "adieuronest:1",
        "source": "adieuronest",
        "lang": "ro",
        "search_core": "",
        "search_wide": "",
        "eligible_as": [],
    }
    row.update(overrides)
    return row


def profile(**overrides):
    p = {"matching": {"ro": {"core": ["cancer"], "wide": ["sănătate"], "guards": ["animal"]}}}
    p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# 9 — purity
# ---------------------------------------------------------------------------

def test_match_all_is_pure():
    """Same inputs, same output, no I/O and no clock. If this ever needs a
    monkeypatched `datetime` to pass, something crossed back over the line."""
    calls = [call(search_core="program cancer"), call(call_id="adieuronest:2", search_core="x")]

    first = match.match_all(calls, profile())
    second = match.match_all(calls, profile())

    assert [m.call_id for m in first] == [m.call_id for m in second]
    assert first[0].matched_terms == second[0].matched_terms
    assert calls[0] == call(search_core="program cancer"), "input was mutated"


# ---------------------------------------------------------------------------
# 11 — the two-tier gate, transplanted
# ---------------------------------------------------------------------------

def test_core_matches_the_core_surface_only():
    """CORE reads `search_core`, which for adieuronest is the full record. A
    CORE term sitting only in the wide surface is not a core hit."""
    assert match.match_call(call(search_core="program cancer"), profile()) is not None
    assert match.match_call(call(search_wide="program cancer"), profile()) is None


def test_wide_matches_only_the_narrow_surface():
    """The calibration this whole split exists for: 'sănătate' in body prose
    pulled 32 junk rows, and in a title it is signal."""
    assert match.match_call(call(search_wide="fondul de sănătate"), profile()) is not None
    assert match.match_call(call(search_core="sănătate animală"), profile()) is None


def test_a_guard_vetoes_a_wide_hit():
    """"siguranta alimentara si sănătate animală" is a food-safety scope, not a
    health call."""
    row = call(search_wide="proiecte de sănătate animală")

    assert match.match_call(row, profile()) is None


def test_a_guard_never_vetoes_a_core_hit():
    """Load-bearing, and the one place the unified rule could have changed
    behaviour. `_eu_matches()` returned on a core hit BEFORE it looked at the
    guard list, so a guard that vetoed the whole match would drop calls that
    match today — and drop them for the strongest reason there is, their own
    name. The guard cancels the WIDE contribution only."""
    row = call(search_core="cancer la animale", search_wide="cancer la animale")

    result = match.match_call(row, profile())

    assert result is not None
    assert result.tier == "core"
    assert result.matched_terms == ("cancer",)


def test_the_tier_is_core_whenever_any_core_term_hits():
    row = call(search_core="program cancer", search_wide="fondul de sănătate")

    result = match.match_call(row, profile())

    assert result.tier == "core"
    assert result.matched_terms == ("cancer", "sănătate")


def test_no_match_produces_no_row():
    assert match.match_call(call(search_core="digitalizare industriala"), profile()) is None


# ---------------------------------------------------------------------------
# The language split — why `calls.lang` exists
# ---------------------------------------------------------------------------

def test_terms_are_read_from_the_calls_own_language():
    """'screening' is CORE in the Romanian list and WIDE in the English one.
    Matching a Romanian row against the English bucket silently widens or
    narrows rather than erroring, which is why lang is a column."""
    both = {"matching": {
        "ro": {"core": ["screening"], "wide": [], "guards": []},
        "en": {"core": [], "wide": ["screening"], "guards": []},
    }}

    ro = match.match_call(call(lang="ro", search_core="program screening"), both)
    en = match.match_call(call(lang="en", search_core="a screening programme"), both)

    assert ro.tier == "core"
    assert en is None, "in English, screening is WIDE and must not match a body surface"


def test_a_missing_lang_falls_back_to_the_sources_language():
    """A row written before the column existed, or by a caller that forgot it."""
    row = call(lang="", source="adieuronest", search_core="program cancer")

    assert match.match_call(row, profile()) is not None


def test_an_unknown_language_matches_nothing_rather_than_borrowing_a_bucket():
    row = call(lang="fr", search_core="program cancer")

    assert match.match_call(row, profile()) is None


# ---------------------------------------------------------------------------
# 31 + 32 — uncalibrated is a defined input, and differs from narrow
# ---------------------------------------------------------------------------

def test_an_uncalibrated_profile_matches_nothing():
    """It must not fall back to a default term list and must never borrow
    another organisation's. A new tenant seeing the seed organisation's inbox is
    the worst failure this system has."""
    assert match.match_all([call(search_core="program cancer")], {"mission": "…"}) == []
    assert match.is_calibrated({"mission": "…"}) is False


def test_missing_and_empty_are_different_states():
    """Missing means nobody has calibrated this org yet, and the dashboard says
    so. Empty means someone deliberately narrowed it to nothing, which is a
    legitimate profile that legitimately matches zero calls."""
    narrow = {"matching": {"ro": {"core": [], "wide": [], "guards": []}}}

    assert match.is_calibrated(narrow) is True
    assert match.match_all([call(search_core="program cancer")], narrow) == []


# ---------------------------------------------------------------------------
# Eligibility — facts on the call, the answer on the profile
# ---------------------------------------------------------------------------

def test_eligibility_intersects_the_two_vocabularies():
    p = profile(eligible_as=["ong", "sanatate"])

    assert match.match_call(call(search_core="cancer", eligible_as=["ong"]), p) is not None
    assert match.match_call(call(search_core="cancer", eligible_as=["companii"]), p) is None


def test_an_empty_call_vocabulary_is_unknown_not_closed():
    """The EU dataset publishes no applicant vocabulary at all. Reading empty as
    'open to nobody' would drop the entire EU feed for every organisation."""
    p = profile(eligible_as=["ong"])

    assert match.match_call(call(search_core="cancer", eligible_as=[]), p) is not None


def test_an_absent_profile_vocabulary_is_unfiltered_not_a_default():
    """Specifically NOT a default of {ong}: a new tenant must not inherit the
    seed organisation's eligibility."""
    row = call(search_core="cancer", eligible_as=["companii"])

    assert match.match_call(row, profile()) is not None


# ---------------------------------------------------------------------------
# profile_hash — a stamp, not a skip condition
# ---------------------------------------------------------------------------

def test_the_hash_covers_the_matching_terms_and_eligibility():
    base = profile(eligible_as=["ong"])
    widened = profile(eligible_as=["ong"])
    widened["matching"]["ro"]["core"] = ["cancer", "oncolog"]

    assert match.profile_hash(base) != match.profile_hash(widened)


def test_the_hash_ignores_fields_that_cannot_change_a_match():
    """Editing a mission statement or a notification address must not restamp
    every row, because the rows would be identical."""
    a = profile(mission="one", notification_email="a@example.org")
    b = profile(mission="two", notification_email="b@example.org")

    assert match.profile_hash(a) == match.profile_hash(b)


def test_the_hash_is_order_sensitive_because_match_reason_is():
    """Terms iterate in profile order and `match_reason` prints them in that
    order, so a reordered list produces different stored copy and must restamp."""
    a = {"matching": {"ro": {"core": ["cancer", "oncolog"], "wide": [], "guards": []}}}
    b = {"matching": {"ro": {"core": ["oncolog", "cancer"], "wide": [], "guards": []}}}

    assert match.profile_hash(a) != match.profile_hash(b)


# ---------------------------------------------------------------------------
# The Romanian copy
# ---------------------------------------------------------------------------

def test_match_reason_is_romanian_and_uses_guillemets():
    assert match.match_reason(["cancer"]) == "Cuvânt cheie potrivit „cancer”."
    assert match.match_reason(["cancer", "oncolog"]) == (
        "Cuvinte cheie potrivite „cancer”, „oncolog”."
    )


def test_terms_keep_profile_order_in_the_reason():
    """Not sorted. The order is the profile's, and today's digest says so."""
    p = {"matching": {"ro": {"core": ["cancer", "paliativ", "oncolog"], "wide": [], "guards": []}}}
    row = call(search_core="oncolog paliativ cancer")

    assert match.match_call(row, p).matched_terms == ("cancer", "paliativ", "oncolog")


# ---------------------------------------------------------------------------
# No diacritic folding in the matcher
# ---------------------------------------------------------------------------

def test_the_matcher_does_not_fold_diacritics():
    """Both spellings are listed in the profile instead. Folding here would both
    widen matches beyond what was calibrated and report a term the source text
    does not contain — `fold` exists for --calibrate and dedup, not for this."""
    p = {"matching": {"ro": {"core": ["sănătate mintal"], "wide": [], "guards": []}}}

    assert match.match_call(call(search_core="sanatate mintala"), p) is None
    assert match.match_call(call(search_core="sănătate mintală"), p) is not None


# ---------------------------------------------------------------------------
# THE GATES
# ---------------------------------------------------------------------------

def _migration_terms():
    """Pulls the jsonb_build_array blocks out of the seed migration.

    Deliberately a dumb text parse rather than a live database read: the point
    is that the file checked into the repo agrees with the Python constant, and
    a test that needed Postgres to answer that could not run in this suite."""
    sql = MIGRATION.read_text(encoding="utf-8")
    matching = sql[sql.index("'matching', jsonb_build_object"):]

    # reason: each language block is bounded at the start of the next one. A
    # block running to end-of-file lets a bucket missing from `ro` silently
    # resolve to `en`'s list — which would make this gate compare the wrong two
    # things, in a test whose entire job is noticing that they differ.
    starts = {lang: matching.index(f"'{lang}', jsonb_build_object") for lang in ("ro", "en")}
    bounds = {"ro": starts["en"], "en": len(matching)}
    assert starts["ro"] < starts["en"], "language blocks reordered — bounds below are wrong"

    out = {}
    for lang in ("ro", "en"):
        block = matching[starts[lang]:bounds[lang]]
        out[lang] = {}
        for bucket in ("core", "wide", "guards"):
            if f"'{bucket}', jsonb_build_array" not in block:
                continue
            start = block.index(f"'{bucket}', jsonb_build_array")
            depth, i = 0, block.index("(", start)
            for i in range(i, len(block)):
                depth += block[i] == "("
                depth -= block[i] == ")"
                if depth == 0:
                    break
            body = block[start:i]
            # Strip -- comments before reading the quoted terms, or a term named
            # inside a comment would be counted as a list entry.
            body = re.sub(r"--[^\n]*", "", body)
            out[lang][bucket] = re.findall(r"'((?:[^']|'')*)'", body)[1:]
    return out


def test_seed_profile_matches_the_migration_verbatim():
    """The drift guard for the one thing that exists twice.

    `SEED_PROFILE` is the bootstrap for a machine with no database; the
    migration is what the database gets. They are the same calibrated
    instrument, and the migration's own header says the terms are copied
    verbatim and must not be re-ordered — so this compares them in order, not as
    sets. A set comparison would pass on a reordering, and reordering changes
    what `match_reason` prints."""
    from_sql = _migration_terms()
    from_py = fr.SEED_PROFILE["matching"]

    assert set(from_sql) == set(from_py) == {"ro", "en"}
    for lang in ("ro", "en"):
        for bucket in ("core", "wide", "guards"):
            assert from_sql[lang].get(bucket, []) == from_py[lang].get(bucket, []), (
                f"{lang}.{bucket} differs between SEED_PROFILE and 0004"
            )


def test_the_seed_profile_carries_no_tenant_identity():
    """SEED_PROFILE is a bootstrap term list, not a copy of an organisation.
    The mission text, the contact address and the org name belong to the
    migration's row alone."""
    blob = json.dumps(fr.SEED_PROFILE, ensure_ascii=False).lower()

    assert "verticalfreedom" not in blob
    assert "office@" not in blob
    assert "mission" not in fr.SEED_PROFILE
    assert "notification_email" not in fr.SEED_PROFILE


def test_the_golden_call_set_is_reproduced(eu_reference_path, adieuronest_csv_bytes,
                                           fake_session, fake_response):
    """Phase C's acceptance gate.

    `golden_vf_matches.json` was captured from the pre-refactor code, before the
    keyword gate left the fetchers. Matching the seed profile against what the
    fetchers now collect must reproduce it exactly — the same call_ids, the same
    tags, and the same Romanian `match_reason` including term order. A
    divergence here is a defect in the move, not a new product decision, and the
    plan says that is where this stops."""
    golden = json.loads((FIXTURES / "golden_vf_matches.json").read_text(encoding="utf-8"))

    session = fake_session(
        {fr.CONFIG["adieuronest_csv_url"]: fake_response(content=adieuronest_csv_bytes)}
    )
    collected = fr.fetch_adieuronest_calls(session)
    collected += fr.fetch_eu_calls(None, dataset_path=eu_reference_path)

    actual = {c.call_id: c for c in fr.apply_profile(collected, fr.SEED_PROFILE)}
    expected = {row["call_id"]: row for rows in golden.values() for row in rows}

    assert sorted(actual) == sorted(expected)
    for call_id, want in expected.items():
        assert actual[call_id].tags == want["tags"], call_id
        assert actual[call_id].match_reason == want["match_reason"], call_id
