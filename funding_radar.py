#!/usr/bin/env python3
"""
Funding Radar — the collector
=============================

Pulls open funding calls from two free, confirmed sources:

  1. adieuronest.ro          -> Romania national + RO/MD/UA cross-border calls (CSV feed)
  2. EU Funding & Tenders     -> Horizon Europe, Erasmus+, LIFE, Digital Europe, EU4Health,
     Portal                      EIC, and every other centrally-managed EU programme

The EU half follows the two APIs the portal documents at
https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/support/apis:
the bulk reference dataset enumerates every opportunity (discovery), and the
SEDIA search API is asked about the handful that matched (enrichment). Asking
the dataset rather than the search index is what makes coverage a fact rather
than a function of how eleven keyword queries happen to rank.

**Scraping is organisation-agnostic.** Both fetchers keep everything above a low
structural bar — a grant, not already closed, deadline still ahead — and no
further. Relevance is not their job: they compute two matching surfaces per call
(`search_core`, `search_wide`) and record what the source says the call is open
to (`eligible_as`), and `match.py` decides per organisation from a profile. What
a fetcher discards is discarded for every tenant forever, so the bar it applies
has to be a fact about the call rather than an opinion about an applicant.

`calls.json`, the digest and the GitHub Issue are still ONE organisation's
export — they always were — so this script matches inline before writing them.
It matches with the same profile document `match.py` uses, read out of
`organizations`; see `export_profile()` for the precedence and for why the
built-in seed copy is a bootstrap value rather than a second source of truth.

Remembers what it has already reported (via seen_calls.json, committed back to
the repo by the GitHub Actions workflow) so re-runs only surface NEW matches,
and opens a GitHub Issue per run when there's something new to report.

Delivery is GitHub Issues only — no Slack, no Telegram, no email/SMTP. GitHub
auto-emails anyone watching the repo when an issue opens, so that's the whole
notification path.

Requests use a retry-with-backoff session (5 attempts, exponential backoff,
honors Retry-After) since neither source publishes a documented rate limit.

Requires: pip install requests

Local run (writes digest to file only, does not open a GitHub Issue):
    python funding_radar.py

Run inside GitHub Actions (opens/updates an Issue via the GitHub API):
    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo python funding_radar.py --create-issue
"""

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlparse

import ijson
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from calls_store import atomic_write_text, write_source_calls
from match import match_all
from provenance import Recorder, sha256_of
from warehouse import Warehouse

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------


