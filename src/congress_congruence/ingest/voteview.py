"""Load roll-call votes from Voteview (UCLA) for one chamber and Congress.

Voteview republishes every recorded vote. It lags the chambers by days to weeks,
so it is used for the Senate (whose site blocks server downloads) and for history.

Usage:
    python -m congress_congruence.ingest.voteview senate 119
    python -m congress_congruence.ingest.voteview senate current        # the Congress in effect today
    python -m congress_congruence.ingest.voteview senate 119 --dir data/raw/voteview   # use files already downloaded

Files (https://voteview.com/static/data/out/...):
    rollcalls/S119_rollcalls.csv   one row per vote
    votes/S119_votes.csv           one row per member per vote (by ICPSR ID)
    members/S119_members.csv       ICPSR -> Bioguide for that Congress

Each vote gets the same ID as the chamber's own file would ('s-119-1-77'),
using Voteview's session + clerk_rollnumber. A vote already loaded from the
official chamber feed is never overwritten by Voteview.
"""

import csv
import hashlib
import io
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from .. import config, db
from .vote_parsers import MemberVote, ParsedRollCall, parse_bill_ref
from .votes import ValidationError, current_session, http_session, load_roll_call, record_run

log = logging.getLogger(__name__)

BASE_URL = "https://voteview.com/static/data/out"
PREFIX = {"house": "H", "senate": "S"}
CHAMBER_NAME = {"house": "House", "senate": "Senate"}
MAX_MEMBERS = {"house": 441, "senate": 100}
# Delegates and the Resident Commissioner: in some Congresses (1993-94, 2007-10, 2019-22) they could
# vote in the Committee of the Whole; their votes are recorded but not in the published totals.
DELEGATE_STATES = {"DC", "PR", "GU", "VI", "AS", "MP"}

# Voteview cast codes. Only 1 (Yea), 6 (Nay) and 7 (Present) are recorded votes;
# paired and announced positions are not counted in the official tally, so they
# are stored as not_voting with their meaning kept in raw_position.
CAST_CODES = {
    "1": ("yea", "Yea"),
    "2": ("not_voting", "Paired Yea"),
    "3": ("not_voting", "Announced Yea"),
    "4": ("not_voting", "Announced Nay"),
    "5": ("not_voting", "Paired Nay"),
    "6": ("nay", "Nay"),
    "7": ("present", "Present"),
    "8": ("present", "Present (avoid conflict)"),
    "9": ("not_voting", "Not Voting"),
}
SKIP_CODE = "0"  # not a member at the time of the vote


def file_names(chamber: str, congress: int) -> dict[str, str]:
    p = f"{PREFIX[chamber]}{congress}"
    return {"rollcalls": f"rollcalls/{p}_rollcalls.csv",
            "votes": f"votes/{p}_votes.csv",
            "members": f"members/{p}_members.csv"}


# Some Voteview files write whole numbers as decimals ("14009.0" in the 114th Congress votes file,
# "14009" elsewhere), so ID and code columns are read as plain whole numbers before matching.
NUMBER_COLUMNS = ("icpsr", "rollnumber", "cast_code", "congress", "session", "clerk_rollnumber")
WHOLE_DECIMAL = re.compile(r"^(-?\d+)\.0+$")


def read_csv(content: bytes) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    for r in rows:
        for k in NUMBER_COLUMNS:
            if r.get(k):
                r[k] = WHOLE_DECIMAL.sub(r"\1", r[k].strip())
    return rows


def to_int(text: str | None) -> int | None:
    text = (text or "").strip()
    try:
        return int(float(text)) if text else None
    except ValueError:
        return None


def session_of(r: dict) -> int | None:
    """Voteview's session, or (where it's blank) the one its date falls in: a Congress's first
    year is its 1st session, the next its 2nd."""
    s = to_int(r.get("session"))
    if s is not None:
        return s
    try:
        first_year = 1789 + 2 * (int(r["congress"]) - 1)
        s = date.fromisoformat(r["date"]).year - first_year + 1
    except (KeyError, ValueError):
        return None
    return s if s in (1, 2) else None


