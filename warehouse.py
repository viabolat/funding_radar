#!/usr/bin/env python3
"""
Supabase warehouse client.
==========================

The third module both watchers import, and the third deliberate exception to
this repo's "duplicate the helpers" rule. The reason is the same one that earned
`calls_store.py` its exception, one storage layer along: both watchers write the
same `calls` table, and two copies of the upsert-plus-sweep contract would
drift. Drift in `calls_store.merge_calls` silently dropped records; drift here
silently marks live calls as withdrawn, which is the same failure wearing a
different hat.

`Warehouse(None, None)` is a fully working no-op — every method is safe to call,
nothing is written, and `enabled` is False. That is the `Recorder(None)`
contract, and it exists for the same reason: wiring this into a code path must
not be able to change what that path does.

Why PostgREST directly instead of supabase-py
---------------------------------------------
Everything the watchers need is a REST call, and this repo already knows how to
make one resiliently — `create_resilient_session()` handles the retry, backoff
and Retry-After behaviour a hosted database needs, and a dependency tree would
add nothing to it. The React app does take `@supabase/supabase-js`, because
hand-rolling GoTrue's auth flows would be a bad trade. This is not that.

The write model
---------------
  * `upsert_calls`   — insert or merge, keyed on call_id. Stamps this run's id.
  * `sweep_withdrawn`— everything from ONE source that this run did not return
                       becomes 'withdrawn'. Soft: the row stays, `withdrawn_at`
                       is set, and triage written against it survives.
  * `sweep_expired`  — an open call whose deadline has passed becomes 'expired'.

**A source that failed must never be swept.** This is the exact invariant
`merge_calls`'s `owned_sources` protects in the calls.json world: a failed
source returned no rows, so sweeping it would mark its entire live inventory
withdrawn while the run still exits 0 — the silent-green failure fixed for
mipe_watch in 6712dfe. It is enforced twice, on purpose. `funding_radar.main()`
tracks per-source success and iterates `succeeded`, never `attempted`; and
`sweep_withdrawn` takes the number of rows that source wrote this run and
refuses when it is zero. The second check is not redundant — it puts the
invariant at the layer that does the damage, where a future caller cannot lose
it by looping over the wrong set. `mipe_watch.py` never sweeps at all: it
reports only the pages that changed, so absence there means "no change", not
"gone".

Never let the service-role key reach a receipt. It bypasses RLS entirely, so a
leak is a full read/write compromise of every tenant's data. It rides in the
`apikey` and `Authorization` headers, neither of which is in
`provenance.SAFE_REQUEST_HEADERS` — which is why that list is an allowlist.
"""

import json
import logging
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from provenance import sha256_of

log = logging.getLogger("warehouse")

# PostgREST accepts a large body, but a single 2,100-row insert is one failure
# away from being retried in full. Batches keep a retry cheap and keep the
# statement inside Postgres' parameter limits.
UPSERT_BATCH = 500

# Read paging. PostgREST caps a response server-side anyway; asking explicitly
# means the client knows whether it saw everything.
PAGE_SIZE = 1000

WAREHOUSE_SOURCES = ("eu_sedia", "adieuronest", "mipe_calendar", "mipe")

# The language each source publishes in. Matching terms are per-language
# (organizations.profile.matching.{ro,en}), so a row with the wrong `lang` is
# matched against the wrong vocabulary and silently under- or over-matches.
# A fetcher may stamp `lang` on the record itself; this is the fallback, and it
# is a property of the source rather than of any one record.
SOURCE_LANG = {
    "eu_sedia": "en",
    "adieuronest": "ro",
    "mipe_calendar": "ro",
    "mipe": "ro",
}

# Postgres SQLSTATE for a unique-constraint violation. Defined by Postgres, so
# it survives any rewording of PostgREST's error messages. Used to tell "this
# email was already sent" from every other reason an insert can fail — a
# distinction the plan calls unrecoverable to get wrong, and therefore not one
# to make by matching on prose.
SQLSTATE_UNIQUE_VIOLATION = "23505"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WarehouseError(RuntimeError):
    """A write or read against the warehouse failed.

    Raised rather than swallowed: a run that could not record what it scraped
    has nothing to say, and must not exit green.

    Carries the HTTP status and PostgREST's own error body so callers can
    branch on a machine-readable code instead of matching on message text.
    `code` is the Postgres SQLSTATE (e.g. '23505' for a unique violation) — a
    constant defined by Postgres itself, not a phrasing choice PostgREST could
    reword in a future release.
    """

    def __init__(self, message: str, status: int | None = None, body: bytes = b""):
        super().__init__(message)
        self.status = status
        self.code = None
        self.detail = ""
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            if isinstance(parsed, dict):
                self.code = parsed.get("code")
                self.detail = parsed.get("message") or ""


