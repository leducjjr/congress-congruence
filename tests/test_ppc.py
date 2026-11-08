"""Tests for the Program for Public Consultation reader, on text laid out like their PDFs.

The Texas sample mirrors the real 2026 health-care questionnaire (numbers included). The Iowa
sample adds district rows in the label styles the reader accepts.
"""

import os

import pytest

from congress_congruence.ingest import ppc

TEXAS = """
                                                     HEALTHCARE COSTS
                                                      - STATE OF TEXAS and NATIONAL -
         Field Dates:
         State of Texas: May 27 – June 19, 2026
         National: February 11-26, 2026

         Sample Sizes:
         State of Texas     : 630
         National: 2,509

         Confidence Interval:
         State of Texas: +/-4.3%
         National: +/- 2.9%

Q7. Here is a proposal: Increase government spending on substance use disorder by $13 billion.


                                                                Favor                       Oppose                  Ref/DK
                             National                            75%                         25%                     0%
                                Republicans                      69%                         31%                     0%
                             Texas (Statewide)                   79%                         21%                     0%
                                Republicans                      75%                         26%                     0%

Q8. As you may know, a law was passed in 2021 which temporarily increased subsidies for health insurance in the ACA marketplace.

Here is a proposal: Renew the increased subsidies for ACA health insurance, so that low- and middle-income households on ACA will not have a major
increase in health insurance costs.

                                                                Favor                       Oppose                  Ref/DK
                             National                            81%                         19%                     0%
                                Republicans                      73%                         27%                     0%
                                Democrats                        90%                         10%                     0%
                                Independents                     80%                         20%                     0%
                             Texas (Statewide)                   81%                         19%                     0%
                                Republicans                      77%                         23%                     0%
                                Democrats                        84%                         16%                     1%

                                                                   Methodology
          State of Texas
          Field Dates: May 27 – June 19, 2026     Sample Size: 630              Response Rate: 8.4%
Q99. Not a question: anything after the methodology heading is ignored.
                             Texas (Statewide)                   11%                         89%                     0%
"""

IOWA = """
                                              HEALTHCARE COSTS
                                    - STATE OF IOWA, DISTRICTS and NATIONAL -
Sample Sizes:
State of Iowa: 1,004
IA-1: 501
District 2: 499
3rd District: 512
National: 2,509

Confidence Interval:
State of Iowa: +/-3.4%
IA-1: +/-4.9%
District 2: +/-5.0%
3rd District: +/-4.8%
National: +/- 2.9%

Q8. Here is a proposal: Renew the increased subsidies for ACA health insurance.
                                       Favor        Oppose       Ref/DK
          National                      81%          19%           0%
          Iowa (Statewide)              80%          20%           0%
             Republicans                72%          28%           0%
          IA-1                          77%          22%           1%
          District 2                    79%          21%           0%
          3rd District                  83%          17%
          Iowa's Senate seat            50%          50%           0%
"""


def test_area_labels():
    assert ppc.area_of("Texas (Statewide)", None) == ("TX", None)
    assert ppc.area_of("State of Texas", None) == ("TX", None)
    assert ppc.area_of("New Hampshire", None) == ("NH", None)
    assert ppc.area_of("IA-1", None) == ("IA", 1)
    assert ppc.area_of("NY-17", None) == ("NY", 17)
    assert ppc.area_of("District 2", "IA") == ("IA", 2)
    assert ppc.area_of("3rd District", "IA") == ("IA", 3)
    assert ppc.area_of("AK At-Large", None) == ("AK", 0)
    assert ppc.area_of("(Statewide)", "GA") == ("GA", None)          # state name wrapped to the line above
    assert ppc.area_of("Iowa CD2", None) == ("IA", 2)
    assert ppc.area_of("National", "TX") is None
    assert ppc.area_of("District 2", None) is None            # no state to put it in


def test_reads_texas_like_the_real_pdf():
    p = ppc.parse(TEXAS)
    assert p["home"] == "TX"
    assert p["sizes"] == {("TX", None): 630} and p["cis"] == {("TX", None): 0.043}
    q = ppc.find_question(p, "renew the increased subsidies")
    assert q["number"] == "8" and "Renew the increased subsidies" in q["text"]
    assert [(r["area"], r["favor"], r["oppose"]) for r in q["rows"]] == [(None, 81, 19), (("TX", None), 81, 19)]
    assert [q["number"] for q in p["questions"]] == ["7", "8"]         # Q99 is after Methodology


