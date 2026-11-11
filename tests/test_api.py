"""Tests for the read-only API, against a small hand-built dataset.

Two House Democrats (D1, D2), two Republicans (R1, R2) and one independent who
caucuses with Democrats (I1), on three votes, so every stat can be checked by hand:

    vote        D1    D2    I1    R1    R2          party majority (D-caucus / R)
    h-119-1-1   yea   yea   nay   nay   nay         yea / nay
    h-119-1-2   nay   yea   yea   yea   not_voting  yea / yea
    h-119-1-3   yea   nay   (absent from file)  yea  yea   tie (none) / yea
"""

import os

import pytest

from congress_congruence import db

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

MEMBERS = [  # bioguide, last name, party, caucus, district
    ("D000001", "Dee", "Democrat", None, 1),
    ("D000002", "Dow", "Democrat", None, 2),
    ("I000001", "Ivy", "Independent", "Democrat", 3),
    ("R000001", "Roe", "Republican", None, 4),
    ("R000002", "Ray", "Republican", None, 0),
]
VOTES = {
    1: {"D000001": "yea", "D000002": "yea", "I000001": "nay", "R000001": "nay", "R000002": "nay"},
    2: {"D000001": "nay", "D000002": "yea", "I000001": "yea", "R000001": "yea", "R000002": "not_voting"},
    3: {"D000001": "yea", "D000002": "nay", "R000001": "yea", "R000002": "yea"},
}


@pytest.fixture(scope="module")
def client():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with db.connect(url) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core cascade")
        c.commit()
        db.migrate(c)
        with c.cursor() as cur:
            for bio, last, party, caucus, district in MEMBERS:
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'Test', %s)",
                            (bio, last))
                cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, caucus,
                               start_date, end_date) values (%s, 'house', 'TX', %s, %s, %s, '2025-01-03', '2099-01-03')""",
                            (bio, district, party, caucus))
            for n, positions in VOTES.items():
                rid = f"h-119-1-{n}"
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, result, bill_type, bill_number, bill_congress, source)
                               values (%s, 'house', 119, 1, %s, %s, 'On Passage', 'Passed', 'hr', %s, 119, 'house_clerk')""",
                            (rid, n, f"2025-03-0{n}", 100 + n))
                for bio, pos in positions.items():
                    cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                                "values (%s, %s, %s, %s)", (rid, bio, pos, pos.title()))
        c.commit()

    os.environ["API_DATABASE_URL"] = url
    from congress_congruence.api import app as api_module
    with TestClient(api_module.app) as tc:
        tc.api = api_module
        yield tc
    os.environ.pop("API_DATABASE_URL", None)


@pytest.fixture(autouse=True)
def pin_congress(monkeypatch, client):
    monkeypatch.setattr(client.api, "current_session", lambda day=None: (119, 1))


def stats(client, bio):
    r = client.get(f"/v1/members/{bio}")
    assert r.status_code == 200
    return r.json()["stats"]


def test_missed_votes(client):
    s = stats(client, "R000002")
    assert (s["votes_total"], s["votes_missed"], s["missed_pct"]) == (3, 1, 33.3)


def test_votes_with_party_majority(client):
    # D1: vote 1 yea=maj yes; vote 2 nay vs maj yea no; vote 3 tie -> excluded.
    s = stats(client, "D000001")
    assert (s["party_votes"], s["with_party"], s["with_party_pct"]) == (2, 1, 50.0)


def test_independent_counts_with_their_caucus(client):
    # I1 caucuses with Democrats: vote 1 nay vs D-caucus yea (no), vote 2 yea vs yea (yes).
    s = stats(client, "I000001")
    assert (s["party_votes"], s["with_party"]) == (2, 1)


def test_republican_alignment(client):
    s = stats(client, "R000001")
    assert (s["party_votes"], s["with_party"]) == (3, 3)


