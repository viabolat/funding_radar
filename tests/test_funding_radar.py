"""Tests for funding_radar.py.

Both parsers are now pinned to payloads captured from the live sources
(tests/fixtures/), not to guessed field names. Every regression below was a real
defect found by diffing the parsers against those live responses.
"""

import json
from datetime import datetime, timedelta

import pytest
import requests

import calls_store as cs
import funding_radar as fr


# ---------------------------------------------------------------------------
# adieuronest CSV source — real header, real rows
# ---------------------------------------------------------------------------

REAL_HEADER = (
    "id,titlu,program,cod,tip,stare,tara,si_md,si_ua,regiune,nord_est,categorii,"
    "solicitanti,finanteaza,conditii,valoare_min,valoare_max,alocare,cofinantare,"
    "deschidere,termen,termen_iso,depunere,url,ghid_url,fisa_url,adaugat,"
    "verificat_la,stadiu,sursa\n"
)


def csv_row(**overrides):
    """Builds one row against the real 30-column header."""
    values = {name: "" for name in REAL_HEADER.strip().split(",")}
    values.update(
        {"id": "slug-1", "titlu": "Titlu", "categorii": "ong", "stare": "activ"}
    )
    values.update(overrides)
    return ",".join(f'"{values[name]}"' for name in REAL_HEADER.strip().split(",")) + "\n"


def feed(*rows, bom=True):
    body = REAL_HEADER + "".join(rows)
    return ("﻿" + body if bom else body).encode("utf-8")


def fetch_csv(fake_session, fake_response, payload):
    session = fake_session(
        {fr.CONFIG["adieuronest_csv_url"]: fake_response(content=payload)}
    )
    return fr.fetch_adieuronest_calls(session)


def test_utf8_bom_does_not_swallow_the_id_column(fake_session, fake_response):
    """Regression: decoding as plain utf-8 left the first header as '\\ufeffid',
    so row.get('id') was always None and calls fell through to a URL-derived id.
    On the live feed that collapsed 495 calls onto 464 ids — 31 never reported."""
    payload = feed(csv_row(id="my-slug", titlu="Program cancer", url="http://a"), bom=True)

    calls = fetch_csv(fake_session, fake_response, payload)

    assert [c.call_id for c in calls] == ["adieuronest:my-slug"]


def test_two_rows_sharing_a_url_keep_distinct_ids(fake_session, fake_response):
    """The collision that lost calls: `cod` is blank on roughly half the feed,
    so an id derived from the URL is not unique."""
    payload = feed(
        csv_row(id="slug-a", titlu="Cancer A", cod="", url="http://shared"),
        csv_row(id="slug-b", titlu="Cancer B", cod="", url="http://shared"),
    )

    calls = fetch_csv(fake_session, fake_response, payload)

    assert len({c.call_id for c in calls}) == 2


def test_deadline_comes_from_termen_iso(fake_session, fake_response):
    """There is no `termen_limita` column; the live names are termen/termen_iso.
    Reading the wrong one left every digest line without a deadline."""
    payload = feed(
        csv_row(titlu="Program cancer", termen="03.09.2026", termen_iso="2026-09-03")
    )

    assert fetch_csv(fake_session, fake_response, payload)[0].deadline == "2026-09-03"


def test_announced_calls_keep_a_clean_date_and_set_the_announced_flag(
    fake_session, fake_response
):
    """The dashboard computes urgency from `deadline`, so the date must stay a
    bare ISO string; "not yet open" rides on the flag and surfaces in the digest
    line and as a tag."""
    payload = feed(csv_row(titlu="Program cancer", stare="anuntat", termen_iso="2026-12-01"))

    call = fetch_csv(fake_session, fake_response, payload)[0]

    assert call.deadline == "2026-12-01"
    assert call.announced is True
    assert "anunțat" in call.tags
    assert "not yet open" in call.digest_line()
    assert call.to_record()["deadline"] == "2026-12-01"


