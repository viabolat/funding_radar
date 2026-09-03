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
# EU SEDIA source — real response shape
# ---------------------------------------------------------------------------

def sedia_routes(payload, keywords=None):
    url = fr.CONFIG["eu_sedia_url"]
    return {
        (url, kw): payload
        for kw in (keywords or fr.CONFIG["eu_sedia_keywords"])
    }


def fetch_sedia(fake_session, fake_response, payload, only_first_keyword=True):
    empty = fake_response(json_data={"results": []})
    routes = {k: empty for k in sedia_routes(None)}
    routes[(fr.CONFIG["eu_sedia_url"], fr.CONFIG["eu_sedia_keywords"][0])] = fake_response(
        json_data=payload
    )
    session = fake_session(routes)
    return fr.fetch_eu_sedia_calls(session), session


def test_sedia_is_queried_over_post_not_get(fake_session, fake_response, sedia_payload):
    """Regression: the API answers GET with 405 Method Not Allowed, so every
    keyword failed and the entire EU half of the radar silently reported zero."""
    _, session = fetch_sedia(fake_session, fake_response, sedia_payload)

    assert session.calls, "no request was made at all"
    assert {method for method, _, _ in session.calls} == {"POST"}


def test_sedia_query_is_sent_as_a_multipart_json_part(
    fake_session, fake_response, sedia_payload
):
    _, session = fetch_sedia(fake_session, fake_response, sedia_payload)

    name, body, content_type = session.posted_queries[0]
    assert content_type == "application/json"
    must = json.loads(body)["bool"]["must"]
    assert {"terms": {"status": fr.CONFIG["eu_sedia_statuses"]}} in must
    assert {"terms": {"language": fr.CONFIG["eu_sedia_languages"]}} in must


def test_language_variants_of_one_topic_collapse_to_the_preferred_language(
    fake_session, fake_response, sedia_payload
):
    """The same topic is indexed once per translation; without a preference the
    digest came out in whichever language happened to land last (Spanish)."""
    calls, _ = fetch_sedia(fake_session, fake_response, sedia_payload)

    horizon = [c for c in calls if c.call_id.endswith("HORIZON-MISS-2027-02-CANCER-02")]
    assert len(horizon) == 1
    assert horizon[0].title.startswith("Clinical research by Comprehensive Cancer")


def test_expired_topics_are_dropped_despite_being_flagged_open(
    fake_session, fake_response, sedia_payload
):
    """EU4H-2024-PJ-03-5 still carries status 31094502 ("Open") with a deadline
    of 2025-01-21. The portal's status field cannot be trusted."""
    calls, _ = fetch_sedia(fake_session, fake_response, sedia_payload)

    assert not any("EU4H-2024-PJ-03-5" in c.call_id for c in calls)


def test_programme_is_named_not_a_numeric_id(
    fake_session, fake_response, sedia_payload
):
    """frameworkProgramme comes back as an opaque id such as 43108390."""
    calls, _ = fetch_sedia(fake_session, fake_response, sedia_payload)

    assert calls[0].programme == "Horizon Europe"


def test_budget_is_reduced_to_this_topics_contribution_range(
    fake_session, fake_response, sedia_payload
):
    """budgetOverview is a multi-kilobyte JSON blob covering every topic in the
    parent call; dumping it raw made the Issue unreadable."""
    calls, _ = fetch_sedia(fake_session, fake_response, sedia_payload)

    budget = calls[0].budget
    assert budget.startswith("EUR ")
    assert "budgetTopicActionMap" not in budget
    assert "grant(s) expected" in budget


def test_one_failing_keyword_does_not_abort_the_rest(
    fake_session, fake_response, sedia_payload
):
    url = fr.CONFIG["eu_sedia_url"]
    empty = fake_response(json_data={"results": []})
    routes = {(url, kw): empty for kw in fr.CONFIG["eu_sedia_keywords"]}
    routes[(url, fr.CONFIG["eu_sedia_keywords"][0])] = requests.RequestException("boom")
    routes[(url, fr.CONFIG["eu_sedia_keywords"][1])] = fake_response(json_data=sedia_payload)

    calls = fr.fetch_eu_sedia_calls(fake_session(routes))

    assert any("HORIZON-MISS-2027-02-CANCER-02" in c.call_id for c in calls)


def test_result_without_any_identifier_is_skipped(fake_session, fake_response):
    payload = {"results": [{"reference": "", "metadata": {"title": ["no id"]}}]}
    calls, _ = fetch_sedia(fake_session, fake_response, payload)

    assert calls == []


# ---------------------------------------------------------------------------
# Deadline helper
# ---------------------------------------------------------------------------

def test_multi_cutoff_deadline_picks_the_next_one_still_ahead():
    """The EIC Accelerator publishes four cutoffs in one list; taking [0] gave a
    date that had already passed."""
    past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    soon = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    later = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")

    deadline, expired = fr._sedia_deadline(
        {"deadlineDate": [f"{past}T17:00:00.000+0000", f"{later}T17:00:00.000+0000",
                          f"{soon}T17:00:00.000+0000"]}
    )

    assert (deadline, expired) == (soon, False)


def test_all_cutoffs_in_the_past_marks_the_topic_expired():
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    assert fr._sedia_deadline({"deadlineDate": [f"{past}T00:00:00.000+0000"]})[1] is True


def test_a_topic_with_no_published_deadline_is_kept():
    """Typical of forthcoming calls — a missing date is not an expired one."""
    assert fr._sedia_deadline({}) == ("", False)


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

def test_main_reports_only_new_calls_and_records_every_fetched_id(
    tmp_path, monkeypatch, fake_session, fake_response, capture_post
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr("sys.argv", ["funding_radar.py", "--create-issue"])

    payload = feed(csv_row(id="slug-100", titlu="Sprijin pacienti cancer", url="http://c"))
    routes = {
        (fr.CONFIG["eu_sedia_url"], kw): fake_response(json_data={"results": []})
        for kw in fr.CONFIG["eu_sedia_keywords"]
    }
    routes[fr.CONFIG["adieuronest_csv_url"]] = fake_response(content=payload)
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

    routes = {
        (fr.CONFIG["eu_sedia_url"], kw): fake_response(json_data={"results": []})
        for kw in fr.CONFIG["eu_sedia_keywords"]
    }
    routes[fr.CONFIG["adieuronest_csv_url"]] = requests.RequestException("down")
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
    routes = {
        (fr.CONFIG["eu_sedia_url"], kw): fake_response(json_data={"results": []})
        for kw in fr.CONFIG["eu_sedia_keywords"]
    }
    routes[fr.CONFIG["adieuronest_csv_url"]] = fake_response(content=payload)
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

    routes = {
        (fr.CONFIG["eu_sedia_url"], kw): fake_response(json_data={"results": []})
        for kw in fr.CONFIG["eu_sedia_keywords"]
    }
    routes[fr.CONFIG["adieuronest_csv_url"]] = fake_response(content=feed())
    monkeypatch.setattr(fr, "create_resilient_session", lambda: fake_session(routes))

    fr.main()

    assert "mipe:page" in cs.load_calls("calls.json")