def test_member_profile_fields(client):
    m = client.get("/v1/members/R000002").json()
    assert (m["seat"], m["party"], m["serving"]) == ("TX-AL", "Republican", True)


def test_members_list_by_state(client):
    r = client.get("/v1/members?state=tx&chamber=house")
    assert r.status_code == 200
    assert [m["seat"] for m in r.json()["members"]] == ["TX-AL", "TX-1", "TX-2", "TX-3", "TX-4"]
    assert r.headers["cache-control"].startswith("public")


def test_recent_votes_newest_first_with_links(client):
    v = client.get("/v1/members/D000001/votes?limit=2").json()["votes"]
    assert [x["roll_call_id"] for x in v] == ["h-119-1-3", "h-119-1-2"]
    assert v[0]["bill"] == {"label": "H.R. 103", "url": "https://www.congress.gov/bill/119th-congress/house-bill/103"}
    assert v[0]["official_url"] == "https://clerk.house.gov/Votes/2025003"


@pytest.mark.parametrize("path, code", [
    ("/v1/members/not-an-id", 400), ("/v1/members/Z999999", 404),
    ("/v1/members?state=ZZ", 400), ("/v1/members/D000001/votes?limit=501", 422),
])
def test_bad_requests(client, path, code):
    assert client.get(path).status_code == code


def test_health_reports_freshness(client):
    h = client.get("/v1/health").json()
    assert h["status"] == "ok"
    assert h["data"][0]["latest_vote"] == "2025-03-03"
    assert h["data"][0]["first_vote"] <= h["data"][0]["latest_vote"] and h["data"][0]["first_congress"] == 119


def test_connections_are_read_only(client):
    import psycopg
    with client.api.pool.connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("delete from core.member_vote")


def test_member_search_by_name_state_and_seat():
    from congress_congruence.api.app import search_members
    rows = [
        {"name": "Nydia M. Velázquez", "last_name": "Velázquez", "chamber": "house", "state": "NY", "district": 7},
        {"name": "Ted Cruz", "last_name": "Cruz", "chamber": "senate", "state": "TX", "district": None},
        {"name": "John Cornyn", "last_name": "Cornyn", "chamber": "senate", "state": "TX", "district": None},
        {"name": "Jake Ellzey", "last_name": "Ellzey", "chamber": "house", "state": "TX", "district": 6},
        {"name": "Nicholas Begich", "last_name": "Begich", "chamber": "house", "state": "AK", "district": 0},
    ]
    names = lambda q: [r["name"] for r in search_members(q, rows)]
    assert names("cruz") == ["Ted Cruz"]
    assert names("velazquez") == ["Nydia M. Velázquez"]                 # accents don't matter
    assert names("ted c") == ["Ted Cruz"]
    assert names("corn*") == ["John Cornyn"]
    assert names("Texas") == ["John Cornyn", "Ted Cruz", "Jake Ellzey"]   # senators first, by last name
    assert names("tx") == names("Texas")
    assert names("TX-6") == ["Jake Ellzey"] and names("tx 6") == ["Jake Ellzey"]
    assert names("AK-AL") == ["Nicholas Begich"]
    assert names("john texas") == ["John Cornyn"]                     # a state word narrows a name
    assert names("zzz") == []

    # A whole delegation, current members first then former ones; the limit is for suggestions.
    big = [{"name": f"Rep {d}", "last_name": f"R{d:02}", "chamber": "house", "state": "OH", "district": d}
           for d in range(1, 16)] + [{"name": "Gone", "last_name": "Gone", "chamber": "senate", "state": "OH",
                                      "district": None, "former": True}]
    assert len(search_members("Ohio", big)) == 12
    found = search_members("Ohio", big, 120)
    assert len(found) == 16 and found[-1]["name"] == "Gone"

    # Former members: most recently in office first.
    from datetime import date
    gone = [{"name": n, "last_name": n, "chamber": "house", "state": "OH", "district": 1, "former": True,
             "end_date": date.fromisoformat(d)} for n, d in [("Aaa", "2021-03-10"), ("Bbb", "2025-01-03"), ("Ccc", "2023-01-03")]]
    assert [r["name"] for r in search_members("Ohio", gone)] == ["Bbb", "Ccc", "Aaa"]


