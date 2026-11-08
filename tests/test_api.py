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
    ("/v1/members?state=ZZ", 400), ("/v1/members/D000001/votes?limit=500", 422),
])
def test_bad_requests(client, path, code):
    assert client.get(path).status_code == code


def test_health_reports_freshness(client):
    h = client.get("/v1/health").json()
    assert h["status"] == "ok"
    assert h["data"][0]["latest_vote"] == "2025-03-03"


def test_connections_are_read_only(client):
    import psycopg
    with client.api.pool.connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("delete from core.member_vote")
