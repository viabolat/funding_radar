"""Tests for mipe_watch.py.

The watcher's whole job is: quiet when nothing changed, one Issue when
something did, and never lose a page's baseline. Those three properties are
what these tests pin.
"""

import json

import requests

import calls_store as cs
import mipe_watch as mw


# ---------------------------------------------------------------------------
# Hashing — must track visible text only
# ---------------------------------------------------------------------------

def test_markup_and_whitespace_changes_do_not_move_the_hash():
    """The CMS reflowing its HTML must not fire a false alarm."""
    a = "<html><body><h1>Calendar</h1><p>Apel   1</p></body></html>"
    b = "<html>\n  <body>\n    <h1>Calendar</h1>\n\n    <div><p>Apel 1</p></div>\n  </body>\n</html>"

    assert mw.normalized_text_hash(a) == mw.normalized_text_hash(b)


def test_visible_text_change_moves_the_hash():
    a = "<p>Apel 1</p>"
    b = "<p>Apel 2</p>"

    assert mw.normalized_text_hash(a) != mw.normalized_text_hash(b)


def test_hash_is_stable_across_calls():
    html = "<p>Apel 1</p>"
    assert mw.normalized_text_hash(html) == mw.normalized_text_hash(html)


# ---------------------------------------------------------------------------
# Hash store
# ---------------------------------------------------------------------------

def test_hash_store_round_trip(tmp_path):
    path = tmp_path / "h.json"
    mw.save_hashes(str(path), {"a": "1"})

    assert json.loads(path.read_text()) == {"a": "1"}
    assert mw.load_hashes(str(path)) == {"a": "1"}


def test_load_hashes_on_missing_file_returns_empty_dict(tmp_path):
    assert mw.load_hashes(str(tmp_path / "nope.json")) == {}


# ---------------------------------------------------------------------------
# main() — change detection and baseline handling
# ---------------------------------------------------------------------------

def run_main(monkeypatch, tmp_path, pages, routes, previous=None, create_issue=False):
    """Drives main() against a fake session in an isolated cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mw, "HASH_STORE_PATH", "h.json")
    monkeypatch.setattr(mw, "WATCHED_PAGES", pages)
    argv = ["mipe_watch.py"] + (["--create-issue"] if create_issue else [])
    monkeypatch.setattr("sys.argv", argv)

    if previous is not None:
        mw.save_hashes("h.json", previous)

    class FakeSession:
        def get(self, url, timeout=None):
            result = routes[url]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(mw, "create_resilient_session", lambda: FakeSession())
    mw.main()
    return mw.load_hashes("h.json")


def test_first_check_records_a_baseline_without_alerting(
    monkeypatch, tmp_path, fake_response, capture_post
):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(mw)

    stored = run_main(
        monkeypatch,
        tmp_path,
        {"cal": "http://cal"},
        {"http://cal": fake_response(text="<p>v1</p>")},
        create_issue=True,
    )

    assert stored["cal"] == mw.normalized_text_hash("<p>v1</p>")
    assert posted == [], "a first sighting has nothing to compare against"


def test_unchanged_page_opens_no_issue(
    monkeypatch, tmp_path, fake_response, capture_post
):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(mw)
    html = "<p>v1</p>"

    run_main(
        monkeypatch,
        tmp_path,
        {"cal": "http://cal"},
        {"http://cal": fake_response(text=html)},
        previous={"cal": mw.normalized_text_hash(html)},
        create_issue=True,
    )

    assert posted == []


def test_changed_page_opens_one_issue_naming_the_page_and_url(
    monkeypatch, tmp_path, fake_response, capture_post
):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(mw)

    stored = run_main(
        monkeypatch,
        tmp_path,
        {"cal": "http://cal"},
        {"http://cal": fake_response(text="<p>v2</p>")},
        previous={"cal": mw.normalized_text_hash("<p>v1</p>")},
        create_issue=True,
    )

    assert len(posted) == 1
    body = posted[0]["json"]["body"]
    assert "**cal**: http://cal" in body
    assert posted[0]["json"]["labels"] == mw.GITHUB_ISSUE_LABELS
    assert stored["cal"] == mw.normalized_text_hash("<p>v2</p>")


def test_failed_fetch_keeps_the_previous_baseline(
    monkeypatch, tmp_path, fake_response, capture_post
):
    """Regression: main() used to start from an empty dict, so a page that
    failed to fetch had its stored hash erased and was treated as a first check
    next run — silently skipping one change-detection cycle."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(mw)
    old_hash = mw.normalized_text_hash("<p>v1</p>")

    stored = run_main(
        monkeypatch,
        tmp_path,
        {"cal": "http://cal"},
        {"http://cal": requests.RequestException("boom")},
        previous={"cal": old_hash},
        create_issue=True,
    )

    assert stored == {"cal": old_hash}
    assert posted == [], "a fetch failure is not a content change"