def test_search_endpoint(client):
    r = client.get("/v1/search", params={"q": "zz"})
    assert r.status_code == 200 and r.json()["members"] == []
    assert client.get("/v1/search", params={"q": "z"}).status_code == 422


# ---------------------------------------------------------------- All votes, compare, states

def test_votes_list_filters_and_pages(client):
    r = client.get("/v1/votes").json()
    assert r["total"] == 3 and [v["roll_call_id"] for v in r["votes"]] == ["h-119-1-3", "h-119-1-2", "h-119-1-1"]
    assert r["votes"][0]["kind"] == "passage" and r["votes"][0]["outcome"] == "passed"
    assert r["votes"][0]["by_party"]["Republican"] == {"yea": 2}
    assert client.get("/v1/votes", params={"sort": "oldest", "limit": 1}).json()["votes"][0]["roll_call_id"] == "h-119-1-1"
    page2 = client.get("/v1/votes", params={"limit": 2, "offset": 2}).json()
    assert page2["total"] == 3 and [v["roll_call_id"] for v in page2["votes"]] == ["h-119-1-1"]
    for params, n in [({"congress": 119}, 3), ({"congress": 118}, 0), ({"chamber": "senate"}, 0),
                      ({"kind": "passage"}, 3), ({"kind": "amendment"}, 0), ({"outcome": "failed"}, 0),
                      ({"surveyed": "true"}, 0), ({"q": "passage"}, 3), ({"topic": "Taxation"}, 0)]:
        assert client.get("/v1/votes", params=params).json()["total"] == n, params
    assert client.get("/v1/votes", params={"kind": "bogus"}).status_code == 422
    f = client.get("/v1/votes/filters").json()
    assert f["congresses"][0]["congress"] == 119 and f["congresses"][0]["votes"] == {"house": 3}


def test_vote_kind_and_outcome_rules(client):
    """The All votes filters read the official wording; check them on real House and Senate phrasings."""
    q = client.api.q
    cases = [  # question, result, kind, outcome
        ("On Passage", "Passed", "passage", "passed"),
        ("On Motion to Suspend the Rules and Pass", "Failed", "passage", "failed"),
        ("On Motion to Suspend the Rules and Agree", "Passed", "passage", "passed"),
        ("On Concurring in Senate Amendment", "Passed", "passage", "passed"),
        ("On Motion to Concur in the Senate Amendment", "Agreed to", "passage", "passed"),
        ("On Agreeing to the Conference Report", "Agreed to", "passage", "passed"),
        ("On Agreeing to the Resolution", "Passed", "passage", "passed"),
        ("On Overriding the Veto", "Failed", "passage", "failed"),
        ("On the Resolution of Ratification", "Resolution of Ratification Agreed to", "passage", "passed"),
        ("On Passage of the Bill", "Bill Passed", "passage", "passed"),
        ("On the Joint Resolution", "Joint Resolution Defeated", "passage", "failed"),
        ("On Agreeing to the Amendment", "Failed", "amendment", "failed"),
        ("On the Amendment", "Amendment Rejected", "amendment", "failed"),
        ("On the Motion to Table", "Motion to Table Agreed to", "procedural", "passed"),
        ("On the Motion to Table the Amendment", "Motion to Table Agreed to", "procedural", "passed"),
        ("On the Cloture Motion", "Cloture Motion Rejected", "procedural", "failed"),
        ("On Cloture on the Motion to Proceed", "Cloture on the Motion to Proceed Agreed to", "procedural", "passed"),
        ("On Ordering the Previous Question", "Passed", "procedural", "passed"),
        ("On Motion to Recommit", "Failed", "procedural", "failed"),
        ("On the Motion", "Motion Agreed to", "procedural", "passed"),
        ("Quorum Call", None, "procedural", "other"),
        ("On the Nomination", "Nomination Confirmed", "nomination", "passed"),
        ("On the Cloture Motion (nomination)", "Cloture Motion Agreed to", "procedural", "passed"),
        ("Election of the Speaker", "Johnson", "other", "other"),
    ]
    with client.api.pool.connection() as conn:
        for question, result, kind, outcome in cases:
            got = conn.execute(f"select {q.VOTE_KIND} as kind, {q.VOTE_OUTCOME} as outcome "
                               "from (select %s::text as question, %s::text as result) r", (question, result)).fetchone()
            assert (got["kind"], got["outcome"]) == (kind, outcome), question


