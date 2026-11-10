"""Nationscape loader: release files, weekly files, answer codes, geography, and a full load
from made-up weekly Stata files (two weeks, two questions)."""

import os
import random
from datetime import date

import pandas as pd
import pytest

from congress_congruence import db
from congress_congruence.ingest import ces, nationscape as ns

pyreadstat = pytest.importorskip("pyreadstat")


def test_pick_release_files_prefers_dta_then_the_dta_zip():
    f = lambda i, name, size=1, restricted=False: {"id": i, "name": name, "bytes": size, "restricted": restricted}
    assert [x["id"] for x in ns.pick_release_files([f(1, "a.zip", 9), f(2, "ns20190718.dta"), f(3, "b.dta")])] == [2, 3]
    files = [f(1, "Nationscape_SPSS.zip", 900), f(2, "Nationscape_DTA.zip", 500), f(3, "guide.pdf")]
    assert [x["id"] for x in ns.pick_release_files(files)] == [2]
    assert [x["id"] for x in ns.pick_release_files([f(1, "x.zip", 5), f(2, "y.zip", 9)])] == [2]
    assert ns.pick_release_files([f(1, "x.dta", restricted=True)]) == []


def test_answer_codes_state_and_district_parsing():
    assert ns.answer_codes({1: "Agree", 2: "Disagree", 999: "Not Sure"}) == {1: 1, 2: 0}
    assert ns.answer_codes({1: "Strongly agree", 4: "Strongly disagree", 3: "Somewhat disagree"}) == {1: 1, 4: 0, 3: 0}
    assert ns.answer_codes({1: "Yes", 2: "No"}) == {}
    assert [ns.state_code(x) for x in ("TX", "tx", 48, 48.0, "48", "XX", None, float("nan"))] == \
           ["TX", "TX", "TX", "TX", "TX", None, None, None]
    assert [ns.district_number(x) for x in ("TX07", "TX-7", "7", 7.0, "WYAL", "AL", "00", "", None)] == \
           [7, 7, 7, 7, 0, 0, 0, None, None]


def test_weekly_files_and_asked_window(tmp_path):
    (tmp_path / "phase1" / "ns20190718").mkdir(parents=True)
    (tmp_path / "phase1" / "ns20190718" / "ns20190718.dta").write_bytes(b"")
    (tmp_path / "ns20200102.dta").write_bytes(b"")
    (tmp_path / "readme.dta").write_bytes(b"")
    assert [w for w, _ in ns.weekly_files(tmp_path)] == [date(2019, 7, 18), date(2020, 1, 2)]
    item = {"asked_from": "2019-09-01", "asked_to": "2020-01-31"}
    assert [ns.asked_in(item, d) for d in (date(2019, 8, 1), date(2019, 9, 1), date(2020, 2, 1))] == [False, True, False]
    assert ns.asked_in({}, date(2019, 1, 1))


def test_items_file_is_well_formed():
    cfg = ns.load_config()
    assert cfg["survey"] == ns.SURVEY and cfg["congress"] == 116 and cfg["district_congress"] == 116
    lines = {116, *cfg["district_lines_also"]}
    for var, item in cfg["items"].items():
        assert item["question"] and item["votes"], var
        assert item.get("match", "same") in ("same", "related"), var
        for chamber, rule in item["votes"].items():
            assert chamber in ("house", "senate"), var
            assert set(rule) <= {"roll_call", "date", "expect", "bill", "find", "questions", "congress",
                                 "note", "support_side"}, (var, set(rule))
            vote_congress = int(rule.get("congress", 116))
            if chamber == "house":
                assert vote_congress in lines, var
            # North Carolina's districts changed for the 117th: those items must skip them.
            if chamber == "house" and vote_congress == 117:
                assert "NC" in (item.get("skip_district_states") or []), var


# ---------------------------------------------------------------- full load

SEATS = [  # bioguide, state, district
    ("T000001", "TX", 1), ("T000002", "TX", 2), ("N000001", "NC", 1), ("W000001", "WY", 0),
]
CFG = {
    "survey": "Nationscape 2019-2021", "congress": 116, "district_congress": 116, "district_lines_also": [117],
    "state_column": "state", "district_column": "congress_district", "weight_column": "weight",
    "items": {
        "guns_bg": {"question": "Background checks", "votes": {"house": {"bill": ["hr", 8], "questions": ["On Passage"]}}},
        "guns_bg_2021": {"column": "guns_bg", "question": "Background checks (2021)", "skip_district_states": ["NC"],
                         "votes": {"house": {"congress": 117, "bill": ["hr", 8], "questions": ["On Passage"]}}},
        "impeach": {"question": "Impeach", "asked_from": "2020-01-01",
                    "votes": {"house": {"date": "2019-12-18", "expect": "3-1"}}},
    },
}


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
            for bio, st, dist in SEATS:
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, 'T', %s)", (bio, bio))
                cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                               values (%s, 'house', %s, %s, 'Independent', '2019-01-03', '2023-01-03')""", (bio, st, dist))
            for rid, congress, d, bn, q in [("h-116-1-100", 116, "2019-02-27", 8, "On Passage"),
                                            ("h-116-1-700", 116, "2019-12-18", 755, "On Agreeing to Article I"),
                                            ("h-117-1-50", 117, "2021-03-11", 8, "On Passage")]:
                cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number, vote_date,
                               question, result, bill_type, bill_number, bill_congress, yea_total, nay_total, source)
                               values (%s, 'house', %s, 1, %s, %s, %s, 'Passed', %s, %s, %s, 3, 1, 'test')""",
                            (rid, congress, int(rid.rsplit("-", 1)[1]), d, q, "hres" if bn == 755 else "hr", bn, congress))
                for bio, *_ in SEATS:
                    cur.execute("insert into core.member_vote (roll_call_id, bioguide_id, position, raw_position) "
                                "values (%s, %s, 'yea', 'Yea')", (rid, bio))
        c.commit()
        yield c


