"""Tests for the House and Senate vote parsers and loader, using real vote files.

Fixtures:
  house_119_1_00362.xml   House roll 362, 18 Dec 2025, H.R. 498 on passage (215-201, 17 not voting)
  senate_119_1_00077.xml  Senate vote 77, 21 Feb 2025, amendment to S.Con.Res. 7 (24-76)
"""

import re
import copy
import os
from pathlib import Path

import pytest

from congress_congruence import db
from congress_congruence.ingest import votes
from congress_congruence.ingest.vote_parsers import (
    normalize_position, parse, parse_bill_ref, parse_house, parse_senate)

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE = (FIXTURES / "house_119_1_00362.xml").read_bytes()
SENATE = (FIXTURES / "senate_119_1_00077.xml").read_bytes()


# ---------------------------------------------------------------- parsing

def test_house_metadata():
    rc = parse_house(HOUSE)
    assert rc.roll_call_id == "h-119-1-362"
    assert (rc.chamber, rc.congress, rc.session, rc.roll_number) == ("house", 119, 1, 362)
    assert str(rc.vote_date) == "2025-12-18" and str(rc.vote_time) == "14:59:00"
    assert (rc.question, rc.result) == ("On Passage", "Passed")
    assert (rc.bill_type, rc.bill_number) == ("hr", 498)
    assert (rc.yea_total, rc.nay_total, rc.present_total, rc.not_voting_total) == (215, 201, 0, 17)


def test_house_member_votes_use_bioguide_ids():
    rc = parse_house(HOUSE)
    assert len(rc.votes) == 433
    first = rc.votes[0]
    assert (first.member_id, first.id_type, first.position, first.party, first.state) == \
        ("A000370", "bioguide", "nay", "D", "NC")


def test_senate_metadata_and_amendment_maps_to_its_bill():
    rc = parse_senate(SENATE)
    assert rc.roll_call_id == "s-119-1-77"
    assert str(rc.vote_date) == "2025-02-21" and str(rc.vote_time) == "00:54:00"
    assert rc.amendment_number == "S.Amdt. 999"
    assert (rc.bill_type, rc.bill_number) == ("sconres", 7)
    assert (rc.yea_total, rc.nay_total) == (24, 76)
    assert rc.present_total is None and rc.not_voting_total is None  # blank in the file


def test_senate_member_votes_use_lis_ids():
    rc = parse_senate(SENATE)
    assert len(rc.votes) == 100
    assert (rc.votes[0].member_id, rc.votes[0].id_type) == ("S428", "lis")


@pytest.mark.parametrize("raw, expected", [
    ("Yea", "yea"), ("Aye", "yea"), ("Guilty", "yea"),
    ("Nay", "nay"), ("No", "nay"), ("Not Guilty", "nay"),
    ("Present", "present"), ("Not Voting", "not_voting"), (" not  voting ", "not_voting"),
    ("Jeffries", "other"),  # a vote for Speaker lists candidate names
])
def test_normalize_position(raw, expected):
    assert normalize_position(raw) == expected


@pytest.mark.parametrize("text, expected", [
    ("H R 498", ("hr", 498)), ("H RES 12", ("hres", 12)), ("H J RES 7", ("hjres", 7)),
    ("H CON RES 3", ("hconres", 3)), ("S 5", ("s", 5)), ("S.Con.Res. 7", ("sconres", 7)),
    ("S.J.Res. 11", ("sjres", 11)), ("H.R. 1", ("hr", 1)), ("S.Res. 90", ("sres", 90)),
    ("QUORUM", (None, None)), ("PN12-3", (None, None)), (None, (None, None)),
])
def test_parse_bill_ref(text, expected):
    assert parse_bill_ref(text) == expected


def test_vote_urls():
    assert votes.vote_url("house", 119, 1, 362) == "https://clerk.house.gov/evs/2025/roll362.xml"
    assert votes.vote_url("house", 119, 2, 5) == "https://clerk.house.gov/evs/2026/roll005.xml"
    assert votes.vote_url("senate", 119, 1, 77) == (
        "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00077.xml")


def test_parse_refuses_the_wrong_chamber():
    with pytest.raises(ValueError):
        parse("senate", HOUSE)


# ---------------------------------------------------------------- validation

def test_real_files_pass_validation():
    votes.validate(parse_house(HOUSE))
    votes.validate(parse_senate(SENATE))


def test_validation_catches_total_mismatch():
    rc = parse_house(HOUSE)
    rc.yea_total = 216
    with pytest.raises(votes.ValidationError, match="yea: file lists 215"):
        votes.validate(rc)


def test_validation_catches_duplicate_member():
    rc = parse_senate(SENATE)
    rc.votes.append(copy.copy(rc.votes[0]))
    rc.nay_total += 1
    with pytest.raises(votes.ValidationError, match="listed twice"):
        votes.validate(rc)


