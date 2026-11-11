"""scripts/check_term_starts.py: terms listed from a Congress's opening day for members who
only arrived later."""

import importlib.util
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_term_starts", ROOT / "scripts" / "check_term_starts.py")
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)


def term(b, start, chamber="house"):
    return {"bioguide_id": b, "name": b, "chamber": chamber, "state": "MS", "district": 2,
            "start_date": date.fromisoformat(start)}


def test_flags_a_member_listed_from_opening_day_who_arrived_later():
    first_vote = {("house", 77): date(1941, 1, 3)}
    presence = {("house", 77): {"W": (date(1941, 11, 6), date(1942, 12, 1)),     # arrived in November
                                "X": (date(1941, 1, 3), date(1942, 12, 1)),      # there all along
                                "Y": (date(1941, 1, 20), date(1942, 12, 1))}}    # a fortnight late: fine
    terms = [term("W", "1941-01-03"), term("X", "1941-01-03"), term("Y", "1941-01-03"),
             term("Z", "1941-05-01"),           # listed as starting mid-Congress: not checked
             term("N", "1941-01-03"),           # listed, but never a member on any roll call
             {**term("A", "1941-01-03"), "end_date": date(1941, 1, 20)},      # left within weeks
             {**term("D", "1941-01-03"), "state": "DC"}]                     # a delegate
    for t in terms:
        t.setdefault("end_date", date(1943, 1, 3))
    flags = ck.find_flags(terms, first_vote, presence)
    assert [(f["bioguide_id"], f["gap_days"]) for f in flags] == [("W", 307), ("N", None)]


def test_at_large_seats_match_either_numbering():
    assert ck.same_district("1", 0) and ck.same_district("0", 0) and ck.same_district("2.0", 2)
    assert not ck.same_district("3", 2)


def test_reads_voteview_files_and_skips_non_members(tmp_path, monkeypatch):
    monkeypatch.setattr(ck, "RAW", tmp_path)
    (tmp_path / "members").mkdir(); (tmp_path / "rollcalls").mkdir(); (tmp_path / "votes").mkdir()
    (tmp_path / "members/H077_members.csv").write_text(
        "congress,chamber,icpsr,state_abbrev,district_code,bioguide_id\n77,House,1,MS,2,D000480\n77,House,2,MS,2,W000428\n")
    (tmp_path / "rollcalls/H077_rollcalls.csv").write_text(
        "congress,chamber,rollnumber,date\n77,House,1,1941-01-03\n77,House,2,1941-11-06\n")
    (tmp_path / "votes/H077_votes.csv").write_text(
        "congress,chamber,rollnumber,icpsr,cast_code\n77,House,1,1,1\n77,House,1,2,0\n77,House,2,1,0\n77,House,2,2,9\n")
    fv, seen, members = ck.from_voteview("house", 77, http=None)
    assert fv == date(1941, 1, 3)
    assert seen == {"D000480": (date(1941, 1, 3), date(1941, 1, 3)), "W000428": (date(1941, 11, 6), date(1941, 11, 6))}
    assert not (tmp_path / "votes/H077_votes.csv").exists() and len(members) == 2


def test_voteview_file_names_use_three_digits():
    from congress_congruence.ingest import voteview as vv
    assert vv.file_names("house", 77)["members"] == "members/H077_members.csv"
    assert vv.file_names("senate", 118)["votes"] == "votes/S118_votes.csv"
