"""Published statewide polls (UNH Survey Center and others): config checks, design effect, at-large seats."""

import os

import pytest

from congress_congruence.ingest import statepolls


def test_unh_items_file_is_well_formed():
    cfg = statepolls.load_config("unh")
    states = {p["state"] for p in cfg["polls"]}
    assert states == {"NH", "ME", "VT", "MA", "CT", "RI"}
    for poll in cfg["polls"]:
        assert poll["source"]["organization"] == "UNH Survey Center" and poll["source"]["asked"] == "adults"
        # The March 2026 six-state poll gives no design effect; every other release does.
        assert poll.get("design_effect", 0) > 1 or poll["survey"].startswith("States of Opinion Poll, Mar 2026")
        assert poll["source"]["dataset_url"].startswith("https://scholars.unh.edu/")
        has_house = "house" in str(poll["items"])
        assert has_house == bool(poll.get("at_large")) and (not has_house or poll["state"] == "VT")
        for item in poll["items"].values():
            assert item["favor"] + item["oppose"] <= 100 and item["url"].startswith("https://scholars.unh.edu/")
    # Every Iran question is compared with the Senate's June 23, 2026 war powers vote (decided Nov 16, 2026).
    iran = [i["votes"]["senate"] for p in cfg["polls"] for v, i in p["items"].items()
            if v.startswith(("UNH2603", "UNH2606", "UNH2609"))]
    assert len(iran) == 23 and {str(r["date"]) for r in iran} == {"2026-06-23"}


def test_design_effect_widens_the_range():
    plain = statepolls.estimate(33, 56, 2.7, 1320, "NH")
    wider = statepolls.estimate(33, 56, 2.7, 1320, "NH", None, 2.1)
    assert plain.support == wider.support and (wider.high - wider.low) > (plain.high - plain.low) * 1.4


def test_house_needs_an_at_large_state(tmp_path):
    p = tmp_path / "x_items.yaml"
    p.write_text("polls:\n  - {survey: s, state: NH, congress: 119, moe: 3, respondents: 900, source: {t: 1}, items: "
                 "{A: {question: q, favor: 40, oppose: 50, url: u, votes: {house: {roll_call: x}}}}}\n")
    with pytest.raises(ValueError, match="at-large"):
        statepolls.load_config(p)


CFG = {"polls": [{
    "survey": "Green Mountain State Poll, Jan 2026", "state": "VT", "at_large": True, "congress": 119,
    "respondents": 765, "moe": 3.5, "design_effect": 2.3,
    "source": {"title": "t", "organization": "UNH Survey Center", "description": "d", "asked": "adults",
               "dataset_url": "https://example.org/vt.pdf"},
    "items": {"ACA": {"question": "Extend the ACA subsidies", "favor": 74, "oppose": 19, "url": "https://example.org/vt.pdf",
                      "votes": {"senate": {"roll_call": "s-119-1-600", "match": "related"},
                                "house": {"roll_call": "h-119-2-11"}}},
              "SEN": {"question": "A Senate-only question", "favor": 40, "oppose": 50, "url": "https://example.org/vt.pdf",
                      "votes": {"senate": {"roll_call": "s-119-1-600"}}}}}]}


@pytest.fixture
def conn():
    from congress_congruence import db
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with db.connect(url) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core, history cascade")
        c.commit()
        db.migrate(c)
        with c.cursor() as cur:
            for bio, chamber, district in (("S000001", "senate", None), ("H000001", "house", 0)):
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'T', %s)", (bio, bio))
                cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                               values (%s, %s, 'VT', %s, 'Independent', '2025-01-03', '2027-01-03')""", (bio, chamber, district))
            for rid, chamber, sess, roll, day, yea, nay in (("s-119-1-600", "senate", 1, 600, "2025-12-11", 51, 48),
                                                             ("h-119-2-11", "house", 2, 11, "2026-01-08", 230, 196)):
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, result, yea_total, nay_total, source)
                               values (%s, %s, 119, %s, %s, %s, 'On Passage', 'x', %s, %s, 'test')""",
                            (rid, chamber, sess, roll, day, yea, nay))
        c.commit()
        yield c


def test_at_large_state_gets_its_house_member_compared(conn):
    out = statepolls.load(conn, CFG)
    assert out["votes_linked"] == 3
    with conn.cursor() as cur:
        cur.execute("select variable, district from core.opinion_estimate order by 1, district nulls first")
        assert cur.fetchall() == [("ACA", None), ("ACA", 0), ("SEN", None)]   # no district row without a House vote
        cur.execute("select variable, chamber, match_kind from core.survey_item_vote order by 1, 2")
        assert cur.fetchall() == [("ACA", "house", "same"), ("ACA", "senate", "related"), ("SEN", "senate", "same")]
