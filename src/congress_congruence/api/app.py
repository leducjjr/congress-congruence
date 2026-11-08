"""Read-only JSON API for the panels and, later, the phone app.

Run locally:
    uvicorn congress_congruence.api.app:app --port 8000

Endpoints (all GET):
    /v1/health                         is the database reachable; how fresh is the data
    /v1/surveys                        every survey loaded, with links (Sources page)
    /v1/search?q=cruz                  members serving today, by name, state or seat (TX-7)
    /v1/members?state=TX&chamber=house members serving today
    /v1/members/{bioguide_id}          profile, attendance, votes with party majority
    /v1/members/{bioguide_id}/votes    most recent votes (limit=1..100, default 20)
    /v1/members/{bioguide_id}/opinion  surveyed votes compared with constituents' estimated views

Settings (environment or .env):
    API_DATABASE_URL   connection for a read-only database login (falls back to DATABASE_URL)
    API_CORS_ORIGINS   comma-separated sites allowed to call the API from a browser (optional)

The API never writes. Connections are opened read-only, and in production the
database login itself only has SELECT permission (see deploy/README.md).
"""

import os
import re
import unicodedata
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .. import config  # noqa: F401  (loads .env)
from ..ingest.ppc import STATE_NAMES as ppc_states
from ..ingest.votes import current_session
from . import queries as q

BIOGUIDE_RE = re.compile(r"^[A-Z]\d{6}$")
STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR", "GU", "VI", "AS", "MP",
}
CACHE = "public, max-age=300"   # data changes at most every couple of hours

pool: ConnectionPool | None = None


def database_url() -> str:
    url = os.environ.get("API_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set API_DATABASE_URL (or DATABASE_URL)")
    return url


def make_read_only(conn) -> None:
    # psycopg's conn.read_only only applies to transactions it opens, which it doesn't
    # do in autocommit mode, so set Postgres's own session default instead.
    conn.autocommit = True
    conn.execute("set default_transaction_read_only = on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = ConnectionPool(database_url(), min_size=1, max_size=5, configure=make_read_only,
                          kwargs={"row_factory": dict_row}, open=True)
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="congress-congruence API", version="0.1.0", lifespan=lifespan,
              docs_url="/v1/docs", openapi_url="/v1/openapi.json")

