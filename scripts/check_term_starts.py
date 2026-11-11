"""Check the member list's term start dates against the roll-call record.

The member list sometimes gives a Congress's opening day as the start for a member who actually
arrived later, by special election or appointment (Hoyer, Pelosi, Whitten...). The roll calls show
when someone was really there: Voteview marks, on every vote, whether each person was a member at
the time (cast code 0 means "not a member yet / any more"), whether or not they voted.

For every member with service since 1989, each term that claims they were there from a Congress's
first roll call is compared with the first roll call on which they were actually a member. A gap of
more than 45 days is listed (delegates, who can't vote on most roll calls, are left out), with whoever else held the seat that Congress, so each case can be
checked against the official House or Senate record before it goes in config/term_corrections.yaml.

    python scripts/check_term_starts.py          # → data/exports/term_start_check.csv

Votes since 1989 come from this site's database. Earlier Congresses come from Voteview's files,
downloaded one at a time with a pause between them; the large per-member vote files are deleted
once read. Nothing is written to the database.
"""

import csv
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

GAP_DAYS = 45                       # later than this after the first roll call is listed
FIRST_DB_CONGRESS = 101             # 1989: votes in this site's database from here on
SINCE = date(1989, 1, 3)
PAUSE_SECONDS = 2
RAW = ROOT / "data" / "raw" / "voteview"
OUT = ROOT / "data" / "exports" / "term_start_check.csv"
CHAMBER_NAME = {"house": "House", "senate": "Senate"}


def congress_on(day: date) -> int:
    year = day.year - (1 if day.year % 2 == 1 and (day.month, day.day) < (1, 3) else 0)
    return (year - 1787) // 2


# Delegates and the Resident Commissioner can't vote on most roll calls, so they look absent.
DELEGATE_STATES = {"DC", "PR", "GU", "VI", "AS", "MP"}


def find_flags(terms, first_vote, presence, gap_days=GAP_DAYS):
    """terms: dicts with bioguide_id, chamber, state, district, start_date.
    first_vote[(chamber, congress)] = date of that chamber's first roll call that Congress.
    presence[(chamber, congress)][bioguide] = (first date as a member, last date as a member).
    Returns the terms that claim a member from the first roll call who wasn't one until later."""
    flags = []
    for t in terms:
        if t["state"] in DELEGATE_STATES:
            continue
        c = congress_on(t["start_date"])
        key = (t["chamber"], c)
        if key not in first_vote or t["start_date"] > first_vote[key]:
            continue                                    # listed as starting mid-Congress: nothing to check
        seen = presence.get(key, {}).get(t["bioguide_id"])
        if seen is None:
            if t.get("end_date") and (t["end_date"] - first_vote[key]).days < 60:
                continue                                # left within weeks (e.g. to join the Cabinet)
            flags.append({**t, "congress": c, "chamber_first_vote": first_vote[key], "first_as_member": None,
                          "gap_days": None})
        elif (seen[0] - first_vote[key]).days > gap_days:
            flags.append({**t, "congress": c, "chamber_first_vote": first_vote[key], "first_as_member": seen[0],
                          "gap_days": (seen[0] - first_vote[key]).days})
    return flags


def same_district(voteview_code, district) -> bool:
    """Voteview numbers an at-large seat 1 (sometimes 0); the member list numbers it 0."""
    code = int(float(voteview_code)) if voteview_code not in (None, "") else None
    return code == district or (not district and code in (0, 1))


def from_database(conn, congresses):
    first_vote, presence = {}, defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute("""select chamber, congress, min(vote_date) from core.roll_call
                       where congress = any(%s) group by chamber, congress""", (list(congresses),))
        for ch, c, d in cur.fetchall():
            first_vote[(ch, c)] = d
        cur.execute("""select r.chamber, r.congress, mv.bioguide_id, min(r.vote_date), max(r.vote_date)
                       from core.member_vote mv join core.roll_call r using (roll_call_id)
                       where r.congress = any(%s) group by 1, 2, 3""", (list(congresses),))
        for ch, c, b, lo, hi in cur.fetchall():
            presence[(ch, c)][b] = (lo, hi)
    return first_vote, presence