def test_vote_detail_lists_every_member(client):
    r = client.get("/v1/votes/h-119-1-1").json()
    by_id = {m["bioguide_id"]: m for m in r["members"]}
    assert len(by_id) == 5 and by_id["I000001"]["position"] == "nay" and (by_id["I000001"]["party"], by_id["I000001"]["caucus"]) == ("Independent", "Democrat")
    assert by_id["R000002"]["seat"] == "TX-AL"
    assert client.get("/v1/votes/nope").status_code == 400
    assert client.get("/v1/votes/h-119-1-99").status_code == 404


def test_compare_two_members(client):
    r = client.get("/v1/compare", params={"a": "D000001", "b": "D000002"}).json()
    assert (r["both_recorded"], r["both_voted"], r["same_way"]) == (3, 3, 1)
    assert r["splits_total"] == 2 and [v["roll_call_id"] for v in r["splits"]] == ["h-119-1-3", "h-119-1-2"]
    assert (r["splits"][0]["position_a"], r["splits"][0]["position_b"]) == ("yea", "nay")
    r = client.get("/v1/compare", params={"a": "D000001", "b": "I000001"}).json()   # I1 absent from vote 3
    assert (r["both_recorded"], r["both_voted"], r["same_way"], r["same_way_pct"]) == (2, 2, 0, 0.0)
    r = client.get("/v1/compare", params={"a": "R000001", "b": "R000002"}).json()   # R2 didn't vote on 2
    assert (r["both_recorded"], r["both_voted"], r["same_way"]) == (3, 2, 2)
    assert client.get("/v1/compare", params={"a": "D000001", "b": "Z999999"}).status_code == 404


def test_state_page(client):
    r = client.get("/v1/states/tx").json()
    assert r["state"] == "TX" and r["name"] == "Texas"
    assert [m["bioguide_id"] for m in r["members"]] == ["R000002", "D000001", "D000002", "I000001", "R000001"]
    assert r["members"][0]["scores"] == [] and r["former"] == [] and r["opinion"] == []
    assert client.get("/v1/states/XX").status_code == 404


def test_search_show_more(client):
    full = client.get("/v1/search", params={"q": "passage"}).json()
    assert full["votes_total"] == 3 and "members" in full
    more = client.get("/v1/search", params={"q": "passage", "only": "votes", "limit": 2, "offset": 2}).json()
    assert "members" not in more and "questions" not in more
    assert more["votes_total"] == 3 and [v["roll_call_id"] for v in more["votes"]] == [full["votes"][2]["roll_call_id"]]
    assert client.get("/v1/search", params={"q": "passage", "surveyed": "true"}).json()["votes_total"] == 0


