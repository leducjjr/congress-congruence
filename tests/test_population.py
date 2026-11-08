"""Tests for the Census population loader and the API's population fields."""

import os

import pytest

from congress_congruence import db
from congress_congruence.ingest import population

# Shaped like api.census.gov responses (first row is the header).
DISTRICTS_119 = [
    ["NAME", "B01003_001E", "state", "congressional district"],
    ["Congressional District 6 (119th Congress), Texas", "766987", "48", "06"],
    ["Congressional District 8 (119th Congress), Texas", "812345", "48", "08"],
    ["Congressional District (at Large) (119th Congress), Wyoming", "587618", "56", "00"],
    ["Delegate District (at Large) (119th Congress), District of Columbia", "702250", "11", "98"],
    ["Resident Commissioner District (at Large) (119th Congress), Puerto Rico", "3203295", "72", "98"],
]
STATES = [
    ["NAME", "B01003_001E", "state"],
    ["Texas", "31290831", "48"], ["Wyoming", "587618", "56"],
    ["District of Columbia", "702250", "11"], ["Puerto Rico", "3203295", "72"],
]


def test_parse_districts_reads_congress_from_names_and_maps_codes():
    congress, rows = population.parse_districts(DISTRICTS_119)
    assert congress == 119
    assert ("TX", 6, 766987) in rows and ("WY", 0, 587618) in rows      # 00 at-large -> 0
    assert ("DC", 0, 702250) in rows and ("PR", 0, 3203295) in rows      # 98 delegate -> 0


def test_parse_districts_refuses_mixed_congresses():
    mixed = DISTRICTS_119 + [["Congressional District 1 (118th Congress), Alabama", "700000", "01", "01"]]
    with pytest.raises(ValueError, match="one Congress"):
        population.parse_districts(mixed)


class FakeHttp:
    def get(self, url, params, timeout):
        class R:
            def raise_for_status(self): pass
        r = R()
        table = DISTRICTS_119 if params["for"].startswith("congressional") else STATES
        r.json = lambda: table
        return r


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with db.connect(url) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core cascade")
        c.commit()
        db.migrate(c)
        yield c


def test_load_files_rows_under_the_congress_and_replaces_on_rerun(conn):
    assert population.load(conn, 2024, FakeHttp()) == {
        "congress": 119, "districts": 5, "states": 4, "source": "ACS 2024 1-year estimate"}
    population.load(conn, 2024, FakeHttp())
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.area_population")
        assert cur.fetchone()[0] == 9


def test_api_population_for_house_and_senate(conn, monkeypatch):
    population.load(conn, 2024, FakeHttp())
    with conn.cursor() as cur:
        # The senator's current term began in 2021 (117th Congress), before the loaded figures.
        for bio, chamber, st, dist, start in (("H000006", "house", "TX", 6, "2025-01-03"),
                                              ("S000099", "senate", "TX", None, "2021-01-03")):
            cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'T', %s)", (bio, bio))
            cur.execute("""insert into core.term (bioguide_id, chamber, state, district, senate_class, party,
                           start_date, end_date) values (%s, %s, %s, %s, %s, 'Independent', %s, '2031-01-03')""",
                        (bio, chamber, st, dist, 1 if chamber == "senate" else None, start))
    conn.commit()
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api_module
    with TestClient(api_module.app) as tc:
        rep = tc.get("/v1/members/H000006").json()["population"]
        sen = tc.get("/v1/members/S000099").json()["population"]
    assert rep["residents"] == 766987 and rep["area"] == "TX-6" and rep["congress"] == 119
    assert rep["average_district"] == round((766987 + 812345 + 587618) / 3)   # DC and PR left out
    assert sen["residents"] == 31290831 and sen["area"] == "TX"
    assert sen["smallest_state"] == {"state": "WY", "residents": 587618}
    assert sen["largest_state"] == {"state": "TX", "residents": 31290831}


def test_non_data_reply_is_reported_in_plain_words():
    class Http:
        def get(self, url, params, timeout):
            class R:
                status_code, text = 200, "error: unknown/unsupported geography hierarchy"
                def raise_for_status(self): pass
                def json(self): raise ValueError("not json")
            return R()
    with pytest.raises(RuntimeError, match="unknown/unsupported geography"):
        population.fetch(2024, "congressional district:*", "state:*", Http())