def test_xml_entities_are_not_expanded():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><rollcall-vote>&e;</rollcall-vote>'
    with pytest.raises(ValueError):  # refused as not a vote file; the entity is never read
        parse_house(evil)


# ---------------------------------------------------------------- database

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
        # Minimal member rows for everyone in the two fixtures.
        with c.cursor() as cur:
            for v in parse_house(HOUSE).votes:
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, '', '')",
                            (v.member_id,))
            for i, v in enumerate(parse_senate(SENATE).votes):
                bio = f"T{i:06d}"
                cur.execute("insert into core.member (bioguide_id, first_name, last_name) values (%s, '', '') "
                            "on conflict do nothing", (bio,))
                cur.execute("insert into core.member_external_id values ('lis', %s, %s)", (v.member_id, bio))
        c.commit()
        yield c


def test_load_both_chambers_and_reload_replaces(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    assert votes.load_roll_call(conn, parse_house(HOUSE)) == 433
    assert votes.load_roll_call(conn, parse_senate(SENATE)) == 100
    assert votes.load_roll_call(conn, parse_senate(SENATE)) == 100  # re-run
    with conn.cursor() as cur:
        cur.execute("select chamber, count(*) from core.member_vote join core.roll_call using (roll_call_id) "
                    "group by chamber order by chamber")
        assert cur.fetchall() == [("house", 433), ("senate", 100)]


def test_unknown_senate_id_loads_nothing(conn):
    with conn.cursor() as cur:
        cur.execute("delete from core.member_external_id where id_value = 'S428'")
    conn.commit()
    with pytest.raises(votes.ValidationError, match="S428"):
        votes.load_roll_call(conn, parse_senate(SENATE))
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.roll_call")
        assert cur.fetchone()[0] == 0


def test_house_member_missing_from_the_list_is_added_under_the_files_name(conn):
    rc = parse_house(HOUSE)
    gone = rc.votes[0]
    assert gone.name                                   # the parser keeps the name the file prints
    with conn.cursor() as cur:
        cur.execute("delete from core.member where bioguide_id = %s", (gone.member_id,))
    conn.commit()
    assert votes.load_roll_call(conn, rc) == 433
    with conn.cursor() as cur:
        cur.execute("select last_name, official_full from core.member where bioguide_id = %s", (gone.member_id,))
        assert cur.fetchone() == (gone.name, gone.name)
        cur.execute("select count(*) from core.term where bioguide_id = %s", (gone.member_id,))
        assert cur.fetchone()[0] == 0                  # no seat is invented for them


def test_house_member_missing_with_no_name_still_stops(conn):
    rc = parse_house(HOUSE)
    rc.votes[0].name = None
    with conn.cursor() as cur:
        cur.execute("delete from core.member where bioguide_id = %s", (rc.votes[0].member_id,))
    conn.commit()
    with pytest.raises(votes.ValidationError, match="not in member table"):
        votes.load_roll_call(conn, rc)


def test_save_raw_keeps_file_and_records_it(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    sha = votes.save_raw(conn, "house", 119, 1, HOUSE, "roll362.xml", "https://example/roll362.xml")
    assert (tmp_path / "house_clerk" / "119" / "1" / "roll362.xml").read_bytes() == HOUSE
    with conn.cursor() as cur:
        cur.execute("select bytes from core.raw_file where sha256 = %s", (sha,))
        assert cur.fetchone()[0] == len(HOUSE)


def test_save_raw_files_each_session_separately_and_replaces_changed_files(conn, tmp_path, monkeypatch):
    """House file names repeat each year; 2025's roll001.xml must not stand in for 2026's."""
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    votes.save_raw(conn, "house", 119, 1, b"<a>2025</a>", "roll001.xml", None)
    votes.save_raw(conn, "house", 119, 2, b"<a>2026</a>", "roll001.xml", None)
    assert (tmp_path / "house_clerk" / "119" / "1" / "roll001.xml").read_bytes() == b"<a>2025</a>"
    assert (tmp_path / "house_clerk" / "119" / "2" / "roll001.xml").read_bytes() == b"<a>2026</a>"
    votes.save_raw(conn, "house", 119, 2, b"<a>2026 corrected</a>", "roll001.xml", None)
    assert (tmp_path / "house_clerk" / "119" / "2" / "roll001.xml").read_bytes() == b"<a>2026 corrected</a>"


def test_vacated_vote_is_skipped_not_failed(conn, tmp_path, monkeypatch):
    """h-114-1-300: vacated by unanimous consent; the file lists nobody and every total is 0."""
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(votes, "REQUEST_PAUSE_SECONDS", 0)
    vacated = re.sub(rb"<recorded-vote>.*?</recorded-vote>", b"", HOUSE, flags=re.S)
    vacated = re.sub(rb"<(yea|nay|present|not-voting)-total>\d+</", rb"<\1-total>0</", vacated)
    assert votes.is_vacated(parse_house(vacated))
    responses = iter([vacated, HOUSE, None])
    monkeypatch.setattr(votes, "download", lambda url, session: next(responses))
    assert votes.sync(conn, "house", 119, 1) == {"loaded": 1, "failed": 0, "vacated": 1, "next_roll": 3, "refused": False}


@pytest.fixture(autouse=True)
def session_119_1_is_current(request, monkeypatch):
    """The sync tests use 119-1 as the session still in progress (no looking past its end)."""
    if "sync" in request.node.name or "vacated" in request.node.name:
        monkeypatch.setattr(votes, "current_session", lambda today=None: (119, 1))


def test_sync_of_a_finished_session_carries_on_past_a_missing_vote_number(conn, tmp_path, monkeypatch):
    """2007's list has no file for vote 1000 but carries on to 1186; 2020's skips 254."""
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(votes, "REQUEST_PAUSE_SECONDS", 0)
    monkeypatch.setattr(votes, "current_session", lambda today=None: (119, 2))
    def numbered(n):
        return HOUSE.replace(b"<rollcall-num>362</rollcall-num>", f"<rollcall-num>{n}</rollcall-num>".encode())
    files = {1: numbered(1), 3: numbered(3)}          # vote 2 has no file; nothing after 3
    monkeypatch.setattr(votes, "download",
                        lambda url, session: files.get(int(url.rsplit("roll", 1)[1].split(".")[0])))
    assert votes.sync(conn, "house", 119, 1) == {"loaded": 2, "failed": 1, "vacated": 0, "next_roll": 4, "refused": False}


def test_sync_loads_until_first_missing_vote_and_skips_bad_files(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(votes, "REQUEST_PAUSE_SECONDS", 0)
    broken = HOUSE.replace(b"<yea-total>215</yea-total>", b"<yea-total>999</yea-total>")  # the overall total
    assert broken != HOUSE
    responses = iter([HOUSE, broken, None])   # roll 1 good, roll 2 fails validation, roll 3 not posted yet
    requested = []

    def fake_download(url, session):
        requested.append(url)
        return next(responses)

    monkeypatch.setattr(votes, "download", fake_download)
    result = votes.sync(conn, "house", 119, 1)
    assert result == {"loaded": 1, "failed": 1, "vacated": 0, "next_roll": 3, "refused": False}
    assert requested[0].endswith("/2025/roll001.xml") and len(requested) == 3


def test_sync_fills_gaps_from_vote_one_and_skips_votes_already_loaded(conn, tmp_path, monkeypatch):
    """Loading one test vote (362) must not make sync skip votes 1-361."""
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(votes, "REQUEST_PAUSE_SECONDS", 0)
    votes.load_roll_call(conn, parse_house(HOUSE))          # vote 362 already present
    requested = []

    def fake_download(url, session):
        n = int(url.rsplit("roll", 1)[1].split(".")[0])
        requested.append(n)
        if n in (1, 2):
            return HOUSE.replace(b"<rollcall-num>362</rollcall-num>", f"<rollcall-num>{n}</rollcall-num>".encode())
        return None                                          # vote 3 not posted yet

    monkeypatch.setattr(votes, "download", fake_download)
    result = votes.sync(conn, "house", 119, 1)
    assert requested == [1, 2, 3]
    assert result["loaded"] == 2 and result["failed"] == 0
    with conn.cursor() as cur:
        cur.execute("select roll_number from core.roll_call order by 1")
        assert [r[0] for r in cur.fetchall()] == [1, 2, 362]


class FakeResponse:
    def __init__(self, body, status=200):
        self.content, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), 0

    def get(self, url, timeout):
        self.calls += 1
        return FakeResponse(self.bodies.pop(0))


CLERK_MISSING = b'<xml>Error sanitizing file "roll363.xml". Please try again.</xml>'  # real reply, Nov 2026


def test_clerk_missing_message_is_retried_then_means_no_such_vote(monkeypatch):
    monkeypatch.setattr(votes, "MISSING_RETRY_PAUSE_SECONDS", 0)
    s = FakeSession(CLERK_MISSING, CLERK_MISSING, CLERK_MISSING)
    assert votes.download("https://clerk.house.gov/evs/2025/roll363.xml", s) is None
    assert s.calls == 3


def test_clerk_missing_message_that_clears_on_retry_returns_the_file(monkeypatch):
    monkeypatch.setattr(votes, "MISSING_RETRY_PAUSE_SECONDS", 0)
    s = FakeSession(CLERK_MISSING, HOUSE)
    assert votes.download("https://clerk.house.gov/evs/2025/roll362.xml", s) == HOUSE


def test_sync_stops_cleanly_on_an_unrecognized_file(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(votes, "REQUEST_PAUSE_SECONDS", 0)
    responses = iter([HOUSE.replace(b"<rollcall-num>362</rollcall-num>", b"<rollcall-num>1</rollcall-num>"),
                      b"<?xml version='1.0'?><something-else/>"])
    monkeypatch.setattr(votes, "download", lambda url, session: next(responses))
    result = votes.sync(conn, "house", 119, 1)          # no exception
    assert result == {"loaded": 1, "failed": 1, "vacated": 0, "next_roll": 2, "refused": False}


@pytest.mark.parametrize("day, expected", [
    ("2025-01-03", (119, 1)), ("2025-12-31", (119, 1)), ("2026-11-07", (119, 2)),
    ("2027-01-02", (119, 2)),   # still the old Congress until Jan 3
    ("2027-01-03", (120, 1)), ("2028-06-01", (120, 2)),
])
def test_current_session(day, expected):
    from datetime import date
    assert votes.current_session(date.fromisoformat(day)) == expected


def test_sync_senate_goes_slowly_and_stops_politely(conn, monkeypatch):
    """senate.gov's bot protection refuses a server that asks too fast: Senate files are capped
    per run, and a refusal ends the run (keeping what loaded) instead of failing the job."""
    monkeypatch.setattr(votes, "SENATE_PAUSE_SECONDS", 0)
    monkeypatch.setattr(votes, "SENATE_MAX_PER_RUN", 2)
    monkeypatch.setattr(votes, "fetch_one", lambda *a, **k: 1)
    assert votes.sync(conn, "senate", 119, 1) == {"loaded": 2, "failed": 0, "vacated": 0, "next_roll": 3, "refused": False}

    def refuse_third(conn_, chamber, congress, session_no, roll, http=None):
        if roll == 3:
            raise PermissionError("refused (403)")
        return 1
    monkeypatch.setattr(votes, "SENATE_MAX_PER_RUN", 60)
    monkeypatch.setattr(votes, "fetch_one", refuse_third)
    assert votes.sync(conn, "senate", 119, 1) == {"loaded": 2, "failed": 0, "vacated": 0, "next_roll": 3, "refused": True}


def test_loading_a_vote_stores_how_each_party_voted(conn, tmp_path, monkeypatch):
    """Member pages read core.party_position instead of working it out on every visit."""
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    rc = parse_house(HOUSE)
    with conn.cursor() as cur:       # give every voter a term so their party is known
        for i, v in enumerate(rc.votes):
            cur.execute("""insert into core.term (bioguide_id, chamber, state, district, party, start_date, end_date)
                           values (%s, 'house', 'TX', %s, %s, '2025-01-03', '2027-01-03')
                           on conflict do nothing""", (v.member_id, i % 36, "Republican" if i % 2 else "Democrat"))
    conn.commit()
    votes.load_roll_call(conn, rc)
    with conn.cursor() as cur:
        cur.execute("select grp, position from core.party_position where roll_call_id = %s order by grp", (rc.roll_call_id,))
        stored = cur.fetchall()
        cur.execute(party_select("and v.roll_call_id = %(id)s"), {"id": rc.roll_call_id})
        live = sorted((g, p) for _, g, p in cur.fetchall())
    assert stored == live and {g for g, _ in stored} == {"Democrat", "Republican"}
    votes.load_roll_call(conn, rc)                       # reloading rewrites, never duplicates
    with conn.cursor() as cur:
        cur.execute("select count(*) from core.party_position where roll_call_id = %s", (rc.roll_call_id,))
        assert cur.fetchone()[0] == 2


def party_select(where):
    from congress_congruence import party
    return party.SELECT.format(where=where)


def test_sync_hands_a_session_without_member_ids_to_voteview(conn, monkeypatch):
    """The Clerk's older files name members without IDs: after the first few, stop the session."""
    monkeypatch.setattr(votes, "REQUEST_PAUSE_SECONDS", 0)
    calls = []

    def no_ids(conn_, chamber, congress, session_no, roll, http=None):
        calls.append(roll)
        raise votes.ValidationError(f"h-104-1-{roll}: member vote without an ID; member listed twice: [None]")
    monkeypatch.setattr(votes, "fetch_one", no_ids)
    assert votes.sync(conn, "house", 104, 1) == {"loaded": 0, "failed": 0, "vacated": 0, "next_roll": 3,
                                                 "refused": False, "no_ids": True}
    assert calls == [1, 2, 3]
