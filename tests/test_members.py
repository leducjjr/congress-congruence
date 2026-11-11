"""Tests for the member loader.

Parsing tests need nothing. Database tests run only when TEST_DATABASE_URL
points at an empty, disposable database.
"""

import os

import pytest

from congress_congruence import db
from congress_congruence.ingest import members

# Two people shaped like the real dataset: one House-then-Senate career with
# a mid-term party switch, one House member with an at-large seat.
PEOPLE = [
    {
        "id": {"bioguide": "X000001", "lis": "S999", "icpsr": 12345, "fec": ["H0XX01", "S0XX01"]},
        "name": {"first": "Pat", "last": "Example", "official_full": "Pat Example"},
        "bio": {"birthday": "1960-01-01", "gender": "F"},
        "terms": [
            {"type": "rep", "start": "2015-01-06", "end": "2017-01-03", "state": "TX",
             "district": 8, "party": "Independent",
             "party_affiliations": [
                 {"start": "2015-01-06", "end": "2016-03-01", "party": "Democrat"},
                 {"start": "2016-03-02", "end": "2017-01-03", "party": "Independent"},
             ]},
            {"type": "sen", "start": "2017-01-03", "end": "2023-01-03", "state": "TX",
             "class": 2, "party": "Independent", "caucus": "Democrat"},
        ],
    },
    {
        "id": {"bioguide": "X000002", "icpsr": 12345},  # deliberately reuses an ICPSR ID
        "name": {"first": "Sam", "last": "Sample"},
        "bio": {},
        "terms": [
            {"type": "rep", "start": "2021-01-03", "end": "2023-01-03", "state": "WY",
             "district": 0, "party": "Republican"},
        ],
    },
]


def test_parse_flattens_members_terms_and_ids():
    p = members.parse(PEOPLE)
    assert [m[0] for m in p.members] == ["X000001", "X000002"]
    assert ("lis", "S999", "X000001") in p.external_ids
    assert ("fec", "H0XX01", "X000001") in p.external_ids and ("fec", "S0XX01", "X000001") in p.external_ids
    assert ("icpsr", "12345", "X000001") in p.external_ids  # numbers become text


def test_parse_reports_duplicate_ids_instead_of_failing():
    p = members.parse(PEOPLE)
    assert p.duplicate_ids == [("icpsr", "12345", "X000001", "X000002")]
    assert ("icpsr", "12345", "X000002") not in p.external_ids


def test_parse_maps_chambers_and_seat_fields():
    house, senate, at_large = members.parse(PEOPLE).terms
    assert (house["chamber"], house["district"], house["senate_class"]) == ("house", 8, None)
    assert (senate["chamber"], senate["district"], senate["senate_class"]) == ("senate", None, 2)
    assert senate["caucus"] == "Democrat"
    assert at_large["district"] == 0
    assert len(house["party_affiliations"]) == 2


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


def test_load_writes_rows_and_is_rerunnable(conn):
    parsed = members.parse(PEOPLE)
    first = members.load(conn, parsed)
    second = members.load(conn, parsed)  # re-run must not duplicate anything
    assert first == second == {"members": 2, "external_ids": 4, "terms": 3, "party_changes": 2}
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.term")
        assert cur.fetchone()[0] == 3
        cur.execute("select bioguide_id from core.member_external_id where id_type='lis' and id_value='S999'")
        assert cur.fetchone()[0] == "X000001"


def test_schema_rejects_house_term_without_district(conn):
    import psycopg

    members.load(conn, members.parse(PEOPLE))
    with pytest.raises(psycopg.errors.CheckViolation), conn.cursor() as cur:
        cur.execute(
            """insert into core.term (bioguide_id, chamber, state, start_date, end_date)
               values ('X000002', 'house', 'WY', '2023-01-03', '2025-01-03')"""
        )
    conn.rollback()


def test_appointed_senator_serves_until_a_successor_is_listed():
    from datetime import date
    def sen(bio, start, end, how=None):
        return {"bioguide_id": bio, "chamber": "senate", "state": "OH", "senate_class": 3, "start_date": start,
                "end_date": end, "how": how, "listed_end_date": None}
    appointed = sen("H000001", date(2025, 1, 21), date(2026, 11, 3), "appointment")
    terms = [sen("V000001", date(2023, 1, 3), date(2025, 1, 9)), appointed]
    held = members.hold_appointed_seats(terms, date(2026, 11, 8))
    assert held and appointed["end_date"] == date(2029, 1, 3) and appointed["listed_end_date"] == date(2026, 11, 3)
    # Once the winner is listed, the list's own date stands.
    appointed2 = sen("H000001", date(2025, 1, 21), date(2026, 11, 3), "appointment")
    terms = [appointed2, sen("W000001", date(2026, 12, 1), date(2029, 1, 3), "special-election")]
    assert members.hold_appointed_seats(terms, date(2026, 12, 5)) == []
    assert appointed2["end_date"] == date(2026, 11, 3)
    # Appointments still running by the list's date, and other terms, are left alone.
    running = sen("X000001", date(2025, 1, 21), date(2026, 11, 3), "appointment")
    assert members.hold_appointed_seats([running], date(2026, 6, 1)) == [] and running["end_date"] == date(2026, 11, 3)
    assert members.regular_end(1, date(2025, 2, 1)) == date(2031, 1, 3)
    assert members.regular_end(2, date(2025, 2, 1)) == date(2027, 1, 3)


def test_corrections_fix_special_election_starts():
    from congress_congruence.ingest import members as m
    terms = [{"bioguide_id": "P000034", "chamber": "house", "start_date": "1987-01-06", "district": 6},
             {"bioguide_id": "P000034", "chamber": "house", "start_date": "1989-01-03", "district": 3}]
    notes = m.apply_corrections(terms, [{"bioguide": "P000034", "chamber": "house", "listed_start": "1987-01-06",
                                         "start": "1988-11-08", "district": 3}])
    assert terms[0]["start_date"] == "1988-11-08" and terms[0]["district"] == 3 and terms[1]["start_date"] == "1989-01-03"
    assert notes == ["Corrected P000034 start 1987-01-06 -> 1988-11-08"]
    # Once the list is fixed upstream, the correction steps aside.
    assert "not needed" in m.apply_corrections(terms, [{"bioguide": "P000034", "chamber": "house",
                                                        "listed_start": "1987-01-06", "start": "1988-11-08"}])[0]


def test_corrections_file_is_valid():
    import datetime as dt
    from congress_congruence.ingest import members as m
    for c in m.read_yaml(m.CORRECTIONS_FILE):
        assert {"bioguide", "chamber", "listed_start", "start", "source"} <= set(c), c
        assert dt.date.fromisoformat(str(c["start"])) > dt.date.fromisoformat(str(c["listed_start"])), c
