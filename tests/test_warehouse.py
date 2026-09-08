"""Phase B regression tests — the warehouse write path.

Nothing here reaches Supabase. Every PostgREST exchange goes through the same
`fake_session` route table the two upstream sources use, so a test that wanted
to talk to a real project would have to add a live call, not just forget a mock.

The invariant these exist for is the one in `warehouse.py`'s docstring: **a
source that failed must never be swept.** It is the warehouse expression of the
`owned_sources` rule, it is the same defect class as `6712dfe`, and it is tested
from both ends — the caller iterating `succeeded`, and the callee refusing a
source that wrote nothing.
"""

import json

import pytest

import funding_radar
import mipe_watch
from provenance import Recorder
from warehouse import SQLSTATE_UNIQUE_VIOLATION, Warehouse, WarehouseError

BASE = "https://project.supabase.co"
CALLS = f"{BASE}/rest/v1/calls"
NOTIFICATIONS = f"{BASE}/rest/v1/org_notifications"

KEY = "eyJfakeservicerolekey"


def _ok(fake_response, body=b"", status=200, request_headers=None):
    """A PostgREST response. `url` must be the warehouse's own host or the
    redirect guard fires — which is the point of that guard, so it is not
    defaulted away here."""
    return fake_response(content=body, status=status, url=BASE, request_headers=request_headers)


