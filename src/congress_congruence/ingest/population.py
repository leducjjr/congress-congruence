"""Residents per state and House district, from the Census Bureau's American Community Survey.

    python -m congress_congruence.ingest.population 2024     # ACS 2024 1-year (119th Congress lines)
    python -m congress_congruence.ingest.population 2023     # ACS 2023 1-year (118th Congress lines)

Each ACS release reports districts as drawn for one Congress, and says which in the
district names ("Congressional District 6 (119th Congress), Texas"); that's what the
rows are filed under. Re-running a year replaces its rows.

Uses https://api.census.gov (no key needed at this volume; set CENSUS_API_KEY in .env
to use one). Guam, the Virgin Islands, American Samoa and the Northern Mariana Islands
aren't in the ACS, so their delegates show no population.
"""

import logging
import os
import re
import sys

from .. import db
from .votes import http_session

log = logging.getLogger(__name__)

API = "https://api.census.gov/data/{year}/acs/acs1"
TOTAL_POPULATION = "B01003_001E"
FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}
CONGRESS_IN_NAME = re.compile(r"\((\d+)(?:st|nd|rd|th) Congress\)")


def fetch(year: int, geography: str, within: str | None = None, http=None) -> list[list[str]]:
    params = {"get": f"NAME,{TOTAL_POPULATION}", "for": geography}
    if within:
        params["in"] = within
    if os.environ.get("CENSUS_API_KEY"):
        params["key"] = os.environ["CENSUS_API_KEY"]
    resp = (http or http_session()).get(API.format(year=year), params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def parse_districts(table: list[list[str]]) -> tuple[int, list[tuple[str, int, int]]]:
    """(congress, [(state, district, population)]) from a 'congressional district' response."""
    header, rows = table[0], table[1:]
    i_name, i_pop = header.index("NAME"), header.index(TOTAL_POPULATION)
    i_state, i_cd = header.index("state"), header.index("congressional district")
    congresses, out = set(), []
    for r in rows:
        st = FIPS.get(r[i_state])
        m = CONGRESS_IN_NAME.search(r[i_name])
        if not st or not m or r[i_pop] in (None, ""):
            continue
        congresses.add(int(m.group(1)))
        code = int(r[i_cd])
        out.append((st, 0 if code in (0, 98) else code, int(r[i_pop])))   # 00 at-large, 98 delegate
    if len(congresses) != 1:
        raise ValueError(f"Expected district names for one Congress, found {sorted(congresses) or 'none'}")
    return congresses.pop(), out


def parse_states(table: list[list[str]]) -> list[tuple[str, int]]:
    header, rows = table[0], table[1:]
    i_pop, i_state = header.index(TOTAL_POPULATION), header.index("state")
    return [(FIPS[r[i_state]], int(r[i_pop])) for r in rows if r[i_state] in FIPS and r[i_pop]]


def load(conn, year: int, http=None) -> dict:
    congress, districts = parse_districts(fetch(year, "congressional district:*", "state:*", http))
    states = parse_states(fetch(year, "state:*", None, http))
    source = f"ACS {year} 1-year estimate"
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from core.area_population where congress = %s", (congress,))
        cur.executemany("insert into core.area_population (congress, state, district, population, source) "
                        "values (%s, %s, %s, %s, %s)", [(congress, s, d, p, source) for s, d, p in districts])
        cur.executemany("insert into core.area_population (congress, state, district, population, source) "
                        "values (%s, %s, null, %s, %s)", [(congress, s, p, source) for s, p in states])
    return {"congress": congress, "districts": len(districts), "states": len(states), "source": source}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(argv) != 2 or not argv[1].isdigit():
        print(__doc__)
        return 2
    from .votes import record_run
    with db.connect() as conn:
        print(record_run(conn, f"population_{argv[1]}", lambda: load(conn, int(argv[1]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
