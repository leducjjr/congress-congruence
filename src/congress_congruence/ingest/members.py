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
from pathlib import Path

import yaml

from .. import db

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
                "party_affiliations": [
                    (a["party"], a["start"], a["end"]) for a in t.get("party_affiliations", [])
                ],
            })
    return out


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

        cur.execute("delete from core.term")  # also removes core.term_party (cascade)
        n_party = 0
        for t in parsed.terms:
            cur.execute(
                """insert into core.term (bioguide_id, chamber, state, district, senate_class, party,
                                          caucus, start_date, end_date, how, end_type)
                   values (%(bioguide_id)s, %(chamber)s, %(state)s, %(district)s, %(senate_class)s,
                           %(party)s, %(caucus)s, %(start_date)s, %(end_date)s, %(how)s, %(end_type)s)
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

    return {
        "members": len(parsed.members),
        "external_ids": len(parsed.external_ids),
        "terms": len(parsed.terms),
        "party_changes": n_party,
    }


def run(source_dir: Path, conn=None) -> dict[str, int]:
    people = []
    for name in SOURCE_FILES:
        people += read_yaml(source_dir / name)
    parsed = parse(people)
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
