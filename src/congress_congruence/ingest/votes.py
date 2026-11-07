"""Fetch, validate and load roll-call votes for both chambers.

Usage:
    # Load a vote file you already have
    python -m congress_congruence.ingest.votes load-file house  path/to/roll362.xml
    python -m congress_congruence.ingest.votes load-file senate path/to/vote_119_1_00077.xml

    # Download and load one vote
    python -m congress_congruence.ingest.votes fetch house  119 1 362
    python -m congress_congruence.ingest.votes fetch senate 119 1 77

    # Download every vote after the newest one already loaded (the scheduled job)
    python -m congress_congruence.ingest.votes sync house  119 1
    python -m congress_congruence.ingest.votes sync senate 119 1

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
SOURCE = {"house": "house_clerk", "senate": "senate_lis"}
MAX_MEMBERS = {"house": 441, "senate": 100}   # House: 435 seats + 6 delegates


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------- URLs

def first_year(congress: int) -> int:
    return 1787 + 2 * congress           # 119th Congress began in 2025


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


def save_raw(conn, chamber: str, congress: int, content: bytes, filename: str, url: str | None) -> str:
    sha = hashlib.sha256(content).hexdigest()
    path = config.raw_data_dir() / SOURCE[chamber] / str(congress) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    with conn.cursor() as cur:
        cur.execute(
            """insert into core.raw_file (sha256, source, url, local_path, bytes)
               values (%s, %s, %s, %s, %s) on conflict (sha256) do nothing""",
            (sha, SOURCE[chamber], url, str(path), len(content)),
        )
    return sha


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
                raise ValidationError(f"{rc.roll_call_id}: Bioguide IDs not in member table: {sorted(missing)}. "
                                      "Refresh members (ingest.members) and retry.")

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

def download(url: str, session: requests.Session) -> bytes | None:
    """Return the file's bytes, or None if that vote doesn't exist (yet)."""
    resp = session.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    if resp.status_code == 403:
        raise PermissionError(
            f"{url} refused the request (403). The Senate's site blocks server addresses; "
            "use the Voteview loader for Senate votes until access is granted.")
    resp.raise_for_status()
    body = resp.content
    # Some servers answer a missing file with an HTML page instead of a 404.
    if not body.lstrip().startswith(b"<?xml") and b"<html" in body[:500].lower():
        return None
    return body


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
    sha = save_raw(conn, chamber, congress, content, url.rsplit("/", 1)[1], url)
    conn.commit()
    return load_roll_call(conn, parse(chamber, content), sha, url)


def sync(conn, chamber: str, congress: int, session_no: int) -> dict[str, int]:
    """Load every vote of the session not yet loaded from the official feed, from vote 1
    upward, stopping at the first vote number the chamber hasn't posted.

    Votes copied from Voteview count as missing, so the official file replaces them."""
    with conn.cursor() as cur:
        cur.execute("select roll_number from core.roll_call where chamber=%s and congress=%s "
                    "and session=%s and source <> 'voteview'", (chamber, congress, session_no))
        have = {row[0] for row in cur.fetchall()}
    http, loaded, failed, roll = http_session(), 0, 0, 1
    while True:
        if roll in have:
            roll += 1
            continue
        if loaded and loaded % 25 == 0:
            log.info("%s %s-%s: %d loaded so far, now at vote %d", chamber, congress, session_no, loaded, roll)
        try:
            n = fetch_one(conn, chamber, congress, session_no, roll, http)
        except ValidationError as e:
            # Keep going: one bad file shouldn't block the rest. It's logged and reported.
            log.error("%s", e)
            failed += 1
            n = -1
        if n is None:
            break
        if n >= 0:
            loaded += 1
        roll += 1
        time.sleep(REQUEST_PAUSE_SECONDS)
    return {"loaded": loaded, "failed": failed, "next_roll": roll}


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
            sha = save_raw(conn, chamber, rc.congress, content, path.name, None)
            n = record_run(conn, f"votes_{chamber}_file", lambda: load_roll_call(conn, rc, sha))
            print(f"Loaded {rc.roll_call_id}: {n} member votes")
        elif cmd == "fetch" and len(rest) == 3:
            congress, session_no, roll = map(int, rest)
            n = record_run(conn, f"votes_{chamber}_fetch",
                           lambda: fetch_one(conn, chamber, congress, session_no, roll))
            print("Not found" if n is None else f"Loaded {n} member votes")
        elif cmd == "sync" and len(rest) == 2:
            congress, session_no = map(int, rest)
            result = record_run(conn, f"votes_{chamber}", lambda: sync(conn, chamber, congress, session_no))
            print(result)
            return 1 if result["failed"] else 0
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