def _record(call_id="adieuronest:1", source="adieuronest", **overrides):
    record = {
        "call_id": call_id,
        "source": source,
        "title": "Sprijin pentru pacienți",
        "programme": "PNRR",
        "deadline": "2026-12-01",
        "announced": False,
        "budget": "",
        "tags": [],
        "match_reason": "",
        "link": "https://adieuronest.ro/x",
        "first_seen": "2020-01-01",
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# 1 — the no-op contract
# ---------------------------------------------------------------------------

def test_unconfigured_warehouse_is_a_working_no_op():
    """Warehouse(None, None) must be safe to wire into any code path.

    Same contract as Recorder(None), and for the same reason: if enabling the
    warehouse can change what a run does, then every run without it configured
    is a different program from the one under test."""
    warehouse = Warehouse()

    assert warehouse.enabled is False
    assert warehouse.upsert_calls([_record()]) == 0
    assert warehouse.sweep_withdrawn("adieuronest", rows_written=5) == 0
    assert warehouse.sweep_expired() == 0
    assert warehouse.fetch_open_calls() == []
    assert warehouse.fetch_organizations() == []
    assert warehouse.claim_notification("org", "weekly_digest", "2026-W37", 3) is False


def test_a_url_without_a_key_is_still_disabled(fake_session):
    """Half a configuration is not a configuration. A URL with no service key
    would otherwise produce unauthenticated requests that PostgREST answers with
    401 on every single call of every single run."""
    assert Warehouse(BASE, None, session=fake_session({})).enabled is False


def test_a_non_https_warehouse_url_is_refused(fake_session):
    with pytest.raises(WarehouseError):
        Warehouse("http://project.supabase.co", KEY, session=fake_session({}))


# ---------------------------------------------------------------------------
# 2 — upsert shape
# ---------------------------------------------------------------------------

def test_upsert_sends_merge_duplicates_and_batches(fake_session, fake_response):
    """`resolution=merge-duplicates` is what makes this an upsert rather than a
    409 per already-known call, and the batch cap keeps a retry cheap."""
    session = fake_session({CALLS: _ok(fake_response)})
    warehouse = Warehouse(BASE, KEY, session=session)

    records = [_record(call_id=f"adieuronest:{i}") for i in range(1100)]
    assert warehouse.upsert_calls(records) == 1100

    assert len(session.calls) == 3          # 500 + 500 + 100
    assert [len(body) for body in session.bodies] == [500, 500, 100]
    for headers in session.request_headers:
        assert "resolution=merge-duplicates" in headers["Prefer"]


def test_upsert_omits_first_seen_so_it_survives_an_update(fake_session, fake_response):
    """first_seen is when a call was first surfaced, not when it was last
    re-fetched, and the UI sorts on it. PostgREST updates only the columns a
    request carries, so omitting it preserves the stored value on update and
    lets the column default apply on insert. Sending it would reset every row's
    sort key to today on every run."""
    session = fake_session({CALLS: _ok(fake_response)})
    Warehouse(BASE, KEY, session=session).upsert_calls([_record()])

    row = session.bodies[0][0]
    assert "first_seen" not in row
    # Every row in one request must carry identical keys, or the generated
    # ON CONFLICT clause differs per row.
    assert row["status"] == "open"
    assert row["withdrawn_at"] is None


def test_lang_is_stamped_per_source(fake_session, fake_response):
    """Matching terms are per-language. A row with the wrong `lang` is matched
    against the wrong vocabulary: 'screening' is CORE in the Romanian list and
    WIDE in the English one, so the mistake widens or narrows silently rather
    than erroring."""
    session = fake_session({CALLS: _ok(fake_response)})
    Warehouse(BASE, KEY, session=session).upsert_calls([
        _record(call_id="eu_sedia:A", source="eu_sedia"),
        _record(call_id="adieuronest:B", source="adieuronest"),
    ])

    langs = {row["call_id"]: row["lang"] for row in session.bodies[0]}
    assert langs == {"eu_sedia:A": "en", "adieuronest:B": "ro"}


# ---------------------------------------------------------------------------
# 3 + 5 — the sweep, and what it must refuse
# ---------------------------------------------------------------------------

def test_sweep_refuses_a_source_that_wrote_nothing(fake_session, fake_response):
    """The invariant, asserted at the layer that does the damage.

    A failed source returned no rows. Sweeping it marks its entire live
    inventory withdrawn while the run still exits 0 — the silent-green failure
    fixed for mipe_watch in 6712dfe. funding_radar.main() already guards this by
    iterating `succeeded`; this is the second, independent check, so a future
    caller cannot lose the guarantee by looping over the wrong set."""
    session = fake_session({CALLS: _ok(fake_response, b"[]")})
    warehouse = Warehouse(BASE, KEY, session=session)

    assert warehouse.sweep_withdrawn("adieuronest", rows_written=0) == 0
    assert session.calls == []   # not a PATCH with zero results — no request at all


def test_sweep_marks_absent_rows_withdrawn_and_does_not_delete(fake_session, fake_response):
    """Soft archival is the whole point: triage written against a call that
    later vanishes must survive, and a call that comes back keeps its
    first_seen."""
    session = fake_session({CALLS: _ok(fake_response, json.dumps([{"call_id": "x"}]).encode())})
    warehouse = Warehouse(BASE, KEY, session=session)

    assert warehouse.sweep_withdrawn("adieuronest", rows_written=42) == 1

    method, _, params = session.calls[0]
    assert method == "PATCH"                       # never DELETE
    assert params["source"] == "eq.adieuronest"
    assert params["status"] == "eq.open"
    body = session.bodies[0]
    assert body["status"] == "withdrawn"
    assert body["withdrawn_at"]


def test_sweep_filter_is_null_safe(fake_session, fake_response):
    """`neq` is NULL-unsafe in SQL. A row written before run stamping has
    last_seen_run_id NULL, and `last_seen_run_id=neq.<run>` would never match
    it — leaving it open forever instead of sweeping it."""
    session = fake_session({CALLS: _ok(fake_response, b"[]")})
    warehouse = Warehouse(BASE, KEY, session=session, run_id="11111111-1111-4111-8111-111111111111")
    warehouse.sweep_withdrawn("adieuronest", rows_written=1)

    assert session.calls[0][2]["or"] == (
        "(last_seen_run_id.neq.11111111-1111-4111-8111-111111111111,last_seen_run_id.is.null)"
    )


def test_sweep_ignores_a_source_the_warehouse_does_not_own(fake_session, fake_response):
    """A typo'd source name must not become a PATCH whose filter matches
    nothing — or, worse, one whose filter is dropped."""
    session = fake_session({CALLS: _ok(fake_response, b"[]")})
    warehouse = Warehouse(BASE, KEY, session=session)

    assert warehouse.sweep_withdrawn("adieuronst", rows_written=10) == 0
    assert session.calls == []


# ---------------------------------------------------------------------------
# 7 — expiry
# ---------------------------------------------------------------------------

def test_expiry_only_touches_open_rows(fake_session, fake_response):
    """A withdrawn call must not be relabelled 'expired'. The two statuses say
    different things — one vanished from its source, the other ran out of time —
    and a sweep that overwrote the first with the second would erase the
    distinction the withdrawal sweep exists to record."""
    session = fake_session({CALLS: _ok(fake_response, b"[]")})
    Warehouse(BASE, KEY, session=session).sweep_expired()

    _, _, params = session.calls[0]
    assert params["status"] == "eq.open"
    assert params["deadline"].startswith("lt.")


# ---------------------------------------------------------------------------
# 3 (caller side) — the loop in funding_radar.main()
# ---------------------------------------------------------------------------

def _stub_warehouse(monkeypatch):
    """Records what main() asked the warehouse to do, without an HTTP layer."""

    class Spy:
        enabled = True

        def __init__(self, *args, **kwargs):
            Spy.upserted = []
            Spy.swept = []
            Spy.expired = 0

        def upsert_calls(self, records):
            Spy.upserted.extend(records)
            return len(records)

        def sweep_withdrawn(self, source, rows_written):
            Spy.swept.append((source, rows_written))
            return 0

        def sweep_expired(self):
            Spy.expired += 1
            return 0

    monkeypatch.setattr(funding_radar, "Warehouse", Spy)
    return Spy


def test_a_failed_source_is_upserted_but_never_swept(monkeypatch, tmp_path, capsys):
    """The load-bearing test of Phase B.

    adieuronest succeeds, the EU source raises. The EU source must appear in
    NEITHER the sweep list nor owned_sources: its rows keep their previous
    last_seen_run_id, stay open, and are simply not refreshed. If the loop ever
    iterates `attempted` instead of `succeeded`, this fails."""
    spy = _stub_warehouse(monkeypatch)
    monkeypatch.chdir(tmp_path)

    call = funding_radar.FundingCall(
        call_id="adieuronest:1", source="adieuronest", title="Sprijin", programme="PNRR",
    )
    monkeypatch.setattr(funding_radar, "fetch_adieuronest_calls", lambda *a, **k: [call])

    def boom(*args, **kwargs):
        raise ValueError("EU portal down")

    monkeypatch.setattr(funding_radar, "fetch_eu_calls", boom)
    monkeypatch.setattr("sys.argv", ["funding_radar.py", "--no-state"])

    funding_radar.main()

    assert [c["call_id"] for c in spy.upserted] == ["adieuronest:1"]
    assert spy.swept == [("adieuronest", 1)]      # eu_sedia attempted, not swept
    assert "eu_sedia" not in dict(spy.swept)
    assert spy.expired == 1                       # expiry is not gated on a source


def test_mipe_watch_never_calls_the_sweep(monkeypatch, tmp_path, fake_session, fake_response):
    """mipe_watch reports only the pages that changed, so absence means 'no
    change', not 'gone'. A sweep here would withdraw every outstanding alert on
    the first quiet day — the warehouse expression of the same defect
    `replace=False` prevents in calls.json.

    This asserts against a Warehouse whose sweep raises rather than against a
    recorded call list, because the guarantee is that the call never happens on
    ANY path through this script — including a run where every page failed."""

    class NoSweep(Warehouse):
        upserted: list = []

        def upsert_calls(self, records):
            NoSweep.upserted.extend(records)
            return len(records)

        def sweep_withdrawn(self, source, rows_written):
            raise AssertionError("mipe_watch must never sweep — absence means 'no change'")

        def sweep_expired(self):
            raise AssertionError("mipe_watch does not own expiry either")

    NoSweep.upserted = []
    monkeypatch.setattr(mipe_watch, "Warehouse", NoSweep)
    monkeypatch.chdir(tmp_path)

    page = next(iter(mipe_watch.WATCHED_PAGES))
    url = mipe_watch.WATCHED_PAGES[page]
    session = fake_session({url: fake_response(text="conținut nou", url=url)})
    monkeypatch.setattr(mipe_watch, "create_resilient_session", lambda: session)
    # A stored baseline that differs, so this run reports a change and has rows
    # to write — the only path on which a sweep could plausibly be added.
    (tmp_path / mipe_watch.HASH_STORE_PATH).write_text(
        json.dumps({page: "0" * 64}), encoding="utf-8"
    )
    monkeypatch.setattr("sys.argv", ["mipe_watch.py"])

    mipe_watch.main()

    assert [row["call_id"] for row in NoSweep.upserted] == [f"mipe:{page}"]


# ---------------------------------------------------------------------------
# 8 — the service-role key must never reach a receipt
# ---------------------------------------------------------------------------

def test_service_role_key_never_lands_in_a_provenance_receipt(
    tmp_path, fake_session, fake_response
):
    """A receipt is an artifact people pass around, and this key bypasses RLS
    entirely — a leak is full read/write on every tenant's data. It rides in
    `apikey` and `Authorization`, neither of which is in SAFE_REQUEST_HEADERS.
    The headers are passed to the recorder and dropped by the allowlist there,
    so the filtering lives in one place and a new call site cannot forget it."""
    sent = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "User-Agent": "FundingRadar/1.0"}
    session = fake_session({CALLS: _ok(fake_response, b"", request_headers=sent)})

    recorder = Recorder(str(tmp_path))
    Warehouse(BASE, KEY, session=session, recorder=recorder).upsert_calls([_record()])
    recorder.write()

    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert KEY not in manifest
    assert "apikey" not in manifest
    assert "Authorization" not in manifest
    assert "FundingRadar/1.0" in manifest   # the allowlist kept what it should


