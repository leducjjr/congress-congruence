"""Tests for the Voteview loader.

The fixtures use Voteview's real column layouts (copied from the S119 files)
with a few small made-up votes so every case is easy to check by eye.
"""

import os

import pytest

from congress_congruence import db
from congress_congruence.ingest import voteview, votes
from congress_congruence.ingest.vote_parsers import parse_senate
from pathlib import Path

ROLLCALLS = b"""congress,chamber,rollnumber,date,session,clerk_rollnumber,majority_requirement,yea_count,nay_count,nominate_mid_1,nominate_mid_2,nominate_spread_1,nominate_spread_2,nominate_log_likelihood,bill_number,vote_result,vote_desc,vote_question,dtl_desc
119,Senate,1,2025-01-09,1,1,3/5,2,1,-0.444,-0.634,-0.708,-0.181,-10.067,S5,Cloture Motion Agreed to,"A bill to require the Secretary of Homeland Security to take into custody aliens who have been charged in the United States with theft, and for other purposes.",On the Cloture Motion,
119,Senate,2,2025-01-13,1,2,1/2,2,0,-0.446,-0.606,-0.715,-0.072,-12.276,S5,Motion to Proceed Agreed to,"A bill, with a comma",On the Motion to Proceed,
119,Senate,3,2025-01-14,1,3,1/2,1,1,,,,,,,Motion Agreed to,"Paired vote case",On the Motion,
"""
VOTES = b"""congress,chamber,rollnumber,icpsr,cast_code,prob
119,Senate,1,14226,1,100.0
119,Senate,1,14435,1,81.0
119,Senate,1,42102,6,90.0
119,Senate,1,99999,0,
119,President,1,99912,1,
119,Senate,2,99912,1,
119,Senate,2,14226,1,100.0
119,Senate,2,14435,1,99.0
119,Senate,2,42102,9,
119,Senate,3,14226,1,100.0
119,Senate,3,14435,2,
119,Senate,3,42102,6,
"""
MEMBERS = b"""congress,chamber,icpsr,state_icpsr,district_code,state_abbrev,party_code,occupancy,last_means,bioname,bioguide_id,born,died,nominate_dim1,nominate_dim2,nominate_log_likelihood,nominate_geo_mean_probability,nominate_number_of_votes,nominate_number_of_errors,conditional,nokken_poole_dim1,nokken_poole_dim2
119,President,99912,99,0,USA,200,0,0,"TRUMP, Donald John",,1946.0,,0.403,0.162,,,,,,,
119,Senate,42102,41,0,AL,200,,,"TUBERVILLE, Thomas Hawley (Tommy)",T000278,1954.0,,0.936,-0.352,-34.17365,0.9605,848,10,,0.936,-0.352
119,Senate,14226,1,0,CT,100,,,"BLUMENTHAL, Richard",B001277,1946.0,,,,,,,,,,
119,Senate,14435,2,0,ME,100,,,"KING, Angus",K000383,1944.0,,,,,,,,,,
"""


def parsed():
    return voteview.build_roll_calls("senate", voteview.read_csv(ROLLCALLS),
                                     voteview.read_csv(VOTES), voteview.read_csv(MEMBERS))


def test_uses_official_session_and_clerk_numbers_for_ids():
    rcs, problems = parsed()
    assert problems == []
    assert [rc.roll_call_id for rc in rcs] == ["s-119-1-1", "s-119-1-2", "s-119-1-3"]
    first = rcs[0]
    assert (str(first.vote_date), first.vote_type, first.question) == ("2025-01-09", "3/5", "On the Cloture Motion")
    assert (first.bill_type, first.bill_number) == ("s", 5)


def test_maps_icpsr_to_bioguide_and_skips_non_members_and_president():
    first = parsed()[0][0]
    assert sorted(v.member_id for v in first.votes) == ["B001277", "K000383", "T000278"]
    assert {v.member_id: v.position for v in first.votes}["T000278"] == "nay"


def test_presidents_position_listed_in_senate_file_is_not_a_member_vote():
    """Found in the live S119 file: icpsr 99912 (the President) appears with chamber
    'Senate' on 145 roll calls, which pushed yea counts one over the published total."""
    second = parsed()[0][1]
    assert sorted(v.member_id for v in second.votes) == ["B001277", "K000383", "T000278"]
    voteview.validate_voteview(second)


def test_cast_codes():
    rcs = parsed()[0]
    by_id = lambda rc: {v.member_id: (v.position, v.raw_position) for v in rc.votes}  # noqa: E731
    assert by_id(rcs[1])["T000278"] == ("not_voting", "Not Voting")
    assert by_id(rcs[2])["K000383"] == ("not_voting", "Paired Yea")


