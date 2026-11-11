"""How each party voted on each roll call (core.party_position, see sql/011_party_position.sql).

Kept up to date by the loaders: a roll call's rows are rewritten whenever it loads
(ingest.votes.load_roll_call), and all of them after the member list reloads terms
(ingest.members), since a member's party or caucus decides which group their vote counts in.

    python -m congress_congruence.party refresh     # rebuild every row (a minute or two)
"""

import sys
import time

from . import db

# One group per party (caucus where it differs): yea or nay, whichever more members chose.
SELECT = """
select v.roll_call_id, coalesce(t.caucus, t.party) as grp,
       case when count(*) filter (where v.position = 'yea') > count(*) filter (where v.position = 'nay') then 'yea'
            when count(*) filter (where v.position = 'nay') > count(*) filter (where v.position = 'yea') then 'nay'
       end as position
  from core.member_vote v
  join core.roll_call r using (roll_call_id)
  join core.term t on t.bioguide_id = v.bioguide_id and t.chamber = r.chamber
                  and r.vote_date between t.start_date and t.end_date
 where coalesce(t.caucus, t.party) is not null {where}
 group by 1, 2
"""


def refresh(cur, roll_call_ids: list[str] | None = None) -> None:
    """Rewrite the rows for these roll calls, or for all of them. Runs in the caller's transaction."""
    if roll_call_ids is None:
        cur.execute("delete from core.party_position")
        cur.execute("insert into core.party_position (roll_call_id, grp, position) " + SELECT.format(where=""))
    else:
        cur.execute("delete from core.party_position where roll_call_id = any(%s)", (roll_call_ids,))
        cur.execute("insert into core.party_position (roll_call_id, grp, position) "
                    + SELECT.format(where="and v.roll_call_id = any(%(ids)s)"), {"ids": roll_call_ids})


def main(argv: list[str]) -> int:
    if argv[1:] != ["refresh"]:
        print(__doc__)
        return 2
    t = time.time()
    with db.connect() as conn, conn.transaction(), conn.cursor() as cur:
        refresh(cur)
        cur.execute("select count(*) from core.party_position")
        n = cur.fetchone()[0]
    print(f"Party positions rebuilt: {n:,} rows in {time.time() - t:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
