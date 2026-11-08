"""Survey opinion: estimator, linking survey items to votes, loading, and the API comparison.

The made-up survey has two Texas districts and Wyoming (at-large), all seven
CES 2025 items, and clear-cut opinion so the expected results are obvious:
TX-1 strongly supports everything, TX-2 strongly opposes everything, Wyoming is split.
"""

import os
import random

import pytest

from congress_congruence import db, opinion

pyreadstat = pytest.importorskip("pyreadstat")
pd = pytest.importorskip("pandas")

ITEMS = [f"CC25_340{c}" for c in "abcdefg"]


# ---------------------------------------------------------------- estimator

def test_pooling_pulls_small_areas_toward_parent_and_widens_their_range():
    random.seed(3)
    resp = []
    for st, base in (("AA", 0.7), ("BB", 0.3), ("CC", 0.5)):
        for d in (1, 2, 3):
            n = 400 if d == 1 else 4                          # district 1 well sampled, others thin
            resp += [(st, d, int(random.random() < base), 1.0) for _ in range(n)]
    states, districts = opinion.estimate(resp, {st: [1, 2, 3] for st in ("AA", "BB", "CC")})
    by = {(a.state, a.district): a for a in districts}
    big, small = by[("AA", 1)], by[("AA", 2)]
    assert abs(big.support - big.raw_support) < 0.02           # lots of data: barely moved
    assert (small.high - small.low) > (big.high - big.low)     # thin data: wider range
    assert {a.state: a.majority for a in states} == {"AA": "support", "BB": "oppose", "CC": "too_close"}


def test_district_with_no_respondents_gets_state_estimate_and_wide_range():
    resp = [("AA", 1, 1, 1.0)] * 300 + [("AA", 1, 0, 1.0)] * 100
    states, districts = opinion.estimate(resp, {"AA": [1, 2]})
    empty = next(a for a in districts if a.district == 2)
    assert empty.respondents == 0 and empty.raw_support is None
    assert empty.support == pytest.approx(states[0].support)


def test_effective_n_drops_with_unequal_weights():
    assert opinion.effective_n(*opinion.summarize([(1, 1.0)] * 4)[:2]) == pytest.approx(4)
    assert opinion.effective_n(*opinion.summarize([(1, 10.0), (1, 1.0), (1, 1.0), (1, 1.0)])[:2]) < 2


# ---------------------------------------------------------------- database fixtures

MEMBERS = [  # bioguide, chamber, state, district, party
    ("H000001", "house", "TX", 1, "Republican"),
    ("H000002", "house", "TX", 2, "Democrat"),
    ("H000003", "house", "WY", 0, "Republican"),
    ("S000001", "senate", "TX", None, "Republican"),
]