def _user_agent() -> str:
    """The contact string every outbound request carries.

    A User-Agent is a contact address for whoever operates the crawler, and this
    crawler serves the whole warehouse rather than any one organisation — so it
    names the repository, not a tenant. Putting one org's office address on a
    request to the EU portal is the identity leak most visible from outside this
    repo, and the hardest to withdraw once it is in someone's access log.

    `GITHUB_REPOSITORY` is set automatically inside Actions. Locally it is
    absent and the bare product string is sent: an invented URL would be worse
    than no URL, because a contact address that goes nowhere is not a contact
    address. `mipe_watch.py` carries a copy of this — four lines duplicated, in
    keeping with "every other shared helper is duplicated by design"; a fourth
    shared module for a string is not a trade worth making.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo:
        return f"FundingRadar/1.0 (+https://github.com/{repo})"
    return "FundingRadar/1.0"


CONFIG = {
    "seen_store_path": "seen_calls.json",
    "digest_output_path": "digests/digest_{date}.md",

    "adieuronest_csv_url": "https://adieuronest.ro/finantari.csv",

    # DISCOVERY — the portal's own bulk reference dataset, listed on
    # https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/support/apis
    #
    # This is the dataset the portal's search index is built FROM, and asking it
    # directly removes four whole classes of defect the search index forced on
    # us: one record per topic instead of one per translation, `frameworkProgramme`
    # as a named object instead of the opaque id 43108390, a resolvable status,
    # and typed epoch-ms deadline lists. Coverage stops depending on how the
    # portal ranks eleven keyword queries and becomes a plain enumeration.
    #
    # Measured 2026-09-08: 129,759,798 bytes, 11,160 records, refreshed daily.
    "eu_reference_url": (
        "https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json"
    ),
    # A hard ceiling on what we will read off the wire. The file grows slowly;
    # 400 MB is generous. Without this an upstream fault (or a redirect to
    # something else entirely) could stream until the runner dies.
    "eu_reference_max_bytes": 400 * 1024 * 1024,

    # `type` in that dataset is exactly two values, confirmed by counting all
    # 11,160 records: 1 = grant topic (10,161 of them; carries callIdentifier and
    # frameworkProgramme), 0 = procurement tender (999; carries lots, CPV codes
    # and placesOfDeliveryOrPerformance instead). The warehouse collects grants;
    # a tender is a contract to supply the Commission, not something an applicant
    # organisation applies to, so it is out of scope for every tenant rather than
    # filtered per tenant. The old ["1","2","8"] was a guess against a different
    # vocabulary — the search index's, not the dataset's.
    "eu_grant_type": 1,

    # Forthcoming is kept on purpose: it is the call you still have time to
    # prepare for. Closed is dropped. Live counts: 368 Open, 279 Forthcoming,
    # 10,513 Closed. The deadline is checked SEPARATELY and always — see
    # _eu_deadline; the portal's status has been wrong before.
    "eu_statuses": {"Open", "Forthcoming"},

    # Grant records carry no url of their own (only tenders do), so the topic
    # page is built from the identifier. Enrichment overwrites this with the
    # portal's own url when the search API answers.
    "eu_topic_url": (
        "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
        "opportunities/topic-details/{identifier}"
    ),

    # ENRICHMENT — the SEDIA search API, now queried once per MATCHED topic
    # instead of once per keyword per page. It still answers GET with 405: the
    # filter goes up as a multipart part named "query" and the free text stays in
    # the query string. It is the only source for a topic's budget and prose, and
    # a failure here must never drop a call that discovery already found.
    "eu_sedia_url": "https://api.tech.ec.europa.eu/search-api/prod/rest/search",
    "eu_sedia_api_key": "SEDIA",   # fixed public constant, not a personal credential
    "eu_sedia_languages": ["en", "ro"],
    "eu_sedia_language_preference": ["en", "ro"],
    "eu_sedia_page_size": 20,

    # `stare` is one of: activ, anuntat, inchis. A closed call is closed for
    # every organisation, so this is a structural bar and stays in the fetcher.
    "adieuronest_excluded_stare": {"inchis"},

    # Which organisation's matches become calls.json, the digest and the Issue.
    # An id rather than a name, and an environment value rather than a literal,
    # so no tenant's identity is compiled into this file. Set as an Actions
    # variable; unset means the export falls back to SEED_PROFILE — see
    # export_profile().
    "export_org_id": os.environ.get("EXPORT_ORG_ID", "").strip(),

    "user_agent": _user_agent(),

    "github_issue_labels": ["funding-radar"],

    # Retry/backoff behavior for both HTTP sources.
    "retry_total": 5,
    "retry_backoff_factor": 2,   # sleeps ~2s, 4s, 8s, 16s, 32s between attempts

    # (connect, read) rather than one number. A source that accepts the socket
    # and then stalls is the common upstream failure, and it deserves a longer
    # budget than one that will not accept a connection at all. The reference
    # dataset is 130 MB, so its read budget is the largest.
    "timeout_default": (10, 30),
    "timeout_bulk": (10, 300),

    # Every response is checked against this AFTER redirects. A source that can
    # redirect us somewhere else can otherwise feed the digest — and the
    # dashboard, and an Issue emailed to the whole office — arbitrary content.
    "allowed_hosts": {
        "adieuronest.ro",
        "www.adieuronest.ro",
        "ec.europa.eu",
        "api.tech.ec.europa.eu",
    },
}

# ---------------------------------------------------------------------------
# THE EXPORT PROFILE
#
# Until Phase C these term lists were CONFIG — global product configuration that
# every scrape applied to every row. They are now one organisation's data, and
# the copy that counts lives in `organizations.profile`, which is also what the
# dashboard edits and what match.py reads.
#
# SEED_PROFILE below is a BOOTSTRAP COPY of supabase/migrations/0004, not a
# second source of truth. It is used only when there is no database to disagree
# with — a local run, and the offline test suite, neither of which has a
# dashboard that could have edited anything. Whenever the warehouse is
# configured and an export org is named, the stored profile wins outright, so
# editing a profile changes calls.json on the very next run.
#
# The one copy pair this leaves — this constant against the migration — is
# covered by a test that parses the SQL and compares the lists term for term,
# in order. Order matters: `match.match_reason` renders terms in profile order,
# and that ordering is what today's digest says.
# ---------------------------------------------------------------------------

SEED_PROFILE = {
    "eligible_as": ["ong", "sanatate"],
    "matching": {
        # Romanian: adieuronest and mipe_calendar. CORE is matched against the
        # full record including the long eligibility and funding prose.
        "ro": {
            "core": [
                "cancer", "oncolog", "tumor", "paliativ",
                "terapii complementare", "terapii alternative", "terapii integrative",
                "abordare holistica", "abordare holistă", "holistic",
                "psihoterapie", "sprijin emotional", "sprijin emoțional",
                "sănătate mintal", "sanatate mintal",
                "pacient", "screening", "boli cronice", "nutriție", "nutritie",
            ],
            # WIDE is matched against TITLE AND PROGRAMME ONLY. These words turn
            # up constantly in generic boilerplate ("beneficiarii din domeniul
            # sănătății pot..."), so full-text matching on them pulled in NetZero
            # innovation and textile-SME calls. In a title they are signal.
            # Both diacritic and non-diacritic spellings are listed, and terms
            # are stems: Romanian inflects, so 'sănătate' does not match
            # 'sănătății'. They are NOT folded at match time — see match.py.
            "wide": [
                "sănătate", "sanatate", "medical", "spital", "psiholog",
                "consiliere", "prevenție", "preventie", "incluziune",
                "vindecare", "ong",
            ],
            "guards": [],
        },
        # English: the EU reference dataset.
        "en": {
            # Matched against title + callTitle. Deliberately NOT against `tags`
            # or `keywords`, which are a ~40-term marketing dump — matching them
            # made "mental health" hit a call about eradicating invasive species
            # and "nutrition" hit livestock feed.
            "core": [
                "cancer", "oncolog", "tumour", "palliative", "psychosocial",
                "psychotherap", "mental health", "integrative medicine",
                "complementary medicine", "patient support", "patient empowerment",
                "patient-centred", "cancer survivor", "caregiver", "informal carer",
                "health promotion", "health literacy", "hospice", "cancer patients",
                "chronic disease", "non-communicable disease",
            ],
            # Matched against the TITLE ONLY, and phrases rather than bare words.
            # Bare "health" matches soil, plant, livestock and ecosystem health;
            # bare "mental" is a substring of environmental, experimental and
            # fundamental, which is how a quantum-computing pilot line reached a
            # cancer-charity digest during calibration.
            "wide": [
                "public health", "human health", "healthcare", "health care",
                "health system", "mental well", "psycholog", "wellbeing",
                "well-being", "social inclusion", "disease prevention", "screening",
            ],
            # A title carrying a WIDE term AND one of these is about something
            # else. The health vocabulary is shared with agriculture, ecology and
            # security: "Health of ecosystems and wild species, predictions and
            # impacts on human health" is a biodiversity call, not a health one.
            "guards": [
                "soil", "plant health", "animal", "livestock", "veterinar",
                "ecosystem", "crime", "food waste", "forest", "biodivers",
                "wildlife", "construction", "renovation", "footwear", "vehicle",
            ],
        },
    },
}


def export_profile(warehouse: Warehouse) -> dict:
    """The profile calls.json, the digest and the Issue are produced from.

    Precedence, and the reason for it: the stored profile is the one the
    dashboard edits and the one match.py matches with, so if it exists it wins.
    Falling back to SEED_PROFILE while a database row also existed would let the
    export and the dashboard disagree about what the organisation sees, with
    both looking live — the exact drift a single document exists to prevent.

    The fallback therefore fires only where no stored profile is reachable: a
    local run, or the offline suite. It logs which one it used, because "why is
    the digest different on the runner" is otherwise an unanswerable question.
    """
    org_id = CONFIG["export_org_id"]
    if warehouse.enabled and org_id:
        for org in warehouse.fetch_organizations():
            if org.get("id") == org_id:
                log.info("export profile: %s (from the warehouse)", org.get("name") or org_id)
                return org.get("profile") or {}
        # Named but absent is a misconfiguration, not a reason to silently
        # export someone else's idea of relevance.
        raise ValueError(f"EXPORT_ORG_ID {org_id!r} is not an organisation in the warehouse")
    log.info("export profile: built-in seed (no warehouse export org configured)")
    return SEED_PROFILE


# Prefix -> readable name. The reference dataset carries the programme as a named
# object, so this is no longer the primary path — it is the fallback for the
# ~0 records that arrive without one, and for anything still coming back from the
# search index, where `frameworkProgramme` is the opaque id 43108390.
EU_PROGRAMME_PREFIXES = {
    "HORIZON": "Horizon Europe",
    "EU4H": "EU4Health",
    "ERASMUS": "Erasmus+",
    "LIFE": "LIFE",
    "DIGITAL": "Digital Europe",
    "CERV": "Citizens, Equality, Rights and Values",
    "AMIF": "Asylum, Migration and Integration Fund",
    "ESF": "European Social Fund+",
    "EMPL": "Employment and Social Innovation",
    "JUST": "Justice Programme",
    "ISF": "Internal Security Fund",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("funding_radar")


# ---------------------------------------------------------------------------
# RESILIENT HTTP SESSION — retries on 429/5xx, honors Retry-After, backs off
# exponentially with jitter. Neither adieuronest.ro nor the EU SEDIA API
# publishes a documented rate limit, so this is the defensive default.
# ---------------------------------------------------------------------------

def create_resilient_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": CONFIG["user_agent"]})

    retry_strategy = Retry(
        total=CONFIG["retry_total"],
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=CONFIG["retry_backoff_factor"],
        backoff_jitter=1,
        respect_retry_after_header=True,
        allowed_methods=["GET", "POST"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # Certificate verification is requests' default; setting it here makes it a
    # visible property of the session rather than an assumption, and there is
    # deliberately no env var or flag that turns it off.
    session.verify = True
    return session


def assert_trusted(response: requests.Response) -> None:
    """
    Reject a response that did not come from an expected host over TLS.

    reason: `response.url` is the URL AFTER redirects. Everything these scripts
    fetch is unauthenticated public data, so nothing stops an upstream from
    redirecting elsewhere — and whatever comes back is parsed, written into
    calls.json, rendered by the dashboard and mailed to the office inside an
    Issue. Checking the final host is what keeps "public data" from meaning
    "data from anyone".
    """
    parsed = urlparse(response.url)
    if parsed.scheme != "https":
        raise requests.RequestException(f"Refusing a non-HTTPS response from {response.url}")
    if parsed.hostname not in CONFIG["allowed_hosts"]:
        raise requests.RequestException(
            f"Refusing a response from unexpected host {parsed.hostname!r} ({response.url})"
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def download_to_file(
    session: requests.Session,
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    timeout,
    headers: dict | None = None,
    recorder: Recorder | None = None,
    source: str = "",
) -> tuple[int, str, int, requests.Response]:
    """
    Stream a URL to `dest`, hashing as it goes. Returns (status, sha256, bytes, response).

    Streaming rather than `response.content` is what keeps a 130 MB body off the
    heap, and hashing the chunks as they are written means the recorded digest
    is over the exact bytes that get parsed — not over a re-serialisation of the
    objects afterwards, which would prove nothing about what arrived.

    A body that grows past `max_bytes` aborts. The cap is not about a
    well-behaved source; it is about the one that is not.
    """
    started = time.monotonic()
    request_headers = dict(headers or {})

    with session.get(url, timeout=timeout, headers=request_headers, stream=True) as response:
        assert_trusted(response)

        if response.status_code == 304:
            if recorder:
                recorder.http(
                    source=source, method="GET", url=response.url, status=304,
                    response_bytes=0, sha256="", request_headers=request_headers,
                    response_headers=dict(response.headers), elapsed_ms=_elapsed_ms(started),
                    conditional=True, not_modified=True,
                    note="cached copy still current; body not re-downloaded",
                )
            return 304, "", 0, response

        response.raise_for_status()

        digest = hashlib.sha256()
        total = 0
        sample = bytearray()
        keep_full = bool(recorder and recorder.full_bodies)

        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise requests.RequestException(
                        f"{url} exceeded the {max_bytes} byte ceiling after {total} bytes — aborted"
                    )
                digest.update(chunk)
                handle.write(chunk)
                if keep_full:
                    sample.extend(chunk)
                elif len(sample) < 64 * 1024:
                    sample.extend(chunk[: 64 * 1024 - len(sample)])

    sha = digest.hexdigest()
    if recorder:
        recorder.http(
            source=source, method="GET", url=response.url, status=response.status_code,
            response_bytes=total, sha256=sha, request_headers=request_headers,
            response_headers=dict(response.headers), elapsed_ms=_elapsed_ms(started),
            conditional=bool(request_headers.keys() & {"If-None-Match", "If-Modified-Since"}),
            sample=bytes(sample),
        )
    return response.status_code, sha, total, response


# ---------------------------------------------------------------------------
# DATA MODEL
# ---------------------------------------------------------------------------

@dataclass
class FundingCall:
    source: str
    call_id: str
    title: str
    # ISO date (YYYY-MM-DD) or "". Kept free of prose so the dashboard can
    # compute urgency from it; "announced but not yet open" rides on `announced`
    # rather than being appended to the date.
    deadline: str = ""
    announced: bool = False
    budget: str = ""
    programme: str = ""
    link: str = ""
    tags: list[str] = field(default_factory=list)
    match_reason: str = ""
    raw: dict = field(default_factory=dict)

    # -- organisation-agnostic matching inputs, computed at ingest -------------
    # The fetcher is the only code that knows a source's shape, so it is the
    # only code that can say which prose is a name and which is fine print.
    # It writes the two surfaces and stops; what counts as relevant in them is
    # match.py's question, asked once per organisation.
    lang: str = ""
    search_core: str = ""
    search_wide: str = ""
    # What the SOURCE says the call is open to. Empty means the source publishes
    # no applicant vocabulary — the EU dataset does not — which is "unknown",
    # never "open to nobody".
    eligible_as: list[str] = field(default_factory=list)
    # Tags that stay at the end of the list after matched terms are merged in.
    # Today only adieuronest publishes one ("anunțat"); the EU side carries the
    # same fact in `announced` and renders it in the digest line instead. That
    # asymmetry is inherited, not designed — it is preserved here rather than
    # tidied because tidying it would rewrite tag order for live rows.
    status_tags: list[str] = field(default_factory=list)

    def apply_match(self, match) -> None:
        """Fold one organisation's match result back onto the call.

        Matched terms join the source's own vocabulary in one sorted set, which
        is what the pre-Phase-C fetchers produced, and the status tags are
        appended after the sort so their position does not move.
        """
        self.match_reason = match.match_reason
        self.tags = sorted(set(match.matched_terms) | set(self.tags)) + list(self.status_tags)

    def digest_line(self) -> str:
        parts = [f"**{self.title}**"]
        if self.programme:
            parts.append(f"_{self.programme}_")
        if self.deadline:
            deadline = self.deadline
            if self.announced:
                deadline += " (announced, not yet open)"
            parts.append(f"deadline: {deadline}")
        if self.budget:
            parts.append(f"budget: {self.budget}")
        line = " — ".join(parts)
        if self.link:
            line += f"\n  {self.link}"
        return line

    def to_record(self) -> dict:
        """The dashboard feed row. Triage fields are deliberately absent — they
        are user-authored and live in triage.json under the same call_id."""
        return {
            "call_id": self.call_id,
            "source": self.source,
            "title": self.title,
            "programme": self.programme,
            "deadline": self.deadline or None,
            "announced": self.announced,
            "budget": self.budget,
            "tags": self.tags,
            "match_reason": self.match_reason,
            "link": self.link,
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
        }

    def to_warehouse_row(self) -> dict:
        """The warehouse row: the feed record plus what matching needs.

        Kept separate from `to_record()` on purpose. That one is the calls.json
        contract, mirrored field for field by web/src/types.ts and pinned by
        FEED_VERSION; adding the matching surfaces to it would push a megabyte
        of eligibility prose into the dashboard's download and force a version
        bump for data no reader wants.
        """
        return dict(
            self.to_record(),
            lang=self.lang,
            search_core=self.search_core,
            search_wide=self.search_wide,
            eligible_as=self.eligible_as,
            raw=self.raw,
        )


# ---------------------------------------------------------------------------
# SOURCE 1 — adieuronest.ro
# ---------------------------------------------------------------------------

def _adieuronest_budget(row: dict) -> str:
    """Renders the three money columns into one human line, skipping blanks."""
    lo = (row.get("valoare_min") or "").strip()
    hi = (row.get("valoare_max") or "").strip()
    alocare = (row.get("alocare") or "").strip()

    if lo and hi and lo != hi:
        per_project = f"{lo} – {hi}"
    else:
        per_project = lo or hi

    if per_project and alocare:
        budget = f"{per_project} / project (total {alocare})"
    else:
        budget = per_project or alocare

    # These columns are free text, not numbers — `alocare` sometimes holds a
    # whole paragraph ("Bugetul total alocat pentru prezentul apel este de..."),
    # which ran a single digest line off the page.
    return _shorten(budget, 140)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip(" ,.;:(") + "…"


def fetch_adieuronest_calls(
    session: requests.Session,
    recorder: Recorder | None = None,
) -> list[FundingCall]:
    """
    Downloads the full CSV feed and keeps every row that is not already closed.

    That is the whole gate, and it is deliberately structural: a closed call is
    closed for every organisation. The `categorii` column used to be applied
    here as an eligibility gate against one organisation's answer; it is now
    carried on the row as `eligible_as`, and the intersection is taken per
    organisation in match.py. Whatever this function drops is dropped for every
    future tenant, so it drops only facts.

    Field names below are the live header, confirmed against the real feed:
        id, titlu, program, cod, tip, stare, tara, si_md, si_ua, regiune,
        nord_est, categorii, solicitanti, finanteaza, conditii, valoare_min,
        valoare_max, alocare, cofinantare, deschidere, termen, termen_iso,
        depunere, url, ghid_url, fisa_url, adaugat, verificat_la, stadiu, sursa

    There is no `descriere` column; the prose lives in solicitanti / finanteaza
    / conditii, which is why `search_core` is built from them. The whole row is
    kept in `raw`, so the columns nothing reads yet — the geography ones above
    all — are preserved rather than discarded at the door.
    """
    recorder = recorder or Recorder(None)
    url = CONFIG["adieuronest_csv_url"]
    log.info("Fetching adieuronest.ro CSV feed: %s", url)

    started = time.monotonic()
    response = session.get(url, timeout=CONFIG["timeout_default"])
    assert_trusted(response)
    response.raise_for_status()

    body = response.content
    recorder.http(
        source="adieuronest",
        method="GET",
        url=response.url,
        status=response.status_code,
        response_bytes=len(body),
        sha256=sha256_of(body),
        request_headers=dict(response.request.headers) if response.request else None,
        response_headers=dict(response.headers),
        elapsed_ms=_elapsed_ms(started),
        sample=recorder.body_for_evidence(body),
    )

    # reason: the feed is served with a UTF-8 BOM. Decoding as plain utf-8 left
    # the first header as "\ufeffid", so row.get("id") was always None and every
    # call silently fell through to a URL-derived id — collapsing 495 calls onto
    # 464 ids, so 31 were never reported at all. utf-8-sig strips the BOM.
    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    excluded_stare = CONFIG["adieuronest_excluded_stare"]

    calls: list[FundingCall] = []
    rows = 0

    for row in reader:
        rows += 1
        if (row.get("stare") or "").strip().lower() in excluded_stare:
            continue

        title = (row.get("titlu") or "").strip()
        programme = (row.get("program") or "").strip()
        categories = sorted(
            {c.strip().lower() for c in (row.get("categorii") or "").split("|") if c.strip()}
        )

        link = (row.get("url") or "").strip()
        # `cod` is blank on roughly half the feed, so it cannot stand alone.
        call_id = (row.get("id") or "").strip() or (row.get("cod") or "").strip() or link or title

        # termen is dd.mm.yyyy; termen_iso is already ISO. Only the ISO form is
        # kept so the dashboard can compare it against today.
        deadline = (row.get("termen_iso") or "").strip()
        announced = (row.get("stare") or "").strip().lower() == "anuntat"

        calls.append(
            FundingCall(
                source="adieuronest",
                call_id=f"adieuronest:{call_id}",
                title=title or "(no title)",
                deadline=deadline,
                announced=announced,
                budget=_adieuronest_budget(row),
                programme=programme,
                link=link,
                # The source's own vocabulary, and nothing derived from any
                # organisation. Matched terms are merged in by apply_match.
                tags=list(categories),
                status_tags=["anunțat"] if announced else [],
                lang="ro",
                # CORE sees the fine print, WIDE sees only the names. Lowercased
                # once here rather than on every term comparison in every run.
                search_core=" ".join(
                    (row.get(f) or "")
                    for f in ("titlu", "program", "solicitanti", "finanteaza", "conditii")
                ).lower(),
                search_wide=f"{title} {programme}".lower(),
                eligible_as=list(categories),
                raw=row,
            )
        )

    recorder.funnel(
        "adieuronest",
        rows=rows,
        # reason: `applicable` and `relevant` were counts of one organisation's
        # gate, and reporting them from an organisation-agnostic scrape would be
        # a receipt for a decision this code no longer makes. The per-org funnel
        # is recorded where that decision now happens — see main() and match.py.
        not_closed=len(calls),
        emitted=len(calls),
    )
    log.info("adieuronest.ro: %d open call(s) collected", len(calls))
    return calls


# ---------------------------------------------------------------------------
# SOURCE 2 — EU Funding & Tenders Portal
#
# Two endpoints, both listed on the portal's own API page
# (.../portal/screen/support/apis), used for the two different jobs they are
# actually good at:
#
#   DISCOVERY   GET  ec.europa.eu/.../data/referenceData/grantsTenders.json
#               The bulk reference dataset — every opportunity the portal
#               knows about, one record each, refreshed daily. This answers
#               "which calls exist", and it answers it by enumeration.
#
#   ENRICHMENT  POST api.tech.ec.europa.eu/search-api/prod/rest/search
#               The search index built over that dataset. It holds the budget
#               and the canonical topic URL, which the bulk file does not, so
#               it is asked about the ~20 topics discovery matched — not the
#               11 keywords × 3 pages it used to be asked about.
#
# The split matters because the search index is lossy in ways the dataset is
# not: it stores one document per translation, replaces the framework
# programme with an opaque numeric id, and carries stale statuses. Using it for
# discovery meant inheriting all three. Using it for enrichment means a failure
# costs a budget line, not a call.
# ---------------------------------------------------------------------------

def _sedia_first(metadata: dict, field_name: str) -> str:
    """Every metadata value comes back wrapped in a list."""
    value = metadata.get(field_name)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def _language_rank(language: str, preference: list[str]) -> int:
    """Lower is better. Anything unlisted sorts after every preferred language."""
    try:
        return preference.index(language)
    except ValueError:
        return len(preference)


def _sedia_programme(identifier: str, metadata: dict) -> str:
    """Name the programme from the identifier prefix, falling back to whatever
    the search index gave us (an opaque id, but better than blank)."""
    prefix = identifier.split("-", 1)[0].upper()
    if prefix in EU_PROGRAMME_PREFIXES:
        return EU_PROGRAMME_PREFIXES[prefix]
    return _sedia_first(metadata, "frameworkProgramme")


def _sedia_budget(metadata: dict, identifier: str) -> str:
    """
    budgetOverview is a multi-kilobyte JSON string covering every topic in the
    parent call. Dumping it raw made the digest unreadable, so this pulls out
    only the contribution range for THIS topic.
    """
    raw = _sedia_first(metadata, "budgetOverview")
    if not raw:
        return ""

    try:
        overview = json.loads(raw)
    except (ValueError, TypeError):
        return ""

    for actions in (overview.get("budgetTopicActionMap") or {}).values():
        for action in actions:
            if not str(action.get("action", "")).startswith(identifier):
                continue
            low = action.get("minContribution")
            high = action.get("maxContribution")
            grants = action.get("expectedGrants")
            if not (low or high):
                continue
            if low and high and low != high:
                amount = f"EUR {low:,} – {high:,}".replace(",", " ")
            else:
                amount = f"EUR {(low or high):,}".replace(",", " ")
            if grants:
                amount += f" ({grants} grant(s) expected)"
            return amount
    return ""


# -- Reference dataset: record helpers --------------------------------------

def _eu_epoch_to_iso(value) -> str:
    """
    Reference-dataset dates are epoch MILLISECONDS, as int or as a string.

    reason: seconds would put every deadline in 1970 and the expiry filter
    would then silently drop the entire EU feed — a failure that looks exactly
    like "no EU calls matched this week".
    """
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _eu_deadline(record: dict) -> tuple[str, bool]:
    """
    Returns (deadline, expired).

    `deadlineDatesLong` is a LIST — multi-cutoff calls like the EIC Accelerator
    carry four — so this takes the next cutoff still ahead of us, not [0].

    The deadline is checked even though the dataset's `status` is already
    filtered, and deliberately so: EU4H-2024-PJ-03-5 sat at status "Open" with a
    deadline of 2025-01-21 for months. Status is a claim; the deadline is a date.
    """
    values = record.get("deadlineDatesLong") or []
    if not isinstance(values, list):
        values = [values]

    dates = sorted(d for d in (_eu_epoch_to_iso(v) for v in values) if d)
    if not dates:
        # Forthcoming calls routinely have no deadline published yet. Keep them.
        return "", False

    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    upcoming = [d for d in dates if d >= today]
    if upcoming:
        return upcoming[0], False
    return dates[-1], True


def _eu_programme(record: dict) -> str:
    """The dataset carries the programme as a named object. Only if it is absent
    do we fall back to naming it from the identifier prefix."""
    programme = record.get("frameworkProgramme")
    if isinstance(programme, dict):
        name = (programme.get("description") or programme.get("abbreviation") or "").strip()
        if name:
            return name
    identifier = str(record.get("identifier") or "")
    prefix = identifier.split("-", 1)[0].upper()
    return EU_PROGRAMME_PREFIXES.get(prefix, "")


def _eu_topic_url(identifier: str) -> str:
    """Grant records carry no url of their own — only tenders do — so the topic
    page is built from the identifier, which is what the portal itself uses."""
    return CONFIG["eu_topic_url"].format(identifier=identifier.lower())


# -- Reference dataset: fetch and iterate ------------------------------------

def _load_cache_meta(cache_dir: Path) -> dict:
    meta_path = cache_dir / "grantsTenders.meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def fetch_eu_reference(
    session: requests.Session,
    dest: Path,
    recorder: Recorder | None = None,
    cache_dir: Path | None = None,
) -> Path:
    """
    Download the bulk reference dataset to `dest` and return its path.

    When `cache_dir` is given and already holds a copy, the request carries
    If-None-Match / If-Modified-Since and a 304 means the cached body is reused
    untouched. That is worth real bandwidth for repeated local runs; on a CI
    runner the checkout is fresh every time, so there is nothing to revalidate
    and this is always a full download. Conditional requests are therefore
    opt-in (--cache-dir) rather than the default: sending If-None-Match with no
    body to fall back on would turn a 304 into an outage.
    """
    url = CONFIG["eu_reference_url"]
    headers: dict[str, str] = {}
    cached_body = None

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        candidate = cache_dir / "grantsTenders.json"
        if candidate.exists():
            cached_body = candidate
            meta = _load_cache_meta(cache_dir)
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        dest = candidate

    log.info("Fetching EU reference dataset: %s", url)
    status, sha, size, response = download_to_file(
        session,
        url,
        dest,
        max_bytes=CONFIG["eu_reference_max_bytes"],
        timeout=CONFIG["timeout_bulk"],
        headers=headers,
        recorder=recorder,
        source="eu_reference",
    )

    if status == 304 and cached_body is not None:
        log.info("EU reference dataset unchanged (304) — reusing the cached copy")
        return cached_body

    log.info("EU reference dataset: %d bytes, sha256 %s", size, sha)

    if cache_dir is not None:
        (cache_dir / "grantsTenders.meta.json").write_text(
            json.dumps(
                {
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "sha256": sha,
                    "bytes": size,
                    "fetched_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return dest


def iter_eu_opportunities(path: Path) -> Iterator[dict]:
    """
    Stream the records out of the dataset one at a time.

    reason: json.load on a 130 MB file materialises ~11,000 dicts of ~40 fields
    at once. It fits on a runner today, but the file only grows, and nothing
    here needs more than one record in hand. ijson keeps the memory flat.
    """
    with path.open("rb") as handle:
        yield from ijson.items(handle, "fundingData.GrantTenderObj.item")


# -- Enrichment via the search index -----------------------------------------

def enrich_eu_call(
    session: requests.Session,
    call: FundingCall,
    identifier: str,
    recorder: Recorder | None = None,
) -> None:
    """
    Ask the search index about ONE topic and fill in what the bulk file lacks:
    the budget and the portal's canonical URL.

    Mutates `call` in place and never raises. Discovery already established that
    this call exists and is relevant; a search-index failure must cost a budget
    line, not the call. That asymmetry is the whole point of the split.
    """
    query = {
        "bool": {
            "must": [
                {"terms": {"language": CONFIG["eu_sedia_languages"]}},
            ]
        }
    }
    params = {
        "apiKey": CONFIG["eu_sedia_api_key"],
        "text": f'"{identifier}"',
        "pageSize": CONFIG["eu_sedia_page_size"],
        "pageNumber": 1,
    }
    started = time.monotonic()

    try:
        response = session.post(
            CONFIG["eu_sedia_url"],
            params=params,
            files={"query": ("query.json", json.dumps(query), "application/json")},
            timeout=CONFIG["timeout_default"],
        )
        assert_trusted(response)
        response.raise_for_status()
        body = response.content
        data = json.loads(body)
    except (requests.RequestException, ValueError) as exc:
        log.warning("Enrichment failed for %s (keeping the call): %s", identifier, exc)
        return

    if recorder:
        recorder.http(
            source="eu_sedia_enrich", method="POST", url=response.url,
            status=response.status_code, response_bytes=len(body), sha256=sha256_of(body),
            response_headers=dict(response.headers), elapsed_ms=_elapsed_ms(started),
            sample=recorder.body_for_evidence(body), note=f"enrich {identifier}",
        )

    # The index answers in every translation it has; take the most preferred.
    best: dict | None = None
    best_rank = len(CONFIG["eu_sedia_language_preference"]) + 1
    for item in data.get("results", []):
        metadata = item.get("metadata", {})
        if _sedia_first(metadata, "identifier") != identifier:
            continue
        rank = _language_rank(_sedia_first(metadata, "language"), CONFIG["eu_sedia_language_preference"])
        if rank < best_rank:
            best, best_rank = item, rank

    if best is None:
        return

    metadata = best.get("metadata", {})
    call.budget = _sedia_budget(metadata, identifier) or call.budget
    call.link = _sedia_first(metadata, "url") or best.get("url", "") or call.link

    # The portal's own keyword list is a better tag source than the bulk file's
    # marketing tags — but it is not trusted for MATCHING, only for display.
    portal_keywords = [
        k for k in (metadata.get("keywords") or [])
        if isinstance(k, str) and not k.startswith(identifier.split("-")[0])
    ]
    if portal_keywords:
        call.tags = sorted(set(call.tags + portal_keywords[:6]))


# -- The source -------------------------------------------------------------

def fetch_eu_calls(
    session: requests.Session,
    recorder: Recorder | None = None,
    cache_dir: Path | None = None,
    dataset_path: Path | None = None,
) -> list[FundingCall]:
    """
    Enumerate the reference dataset and keep every live grant.

    Three structural bars and no fourth: a grant rather than a tender, a status
    of Open or Forthcoming, and a deadline still ahead. All three are facts
    about the call. The keyword gate that used to run here as well is gone —
    it was one organisation's, it rejected 10,137 of 10,161 grants, and every
    rejection was permanent for every tenant that would ever exist.

    Enrichment does NOT happen here any more; see `enrich_eu_calls`. Asking the
    search index about all ~650 survivors would be ~650 POSTs a run in place of
    today's ~24, so it is driven by what actually matched instead.

    `dataset_path` bypasses the download entirely — that is how the tests drive
    this against a captured fixture without a network stub for a 130 MB body.
    """
    recorder = recorder or Recorder(None)

    with tempfile.TemporaryDirectory(prefix="funding-radar-") as scratch:
        if dataset_path is None:
            dataset_path = fetch_eu_reference(
                session,
                Path(scratch) / "grantsTenders.json",
                recorder=recorder,
                cache_dir=cache_dir,
            )

        seen = 0
        grants = 0
        open_or_forthcoming = 0
        unexpired = 0
        calls: list[FundingCall] = []

        for record in iter_eu_opportunities(dataset_path):
            seen += 1

            if record.get("type") != CONFIG["eu_grant_type"]:
                continue
            grants += 1

            status = (record.get("status") or {}).get("abbreviation")
            if status not in CONFIG["eu_statuses"]:
                continue
            open_or_forthcoming += 1

            deadline, expired = _eu_deadline(record)
            if expired:
                continue
            unexpired += 1

            identifier = str(record.get("identifier") or "").strip()
            if not identifier:
                continue

            # reason: the matching surfaces are built from the RAW record, not
            # from the shortened title below. `_eu_matches()` searched the full
            # `record["title"]`, which runs to 323 characters in the live
            # dataset; building the surface from the 200-character display title
            # would silently stop matching any term past that cut, and the loss
            # would look like a call that simply was not relevant.
            full_title = str(record.get("title") or "")
            call_title = str(record.get("callTitle") or "")

            calls.append(
                FundingCall(
                    source="eu_sedia",
                    # reason: the call_id prefix stays "eu_sedia" even though
                    # discovery moved to the reference dataset. It is the key in
                    # seen_calls.json, calls.json and triage.json; renaming it
                    # would re-report every EU call as new and orphan the triage
                    # state the office has already written against it.
                    call_id=f"eu_sedia:{identifier}",
                    # Titles run to 323 characters in the live dataset, which
                    # takes a digest line off the page the way `alocare` did.
                    title=_shorten(full_title.strip(), 200) or "(no title)",
                    deadline=deadline,
                    announced=status == "Forthcoming",
                    programme=_eu_programme(record),
                    link=_eu_topic_url(identifier),
                    # No source vocabulary to seed these with. `tags` and
                    # `keywords` on an EU record are a ~40-term marketing dump
                    # ("opportunities", "funding", "partners") and matching them
                    # turned an invasive-species call into a mental-health hit,
                    # so they are neither stored nor matched. Everything in
                    # `tags` for an EU call arrives from apply_match.
                    tags=[],
                    lang="en",
                    # CORE searched title + callTitle: the topic's own name and
                    # its parent call's. WIDE searched the title alone.
                    search_core=f"{full_title} {call_title}".lower(),
                    search_wide=full_title.lower(),
                    # The EU dataset publishes no applicant vocabulary at all.
                    # Empty is "unknown", which match.py does not filter on —
                    # not "open to nobody", which would drop the entire feed.
                    eligible_as=[],
                    raw={
                        "identifier": identifier,
                        "callIdentifier": record.get("callIdentifier"),
                        "callTitle": call_title,
                        "status": status,
                        # Every cutoff, not just the next one. `_eu_deadline`
                        # keeps the next date ahead because that is what a
                        # digest line needs; the rest are facts about the call
                        # and are cheap to keep now that nothing deletes rows.
                        "deadlines": record.get("deadlineDatesLong"),
                    },
                )
            )

    recorder.funnel(
        "eu",
        records=seen,
        grants=grants,
        open_or_forthcoming=open_or_forthcoming,
        deadline_ahead=unexpired,
        # reason: `keyword_matched` was one organisation's gate and is no longer
        # applied here. The per-org funnel is recorded where the decision now
        # happens — see main().
        emitted=len(calls),
    )
    log.info("EU Funding & Tenders Portal: %d live grant(s) collected", len(calls))
    return calls


def enrich_eu_calls(
    session: requests.Session,
    calls: list[FundingCall],
    recorder: Recorder | None = None,
) -> None:
    """Ask the search index for a budget and a canonical URL, once per call.

    Driven by what MATCHED rather than by what was collected. Discovery now
    keeps ~650 live grants where it used to keep 24, and the index is one small
    POST per topic — so enriching everything would multiply this run's outbound
    traffic by twenty-seven for data that, for most of those calls, no
    organisation has asked to see.

    `enrich_eu_call` still never raises: a search-index failure costs a budget
    line, not a call. That asymmetry is the whole reason discovery and
    enrichment are separate halves.
    """
    for call in calls:
        enrich_eu_call(session, call, call.call_id.split(":", 1)[1], recorder=recorder)


# ---------------------------------------------------------------------------
# RELEVANCE — the step that used to live inside the two fetchers
# ---------------------------------------------------------------------------

def apply_profile(
    calls: list[FundingCall],
    profile: dict,
    recorder: Recorder | None = None,
) -> list[FundingCall]:
    """Ask one organisation's question of a collected inventory.

    This exists as a named function rather than a block inside `main()` because
    it is the seam the whole restructure turns on, and a test that re-implements
    it is a test that can agree with a broken pipeline. Everything above this
    line collects; nothing above it knows what any organisation cares about.

    Matching runs against `to_warehouse_row()` — the same payload the warehouse
    receives — so what this returns and what `match.py` later derives from the
    database cannot disagree about a call.

    Returns the matched calls, each with `apply_match` already applied, in the
    matcher's order.
    """
    by_id = {call.call_id: call for call in calls}
    matches = match_all([call.to_warehouse_row() for call in calls], profile)

    matched: list[FundingCall] = []
    for match in matches:
        call = by_id[match.call_id]
        call.apply_match(match)
        matched.append(call)

    if recorder is not None:
        recorder.funnel(
            "match",
            collected=len(calls),
            matched=len(matched),
            core=sum(1 for m in matches if m.tier == "core"),
            wide=sum(1 for m in matches if m.tier == "wide"),
        )
    log.info("Export profile matched %d of %d collected call(s)", len(matched), len(calls))
    return matched


# ---------------------------------------------------------------------------
# DEDUPLICATION / "ONLY REPORT WHAT'S NEW" STATE
# ---------------------------------------------------------------------------

def load_seen_ids(path: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")))


def save_seen_ids(path: str, ids: Iterable[str]) -> None:
    # Atomic, for the same reason calls.json is: a half-written seen store is
    # not a detectable error, it just re-reports everything next run.
    atomic_write_text(path, json.dumps(sorted(set(ids)), ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# DIGEST GENERATION
# ---------------------------------------------------------------------------

def build_digest(new_calls: list[FundingCall]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    if not new_calls:
        return f"# Funding Radar — {today}\n\nNo new matching calls this run.\n"

    by_source: dict[str, list[FundingCall]] = {}
    for call in new_calls:
        by_source.setdefault(call.source, []).append(call)

    lines = [f"# Funding Radar — {today}", ""]
    lines.append(f"{len(new_calls)} new call(s) matched this run.\n")

    source_labels = {
        "adieuronest": "Romania national / RO-MD-UA cross-border (adieuronest.ro)",
        "eu_sedia": "EU-wide centrally-managed programmes (Funding & Tenders Portal)",
    }

    for source, source_calls in by_source.items():
        lines.append(f"## {source_labels.get(source, source)}")
        lines.append("")
        for call in source_calls:
            lines.append(f"- {call.digest_line()}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GITHUB ISSUE DELIVERY (the only notification path — no Slack, no Telegram)
# ---------------------------------------------------------------------------

def create_github_issue(digest_text: str, new_call_count: int) -> None:
    """
    Opens a GitHub Issue with the digest as the body. GitHub automatically emails
    everyone "watching" the repo — no SMTP credentials, no chat integration needed.
    Requires GITHUB_TOKEN and GITHUB_REPOSITORY, both auto-provided inside GitHub
    Actions when the workflow grants `issues: write` permission.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        log.warning("GITHUB_TOKEN or GITHUB_REPOSITORY not set — skipping issue creation.")
        return

    if new_call_count == 0:
        log.info("No new calls — skipping issue creation (no noise for a no-op run).")
        return

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "title": f"Funding Radar: {new_call_count} new call(s) — {datetime.now().strftime('%Y-%m-%d')}",
        "body": digest_text,
        "labels": CONFIG["github_issue_labels"],
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    log.info("GitHub Issue created: %s", response.json().get("html_url"))


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--create-issue",
        action="store_true",
        help="Open a GitHub Issue with the digest (only meaningful inside GitHub Actions).",
    )
    parser.add_argument(
        "--source",
        choices=("all", "adieuronest", "eu"),
        default="all",
        help="Run a single source in isolation. Default: all.",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="Read and write no state at all — no seen_calls.json, no calls.json, "
             "no digest file. Use this to verify a source without poisoning the "
             "next scheduled run.",
    )
    parser.add_argument(
        "--evidence",
        metavar="DIR",
        help="Write a provenance manifest (URLs, status codes, sha256 of the exact "
             "bytes parsed, upstream Date/ETag) plus bounded raw samples to DIR.",
    )
    parser.add_argument(
        "--evidence-full",
        action="store_true",
        help="Persist complete raw bodies in the evidence directory. Off by default: "
             "the EU reference dataset is ~130 MB.",
    )
    parser.add_argument(
        "--cache-dir",
        metavar="DIR",
        help="Keep the EU reference dataset here and revalidate it with a conditional "
             "GET. Off by default, so the default run always downloads a fresh body.",
    )
    args = parser.parse_args()

    if args.create_issue and args.no_state:
        parser.error("--no-state and --create-issue are contradictory: a verification "
                     "run must not notify the office.")

    session = create_resilient_session()
    recorder = Recorder(args.evidence, full_bodies=args.evidence_full)

    # Unconfigured — locally, and in any test — this is a fully working no-op:
    # every method below returns as if on an empty result and nothing is sent.
    # That is the Recorder(None) contract, and it is why wiring the warehouse in
    # here cannot change what this run does.
    #
    # `--no-state` deliberately does NOT disable it. That flag protects
    # seen_calls.json and calls.json, because a verification run that wrote them
    # would suppress the next scheduled run's alerts. The warehouse is not that
    # kind of state: upsert-plus-sweep is idempotent, it does not feed the
    # new-call diff, and a verification run putting fresh rows in it is the
    # correct outcome rather than a poisoned one.
    warehouse = Warehouse(
        url=os.environ.get("SUPABASE_URL"),
        service_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        session=session,
        recorder=recorder,
        user_agent=CONFIG["user_agent"],
    )

    all_calls: list[FundingCall] = []
    # reason: owned_sources drives merge_calls, which DELETES every row of a
    # source it is given. A source that failed returned no rows, so naming it
    # here would erase its rows from calls.json while the run still exits 0 —
    # the silent-green failure fixed for mipe_watch in 6712dfe. Only sources
    # that actually succeeded may be replaced.
    succeeded: set[str] = set()
    attempted: set[str] = set()

    if args.source in ("all", "adieuronest"):
        attempted.add("adieuronest")
        try:
            all_calls.extend(fetch_adieuronest_calls(session, recorder=recorder))
            succeeded.add("adieuronest")
        except (requests.RequestException, ValueError) as exc:
            log.error("adieuronest.ro fetch failed: %s", exc)

    if args.source in ("all", "eu"):
        attempted.add("eu_sedia")
        try:
            all_calls.extend(
                fetch_eu_calls(
                    session,
                    recorder=recorder,
                    cache_dir=Path(args.cache_dir) if args.cache_dir else None,
                )
            )
            succeeded.add("eu_sedia")
        except (requests.RequestException, ValueError, OSError) as exc:
            log.error("EU Funding & Tenders Portal fetch failed: %s", exc)

    # -- relevance, which is now a separate step from collection ------------
    # Everything above collected calls. Nothing above knows what an
    # organisation cares about; `all_calls` is ~650 EU grants and ~1,100
    # Romanian rows, the whole live inventory. This is where one organisation's
    # question gets asked of it, and the answer drives the digest, the Issue and
    # calls.json — the three surfaces that belong to that one organisation.
    #
    # The profile comes from the warehouse when EXPORT_ORG_ID names an org
    # there, so editing it in the database changes what this export contains.
    # SEED_PROFILE is the bootstrap for a machine with no database, not a
    # second copy that can drift from one.
    profile = export_profile(warehouse)
    matched_calls = apply_profile(all_calls, profile, recorder=recorder)

    # Enrichment is driven by what matched, not by what was collected: the
    # search index is one POST per topic, and asking it about all ~650 live
    # grants would multiply this run's outbound traffic twenty-sevenfold for
    # budget lines nobody has asked to see.
    enrich_eu_calls(
        session,
        [call for call in matched_calls if call.source == "eu_sedia"],
        recorder=recorder,
    )

    seen_ids = set() if args.no_state else load_seen_ids(CONFIG["seen_store_path"])
    new_calls = [call for call in matched_calls if call.call_id not in seen_ids]

    log.info(
        "Total matched: %d | Already seen: %d | New: %d",
        len(matched_calls),
        len(matched_calls) - len(new_calls),
        len(new_calls),
    )

    digest_text = build_digest(new_calls)

    if args.no_state:
        # Nothing is written anywhere. The digest goes to stdout so the run is
        # still inspectable, and neither state file is touched.
        log.info("--no-state: nothing written. Digest follows.")
        print(digest_text)
    else:
        output_path = CONFIG["digest_output_path"].format(date=datetime.now().strftime("%Y-%m-%d"))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_path, digest_text)
        log.info("Digest written to: %s", output_path)

        # reason: MATCHED ids, not every collected id. The seen store answers
        # "has the office been told about this call", and the office is only
        # told about matches. Recording all ~1,750 collected ids here would mean
        # that widening the export profile later surfaces nothing: every newly
        # relevant call would already be marked seen and would never appear in a
        # digest. Under the old single-tenant shape the two sets were identical,
        # because collection *was* matching.
        save_seen_ids(CONFIG["seen_store_path"], seen_ids | {c.call_id for c in matched_calls})

        # The dashboard feed. Written on every run, including a run with nothing
        # new, so the UI reflects calls dropping off their source as well as
        # appearing. Only sources that succeeded on THIS run are replaced;
        # mipe_watch's rows, and a failed source's rows, survive untouched.
        total = write_source_calls(
            [call.to_record() for call in matched_calls if call.source in succeeded],
            owned_sources=succeeded,
        )
        log.info("calls.json now holds %d call(s) across all sources", total)

    # -- the warehouse ------------------------------------------------------
    # Same invariant as owned_sources above, one storage layer along. Upsert
    # first so every row this run returned carries this run's id, THEN sweep:
    # the sweep is "everything from this source not stamped with this run",
    # which is a single statement only because the upsert already happened.
    rows_by_source: dict[str, int] = {}
    for call in all_calls:
        rows_by_source[call.source] = rows_by_source.get(call.source, 0) + 1

    # reason: to_warehouse_row(), not to_record(). The warehouse row carries the
    # matching surfaces (`lang`, `search_core`, `search_wide`, `eligible_as`)
    # and the untrimmed `raw`; the calls.json record deliberately does not, so
    # ~2 MB of eligibility prose stays out of a browser download. Writing
    # to_record() here lands every row with an empty surface, and match.py then
    # returns zero matches for every organisation — silently, because an
    # unmatched call and an unmatchable one look identical from the outside.
    # test_what_main_upserts_still_matches_after_the_round_trip is the guard.
    #
    # ALL collected calls, not just the matched ones. The warehouse is the
    # organisation-agnostic half; a call this export profile rejected is exactly
    # what a second organisation is here to find.
    warehouse.upsert_calls([call.to_warehouse_row() for call in all_calls])
    # reason: `succeeded`, never `attempted`. A failed source returned no rows,
    # so sweeping it would mark its entire live inventory withdrawn while the
    # run still exits 0 — the same silent-green failure `owned_sources` guards
    # against above, and the one fixed for mipe_watch in 6712dfe. A failed
    # source is upserted-not-swept: its rows keep their previous
    # last_seen_run_id, stay open, and are simply not refreshed this run.
    for source in sorted(succeeded):
        warehouse.sweep_withdrawn(source, rows_by_source.get(source, 0))
    # Expiry is source-independent — a passed deadline is a fact about the call,
    # not about whether anyone fetched it — so it runs outside the loop and is
    # not gated on `succeeded`.
    warehouse.sweep_expired()

    recorder.write()

    if args.create_issue:
        create_github_issue(digest_text, len(new_calls))

    if attempted and not succeeded:
        # reason: exiting 0 here made a total outage look like a quiet week.
        log.error("Every requested source failed — failing the run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
