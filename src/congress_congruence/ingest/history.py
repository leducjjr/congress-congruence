"""Load the historical record, 1789-1972 (1st to 92nd Congresses), from Voteview into the history schema
(sql/012_history.sql), for the site's /history/ section.

    python -m congress_congruence.ingest.history 1 92             # both chambers, 92nd back to 1st
    python -m congress_congruence.ingest.history 80 80 senate     # one chamber, one Congress
    python -m congress_congruence.ingest.history --status         # what's loaded

Each chamber and Congress downloads three files from Voteview (members, roll calls, votes), one at a
time with a pause between requests, then replaces that Congress in one transaction, so a run can be
stopped and restarted at any point. The members and roll-call files are kept in data/raw/voteview; the
large votes file is deleted once loaded. Nothing comes from senate.gov or the House Clerk.

Figures follow the main site's rules: a Yea or Nay is an actual Yea or Nay (paired and announced
positions count as not voting), and a party's side on a roll call is whichever of Yea or Nay more of
its members chose (none on a tie). Voteview's published totals are compared with the members' votes;
older totals often count pairs or are missing, so a mismatch is recorded (totals_match), not refused.
"""

import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import date

from .. import config, db
from .voteview import BASE_URL, CHAMBER_NAME, file_names, read_csv

log = logging.getLogger(__name__)

FIRST, LAST = 1, 92                  # 1789-1972; the main site has 1973 on
PAUSE_SECONDS = 2
PARTIES_FILE = "parties/HSall_parties.csv"
YEA, NAY = "1", "6"
PRESENT = {"7", "8"}
NOT_VOTING = {"2", "3", "4", "5", "9"}


def to_int(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except ValueError:
        return None


def build(chamber: str, members: list[dict], rollcalls: list[dict], votes: list[dict]) -> dict:
    """Everything to store for one chamber and Congress, worked out from Voteview's three files."""
    name = CHAMBER_NAME[chamber]
    members = [m for m in members if m["chamber"] == name]
    rollcalls = sorted((r for r in rollcalls if r["chamber"] == name), key=lambda r: int(r["rollnumber"]))
    n = max((int(r["rollnumber"]) for r in rollcalls), default=0)
    party_of = {m["icpsr"]: to_int(m.get("party_code")) for m in members}
    casts = {m["icpsr"]: ["0"] * n for m in members}
    for v in votes:
        if v["chamber"] != name or v["icpsr"] not in casts:
            continue
        roll = int(v["rollnumber"])
        if 1 <= roll <= n and v["cast_code"] not in ("", "0"):
            casts[v["icpsr"]][roll - 1] = v["cast_code"]

    # Each party's side on each roll call.
    side = []
    for i in range(n):
        tally = defaultdict(Counter)
        for icpsr, c in casts.items():
            if c[i] in (YEA, NAY):
                tally[party_of.get(icpsr)][c[i]] += 1
        side.append({p: (YEA if t[YEA] > t[NAY] else NAY if t[NAY] > t[YEA] else None) for p, t in tally.items()})

    dates = {int(r["rollnumber"]): date.fromisoformat(r["date"]) for r in rollcalls if r.get("date")}
    roll_rows, mismatched = [], 0
    for r in rollcalls:
        i = int(r["rollnumber"]) - 1
        col = Counter(c[i] for c in casts.values())
        yeas, nays = to_int(r.get("yea_count")), to_int(r.get("nay_count"))
        ok = None
        if yeas is not None and nays is not None:
            ok = (yeas in (col[YEA], col[YEA] + col["2"] + col["3"])
                  and nays in (col[NAY], col[NAY] + col["4"] + col["5"]))
            mismatched += not ok
        roll_rows.append({
            "rollnumber": i + 1, "session": to_int(r.get("session")), "clerk_rollnumber": to_int(r.get("clerk_rollnumber")),
            "vote_date": dates.get(i + 1), "yea_count": yeas, "nay_count": nays,
            "result": r.get("vote_result") or None, "question": r.get("vote_question") or None,
            "description": r.get("vote_desc") or r.get("dtl_desc") or None,
            "bill_number": r.get("bill_number") or None, "totals_match": ok})

    member_rows = []
    for m in members:
        c = casts[m["icpsr"]]
        p = party_of.get(m["icpsr"])
        served = [i for i, x in enumerate(c) if x != "0"]
        party_votes = sum(1 for i in served if c[i] in (YEA, NAY) and side[i].get(p))
        with_party = sum(1 for i in served if c[i] in (YEA, NAY) and side[i].get(p) == c[i])
        member_rows.append({
            "icpsr": int(m["icpsr"]), "state": m.get("state_abbrev") or None, "district": to_int(m.get("district_code")),
            "party_code": p, "casts": "".join(c), "votes_total": len(served),
            "yea": c.count(YEA), "nay": c.count(NAY), "present": sum(c.count(x) for x in PRESENT),
            "not_voting": sum(c.count(x) for x in NOT_VOTING), "party_votes": party_votes, "with_party": with_party,
            "first_vote": dates.get(served[0] + 1) if served else None,
            "last_vote": dates.get(served[-1] + 1) if served else None,
            "bioguide_id": m.get("bioguide_id") or None, "name": m.get("bioname") or f"ICPSR {m['icpsr']}",
            "born": to_int(m.get("born")), "died": to_int(m.get("died"))})
    return {"roll_calls": roll_rows, "members": member_rows, "mismatched": mismatched}


def store(conn, chamber: str, congress: int, data: dict) -> None:
    with conn.transaction(), conn.cursor() as cur:
        for m in data["members"]:
            cur.execute("""insert into history.member (icpsr, bioguide_id, name, born, died) values (%s, %s, %s, %s, %s)
                           on conflict (icpsr) do update set bioguide_id = coalesce(excluded.bioguide_id, history.member.bioguide_id),
                                 name = excluded.name, born = excluded.born, died = excluded.died""",
                        (m["icpsr"], m["bioguide_id"], m["name"], m["born"], m["died"]))
        cur.execute("delete from history.member_congress where chamber = %s and congress = %s", (chamber, congress))
        cur.execute("delete from history.roll_call where chamber = %s and congress = %s", (chamber, congress))
        cur.executemany("""insert into history.roll_call (chamber, congress, rollnumber, session, clerk_rollnumber,
                               vote_date, yea_count, nay_count, result, question, description, bill_number, totals_match)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(chamber, congress, r["rollnumber"], r["session"], r["clerk_rollnumber"], r["vote_date"],
                          r["yea_count"], r["nay_count"], r["result"], r["question"], r["description"],
                          r["bill_number"], r["totals_match"]) for r in data["roll_calls"] if r["vote_date"]])
        cur.executemany("""insert into history.member_congress (chamber, congress, icpsr, state, district, party_code,
                               casts, votes_total, yea, nay, present, not_voting, party_votes, with_party,
                               first_vote, last_vote)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(chamber, congress, m["icpsr"], m["state"], m["district"], m["party_code"], m["casts"],
                          m["votes_total"], m["yea"], m["nay"], m["present"], m["not_voting"], m["party_votes"],
                          m["with_party"], m["first_vote"], m["last_vote"]) for m in data["members"]])
        cur.execute("""insert into history.load_run (chamber, congress, roll_calls, members, totals_mismatched)
                       values (%s, %s, %s, %s, %s)
                       on conflict (chamber, congress) do update set loaded_at = now(), roll_calls = excluded.roll_calls,
                             members = excluded.members, totals_mismatched = excluded.totals_mismatched""",
                        (chamber, congress, len(data["roll_calls"]), len(data["members"]), data["mismatched"]))