def build_roll_calls(chamber: str, rollcalls: list[dict], votes: list[dict],
                     members: list[dict], known_icpsr: dict[str, str] | None = None
                     ) -> tuple[list[ParsedRollCall], list[str]]:
    """Combine the three files into ParsedRollCalls. Returns (roll calls, problems).
    known_icpsr (ICPSR -> Bioguide, from the member list) fills in members whose Voteview
    member row has no Bioguide ID."""
    name = CHAMBER_NAME[chamber]
    icpsr_to_bio, problems = dict(known_icpsr or {}), []
    for m in members:
        if m["chamber"] == name and m.get("bioguide_id"):
            icpsr_to_bio[m["icpsr"]] = m["bioguide_id"]
    member_info = {m["icpsr"]: m for m in members if m["chamber"] == name}
    # Voteview records the President's announced position on some roll calls as a
    # row in the chamber's vote file. It is not a member vote and not in the tally.
    presidents = {m["icpsr"] for m in members if m["chamber"] == "President"}

    by_roll = defaultdict(list)
    for v in votes:
        if v["chamber"] == name and v["cast_code"] != SKIP_CODE and v["icpsr"] not in presidents:
            by_roll[v["rollnumber"]].append(v)

    # A House session with no Clerk numbers at all (1989: the Clerk's records start in 1990) is
    # numbered in Voteview's order, the order the votes were taken. A session with only some
    # numbers missing is left as it is: those votes are skipped rather than guessed.
    numbered, unnumbered = defaultdict(int), defaultdict(list)
    for r in rollcalls:
        if r["chamber"] == name and session_of(r) is not None:
            if to_int(r.get("clerk_rollnumber")) is None:
                unnumbered[(r["congress"], session_of(r))].append(r)
            else:
                numbered[(r["congress"], session_of(r))] += 1
    assigned = {}
    for key, rows in unnumbered.items():
        if chamber == "house" and not numbered[key]:
            for i, r in enumerate(sorted(rows, key=lambda r: int(r["rollnumber"])), start=1):
                assigned[id(r)] = i

    out = []
    for r in rollcalls:
        if r["chamber"] != name:
            continue
        clerk_no, session = to_int(r.get("clerk_rollnumber")) or assigned.get(id(r)), session_of(r)
        if clerk_no is None or session is None:
            problems.append(f"Voteview roll {r['rollnumber']}: missing session or clerk roll number; skipped")
            continue
        bill_type, bill_number = parse_bill_ref(r.get("bill_number"))
        rc = ParsedRollCall(
            chamber=chamber,
            congress=int(r["congress"]),
            session=session,
            roll_number=clerk_no,
            vote_date=date.fromisoformat(r["date"]),
            vote_time=None,                       # Voteview has dates only
            question=r.get("vote_question") or None,
            vote_type=r.get("majority_requirement") or None,
            result=r.get("vote_result") or None,
            description=r.get("vote_desc") or r.get("dtl_desc") or None,
            bill_type=bill_type,
            bill_number=bill_number,
            amendment_number=None,
            yea_total=to_int(r.get("yea_count")),
            nay_total=to_int(r.get("nay_count")),
            present_total=None,
            not_voting_total=None,
        )
        for v in by_roll.get(r["rollnumber"], []):
            position, raw = CAST_CODES.get(v["cast_code"], ("other", f"cast code {v['cast_code']}"))
            info = member_info.get(v["icpsr"], {})
            rc.votes.append(MemberVote(
                member_id=icpsr_to_bio.get(v["icpsr"]) or f"icpsr:{v['icpsr']}",
                id_type="bioguide",
                position=position,
                raw_position=raw,
                party=None,
                state=info.get("state_abbrev") or None,
            ))
        out.append(rc)
    return out, problems