def test_reads_districts_and_flags_unknown_labels():
    p = ppc.parse(IOWA)
    assert p["home"] == "IA"
    assert p["sizes"][("IA", 2)] == 499 and p["cis"][("IA", 3)] == 0.048
    q = ppc.find_question(p, "subsidies")
    areas = {r["area"]: (r["favor"], r["oppose"], r["dk"]) for r in q["rows"] if r["area"]}
    assert areas == {("IA", None): (80, 20, 0), ("IA", 1): (77, 22, 1), ("IA", 2): (79, 21, 0),
                     ("IA", 3): (83, 17, None)}
    assert q["unread_labels"] == ["Iowa's Senate seat"]                 # reported, never guessed


# As in the real 2026 Iowa PDFs: several areas per header line, one shared interval given as a
# range, and a short question that relies on the paragraph before it.
IOWA_REAL = """
                                              HEALTHCARE COSTS
                                    - STATE OF IOWA, CD1, CD2, CD3, CD4, and NATIONAL -
          Field Dates:
          State of Iowa, Iowa CD1, Iowa CD2, Iowa CD3, Iowa CD4: May 27 – June 23, 2026
          National: February 11-26, 2026

          Sample Sizes:
          State of Iowa:    2000           Iowa CD1: 500         Iowa CD2: 500         Iowa CD3: 500         Iowa CD4: 500
          National: 2,509

          Confidence Interval:
          State of Iowa: +/-2.9%           Iowa CD1, Iowa CD2, Iowa CD3, Iowa CD4: +/-5.5-6.0%
          National: +/- 2.9%

Q9. Some other question.
                                   Favor          Oppose        Ref/DK
          National                  80%            20%           0%
          Iowa (Statewide)          81%            19%           0%

Proposals have been put forward to prohibit high-level officials in the federal government from trading stocks in
individual companies. They would still be allowed to buy or sell shares of funds that include stocks in numerous
companies. For each group of federal officials, please say whether you favor or oppose prohibiting them from trading
stocks in individual companies.


Q10. Members of Congress


                                   Favor          Oppose        Ref/DK
          National                  76%            24%           0%
             Republicans            78%            22%           0%
          Iowa (statewide)          78%            21%           1%
             Democrats              82%            17%           1%
          Iowa CD1                  75%            24%           1%
          Iowa CD4                  85%            15%           0%

Q11. The President, Vice President and Supreme Court Justices
                                   Favor          Oppose        Ref/DK
          National                  71%            29%           0%
          Iowa (statewide)          70%            30%           0%
"""


def test_reads_the_real_district_layout():
    p = ppc.parse(IOWA_REAL)
    assert p["home"] == "IA"
    assert p["sizes"] == {("IA", None): 2000, ("IA", 1): 500, ("IA", 2): 500, ("IA", 3): 500, ("IA", 4): 500}
    assert p["cis"] == {("IA", None): 0.029, ("IA", 1): 0.06, ("IA", 2): 0.06, ("IA", 3): 0.06, ("IA", 4): 0.06}
    find = ppc.load_config(2026)["items"]["PPC26_STOCKS"]["find"]
    q = ppc.find_question(p, find)
    assert q["number"] == "10" and q["intro"].startswith("Proposals have been put forward")
    assert {r["area"]: r["favor"] for r in q["rows"] if r["area"]} == {("IA", None): 78, ("IA", 1): 75, ("IA", 4): 85}
    assert ppc.find_question(p, "Supreme Court")["number"] == "11"     # no lead-in carried past a table


def test_header_layouts_from_maine_and_michigan():
    maine = """
          Sample Sizes:
          State of Maine:     800                       Maine CD2: 500
          National: 2,509

          Confidence Interval:
          State of Maine +/- 6.6%                       Maine CD2: +/- 5.7%
          National: +/- 2.9%
"""
    michigan = """
        Sample Sizes:
        State of Michigan: 600            Michigan CD4: 509        Michigan CD7: 505         Michigan CD8: 516
        Michigan CD10: 499       National: 2,509


        Confidence Interval:
        State of Michigan+/-4.2%         Michigan CD4+/-6.7%            Michigan CD7: +/-6.1%            Michigan CD8:
        +/-6.6%
        Michigan CD10: +/-6.2%                    National: +/- 2.9%
"""
    def read(text, heading):
        return {ppc.area_of(k, None): v for k, v in ppc.header_values(text, heading) if ppc.area_of(k, None)}
    assert read(maine, "Sample Sizes") == {("ME", None): "800", ("ME", 2): "500"}
    assert read(maine, "Confidence Interval") == {("ME", None): "6.6", ("ME", 2): "5.7"}
    assert read(michigan, "Sample Sizes") == {("MI", None): "600", ("MI", 4): "509", ("MI", 7): "505",
                                              ("MI", 8): "516", ("MI", 10): "499"}
    assert read(michigan, "Confidence Interval") == {("MI", None): "4.2", ("MI", 4): "6.7", ("MI", 7): "6.1",
                                                     ("MI", 8): "6.6", ("MI", 10): "6.2"}
    assert ("National", "2,509") in ppc.header_values(michigan, "Sample Sizes")