def from_voteview(chamber, congress, http, log=print):
    """(first roll call date, {bioguide: (first, last) date as a member}, member rows) for one Congress."""
    from congress_congruence.ingest import voteview as vv
    files = vv.file_names(chamber, congress)
    content = {}
    for kind in ("members", "rollcalls", "votes"):
        path = RAW / files[kind]
        if not path.exists():
            url = f"{vv.BASE_URL}/{files[kind]}"
            log(f"  downloading {url}")
            r = http.get(url, timeout=300)
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            time.sleep(PAUSE_SECONDS)
        content[kind] = path.read_bytes()
    members = [m for m in vv.read_csv(content["members"]) if m["chamber"] == CHAMBER_NAME[chamber]]
    bio = {m["icpsr"]: m.get("bioguide_id") for m in members}
    dates = {r["rollnumber"]: date.fromisoformat(r["date"]) for r in vv.read_csv(content["rollcalls"])}
    seen = {}
    for v in vv.read_csv(content["votes"]):
        if v["chamber"] != CHAMBER_NAME[chamber] or v["cast_code"] in ("", "0") or not bio.get(v["icpsr"]):
            continue
        d = dates.get(v["rollnumber"])
        if d is None:
            continue
        b = bio[v["icpsr"]]
        lo, hi = seen.get(b, (d, d))
        seen[b] = (min(lo, d), max(hi, d))
    (RAW / files["votes"]).unlink(missing_ok=True)       # large; the other two are kept (small)
    return (min(dates.values()) if dates else None), seen, members


def main() -> int:
    from congress_congruence import db
    from congress_congruence.ingest.votes import http_session

    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("""select t.bioguide_id, coalesce(m.official_full, m.first_name || ' ' || m.last_name),
                              t.chamber, t.state, t.district, t.start_date, t.end_date
                       from core.term t join core.member m using (bioguide_id)
                       where t.bioguide_id in (select bioguide_id from core.term where end_date > %s)
                       order by t.start_date""", (SINCE,))
        cols = ("bioguide_id", "name", "chamber", "state", "district", "start_date", "end_date")
        terms = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(f"{len({t['bioguide_id'] for t in terms}):,} members with service since 1989; {len(terms):,} terms")

    wanted = sorted({(t["chamber"], congress_on(t["start_date"])) for t in terms})
    first_vote, presence = from_database(conn, {c for _, c in wanted if c >= FIRST_DB_CONGRESS})
    seat_holders = {}                                  # (chamber, congress) -> Voteview member rows
    http = http_session()
    early = [(ch, c) for ch, c in wanted if c < FIRST_DB_CONGRESS]
    print(f"Reading Voteview for {len(early)} earlier chamber-Congresses ...")
    for ch, c in early:
        try:
            fv, seen, members = from_voteview(ch, c, http)
        except Exception as e:                         # noqa: BLE001 - report and carry on
            print(f"  skipped {ch} {c}: {e}")
            continue
        if fv:
            first_vote[(ch, c)] = fv
            presence[(ch, c)] = seen
            seat_holders[(ch, c)] = members

    flags = find_flags(terms, first_vote, presence)
    # Who else held the seat that Congress, with when they were there.
    for f in flags:
        key = (f["chamber"], f["congress"])
        others = []
        for b, (lo, hi) in presence.get(key, {}).items():
            if b == f["bioguide_id"]:
                continue
            same = [t for t in terms if t["bioguide_id"] == b and t["chamber"] == f["chamber"]
                    and congress_on(t["start_date"]) == f["congress"]
                    and t["state"] == f["state"] and (f["chamber"] == "senate" or t["district"] == f["district"])]
            vv_same = [m for m in seat_holders.get(key, []) if m.get("bioguide_id") == b and m["state_abbrev"] == f["state"]
                       and (f["chamber"] == "senate" or same_district(m.get("district_code"), f["district"]))]
            if (same or vv_same) and lo < (f["first_as_member"] or date.max):
                others.append(f"{b} {lo:%Y-%m-%d}..{hi:%Y-%m-%d}")
        f["others_in_seat_before"] = "; ".join(others)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ("bioguide_id", "name", "chamber", "state", "district", "congress", "start_date",
              "chamber_first_vote", "first_as_member", "gap_days", "others_in_seat_before")
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(flags)
    print(f"{len(flags)} terms to check, written to {OUT}")
    for f in flags[:40]:
        print(f"  {f['name']:<28} {f['chamber']:<6} {f['state']}-{f['district'] if f['district'] is not None else ''} "
              f"listed {f['start_date']}  first as member {f['first_as_member']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
