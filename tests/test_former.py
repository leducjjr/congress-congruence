"""Former members: found in lists and search, with figures for every Congress and chamber served."""

import os

from test_ppc import conn, test_load_and_compare  # noqa: F401  (database fixture and demo data)


def add_former_member(conn):
    """C000001: House (IA-3) in the 118th Congress, then Senate (IA) until mid-2026, when they left."""
    with conn.cursor() as cur:
        cur.execute("insert into core.member (bioguide_id, first_name, last_name, official_full) "
                    "values ('C000001', 'Cee', 'Former', 'Cee Former')")
        cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date) values
                       ('C000001', 'house', 'IA', 3, 'Democrat', '2023-01-03', '2025-01-03'),
                       ('C000001', 'senate', 'IA', null, 'Democrat', '2025-01-03', '2026-06-01')""")
        for rid, chamber, congress, sess, roll, day, pos in [
                ("h-118-1-5", "house", 118, 1, 5, "2023-02-01", "yea"),
                ("h-118-1-6", "house", 118, 1, 6, "2023-02-02", "not_voting"),
                ("s-119-1-9", "senate", 119, 1, 9, "2025-03-01", "nay")]:
            cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number, vote_date,
                           question, result, yea_total, nay_total, source) values (%s, %s, %s, %s, %s, %s, 'On Passage',
                           'Passed', 1, 0, 'test')""", (rid, chamber, congress, sess, roll, day))
            cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                        "values (%s, 'C000001', %s, %s)", (rid, pos, pos))
    conn.commit()


def client_for(monkeypatch):
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    return TestClient(api.app)


def test_former_members_listed_found_and_given_figures_per_period(conn, monkeypatch):  # noqa: F811
    test_load_and_compare(conn, monkeypatch, None)
    add_former_member(conn)
    with client_for(monkeypatch) as client:
        current = client.get("/v1/members", params={"state": "IA"}).json()["members"]
        listed = client.get("/v1/members", params={"state": "IA", "include": "former"}).json()["members"]
        profile = client.get("/v1/members/C000001").json()
        found = client.get("/v1/search", params={"q": "former", "only": "members"}).json()["members"]
        iowa = client.get("/v1/search", params={"q": "Iowa", "only": "members"}).json()["members"]

    assert "C000001" not in [m["bioguide_id"] for m in current]
    (c,) = [m for m in listed if m["bioguide_id"] == "C000001"]
    assert c["former"] and c["left_office"] == "2026-06-01" and c["chamber"] == "senate"
    assert listed[-1]["bioguide_id"] == "C000001"                   # after everyone serving today

    assert profile["serving"] is False and profile["left_office"] == "2026-06-01"
    periods = [(p["chamber"], p["congress"], p["votes_total"], p["seat"]) for p in profile["service"]]
    assert periods == [("senate", 119, 1, "IA"), ("house", 118, 2, "IA-3")]
    assert profile["service"][1]["missed_pct"] == 50.0
    assert profile["stats"]["chamber"] == "senate" and profile["stats"]["votes_total"] == 1   # not blank

    assert [m["bioguide_id"] for m in found] == ["C000001"] and found[0]["former"]
    assert iowa[-1]["bioguide_id"] == "C000001"                      # current members first