class Warehouse:
    """
    PostgREST client for the `calls` warehouse and the per-org tables.

    Constructed with no URL or no key it is disabled, and every method returns
    the same shape it would on an empty result. Nothing else in the codebase
    needs to guard on whether Supabase is configured.
    """

    def __init__(
        self,
        url: str | None = None,
        service_key: str | None = None,
        session=None,
        run_id: str | None = None,
        recorder=None,
        user_agent: str = "FundingRadar/1.0",
        timeout: tuple[int, int] = (10, 60),
        dry_run: bool = False,
    ):
        self.base = url.rstrip("/") if url else None
        self.key = service_key or None
        self.session = session
        self.recorder = recorder
        self.user_agent = user_agent
        self.timeout = timeout
        self.dry_run = dry_run
        # One id per process run. `sweep_withdrawn` is "everything this run did
        # not touch", which is a single statement only because every row this
        # run wrote carries the same stamp.
        self.run_id = run_id or str(uuid.uuid4())
        self.writes: list[dict] = []   # what a dry run would have sent

        if self.base and self.session is None:
            raise WarehouseError("a configured Warehouse needs an HTTP session")
        if self.base:
            parsed = urlparse(self.base)
            if parsed.scheme != "https" or not parsed.netloc:
                raise WarehouseError(f"refusing a non-HTTPS warehouse URL: {self.base}")
            self.host = parsed.netloc

    @property
    def enabled(self) -> bool:
        return bool(self.base and self.key)

    # -- plumbing -----------------------------------------------------------

    def _headers(self, prefer: str = "") -> dict:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _record(self, method: str, url: str, response, body: bytes) -> None:
        if self.recorder is None:
            return
        self.recorder.http(
            source="warehouse",
            method=method,
            url=url,
            status=response.status_code,
            response_bytes=len(body),
            sha256=sha256_of(body),
            # provenance filters these through SAFE_REQUEST_HEADERS, which does
            # not include apikey or Authorization. Passing them here and letting
            # the allowlist drop them is deliberate: the filtering lives in one
            # place, so a new call site cannot forget it.
            request_headers=dict(response.request.headers) if getattr(response, "request", None) else None,
            response_headers=dict(getattr(response, "headers", {}) or {}),
            sample=self.recorder.body_for_evidence(body),
        )

    def _request(self, method: str, path: str, *, params=None, payload=None, prefer=""):
        url = f"{self.base}/rest/v1/{path}"
        kwargs = {"timeout": self.timeout, "headers": self._headers(prefer)}
        if params:
            kwargs["params"] = params
        if payload is not None:
            kwargs["data"] = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        response = self.session.request(method, url, **kwargs)
        body = response.content or b""
        self._record(method, url, response, body)

        # A redirect to another host would mean sending the service-role key
        # somewhere it does not belong. response.url is the URL after redirects.
        final_host = urlparse(getattr(response, "url", url) or url).netloc
        if final_host and final_host != self.host:
            raise WarehouseError(f"warehouse request redirected to {final_host}")

        if response.status_code >= 400:
            raise WarehouseError(
                f"{method} {path} -> {response.status_code}: {body[:400].decode('utf-8', 'replace')}",
                status=response.status_code,
                body=body,
            )
        return response, body

    @staticmethod
    def _decode(body: bytes) -> list[dict]:
        if not body:
            return []
        parsed = json.loads(body.decode("utf-8"))
        return parsed if isinstance(parsed, list) else [parsed]

    # -- writing calls ------------------------------------------------------

    def upsert_calls(self, records: list[dict]) -> int:
        """
        Insert or merge warehouse rows, stamped with this run's id.

        `first_seen` is deliberately NOT in the payload. PostgREST updates only
        the columns a request actually carries, so omitting it leaves an
        existing row's value alone and lets the column default apply on insert.
        That is the same rule calls_store applies on both merge paths:
        first_seen is when a call was first surfaced, not when it was last
        re-fetched, and the UI sorts on it.

        `status` and `withdrawn_at` ARE in the payload, so a call that comes
        back after vanishing is reopened rather than left archived.
        """
        if not self.enabled or not records:
            return 0

        rows = [self._row(record) for record in records]
        if self.dry_run:
            self.writes.extend(rows)
            log.info("dry run: would upsert %d call(s)", len(rows))
            return len(rows)

        written = 0
        for start in range(0, len(rows), UPSERT_BATCH):
            batch = rows[start:start + UPSERT_BATCH]
            self._request(
                "POST",
                "calls",
                payload=batch,
                prefer="resolution=merge-duplicates,return=minimal",
            )
            written += len(batch)
        log.info("warehouse: upserted %d call(s)", written)
        return written

    def _row(self, record: dict) -> dict:
        """Project a FundingCall record onto the warehouse columns.

        Every row in one PostgREST request must carry the same keys, or the
        generated ON CONFLICT clause differs per row. Building each row from a
        fixed key list rather than from the record's own keys is what guarantees
        that.
        """
        return {
            "call_id": record["call_id"],
            "source": record["source"],
            "title": record.get("title", ""),
            "programme": record.get("programme", "") or "",
            "deadline": record.get("deadline"),
            "announced": bool(record.get("announced", False)),
            "budget": record.get("budget", "") or "",
            "tags": record.get("tags") or [],
            "match_reason": record.get("match_reason", "") or "",
            "link": record.get("link", "") or "",
            "raw": record.get("raw") or {},
            "lang": record.get("lang") or SOURCE_LANG.get(record["source"], "ro"),
            "search_core": record.get("search_core", "") or "",
            "search_wide": record.get("search_wide", "") or "",
            "status": "open",
            "withdrawn_at": None,
            "last_seen_at": _utc_now(),
            "last_seen_run_id": self.run_id,
            "updated_at": _utc_now(),
        }

    def sweep_withdrawn(self, source: str, rows_written: int) -> int:
        """
        Mark every open row of ONE source that this run did not return.

        Soft by design: the row stays, so a call that is withdrawn and later
        reappears keeps its first_seen, its history and any triage attached to
        it. `merge_calls` hard-deletes in the calls.json world; the warehouse
        keeps the property that motivated that (dead calls do not clutter a
        dashboard) by filtering on status at read time instead.

        `rows_written` is how many rows this source contributed to the warehouse
        THIS RUN, and a sweep with zero is refused. That check is not redundant
        with `funding_radar.main()` only sweeping sources in `succeeded`: it is
        the same invariant asserted at the layer that does the damage, so a
        future caller cannot reintroduce the failure by looping over the wrong
        set. A failed source contributes zero rows, and sweeping it would
        withdraw its entire live inventory while the run still exits 0 — the
        silent-green failure fixed for mipe_watch in 6712dfe.

        A source that genuinely has nothing live is indistinguishable from a
        failed one here, and is refused too. That direction is deliberate: the
        cost is stale rows staying open one run longer, against wrongly
        archiving every call the organisation is tracking.
        """
        if not self.enabled or source not in WAREHOUSE_SOURCES:
            return 0
        if rows_written <= 0:
            log.warning(
                "refusing to sweep %s: it wrote no rows this run, so 'absent' "
                "cannot be told apart from 'failed'",
                source,
            )
            return 0
        if self.dry_run:
            log.info("dry run: would sweep withdrawn rows for %s", source)
            return 0

        _, body = self._request(
            "PATCH",
            "calls",
            params={
                "source": f"eq.{source}",
                "status": "eq.open",
                # A row that predates run stamping has last_seen_run_id NULL,
                # and `neq` is NULL-unsafe in SQL — it would leave those rows
                # untouched forever rather than sweeping them.
                "or": f"(last_seen_run_id.neq.{self.run_id},last_seen_run_id.is.null)",
            },
            payload={"status": "withdrawn", "withdrawn_at": _utc_now(), "updated_at": _utc_now()},
            prefer="return=representation",
        )
        swept = len(self._decode(body))
        if swept:
            log.info("warehouse: %d %s call(s) withdrawn (absent this run)", swept, source)
        return swept

    def sweep_expired(self) -> int:
        """Open calls whose deadline has passed become 'expired'.

        Deliberately scoped to status='open': a withdrawn call stays withdrawn.
        Withdrawal says the source stopped listing it, expiry says the date
        passed, and overwriting the first with the second would lose why the
        call left.
        """
        if not self.enabled:
            return 0
        if self.dry_run:
            log.info("dry run: would sweep expired rows")
            return 0

        today = date.today().isoformat()
        _, body = self._request(
            "PATCH",
            "calls",
            params={"status": "eq.open", "deadline": f"lt.{today}"},
            payload={"status": "expired", "updated_at": _utc_now()},
            prefer="return=representation",
        )
        expired = len(self._decode(body))
        if expired:
            log.info("warehouse: %d call(s) expired", expired)
        return expired

    # -- reading ------------------------------------------------------------

    def _paged(self, path: str, params: dict) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            page_params = dict(params, limit=PAGE_SIZE, offset=offset)
            _, body = self._request("GET", path, params=page_params)
            page = self._decode(body)
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            offset += PAGE_SIZE

    def fetch_open_calls(self) -> list[dict]:
        if not self.enabled:
            return []
        return self._paged("calls", {"status": "eq.open", "order": "call_id"})

    def fetch_organizations(self) -> list[dict]:
        if not self.enabled:
            return []
        return self._paged("organizations", {"select": "id,name,profile", "order": "created_at"})

    def fetch_matches(self, org_id: str) -> list[dict]:
        if not self.enabled:
            return []
        return self._paged("org_call_matches", {"org_id": f"eq.{org_id}", "order": "call_id"})

    def fetch_triage(self, org_id: str) -> list[dict]:
        if not self.enabled:
            return []
        return self._paged("org_call_triage", {"org_id": f"eq.{org_id}", "order": "call_id"})

    # -- matches ------------------------------------------------------------

    def upsert_matches(self, rows: list[dict]) -> int:
        """Write one org's matches.

        `first_matched_at` is omitted for the same reason `first_seen` is: it is
        when a call became new TO THIS ORG, and a rematch must not reset it.
        """
        if not self.enabled or not rows:
            return 0
        if self.dry_run:
            self.writes.extend(rows)
            return len(rows)

        written = 0
        for start in range(0, len(rows), UPSERT_BATCH):
            batch = rows[start:start + UPSERT_BATCH]
            self._request(
                "POST",
                "org_call_matches",
                payload=batch,
                prefer="resolution=merge-duplicates,return=minimal",
            )
            written += len(batch)
        return written

    def delete_matches(self, org_id: str, call_ids: list[str]) -> int:
        """Drop matches a rematch no longer produces.

        Unlike a warehouse call, a match row carries no history worth keeping:
        it is derived output, and an org that no longer matches a call should
        not see it. The call itself is untouched.
        """
        if not self.enabled or not call_ids:
            return 0
        if self.dry_run:
            return len(call_ids)

        deleted = 0
        for start in range(0, len(call_ids), UPSERT_BATCH):
            batch = call_ids[start:start + UPSERT_BATCH]
            quoted = ",".join(f'"{cid}"' for cid in batch)
            self._request(
                "DELETE",
                "org_call_matches",
                params={"org_id": f"eq.{org_id}", "call_id": f"in.({quoted})"},
            )
            deleted += len(batch)
        return deleted

    # -- notifications ------------------------------------------------------

    def claim_notification(self, org_id: str, kind: str, dedupe_key: str, call_count: int) -> bool:
        """
        Reserve the right to send one email, before sending it.

        Returns False when this exact notification has already been sent. The
        unique constraint on (org_id, kind, dedupe_key) is what enforces that —
        not this function, and not the caller's bookkeeping. Claiming first and
        sending second means a crash costs a missed email; sending first would
        risk a duplicate blast to a client's contact list, which is the one
        failure here that cannot be taken back.
        """
        if not self.enabled:
            return False
        if self.dry_run:
            return True

        try:
            self._request(
                "POST",
                "org_notifications",
                payload=[{
                    "org_id": org_id,
                    "kind": kind,
                    "dedupe_key": dedupe_key,
                    "call_count": call_count,
                }],
                prefer="return=minimal",
            )
        except WarehouseError as exc:
            # SQLSTATE, not message text. 23505 is a Postgres constant; the
            # phrasing of "duplicate key value violates..." is PostgREST's to
            # change. Matching on prose would fail open one release later, and
            # failing open here means a duplicate send.
            if exc.code == SQLSTATE_UNIQUE_VIOLATION:
                log.info("already sent: %s / %s / %s", org_id, kind, dedupe_key)
                return False
            # A 409 with any other code is NOT a duplicate — PostgREST maps
            # foreign-key violations to 409 as well, and an unknown org_id
            # reaching this branch would report "already sent" for an email
            # that was never sent and never will be. Raise instead.
            raise
        return True
