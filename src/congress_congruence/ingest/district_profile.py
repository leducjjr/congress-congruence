"""Census profiles of House districts (American Community Survey), for district opinion estimates.

    python -m congress_congruence.ingest.district_profile 2024        # one ACS 1-year release
    python -m congress_congruence.ingest.district_profile 2007 2024   # a range (2020 is skipped:
                                                                       # the Census didn't release it)

Each release reports districts as drawn for one Congress, named in the data ("Congressional
District 6 (119th Congress), Texas"); rows are filed under that Congress. Where two releases cover
the same lines, the later one is kept. Needs CENSUS_API_KEY in .env, as for population.

Figures: share of adults 25+ with a bachelor's degree or more (B15002), median household income
(B19013), non-Hispanic white, non-Hispanic Black and Hispanic shares (B03002), median age (B01002).
These are official, nonpartisan descriptions of who lives in each district; no election results.
"""

import logging
import sys

from .. import db
from .population import CONGRESS_IN_NAME, FIPS, api_get

log = logging.getLogger(__name__)

BA_PLUS = [f"B15002_{n:03d}E" for n in (15, 16, 17, 18, 32, 33, 34, 35)]
# From 2012 the Census also publishes B15003 (educational attainment without the split by sex);
# some releases leave B15002 empty for districts, so both are asked for and B15003 is preferred.
BA_PLUS_2012 = [f"B15003_{n:03d}E" for n in (22, 23, 24, 25)]
OTHER = ["B19013_001E", "B03002_001E", "B03002_003E", "B03002_004E", "B03002_012E", "B01002_001E"]
VARIABLES = ["B15002_001E", *BA_PLUS, *OTHER]


def variables_for(year: int) -> list[str]:
    return VARIABLES + (["B15003_001E", *BA_PLUS_2012] if year >= 2012 else [])
NO_RELEASE = {2020}      # the 2020 ACS 1-year estimates weren't released (pandemic data collection)


def number(text):
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return None if v < 0 else v          # the Census marks missing values with large negative codes


def parse(table: list[list[str]]) -> tuple[int, list[dict]]:
    header, rows = table[0], table[1:]
    wanted = ["NAME", "state", "congressional district", *VARIABLES, "B15003_001E", *BA_PLUS_2012]
    col = {name: header.index(name) for name in wanted if name in header}
    congresses, out = set(), []
    for r in rows:
        st = FIPS.get(r[col["state"]])
        m = CONGRESS_IN_NAME.search(r[col["NAME"]])
        if not st or st == "PR" or not m:
            continue
        congresses.add(int(m.group(1)))
        code = int(r[col["congressional district"]])
        if code == 98:
            continue                                         # delegate (DC): no voting House seat
        v = {k: number(r[i]) for k, i in col.items() if k not in ("NAME", "state", "congressional district")}
        people = v["B03002_001E"]
        share = lambda part, whole: round(100 * part / whole, 2) if part is not None and whole else None  # noqa: E731
        if v.get("B15003_001E") and all(v.get(k) is not None for k in BA_PLUS_2012):
            ba = share(sum(v[k] for k in BA_PLUS_2012), v["B15003_001E"])
        elif v.get("B15002_001E") and all(v.get(k) is not None for k in BA_PLUS):
            ba = share(sum(v[k] for k in BA_PLUS), v["B15002_001E"])
        else:
            ba = None
        out.append({
            "state": st, "district": 0 if code == 0 else code,
            "pct_ba": ba,
            "median_income": v["B19013_001E"],
            "pct_white_nh": share(v["B03002_003E"], people),
            "pct_black": share(v["B03002_004E"], people),
            "pct_hispanic": share(v["B03002_012E"], people),
            "median_age": v["B01002_001E"],
        })
    if len(congresses) != 1:
        raise ValueError(f"Expected district names for one Congress, found {sorted(congresses) or 'none'}")
    return congresses.pop(), out


def load(conn, year: int, http=None) -> dict:
    congress, rows = parse(api_get(year, variables_for(year), "congressional district:*", "state:*", http))
    gaps = {f: sum(r[f] is None for r in rows) for f in ("pct_ba", "median_income", "pct_white_nh",
                                                          "pct_black", "pct_hispanic", "median_age")}
    if any(gaps.values()):
        log.warning("ACS %s: districts missing a figure: %s", year, {f: n for f, n in gaps.items() if n})
    source = f"ACS {year} 1-year estimate"
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("select max(acs_year) from core.district_profile where congress = %s", (congress,))
        have = cur.fetchone()[0]
        if have and have > year:
            return {"congress": congress, "kept": f"ACS {have} (newer)", "districts": 0}
        cur.execute("delete from core.district_profile where congress = %s", (congress,))
        cur.executemany(
            """insert into core.district_profile (congress, state, district, acs_year, pct_ba, median_income,
                   pct_white_nh, pct_black, pct_hispanic, median_age, source)
               values (%(congress)s, %(state)s, %(district)s, %(year)s, %(pct_ba)s, %(median_income)s,
                       %(pct_white_nh)s, %(pct_black)s, %(pct_hispanic)s, %(median_age)s, %(source)s)""",
            [{**r, "congress": congress, "year": year, "source": source} for r in rows])
    return {"congress": congress, "districts": len(rows), "complete": sum(all(
        r[f] is not None for f in ("pct_ba", "median_income", "pct_white_nh", "pct_black", "pct_hispanic",
                                   "median_age")) for r in rows), "source": source}


def profiles_for(conn, congress: int) -> dict:
    """{(state, district): profile} for the given Congress's lines, or {} if none are loaded.

    The Census names a new Congress in its district data only when the lines change; when they
    don't, it keeps the earlier name (the ACS 2021 release says "116th Congress", because the 117th
    used the same lines). So a Congress with no rows of its own uses the latest earlier Congress
    that has them. Load releases in order so a gap really means "unchanged"."""
    with conn.cursor() as cur:
        cur.execute("select max(congress) from core.district_profile where congress <= %s", (congress,))
        use = cur.fetchone()[0]
        if use is None:
            return {}
        if use != congress:
            log.info("No Census profiles labelled the %sth Congress; using the %sth's (same lines)", congress, use)
        cur.execute("""select state, district, pct_ba, median_income, pct_white_nh, pct_black, pct_hispanic,
                              median_age from core.district_profile where congress = %s""", (use,))
        cols = [d.name for d in cur.description]
        return {(r[0], r[1]): dict(zip(cols[2:], r[2:])) for r in cur.fetchall()}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    nums = [int(a) for a in argv[1:] if a.isdigit()]
    if not 1 <= len(nums) <= 2 or len(nums) != len(argv) - 1:
        print(__doc__)
        return 2
    years = [y for y in range(nums[0], nums[-1] + 1) if y not in NO_RELEASE]
    from .votes import record_run
    failed = 0
    with db.connect() as conn:
        for y in years:
            try:
                print(y, record_run(conn, f"district_profile_{y}", lambda: load(conn, y)))
            except Exception as e:                        # report and carry on with the other years
                log.error("ACS %s: %s", y, e)
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
