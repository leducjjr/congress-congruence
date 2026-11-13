"""Tests for the survey watcher, with a fake Dataverse and a small made-up survey file."""

import json
import os

import pytest

from congress_congruence import db
from congress_congruence.ingest import ces, watch

pd = pytest.importorskip("pandas")
pyreadstat = pytest.importorskip("pyreadstat")


def search_item(title, doi, major=1, minor=0):
    return {"name": title, "global_id": doi, "type": "dataset", "majorVersion": major, "minorVersion": minor,
            "published_at": "2027-03-20T00:00:00Z"}


class FakeHttp:
    def __init__(self, items):
        self.items = items

    def get(self, url, timeout, params):
        class R:
            def raise_for_status(self): pass
        r = R()
        page = self.items[params["start"]:params["start"] + params["per_page"]]
        r.json = lambda: {"data": {"items": page, "total_count": len(self.items)}}
        return r


TODAY = [
    search_item("CES 2025 Data", "doi:10.7910/DVN/DFUGJR"),
    search_item("Cooperative Election Study 2024 Common Content", "doi:10.7910/DVN/X11EP6", 3, 1),
    search_item("Cumulative CES Common Content", "doi:10.7910/DVN/II2DB6"),
    search_item("CES 2020-2022 Recontact Survey", "doi:10.7910/DVN/XV7ABM"),
    search_item("CES 2019 Data/Guide", "doi:10.7910/DVN/WOT7O8"),
]


