"""Shared fixtures. Puts the repo root on sys.path so the two top-level
scripts (funding_radar.py, mipe_watch.py) import as plain modules — they are
standalone scripts, not a package, so there is nothing to pip install."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class FakeRequest:
    """The `.request` attribute — provenance reads the sent headers off it."""

    def __init__(self, headers=None):
        self.headers = dict(headers or {})


class FakeResponse:
    """Stands in for requests.Response for the fields these scripts touch.

    `url` defaults to an allowed host because assert_trusted() inspects the URL
    AFTER redirects and refuses anything else. A test that wants to prove that
    guard passes an off-allowlist `url` explicitly."""

    def __init__(
        self,
        text="",
        json_data=None,
        status=200,
        content=None,
        url="https://ec.europa.eu/fixture",
        headers=None,
        request_headers=None,
        chunks=None,
    ):
        self.text = text
        # Every caller reads .content, not .json() or .text: the CSV parser
        # decodes it itself to strip the feed's UTF-8 BOM, and the EU enrichment
        # hashes it before parsing so the receipt covers the bytes that were
        # actually parsed. A JSON route therefore has to carry real bytes too.
        if content is not None:
            self.content = content
        elif json_data is not None:
            import json as _json

            self.content = _json.dumps(json_data).encode("utf-8")
        else:
            self.content = text.encode("utf-8")
        self._json = json_data if json_data is not None else {}
        self.status_code = status
        self.url = url
        self.headers = dict(headers or {})
        self.request = FakeRequest(request_headers)
        # download_to_file streams; a route can dictate the chunk boundaries so
        # a test can drive the size ceiling without holding a big body.
        self._chunks = chunks

    def json(self):
        return self._json

    def iter_content(self, chunk_size=1):
        if self._chunks is not None:
            yield from self._chunks
            return
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]

    # `with session.get(..., stream=True) as response:` in download_to_file.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

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
        self.request_headers = []
        self.bodies = []

    def _resolve(self, url, params):
        key = (url, params["text"]) if params and "text" in params else url
        result = self.routes.get(key)
        if result is None:
            raise AssertionError(f"unexpected request: {key}")
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, params=None, timeout=None, headers=None, stream=False):
        self.calls.append(("GET", url, params))
        self.request_headers.append(dict(headers or {}))
        return self._resolve(url, params)

    def post(self, url, params=None, files=None, timeout=None):
        self.calls.append(("POST", url, params))
        if files and "query" in files:
            self.posted_queries.append(files["query"])
        return self._resolve(url, params)

    def request(self, method, url, params=None, data=None, timeout=None, headers=None):
        """`warehouse.py` calls session.request() because it needs PATCH as well
        as GET and POST, and PostgREST takes a JSON body rather than multipart.

        Routing is by URL only — a PostgREST route is `.../rest/v1/calls` with
        the filters in `params` — so a test that wants to distinguish a sweep
        from an upsert asserts on `calls`/`bodies` rather than adding a route
        per query string. The decoded request body is recorded because every
        warehouse assertion worth making (merge-duplicates batching, the
        first_seen omission, withdrawn_at being set) is about what was sent."""
        self.calls.append((method, url, params))
        self.request_headers.append(dict(headers or {}))
        self.bodies.append(json.loads(data.decode("utf-8")) if data else None)
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
def eu_reference_path():
    """Seven records cut unedited from the live 129,759,798-byte reference
    dataset (sha256 3f3440d0…, Last-Modified 2026-09-08): an open cancer grant,
    a forthcoming one, a WIDE-tier match, a closed grant, a multi-cutoff grant,
    a context-guarded biodiversity/human-health grant, and a procurement tender.
    Re-cut it from a live body rather than hand-editing if the shape changes."""
    return FIXTURES / "eu_reference_sample.json"


@pytest.fixture
def eu_reference_bytes(eu_reference_path):
    return eu_reference_path.read_bytes()


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
