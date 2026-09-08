#!/usr/bin/env python3
"""
MIPE Calendar Watcher — Vertical Freedom
=========================================

MIPE (Ministerul Investițiilor și Proiectelor Europene) publishes its estimated
call calendar as a plain webpage/PDF, with no API and no RSS feed. This script
does the only thing that IS reliable for a source like that: it fetches each
watched page, hashes the text content, and compares that hash to the last known
one (stored in a small JSON file committed back to the repo by the GitHub
Actions workflow).

Behaviour, exactly as specified:
  - If the page's content hash is UNCHANGED since last run -> log a plain
    "no change" line internally. Nothing else happens. No noise.
  - If the page's content hash HAS CHANGED -> open a GitHub Issue flagging it
    as something that needs a human to look at and (if relevant) add to the
    funding_radar seen/tracked list manually.

Delivery is GitHub Issues only — no Slack, no Telegram, no email/SMTP.

This deliberately does NOT try to parse the PDF/page into structured data —
that content isn't machine-readable in a stable way, so a change-detection
alert plus a human review step is the realistic, low-maintenance approach.

Requests use a retry-with-backoff session (5 attempts, exponential backoff,
honors Retry-After) since mfe.gov.ro publishes no documented rate limit.

Requires: pip install requests beautifulsoup4

Local run (just logs, does not open a GitHub Issue):
    python mipe_watch.py

Inside GitHub Actions (opens an Issue on change):
    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo python mipe_watch.py --create-issue
"""

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from calls_store import atomic_write_text, write_source_calls
from provenance import Recorder, sha256_of
from warehouse import Warehouse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("mipe_watch")

# ---------------------------------------------------------------------------
# CONFIGURATION — one entry per page you want watched.
# ---------------------------------------------------------------------------

WATCHED_PAGES = {
    "calendar_apeluri_general": "https://mfe.gov.ro/calendar-apeluri-de-proiecte/",
    # NOTE: add the specific managing-authority calendar subpages once you've
    # confirmed their exact URLs — e.g. the ones for Programul Incluziune și
    # Demnitate Socială and Programul Regional Nord-Vest, which are more
    # directly relevant to Vertical Freedom's mission than the general page.
    # "incluziune_si_demnitate_sociala": "https://mfe.gov.ro/.../calendar-apeluri-de-proiecte/",
    # "programul_regional_nord_vest": "https://mfe.gov.ro/.../calendar-apeluri-de-proiecte/",
}

# Romanian display names for the dashboard; the keys above are storage ids.
PAGE_LABELS = {
    "calendar_apeluri_general": "Calendar apeluri de proiecte",
}

HASH_STORE_PATH = "mipe_page_hashes.json"
GITHUB_ISSUE_LABELS = ["mipe-watch"]


