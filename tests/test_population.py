"""Tests for the Census population loader and the API's population fields."""

import os

import pytest

from congress_congruence import db
from congress_congruence.ingest import population

# Shaped like api.census.gov responses (first row is the header).
DISTRICTS_119 = [
    ["NAME", "B01003_001E", "B05001_006E", "B29001_001E", "state", "congressional district"],
    ["Congressional District 6 (119th Congress), Texas", "766987", "61000", "512000", "48", "06"],
    ["Congressional District 8 (119th Congress), Texas", "812345", "70000", "540000", "48", "08"],
    ["Congressional District (at Large) (119th Congress), Wyoming", "587618", "9000", "450000", "56", "00"],
    ["Delegate District (at Large) (119th Congress), District of Columbia", "702250", "40000", "520000", "11", "98"],
    # Puerto Rico's citizenship figures are in its own tables: blank / annotation codes here.
    ["Resident Commissioner District (at Large) (119th Congress), Puerto Rico", "3203295", "", "-666666666", "72", "98"],
]
STATES = [
    ["NAME", "B01003_001E", "B05001_006E", "B29001_001E", "state"],
    ["Texas", "31290831", "3100000", "19400000", "48"], ["Wyoming", "587618", "9000", "450000", "56"],
    ["District of Columbia", "702250", "40000", "520000", "11"], ["Puerto Rico", "3203295", None, None, "72"],
]


def test_parse_districts_reads_congress_from_names_and_maps_codes():
    congress, rows = population.parse_districts(DISTRICTS_119)
    assert congress == 119
    assert ("TX", 6, 766987, 705987, 512000) in rows                     # citizens = residents - non-citizens
    assert ("WY", 0, 587618, 578618, 450000) in rows                     # 00 at-large -> 0
    assert ("DC", 0, 702250, 662250, 520000) in rows and ("PR", 0, 3203295, None, None) in rows   # 98 delegate -> 0


def test_states_carry_citizen_counts_and_tolerate_blanks():
    rows = population.parse_states(STATES)
    assert ("TX", 31290831, 28190831, 19400000) in rows and ("PR", 3203295, None, None) in rows


def test_older_tables_without_citizen_columns_still_load():
    old = [["NAME", "B01003_001E", "state"], ["Texas", "29000000", "48"]]
    assert population.parse_states(old) == [("TX", 29000000, None, None)]


def test_parse_districts_refuses_mixed_congresses():
    mixed = DISTRICTS_119 + [["Congressional District 1 (118th Congress), Alabama", "700000", "1", "500000", "01", "01"]]
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
            cur.execute("drop schema if exists core, history cascade")
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
    assert rep["citizens"] == 705987 and rep["adult_citizens"] == 512000
    assert sen["adult_citizens"] == 19400000
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


def test_missing_key_redirect_explains_how_to_get_a_key():
    class Http:
        def get(self, url, params, timeout):
            class R:
                url = "https://api.census.gov/data/missing_key.html"
                status_code, text = 200, "<html><title>Missing Key</title></html>"
                def raise_for_status(self): pass
                def json(self): raise ValueError("not json")
            return R()
    with pytest.raises(RuntimeError, match="key_signup"):
        population.fetch(2024, "state:*", None, Http())


def test_numbers_carry_each_seats_citizen_counts(conn, monkeypatch):
    population.load(conn, 2024, FakeHttp())
    with conn.cursor() as cur:
        cur.execute("insert into core.member (bioguide_id, first_name, last_name) values ('H000006', 'T', 'Rep')")
        cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                       values ('H000006', 'house', 'TX', 6, 'Independent', '2025-01-03', '2027-01-03')""")
        cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number, vote_date,
                       question, result, yea_total, nay_total, source)
                       values ('h-119-1-1', 'house', 119, 1, 1, '2025-02-01', 'On Passage', 'Passed', 1, 0, 'test')""")
        cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                    "values ('h-119-1-1', 'H000006', 'yea', 'Yea')")
    conn.commit()
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api_module
    with TestClient(api_module.app) as tc:
        (m,) = tc.get("/v1/numbers?congress=119&chamber=house").json()["members"]
    assert (m["residents"], m["citizens"], m["adult_citizens"]) == (766987, 705987, 512000)