@pytest.fixture
def weeks(tmp_path):
    """Two weekly files. guns_bg is asked in both; impeach only in the second (and its rule also
    limits it to 2020). TX-1 mostly agrees, TX-2 mostly disagrees; 'Not sure' (999) is dropped."""
    random.seed(3)
    labels = {"guns_bg": {1: "Agree", 2: "Disagree", 999: "Not Sure"},
              "impeach": {1: "Agree", 2: "Disagree", 999: "Not Sure"}}
    for name, with_impeach in (("ns20190718", False), ("ns20200102", True)):
        rows = []
        for st, cd, p, n in (("TX", "TX01", 0.9, 150), ("TX", "TX02", 0.1, 150), ("NC", "NC01", 0.5, 100),
                             ("WY", "WYAL", 0.5, 60)):
            for _ in range(n):
                row = {"state": st, "congress_district": cd, "weight": random.uniform(0.5, 1.5),
                       "guns_bg": 1 if random.random() < p else 2}
                if with_impeach:
                    row["impeach"] = 1 if random.random() < p else 2
                rows.append(row)
        rows.append({"state": "TX", "congress_district": "TX01", "weight": 1.0, "guns_bg": 999,
                     **({"impeach": 999} if with_impeach else {})})
        folder = tmp_path / name
        folder.mkdir()
        pyreadstat.write_dta(pd.DataFrame(rows), str(folder / f"{name}.dta"),
                             variable_value_labels={k: v for k, v in labels.items() if with_impeach or k != "impeach"})
    return tmp_path


def test_load_pools_weeks_and_skips_nc_districts_for_117th_votes(conn, weeks, monkeypatch):
    monkeypatch.setattr(ns, "load_config", lambda: CFG)
    summary = ns.load(conn, weeks)
    assert summary["respondents"] == 2 * 461 and summary["weeks"] == 2 and summary["votes_linked"] == 3
    with conn.cursor() as cur:
        cur.execute("""select variable, state, district, majority, respondents from core.opinion_estimate
                        order by variable, state, district nulls first""")
        by = {(v, s, d): (m, n) for v, s, d, m, n in cur.fetchall()}
        cur.execute("select organization from core.survey where survey = %s", (CFG["survey"],))
        assert cur.fetchone()[0] == ns.ORGANIZATION
    assert by[("guns_bg", "TX", 1)] == ("support", 300)          # both weeks pooled; "Not sure" left out
    assert by[("guns_bg", "TX", 2)][0] == "oppose"
    assert by[("guns_bg", "WY", 0)][1] == 120                     # at-large "WYAL" -> seat 0
    assert ("guns_bg", "NC", 1) in by
    assert ("guns_bg_2021", "NC", 1) not in by and ("guns_bg_2021", "NC", None) in by   # NC: state only
    assert by[("guns_bg_2021", "TX", 1)] == by[("guns_bg", "TX", 1)]
    assert by[("impeach", "TX", 1)][1] == 150                     # second week only
    # Re-loading replaces rather than duplicates.
    ns.load(conn, weeks)
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.opinion_estimate where survey = %s", (CFG["survey"],))
        assert cur.fetchone()[0] == len(by)


def test_load_stops_on_a_missing_question(conn, weeks, monkeypatch):
    monkeypatch.setattr(ns, "load_config", lambda: {**CFG, "items": {"nope": {"question": "q", "votes": {}}}})
    with pytest.raises(ValueError, match="nope"):
        ns.load(conn, weeks)


def test_inspect_reports_columns_weeks_and_codes(weeks, monkeypatch, tmp_path):
    monkeypatch.setattr(ns.config, "PROJECT_ROOT", tmp_path)
    report = ns.inspect(weeks).read_text()
    assert "Weekly files: 2, 2019-07-18 to 2020-01-02" in report and "Respondents in all weeks: 922" in report
    assert "  guns_bg | 2 | 2019-07-18 to 2020-01-02 |" in report and "[agree/disagree]" in report
    assert "  impeach | 1 | 2020-01-02 to 2020-01-02 |" in report
    assert "congress_district" in report and "weight" in report