def test_estimate_uses_published_interval_at_the_90_percent_level():
    a = ppc.estimate(56, 43, 0.045, 600, "TX", None)                   # Texas, Ukraine aid
    assert a.support == pytest.approx(56 / 99)
    half = 0.045 * (1.9 / 1.96) / 0.99
    assert (a.low, a.high) == (pytest.approx(56 / 99 - half), pytest.approx(56 / 99 + half))
    assert a.majority == "support" and a.effective_n == pytest.approx(493.8, abs=0.1)
    assert ppc.estimate(52, 47, 0.045, 600, "TX", None).majority == "too_close"


def test_finds_the_topic_pdf_on_a_page():
    page = """<a href="/wp-content/uploads/2026/07/CG-Questionnaire-Texas-Healthcare-Costs-2026.pdf#page=3">x</a>
              <a href='https://publicconsultation.org/wp-content/uploads/2026/10/CG_Questionnaire_Texas_-_Americas_Role.pdf'>y</a>
              <a href="https://vop.org/wp-content/uploads/2026/11/Texas_Findings.pdf">summary</a>"""
    links = ppc.pdf_links(page, "https://vop.org/battlegrounds-texas/")
    assert links[0] == "https://vop.org/wp-content/uploads/2026/07/CG-Questionnaire-Texas-Healthcare-Costs-2026.pdf"
    assert ppc.pick_pdf(links, ["healthcare"]) == links[0]
    assert ppc.pick_pdf(links, ["health-care"]) == links[0]             # punctuation doesn't matter
    assert ppc.pick_pdf(links, ["americas", "role"]).endswith("Americas_Role.pdf")
    assert ppc.pick_pdf(links, ["findings"]) is None                    # not a questionnaire


def test_at_large_state_figure_stands_for_its_district():
    rows = [{"item": "X", "state": "AK", "district": "", "favor": "60", "oppose": "40", "n": "600",
             "ci": "0.045", "source_url": "u"},
            {"item": "X", "state": "TX", "district": "", "favor": "60", "oppose": "40", "n": "600",
             "ci": "0.045", "source_url": "u"}]
    got = [(a.state, a.district) for _, a, _ in ppc.area_estimates(rows, {"AK": [0], "TX": [1, 2]})]
    assert got == [("AK", None), ("AK", 0), ("TX", None)]


def test_2026_items_file_is_well_formed():
    cfg = ppc.load_config(2026)
    assert cfg["congress"] == 119 and cfg["pages"]
    assert cfg["items"]["PPC26_UKRAINE"]["votes"]["house"]["support_side"] == "nay"
    assert cfg["items"]["PPC26_STOCKS"]["match"] == "related"
    for item in cfg["items"].values():
        assert item["question"] and item["pdf"] and item["find"] and item["votes"]
    assert ppc.find_question(ppc.parse(TEXAS), cfg["items"]["PPC26_ACA"]["find"])["number"] == "8"


# ---------------------------------------------------------------- with a database

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
            for bio, district, pos_aca, pos_ukr in [("A000001", 1, "yea", "nay"), ("B000001", 2, "nay", "yea")]:
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'T', %s)",
                            (bio, bio))
                cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                               values (%s, 'house', 'IA', %s, 'Republican', '2025-01-03', '2027-01-03')""",
                            (bio, district))
            votes = [("h-119-1-255", 1, 255, "2025-09-10", "On Agreeing to the Amendment", 60, 372),
                     ("h-119-2-10", 2, 10, "2026-01-08", "On Motion to Recommit", 200, 226),
                     ("h-119-2-11", 2, 11, "2026-01-08", "On Passage", 230, 196)]
            for rid, sess, roll, day, question, y, n in votes:
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                               vote_date, question, result, yea_total, nay_total, source)
                               values (%s, 'house', 119, %s, %s, %s, %s, 'x', %s, %s, 'house_clerk')""",
                            (rid, sess, roll, day, question, y, n))
            for rid, positions in [("h-119-2-11", {"A000001": "yea", "B000001": "nay"}),
                                   ("h-119-1-255", {"A000001": "nay", "B000001": "yea"})]:
                for bio, pos in positions.items():
                    cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                                "values (%s, %s, %s, %s)", (rid, bio, pos, pos))
        c.commit()
        yield c