def test_numbers_match_each_member_page(client):
    """Members by the numbers: the same counts as each member's own page, for every member."""
    r = client.get("/v1/numbers?congress=119&chamber=house")
    assert r.status_code == 200
    d = r.json()
    assert d["congress"] == 119 and 119 in d["congresses"]
    assert {m["bioguide_id"] for m in d["members"]} == {b for b, *_ in MEMBERS if any(b in v for v in VOTES.values())}
    for m in d["members"]:
        s = stats(client, m["bioguide_id"])
        assert (m["votes_total"], m["not_voting"], m["missed_pct"]) == (s["votes_total"], s["votes_missed"], s["missed_pct"]), m
        assert (m["party_votes"], m["with_party"], m["with_party_pct"]) == (s["party_votes"], s["with_party"], s["with_party_pct"]), m
        assert m["yea"] + m["nay"] + m["present"] + m["not_voting"] <= m["votes_total"]
        assert m["serving"] and m["first_sworn_in"] == "2025-01-03" and m["seat"].startswith("TX-")
        assert m["months_in_congress"] == m["months_in_seat"] > 0


def test_numbers_defaults_and_errors(client):
    assert client.get("/v1/numbers").json()["congress"] == 119       # the newest Congress with votes
    assert client.get("/v1/numbers?congress=90").status_code == 404
    assert client.get("/v1/numbers?chamber=both").status_code == 422
    assert client.get("/v1/numbers?chamber=senate").json()["members"] == []


def test_months_between():
    from datetime import date
    m = client_module_months()
    assert m(date(2012, 11, 13), date(2026, 11, 10)) == 167          # 13 years, 11 months
    assert m(date(2025, 1, 3), date(2025, 1, 2)) == 0


def client_module_months():
    from congress_congruence.api.app import months_between
    return months_between


def test_numbers_returning_member(client):
    """A member who left and came back: time in Congress leaves out the gap, the current seat counts
    from the return, and the break is listed."""
    import psycopg
    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url) as c, c.cursor() as cur:
        cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                       values ('R000001', 'house', 'TX', 9, 'Republican', '2011-01-03', '2015-01-03')""")
        c.commit()
    try:
        m = next(x for x in client.get("/v1/numbers?congress=119").json()["members"] if x["bioguide_id"] == "R000001")
        assert m["first_sworn_in"] == "2011-01-03"
        assert m["breaks"] == [{"left": "2015-01-03", "returned": "2025-01-03"}]
        assert m["months_in_congress"] == 48 + m["months_in_seat"]           # 2011-15, plus since 2025
    finally:
        with psycopg.connect(url) as c, c.cursor() as cur:
            cur.execute("delete from core.term where bioguide_id = 'R000001' and start_date = '2011-01-03'")
            c.commit()


def test_numbers_past_congress_is_measured_as_of_then(client, monkeypatch):
    """Looking back at a Congress after it ended: time in office stops at its last day, and a seat
    taken later doesn't count, while still-serving members stay marked as serving."""
    from datetime import date as real_date
    import congress_congruence.api.app as app_module

    class Later(real_date):
        @classmethod
        def today(cls):
            return real_date(2029, 6, 1)

    import psycopg
    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url) as c, c.cursor() as cur:       # R000001 later moves on to a Senate seat
        cur.execute("update core.term set end_date = '2027-01-03' where bioguide_id = 'R000001' and start_date = '2025-01-03'")
        cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                       values ('R000001', 'senate', 'TX', null, 'Republican', '2027-01-03', '2099-01-03')""")
        c.commit()
    monkeypatch.setattr(app_module, "date", Later)
    try:
        d = client.get("/v1/numbers?congress=119").json()
        assert d["as_of"] == "2027-01-03"
        for m in d["members"]:
            assert m["months_in_congress"] == m["months_in_seat"] == 24, m        # Jan 2025 to Jan 2027
            assert m["seat_since"] == "2025-01-03" and m["seat"].startswith("TX-"), m
            assert m["serving"], m                                                  # fixture terms run to 2099
    finally:
        with psycopg.connect(url) as c, c.cursor() as cur:
            cur.execute("delete from core.term where bioguide_id = 'R000001' and chamber = 'senate'")
            cur.execute("update core.term set end_date = '2099-01-03' where bioguide_id = 'R000001' and start_date = '2025-01-03'")
            c.commit()