def download(http, rel: str, keep: bool = True) -> bytes:
    path = config.raw_data_dir() / "voteview" / rel
    if path.exists():
        return path.read_bytes()
    r = http.get(f"{BASE_URL}/{rel}", timeout=300)
    r.raise_for_status()
    time.sleep(PAUSE_SECONDS)
    if keep:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return r.content


def load_parties(conn, http) -> int:
    rows = read_csv(download(http, PARTIES_FILE))
    names = {}
    for r in rows:
        code = to_int(r.get("party_code"))
        if code is not None and r.get("party_name"):
            names[code] = r["party_name"].strip()
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany("""insert into history.party (party_code, name) values (%s, %s)
                           on conflict (party_code) do update set name = excluded.name""", sorted(names.items()))
    return len(names)


def load(conn, http, chamber: str, congress: int) -> dict:
    files = file_names(chamber, congress)
    members = read_csv(download(http, files["members"]))
    rollcalls = read_csv(download(http, files["rollcalls"]))
    votes = read_csv(download(http, files["votes"], keep=False))
    data = build(chamber, members, rollcalls, votes)
    store(conn, chamber, congress, data)
    return {"roll_calls": len(data["roll_calls"]), "members": len(data["members"]),
            "totals_mismatched": data["mismatched"]}


def status(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("""select chamber, count(*), min(congress), max(congress), sum(roll_calls), sum(totals_mismatched)
                       from history.load_run group by chamber order by chamber""")
        rows = cur.fetchall()
        cur.execute("select pg_size_pretty(sum(pg_total_relation_size(c.oid))) from pg_class c "
                    "join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'history' and c.relkind = 'r'")
        size = cur.fetchone()[0]
    lines = [f"{ch}: {n} Congresses ({lo}-{hi}), {rc:,} roll calls, {mm:,} with totals that don't match"
             for ch, n, lo, hi, rc, mm in rows] or ["Nothing loaded yet."]
    return "\n".join(lines + [f"Space used: {size}"])


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = argv[1:]
    if args == ["--status"]:
        with db.connect() as conn:
            print(status(conn))
        return 0
    chambers = [a for a in args if a in ("house", "senate")] or ["house", "senate"]
    nums = [a for a in args if a.isdigit()]
    if len(nums) != 2:
        print(__doc__)
        return 2
    first, last = sorted(int(x) for x in nums)
    if first < FIRST or last > LAST:
        print(f"Congresses {FIRST} to {LAST} only (the main site has the 93rd on).")
        return 2
    from .votes import http_session
    http = http_session()
    problems = 0
    with db.connect() as conn:
        try:
            log.info("Parties: %d", load_parties(conn, http))
        except Exception as e:                         # noqa: BLE001 - names are a nicety; the votes come first
            log.warning("Party names not loaded (%s); party codes are kept and can be named later", e)
        for congress in range(last, first - 1, -1):
            for chamber in chambers:
                try:
                    log.info("%s %s: %s", chamber, congress, load(conn, http, chamber, congress))
                except Exception as e:                 # noqa: BLE001 - report it and go on to the next
                    problems += 1
                    log.error("%s %s failed: %s", chamber, congress, e)
        log.info("%s", status(conn).replace("\n", "; "))
    log.info("Done. %s", "No problems." if not problems else f"{problems} failed: see above.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