def test_budget_is_built_from_the_money_columns(fake_session, fake_response):
    payload = feed(
        csv_row(
            titlu="Program cancer",
            valoare_min="10 000 EUR",
            valoare_max="50 000 EUR",
            alocare="1 000 000 EUR",
        )
    )

    budget = fetch_csv(fake_session, fake_response, payload)[0].budget

    assert budget == "10 000 EUR – 50 000 EUR / project (total 1 000 000 EUR)"


def test_budget_omits_the_range_when_only_an_allocation_is_published(
    fake_session, fake_response
):
    payload = feed(csv_row(titlu="Program cancer", alocare="500 000 EUR"))

    assert fetch_csv(fake_session, fake_response, payload)[0].budget == "500 000 EUR"


def test_a_prose_allocation_is_truncated(fake_session, fake_response):
    """`alocare` is free text and sometimes holds a whole paragraph, which ran a
    single digest line off the page."""
    payload = feed(
        csv_row(
            titlu="Program cancer",
            alocare=(
                "Bugetul total alocat pentru prezentul apel este de 65.349.654 euro, "
                "din care 48.812.778 euro contributie UE FEDR si FSE+, iar restul "
                "reprezinta cofinantarea de la bugetul national al Romaniei"
            ),
        )
    )

    budget = fetch_csv(fake_session, fake_response, payload)[0].budget

    assert len(budget) <= 140
    assert budget.endswith("…")


def test_closed_calls_are_dropped(fake_session, fake_response):
    """448 of 1162 live rows are anuntat or inchis; a closed call is dead weight."""
    payload = feed(csv_row(titlu="Program cancer", stare="inchis"))

    assert fetch_csv(fake_session, fake_response, payload) == []


def test_calls_an_ngo_cannot_apply_for_are_dropped(fake_session, fake_response):
    """Live `categorii` vocabulary is companii, universitati, autoritati, ong,
    persoane, scoli, cultura, sanatate. A companies-only call is not a lead."""
    payload = feed(csv_row(titlu="Program cancer", categorii="companii"))

    assert fetch_csv(fake_session, fake_response, payload) == []


def test_ngo_eligibility_alone_is_not_enough(fake_session, fake_response):
    """Passing on category alone matched 461 rows of drug trafficking, fisheries
    and vocational training. Relevance is now required as well."""
    payload = feed(csv_row(titlu="Digitalizare industriala", categorii="ong"))

    assert fetch_csv(fake_session, fake_response, payload) == []


def test_core_keyword_matches_anywhere_in_the_record(fake_session, fake_response):
    """The prose lives in solicitanti/finanteaza/conditii — there is no
    `descriere` column. Title-only matching found 54 hits where the full record
    finds 408."""
    payload = feed(
        csv_row(titlu="Apel generic", finanteaza="sprijin pentru pacienti oncologici")
    )

    assert len(fetch_csv(fake_session, fake_response, payload)) == 1


def test_wide_keyword_in_body_prose_is_ignored(fake_session, fake_response):
    """'sănătate' in body prose was the sole reason 32 junk rows passed. The
    text below is the live scope of the PowerUp NetZero innovation call, which
    matched purely on "sănătate animală" — animal health, in a food-safety
    funding scope."""
    payload = feed(
        csv_row(
            titlu="Apel deschis pentru proiecte de inovare PowerUp NetZero",
            finanteaza=(
                "acces pe piete noi; protectia consumatorilor; "
                "siguranta alimentara si sănătate animală; activitati de standardizare"
            ),
        )
    )

    assert fetch_csv(fake_session, fake_response, payload) == []


def test_wide_keyword_in_the_title_still_passes(fake_session, fake_response):
    payload = feed(csv_row(titlu="Fondul de sănătate — Fundația Comunitară Bacău"))

    assert len(fetch_csv(fake_session, fake_response, payload)) == 1


@pytest.mark.parametrize("term", ["sănătate mintal", "sanatate mintal"])
def test_romanian_keywords_match_with_and_without_diacritics(
    term, fake_session, fake_response
):
    payload = feed(csv_row(titlu="Apel generic", finanteaza=f"proiecte de {term}"))

    assert len(fetch_csv(fake_session, fake_response, payload)) == 1


