# congress-congruence

Measures how often members of the U.S. House and Senate vote with the
estimated majority opinion of their own constituents, per vote and over time.

See the systems inventory doc for the full design. This repo implements it in phases:

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Schema, member loader, House + Senate vote ingestion, validation | In progress |
| 2 | Voteview historical backfill and reconciliation | Not started |
| 3 | CES opinion data, item-to-vote linking, MRP, congruence scores | Not started |
| 4 | API, dashboard, address-to-district lookup | Not started |

## Layout

```
sql/                    Database schema, applied in filename order
src/congress_congruence/         Python package
  config.py             Settings read from environment / .env
  db.py                 Database connection and schema migration
  ingest/members.py     Loads members, terms and ID crosswalk
tests/                  Automated tests (pytest)
data/raw/               Downloaded source files, kept as-is (not committed)
```

## Setup

Requires Python 3.11+ and PostgreSQL 14+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env          # then edit DATABASE_URL
createdb congress             # or create it however you manage Postgres
python -m congress_congruence.db migrate
```

## Load members

```bash
# Get the member dataset (re-run `git pull` inside it to refresh)
git clone --depth 1 https://github.com/unitedstates/congress-legislators.git data/raw/congress-legislators

python -m congress_congruence.ingest.members data/raw/congress-legislators
```

Safe to re-run: every load replaces the member tables inside one transaction.

## Run tests

```bash
pytest
```

Tests that need a database use `TEST_DATABASE_URL` and are skipped if it isn't set.

## Design notes

- **Both chambers from the start.** `roll_call` and `member_vote` hold House
  and Senate together, keyed by chamber.
- **One member key.** Every member is identified by Bioguide ID. House vote
  files use Bioguide IDs directly; Senate vote files use LIS IDs, which are
  translated through `core.member_external_id`.
- **Raw first.** Source files are saved unchanged before parsing, so data can
  be reprocessed without downloading again.

## Known data gaps (found during Phase 1 load, Nov 2026)

- Every senator since 1989 has a Senate LIS ID, so Senate vote files will
  translate cleanly.
- About 300 members who started in 2020 or later have no Voteview (ICPSR) ID in
  congress-legislators. Voteview's own member file includes Bioguide IDs, so the
  Phase 2 backfill should build that link from Voteview's side.
- The dataset showed 98 senators and 433 voting House members serving on the
  load date. Check whether that reflects real vacancies or lag in the dataset.
