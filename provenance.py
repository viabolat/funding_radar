#!/usr/bin/env python3
"""
Provenance receipts for the watchers.
=====================================

The second module both scripts import, and the second deliberate exception to
the "duplicate the helpers" rule — for the same reason `calls_store.py` is the
first one. A receipt is only worth anything if every producer emits the *same*
shape: the whole point is that two runs, from two machines, can be compared
field for field. Two drifting copies of this would make the evidence useless,
which is a worse failure than the duplication it saves.

What a receipt is for
---------------------
Nothing in a digest distinguishes "these rows came off the wire" from "these
rows came out of a file someone put there". A receipt closes that gap without
requiring anyone to trust the run:

  * `sha256` is taken over the exact bytes that were parsed — not a
    re-serialisation of the objects afterwards.
  * `server_date`, `etag` and `last_modified` are the upstream server's own
    headers, echoed verbatim.
  * the funnel records how many records survived each filter stage, so the
    final count can be re-derived from the raw body offline.

Anyone can re-fetch the URL, hash it, and compare. A fabricated row cannot
produce a matching hash against a live re-fetch.

Nothing here ever touches the repo state files, and a Recorder with no
directory is a no-op, so wiring it into a code path cannot change what that
path does.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("provenance")

# Only these request headers are ever written to a receipt. This is an
# allowlist rather than a denylist on purpose: GITHUB_TOKEN rides in an
# `Authorization` header, and a receipt is an artifact people pass around.
SAFE_REQUEST_HEADERS = ("User-Agent", "If-None-Match", "If-Modified-Since", "Accept")

# Response headers worth keeping — the ones that let someone else re-fetch the
# same version of a resource and get the same hash.
KEPT_RESPONSE_HEADERS = ("Date", "ETag", "Last-Modified", "Content-Type", "Content-Length")

# How much of a body is kept when `full_bodies` is off. The EU reference
# dataset is ~130 MB; persisting it by default would make the evidence
# directory unusable and tempt someone into committing it.
SAMPLE_BYTES = 64 * 1024


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Recorder:
    """
    Collects receipts for one process run.

    `Recorder(None)` is a fully working no-op — every method is safe to call,
    nothing is written, and `enabled` is False. Call sites therefore never need
    to guard on whether evidence was asked for.
    """

    def __init__(self, evidence_dir: str | None = None, full_bodies: bool = False):
        self.dir = Path(evidence_dir) if evidence_dir else None
        self.full_bodies = full_bodies
        self.exchanges: list[dict] = []
        self.funnels: list[dict] = []
        self._seq = 0

    @property
    def enabled(self) -> bool:
        return self.dir is not None

    # -- HTTP ---------------------------------------------------------------

    def http(
        self,
        *,
        source: str,
        method: str,
        url: str,
        status: int,
        response_bytes: int,
        sha256: str,
        request_headers: dict | None = None,
        response_headers: dict | None = None,
        elapsed_ms: int | None = None,
        conditional: bool = False,
        not_modified: bool = False,
        sample: bytes = b"",
        note: str = "",
    ) -> None:
        """Record one HTTP exchange. `sha256` is over the bytes actually parsed."""
        if not self.enabled:
            return

        self._seq += 1
        response_headers = response_headers or {}
        request_headers = request_headers or {}

        entry = {
            "seq": self._seq,
            "ts": _utc_now(),
            "source": source,
            "method": method.upper(),
            "url": url,
            "status": status,
            "conditional": conditional,
            "not_modified": not_modified,
            "response_bytes": response_bytes,
            "sha256": sha256,
            "elapsed_ms": elapsed_ms,
            "request_headers": {
                name: request_headers[name]
                for name in SAFE_REQUEST_HEADERS
                if name in request_headers
            },
        }
        for name in KEPT_RESPONSE_HEADERS:
            entry[name.lower().replace("-", "_")] = response_headers.get(name)
        if note:
            entry["note"] = note

        if sample:
            entry["sample_path"] = self._write_sample(sample, sha256, url)
            entry["sample_bytes"] = len(sample)
            entry["sample_truncated"] = len(sample) < response_bytes

        self.exchanges.append(entry)

    def _write_sample(self, body: bytes, sha256: str, url: str) -> str:
        suffix = ".json" if url.endswith(".json") else ".txt"
        if url.endswith(".csv"):
            suffix = ".csv"
        raw_dir = self.dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        name = f"{self._seq:03d}-{sha256[:8]}{suffix}"
        (raw_dir / name).write_bytes(body)
        return f"raw/{name}"

    def body_for_evidence(self, body: bytes) -> bytes:
        """Trim a body to what should be persisted, honouring --evidence-full."""
        if not self.enabled:
            return b""
        return body if self.full_bodies else body[:SAMPLE_BYTES]

    # -- Filter funnel ------------------------------------------------------

    def funnel(self, source: str, **stages: int) -> None:
        """
        Record how many records survived each filter stage, in the order given.

        This is the half that makes a count checkable: with the raw body and
        these numbers, someone else can re-run the filters by hand and land on
        the same total.
        """
        record = {"source": source, "stages": dict(stages)}
        self.funnels.append(record)
        log.info(
            "%s funnel: %s",
            source,
            " ".join(f"{name}={count}" for name, count in stages.items()),
        )

    # -- Output -------------------------------------------------------------

    def write(self) -> str | None:
        """Write manifest.json. Returns its path, or None when disabled."""
        if not self.enabled:
            return None

        self.dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "generated_at": _utc_now(),
            "exchanges": self.exchanges,
            "funnels": self.funnels,
            "totals": {
                "requests": len(self.exchanges),
                "bytes_downloaded": sum(e["response_bytes"] for e in self.exchanges),
            },
        }
        path = self.dir / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(
            "Evidence written to %s (%d request(s), %d byte(s) downloaded)",
            path,
            manifest["totals"]["requests"],
            manifest["totals"]["bytes_downloaded"],
        )
        return str(path)
