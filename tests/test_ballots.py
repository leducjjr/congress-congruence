"""State ballot measures: certified results stored beside the surveys, compared only statewide."""

import os

import pytest

from congress_congruence.ingest import ballots

CFG = {
    "survey": "Ballot measures 2024", "congress": 119,
    "source": {"title": "Test ballots", "organization": "State ballot measures", "description": "d",
               "fielded": "November 5, 2024"},
    "items": {"CIT": {"question": "Only citizens may vote", "match": "related",
                      "votes": {"senate": {"roll_call": "s-119-1-50"}, "house": {"roll_call": "h-119-1-60"}},
                      "results": [
                          {"state": "ID", "measure": "Idaho HJR 5", "yes_votes": 650, "no_votes": 350, "url": "https://example.org/id"},
                          {"state": "WY", "measure": "Wyoming Amendment A", "yes_votes": 400, "no_votes": 600, "url": "https://example.org/wy"}]}},
}


def test_result_row_is_the_share_of_votes_cast():
    r = ballots.result_row({"state": "ID", "measure": "m", "yes_votes": 572865, "no_votes": 309456, "url": "u"})
    assert r["majority"] == "support" and r["votes"] == 882321 and round(r["support"], 4) == 0.6493
    assert ballots.result_row({"state": "X", "measure": "m", "yes_votes": 5, "no_votes": 5, "url": "u"})["majority"] == "too_close"
    assert ballots.result_row({"state": "X", "measure": "m", "yes_votes": 4, "no_votes": 6, "url": "u"})["majority"] == "oppose"


def test_2024_items_file_is_well_formed():
    cfg = ballots.load_config(2024)
    assert cfg["kind"] == "ballot"
    for item in cfg["items"].values():
        assert item["match"] == "related"          # no measure asked exactly what Congress voted on
        assert item["results"] and all(r["url"].startswith("https://") for r in item["results"])


def test_rejects_missing_counts(monkeypatch, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ballot_2030_items.yaml").write_text(
        "survey: x\nitems:\n  A:\n    question: q\n    results:\n      - {state: ID, measure: m, yes_votes: 1, url: u}\n")
    monkeypatch.setattr(ballots.config, "PROJECT_ROOT", tmp_path)
    with pytest.raises(ValueError, match="missing"):
        ballots.load_config(2030)


@pytest.fixture
def conn():
    from congress_congruence import db
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with db.connect(url) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core cascade")
        c.commit()
        db.migrate(c)
        with c.cursor() as cur:
            members = [("S000001", "senate", "ID", None), ("S000002", "senate", "NV", None),
                       ("H000001", "house", "WY", 0), ("H000002", "house", "ID", 1)]
            for bio, chamber, state, district in members:
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'T', %s)", (bio, bio))
                cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                               values (%s, %s, %s, %s, 'Republican', '2023-01-03', '2027-01-03')""",
                            (bio, chamber, state, district))
            for rid, chamber, roll in [("s-119-1-50", "senate", 50), ("h-119-1-60", "house", 60)]:
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, result, yea_total, nay_total, source)
                               values (%s, %s, 119, 1, %s, '2025-06-01', 'On Passage', 'x', 50, 48, 'test')""",
                            (rid, chamber, roll))
            for rid, bio, pos in [("s-119-1-50", "S000001", "yea"), ("s-119-1-50", "S000002", "nay"),
                                  ("h-119-1-60", "H000001", "yea"), ("h-119-1-60", "H000002", "yea")]:
                cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                            "values (%s, %s, %s, %s)", (rid, bio, pos, pos))
        c.commit()
        yield c


def client_for(monkeypatch):
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    return TestClient(api.app)


def test_load_compares_senators_and_at_large_seats_only(conn, monkeypatch):
    monkeypatch.setattr(ballots, "load_config", lambda year: CFG)
    out = ballots.load(conn, 2024)
    assert out == {"items": 1, "votes_linked": 2, "area_rows": 3}     # ID, WY, and WY's at-large seat
    with conn.cursor() as cur:
        cur.execute("select kind from core.survey")
        assert cur.fetchone() == ("ballot",)
        cur.execute("select state, district, support_low = support_high, area_note from core.opinion_estimate order by 1, 2")
        assert cur.fetchall() == [("ID", None, True, "Idaho HJR 5"), ("WY", 0, True, "Wyoming Amendment A"),
                                  ("WY", None, True, "Wyoming Amendment A")]

    with client_for(monkeypatch) as client:
        s = client.get("/v1/members/S000001/opinion").json()
        wy = client.get("/v1/members/H000001/opinion").json()
        id1 = client.get("/v1/members/H000002/opinion").json()
        (card,) = client.get("/v1/surveyed").json()["questions"]
        listed = client.get("/v1/surveys").json()["surveys"]
    (item,) = s["items"]
    assert item["kind"] == "ballot" and item["match"] == "related"
    assert item["constituents"]["area_note"] == "Idaho HJR 5" and item["constituents"]["respondents"] == 1000
    assert item["wording_url"] == "https://example.org/id" and item["wording_hint"] is None
    assert s["summary"]["related_votes"] == 1 and s["summary"]["surveyed_votes"] == 0   # never scored
    assert s["samples"] == []                                                          # votes cast, not people surveyed
    assert s["surveys"][0]["kind"] == "ballot"
    assert wy["items"][0]["constituents"]["support_pct"] == 40.0                       # at-large seat compared
    assert id1["items"] == []                                                          # a district isn't the state
    assert card["source"]["kind"] == "ballot" and set(card["spread"]) == {"states"}
    assert card["spread"]["states"] == {"areas": 2, "lowest_pct": 40.0, "highest_pct": 65.0,
                                        "support": 1, "oppose": 1, "too_close": 0}
    assert listed[0]["kind"] == "ballot"