def test_a_redirect_to_another_host_is_refused(fake_session, fake_response):
    """response.url is the URL after redirects. A warehouse that can redirect us
    elsewhere can collect the service-role key."""
    session = fake_session({
        CALLS: fake_response(content=b"", status=200, url="https://attacker.example/rest/v1/calls")
    })
    with pytest.raises(WarehouseError, match="redirected"):
        Warehouse(BASE, KEY, session=session).upsert_calls([_record()])


# ---------------------------------------------------------------------------
# 19 — the send claim
# ---------------------------------------------------------------------------

def test_a_duplicate_claim_is_detected_by_sqlstate_not_by_message_text(
    fake_session, fake_response
):
    """23505 is a Postgres constant. The prose of 'duplicate key value violates
    unique constraint' is PostgREST's to reword, and matching on it would fail
    open one release later — where failing open means a second email to a
    client's contact list."""
    body = json.dumps({"code": "23505", "message": "whatever PostgREST decides to say"}).encode()
    session = fake_session({NOTIFICATIONS: _ok(fake_response, body, status=409)})
    warehouse = Warehouse(BASE, KEY, session=session)

    assert warehouse.claim_notification("org", "weekly_digest", "2026-W37", 3) is False
    assert SQLSTATE_UNIQUE_VIOLATION == "23505"