def test_real_feed_sample_is_filtered_as_expected(
    adieuronest_csv_bytes, fake_session, fake_response
):
    """Four unedited rows from the live feed: a cancer call, a closed call, a
    blank-`cod` call, and a companies-only call."""
    calls = fetch_csv(fake_session, fake_response, adieuronest_csv_bytes)

    titles = [c.title for c in calls]
    assert any("Misiunea Cancer" in t for t in titles)
    assert not any("Europa Creativă MEDIA" in t for t in titles)
    assert all(c.call_id.startswith("adieuronest:") for c in calls)
    assert len({c.call_id for c in calls}) == len(calls)


# ---------------------------------------------------------------------------
# EU discovery — the portal's bulk reference dataset
#
# Discovery reads the dataset directly, so these run against a slice of the real
# 129,759,798-byte body rather than against a stubbed search response. Nothing
# here touches the network: fetch_eu_calls takes `dataset_path` for exactly this.
# ---------------------------------------------------------------------------

class OfflineEnrichment:
    """A session whose enrichment POST always fails. Discovery must not care."""

    def __init__(self):
        self.calls = []

    def post(self, url, params=None, files=None, timeout=None):
        self.calls.append((url, params))
        raise requests.RequestException("enrichment unavailable")


def eu_calls(dataset_path, session=None):
    session = session or OfflineEnrichment()
    return fr.fetch_eu_calls(session, dataset_path=dataset_path), session


def eu_ids(dataset_path, session=None):
    calls, _ = eu_calls(dataset_path, session)
    return {call.call_id for call in calls}


def eu_record(dataset_path, identifier):
    for record in fr.iter_eu_opportunities(dataset_path):
        if record.get("identifier") == identifier:
            return record
    raise AssertionError(f"{identifier} is not in the fixture")


def test_procurement_tenders_are_excluded(eu_reference_path):
    """type 0 is a procurement tender (999 in the live dataset), type 1 a grant
    topic (10,161). Vertical Freedom applies for grants; a tender in the digest
    is noise the office cannot act on."""
    assert "eu_sedia:INTPA/2023/EA-RP/0177-PIN" not in eu_ids(eu_reference_path)
    assert any(c.startswith("eu_sedia:HORIZON-MISS") for c in eu_ids(eu_reference_path))


def test_closed_calls_are_dropped_and_forthcoming_kept(eu_reference_path):
    ids = eu_ids(eu_reference_path)
    assert "eu_sedia:AGRIP-MULTI-2021-IM" not in ids
    assert "eu_sedia:HORIZON-MISS-2027-02-CANCER-06" in ids


def test_forthcoming_calls_are_flagged_announced(eu_reference_path):
    calls, _ = eu_calls(eu_reference_path)
    by_id = {c.call_id: c for c in calls}
    assert by_id["eu_sedia:HORIZON-MISS-2027-02-CANCER-06"].announced is True
    assert by_id["eu_sedia:HORIZON-MISS-2026-02-CANCER-05"].announced is False


def test_programme_is_the_named_object_not_an_opaque_id(eu_reference_path):
    calls, _ = eu_calls(eu_reference_path)
    programmes = {c.programme for c in calls}
    assert "Horizon Europe (HORIZON)" in programmes
    assert not any(p.isdigit() for p in programmes), "43108390 is not a programme name"


def test_programme_falls_back_to_the_prefix_map(eu_reference_path):
    """The live dataset always carries frameworkProgramme, but the fallback is
    the only thing standing between a missing object and a blank column, so it
    is exercised against a record with the object removed."""
    record = eu_record(eu_reference_path, "HORIZON-MISS-2026-02-CANCER-05")
    record.pop("frameworkProgramme", None)

    assert fr._eu_programme(record) == fr.EU_PROGRAMME_PREFIXES["HORIZON"]