def test_rules_pick_by_date_and_tally(conn):
    from congress_congruence.ingest import ces
    vote, n = ces.match_vote(conn, "house", 119, {"date": "2026-01-08", "expect": "230-196"})
    assert vote["roll_call_id"] == "h-119-2-11" and n == 1
    assert ces.match_vote(conn, "house", 119, {"date": "2026-01-08", "expect": "231-195"}) == (None, 0)
    assert ces.match_vote(conn, "house", 119, {"roll_call": "h-119-1-255"})[0]["yea_total"] == 60


def test_load_and_compare(conn, monkeypatch, tmp_path):
    from congress_congruence.api import app as api
    cfg = {"survey": "PPC 2026", "congress": 119,
           "source": {"title": "Test PPC", "organization": "Program for Public Consultation", "description": "d"},
           "pages": [],
           "items": {
               "ACA": {"question": "Renew ACA subsidies", "pdf": ["healthcare"], "find": "x",
                       "votes": {"house": {"date": "2026-01-08", "questions": ["On Passage"], "expect": "230-196"}}},
               "UKR": {"question": "Aid Ukraine", "pdf": ["role"], "find": "x",
                       "votes": {"house": {"roll_call": "h-119-1-255", "support_side": "nay"}}},
               "REL": {"question": "Something close", "pdf": ["reform"], "find": "x", "match": "related",
                       "votes": {"house": {"roll_call": "h-119-1-255"}}}}}
    rows = [{"item": i, "state": "IA", "district": d, "favor": f, "oppose": o, "n": "500", "ci": "0.049",
             "source_url": f"https://example.org/{i}.pdf"}
            for i, f, o in [("ACA", "80", "20"), ("UKR", "70", "30"), ("REL", "70", "30")] for d in ("", "1", "2")]
    monkeypatch.setattr(ppc, "load_config", lambda year: cfg)
    monkeypatch.setattr(ppc, "read_results", lambda year: rows)
    result = ppc.load(conn, 2026)
    assert result["items"] == 3 and result["votes_linked"] == 3

    with conn.cursor() as cur:
        cur.execute("select variable, support_side, match_kind from core.survey_item_vote order by variable")
        assert cur.fetchall() == [("ACA", "yea", "same"), ("REL", "yea", "related"), ("UKR", "nay", "same")]

    # Through the API. Member A: Yea on ACA (with the 80% majority) and Nay on the amendment
    # blocking Ukraine aid, i.e. for aid (with the 70% majority). Member B: the opposite on both.
    # The related item is listed but never scored.
    from fastapi.testclient import TestClient
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(api.app) as client:
        a = client.get("/v1/members/A000001/opinion").json()
        b = client.get("/v1/members/B000001/opinion").json()
    by_item = {i["item"]: i for i in a["items"]}
    assert by_item["UKR"]["sided_with"] == "support" and by_item["UKR"]["agreement"] == "with"
    assert by_item["REL"]["match"] == "related" and by_item["REL"]["sided_with"] == "oppose"
    assert by_item["ACA"]["wording_url"] == "https://example.org/ACA.pdf" and by_item["ACA"]["wording_hint"] is None
    assert a["summary"] == {"surveyed_votes": 2, "clear_majority": 2, "with_majority": 2, "related_votes": 1}
    assert b["summary"]["with_majority"] == 0
    assert a["by_source"] == [{"organization": "Program for Public Consultation", **a["summary"]}]
    assert a["surveys"][0]["description"] == "d"


def test_surveys_endpoint_lists_each_survey_with_its_question_count(conn, monkeypatch):
    test_load_and_compare(conn, monkeypatch, None)
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(api.app) as client:
        got = client.get("/v1/surveys").json()["surveys"]
    assert [(s["survey"], s["organization"], s["items"]) for s in got] == \
        [("PPC 2026", "Program for Public Consultation", 3)]


