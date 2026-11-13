"""The historical record (1789-1972): Voteview's three files for one chamber and Congress become one
row per member with a string of cast codes and their totals (ingest/history.py, sql/012_history.sql)."""

import os
from datetime import date

import pytest

from congress_congruence import db
from congress_congruence.ingest import history

MEMBERS = [  # two Federalists, a Republican, and one who left after roll call 2 (replaced by another)
    {"congress": "5", "chamber": "House", "icpsr": "101", "state_abbrev": "MA", "district_code": "1",
     "party_code": "38", "bioname": "ADAMS, Fisher", "bioguide_id": "A000001", "born": "1750", "died": "1810"},
    {"congress": "5", "chamber": "House", "icpsr": "102", "state_abbrev": "MA", "district_code": "2",
     "party_code": "38", "bioname": "BROWN, Eli", "bioguide_id": "B000001", "born": "1760", "died": ""},
    {"congress": "5", "chamber": "House", "icpsr": "103", "state_abbrev": "VA", "district_code": "1",
     "party_code": "13", "bioname": "CARTER, Ann", "bioguide_id": "", "born": "", "died": ""},
    {"congress": "5", "chamber": "House", "icpsr": "104", "state_abbrev": "VA", "district_code": "2",
     "party_code": "13", "bioname": "DAVIS, Leaving", "bioguide_id": "D000001", "born": "", "died": ""},
    {"congress": "5", "chamber": "President", "icpsr": "99901", "state_abbrev": "USA", "district_code": "0",
     "party_code": "38", "bioname": "ADAMS, John", "bioguide_id": "", "born": "", "died": ""},
]
ROLLCALLS = [
    {"congress": "5", "chamber": "House", "rollnumber": "1", "date": "1797-05-15", "session": "1",
     "clerk_rollnumber": "", "yea_count": "3", "nay_count": "1", "vote_result": "", "vote_question": "",
     "vote_desc": "TO PASS THE BILL", "bill_number": ""},
    {"congress": "5", "chamber": "House", "rollnumber": "2", "date": "1797-05-16", "session": "1",
     "clerk_rollnumber": "", "yea_count": "9", "nay_count": "9", "vote_result": "", "vote_question": "",
     "vote_desc": "TO ADJOURN", "bill_number": ""},
    {"congress": "5", "chamber": "House", "rollnumber": "3", "date": "1798-01-02", "session": "2",
     "clerk_rollnumber": "", "yea_count": "0", "nay_count": "2", "vote_result": "", "vote_question": "",
     "vote_desc": "TO AMEND", "bill_number": "HR5"},
]
CASTS = {  # icpsr: codes for roll calls 1, 2, 3
    "101": "116", "102": "169", "103": "616", "104": "190",
}
VOTES = [{"congress": "5", "chamber": "House", "rollnumber": str(i + 1), "icpsr": icpsr, "cast_code": c}
         for icpsr, codes in CASTS.items() for i, c in enumerate(codes)]
VOTES.append({"congress": "5", "chamber": "President", "rollnumber": "1", "icpsr": "99901", "cast_code": "1"})


def test_build_one_congress():
    data = history.build("house", MEMBERS, ROLLCALLS, VOTES)
    m = {x["icpsr"]: x for x in data["members"]}
    assert set(m) == {101, 102, 103, 104}                                         # no President
    assert m[101]["casts"] == "116" and m[104]["casts"] == "190"
    assert (m[101]["yea"], m[101]["nay"], m[101]["not_voting"], m[101]["votes_total"]) == (2, 1, 0, 3)
    assert (m[104]["votes_total"], m[104]["last_vote"]) == (2, date(1797, 5, 16))   # gone by roll call 3
    # Party sides: roll 1 Federalists (38) yea, Republicans (13) split 1-1 (none); roll 2 Federalists
    # split 1-1 (none), Republicans yea (104 not voting); roll 3 both nay (102 not voting).
    assert (m[101]["party_votes"], m[101]["with_party"]) == (2, 2)
    assert (m[102]["party_votes"], m[102]["with_party"]) == (1, 1)
    assert (m[103]["party_votes"], m[103]["with_party"]) == (2, 2)
    assert (m[104]["party_votes"], m[104]["with_party"]) == (0, 0)       # his one Yea came on a tied party
    rolls = {r["rollnumber"]: r for r in data["roll_calls"]}
    assert rolls[1]["totals_match"] is True and rolls[2]["totals_match"] is False and data["mismatched"] == 1
    assert rolls[3]["session"] == 2 and rolls[3]["bill_number"] == "HR5"