origins = [o.strip() for o in os.environ.get("API_CORS_ORIGINS", "").split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"])


def fetch(sql: str, params: dict | None = None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params or {}).fetchall()


def member_summary(row: dict) -> dict:
    return {
        "bioguide_id": row["bioguide_id"],
        "name": row["name"],
        "chamber": row["chamber"],
        "state": row["state"],
        "district": row["district"] if row["chamber"] == "house" else None,
        "seat": q.seat_label(row["state"], row["district"], row["chamber"]),
        "party": row["party"],
        "caucus": row["caucus"],
    }


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


@app.get("/v1/health")
def health(response: Response):
    response.headers["Cache-Control"] = "no-cache"
    data = [{"chamber": r["chamber"], "source": r["source"], "votes": r["votes"],
             "first_vote": r["first_vote"], "latest_vote": r["latest_vote"],
             "first_congress": r["first_congress"], "latest_congress": r["latest_congress"]}
            for r in fetch(q.FRESHNESS)]
    runs = {r["job"]: r["finished_at"] for r in fetch(q.LAST_RUNS)}
    return {"status": "ok", "data": data, "last_successful_runs": runs}


@app.get("/v1/surveys")
def surveys(response: Response):
    """Every survey loaded, newest first within each organization (for the Sources page)."""
    response.headers["Cache-Control"] = CACHE
    keys = ("survey", "title", "fielded", "respondents", "dataset_url", "guide_url", "about_url",
            "organization", "description", "items")
    return {"surveys": [{k: r[k] for k in keys} for r in fetch(q.SURVEY_LIST)]}


def fold(text: str) -> str:
    """Lowercase without accents, so 'velazquez' finds 'Velázquez'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


STATE_NAMES = {fold(name): code for name, code in {
    **ppc_states, "District of Columbia": "DC", "Washington DC": "DC", "Puerto Rico": "PR", "Guam": "GU",
    "Virgin Islands": "VI", "U.S. Virgin Islands": "VI", "American Samoa": "AS",
    "Northern Mariana Islands": "MP"}.items()}
SEAT_RE = re.compile(r"^([a-z]{2})\s*-?\s*(\d{1,2}|al|at-large)$")


def search_members(query: str, rows: list[dict], limit: int = 12) -> list[dict]:
    """Members serving today matching a name, a state, or a seat. Examples:
    'cruz', 'ted c', 'velazquez', 'Texas', 'TX', 'TX-7', 'tx 7', 'ak-al'. A trailing * is ignored."""
    q = fold(query).replace("*", " ").strip()
    q = re.sub(r"\s+", " ", q)
    if not q:
        return []
    seat = SEAT_RE.match(q)
    if seat and seat.group(1).upper() in STATES:
        st, d = seat.group(1).upper(), seat.group(2)
        district = 0 if d in ("al", "at-large") else int(d)
        return [r for r in rows if r["chamber"] == "house" and r["state"] == st
                and (r["district"] or 0) == district][:limit]
    state = STATE_NAMES.get(q) or (q.upper() if len(q) == 2 and q.upper() in STATES else None)
    if state:
        mine = [r for r in rows if r["state"] == state]
        return sorted(mine, key=lambda r: (r["chamber"] != "senate", r["district"] or 0, r["last_name"] or ""))[:limit]

    tokens = q.split(" ")
    scored = []
    for r in rows:
        words = re.split(r"[\s.,'-]+", fold(r["name"]))
        where = {r["state"].lower(), *[w for n, c in STATE_NAMES.items() if c == r["state"] for w in n.split()]}
        if not all(any(w.startswith(t) for w in words) or t in where for t in tokens):
            continue
        last = fold(r["last_name"] or "")
        score = (0 if last.startswith(tokens[0]) else 1, r["chamber"] != "senate", r["state"], r["district"] or 0)
        scored.append((score, r))
    return [r for _, r in sorted(scored, key=lambda x: x[0])][:limit]


@app.get("/v1/search")
def search(response: Response, text: str = Query(..., alias="q", min_length=2, max_length=60)):
    """Find members serving today by name, state or seat (more kinds of results to come)."""
    rows = fetch(q.CURRENT_MEMBERS, {"on": date.today(), "state": None, "chamber": None})
    response.headers["Cache-Control"] = CACHE
    return {"query": text, "members": [member_summary(r) for r in search_members(text, rows)]}


@app.get("/v1/members")
def members(response: Response,
            state: str | None = Query(None, min_length=2, max_length=2),
            chamber: str | None = Query(None, pattern="^(house|senate)$")):
    if state is not None:
        state = state.upper()
        if state not in STATES:
            raise HTTPException(400, "Unknown state code")
    rows = fetch(q.CURRENT_MEMBERS, {"on": date.today(), "state": state, "chamber": chamber})
    rows.sort(key=lambda r: (r["chamber"] != "senate", r["state"], r["district"] or 0, r["last_name"]))
    response.headers["Cache-Control"] = CACHE
    return {"members": [member_summary(r) for r in rows]}


def get_member_row(bioguide_id: str) -> dict:
    if not BIOGUIDE_RE.match(bioguide_id):
        raise HTTPException(400, "A member ID looks like B001277")
    rows = fetch(q.MEMBER, {"id": bioguide_id, "on": date.today()})
    if not rows:
        raise HTTPException(404, "No member with that ID")
    return rows[0]


def seat_population(row: dict) -> dict | None:
    """Residents of the member's seat (lines of the Congress their term began in), with context."""
    if row["chamber"] == "senate":
        # Six-year terms span Congresses, and a state's population doesn't depend on district lines.
        found = fetch(q.STATE_POPULATION, {"state": row["state"]})
    else:
        congress = current_session(row["start_date"])[0]
        found = fetch(q.AREA_POPULATION, {"congress": congress, "state": row["state"], "district": row["district"]})
    if not found:
        return None
    congress = found[0]["congress"]
    ctx = fetch(q.POPULATION_CONTEXT, {"congress": congress})[0]
    return {
        "residents": found[0]["population"],
        "source": found[0]["source"],
        "congress": congress,
        "area": q.seat_label(row["state"], row["district"], row["chamber"]),
        "average_district": int(ctx["avg_district"]) if ctx["avg_district"] else None,
        "smallest_state": {"state": ctx["smallest_state"], "residents": ctx["smallest_pop"]} if ctx["smallest_state"] else None,
        "largest_state": {"state": ctx["largest_state"], "residents": ctx["largest_pop"]} if ctx["largest_state"] else None,
    }


@app.get("/v1/members/{bioguide_id}")
def member(bioguide_id: str, response: Response):
    row = get_member_row(bioguide_id)
    congress = current_session()[0]
    s = fetch(q.STATS, {"id": bioguide_id, "congress": congress, "chamber": row["chamber"]})[0]
    response.headers["Cache-Control"] = CACHE
    return {
        **member_summary(row),
        "serving": row["serving"],
        "term": {"start": row["start_date"], "end": row["end_date"]},
        "population": seat_population(row),
        "stats": {
            "congress": congress,
            "votes_total": s["votes_total"],
            "votes_missed": s["votes_missed"],
            "missed_pct": pct(s["votes_missed"], s["votes_total"]),
            "party_votes": s["party_votes"],
            "with_party": s["with_party"],
            "with_party_pct": pct(s["with_party"], s["party_votes"]),
            "first_vote": s["first_vote"],
            "last_vote": s["last_vote"],
        },
    }


@app.get("/v1/members/{bioguide_id}/votes")
def member_votes(bioguide_id: str, response: Response, limit: int = Query(20, ge=1, le=100)):
    get_member_row(bioguide_id)
    rows = fetch(q.RECENT_VOTES, {"id": bioguide_id, "limit": limit})
    response.headers["Cache-Control"] = CACHE
    return {"votes": [{
        "roll_call_id": r["roll_call_id"],
        "chamber": r["chamber"],
        "date": r["vote_date"],
        "question": r["question"],
        "description": r["description"],
        "result": r["result"],
        "bill": q.bill_info(r["bill_congress"], r["bill_type"], r["bill_number"]),
        "yea_total": r["yea_total"],
        "nay_total": r["nay_total"],
        "position": r["position"],
        "position_detail": r["raw_position"],
        "source": r["source"],
        "official_url": q.official_vote_url(r["chamber"], r["congress"], r["session"],
                                            r["roll_number"], r["vote_date"]),
    } for r in rows]}


def sided_with(position: str, support_side: str = "yea") -> str | None:
    """Which side of the survey question the vote was on: 'support', 'oppose', or None (didn't vote)."""
    if position not in ("yea", "nay"):
        return None
    return "support" if position == support_side else "oppose"


def agreement(position: str, majority: str, support_side: str = "yea") -> str:
    """How a vote lines up with the estimated majority where the member represents."""
    side = sided_with(position, support_side)
    if side is None:
        return "did_not_vote"
    if majority == "too_close":
        return "too_close"
    return "with" if side == majority else "against"


def tally(items: list[dict]) -> dict:
    """Score only votes on the same proposal the survey asked about, where the majority was clear."""
    same = [i for i in items if i["match"] == "same"]
    counted = [i for i in same if i["agreement"] in ("with", "against")]
    return {"surveyed_votes": len(same), "clear_majority": len(counted),
            "with_majority": sum(i["agreement"] == "with" for i in counted),
            "related_votes": len(items) - len(same)}


@app.get("/v1/members/{bioguide_id}/opinion")
def member_opinion(bioguide_id: str, response: Response):
    row = get_member_row(bioguide_id)
    rows = fetch(q.OPINION, {"id": bioguide_id})
    surveys = {r["survey"]: r for r in fetch(q.SURVEYS)}
    items = [{
        "survey": r["survey"],
        "item": r["variable"],
        "question": r["question"],
        "note": r["note"],
        "vote": {
            "roll_call_id": r["roll_call_id"], "date": r["vote_date"], "question": r["vote_question"],
            "result": r["result"], "yea_total": r["yea_total"], "nay_total": r["nay_total"],
            "official_url": q.official_vote_url(r["chamber"], r["congress"], r["session"],
                                                r["roll_number"], r["vote_date"]),
        },
        "position": r["position"],
        "match": r["match_kind"],                       # same | related (related is never scored)
        "support_side": r["support_side"],              # which vote (yea/nay) supported the proposal
        "sided_with": sided_with(r["position"], r["support_side"]),
        # Where to read the exact question: the area's own PDF if the survey publishes per area,
        # else the survey's guide (search it for the item's variable name).
        "wording_url": r["source_url"] or surveys.get(r["survey"], {}).get("guide_url"),
        "wording_hint": None if r["source_url"] else r["variable"],
        "constituents": {
            "area": "state" if r["chamber"] == "senate" else "district",
            "area_label": q.seat_label(r["state"], r["seat_district"], r["chamber"]),   # seat at vote time
            "support_pct": round(100 * r["support"], 1),
            "range_pct": [round(100 * r["support_low"], 1), round(100 * r["support_high"], 1)],
            "majority": r["majority"],
            "respondents": r["respondents"],
            "residents": r["residents"],
        },
        "agreement": agreement(r["position"], r["majority"], r["support_side"]),
    } for r in rows]
    samples, res = {}, {}
    for i in items:
        key = (i["survey"], i["constituents"]["area_label"])
        samples[key] = max(samples.get(key, 0), i["constituents"]["respondents"])
        res[key] = i["constituents"]["residents"]
    response.headers["Cache-Control"] = CACHE
    return {
        "area": q.seat_label(row["state"], row["district"], row["chamber"]),
        "summary": tally(items),
        # The same score per survey organization: sources are shown side by side, never blended.
        "by_source": [{"organization": org, **tally([i for i in items
                                                     if surveys[i["survey"]]["organization"] == org])}
                      for org in dict.fromkeys(surveys[i["survey"]]["organization"] for i in items)],
        # People surveyed where the member represented them, per survey (largest count among its questions).
        "samples": sorted(({"survey": k[0], "area_label": k[1], "surveyed": v, "residents": res.get(k)}
                           for k, v in samples.items()), key=lambda x: x["survey"], reverse=True),
        "surveys": [{
            "name": s["survey"], "title": s["title"], "fielded": s["fielded"], "respondents": s["respondents"],
            "dataset_url": s["dataset_url"], "guide_url": s["guide_url"], "about_url": s["about_url"],
            "organization": s["organization"], "description": s["description"],
        } for s in surveys.values() if any(i["survey"] == s["survey"] for i in items)],
        "items": items,
    }