def test_text_search_finds_questions_and_votes(conn, monkeypatch):
    test_load_and_compare(conn, monkeypatch, None)
    with conn.cursor() as cur:
        cur.execute("update core.roll_call set description = 'Lower Health Care Premiums Act', bill_type = 'hr', "
                    "bill_number = 1834, bill_congress = 119 where roll_call_id = 'h-119-2-11'")
        cur.execute("update core.roll_call set description = 'Amendment to prohibit assistance to Ukraine' "
                    "where roll_call_id = 'h-119-1-255'")
    conn.commit()
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(api.app) as client:
        res = client.get("/v1/search", params={"q": "ukrain*", "member": ["A000001", "bad"]}).json()
        aca = client.get("/v1/search", params={"q": "ACA", "only": "text"}).json()
        bill = client.get("/v1/search", params={"q": "H.R. 1834", "only": "text"}).json()
        phrase = client.get("/v1/search", params={"q": '"health premiums"', "only": "text"}).json()
        just_members = client.get("/v1/search", params={"q": "ukraine", "only": "members"}).json()

    # The survey question about Ukraine aid, with its vote and how members lined up.
    (qn,) = res["questions"]
    assert qn["item"] == "UKR" and qn["source"]["organization"] == "Program for Public Consultation"
    (v,) = qn["votes"]
    assert v["support_side"] == "nay" and v["members"]["with_majority"] == 1 and v["members"]["against_majority"] == 1
    assert v["your_members"] == [{"bioguide_id": "A000001", "name": "T A000001", "position": "nay"}]
    assert qn["spread"]["states"]["areas"] == 1 and qn["spread"]["districts"]["areas"] == 2
    # The vote itself, tagged as surveyed (by two questions: one same, one related), with a party split.
    (vote,) = res["votes"]
    assert vote["roll_call_id"] == "h-119-1-255" and res["votes_total"] == 1
    assert {s["item"] for s in vote["surveyed"]} == {"UKR", "REL"}
    assert vote["by_party"] == {"Republican": {"nay": 1, "yea": 1}}
    assert "members" in res
    # Words in survey questions; bill numbers with or without dots; phrases in order only.
    assert [x["item"] for x in aca["questions"]] == ["ACA"] and "members" not in aca
    assert [x["roll_call_id"] for x in bill["votes"]] == ["h-119-2-11"]
    assert phrase["votes"] == []
    assert set(just_members) == {"query", "members"}


def test_vote_search_sort_orders(conn, monkeypatch):
    test_load_and_compare(conn, monkeypatch, None)
    with conn.cursor() as cur:
        cur.execute("update core.roll_call set description = 'Farm bill' where roll_call_id = 'h-119-1-255'")
        cur.execute("update core.roll_call set description = 'Something else', question = 'On farm passage' "
                    "where roll_call_id = 'h-119-2-11'")
    conn.commit()
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    ids = lambda r: [v["roll_call_id"] for v in r.json()["votes"]]          # noqa: E731
    with TestClient(api.app) as client:
        assert ids(client.get("/v1/search", params={"q": "farm", "sort": "match"})) == ["h-119-2-11", "h-119-1-255"]
        assert ids(client.get("/v1/search", params={"q": "farm", "sort": "newest"})) == ["h-119-2-11", "h-119-1-255"]
        assert ids(client.get("/v1/search", params={"q": "farm", "sort": "oldest"})) == ["h-119-1-255", "h-119-2-11"]
        assert client.get("/v1/search", params={"q": "farm", "sort": "random"}).status_code == 422


def test_long_vote_titles_come_with_a_matching_snippet(conn, monkeypatch):
    test_load_and_compare(conn, monkeypatch, None)
    long_title = ("; and ".join(f"Person {i}, of Virginia, to be Assistant Secretary of Agriculture" for i in range(30))
                  + "; and Pat Doe, of Ohio, to be Administrator of the Federal Emergency Management Agency")
    with conn.cursor() as cur:
        cur.execute("update core.roll_call set description = %s where roll_call_id = 'h-119-2-10'", (long_title,))
        cur.execute("update core.roll_call set description = 'Short title about an emergency' where roll_call_id = 'h-119-2-11'")
    conn.commit()
    from fastapi.testclient import TestClient
    from congress_congruence.api import app as api
    monkeypatch.setenv("API_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    with TestClient(api.app) as client:
        votes = {v["roll_call_id"]: v for v in client.get("/v1/search", params={"q": "emergency", "only": "text"}).json()["votes"]}
    assert "[[Emergency]]" in votes["h-119-2-10"]["snippet"] and len(votes["h-119-2-10"]["snippet"]) < 400
    assert votes["h-119-2-10"]["description"] == long_title                      # full title still available
    assert votes["h-119-2-11"]["snippet"] is None                                # short titles shown whole