def validate_voteview(rc: ParsedRollCall) -> None:
    problems = []
    ids = [v.member_id for v in rc.votes]
    unmapped = [i for i in ids if i.startswith("icpsr:")]
    if unmapped:
        problems.append(f"no Bioguide ID in Voteview member file for {unmapped}")
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        problems.append(f"member listed twice: {dupes}")
    if len(ids) > MAX_MEMBERS[rc.chamber]:
        problems.append(f"{len(ids)} members exceeds {MAX_MEMBERS[rc.chamber]}")

    # Voteview's yea_count/nay_count may or may not include paired and announced
    # positions, and may leave out delegates' votes (see DELEGATE_STATES); accept those
    # conventions, nothing else.
    raw = Counter(v.raw_position for v in rc.votes)
    delegates = Counter(v.raw_position for v in rc.votes if v.state in DELEGATE_STATES)
    recorded = {"yea": raw["Yea"], "nay": raw["Nay"]}
    with_pairs = {"yea": raw["Yea"] + raw["Paired Yea"] + raw["Announced Yea"],
                  "nay": raw["Nay"] + raw["Paired Nay"] + raw["Announced Nay"]}
    for side, published in (("yea", rc.yea_total), ("nay", rc.nay_total)):
        accepted = {recorded[side], with_pairs[side]}
        if rc.chamber == "house":
            accepted.add(recorded[side] - delegates["Yea" if side == "yea" else "Nay"])
        if published is not None and published not in accepted:
            problems.append(f"{side}: file lists {recorded[side]} recorded "
                            f"({with_pairs[side]} with pairs), published total is {published}")
    if problems:
        raise ValidationError(f"{rc.roll_call_id} (Voteview): " + "; ".join(problems))


def official_ids(conn, chamber: str, congress: int) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("select roll_call_id from core.roll_call where chamber=%s and congress=%s "
                    "and source <> 'voteview'", (chamber, congress))
        return {row[0] for row in cur.fetchall()}


def save_raw(conn, content: bytes, rel_path: str, url: str | None) -> str:
    sha = hashlib.sha256(content).hexdigest()
    path = config.raw_data_dir() / "voteview" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)  # Voteview files are replaced in place as they update
    with conn.cursor() as cur:
        cur.execute("""insert into core.raw_file (sha256, source, url, local_path, bytes)
                       values (%s, 'voteview', %s, %s, %s) on conflict (sha256) do nothing""",
                    (sha, url, str(path), len(content)))
    conn.commit()
    return sha


def get_files(conn, chamber: str, congress: int, local_dir: Path | None) -> tuple[dict[str, bytes], str]:
    files, shas = {}, []
    http = None if local_dir else http_session()
    for kind, rel in file_names(chamber, congress).items():
        if local_dir:
            content, url = (local_dir / Path(rel).name).read_bytes(), None
        else:
            url = f"{BASE_URL}/{rel}"
            resp = http.get(url, timeout=120)
            resp.raise_for_status()
            content = resp.content
        shas.append(save_raw(conn, content, rel, url))
        files[kind] = content
    return files, shas[0]  # the rollcalls file identifies the snapshot


def run(conn, chamber: str, congress: int, local_dir: Path | None = None) -> dict:
    files, sha = get_files(conn, chamber, congress, local_dir)
    with conn.cursor() as cur:
        cur.execute("select id_value, bioguide_id from core.member_external_id where id_type = 'icpsr'")
        known = dict(cur.fetchall())
    roll_calls, problems = build_roll_calls(
        chamber, read_csv(files["rollcalls"]), read_csv(files["votes"]), read_csv(files["members"]), known)
    skip = official_ids(conn, chamber, congress)

    loaded = skipped = failed = 0
    for rc in roll_calls:
        if rc.roll_call_id in skip:
            skipped += 1
            continue
        try:
            load_roll_call(conn, rc, raw_sha=sha, source="voteview", validator=validate_voteview)
            loaded += 1
        except ValidationError as e:
            log.error("%s", e)
            failed += 1
    for p in problems:
        log.warning("%s", p)
    newest = max((rc.vote_date for rc in roll_calls), default=None)
    return {"loaded": loaded, "kept_official": skipped, "failed": failed + len(problems),
            "newest_vote": str(newest) if newest else None}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = argv[1:]
    local_dir = None
    if "--dir" in args:
        i = args.index("--dir")
        local_dir = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 2 or args[0] not in PREFIX:
        print(__doc__)
        return 2
    chamber = args[0]
    congress = current_session()[0] if args[1] == "current" else int(args[1])
    with db.connect() as conn:
        result = record_run(conn, f"voteview_{chamber}", lambda: run(conn, chamber, congress, local_dir))
    print(result)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
