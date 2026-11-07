"""Read-only JSON API for the panels and, later, the phone app.

Run locally:
    uvicorn congress_congruence.api.app:app --port 8000

Endpoints (all GET):
    /v1/health                         is the database reachable; how fresh is the data
    /v1/members?state=TX&chamber=house members serving today
    /v1/members/{bioguide_id}          profile, attendance, votes with party majority
    /v1/members/{bioguide_id}/votes    most recent votes (limit=1..100, default 20)

Settings (environment or .env):
    API_DATABASE_URL   connection for a read-only database login (falls back to DATABASE_URL)
    API_CORS_ORIGINS   comma-separated sites allowed to call the API from a browser (optional)

The API never writes. Connections are opened read-only, and in production the
database login itself only has SELECT permission (see deploy/README.md).
"""

import os
import re
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .. import config  # noqa: F401  (loads .env)
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
             "latest_vote": r["latest_vote"]} for r in fetch(q.FRESHNESS)]
    runs = {r["job"]: r["finished_at"] for r in fetch(q.LAST_RUNS)}
    return {"status": "ok", "data": data, "last_successful_runs": runs}


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
