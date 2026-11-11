"""Load members, terms and the ID crosswalk from the congress-legislators dataset.

Source: https://github.com/unitedstates/congress-legislators
Files used: legislators-current.yaml, legislators-historical.yaml

Usage:
    python -m congress_congruence.ingest.members <path to congress-legislators folder>

Members are upserted (vote rows point at them, so they are never deleted).
IDs, terms and party changes are fully replaced on every run, in one transaction.
"""

import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .. import db
from .. import party as party_positions

log = logging.getLogger(__name__)

SOURCE_FILES = ("legislators-current.yaml", "legislators-historical.yaml")
CHAMBER = {"rep": "house", "sen": "senate"}


@dataclass
class ParsedMembers:
    members: list[tuple] = field(default_factory=list)
    external_ids: list[tuple] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)
    duplicate_ids: list[tuple] = field(default_factory=list)


def read_yaml(path: Path) -> list[dict]:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # C loader is ~10x faster
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=loader)


def parse(people: list[dict]) -> ParsedMembers:
    """Turn the dataset's nested records into flat rows. No database access."""
    out = ParsedMembers()
    seen_ids: dict[tuple[str, str], str] = {}

    for person in people:
        ids = person["id"]
        bioguide = ids["bioguide"]
        name, bio = person.get("name", {}), person.get("bio", {})
        out.members.append((
            bioguide,
            name.get("first"),
            name.get("middle"),
            name.get("last"),
            name.get("suffix"),
            name.get("nickname"),
            name.get("official_full"),
            bio.get("birthday"),
            bio.get("gender"),
        ))

        for id_type, value in ids.items():
            if id_type == "bioguide" or value in (None, ""):
                continue
            for v in value if isinstance(value, list) else [value]:
                key = (id_type, str(v))
                if key in seen_ids and seen_ids[key] != bioguide:
                    # Same external ID claimed by two people: keep the first, report it.
                    out.duplicate_ids.append((id_type, str(v), seen_ids[key], bioguide))
                    continue
                if key not in seen_ids:
                    seen_ids[key] = bioguide
                    out.external_ids.append((id_type, str(v), bioguide))

        for t in person.get("terms", []):
            chamber = CHAMBER[t["type"]]
            out.terms.append({
                "bioguide_id": bioguide,
                "chamber": chamber,
                "state": t["state"],
                "district": t.get("district") if chamber == "house" else None,
                "senate_class": t.get("class") if chamber == "senate" else None,
                "party": t.get("party"),
                "caucus": t.get("caucus"),
                "start_date": t["start"],
                "end_date": t["end"],
                "how": t.get("how"),
                "end_type": t.get("end-type"),
                "listed_end_date": None,
                "party_affiliations": [
                    (a["party"], a["start"], a["end"]) for a in t.get("party_affiliations", [])
                ],
            })
    return out


# Senate seats of each class run six-year terms ending January 3 of these years (and every 6 after).
CLASS_TERM_END_YEAR = {1: 2025, 2: 2027, 3: 2029}


def as_date(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d))


def regular_end(senate_class: int, after: date) -> date:
    """The end of the seat's regular six-year term that is running on a date."""
    base = CLASS_TERM_END_YEAR[senate_class]
    year = after.year + 1
    while (year - base) % 6:
        year += 1
    return date(year, 1, 3)


def hold_appointed_seats(terms: list[dict], today: date) -> list[str]:
    """Keep an appointed senator serving until a successor appears in the list.

    The list ends an appointment on the day of the special election, but the appointee serves
    until the winner is sworn in, weeks later. So when an appointment has ended by the list's date
    and no one else (or the appointee, newly elected) has a later term in that seat, the term runs
    to the seat's regular end; the list's own date is kept in listed_end_date. Once the list adds
    the successor, the next refresh uses the list's date again. Returns who was held, for the log."""
    held = []
    for t in terms:
        t.setdefault("listed_end_date", None)
        if t["chamber"] != "senate" or t.get("how") != "appointment" or not t.get("senate_class"):
            continue
        start, end = as_date(t["start_date"]), as_date(t["end_date"])
        if end >= today:
            continue
        successor = any(o is not t and o["chamber"] == "senate" and o["state"] == t["state"]
                        and o.get("senate_class") == t["senate_class"] and as_date(o["start_date"]) > start
                        for o in terms)
        if not successor:
            t["listed_end_date"], t["end_date"] = end, regular_end(t["senate_class"], start)
            held.append(f"{t['bioguide_id']} ({t['state']}, appointed; listed end {end})")
    return held


