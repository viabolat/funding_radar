"""Tests for calls_store.py — the shared calls.json feed.

Both watchers write this one file, so the merge rules are the part most likely
to lose data silently. Each test below pins one of those rules.
"""

import json

import calls_store as cs


def record(call_id, source, **extra):
    base = {
        "call_id": call_id,
        "source": source,
        "title": f"Call {call_id}",
        "programme": "",
        "deadline": None,
        "announced": False,
        "budget": "",
        "tags": [],
        "match_reason": "",
        "link": "",
        "first_seen": "2026-09-03",
    }
    base.update(extra)
    return base


def write(tmp_path, *records):
    path = str(tmp_path / "calls.json")
    cs.save_calls({r["call_id"]: r for r in records}, path)
    return path


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def test_round_trip_keys_by_call_id(tmp_path):
    path = write(tmp_path, record("a:1", "adieuronest"))

    assert list(cs.load_calls(path)) == ["a:1"]


def test_missing_feed_loads_as_empty(tmp_path):
    assert cs.load_calls(str(tmp_path / "nope.json")) == {}


def test_corrupt_feed_loads_as_empty_rather_than_raising(tmp_path):
    """A half-written file must not stop a watcher from reporting new calls."""
    path = tmp_path / "calls.json"
    path.write_text("{ this is not json", encoding="utf-8")

    assert cs.load_calls(str(path)) == {}


def test_feed_is_written_sorted_so_commit_diffs_are_meaningful(tmp_path):
    path = str(tmp_path / "calls.json")
    cs.save_calls(
        {"z:1": record("z:1", "eu_sedia"), "a:1": record("a:1", "adieuronest")}, path
    )

    payload = json.loads(open(path, encoding="utf-8").read())

    assert [c["call_id"] for c in payload["calls"]] == ["a:1", "z:1"]
    assert payload["version"] == cs.FEED_VERSION


# ---------------------------------------------------------------------------
# Replace semantics — funding_radar
# ---------------------------------------------------------------------------

def test_replacing_one_source_leaves_the_other_sources_alone(tmp_path):
    """A funding_radar run must never erase mipe_watch's alerts."""
    path = write(
        tmp_path,
        record("adieuronest:1", "adieuronest"),
        record("mipe:page", "mipe"),
    )

    cs.write_source_calls(
        [record("adieuronest:2", "adieuronest")],
        owned_sources={"adieuronest", "eu_sedia"},
        path=path,
    )

    assert set(cs.load_calls(path)) == {"adieuronest:2", "mipe:page"}


def test_a_call_that_vanished_from_its_source_is_dropped(tmp_path):
    path = write(tmp_path, record("adieuronest:gone", "adieuronest"))

    cs.write_source_calls([], owned_sources={"adieuronest"}, path=path)

    assert cs.load_calls(path) == {}


def test_first_seen_survives_a_refetch(tmp_path):
    """first_seen is when a call was first surfaced, not when it was last
    re-fetched — the dashboard sorts on it."""
    path = write(tmp_path, record("adieuronest:1", "adieuronest", first_seen="2026-01-01"))

    cs.write_source_calls(
        [record("adieuronest:1", "adieuronest", first_seen="2026-09-03", title="Retitled")],
        owned_sources={"adieuronest"},
        path=path,
    )

    stored = cs.load_calls(path)["adieuronest:1"]
    assert stored["first_seen"] == "2026-01-01"
    assert stored["title"] == "Retitled", "everything else should still refresh"


# ---------------------------------------------------------------------------
# Upsert semantics — mipe_watch
# ---------------------------------------------------------------------------

def test_a_quiet_mipe_run_does_not_delete_outstanding_alerts(tmp_path):
    """Regression: mipe_watch reports only the pages that changed, so a day with
    no changes passes an empty list. Under replace semantics that wiped every
    unresolved alert."""
    path = write(tmp_path, record("mipe:page", "mipe"))

    cs.write_source_calls([], owned_sources={"mipe"}, path=path, replace=False)

    assert set(cs.load_calls(path)) == {"mipe:page"}


def test_upsert_adds_a_new_alert_without_touching_the_old_one(tmp_path):
    path = write(tmp_path, record("mipe:page-a", "mipe"))

    cs.write_source_calls(
        [record("mipe:page-b", "mipe")],
        owned_sources={"mipe"},
        path=path,
        replace=False,
    )

    assert set(cs.load_calls(path)) == {"mipe:page-a", "mipe:page-b"}


def test_records_without_a_call_id_are_ignored(tmp_path):
    path = write(tmp_path, record("mipe:page", "mipe"))

    cs.write_source_calls(
        [{"source": "mipe", "title": "no id"}],
        owned_sources={"mipe"},
        path=path,
        replace=False,
    )

    assert set(cs.load_calls(path)) == {"mipe:page"}