def test_call_id_keeps_the_eu_sedia_prefix(eu_reference_path):
    """Regression: the prefix is the key in seen_calls.json, calls.json and
    triage.json. Renaming it when discovery moved to the reference dataset would
    have re-reported every EU call as new and orphaned the office's triage."""
    assert "eu_sedia:HORIZON-MISS-2026-02-CANCER-05" in eu_ids(eu_reference_path)


def test_topic_url_is_built_from_the_identifier(eu_reference_path):
    """Regression: grant records carry no `url` field — only tenders do — so a
    link copied straight off the record is always empty."""
    calls, _ = eu_calls(eu_reference_path)
    link = next(c.link for c in calls if c.call_id.endswith("HORIZON-MISS-2026-02-CANCER-05"))

    assert link.endswith("/topic-details/horizon-miss-2026-02-cancer-05")
    assert link.startswith("https://ec.europa.eu/")


def test_core_keywords_match_the_topic_and_its_parent_call(eu_reference_path):
    calls, _ = eu_calls(eu_reference_path)
    tags = next(c.tags for c in calls if c.call_id.endswith("HORIZON-MISS-2026-02-CANCER-05"))

    assert "cancer" in tags
    assert "mental health" in tags


def test_wide_keyword_alone_still_matches_in_a_title(eu_reference_path):
    """"screening" is a WIDE term: signal in a title, noise in body prose."""
    assert "eu_sedia:DIGITAL-2026-AI-PILOTING-10-SCREENING" in eu_ids(eu_reference_path)


def test_context_guard_rejects_a_wide_match_in_the_wrong_domain(eu_reference_path):
    """Regression: "Health of ecosystems and wild species, predictions and
    impacts on human health" matches the WIDE term "human health" and is a
    biodiversity call. Same failure as "sănătate animală" on the Romanian side."""
    assert "eu_sedia:HORIZON-CL6-2027-01-BIODIV-07" not in eu_ids(eu_reference_path)


def test_tags_are_never_matched_against(eu_reference_path):
    """Regression: `tags` is a ~40-term marketing keyword dump. Matching it made
    an invasive-species call hit on "mental health"."""
    record = eu_record(eu_reference_path, "HORIZON-CL6-2027-01-BIODIV-07")
    record["tags"] = ["cancer", "oncology", "palliative"]
    record["keywords"] = ["cancer"]

    assert fr._eu_matches(record) == []


def test_enrichment_failure_keeps_the_call_without_a_budget(eu_reference_path):
    """Discovery already established the call exists and is relevant. A search
    index failure must cost a budget line, not a call — that asymmetry is the
    whole reason discovery and enrichment use different endpoints."""
    calls, session = eu_calls(eu_reference_path)

    assert calls, "every call was dropped when enrichment failed"
    assert all(c.budget == "" for c in calls)
    assert len(session.calls) == len(calls), "one enrichment attempt per matched call"