def test_parse_release_keeps_only_single_year_studies():
    years = sorted(r["year"] for r in map(watch.parse_release, TODAY) if r)
    assert years == [2019, 2024, 2025]          # cumulative and multi-year recontact skipped
    assert watch.parse_release(search_item("Some other study 2024", "doi:x")) is None


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(watch.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ces.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("NOTIFY_URL", raising=False)
    return tmp_path


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with db.connect(url) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core, history cascade")
        c.commit()
        db.migrate(c)
        with c.cursor() as cur:
            for rid, ch, d, q, bt, bn, desc in [
                ("h-120-1-40", "house", "2027-02-10", "On Passage", "hr", 5, "Lower Grocery Prices Act"),
                ("h-120-1-41", "house", "2027-02-11", "On Ordering the Previous Question", "hres", 9, "Grocery rule"),
                ("s-120-1-30", "senate", "2027-03-01", "On Passage of the Bill", "hr", 5, "Lower Grocery Prices Act"),
                ("h-120-1-90", "house", "2027-04-01", "On Passage", "hr", 77, "National Parks Funding Act"),
            ]:
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, description, bill_type, bill_number, source)
                               values (%s, %s, 120, 1, %s, %s, %s, %s, %s, %s, 'test')""",
                            (rid, ch, int(rid.rsplit("-", 1)[1]), d, q, desc, bt, bn))
        c.commit()
        yield c


@pytest.fixture
def survey_2027(project):
    df = pd.DataFrame({"inputstate": [48, 6], "cdid120": [8, 12], "commonweight": [1.0, 1.0],
                       "CC27_340a": [1, 2], "CC27_340b": [2, 2], "CC27_401": [1, 2]})
    folder = project / "data" / "raw" / "ces" / "2027"
    folder.mkdir(parents=True)
    path = folder / "CES27_Common.dta"
    pyreadstat.write_dta(df, str(path),
        column_labels=["State", "CD 120", "Common weight",
                       "Congress Bills -- Lower grocery prices by cutting food import taxes",
                       "Congress Bills -- Increase funding for national parks",
                       "Do you support lower grocery prices?"],
        variable_value_labels={"CC27_340a": {1: "Support", 2: "Oppose"}, "CC27_340b": {1: "Support", 2: "Oppose"},
                               "CC27_401": {1: "Support", 2: "Oppose"}})
    return path


def test_first_run_records_without_asking_then_new_year_is_drafted(project, conn, survey_2027, monkeypatch):
    monkeypatch.setenv("RAW_DATA_DIR", str(project / "data" / "raw"))
    assert watch.check_ces(conn, FakeHttp(TODAY)) == []                     # baseline
    assert set(watch.load_state()) == {"2019", "2024", "2025"}

    monkeypatch.setattr(ces, "inspect", lambda year: project / "logs" / f"ces_{year}_inspect.txt")
    later = [search_item("CES 2027 Data", "doi:10.7910/DVN/NEW27")] + TODAY
    messages = watch.check_ces(conn, FakeHttp(later))
    assert len(messages) == 1 and "CES 2027 Data" in messages[0] and "drafts/ces_2027_items.yaml" in messages[0]
    assert ces.dataset_id(2027) == "doi:10.7910/DVN/NEW27"                  # usable by `ces` commands

    draft = (project / "config" / "drafts" / "ces_2027_items.yaml").read_text()
    assert "DRAFT" in draft and "district_column: cdid120" in draft
    assert "CC27_340a:" in draft and "CC27_340b:" in draft and "CC27_401" not in draft   # only Congress items
    grocery = draft.split("CC27_340a:")[1].split("CC27_340b:")[0]
    assert "h-120-1-40" in grocery and "s-120-1-30" in grocery              # word-matched candidates
    assert "h-120-1-41" not in grocery                                      # procedural vote excluded
    parks = draft.split("CC27_340b:")[1]
    assert "h-120-1-90" in parks

    assert watch.check_ces(conn, FakeHttp(later)) == []                     # nothing new the next month


def test_new_version_of_a_known_year_asks_for_review(project, conn):
    watch.check_ces(conn, FakeHttp(TODAY))
    updated = [search_item("CES 2025 Data", "doi:10.7910/DVN/DFUGJR", 2, 0)] + TODAY[1:]
    messages = watch.check_ces(conn, FakeHttp(updated))
    assert len(messages) == 1 and "CES 2025 has a new version (1.0 -> 2.0)" in messages[0]


def test_notify_writes_review_file(project):
    watch.notify(["CES 2027 is waiting"])
    assert "CES 2027 is waiting" in (project / "logs" / "review_needed.txt").read_text()


def test_draft_is_valid_yaml(project, conn, survey_2027, monkeypatch):
    import yaml
    monkeypatch.setenv("RAW_DATA_DIR", str(project / "data" / "raw"))
    cols, labels, values, n = ces.read_metadata(survey_2027)
    text = watch.draft_items(conn, 2027, {"title": "CES 2027 Data", "id": "doi:10.7910/DVN/NEW27", "version": "1.0"},
                             cols, labels, values, n)
    cfg = yaml.safe_load(text)
    assert cfg["survey"] == "CES 2027" and cfg["dataset_id"] == "doi:10.7910/DVN/NEW27"
    assert set(cfg["items"]) == {"CC27_340a", "CC27_340b"}
    assert cfg["source"]["dataset_url"] == "https://doi.org/10.7910/DVN/NEW27"


# ---------------------------------------------------------------- Census

def census_fixture(congress):
    from test_population import DISTRICTS_119, STATES   # pytest puts tests/ on the import path
    districts = [DISTRICTS_119[0]] + [[r[0].replace("119th", f"{congress}th"), *r[1:]] for r in DISTRICTS_119[1:]]
    return districts, STATES


def test_census_watch_loads_the_next_release_when_published(conn, monkeypatch):
    import requests
    from congress_congruence.ingest import population
    districts, states = census_fixture(119)
    published = {2024}

    def fake_fetch(year, geography, within=None, http=None):
        if year not in published:
            raise requests.HTTPError("404")
        return districts if geography.startswith("congressional") else states

    monkeypatch.setattr(population, "fetch", fake_fetch)
    assert watch.check_census(conn) == []                    # nothing loaded yet: left to a person
    population.load(conn, 2024)
    assert watch.check_census(conn) == []                    # 2025 not published yet
    published.add(2025)
    msgs = watch.check_census(conn)
    assert len(msgs) == 1 and "ACS 2025" in msgs[0] and "Nothing to review" in msgs[0]
    assert watch.latest_acs_year(conn) == 2025
    assert watch.check_census(conn) == []                    # 2026 not published


def test_census_watch_surfaces_a_key_problem(conn, monkeypatch):
    from congress_congruence.ingest import population
    population_rows = census_fixture(119)
    monkeypatch.setattr(population, "fetch", lambda *a, **k: population_rows[0] if "congressional" in a[1] else population_rows[1])
    population.load(conn, 2024)

    def no_key(*a, **k):
        raise RuntimeError("The Census API needs a free key (it redirected to its missing-key page).")
    monkeypatch.setattr(population, "fetch", no_key)
    with pytest.raises(RuntimeError, match="free key"):
        watch.check_census(conn)


def test_run_separates_review_from_updates(project, conn, monkeypatch):
    monkeypatch.setattr(watch, "SOURCES", {
        "A": (lambda c: ["CES 2027 needs review"], "review"),
        "B": (lambda c: ["Loaded ACS 2025"], "info"),
        "C": (lambda c: (_ for _ in ()).throw(RuntimeError("boom")), "info"),
    })
    result = watch.run(conn)
    assert result == {"needs_review": 1, "updated": 1, "errors": ["C: boom"]}
    log = (project / "logs" / "review_needed.txt").read_text()
    assert "CES 2027 needs review" in log and "Loaded ACS 2025" in log


def test_older_years_item_wording_is_recognized():
    columns = ["CC316a", "CC316b", "CC310", "V101"]
    labels = {"CC316a": "Roll Call Votes -- Stem Cell Research", "CC316b": "Roll call vote -- Iraq withdrawal",
              "CC310": "Do you approve of the way the President is handling his job", "V101": "weight"}
    values = {"CC316a": {1: "For", 2: "Against"}, "CC316b": {1.0: "Support", 2.0: "Oppose"},
              "CC310": {1: "Strongly approve", 2: "Somewhat approve"}}
    assert watch.congress_items(columns, labels, values) == [
        ("CC316a", "Stem Cell Research"), ("CC316b", "Iraq withdrawal")]
