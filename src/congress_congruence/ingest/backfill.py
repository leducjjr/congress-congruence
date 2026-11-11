"""Load the votes of earlier Congresses, newest first, from the same sources as the current one.

    python -m congress_congruence.ingest.backfill 110 118          # both chambers, 118th back to 110th
    python -m congress_congruence.ingest.backfill 117 117 house    # one chamber, one Congress

House: the Clerk's official vote files (clerk.house.gov/evs), one request per vote with a pause
between them, so a Congress takes about an hour. They exist from 1990 (101st Congress, 2nd session).
Earlier House votes (1989 and before) come from Voteview, one download per Congress; for the 101st,
Voteview fills only the 1989 votes, since it never replaces a vote loaded from the Clerk's files.
Senate: Voteview's file for the whole Congress (one download), as for the current Congress.

Safe to stop and re-run: votes already loaded are skipped, so a re-run carries on where it stopped.
Members don't need loading first: the member list already includes everyone who has served.
Each chamber and Congress is recorded as its own run (core.ingest_run), so a failure in one
doesn't undo the others.
"""

import logging
import sys

from .votes import current_session, record_run

log = logging.getLogger(__name__)

FIRST_HOUSE_FILES = (101, 2)          # the Clerk's vote files start with the 2nd session of the 101st


def house_sessions(congress: int) -> list[int]:
    if congress < FIRST_HOUSE_FILES[0]:
        return []
    return [s for s in (1, 2) if (congress, s) >= FIRST_HOUSE_FILES]


def plan(first: int, last: int, chambers: list[str]) -> list[tuple[str, int, int | None]]:
    """(chamber, congress, session or None for the whole Congress), newest Congress first."""
    steps = []
    for congress in range(last, first - 1, -1):
        if "house" in chambers:
            steps += [("house", congress, s) for s in house_sessions(congress)]
            if congress <= FIRST_HOUSE_FILES[0]:          # votes before the Clerk's files: Voteview
                steps.append(("house", congress, None))
        if "senate" in chambers:
            steps.append(("senate", congress, None))
    return steps


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = argv[1:]
    chambers = [a for a in args if a in ("house", "senate")] or ["house", "senate"]
    nums = [a for a in args if a.isdigit()]
    current = current_session()[0]
    unknown = [a for a in args if not a.isdigit() and a not in ("house", "senate")]
    if len(nums) != 2 or unknown:
        print(__doc__)
        return 2
    first, last = sorted(map(int, nums))
    if last >= current:
        print(f"The {current}th Congress is the current one; its votes load on the regular schedule. "
              f"Use {current - 1} or earlier.")
        return 2
    if first < 1:
        print(__doc__)
        return 2

    from .. import db
    from . import votes, voteview
    failed = 0
    with db.connect() as conn:
        for chamber, congress, session in plan(first, last, chambers):
            log.info("== %s, %sth Congress%s", chamber, congress, f", session {session}" if session else "")
            try:
                if chamber == "house" and session is None:
                    result = record_run(conn, f"backfill_house_{congress}_voteview",
                                        lambda: voteview.run(conn, "house", congress))
                elif chamber == "house":
                    result = record_run(conn, f"backfill_house_{congress}_{session}",
                                        lambda: votes.sync(conn, "house", congress, session))
                else:
                    result = record_run(conn, f"backfill_senate_{congress}",
                                        lambda: voteview.run(conn, "senate", congress))
            except Exception as e:             # recorded as a failed run; carry on with the rest
                log.error("%s %s%s failed: %s", chamber, congress, f"-{session}" if session else "", e)
                failed += 1
                continue
            log.info("%s", result)
            failed += bool(result.get("failed"))
    log.info("Done. %s", "Some steps reported problems: see above and logs." if failed else "No problems.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