def test_enrichment_fills_in_the_budget(eu_reference_path, fake_session, fake_response, sedia_payload):
    """The reference dataset carries no money at all; the budget in the digest
    comes from the search index, one POST per matched topic."""
    identifier = sedia_payload["results"][0]["metadata"]["identifier"][0]
    call = fr.FundingCall(source="eu_sedia", call_id=f"eu_sedia:{identifier}", title="t")
    session = fake_session({
        (fr.CONFIG["eu_sedia_url"], f'"{identifier}"'): fake_response(
            json_data=sedia_payload, url="https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        )
    })

    fr.enrich_eu_call(session, call, identifier)

    assert call.budget.startswith("EUR ")


def test_enrichment_prefers_english_over_other_translations(
    eu_reference_path, fake_session, fake_response, sedia_payload
):
    """Regression: every topic is indexed once per translation (up to 23), so
    taking the first result put Spanish topic pages in the digest."""
    identifier = sedia_payload["results"][0]["metadata"]["identifier"][0]
    call = fr.FundingCall(source="eu_sedia", call_id=f"eu_sedia:{identifier}", title="t")
    session = fake_session({
        (fr.CONFIG["eu_sedia_url"], f'"{identifier}"'): fake_response(
            json_data=sedia_payload, url="https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        )
    })

    fr.enrich_eu_call(session, call, identifier)

    assert "/es/" not in call.link


# ---------------------------------------------------------------------------
# Deadline helper — epoch-millisecond lists off the reference dataset
# ---------------------------------------------------------------------------

def ms(date_string):
    from datetime import timezone

    return int(datetime.strptime(date_string, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_multi_cutoff_deadline_picks_the_next_one_still_ahead(eu_reference_path):
    """Regression, against a real multi-cutoff record: EDF-EDIP publishes three
    dates in one list and the EIC Accelerator four. Taking [0] gave a date that
    had already passed."""
    record = eu_record(eu_reference_path, "EDF-EDIP-P-2026-2027-FNLC-SA-SEAP")
    deadline, expired = fr._eu_deadline(record)
    dates = sorted(fr._eu_epoch_to_iso(v) for v in record["deadlineDatesLong"])
    today = datetime.now().strftime("%Y-%m-%d")

    assert expired is False
    assert deadline == next(d for d in dates if d >= today)
    assert deadline != dates[0] or dates[0] >= today


def test_dates_are_read_as_milliseconds_not_seconds():
    """Regression: reading these as seconds puts every deadline in 1970, which
    expires the entire EU feed and looks exactly like "nothing matched"."""
    assert fr._eu_epoch_to_iso(1620691200000) == "2021-05-11"
    assert fr._eu_epoch_to_iso("1620691200000") == "2021-05-11"
    assert fr._eu_epoch_to_iso(None) == ""


def test_a_status_open_call_whose_deadline_passed_is_still_dropped():
    """Regression: EU4H-2024-PJ-03-5 sat at "Open" with a deadline of
    2025-01-21. Status is a claim; the deadline is a date."""
    past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    assert fr._eu_deadline({"deadlineDatesLong": [ms(past)]}) == (past, True)


def test_a_topic_with_no_published_deadline_is_kept():
    """Typical of forthcoming calls — a missing date is not an expired one."""
    assert fr._eu_deadline({}) == ("", False)


# ---------------------------------------------------------------------------
# Streaming download, size ceiling, conditional GET
# ---------------------------------------------------------------------------

def test_download_hashes_the_exact_bytes_it_wrote(tmp_path, fake_session, fake_response):
    """The receipt is worthless unless the digest is over the bytes that were
    actually parsed, so this compares it against hashlib over the file on disk."""
    import hashlib

    body = b'{"fundingData": {"GrantTenderObj": []}}'
    url = fr.CONFIG["eu_reference_url"]
    session = fake_session({url: fake_response(content=body, url=url)})
    dest = tmp_path / "out.json"

    status, sha, size, _ = fr.download_to_file(
        session, url, dest, max_bytes=10_000, timeout=(1, 1)
    )

    assert (status, size) == (200, len(body))
    assert sha == hashlib.sha256(dest.read_bytes()).hexdigest()


def test_download_aborts_past_the_size_ceiling(tmp_path, fake_session, fake_response):
    """An upstream fault — or a redirect to something else entirely — must not
    stream until the runner dies."""
    url = fr.CONFIG["eu_reference_url"]
    session = fake_session({url: fake_response(chunks=[b"x" * 512] * 8, url=url)})

    with pytest.raises(requests.RequestException, match="ceiling"):
        fr.download_to_file(session, url, tmp_path / "out.json", max_bytes=1024, timeout=(1, 1))


def test_conditional_get_reuses_the_cached_dataset(tmp_path, fake_session, fake_response):
    """With --cache-dir, an unchanged dataset costs one 304 and zero bytes."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "grantsTenders.json").write_bytes(b'{"fundingData": {"GrantTenderObj": []}}')
    (cache / "grantsTenders.meta.json").write_text(json.dumps({"etag": '"abc"'}))

    url = fr.CONFIG["eu_reference_url"]
    session = fake_session({url: fake_response(status=304, url=url)})

    path = fr.fetch_eu_reference(session, tmp_path / "unused.json", cache_dir=cache)

    assert path == cache / "grantsTenders.json"
    assert session.request_headers[-1]["If-None-Match"] == '"abc"'


def test_a_response_from_an_unexpected_host_is_refused(fake_response):
    """assert_trusted reads the URL AFTER redirects: whatever comes back is
    parsed, written to calls.json and mailed to the office inside an Issue."""
    with pytest.raises(requests.RequestException, match="unexpected host"):
        fr.assert_trusted(fake_response(url="https://evil.example/grantsTenders.json"))

    with pytest.raises(requests.RequestException, match="non-HTTPS"):
        fr.assert_trusted(fake_response(url="http://ec.europa.eu/x"))


# ---------------------------------------------------------------------------
# Provenance receipts
# ---------------------------------------------------------------------------

def test_manifest_records_a_hash_matching_the_fixture_bytes(
    tmp_path, fake_session, fake_response, adieuronest_csv_bytes
):
    import hashlib

    recorder = fr.Recorder(str(tmp_path / "evidence"))
    url = fr.CONFIG["adieuronest_csv_url"]
    session = fake_session({url: fake_response(content=adieuronest_csv_bytes, url=url)})

    fr.fetch_adieuronest_calls(session, recorder=recorder)
    recorder.write()

    manifest = json.loads((tmp_path / "evidence" / "manifest.json").read_text())
    exchange = manifest["exchanges"][0]

    assert exchange["status"] == 200
    assert exchange["response_bytes"] == len(adieuronest_csv_bytes)
    assert exchange["sha256"] == hashlib.sha256(adieuronest_csv_bytes).hexdigest()
    assert manifest["funnels"][0]["source"] == "adieuronest"


def test_a_receipt_never_carries_an_authorization_header(tmp_path):
    """GITHUB_TOKEN rides in an Authorization header and a receipt is an
    artifact people pass around, so the header list is an allowlist."""
    recorder = fr.Recorder(str(tmp_path / "evidence"))
    recorder.http(
        source="s", method="GET", url="https://ec.europa.eu/x", status=200,
        response_bytes=0, sha256="",
        request_headers={"Authorization": "Bearer secret", "User-Agent": "ua"},
    )
    recorder.write()

    text = (tmp_path / "evidence" / "manifest.json").read_text()
    assert "secret" not in text
    assert "ua" in text


def test_a_recorder_with_no_directory_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = fr.Recorder(None)

    recorder.http(source="s", method="GET", url="u", status=200, response_bytes=1, sha256="x")
    recorder.funnel("s", rows=1)

    assert recorder.write() is None
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Seen-state / dedupe across runs
# ---------------------------------------------------------------------------

def test_seen_ids_round_trip(tmp_path):
    path = tmp_path / "seen.json"
    fr.save_seen_ids(str(path), ["b", "a", "b"])

    assert json.loads(path.read_text()) == ["a", "b"]
    assert fr.load_seen_ids(str(path)) == {"a", "b"}


def test_load_seen_ids_on_missing_file_returns_empty_set(tmp_path):
    assert fr.load_seen_ids(str(tmp_path / "nope.json")) == set()


def test_save_seen_ids_creates_parent_directory(tmp_path):
    fr.save_seen_ids(str(tmp_path / "nested" / "seen.json"), ["x"])

    assert (tmp_path / "nested" / "seen.json").exists()


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def test_digest_says_nothing_new_when_there_are_no_calls():
    assert "No new matching calls this run." in fr.build_digest([])


def test_digest_groups_by_source_with_readable_labels():
    calls = [
        fr.FundingCall(source="adieuronest", call_id="a:1", title="RO call"),
        fr.FundingCall(source="eu_sedia", call_id="e:1", title="EU call"),
    ]

    digest = fr.build_digest(calls)

    assert "2 new call(s) matched this run." in digest
    assert "## Romania national / RO-MD-UA cross-border (adieuronest.ro)" in digest
    assert "## EU-wide centrally-managed programmes (Funding & Tenders Portal)" in digest


def test_digest_line_includes_every_populated_field_and_omits_empty_ones():
    line = fr.FundingCall(
        source="s", call_id="i", title="T", deadline="2026-01-01",
        budget="EUR 1", programme="P", link="http://l",
    ).digest_line()

    assert line.startswith("**T** — _P_ — deadline: 2026-01-01 — budget: EUR 1")
    assert line.endswith("http://l")
    assert fr.FundingCall(source="s", call_id="i", title="T").digest_line() == "**T**"


# ---------------------------------------------------------------------------
# GitHub Issue delivery
# ---------------------------------------------------------------------------

def test_no_issue_is_opened_when_nothing_is_new(monkeypatch, capture_post):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(fr)

    fr.create_github_issue("digest", 0)

    assert posted == []


def test_no_issue_is_opened_without_token_or_repo(monkeypatch, capture_post):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    posted = capture_post(fr)

    fr.create_github_issue("digest", 3)

    assert posted == []


def test_issue_payload_carries_digest_count_and_label(monkeypatch, capture_post):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    posted = capture_post(fr)

    fr.create_github_issue("the digest body", 2)

    assert len(posted) == 1
    assert posted[0]["url"] == "https://api.github.com/repos/o/r/issues"
    assert posted[0]["headers"]["Authorization"] == "Bearer t"
    assert posted[0]["json"]["body"] == "the digest body"
    assert posted[0]["json"]["title"].startswith("Funding Radar: 2 new call(s)")
    assert posted[0]["json"]["labels"] == fr.CONFIG["github_issue_labels"]


# ---------------------------------------------------------------------------
# End-to-end main()
# ---------------------------------------------------------------------------

EMPTY_DATASET = b'{"fundingData": {"GrantTenderObj": []}}'


def main_routes(fake_response, csv_payload=None, eu=EMPTY_DATASET):
    """The two URLs main() reaches for. The EU side defaults to an empty
    dataset envelope so a test about the CSV side triggers no enrichment POSTs
    it would then have to route."""
    routes = {}
    eu_url = fr.CONFIG["eu_reference_url"]
    routes[eu_url] = eu if isinstance(eu, Exception) else fake_response(content=eu, url=eu_url)
    if csv_payload is not None:
        csv_url = fr.CONFIG["adieuronest_csv_url"]
        routes[csv_url] = (
            csv_payload if isinstance(csv_payload, Exception)
            else fake_response(content=csv_payload, url="https://adieuronest.ro/finantari.csv")
        )
    return routes

def test_main_reports_only_new_calls_and_records_every_fetched_id(
    tmp_path, monkeypatch, fake_session, fake_response, capture_post
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr("sys.argv", ["funding_radar.py", "--create-issue"])

    payload = feed(csv_row(id="slug-100", titlu="Sprijin pacienti cancer", url="http://c"))
    routes = main_routes(fake_response, payload)
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    posted = capture_post(fr)

    fr.main()
    assert len(posted) == 1
    assert "Sprijin pacienti cancer" in posted[0]["json"]["body"]
    assert fr.load_seen_ids(fr.CONFIG["seen_store_path"]) == {"adieuronest:slug-100"}

    fr.main()
    assert len(posted) == 1, "second run over an unchanged feed must stay silent"


def test_main_survives_a_totally_dead_source(
    tmp_path, monkeypatch, fake_session, fake_response
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py"])

    routes = main_routes(fake_response, requests.RequestException("down"))
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    fr.main()  # must not raise

    from pathlib import Path

    written = Path(
        fr.CONFIG["digest_output_path"].format(date=datetime.now().strftime("%Y-%m-%d"))
    )
    assert "No new matching calls this run." in written.read_text()


def test_main_writes_a_feed_row_per_call(
    tmp_path, monkeypatch, fake_session, fake_response
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py"])

    payload = feed(
        csv_row(
            id="slug-1",
            titlu="Sprijin pacienti cancer",
            program="PNRR",
            url="http://c",
            termen_iso="2026-12-01",
            valoare_max="500 000 EUR",
        )
    )
    routes = main_routes(fake_response, payload)
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    fr.main()

    row = cs.load_calls("calls.json")["adieuronest:slug-1"]
    assert row["title"] == "Sprijin pacienti cancer"
    assert row["programme"] == "PNRR"
    assert row["deadline"] == "2026-12-01"
    assert row["budget"] == "500 000 EUR"
    assert row["link"] == "http://c"
    assert "cancer" in row["tags"]
    assert "cancer" in row["match_reason"]
    assert row["first_seen"]


def test_a_radar_run_does_not_disturb_mipe_rows(
    tmp_path, monkeypatch, fake_session, fake_response
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py"])
    cs.save_calls({"mipe:page": {"call_id": "mipe:page", "source": "mipe"}}, "calls.json")

    routes = main_routes(fake_response, feed())
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    fr.main()

    assert "mipe:page" in cs.load_calls("calls.json")


def test_a_failed_eu_fetch_does_not_delete_the_existing_eu_rows(
    tmp_path, monkeypatch, fake_session, fake_response
):
    """Regression: merge_calls DELETES every row of a source named in
    owned_sources. Naming a source that failed erased all 22 EU rows from
    calls.json and redeployed the dashboard without them, exiting 0 — the
    silent-green failure fixed for mipe_watch in 6712dfe, living in the other
    script."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py"])
    cs.save_calls(
        {"eu_sedia:OLD": {"call_id": "eu_sedia:OLD", "source": "eu_sedia", "first_seen": "2026-01-01"}},
        "calls.json",
    )

    routes = main_routes(
        fake_response,
        feed(csv_row(id="slug-1", titlu="Sprijin pacienti cancer")),
        eu=requests.RequestException("portal down"),
    )
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    fr.main()

    stored = cs.load_calls("calls.json")
    assert "eu_sedia:OLD" in stored, "a failed source must not have its rows replaced"
    assert "adieuronest:slug-1" in stored, "the source that succeeded is still written"


def test_every_source_failing_exits_non_zero(
    tmp_path, monkeypatch, fake_session, fake_response
):
    """A total outage used to be reported as a green, quiet week."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py"])

    routes = main_routes(
        fake_response,
        requests.RequestException("down"),
        eu=requests.RequestException("also down"),
    )
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    with pytest.raises(SystemExit) as exc:
        fr.main()

    assert exc.value.code == 1


def test_source_flag_runs_one_scraper_alone(
    tmp_path, monkeypatch, fake_session, fake_response
):
    """--source is what makes a scraper verifiable in isolation: the other
    source must not be reached at all, not merely produce nothing."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py", "--source", "adieuronest"])

    routes = main_routes(fake_response, feed(csv_row(id="slug-1", titlu="cancer")))
    session = fake_session(routes)
    monkeypatch.setattr(fr, "create_resilient_session", lambda: session)

    fr.main()

    assert [c[1] for c in session.calls] == [fr.CONFIG["adieuronest_csv_url"]]


def test_no_state_writes_nothing_anywhere(
    tmp_path, monkeypatch, fake_session, fake_response, capsys
):
    """A verification run must be incapable of poisoning the next scheduled one:
    running locally normally rewrites seen_calls.json / calls.json in the working
    directory, which suppresses the real run's alerts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py", "--source", "adieuronest", "--no-state"])

    routes = main_routes(fake_response, feed(csv_row(id="slug-1", titlu="Sprijin cancer")))
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    fr.main()

    assert list(tmp_path.rglob("*")) == []
    assert "Sprijin cancer" in capsys.readouterr().out


def test_no_state_refuses_to_open_an_issue(tmp_path, monkeypatch):
    """The two flags are contradictory: a verification run must not notify."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["funding_radar.py", "--no-state", "--create-issue"])

    with pytest.raises(SystemExit) as exc:
        fr.main()

    assert exc.value.code == 2