def test_page_removed_from_the_watch_list_is_pruned(
    monkeypatch, tmp_path, fake_response
):
    stored = run_main(
        monkeypatch,
        tmp_path,
        {"cal": "http://cal"},
        {"http://cal": fake_response(text="<p>v1</p>")},
        previous={"cal": "old", "retired": "stale"},
    )

    assert "retired" not in stored


def test_one_failing_page_does_not_block_detection_on_another(
    monkeypatch, tmp_path, fake_response, capture_post
):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(mw)
    a_hash = mw.normalized_text_hash("<p>a1</p>")

    stored = run_main(
        monkeypatch,
        tmp_path,
        {"a": "http://a", "b": "http://b"},
        {
            "http://a": requests.RequestException("boom"),
            "http://b": fake_response(text="<p>b2</p>"),
        },
        previous={"a": a_hash, "b": mw.normalized_text_hash("<p>b1</p>")},
        create_issue=True,
    )

    assert stored["a"] == a_hash
    assert stored["b"] == mw.normalized_text_hash("<p>b2</p>")
    assert len(posted) == 1
    assert "**b**" in posted[0]["json"]["body"]
    assert "**a**" not in posted[0]["json"]["body"]


def test_without_create_issue_flag_nothing_is_posted(
    monkeypatch, tmp_path, fake_response, capture_post
):
    """Local runs must never touch the GitHub API, even with a token in env."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(mw)

    run_main(
        monkeypatch,
        tmp_path,
        {"cal": "http://cal"},
        {"http://cal": fake_response(text="<p>v2</p>")},
        previous={"cal": mw.normalized_text_hash("<p>v1</p>")},
        create_issue=False,
    )

    assert posted == []


# ---------------------------------------------------------------------------
# calls.json feed
# ---------------------------------------------------------------------------

def test_a_changed_page_becomes_a_feed_row(monkeypatch, tmp_path, fake_response):
    run_main(
        monkeypatch,
        tmp_path,
        {"calendar_apeluri_general": "http://cal"},
        {"http://cal": fake_response(text="<p>v2</p>")},
        previous={"calendar_apeluri_general": mw.normalized_text_hash("<p>v1</p>")},
    )

    rows = cs.load_calls("calls.json")

    assert list(rows) == ["mipe:calendar_apeluri_general"]
    row = rows["mipe:calendar_apeluri_general"]
    assert row["source"] == "mipe"
    assert row["title"] == "Calendar apeluri de proiecte — calendar modificat"
    assert row["deadline"] is None, "a change-alert has no deadline"
    assert row["match_reason"] == "text modificat"
    assert row["link"] == "http://cal"


def test_an_unchanged_page_writes_no_feed_row(monkeypatch, tmp_path, fake_response):
    html = "<p>v1</p>"
    run_main(
        monkeypatch,
        tmp_path,
        {"calendar_apeluri_general": "http://cal"},
        {"http://cal": fake_response(text=html)},
        previous={"calendar_apeluri_general": mw.normalized_text_hash(html)},
    )

    assert cs.load_calls("calls.json") == {}