def _user_agent() -> str:
    """The contact string every outbound request carries.

    A User-Agent is a contact address for whoever operates the crawler, and this
    crawler serves the whole warehouse rather than any one organisation — so it
    names the repository, not a tenant. Putting one org's office address on a
    request to mfe.gov.ro is the identity leak most visible from outside this
    repo, and the hardest to withdraw once it is in someone's access log.

    `GITHUB_REPOSITORY` is set automatically inside Actions. Locally it is
    absent and the bare product string is sent: an invented URL would be worse
    than no URL, because a contact address that goes nowhere is not a contact
    address. `funding_radar.py` carries a copy of this — four lines duplicated,
    in keeping with "every other shared helper is duplicated by design"; a
    fourth shared module for a string is not a trade worth making.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo:
        return f"FundingRadar/1.0 (+https://github.com/{repo})"
    return "FundingRadar/1.0"


USER_AGENT = _user_agent()

RETRY_TOTAL = 5
RETRY_BACKOFF_FACTOR = 2   # sleeps ~2s, 4s, 8s, 16s, 32s between attempts


# ---------------------------------------------------------------------------
# RESILIENT HTTP SESSION — retries on 429/5xx, honors Retry-After, backs off
# exponentially with jitter. mfe.gov.ro publishes no documented rate limit,
# so this is the defensive default.
# ---------------------------------------------------------------------------

def create_resilient_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    retry_strategy = Retry(
        total=RETRY_TOTAL,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=RETRY_BACKOFF_FACTOR,
        backoff_jitter=1,
        respect_retry_after_header=True,
        allowed_methods=["GET", "POST"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ---------------------------------------------------------------------------
# HASHING
# ---------------------------------------------------------------------------

def normalized_text_hash(html: str) -> str:
    """
    Strips markup and collapses whitespace before hashing, so the hash only
    changes when the actual visible text changes — not on every irrelevant
    markup/whitespace tweak the page's CMS might make.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(separator=" ").split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_hashes(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_hashes(path: str, hashes: dict) -> None:
    # Atomic: a truncated hash map reads as "first check" for every page it lost,
    # which silently skips a change-detection cycle rather than erroring.
    atomic_write_text(path, json.dumps(hashes, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# GITHUB ISSUE DELIVERY (the only notification path — no Slack, no Telegram)
# ---------------------------------------------------------------------------

def create_github_issue(changed_pages: list[str]) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        log.warning("GITHUB_TOKEN or GITHUB_REPOSITORY not set — skipping issue creation.")
        return

    if not changed_pages:
        log.info("No pages changed — skipping issue creation (no noise for a no-op run).")
        return

    lines = [
        "The following MIPE calendar page(s) changed since the last check:",
        "",
    ]
    for name in changed_pages:
        lines.append(f"- **{name}**: {WATCHED_PAGES[name]}")
    lines.append("")
    lines.append(
        "Please open the page, check what changed, and — if it's a new relevant "
        "call — add it manually to the Funding Radar tracker."
    )

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "title": f"MIPE calendar changed — {datetime.now().strftime('%Y-%m-%d')}",
        "body": "\n".join(lines),
        "labels": GITHUB_ISSUE_LABELS,
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
        help="Open a GitHub Issue if any watched page changed (meaningful inside GitHub Actions).",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="Read and write no state — no mipe_page_hashes.json, no calls.json. "
             "Every page reads as a first check, so nothing is reported as changed; "
             "use this to verify the fetch itself without disturbing the baseline.",
    )
    parser.add_argument(
        "--evidence",
        metavar="DIR",
        help="Write a provenance manifest (URLs, status codes, sha256 of the exact "
             "bytes hashed, upstream Date/ETag) plus bounded raw samples to DIR.",
    )
    parser.add_argument(
        "--evidence-full",
        action="store_true",
        help="Persist complete raw page bodies in the evidence directory.",
    )
    args = parser.parse_args()

    if args.create_issue and args.no_state:
        parser.error("--no-state and --create-issue are contradictory: a verification "
                     "run must not notify the office.")

    session = create_resilient_session()
    recorder = Recorder(args.evidence, full_bodies=args.evidence_full)

    # Unconfigured, this is a fully working no-op — same contract as
    # Recorder(None). See the block in funding_radar.main() for why --no-state
    # does not gate it.
    warehouse = Warehouse(
        url=os.environ.get("SUPABASE_URL"),
        service_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        session=session,
        recorder=recorder,
        user_agent=USER_AGENT,
    )

    previous_hashes = {} if args.no_state else load_hashes(HASH_STORE_PATH)

    # reason: seeding from previous_hashes (instead of starting empty) keeps the
    # stored baseline for any page that fails to fetch this run. Starting empty
    # wrote the failed page's hash out of existence, so the next run treated it
    # as a first check and silently skipped one change-detection cycle.
    # Only keys still in WATCHED_PAGES are carried over, so removing a watched
    # page still prunes its stale hash.
    current_hashes = {
        name: h for name, h in previous_hashes.items() if name in WATCHED_PAGES
    }
    changed_pages = []
    failed_pages = []

    for name, url in WATCHED_PAGES.items():
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            log.error("Failed to fetch %s (%s): %s", name, url, exc)
            failed_pages.append(name)
            continue

        body = response.content
        recorder.http(
            source=f"mipe:{name}",
            method="GET",
            url=response.url,
            status=response.status_code,
            response_bytes=len(body),
            # reason: this is the sha256 of the RAW bytes, which is what someone
            # re-fetching can reproduce. The page hash below is deliberately a
            # different digest — over the normalised visible text — because that
            # is what change detection has to be insensitive to markup for.
            sha256=sha256_of(body),
            request_headers=dict(response.request.headers) if response.request else None,
            response_headers=dict(response.headers),
            sample=recorder.body_for_evidence(body),
        )

        new_hash = normalized_text_hash(response.text)
        current_hashes[name] = new_hash

        old_hash = previous_hashes.get(name)

        if old_hash is None:
            log.info("First check for '%s' — baseline hash recorded, no comparison yet.", name)
        elif old_hash == new_hash:
            log.info("No change: '%s'", name)
        else:
            log.info("CHANGE DETECTED: '%s' (%s)", name, url)
            changed_pages.append(name)

    # A MIPE row is a change-alert, not a funding call: it has no deadline and
    # no budget, and stays in the feed until a human resolves it. Only pages
    # that actually changed become rows — an unchanged page is not news, and a
    # page whose fetch failed has nothing to say either way.
    change_rows = [
        {
            "call_id": f"mipe:{name}",
            "source": "mipe",
            "title": f"{PAGE_LABELS.get(name, name)} — calendar modificat",
            "programme": "MIPE",
            "deadline": None,
            "announced": False,
            "budget": "",
            "tags": ["pagină modificată"],
            "match_reason": "text modificat",
            "link": WATCHED_PAGES[name],
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
        }
        for name in changed_pages
    ]

    if args.no_state:
        log.info("--no-state: nothing written, no page hash stored, no feed row.")
    else:
        save_hashes(HASH_STORE_PATH, current_hashes)

        write_source_calls(
            change_rows,
            owned_sources={"mipe"},
            # reason: this script reports only the pages that changed on this run, so
            # a quiet day passes an empty list. Replacing would delete every
            # outstanding alert the moment a page stopped changing.
            replace=False,
        )

    # The warehouse gets the same rows and, deliberately, NO sweep. There is no
    # `sweep_withdrawn` call anywhere in this file and there must never be one:
    # this watcher reports only the pages that changed, so absence from a run
    # means "no change", not "gone". A sweep here would withdraw every
    # outstanding alert on the first quiet day — the warehouse expression of
    # exactly the same defect `replace=False` prevents above. That asymmetry
    # between the two watchers is the ownership contract, not an oversight.
    warehouse.upsert_calls(change_rows)

    recorder.funnel(
        "mipe",
        watched=len(WATCHED_PAGES),
        fetched=len(WATCHED_PAGES) - len(failed_pages),
        changed=len(changed_pages),
    )
    recorder.write()

    if args.create_issue:
        create_github_issue(changed_pages)
    elif changed_pages:
        log.info("Changed pages this run: %s", ", ".join(changed_pages))
    else:
        log.info("No pages changed this run.")

    # reason: a run where every page failed to fetch used to log the errors and
    # exit 0, so it was reported as a green, quiet run — indistinguishable from
    # "nothing changed", which is exactly the state this watcher exists to
    # detect. mfe.gov.ro drops packets from GitHub's IP ranges, so this went
    # unnoticed for a full run. State handling above is unchanged (baselines are
    # kept, no Issue, no feed rows); only the exit code now tells the truth.
    # A partial failure stays green: the pages that did fetch were still checked.
    if WATCHED_PAGES and len(failed_pages) == len(WATCHED_PAGES):
        log.error(
            "Every watched page failed to fetch (%s) — this run checked nothing.",
            ", ".join(failed_pages),
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
