#!/usr/bin/env python3
"""
Funding Radar — Vertical Freedom
=================================

Pulls open funding calls from two free, confirmed sources:

  1. adieuronest.ro          -> Romania national + RO/MD/UA cross-border calls (CSV feed)
  2. EU Funding & Tenders     -> Horizon Europe, Erasmus+, LIFE, Digital Europe, EU4Health,
     Portal (SEDIA API)          EIC, and every other centrally-managed EU programme

Filters both for calls relevant to Vertical Freedom's actual mission — holistic
support for cancer patients: complementary/integrative therapies, psychotherapy, emotional
support, nutrition, and prevention — plus general health/mental-health/social-inclusion
terms as a wider net. A Romanian row must be BOTH applicable (NGO-eligible category, not
closed) AND relevant (mission term anywhere, or a broad health term in the title);
matching on the broad terms in body prose produced unusable digests. Remembers what it
has already reported (via seen_calls.json,
committed back to the repo by the GitHub Actions workflow) so re-runs only surface NEW
matches, and opens a GitHub Issue per run when there's something new to report.

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
import io
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from calls_store import write_source_calls

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

CONFIG = {
    "seen_store_path": "seen_calls.json",
    "digest_output_path": "digests/digest_{date}.md",

    "adieuronest_csv_url": "https://adieuronest.ro/finantari.csv",

    # The SEDIA search API rejects GET with 405 — it takes a POST whose query is
    # sent as a multipart file part named "query". Status codes are the portal's
    # own: 31094501 = Forthcoming, 31094502 = Open. Both are worth reporting; a
    # forthcoming call is the one you still have time to prepare for.
    "eu_sedia_url": "https://api.tech.ec.europa.eu/search-api/prod/rest/search",
    "eu_sedia_api_key": "SEDIA",   # fixed public constant, not a personal credential
    "eu_sedia_statuses": ["31094501", "31094502"],
    "eu_sedia_types": ["1", "2", "8"],

    # Every topic is indexed once per translation. Restricting to en+ro cuts the
    # duplicate flood (630 docs -> 43 for "cancer") while keeping far more distinct
    # topics per page than an en-only filter, which drops topics with no English
    # translation. Remaining duplicates are collapsed by identifier below.
    "eu_sedia_languages": ["en", "ro"],
    "eu_sedia_page_size": 100,
    "eu_sedia_max_pages": 3,
    "eu_sedia_language_preference": ["en", "ro"],

    # Multi-word terms are quoted: SEDIA treats an unquoted phrase as loose OR
    # matching, which turned `patient support` into 943 junk hits. Quoting it
    # gives 0 — that phrase simply is not used — while "mental health" gives 9
    # real ones. Zero-hit phrases are kept deliberately: they cost one request
    # and will fire the day such a call appears.
    "eu_sedia_keywords": [
        "cancer",
        "oncology",
        '"cancer patients"',
        '"mental health"',
        '"psychosocial support"',
        '"palliative care"',
        '"integrative medicine"',
        '"complementary medicine"',
        '"health promotion"',
        '"disease prevention"',
        '"social inclusion"',
    ],

    # Vertical Freedom is an NGO, so a call it cannot apply for is not a lead.
    # Live vocabulary of the `categorii` column is exactly:
    # companii, universitati, autoritati, ong, persoane, scoli, cultura, sanatate.
    "adieuronest_eligible_categories": {"ong", "sanatate"},

    # `stare` is one of: activ, anuntat, inchis. Closed calls are dead weight.
    "adieuronest_excluded_stare": {"inchis"},

    # CORE terms are matched against the full record including the long
    # eligibility/funding prose.
    "adieuronest_core_keywords": [
        "cancer",
        "oncolog",
        "tumor",
        "paliativ",
        "terapii complementare",
        "terapii alternative",
        "terapii integrative",
        "abordare holistica",
        "abordare holistă",
        "holistic",
        "psihoterapie",
        "sprijin emotional",
        "sprijin emoțional",
        "sănătate mintal",
        "sanatate mintal",
        "pacient",
        "screening",
        "boli cronice",
        "nutriție",
        "nutritie",
    ],

    # WIDE terms are matched against the TITLE AND PROGRAMME ONLY. These words
    # turn up constantly in generic boilerplate ("beneficiarii din domeniul
    # sănătății pot..."), so full-text matching on them pulled in NetZero
    # innovation and textile-SME calls. In a title they are signal; in the fine
    # print they are noise. This is the dial to turn if the digest gets thin.
    "adieuronest_wide_keywords": [
        "sănătate",
        "sanatate",
        "medical",
        "spital",
        "psiholog",
        "consiliere",
        "prevenție",
        "preventie",
        "incluziune",
        "vindecare",
        "ong",
    ],

    "user_agent": "VerticalFreedom-FundingRadar/1.0 (+office@verticalfreedom.org)",

    "github_issue_labels": ["funding-radar"],

    # Retry/backoff behavior for both HTTP sources.
    "retry_total": 5,
    "retry_backoff_factor": 2,   # sleeps ~2s, 4s, 8s, 16s, 32s between attempts
}

# Prefix -> readable name. `frameworkProgramme` in the API response is an opaque
# numeric id (e.g. 43108390), so the call identifier is the only human-readable
# programme signal available without a second lookup.
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
    return session


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


# ---------------------------------------------------------------------------
# SOURCE 1 — adieuronest.ro
# ---------------------------------------------------------------------------

def _match_reason(matched: list[str]) -> str:
    """Romanian copy for the dashboard's "De ce a apărut" callout — the office's
    working language, per the design handoff."""
    if not matched:
        return ""
    terms = ", ".join(f"„{term}”" for term in matched[:4])
    if len(matched) == 1:
        return f"Cuvânt cheie potrivit {terms}."
    return f"Cuvinte cheie potrivite {terms}."


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


def fetch_adieuronest_calls(session: requests.Session) -> list[FundingCall]:
    """
    Downloads the full CSV feed and keeps a row only when it is BOTH applicable
    (an NGO-eligible category, not already closed) AND relevant (a mission term
    in the full record, or a broader health term in the title).

    Field names below are the live header, confirmed against the real feed:
        id, titlu, program, cod, tip, stare, tara, si_md, si_ua, regiune,
        nord_est, categorii, solicitanti, finanteaza, conditii, valoare_min,
        valoare_max, alocare, cofinantare, deschidere, termen, termen_iso,
        depunere, url, ghid_url, fisa_url, adaugat, verificat_la, stadiu, sursa

    There is no `descriere` column; the prose lives in solicitanti / finanteaza
    / conditii, which is what the CORE keywords are matched against.
    """
    url = CONFIG["adieuronest_csv_url"]
    log.info("Fetching adieuronest.ro CSV feed: %s", url)

    response = session.get(url, timeout=30)
    response.raise_for_status()

    # reason: the feed is served with a UTF-8 BOM. Decoding as plain utf-8 left
    # the first header as "\ufeffid", so row.get("id") was always None and every
    # call silently fell through to a URL-derived id — collapsing 495 calls onto
    # 464 ids, so 31 were never reported at all. utf-8-sig strips the BOM.
    text = response.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    core_keywords = [k.lower() for k in CONFIG["adieuronest_core_keywords"]]
    wide_keywords = [k.lower() for k in CONFIG["adieuronest_wide_keywords"]]
    eligible_categories = CONFIG["adieuronest_eligible_categories"]
    excluded_stare = CONFIG["adieuronest_excluded_stare"]

    calls: list[FundingCall] = []

    for row in reader:
        categories = {
            c.strip().lower()
            for c in (row.get("categorii") or "").split("|")
            if c.strip()
        }
        if not categories & eligible_categories:
            continue

        if (row.get("stare") or "").strip().lower() in excluded_stare:
            continue

        title = (row.get("titlu") or "").strip()
        programme = (row.get("program") or "").strip()

        full_text = " ".join(
            (row.get(f) or "")
            for f in ("titlu", "program", "solicitanti", "finanteaza", "conditii")
        ).lower()
        title_text = f"{title} {programme}".lower()

        matched_core = [kw for kw in core_keywords if kw in full_text]
        matched_wide = [kw for kw in wide_keywords if kw in title_text]

        if not (matched_core or matched_wide):
            continue

        link = (row.get("url") or "").strip()
        # `cod` is blank on roughly half the feed, so it cannot stand alone.
        call_id = (row.get("id") or "").strip() or (row.get("cod") or "").strip() or link or title

        # termen is dd.mm.yyyy; termen_iso is already ISO. Only the ISO form is
        # kept so the dashboard can compare it against today.
        deadline = (row.get("termen_iso") or "").strip()
        announced = (row.get("stare") or "").strip().lower() == "anuntat"

        matched = matched_core + matched_wide
        tags = sorted(set(matched + sorted(categories)))
        if announced:
            tags.append("anunțat")

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
                tags=tags,
                match_reason=_match_reason(matched),
                raw=row,
            )
        )

    log.info("adieuronest.ro: %d matching calls after filtering", len(calls))
    return calls


# ---------------------------------------------------------------------------
# SOURCE 2 — EU Funding & Tenders Portal (SEDIA search API)
# ---------------------------------------------------------------------------

def _sedia_first(metadata: dict, field_name: str) -> str:
    """Every metadata value comes back wrapped in a list."""
    value = metadata.get(field_name)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def _sedia_programme(identifier: str, metadata: dict) -> str:
    """frameworkProgramme is an opaque numeric id, so name the programme from
    the identifier prefix and fall back to the raw id."""
    prefix = identifier.split("-", 1)[0].upper()
    if prefix in EU_PROGRAMME_PREFIXES:
        return EU_PROGRAMME_PREFIXES[prefix]
    return _sedia_first(metadata, "frameworkProgramme")


def _sedia_deadline(metadata: dict) -> tuple[str, bool]:
    """
    Returns (deadline, expired).

    reason: the portal's own `status` field cannot be trusted — topics such as
    EU4H-2024-PJ-03-5 are still flagged 31094502 ("Open") with a deadline that
    passed in January 2025, so filtering on status alone put long-dead calls in
    the digest. The deadline itself is the reliable signal. `deadlineDate` is
    also a LIST for multi-cutoff calls (the EIC Accelerator carries four), so
    this picks the next cutoff still ahead of us rather than the first one.
    """
    values = metadata.get("deadlineDate")
    if isinstance(values, str):
        values = [values]
    if not values:
        # No deadline published yet — typical of forthcoming calls. Keep it.
        return "", False

    today = datetime.now().strftime("%Y-%m-%d")
    dates = sorted(str(v)[:10] for v in values if v)
    upcoming = [d for d in dates if d >= today]

    if upcoming:
        return upcoming[0], False
    return (dates[-1] if dates else ""), True


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


def fetch_eu_sedia_calls(session: requests.Session) -> list[FundingCall]:
    """
    Queries the EU Funding & Tenders Portal search API once per keyword.

    reason: this endpoint answers GET with 405 Method Not Allowed. It requires a
    POST whose filter is uploaded as a multipart part named "query" containing
    JSON; the free-text term and paging stay in the query string. The previous
    GET form failed on every keyword, so the whole EU half of the radar silently
    reported nothing.
    """
    calls: dict[str, FundingCall] = {}
    languages = CONFIG["eu_sedia_language_preference"]

    query = {
        "bool": {
            "must": [
                {"terms": {"type": CONFIG["eu_sedia_types"]}},
                {"terms": {"status": CONFIG["eu_sedia_statuses"]}},
                {"terms": {"language": CONFIG["eu_sedia_languages"]}},
            ]
        }
    }
    query_part = json.dumps(query)

    for keyword in CONFIG["eu_sedia_keywords"]:
        log.info("Querying EU SEDIA API for keyword: %s", keyword)

        for page in range(1, CONFIG["eu_sedia_max_pages"] + 1):
            params = {
                "apiKey": CONFIG["eu_sedia_api_key"],
                "text": keyword,
                "pageSize": CONFIG["eu_sedia_page_size"],
                "pageNumber": page,
            }

            try:
                response = session.post(
                    CONFIG["eu_sedia_url"],
                    params=params,
                    files={"query": ("query.json", query_part, "application/json")},
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("EU SEDIA request failed for keyword '%s' page %d: %s", keyword, page, exc)
                break

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                metadata = item.get("metadata", {})
                identifier = _sedia_first(metadata, "identifier") or item.get("reference", "")
                if not identifier:
                    continue

                key = f"eu_sedia:{identifier}"
                language = _sedia_first(metadata, "language")

                # The same topic is indexed once per translation. Keep the most
                # preferred language so the digest doesn't come out in Spanish.
                existing = calls.get(key)
                if existing is not None:
                    existing_lang = _sedia_first(existing.raw.get("metadata", {}), "language")
                    if _language_rank(language, languages) >= _language_rank(existing_lang, languages):
                        continue

                deadline, expired = _sedia_deadline(metadata)
                if expired:
                    continue

                # The portal's own keyword list is the best category signal it
                # offers; the identifier is echoed in it, so drop that.
                portal_keywords = [
                    k for k in (metadata.get("keywords") or [])
                    if isinstance(k, str) and not k.startswith(identifier.split("-")[0])
                ]
                search_term = keyword.strip('"')

                calls[key] = FundingCall(
                    source="eu_sedia",
                    call_id=key,
                    title=_sedia_first(metadata, "title"),
                    deadline=deadline,
                    budget=_sedia_budget(metadata, identifier),
                    programme=_sedia_programme(identifier, metadata),
                    link=_sedia_first(metadata, "url") or item.get("url", ""),
                    tags=sorted(set([search_term] + portal_keywords[:6])),
                    match_reason=_match_reason([search_term]),
                    raw=item,
                )

            if len(results) < CONFIG["eu_sedia_page_size"]:
                break

    log.info("EU SEDIA API: %d unique matching calls after merge", len(calls))
    return list(calls.values())


def _language_rank(language: str, preference: list[str]) -> int:
    """Lower is better. Anything unlisted sorts after every preferred language."""
    try:
        return preference.index(language)
    except ValueError:
        return len(preference)


# ---------------------------------------------------------------------------
# DEDUPLICATION / "ONLY REPORT WHAT'S NEW" STATE
# ---------------------------------------------------------------------------

def load_seen_ids(path: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")))


def save_seen_ids(path: str, ids: Iterable[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(set(ids)), ensure_ascii=False, indent=2), encoding="utf-8")


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
    args = parser.parse_args()

    session = create_resilient_session()

    all_calls: list[FundingCall] = []

    try:
        all_calls.extend(fetch_adieuronest_calls(session))
    except requests.RequestException as exc:
        log.error("adieuronest.ro fetch failed: %s", exc)

    try:
        all_calls.extend(fetch_eu_sedia_calls(session))
    except requests.RequestException as exc:
        log.error("EU SEDIA fetch failed: %s", exc)

    seen_ids = load_seen_ids(CONFIG["seen_store_path"])
    new_calls = [call for call in all_calls if call.call_id not in seen_ids]

    log.info(
        "Total fetched: %d | Already seen: %d | New: %d",
        len(all_calls),
        len(all_calls) - len(new_calls),
        len(new_calls),
    )

    digest_text = build_digest(new_calls)

    output_path = CONFIG["digest_output_path"].format(date=datetime.now().strftime("%Y-%m-%d"))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(digest_text, encoding="utf-8")
    log.info("Digest written to: %s", output_path)

    save_seen_ids(CONFIG["seen_store_path"], seen_ids | {c.call_id for c in all_calls})

    # The dashboard feed. Written on every run, including a run with nothing new,
    # so the UI reflects calls dropping off their source as well as appearing.
    # Only this script's two sources are replaced; mipe_watch's rows survive.
    total = write_source_calls(
        [call.to_record() for call in all_calls],
        owned_sources={"adieuronest", "eu_sedia"},
    )
    log.info("calls.json now holds %d call(s) across all sources", total)

    if args.create_issue:
        create_github_issue(digest_text, len(new_calls))


if __name__ == "__main__":
    main()
