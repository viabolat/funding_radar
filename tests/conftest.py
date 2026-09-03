"""Shared fixtures. Puts the repo root on sys.path so the two top-level
scripts (funding_radar.py, mipe_watch.py) import as plain modules — they are
standalone scripts, not a package, so there is nothing to pip install."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    """Stands in for requests.Response for the fields these scripts touch."""

    def __init__(self, text="", json_data=None, status=200, content=None):
        self.text = text
        # fetch_adieuronest_calls decodes .content itself so it can strip the
        # feed's UTF-8 BOM, so a fixture must carry bytes as well as text.
        self.content = content if content is not None else text.encode("utf-8")
        self._json = json_data if json_data is not None else {}
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Maps a URL (or a (url, keyword) pair for SEDIA) to a FakeResponse or an
    exception to raise. Records every call for assertions.

    The SEDIA source uses POST — the API answers GET with 405 — so `post` is
    routed the same way and additionally records the multipart query part."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.posted_queries = []

    def _resolve(self, url, params):
        key = (url, params["text"]) if params and "text" in params else url
        result = self.routes.get(key)
        if result is None:
            raise AssertionError(f"unexpected request: {key}")
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        return self._resolve(url, params)

    def post(self, url, params=None, files=None, timeout=None):
        self.calls.append(("POST", url, params))
        if files and "query" in files:
            self.posted_queries.append(files["query"])
        return self._resolve(url, params)


@pytest.fixture
def fake_response():
    return FakeResponse


@pytest.fixture
def fake_session():
    return FakeSession


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def sedia_payload():
    """A real, unedited SEDIA response trimmed to five results: one topic in
    en/es/ro, and one expired EU4H topic in es/ro with no English translation."""
    import json

    return json.loads((FIXTURES / "sedia_response.json").read_text(encoding="utf-8"))


@pytest.fixture
def adieuronest_csv_bytes():
    """The real feed's header and four real rows, BOM included."""
    return (FIXTURES / "adieuronest_sample.csv").read_bytes()


@pytest.fixture
def capture_post(monkeypatch):
    """Captures requests.post on a given module so GitHub Issue creation can be
    asserted on without touching the network. Returns the recorded call list."""

    def _capture(module):
        recorded = []

        def fake_post(url, headers=None, json=None, timeout=None):
            recorded.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(json_data={"html_url": "https://github.com/o/r/issues/1"})

        monkeypatch.setattr(module.requests, "post", fake_post)
        return recorded

    return _capture
