"""Earlier Congresses: the load plan, and seat histories built from whole careers."""

from datetime import date

from congress_congruence.api.app import congress_on, seat_history
from congress_congruence.ingest import backfill


def test_plan_goes_newest_first_and_skips_house_years_without_clerk_files():
    assert backfill.plan(117, 118, ["house", "senate"]) == [
        ("house", 118, 1), ("house", 118, 2), ("senate", 118, None),
        ("house", 117, 1), ("house", 117, 2), ("senate", 117, None)]
    assert backfill.house_sessions(101) == [2] and backfill.house_sessions(100) == []
    # Before the Clerk's files (1989 and earlier), House votes come from Voteview: the whole
    # Congress, after the Clerk's files for the 101st, so Voteview only fills in 1989.
    assert backfill.plan(100, 101, ["house"]) == [("house", 101, 2), ("house", 101, None), ("house", 100, None)]
    assert backfill.plan(102, 102, ["house"]) == [("house", 102, 1), ("house", 102, 2)]


def test_refuses_the_current_congress_and_bad_arguments(capsys):
    assert backfill.main(["backfill", "118", "119"]) == 2
    assert backfill.main(["backfill", "118"]) == 2
    assert backfill.main(["backfill", "110", "118", "both"]) == 2


def T(chamber, state, district, party, start, end, caucus=None):
    return {"chamber": chamber, "state": state, "district": district, "party": party, "caucus": caucus,
            "start_date": date.fromisoformat(start), "end_date": date.fromisoformat(end)}


def test_seat_history_merges_back_to_back_terms_and_splits_on_any_change():
    terms = [T("house", "OH", 2, "Republican", "2013-01-03", "2015-01-03"),
             T("house", "OH", 2, "Republican", "2015-01-03", "2017-01-03"),
             T("house", "OH", 3, "Republican", "2023-01-03", "2025-01-03"),      # gap, then a new district
             T("senate", "OH", None, "Republican", "2025-01-03", "2031-01-03")]
    spells = seat_history(terms, date(2026, 11, 8))
    assert [(s["seat"], s["end"], s["first_congress"], s["last_congress"]) for s in spells] == [
        ("OH", None, 119, 119), ("OH-3", date(2025, 1, 3), 118, 118), ("OH-2", date(2017, 1, 3), 113, 114)]
    # A party switch is a new spell; caucus counts for independents.
    switch = seat_history([T("senate", "VT", None, "Independent", "2007-01-03", "2013-01-03", caucus="Democrat"),
                           T("senate", "VT", None, "Independent", "2013-01-03", "2019-01-03", caucus="Democrat"),
                           T("senate", "VT", None, "Republican", "2019-01-03", "2025-01-03")], date(2026, 1, 1))
    assert [s["party"] for s in switch] == ["Republican", "Democrat"]


def test_congress_on_a_day():
    assert congress_on(date(2025, 1, 2)) == 118 and congress_on(date(2025, 1, 3)) == 119
    assert congress_on(date(2026, 12, 31)) == 119 and congress_on(date(1991, 6, 1)) == 102