@pytest.fixture()
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


def test_store_replaces_a_congress_and_reports_status(conn):
    data = history.build("house", MEMBERS, ROLLCALLS, VOTES)
    history.store(conn, "house", 5, data)
    history.store(conn, "house", 5, data)                                          # rerun: replaced, not doubled
    with conn.cursor() as cur:
        cur.execute("select count(*), sum(votes_total) from history.member_congress")
        assert cur.fetchone() == (4, 11)
        cur.execute("select count(*) from history.roll_call")
        assert cur.fetchone()[0] == 3
        cur.execute("select bioguide_id, name from history.member where icpsr = 103")
        assert cur.fetchone() == (None, "CARTER, Ann")
    s = history.status(conn)
    assert "house: 1 Congresses (5-5), 3 roll calls, 1 with totals that don't match" in s and "Space used" in s


@pytest.fixture()
def client(conn):
    from fastapi.testclient import TestClient
    data = history.build("house", MEMBERS, ROLLCALLS, VOTES)
    history.store(conn, "house", 5, data)
    with conn.cursor() as cur:
        cur.execute("insert into history.party values (38, 'Federalist'), (13, 'Democratic-Republican')")
    conn.commit()
    os.environ["API_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    from congress_congruence.api import app as api_module
    with TestClient(api_module.app) as tc:
        yield tc
    os.environ.pop("API_DATABASE_URL", None)


def test_names_read_naturally():
    from congress_congruence.api.history import display_name
    assert display_name("LINCOLN, Abraham") == "Abraham Lincoln"
    assert display_name("VAN BUREN, Martin") == "Martin Van Buren"
    assert display_name("McKINLEY, William (Jr.)") == "William McKinley, Jr."
    assert display_name("O'NEILL, Thomas Phillip (Tip)") == "Thomas Phillip (Tip) O'Neill"


def test_history_api(client):
    c = client.get("/v1/history/congresses").json()["congresses"]
    assert c[0]["congress"] == 5 and c[0]["years"] == "1797–1799" and c[0]["house"]["roll_calls"] == 3
    n = client.get("/v1/history/congresses/5/numbers?chamber=house").json()
    adams = next(m for m in n["members"] if m["icpsr"] == 101)
    assert adams["name"] == "Fisher Adams" and adams["party"] == "Federalist" and adams["with_party_pct"] == 100.0
    assert adams["id"] == "A000001" and adams["district"] == 1 and adams["on_main_site"] is False
    assert {p["party"]: p["members"] for p in n["parties"]} == {"Federalist": 2, "Democratic-Republican": 2}
    v = client.get("/v1/history/congresses/5/votes?chamber=house&q=adjourn").json()
    assert v["total"] == 1 and v["votes"][0]["description"] == "To adjourn" and v["votes"][0]["totals_match"] is False
    assert v["votes"][0]["voteview_url"] == "https://voteview.com/rollcall/RH0050002"
    one = client.get("/v1/history/votes/house/5/1").json()
    assert len(one["members"]) == 4 and {"party": "Federalist", "yea": 2, "nay": 0} in one["by_party"]
    gone = client.get("/v1/history/votes/house/5/3").json()
    assert "D000001" not in [m["id"] for m in gone["members"]]                  # had left by then
    m = client.get("/v1/history/members/A000001").json()
    assert m["name"] == "Fisher Adams" and m["congresses"][0]["congress"] == 5 and m["votes_total"] == 3
    assert client.get("/v1/history/members/103").json()["name"] == "Ann Carter"     # no Bioguide ID: by number
    mv = client.get("/v1/history/members/D000001/votes?congress=5&chamber=house").json()["votes"]
    assert [(x["roll"], x["position"]) for x in mv] == [(1, "yea"), (2, "not_voting")]
    assert client.get("/v1/history/congresses/40/numbers").status_code == 404
    assert client.get("/v1/history/members/Z999999").status_code == 404
