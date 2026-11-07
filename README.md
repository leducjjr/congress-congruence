# congress-congruence

Measures how often members of the U.S. House and Senate vote with the
estimated majority opinion of their own constituents, per vote and over time.

See the systems inventory doc for the full design. This repo implements it in phases:

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Schema, member loader, House + Senate vote ingestion, validation | Built; live download not yet run |
| 2 | Voteview historical backfill and reconciliation | Not started |
| 3 | CES opinion data, item-to-vote linking, MRP, congruence scores | Not started |
| 4 | API, dashboard, address-to-district lookup | Not started |

## Layout

```
sql/                          Database schema, applied in filename order
src/congress_congruence/      Python package
  config.py                   Settings read from environment / .env
  db.py                       Database connection and schema migration
  ingest/members.py           Loads members, terms and ID crosswalk
  ingest/vote_parsers.py      Parses House Clerk and Senate LIS vote XML
  ingest/votes.py             Fetches, validates and loads votes (both chambers)
tests/                        Automated tests (pytest)
  fixtures/                   Real vote files used by the tests
data/raw/                     Downloaded source files, kept as-is (not committed)
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
Load members before votes, and refresh them when new members are sworn in.

## Load votes

```bash
# Scheduled job: download every vote newer than the last one loaded
python -m congress_congruence.ingest.votes sync house  119 1
python -m congress_congruence.ingest.votes sync senate 119 1

# One specific vote
python -m congress_congruence.ingest.votes fetch house 119 1 362

# A file you downloaded yourself
python -m congress_congruence.ingest.votes load-file senate path/to/vote_119_1_00077.xml
```

Each vote is checked before it is written: member rows must add up to the
chamber's published Yea/Nay/Present/Not Voting totals, no member may appear
twice, and every member must already exist in the member table. A vote that
fails is skipped and logged; `sync` keeps going and exits with code 1 so a
scheduler can alert on it. Re-loading a vote replaces it.

Arguments are congress and session (e.g. `119 1` = 119th Congress, 1st
session, 2025). On a first `sync` this downloads the whole session one file at
a time with a one-second pause between requests.

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
- The two test fixtures were rebuilt from browser printouts of the official
  files, so line breaks inside long text fields may differ from the originals.
  The parsers collapse whitespace, so this doesn't affect results. The download
  code (`fetch`, `sync`) was tested with a stand-in and still needs a first
  real run.
