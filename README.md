# congress-congruence

Measures how often members of the U.S. House and Senate vote with the
estimated majority opinion of their own constituents, per vote and over time.

See the systems inventory doc for the full design. This repo implements it in phases:

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Schema, member loader, House + Senate vote ingestion, validation | Built; live download not yet run |
| 2 | Voteview historical backfill and reconciliation | Not started |
| 3 | CES opinion data, item-to-vote linking, district/state estimates, comparison | First version built (CES 2025) |
| 4 | API, dashboard, address-to-district lookup | First member panel and API built |

For where every dataset comes from and every special case in handling it, see
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Layout

```
sql/                          Database schema, applied in filename order
src/congress_congruence/      Python package
  config.py                   Settings read from environment / .env
  db.py                       Database connection and schema migration
  ingest/members.py           Loads members, terms and ID crosswalk
  ingest/vote_parsers.py      Parses House Clerk and Senate LIS vote XML
  ingest/votes.py             Fetches, validates and loads votes (both chambers)
  ingest/voteview.py          Loads votes from Voteview (Senate fallback, history)
  api/app.py                  Read-only JSON API (FastAPI)
web/                          The panel: cc-member-panel.js and a dev page (index.html)
deploy/                       Server setup: API service, nginx site, step-by-step README
scripts/                      Scheduled jobs and publishing helpers
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

### Senate votes: use Voteview for now

The Senate's website refuses downloads from server addresses (HTTP 403), and
the Congress.gov API has no Senate votes yet. Until the Senate grants access,
load Senate votes from Voteview (UCLA), which republishes every roll call
with a lag of days to weeks:

```bash
python -m congress_congruence.ingest.voteview senate 119
```

Voteview votes get the same IDs as the Senate's own files (`s-119-1-77`), and
are stored with `source = 'voteview'`. A vote loaded from the official Senate
file is never overwritten by Voteview, and an official file loaded later
replaces the Voteview copy. Voteview has dates but no times of day.

Arguments are congress and session (e.g. `119 1` = 119th Congress, 1st
session, 2025). On a first `sync` this downloads the whole session one file at
a time with a one-second pause between requests.

## The member panel

`web/cc-member-panel.js` is a self-contained web component. Any page can show a
member's record with:

```html
<script src="https://dev.yourdomain.org/cc-member-panel.js" defer></script>
<cc-member-panel member="C001098"></cc-member-panel>
```

It shows the member's seat and party, a strip of their recent votes (shapes,
not party colours: filled = Yea, ring = Nay, square = Present, dash = did not
vote), how often they missed votes, how often they voted with their party's
majority, and a list of recent votes linking to Congress.gov and the official
roll call. `web/index.html` is a dev page to pick a state and member.

The API (`api/app.py`) serves `/v1/members`, `/v1/members/{id}`,
`/v1/members/{id}/votes` and `/v1/health`. Its database connections are
read-only, and in deployment it logs in with a role that only has SELECT.
Run locally with `uvicorn congress_congruence.api.app:app --port 8000`.
Server setup: `deploy/README.md`.

**Definitions.** *Missed* = votes recorded as Not Voting ÷ all votes during the
member's service in the current Congress. *With party majority* = votes where
the member voted the same way (Yea or Nay) as most of their party; ties are left
out, and independents count with the party they caucus with. Party is taken from
the member's term, so a mid-term party switch isn't reflected yet.

## Constituent opinion (CES)

The Cooperative Election Study asks people whether they support specific actions
of Congress. `config/ces_2025_items.yaml` lists the seven CES 2025 items about the
119th Congress and how to find the vote that answers each one (the last decisive
floor vote in each chamber; voting Yea is the "support" side).

```bash
python -m congress_congruence.ingest.ces inspect 2025   # what's in the release
python -m congress_congruence.ingest.ces link 2025      # review which vote each item matched
python -m congress_congruence.ingest.ces load 2025      # link + estimate every state and district
```

**How the estimates work** (`src/congress_congruence/opinion.py`). CES 2025 has
17,000 respondents, about 40 per House district, too few for raw district
percentages. Each state is pulled toward the national figure and each district
toward its state, more strongly the fewer respondents it has. How hard to pull is
learned from how much areas really differ, with a floor that assumes they can
differ by at least ~5 points. Each estimate gets a 90% range; where the range
crosses 50% the area is shown as **too close to call**, and no comparison is made.

Checked on simulated surveys with known answers (`tests/test_opinion.py` and
the notes in `opinion.py`): pooling cut district error by about a third versus
raw percentages; ranges use a multiplier of 1.9 rather than the textbook 1.645
because 1.645 only covered the truth 84-87% of the time; with 1.9 coverage was
91-96% and about 1% of clear calls were wrong.

This is simpler than full MRP, which would also use each district's demographics
and past election results and would call more districts. Senators are compared
with their whole state, where samples are much larger.

The panel's **Compared with constituents** section lists each surveyed vote,
the area's estimated support with its range, how the member voted, and whether
that was with or against a clear majority.

## Constituent opinion (Program for Public Consultation)

A second, independent survey source, shown next to CES and never blended with it. The
University of Maryland's Program for Public Consultation (PPC) surveyed 11 competitive states
and 28 competitive House districts in 2026 ("Common Ground in the Battlegrounds"). It
publishes results per state and district in questionnaire PDFs rather than as respondent
data, so the loader reads those PDFs.

```bash
python -m congress_congruence.ingest.ppc fetch 2026   # download + read the PDFs; check logs/ppc_2026_review.txt
python -m congress_congruence.ingest.ppc link 2026    # review which vote each item matched
python -m congress_congruence.ingest.ppc load 2026
```

`config/ppc_2026_items.yaml` lists the items a 119th Congress floor vote answers, which PDF
and question each comes from, and the vote. Differences from CES:

- **No pooling.** Each area has its own sample of roughly 400 to 2,000 people, so the panel shows
  that area's published share, with PPC's published confidence interval converted to the same
  90% level used for CES. Support = Favor ÷ (Favor + Oppose).
- **Method.** Online opt-in panels weighted to Census figures, and each proposal comes with a
  short background paragraph. The panel says so in the source line.
- **Votes on the other side.** `support_side: nay` marks a vote where No supports the
  proposal (e.g. an amendment to block Ukraine aid); the member's mark is placed at the
  end of the scale their vote supported.
- **Related votes.** `match: related` marks a vote on a close but different bill (e.g. the
  2026 partial stock-trading restriction against a full ban). It's shown, labelled
  "Related vote", and never counted in the with/against score.
- **Coverage.** Only senators from surveyed states and representatives from surveyed
  districts get PPC comparisons.

The panel shows one with/against line per survey organization (`by_source` in the API).

## Residents per area (Census)

```bash
python -m congress_congruence.ingest.population 2024   # ACS 2024 1-year: 119th Congress district lines
python -m congress_congruence.ingest.population 2023   # ACS 2023 1-year: 118th Congress district lines
```

Total population (table B01003) for every state and House district from the
Census Bureau's American Community Survey. Each release reports districts as
drawn for one Congress and names it in the district names; rows are filed under
that Congress. The panel shows each member's residents (with the average House
district, or the range of state sizes for senators) and, in the constituent
section, how many people were surveyed in the area out of how many residents.

## Scheduled jobs

`scripts/run_job.sh` runs one job and appends its output to `logs/<job>.log`.
`scripts/crontab.txt` schedules them (server clock, UTC):

| Job | When | What |
| --- | --- | --- |
| `members` | Daily 06:10 | Refresh the member list, so new members exist before their votes load |
| `house` | Every 2 hours at :17 | Load any new House votes for the current session |
| `senate-voteview` | Daily 06:40 | Reload the current Congress's Senate votes from Voteview |

The jobs use `current` to work out the Congress and session from today's date,
so nothing needs editing each January. Each job holds a lock, so a slow run is
never started twice. Every run is also recorded in `core.ingest_run`.

```bash
# Install the schedule (keeps any existing crontab lines)
(crontab -l 2>/dev/null; cat scripts/crontab.txt) | crontab -
crontab -l

# Recent results
tail -20 logs/house.log
psql congress_dev -c "select job, status, started_at, rows_written, message from core.ingest_run order by run_id desc limit 10;"
```

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
  The parsers collapse whitespace, so this doesn't affect results.
- First live run (Nov 7, 2026, from the dev server): House download works.
  senate.gov returned 403 for every request from the server. Voteview's Senate
  files were reachable but last updated Oct 1, 2026.
- In Voteview, paired and announced positions are stored as `not_voting`, with
  their meaning kept in `raw_position`, matching how the official tallies count them.
