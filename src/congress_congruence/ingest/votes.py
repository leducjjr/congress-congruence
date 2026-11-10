"""Fetch, validate and load roll-call votes for both chambers.

Usage:
    # Load a vote file you already have
    python -m congress_congruence.ingest.votes load-file house  path/to/roll362.xml
    python -m congress_congruence.ingest.votes load-file senate path/to/vote_119_1_00077.xml

    # Download and load one vote
    python -m congress_congruence.ingest.votes fetch house  119 1 362
    python -m congress_congruence.ingest.votes fetch senate 119 1 77

    # Download every vote of the session not yet loaded (stops at the first one not posted)
    python -m congress_congruence.ingest.votes sync house  119 1
    python -m congress_congruence.ingest.votes sync senate 119 1

    # Same, for whatever Congress and session are in effect today (for the scheduler)
    python -m congress_congruence.ingest.votes sync house current

Every file is saved unchanged under RAW_DATA_DIR before it is parsed.
A vote is written only if it passes validation; a failure loads nothing for that vote.
"""

import hashlib
import logging
import sys
import time
from collections import Counter
from pathlib import Path

import requests

from .. import config, db
from .vote_parsers import ParsedRollCall, parse

log = logging.getLogger(__name__)

USER_AGENT = "congress-congruence/0.1 (+https://github.com/leducjjr/congress-congruence)"
REQUEST_PAUSE_SECONDS = 1.0     # be polite to the chambers' servers
# senate.gov's bot protection refuses a server that asks too fast (it let ~97 files through at
# one a second, Nov 10, 2026). So Senate files go slower, and at most this many in one run; the
# next daily run carries on where this one stopped, and Voteview fills any gap meanwhile.
SENATE_PAUSE_SECONDS = 6.0
SENATE_MAX_PER_RUN = 60
SOURCE = {"house": "house_clerk", "senate": "senate_lis"}
MAX_MEMBERS = {"house": 441, "senate": 100}   # House: 435 seats + 6 delegates


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------- URLs

def first_year(congress: int) -> int:
    return 1787 + 2 * congress           # 119th Congress began in 2025


def current_session(today=None) -> tuple[int, int]:
    """(congress, session) in effect on a date. A new Congress begins Jan 3 of odd years,
    so Jan 1-2 of an odd year still belong to the previous Congress's second session."""
    from datetime import date as _date
    today = today or _date.today()
    year = today.year
    if year % 2 == 1 and (today.month, today.day) < (1, 3):
        year -= 1
    congress = (year - 1787) // 2
    return congress, year - first_year(congress) + 1


def vote_url(chamber: str, congress: int, session: int, roll: int) -> str:
    if chamber == "house":
        year = first_year(congress) + session - 1
        return f"https://clerk.house.gov/evs/{year}/roll{roll:03d}.xml"
    return ("https://www.senate.gov/legislative/LIS/roll_call_votes/"
            f"vote{congress}{session}/vote_{congress}_{session}_{roll:05d}.xml")


# ---------------------------------------------------------------- validation

def validate(rc: ParsedRollCall) -> None:
    """Raise ValidationError unless the member rows agree with the published totals."""
    problems = []
    ids = [v.member_id for v in rc.votes]
    if not rc.votes:
        problems.append("no member votes in file")
    if any(not i for i in ids):
        problems.append("member vote without an ID")
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        problems.append(f"member listed twice: {dupes}")
    if len(ids) > MAX_MEMBERS[rc.chamber]:
        problems.append(f"{len(ids)} members exceeds {MAX_MEMBERS[rc.chamber]} for the {rc.chamber}")

    counted = Counter(v.position for v in rc.votes)
    # Senate files leave present/absent blank when they are zero.
    blank_is_zero = rc.chamber == "senate"
    for position, published in [("yea", rc.yea_total), ("nay", rc.nay_total),
                                ("present", rc.present_total), ("not_voting", rc.not_voting_total)]:
        if published is None and blank_is_zero:
            published = 0
        if published is not None and counted[position] != published:
            problems.append(f"{position}: file lists {counted[position]} members, published total is {published}")

    if problems:
        raise ValidationError(f"{rc.roll_call_id}: " + "; ".join(problems))


