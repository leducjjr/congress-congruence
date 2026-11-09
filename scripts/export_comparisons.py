"""Export every member's vote on every surveyed question, with their constituents' estimate.

    python scripts/export_comparisons.py                 # writes data/exports/comparisons.csv.gz

One row per member per linked vote: the survey and question, the vote (chamber, Congress,
date), the member's seat and party at the time of the vote, how they voted, which side
supported the proposal, and the estimated support where they represented (state for
senators, district for representatives), with its range and majority call. The same rules
as the member panel decide "with", "against" and "too close", so the analysis matches the site.

Read-only; nothing about visitors is involved. For offline analysis of trends.
"""

import csv
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from congress_congruence import db                              # noqa: E402
from congress_congruence.api.app import agreement                # noqa: E402

SQL = """
select s.organization, s.kind, si.survey, si.variable, si.question, siv.match_kind, siv.support_side,
       r.roll_call_id, r.chamber, r.congress, r.vote_date, r.yea_total, r.nay_total,
       mv.bioguide_id, t.state, t.district, coalesce(nullif(t.caucus, t.party), t.party) as party,
       mv.position, oe.support, oe.support_low, oe.support_high, oe.majority, oe.respondents
  from core.survey_item_vote siv
  join core.survey_item si on si.survey = siv.survey and si.variable = siv.variable
  join core.survey s on s.survey = si.survey
  join core.roll_call r on r.roll_call_id = siv.roll_call_id
  join core.member_vote mv on mv.roll_call_id = r.roll_call_id
  join lateral (
        select state, district, party, caucus from core.term t
         where t.bioguide_id = mv.bioguide_id and t.chamber = r.chamber
           and r.vote_date between t.start_date and t.end_date
         order by t.start_date desc limit 1) t on true
  left join core.opinion_estimate oe on oe.survey = si.survey and oe.variable = si.variable
                                    and oe.state = t.state
                                    and ((r.chamber = 'senate' and oe.district is null)
                                      or (r.chamber = 'house' and oe.district = t.district))
 order by r.vote_date, si.survey, si.variable, mv.bioguide_id
"""


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "data" / "exports" / "comparisons.csv.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with db.connect() as conn, conn.cursor() as cur, gzip.open(out, "wt", newline="") as fh:
        cur.execute(SQL)
        cols = [d.name for d in cur.description]
        w = csv.writer(fh)
        w.writerow(cols + ["agreement"])
        for row in cur:
            r = dict(zip(cols, row))
            verdict = ("not_surveyed" if r["majority"] is None
                       else agreement(r["position"], r["majority"], r["support_side"] or "yea"))
            w.writerow(list(row) + [verdict])
            n += 1
    print(f"{n:,} rows -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
