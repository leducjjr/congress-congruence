"""Texas Politics Project: published statewide toplines, compared with Texas's senators only."""

import os

import pytest

from congress_congruence.ingest import tpp


def test_estimate_uses_those_who_took_a_side():
    a = tpp.estimate(32, 45, 3.28, 1200)
    assert round(a.support, 4) == round(32 / 77, 4)
    assert a.majority == "oppose"                                # 41.6%, range well under 50%
    assert a.state == "TX" and a.district is None
    assert round(a.effective_n) == 893                           # (0.98 / 0.0328)^2
    assert tpp.estimate(54, 30, 3.58, 1200).majority == "support"
    assert tpp.estimate(41, 47, 3.47, 1200).majority == "too_close"   # 46.6%, range reaches 50%


def test_items_file_is_well_formed():
    cfg = tpp.load_config()
    assert [p["survey"] for p in cfg["polls"]] == ["Texas Politics Project, Aug 2025", "Texas Politics Project, Jun 2026",
                                                   "Texas Politics Project, Aug 2026"]
    for poll in cfg["polls"]:
        assert poll["source"]["organization"] == "Texas Politics Project"
        assert poll["source"]["dataset_url"].startswith("https://texaspolitics.utexas.edu/files/")
        for item in poll["items"].values():
            assert set(item["votes"]) == {"senate"} and item["url"] == poll["source"]["dataset_url"]
    iran = cfg["polls"][1]["items"]["TPP2606_Q36"]["votes"]["senate"]
    end = cfg["polls"][2]["items"]["TPP2608_Q33"]["votes"]["senate"]
    assert iran["support_side"] == "nay" and end["support_side"] == "yea"
    assert iran["expect"] == end["expect"] == "50-48" and str(end["date"]) == "2026-06-23"


def test_rejects_house_comparisons(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("polls:\n  - {survey: s, congress: 119, moe: 3, respondents: 1200, source: {}, items: "
                 "{A: {question: q, favor: 40, oppose: 50, url: u, votes: {house: {roll_call: x}}}}}\n")
    with pytest.raises(ValueError, match="senators only"):
        tpp.load_config(p)


CFG = {"polls": [{
    "survey": "Texas Politics Project, Jun 2026", "congress": 119, "moe": 3.47, "respondents": 1200,
    "source": {"title": "t", "organization": "Texas Politics Project", "description": "d", "fielded": "June 2026",
               "asked": "registered_voters",
               "dataset_url": "https://example.org/topline.pdf"},
    "items": {"Q36": {"question": "Approve of U.S. military actions against Iran", "favor": 30, "oppose": 60,
                      "url": "https://example.org/topline.pdf", "match": "related",
                      "votes": {"senate": {"date": "2026-06-23", "expect": "50-48", "support_side": "nay"}}}}}]}


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
            cur.execute("insert into core.member (bioguide_id, first_name, last_name) values ('S000001', 'T', 'Senator')")
            cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                           values ('S000001', 'senate', 'TX', null, 'Republican', '2025-01-03', '2031-01-03')""")
            cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                           vote_date, question, result, yea_total, nay_total, source)
                           values ('s-119-2-200', 'senate', 119, 2, 200, '2026-06-23', 'On the Joint Resolution',
                                   'Passed', 50, 48, 'test')""")
            cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                        "values ('s-119-2-200', 'S000001', 'nay', 'Nay')")
        c.commit()
        yield c


def test_load_stores_a_statewide_row_per_question(conn):
    out = tpp.load(conn, CFG)
    assert out == {"polls": 1, "items": 1, "votes_linked": 1, "calls": {"support": 0, "oppose": 1, "too_close": 0}}
    with conn.cursor() as cur:
        cur.execute("select organization, kind, respondents, asked from core.survey")
        assert cur.fetchall() == [("Texas Politics Project", "survey", 1200, "registered_voters")]
        cur.execute("select state, district, method, source_url from core.opinion_estimate")
        assert cur.fetchall() == [("TX", None, "published-topline-v1", "https://example.org/topline.pdf")]
        cur.execute("select support_side, match_kind from core.survey_item_vote")
        assert cur.fetchall() == [("nay", "related")]


def test_a_question_without_a_vote_loads_nothing(conn):
    bad = {"polls": [{**CFG["polls"][0], "items": {"Q36": {**CFG["polls"][0]["items"]["Q36"],
                                                           "votes": {"senate": {"date": "2026-06-23", "expect": "51-47"}}}}}]}
    with pytest.raises(ValueError, match="no vote found"):
        tpp.load(conn, bad)
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.survey")
        assert cur.fetchone() == (0,)


def test_every_poll_says_registered_voters():
    assert {p["source"]["asked"] for p in tpp.load_config()["polls"]} == {"registered_voters"}