# ---------------------------------------------------------------- database

def lis_to_bioguide(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("select id_value, bioguide_id from core.member_external_id where id_type = 'lis'")
        return dict(cur.fetchall())


def save_raw(conn, chamber: str, congress: int, session_no: int, content: bytes,
             filename: str, url: str | None) -> str:
    """Keep the file exactly as downloaded, under <source>/<congress>/<session>/.

    Filed by session because House file names repeat each year (roll001.xml in 2025
    and in 2026). A file that changed since it was last saved is replaced."""
    sha = hashlib.sha256(content).hexdigest()
    path = config.raw_data_dir() / SOURCE[chamber] / str(congress) / str(session_no) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != content:
        path.write_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            """insert into core.raw_file (sha256, source, url, local_path, bytes)
               values (%s, %s, %s, %s, %s) on conflict (sha256) do nothing""",
            (sha, SOURCE[chamber], url, str(path), len(content)),
        )
    return sha


def add_unlisted_members(cur, rc: ParsedRollCall, missing: list[str]) -> None:
    """A House file can list someone the member list doesn't have: e.g. a member-elect listed on
    the opening vote of a Congress who never took the seat (L000555 on h-117-1-1), or a new
    member before the list is refreshed. Add them under the name the Clerk's file prints, with
    no term (so they're never shown as a member of any seat); a later member refresh fills in
    the rest if the list ever includes them. Without a name to go on, stop as before."""
    names = {v.member_id: v.name for v in rc.votes if v.member_id in missing}
    if not all(names.values()):
        raise ValidationError(f"{rc.roll_call_id}: Bioguide IDs not in member table: {missing}. "
                              "Refresh members (ingest.members) and retry.")
    for bioguide, name in names.items():
        log.warning("%s: %s (%s) isn't in the member list; added under the name in the Clerk's file",
                    rc.roll_call_id, bioguide, name)
        cur.execute("insert into core.member (bioguide_id, first_name, last_name, official_full) "
                    "values (%s, '', %s, %s) on conflict do nothing", (bioguide, name, name))