def test_validation_accepts_both_pair_conventions_and_rejects_others():
    for rc in parsed()[0]:
        voteview.validate_voteview(rc)        # roll 3: yea_count 1 excludes the pair -> accepted
    rc = parsed()[0][2]
    rc.yea_total = 2                           # counting the pair -> also accepted
    voteview.validate_voteview(rc)
    rc.yea_total = 5
    with pytest.raises(votes.ValidationError, match="yea"):
        voteview.validate_voteview(rc)


def test_unmapped_member_fails_validation():
    members = MEMBERS.replace(b",K000383,", b",,")
    rc = voteview.build_roll_calls("senate", voteview.read_csv(ROLLCALLS),
                                   voteview.read_csv(VOTES), voteview.read_csv(members))[0][0]
    with pytest.raises(votes.ValidationError, match="icpsr:14435"):
        voteview.validate_voteview(rc)


def test_decimal_ids_in_one_file_still_match_the_other():
    """The 114th Congress votes file writes ICPSR IDs as '14226.0'; the member file as '14226'."""
    import re
    decimal_votes = re.sub(rb"^(\d+),(\w+),(\d+),(\d+),(\d+),", rb"\1,\2,\3.0,\4.0,\5.0,", VOTES, flags=re.M)
    assert b"14226.0" in decimal_votes
    rc = voteview.build_roll_calls("senate", voteview.read_csv(ROLLCALLS),
                                   voteview.read_csv(decimal_votes), voteview.read_csv(MEMBERS))[0][0]
    voteview.validate_voteview(rc)
    assert sorted(v.member_id for v in rc.votes) == ["B001277", "K000383", "T000278"]


def test_member_list_fills_in_a_missing_bioguide_id():
    members = MEMBERS.replace(b",K000383,", b",,")
    rc = voteview.build_roll_calls("senate", voteview.read_csv(ROLLCALLS), voteview.read_csv(VOTES),
                                   voteview.read_csv(members), {"14435": "K000383"})[0][0]
    voteview.validate_voteview(rc)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    with db.connect(url) as c:
        with c.cursor() as cur:
            cur.execute("drop schema if exists core cascade")
        c.commit()
        db.migrate(c)
        with c.cursor() as cur:
            for bio in ("B001277", "K000383", "T000278"):
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, '', '')", (bio,))
        c.commit()
        yield c


def write_files(folder: Path, rollcalls=ROLLCALLS):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "S119_rollcalls.csv").write_bytes(rollcalls)
    (folder / "S119_votes.csv").write_bytes(VOTES)
    (folder / "S119_members.csv").write_bytes(MEMBERS)
    return folder


def test_run_loads_and_never_overwrites_official_votes(conn, tmp_path):
    files = write_files(tmp_path / "vv")
    # Pretend roll 2 already came from the Senate's own feed.
    with conn.cursor() as cur:
        cur.execute("""insert into core.roll_call (roll_call_id, chamber, congress, session, roll_number,
                       vote_date, source) values ('s-119-1-2', 'senate', 119, 1, 2, '2025-01-13', 'senate_lis')""")
    conn.commit()

    result = voteview.run(conn, "senate", 119, files)
    assert result == {"loaded": 2, "kept_official": 1, "failed": 0, "newest_vote": "2025-01-14"}
    again = voteview.run(conn, "senate", 119, files)   # re-run replaces, doesn't duplicate
    assert again["loaded"] == 2
    with conn.cursor() as cur:
        cur.execute("select roll_call_id, source from core.roll_call order by 1")
        assert cur.fetchall() == [("s-119-1-1", "voteview"), ("s-119-1-2", "senate_lis"), ("s-119-1-3", "voteview")]
        cur.execute("select count(*) from core.member_vote")
        assert cur.fetchone()[0] == 6


def test_official_senate_file_replaces_voteview_copy(conn, tmp_path):
    """When the Senate's own file arrives later, it takes over the same ID."""
    real = parse_senate((Path(__file__).parent / "fixtures" / "senate_119_1_00077.xml").read_bytes())
    rollcalls = ROLLCALLS + b'119,Senate,77,2025-02-21,1,77,1/2,,,,,,,,,Amendment Rejected,"x",On the Amendment,\n'  # no member rows in this fixture
    voteview.run(conn, "senate", 119, write_files(tmp_path / "vv", rollcalls))
    with conn.cursor() as cur:
        cur.execute("select source from core.roll_call where roll_call_id='s-119-1-77'")
        assert cur.fetchone()[0] == "voteview"
        # minimal LIS crosswalk so the official file can load
        for i, v in enumerate(real.votes):
            cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s,'','') "
                        "on conflict do nothing", (f"L{i:06d}",))
            cur.execute("insert into core.member_external_id values ('lis', %s, %s)", (v.member_id, f"L{i:06d}"))
    conn.commit()
    votes.load_roll_call(conn, real)
    with conn.cursor() as cur:
        cur.execute("select source, count(*) from core.roll_call join core.member_vote using (roll_call_id) "
                    "where roll_call_id='s-119-1-77' group by source")
        assert cur.fetchall() == [("senate_lis", 100)]