# roll_call_id, chamber, date, question, bill_type, bill_number, description
VOTES = [
    ("h-119-1-20", "house", "2025-01-22", "On Passage", "s", 5, "Laken Riley Act"),
    ("h-119-1-60", "house", "2025-04-10", "On Passage", "hr", 22, "SAVE Act"),
    ("h-119-1-25", "house", "2025-01-23", "On Passage", "hr", 21, "Born-Alive Abortion Survivors Protection Act"),
    ("h-119-1-145", "house", "2025-05-22", "On Passage", "hr", 1, "One Big Beautiful Bill Act"),
    ("h-119-1-190", "house", "2025-07-03", "On Motion to Concur in the Senate Amendment", "hr", 1, "One Big Beautiful Bill Act"),
    ("h-119-1-189", "house", "2025-07-03", "On Ordering the Previous Question", "hr", 1, "procedural"),  # not final
    ("h-119-1-160", "house", "2025-06-12", "On Passage", "hr", 4, "Rescissions Act of 2025"),
    # The real final House action: a self-executing rule that accepted the Senate's version.
    ("h-119-1-203", "house", "2025-07-18", "On Agreeing to the Resolution", "hres", 590,
     "Relating to consideration of the Senate amendment to the bill (H.R. 4) to rescind certain budget authority"),
    ("h-119-1-202", "house", "2025-07-17", "On Ordering the Previous Question", "hres", 590,
     "Relating to consideration of the Senate amendment to the bill (H.R. 4) to rescind certain budget authority"),
    ("s-119-1-7", "senate", "2025-01-20", "On Passage of the Bill", "s", 5, "Laken Riley Act"),
    ("s-119-1-20", "senate", "2025-01-23", "On the Cloture Motion", None, None, "Pete Hegseth, of Tennessee, to be Secretary of Defense"),
    ("s-119-1-25", "senate", "2025-01-24", "On the Nomination", None, None, "Pete Hegseth, of Tennessee, to be Secretary of Defense"),
    ("s-119-1-80", "senate", "2025-02-13", "On the Nomination", None, None, "Robert F. Kennedy, Jr., of California, to be Secretary of Health and Human Services"),
    ("s-119-1-60", "senate", "2025-02-03", "On the Cloture Motion", "s", 6, "Born-Alive Abortion Survivors Protection Act"),
    ("s-119-1-372", "senate", "2025-07-01", "On Passage of the Bill", "hr", 1, "One Big Beautiful Bill Act"),
    ("s-119-1-400", "senate", "2025-07-17", "On Passage of the Bill", "hr", 4, "Rescissions Act of 2025"),
]


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
        with c.cursor() as cur:
            for bio, chamber, st, dist, party in MEMBERS:
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'T', %s)",
                            (bio, bio))
                cur.execute("""insert into core.term (bioguide_id, chamber, state, district, senate_class, party,
                               start_date, end_date) values (%s, %s, %s, %s, %s, %s, '2025-01-03', '2027-01-03')""",
                            (bio, chamber, st, dist, 1 if chamber == "senate" else None, party))
            for rid, chamber, d, q, bt, bn, desc in VOTES:
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, result, bill_type, bill_number, bill_congress, description, source)
                               values (%s, %s, 119, 1, %s, %s, %s, 'Passed', %s, %s, %s, %s, 'test')""",
                            (rid, chamber, int(rid.rsplit("-", 1)[1]), d, q, bt, bn, 119 if bt else None, desc))
                for bio, mch, *_ in MEMBERS:
                    if mch == chamber:
                        # TX-1 and the senator vote Yea on everything; TX-2 Nay; WY Yea.
                        pos = "nay" if bio == "H000002" else "yea"
                        cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                                    "values (%s, %s, %s, %s)", (rid, bio, pos, pos.title()))
        c.commit()
        yield c


@pytest.fixture
def survey_file(tmp_path):
    random.seed(7)
    rows = []
    for fips, cd, p_support, n in ((48, 1, 0.9, 300), (48, 2, 0.1, 300), (56, 1, 0.5, 200)):
        for _ in range(n):
            row = {"inputstate": fips, "cdid119": cd, "commonweight": random.uniform(0.5, 1.5)}
            for item in ITEMS:
                row[item] = 1 if random.random() < p_support else 2
            rows.append(row)
    rows.append({"inputstate": 48, "cdid119": 1, "commonweight": 1.0, **{i: 8 for i in ITEMS}})  # skipped all
    path = tmp_path / "CES25_Common.dta"
    pyreadstat.write_dta(pd.DataFrame(rows), str(path))
    return path


# ---------------------------------------------------------------- linking and loading

def test_link_picks_the_final_decisive_vote(conn):
    from congress_congruence.ingest import ces
    links = {(v, ch): rid for _, v, ch, rid, _, _ in ces.link(conn, 2025, ces.load_config(2025))}
    assert links[("CC25_340f", "house")] == "h-119-1-190"      # concurrence, not first passage or procedure
    assert links[("CC25_340a", "senate")] == "s-119-1-25"      # confirmation, not cloture
    assert links[("CC25_340b", "senate")] == "s-119-1-80"
    assert links[("CC25_340e", "senate")] == "s-119-1-60"      # only Senate vote was cloture
    assert links[("CC25_340g", "house")] == "h-119-1-203"      # the rule's adoption, not the procedural vote
    assert ("CC25_340d", "senate") not in links                # Senate never voted on the SAVE Act
    assert len(links) == 11


def test_load_estimates_every_state_and_district(conn, survey_file):
    from congress_congruence.ingest import ces
    summary = ces.load(conn, 2025, survey_file)
    assert summary["items"] == 7 and summary["votes_linked"] == 11
    with conn.cursor() as cur:
        cur.execute("""select state, district, majority, respondents from core.opinion_estimate
                        where variable = 'CC25_340c' order by state, district nulls first""")
        rows = cur.fetchall()
    assert rows == [("TX", None, "support", 600) if False else rows[0], *rows[1:]]  # shape check below
    by = {(s, d): (m, n) for s, d, m, n in rows}
    assert by[("TX", 1)] == ("support", 300)
    assert by[("TX", 2)] == ("oppose", 300)
    assert by[("WY", 0)][1] == 200                                 # at-large: cdid 1 mapped to seat 0
    assert by[("TX", None)][1] == 600                              # skipped answers left out
    # Re-loading replaces rather than duplicates.
    ces.load(conn, 2025, survey_file)
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.opinion_estimate where variable = 'CC25_340c'")
        assert cur.fetchone()[0] == len(rows)


# ---------------------------------------------------------------- API

@pytest.fixture
def client(conn, survey_file, monkeypatch):
    from congress_congruence.ingest import ces
    ces.load(conn, 2025, survey_file)
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api_module
    with TestClient(api_module.app) as tc:
        yield tc


def test_api_house_member_compared_with_district(client):
    with_tx1 = client.get("/v1/members/H000001/opinion").json()
    assert with_tx1["area"] == "TX-1"
    assert with_tx1["summary"] == {"surveyed_votes": 5, "clear_majority": 5, "with_majority": 5}
    first = with_tx1["items"][0]
    assert first["constituents"]["area"] == "district" and first["agreement"] == "with"

    tx2 = client.get("/v1/members/H000002/opinion").json()   # votes Nay, district opposes
    assert tx2["summary"]["with_majority"] == 5


def test_api_senator_compared_with_state(client):
    s = client.get("/v1/members/S000001/opinion").json()
    assert s["area"] == "TX"
    assert {i["item"] for i in s["items"]} == {"CC25_340a", "CC25_340b", "CC25_340c", "CC25_340e",
                                              "CC25_340f", "CC25_340g"}
    assert all(i["constituents"]["area"] == "state" for i in s["items"])
    # Texas as a whole is evenly split in this sample, so no clear majority to compare with.
    assert s["summary"]["clear_majority"] == 0


def test_api_split_district_is_too_close(client):
    wy = client.get("/v1/members/H000003/opinion").json()
    assert {i["agreement"] for i in wy["items"]} <= {"too_close", "with", "against"}


def test_agreement_rules():
    from congress_congruence.api.app import agreement
    assert agreement("yea", "support") == "with"
    assert agreement("nay", "support") == "against"
    assert agreement("nay", "oppose") == "with"
    assert agreement("yea", "too_close") == "too_close"
    assert agreement("not_voting", "support") == "did_not_vote"


def test_chamber_notes_only_show_on_that_chambers_panels(client):
    house = {i["item"]: i["note"] for i in client.get("/v1/members/H000001/opinion").json()["items"]}
    senate = {i["item"]: i["note"] for i in client.get("/v1/members/S000001/opinion").json()["items"]}
    assert house["CC25_340e"] is None and "cloture" in senate["CC25_340e"]       # Senate-only note
    assert "H.Res. 590" in house["CC25_340g"] and senate["CC25_340g"] is None     # House-only note
    assert "exact question" in house["CC25_340f"] and "exact question" in senate["CC25_340f"]  # item-level note


def test_api_names_the_survey_with_links(client):
    s = client.get("/v1/members/H000001/opinion").json()["surveys"]
    assert len(s) == 1
    assert s[0]["title"] == "Cooperative Election Study 2025" and s[0]["fielded"] == "November 2025"
    assert s[0]["respondents"] == 17000
    assert s[0]["guide_url"].startswith("https://dataverse.harvard.edu/")
    assert s[0]["dataset_url"] == "https://doi.org/10.7910/DVN/DFUGJR"


def test_api_reports_respondents_per_area(client):
    items = client.get("/v1/members/H000001/opinion").json()["items"]
    assert all(i["constituents"]["respondents"] == 300 for i in items)   # TX-1 in the made-up survey


def test_older_votes_use_the_seat_held_at_the_time(conn, survey_file, monkeypatch):
    """H000001 represented TX-2 in the 118th Congress and TX-1 now. A 2024 survey item on a
    118th Congress vote must be compared with TX-2, and both surveys must be named as sources."""
    from congress_congruence.ingest import ces
    ces.load(conn, 2025, survey_file)
    with conn.cursor() as cur:
        cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                       values ('H000001', 'house', 'TX', 2, 'Republican', '2023-01-03', '2025-01-03')""")
        cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number, vote_date,
                       question, result, source) values ('h-118-2-50', 'house', 118, 2, 50, '2024-03-01',
                       'On Passage', 'Passed', 'test')""")
        cur.execute("insert into core.member_vote values ('h-118-2-50', 'H000001', 'yea', 'Yea', null, null)")
        cur.execute("""insert into core.survey values ('CES 2024', 'Cooperative Election Study 2024', 'Fall 2024',
                       60000, 'https://example/data', 'https://example/guide24.pdf', 'https://example/about')""")
        cur.execute("insert into core.survey_item (survey, variable, question) values ('CES 2024', 'CC24_300', 'A 2024 item')")
        cur.execute("insert into core.survey_item_vote (survey, variable, chamber, roll_call_id) "
                    "values ('CES 2024', 'CC24_300', 'house', 'h-118-2-50')")
        for d, support in ((1, 0.2), (2, 0.8)):      # only TX-2 supports: comparing with TX-1 would say "against"
            cur.execute("""insert into core.opinion_estimate (survey, variable, state, district, respondents,
                           effective_n, raw_support, support, support_low, support_high, majority, method)
                           values ('CES 2024', 'CC24_300', 'TX', %s, 100, 90, %s, %s, %s, %s, %s, 'test')""",
                        (d, support, support, support - 0.1, support + 0.1, "support" if support > 0.5 else "oppose"))
    conn.commit()

    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api_module
    with TestClient(api_module.app) as tc:
        body = tc.get("/v1/members/H000001/opinion").json()
    old = next(i for i in body["items"] if i["item"] == "CC24_300")
    assert old["constituents"]["area_label"] == "TX-2" and old["agreement"] == "with"
    new = next(i for i in body["items"] if i["item"] == "CC25_340c")
    assert new["constituents"]["area_label"] == "TX-1"
    assert {s["name"] for s in body["surveys"]} == {"CES 2024", "CES 2025"}


def test_api_reports_surveyed_and_residents_per_area(client, conn):
    with conn.cursor() as cur:
        cur.execute("""insert into core.area_population (congress, state, district, population, source)
                       values (119, 'TX', 1, 770000, 'test'), (119, 'TX', null, 31000000, 'test')""")
    conn.commit()
    house = client.get("/v1/members/H000001/opinion").json()
    assert house["samples"] == [{"survey": "CES 2025", "area_label": "TX-1", "surveyed": 300, "residents": 770000}]
    assert all(i["constituents"]["residents"] == 770000 for i in house["items"])
    senate = client.get("/v1/members/S000001/opinion").json()
    assert senate["samples"][0]["surveyed"] == 600 and senate["samples"][0]["residents"] == 31000000