def test_a_409_that_is_not_a_unique_violation_raises(fake_session, fake_response):
    """PostgREST maps foreign-key violations (23503) to 409 as well, so the
    status alone is ambiguous. An unknown org_id treated as 'already sent' would
    report a delivered digest for an email that was never sent and never will
    be — a silent, permanent hole in the notification path."""
    body = json.dumps({"code": "23503", "message": "insert violates foreign key"}).encode()
    session = fake_session({NOTIFICATIONS: _ok(fake_response, body, status=409)})
    warehouse = Warehouse(BASE, KEY, session=session)

    with pytest.raises(WarehouseError):
        warehouse.claim_notification("ghost-org", "weekly_digest", "2026-W37", 3)


def test_a_first_claim_succeeds(fake_session, fake_response):
    session = fake_session({NOTIFICATIONS: _ok(fake_response)})
    warehouse = Warehouse(BASE, KEY, session=session)
    assert warehouse.claim_notification("org", "weekly_digest", "2026-W37", 3) is True


# ---------------------------------------------------------------------------
# 24 — no tenant identity on the wire
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module", [funding_radar, mipe_watch])
def test_no_outbound_user_agent_names_a_tenant(module, monkeypatch):
    """A User-Agent is a contact address for whoever runs the crawler, and this
    crawler serves the whole warehouse. One org's office address on a request to
    the EU portal is the identity leak most visible from outside this repo."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert module._user_agent() == "FundingRadar/1.0"

    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/funding_radar")
    agent = module._user_agent()
    assert agent == "FundingRadar/1.0 (+https://github.com/owner/funding_radar)"
    assert "verticalfreedom" not in agent.lower()
    assert "office@" not in agent
