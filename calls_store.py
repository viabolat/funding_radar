#!/usr/bin/env python3
"""
Shared calls.json store — Vertical Freedom
==========================================

Both watchers write into ONE file, `calls.json`, which is the machine-readable
feed the staff dashboard reads. The GitHub Issues remain the notification path;
this file is the data behind the UI.

This is the only module both scripts import. They otherwise duplicate their
helpers on purpose (see CLAUDE.md), but the merge contract below cannot be
duplicated safely: two copies of it would drift, and drift here silently drops
records from a shared file.

Merge semantics, deliberately:
  - A script owns its own sources and touches only those entries. funding_radar
    owns "adieuronest" and "eu_sedia"; mipe_watch owns "mipe". A run of one must
    never erase the other's rows.
  - The two owners need different semantics. funding_radar REPLACES its rows:
    it re-fetches the whole feed every run, so what it did not return is gone.
    mipe_watch UPSERTS: it only ever reports the pages that changed on that run,
    so replacing would delete every outstanding alert on the first quiet day.
  - `first_seen` is preserved from the existing entry. It is the date a call was
    first surfaced, not the date it was last re-fetched, and the UI sorts on it.
  - A call that disappears from its source is dropped from the feed. It has
    already been reported as an Issue, and a dashboard listing dead calls is
    worse than one that forgets them.

Triage state (status, assignee, note, reminder, snooze) is NOT stored here. It
is user-authored and lives in triage.json, keyed by the same call_id.
"""

import json
from datetime import datetime
from pathlib import Path

CALLS_STORE_PATH = "calls.json"

# Bumped when the record shape changes so the frontend can refuse a feed it
# does not understand rather than rendering blanks.
FEED_VERSION = 1


def load_calls(path: str = CALLS_STORE_PATH) -> dict:
    """Returns {call_id: record}. A missing or unreadable feed is an empty one —
    a corrupt file must not stop a watcher from reporting new calls."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {record["call_id"]: record for record in data.get("calls", []) if record.get("call_id")}


def merge_calls(existing: dict, records: list[dict], owned_sources: set[str]) -> dict:
    """
    Replaces every entry belonging to `owned_sources` with `records`, leaving all
    other sources untouched, and carries `first_seen` over from any entry that
    was already known.
    """
    merged = {
        call_id: record
        for call_id, record in existing.items()
        if record.get("source") not in owned_sources
    }

    for record in records:
        call_id = record.get("call_id")
        if not call_id:
            continue
        previous = existing.get(call_id)
        if previous and previous.get("first_seen"):
            record = {**record, "first_seen": previous["first_seen"]}
        merged[call_id] = record

    return merged


def save_calls(calls: dict, path: str = CALLS_STORE_PATH) -> None:
    """Writes the feed sorted by call_id so a commit diff shows real changes
    rather than dictionary reordering."""
    payload = {
        "version": FEED_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "calls": [calls[key] for key in sorted(calls)],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_calls(existing: dict, records: list[dict]) -> dict:
    """Adds or updates the given records, leaving every other entry — including
    other rows of the same source — in place."""
    merged = dict(existing)

    for record in records:
        call_id = record.get("call_id")
        if not call_id:
            continue
        previous = existing.get(call_id)
        if previous and previous.get("first_seen"):
            record = {**record, "first_seen": previous["first_seen"]}
        merged[call_id] = record

    return merged


def write_source_calls(
    records: list[dict],
    owned_sources: set[str],
    path: str = CALLS_STORE_PATH,
    replace: bool = True,
) -> int:
    """
    Load, merge this run's records, save. Returns the feed size afterwards.

    `replace=True` (funding_radar) drops owned rows this run did not return.
    `replace=False` (mipe_watch) keeps them: that script reports only the pages
    that changed, so a quiet run passes an empty list and must not be read as
    "every outstanding alert is resolved".
    """
    existing = load_calls(path)
    if replace:
        merged = merge_calls(existing, records, owned_sources)
    else:
        merged = upsert_calls(existing, records)
    save_calls(merged, path)
    return len(merged)