def load_roll_call(conn, rc: ParsedRollCall, raw_sha: str | None = None,
                   source_url: str | None = None, lis_map: dict[str, str] | None = None,
                   source: str | None = None, validator=None) -> int:
    """Validate and write one roll call and its member votes. Re-loading replaces it.

    source/validator default to the official chamber feed; other sources (Voteview)
    pass their own."""
    (validator or validate)(rc)

    if any(v.id_type == "lis" for v in rc.votes):
        lis_map = lis_map if lis_map is not None else lis_to_bioguide(conn)
        unknown = sorted({v.member_id for v in rc.votes if v.member_id not in lis_map})
        if unknown:
            raise ValidationError(
                f"{rc.roll_call_id}: Senate IDs not in member table: {unknown}. "
                "Refresh members (ingest.members) and retry.")
    to_bioguide = lambda v: lis_map[v.member_id] if v.id_type == "lis" else v.member_id  # noqa: E731

    rows = [(rc.roll_call_id, to_bioguide(v), v.position, v.raw_position, v.party, v.state) for v in rc.votes]

    with conn.transaction(), conn.cursor() as cur:
        if any(v.id_type == "bioguide" for v in rc.votes):
            cur.execute("select array_agg(x) from unnest(%s::text[]) x "
                        "where not exists (select 1 from core.member m where m.bioguide_id = x)",
                        ([r[1] for r in rows],))
            missing = cur.fetchone()[0]
            if missing:
                add_unlisted_members(cur, rc, sorted(missing))

        cur.execute("delete from core.roll_call where roll_call_id = %s", (rc.roll_call_id,))
        cur.execute(
            """insert into core.roll_call (
                   roll_call_id, chamber, congress, session, roll_number, vote_date, vote_time,
                   question, vote_type, result, description, bill_congress, bill_type, bill_number,
                   amendment_number, yea_total, nay_total, present_total, not_voting_total,
                   tie_breaker, source, source_url, raw_file_sha256)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (rc.roll_call_id, rc.chamber, rc.congress, rc.session, rc.roll_number, rc.vote_date,
             rc.vote_time, rc.question, rc.vote_type, rc.result, rc.description,
             rc.congress if rc.bill_type else None, rc.bill_type, rc.bill_number,
             rc.amendment_number, rc.yea_total, rc.nay_total, rc.present_total, rc.not_voting_total,
             rc.tie_breaker, source or SOURCE[rc.chamber], source_url, raw_sha),
        )
        with cur.copy("copy core.member_vote (roll_call_id, bioguide_id, position, raw_position, party, state) "
                      "from stdin") as cp:
            for r in rows:
                cp.write_row(r)
    return len(rows)


# ---------------------------------------------------------------- fetching

MISSING_RETRIES = 2
MISSING_RETRY_PAUSE_SECONDS = 5.0
# A finished session's list can have a hole: one vote number with no file (2007's vote 1000,
# 2020's vote 254), after which the files carry on. For past sessions, look this many numbers
# ahead before deciding the list has ended.
LOOKAHEAD_PAST_SESSION = 5


def looks_missing(body: bytes) -> bool:
    """True when a server answered with a 'no such file' message instead of a 404.

    House Clerk, for a vote not yet posted (seen Nov 2026):
        <xml>Error sanitizing file "roll363.xml". Please try again.</xml>
    Others answer with an HTML page."""
    head = body.lstrip()[:500].lower()
    if b"error sanitizing file" in head:
        return True
    return not head.startswith(b"<?xml") and b"<html" in head


def download(url: str, session: requests.Session) -> bytes | None:
    """Return the file's bytes, or None if that vote doesn't exist (yet).

    The Clerk's 'missing' message says 'please try again', so it's retried a
    couple of times before being taken as the end of the list. If it was only a
    hiccup, the next sync fills the gap, since sync always starts from vote 1."""
    for attempt in range(MISSING_RETRIES + 1):
        resp = session.get(url, timeout=60)
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            raise PermissionError(
                f"{url} refused the request (403). senate.gov refuses servers that ask too often "
                "or that it hasn't allowed; the next run tries again.")
        resp.raise_for_status()
        body = resp.content
        if not looks_missing(body):
            return body
        if attempt < MISSING_RETRIES:
            time.sleep(MISSING_RETRY_PAUSE_SECONDS)
    return None


def http_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def fetch_one(conn, chamber: str, congress: int, session_no: int, roll: int,
              http: requests.Session | None = None) -> int | None:
    url = vote_url(chamber, congress, session_no, roll)
    content = download(url, http or http_session())
    if content is None:
        return None
    sha = save_raw(conn, chamber, congress, session_no, content, url.rsplit("/", 1)[1], url)
    conn.commit()
    rc = parse(chamber, content)
    if is_vacated(rc):
        log.info("%s: vacated (no votes recorded; the number stays used)", rc.roll_call_id)
        return VACATED
    return load_roll_call(conn, rc, sha, url)


VACATED = -2


def is_vacated(rc: ParsedRollCall) -> bool:
    """A vote vacated by unanimous consent keeps its number, but its file lists nobody and every
    total is zero (e.g. h-114-1-300, June 4, 2015). There is nothing to load."""
    return not rc.votes and not any((rc.yea_total, rc.nay_total, rc.present_total, rc.not_voting_total))


def next_existing(conn, chamber: str, congress: int, session_no: int, roll: int, http) -> int | None:
    """For a session that has ended, the next vote number after `roll` that has a file, if any
    within LOOKAHEAD_PAST_SESSION. The current session's list simply hasn't grown yet: None."""
    if (congress, session_no) >= current_session():
        return None
    for ahead in range(roll + 1, roll + 1 + LOOKAHEAD_PAST_SESSION):
        if download(vote_url(chamber, congress, session_no, ahead), http) is not None:
            return ahead
    return None


def sync(conn, chamber: str, congress: int, session_no: int) -> dict[str, int]:
    """Load every vote of the session not yet loaded from the official feed, from vote 1
    upward, stopping at the first vote number the chamber hasn't posted.

    Votes copied from Voteview count as missing, so the official file replaces them."""
    with conn.cursor() as cur:
        cur.execute("select roll_number from core.roll_call where chamber=%s and congress=%s "
                    "and session=%s and source <> 'voteview'", (chamber, congress, session_no))
        have = {row[0] for row in cur.fetchall()}
    http, loaded, failed, vacated, roll = http_session(), 0, 0, 0, 1
    pause = SENATE_PAUSE_SECONDS if chamber == "senate" else REQUEST_PAUSE_SECONDS
    cap = SENATE_MAX_PER_RUN if chamber == "senate" else None
    refused = False
    while True:
        if roll in have:
            roll += 1
            continue
        if cap and loaded + vacated >= cap:
            log.info("%s %s-%s: %d files this run, the most per run; the next run carries on at vote %d",
                     chamber, congress, session_no, cap, roll)
            break
        if loaded and loaded % 25 == 0:
            log.info("%s %s-%s: %d loaded so far, now at vote %d", chamber, congress, session_no, loaded, roll)
        try:
            n = fetch_one(conn, chamber, congress, session_no, roll, http)
        except ValidationError as e:
            # Keep going: one bad file shouldn't block the rest. It's logged and reported.
            log.error("%s", e)
            failed += 1
            n = -1
        except PermissionError as e:
            # senate.gov's bot protection: stop for today, keep what loaded, try again next run.
            log.warning("%s; stopping this run at vote %d (%d loaded)", e, roll, loaded)
            refused = True
            break
        except ValueError as e:
            # Not a vote file at all (an unfamiliar error page, say). Stop cleanly rather
            # than guess; the raw file is saved for a look, and the next run resumes here.
            log.error("%s %s-%s vote %d: unexpected file, stopping this run: %s",
                      chamber, congress, session_no, roll, e)
            failed += 1
            break
        if n is None:
            nxt = next_existing(conn, chamber, congress, session_no, roll, http)
            if nxt is None:
                break
            log.warning("%s %s-%s: no file for vote %d; the list carries on at %d",
                        chamber, congress, session_no, roll, nxt)
            failed += 1
            roll = nxt
            continue
        if n == VACATED:
            vacated += 1
        elif n >= 0:
            loaded += 1
        roll += 1
        time.sleep(pause)
    return {"loaded": loaded, "failed": failed, "vacated": vacated, "next_roll": roll, "refused": refused}


# ---------------------------------------------------------------- command line

def record_run(conn, job: str, fn):
    with conn.cursor() as cur:
        cur.execute("insert into core.ingest_run (job) values (%s) returning run_id", (job,))
        run_id = cur.fetchone()[0]
    conn.commit()
    try:
        result = fn()
    except Exception as e:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("update core.ingest_run set status='failed', finished_at=now(), message=%s "
                        "where run_id=%s", (str(e)[:2000], run_id))
        conn.commit()
        raise
    with conn.cursor() as cur:
        rows = result.get("loaded", 0) if isinstance(result, dict) else result
        cur.execute("update core.ingest_run set status='succeeded', finished_at=now(), rows_written=%s, "
                    "message=%s where run_id=%s", (rows, str(result), run_id))
    conn.commit()
    return result


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(argv) < 3 or argv[2] not in SOURCE:
        print(__doc__)
        return 2
    cmd, chamber, rest = argv[1], argv[2], argv[3:]
    with db.connect() as conn:
        if cmd == "load-file" and len(rest) == 1:
            path = Path(rest[0])
            content = path.read_bytes()
            rc = parse(chamber, content)
            sha = save_raw(conn, chamber, rc.congress, rc.session, content, path.name, None)
            n = record_run(conn, f"votes_{chamber}_file", lambda: load_roll_call(conn, rc, sha))
            print(f"Loaded {rc.roll_call_id}: {n} member votes")
        elif cmd == "fetch" and len(rest) == 3:
            congress, session_no, roll = map(int, rest)
            n = record_run(conn, f"votes_{chamber}_fetch",
                           lambda: fetch_one(conn, chamber, congress, session_no, roll))
            print("Not found" if n is None else f"Loaded {n} member votes")
        elif cmd == "sync" and (len(rest) == 2 or rest == ["current"]):
            congress, session_no = current_session() if rest == ["current"] else map(int, rest)
            result = record_run(conn, f"votes_{chamber}", lambda: sync(conn, chamber, congress, session_no))
            print(result)
            return 1 if result["failed"] else 0
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