def load(conn, parsed: ParsedMembers) -> dict[str, int]:
    """Write parsed rows to the database in a single transaction."""
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """insert into core.member (bioguide_id, first_name, middle_name, last_name, suffix,
                                        nickname, official_full, birthday, gender)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (bioguide_id) do update set
                   first_name = excluded.first_name, middle_name = excluded.middle_name,
                   last_name = excluded.last_name, suffix = excluded.suffix,
                   nickname = excluded.nickname, official_full = excluded.official_full,
                   birthday = excluded.birthday, gender = excluded.gender""",
            parsed.members,
        )

        cur.execute("delete from core.member_external_id")
        with cur.copy("copy core.member_external_id (id_type, id_value, bioguide_id) from stdin") as cp:
            for row in parsed.external_ids:
                cp.write_row(row)

        before = term_fingerprint(cur)
        cur.execute("delete from core.term")  # also removes core.term_party (cascade)
        n_party = 0
        for t in parsed.terms:
            cur.execute(
                """insert into core.term (bioguide_id, chamber, state, district, senate_class, party,
                                          caucus, start_date, end_date, how, end_type, listed_end_date)
                   values (%(bioguide_id)s, %(chamber)s, %(state)s, %(district)s, %(senate_class)s,
                           %(party)s, %(caucus)s, %(start_date)s, %(end_date)s, %(how)s, %(end_type)s,
                           %(listed_end_date)s)
                   returning term_id""",
                t,
            )
            term_id = cur.fetchone()[0]
            for party, start, end in t["party_affiliations"]:
                cur.execute(
                    "insert into core.term_party (term_id, party, start_date, end_date) values (%s, %s, %s, %s)",
                    (term_id, party, start, end),
                )
                n_party += 1

        # Which party each vote counts toward depends on the terms: if any changed, rework them all.
        if term_fingerprint(cur) != before:
            party_positions.refresh(cur)

    return {
        "members": len(parsed.members),
        "external_ids": len(parsed.external_ids),
        "terms": len(parsed.terms),
        "party_changes": n_party,
    }


def term_fingerprint(cur) -> str:
    """Changes whenever a term's dates, chamber, party or caucus change."""
    cur.execute("""select md5(coalesce(string_agg(concat_ws('|', bioguide_id, chamber, party, caucus,
                                                            start_date, end_date), ',' order by bioguide_id,
                                                  chamber, start_date), '')) from core.term""")
    return cur.fetchone()[0]


def run(source_dir: Path, conn=None) -> dict[str, int]:
    people = []
    for name in SOURCE_FILES:
        people += read_yaml(source_dir / name)
    parsed = parse(people)
    for who in hold_appointed_seats(parsed.terms, date.today()):
        log.info("Kept serving until a successor is listed: %s", who)
    for id_type, value, kept, skipped in parsed.duplicate_ids:
        log.warning("Duplicate %s ID %s: kept %s, skipped %s", id_type, value, kept, skipped)

    own_conn = conn is None
    conn = conn or db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("insert into core.ingest_run (job) values ('members') returning run_id")
            run_id = cur.fetchone()[0]
        conn.commit()
        try:
            counts = load(conn, parsed)
        except Exception as e:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    "update core.ingest_run set status='failed', finished_at=now(), message=%s where run_id=%s",
                    (str(e)[:2000], run_id),
                )
            conn.commit()
            raise
        with conn.cursor() as cur:
            cur.execute(
                """update core.ingest_run set status='succeeded', finished_at=now(),
                          rows_written=%s, message=%s where run_id=%s""",
                (sum(counts.values()), str(counts), run_id),
            )
        conn.commit()
        return counts
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    result = run(Path(sys.argv[1]))
    print("Loaded:", ", ".join(f"{v:,} {k.replace('_', ' ')}" for k, v in result.items()))
