# Data sources and how they are retrieved

This is the reference for a public "About this data" page. For each source, it records
where the data comes from, how it is fetched, every special case found along the way, and
how the panel's figures are calculated. When the handling of a source changes, update this
file in the same commit.

Principles that apply to every source:

- **Public data only.** Nothing about visitors is collected or stored. An address is used
  only to find the member, and any opinions a visitor enters stay in their browser.
- **Originals kept.** Every downloaded file is saved unchanged under `data/raw/` before it is
  read, so results can be rebuilt and checked without downloading again.
- **Checked before stored.** A record that doesn't add up is skipped and logged, never
  loaded half-right.
- **Sources side by side, never blended.** Each survey organization gets its own score line.
- **Only like-for-like comparisons are scored.** A vote is compared with a survey question
  only when both are about the same proposal. Close but different matches are shown,
  labelled "Related vote", and never counted.

---

## 1. Members of Congress

| | |
|---|---|
| Source | [`unitedstates/congress-legislators`](https://github.com/unitedstates/congress-legislators) (public domain, community-maintained) |
| Fetched | `git pull` of the repository, daily at 06:10 UTC (`members` job) |
| Code | `src/congress_congruence/ingest/members.py` |

- **One key per member.** Bioguide ID (the Congress's own biographical directory ID) is the
  master key. Other ID systems are translated through `core.member_external_id`:
  - Senate vote files use LIS IDs.
  - Voteview uses ICPSR IDs.
- **Terms.** Each term (chamber, state, district, party, dates) is stored separately. Every
  comparison uses the seat the member held **on the day of the vote**. That matters when
  districts are redrawn or a member moves between chambers.
- **Party and caucus.** Independents count with the party they caucus with (for "voted with
  party majority"). A party switch in the middle of a term isn't reflected yet.
- **Known gaps.**
  - About 300 members who started in 2020 or later have no ICPSR ID in this dataset; the
    Voteview member file, which lists Bioguide IDs, fills the gap.
  - On the first load, the dataset showed 98 senators and 433 voting House members.

## 2. House votes

| | |
|---|---|
| Source | Office of the Clerk, U.S. House: one XML file per roll call, `clerk.house.gov/evs/<year>/roll<NNN>.xml` |
| Fetched | Every 2 hours at :17 (`house` job). Walks from vote 1 of the current session and fills any gaps. Pauses 1 second between requests and identifies itself with a User-Agent that names this project. |
| Code | `ingest/vote_parsers.py`, `ingest/votes.py` |

- **IDs.** Each vote is stored as `h-<congress>-<session>-<roll>` (e.g. `h-119-1-362`).
- **Validation.** The member rows must add up to the Clerk's published Yea, Nay, Present and
  Not Voting totals. No member may appear twice, and every member must already exist in the
  member table.
- **"Error sanitizing file".** The Clerk's server sometimes returns this text instead of XML.
  The loader retries twice, then treats the vote as not yet published (the end of the list).
  An unrecognized file stops the run cleanly rather than loading bad data.
- **Raw files by session.** Raw files are saved under `<source>/<congress>/<session>/`,
  because roll numbers restart each session. Without this, an early version let one
  session's files overwrite another's, and the House data was reloaded. A changed file
  replaces the stored copy.
- **Schedule.** The Congress and session are worked out from the date (`current`), so the
  schedule needs no edits each January.

## 3. Senate votes

| | |
|---|---|
| Official source | Senate LIS XML, `senate.gov/legislative/LIS/roll_call_votes/...` |
| Source actually used | [Voteview](https://voteview.com) (UCLA), which republishes every roll call |
| Fetched | Daily at 06:40 UTC (`senate-voteview` job), reloading the current Congress |
| Code | `ingest/voteview.py`; the official parser is ready in `ingest/vote_parsers.py` |

- **Why Voteview.**
  - senate.gov refuses downloads from server addresses (HTTP 403, every request), and the
    Congress.gov API has no Senate votes yet.
  - A request for access has been drafted to the Senate webmaster; it isn't sent yet.
  - Voteview lags the official record by days to weeks. When first checked (7 Nov 2026), its
    Senate files were last updated 1 Oct 2026.
- **Same IDs as the official files.** Voteview rows reuse the official session and roll
  number (`s-119-1-77`), so the two never duplicate each other. They are stored with
  `source = 'voteview'`. An official file is never overwritten by Voteview, and an official
  file loaded later replaces the Voteview copy.
- **The President's position is excluded.** Voteview's member file includes the President
  (chamber "President"), whose announced position appears on some Senate roll calls.
  Counting it made 145 votes fail validation, so those rows are dropped.
- **Paired and announced positions.** These aren't in the official tally. They are stored as
  "not voting", and the original wording is kept in `raw_position`. Voteview's published
  totals may or may not include pairs; validation accepts either convention and nothing else.
- **No times.** Voteview has dates but no times of day.

## 3a. Bill titles, policy areas and subjects: Congress.gov

| | |
|---|---|
| Source | [Congress.gov API](https://api.congress.gov/) (Library of Congress), `GET /v3/bill/{congress}/{type}/{number}` and `.../subjects` |
| Fetched | Daily at 07:05 UTC (`bills` job): every bill with a recorded vote that is new, has had a vote since its last check, or was last checked over 30 days ago |
| Code | `ingest/bills.py`; tables `core.bill`, `core.bill_subject` |

- **Why.** Vote titles are official names ("Laken Riley Act") that often lack the words people search
  for. The Library of Congress tags each bill with one policy area and many legislative subjects. Search
  matches votes on those too, and survey questions through the bills of the votes they're linked to.
- **Key.** Needs a free api.data.gov key as `CONGRESS_API_KEY` in `.env` (5,000 requests an hour; two per
  bill; the loader pauses 0.4 s between requests and waits a minute on HTTP 429). A missing or refused key
  stops the run with a clear message; the key never appears in logs or errors.
- **Raw copies.** Each bill's responses are kept as `RAW_DATA_DIR/congress_gov/bills/<congress>/<type><number>.json`.
- **Subjects are paged.** The subjects list is followed through every page (`pagination.next`).
- **Not found.** A bill Congress.gov doesn't know is recorded as checked, so it isn't asked again every day.
- **Nominations and procedural votes** have no bill, so they get no subjects.

## 4. Constituent opinion: Cooperative Election Study (CES)

| | |
|---|---|
| Source | [Cooperative Election Study](https://cces.gov.harvard.edu/) (Harvard / Tufts), on Harvard Dataverse |
| Loaded | CES 2025 (DOI 10.7910/DVN/DFUGJR, about 17,000 respondents, November 2025) and CES 2024 (DOI 10.7910/DVN/X11EP6, about 60,000 respondents, fall 2024 before the election). Files back to 2006 are available. |
| Fetched | `ces inspect / link / load <year>`, run by hand after review |
| Code | `ingest/ces.py`, `opinion.py`; item lists in `config/ces_<year>_items.yaml` |

**What is used.** The data has one row per respondent, with the state (`inputstate`), the
House district (`cdid119` for 2025, `cdid118` for 2024), survey weights, and answers
(1 = Support, 2 = Oppose) to questions about specific actions of Congress.
- Weights: 2025 prefers `commonpostweight` and falls back to `commonweight`. 2024 uses
  `commonweight`, because its 300-series questions were asked in the pre-election wave.
- Districts are as respondents lived in them at the time, so 2024 answers use 118th
  Congress lines.

**Matching a survey question to a vote.**
- The rule is the last decisive floor vote in each chamber that matches: final passage,
  agreeing to the other chamber's version, or confirmation. `ces link` prints every match
  for review.
- A Yea vote is the "support" side, unless marked otherwise (see the Program for Public
  Consultation, section 5).
- **Notes are per chamber.** A note shows only on that chamber's panels. Example: the
  Senate's only vote on the Born-Alive bill was on cloture (whether to proceed), and it
  failed.
- **The Senate's only vote was procedural.** Born-Alive (2025) and the Right to
  Contraception Act (2024) are compared on their cloture votes, with a note saying so.
- **Self-executing rule.** The 2025 Rescissions Act (H.R. 4) cleared the House through a
  rule (H.Res. 590) that agreed to the Senate's version, so no separate concurrence vote
  exists. The House comparison uses the vote on that rule (h-119-1-203).
- **Suspension of the rules.** The 2024 TikTok bill (H.R. 7521) passed under suspension of
  the rules, so its final vote is recorded as "On Motion to Suspend the Rules and Pass".
- **Nominations** have no bill number and are matched by name in the vote description.
- **Left out on purpose.**
  - 2024: access to abortion services (no matching 118th Congress floor vote).
  - 2024: Respect for Marriage Act (passed in the 117th Congress, which isn't loaded).
  - 2024: general policy questions not tied to a vote.
- The TikTok ban became law inside a larger foreign-aid package, so senators aren't compared
  on it.

**Estimates** (`opinion.py`, method `partial-pooling-v1.1`).
- Each district has only about 40 respondents in 2025, too few for raw percentages, so each
  district is pulled toward its state and each state toward the nation. The pull is stronger
  the fewer respondents an area has (partial pooling).
- The effective sample size accounts for unequal weights: n_eff = (Σw)² / Σw².
- How hard to pull is learned from how much areas really differ. A floor assumes areas can
  differ by at least about 5 points (MIN_TAU2 = 0.0025). Without it, ranges came out
  unrealistically narrow.
- Each estimate gets a 90% range, using a multiplier of 1.9 rather than the textbook 1.645.
  In simulated surveys with known answers, 1.645 covered the truth only 84–87% of the time;
  1.9 covered it 91–96% of the time, and about 1% of clear calls were wrong. Pooling cut
  district error by about a third.
- If the range crosses 50%, the area is "too close to call" and isn't scored.
- Senators are compared with their whole state.
- Results: in CES 2025, 59% of district calls were too close to call; in CES 2024, 27%.
- This is simpler than full MRP (multilevel regression with poststratification), which
  would also use district demographics and past election results.

**Exact wording.** "See the exact question" links to the survey guide on Dataverse, which
the loader finds automatically. Readers search it for the item's code (e.g. `CC25_340a`).

## 5. Constituent opinion: Program for Public Consultation (PPC)

| | |
|---|---|
| Source | Program for Public Consultation, University of Maryland: [Common Ground in the Battlegrounds 2026](https://publicconsultation.org/about-the-common-ground-in-the-battlegrounds-survey-series/), results at [vop.org/battlegrounds-aggregate](https://vop.org/battlegrounds-aggregate/) |
| Coverage | 11 competitive states and 28 competitive House districts. Fielded May to August 2026, about 20,000 adults per wave. |
| Fetched | `ppc fetch / link / load 2026`, run by hand. `fetch` writes `logs/ppc_2026_review.txt` for checking before anything is loaded. |
| Code | `ingest/ppc.py`; item list in `config/ppc_2026_items.yaml` |

**Why it was chosen.** It was the second independent source with questions on specific
proposals and results by state and district. America's Political Pulse was considered and
rejected, because it asks about attitudes (partisan feelings, norms, political violence),
not bills, and reports states only.

**Method differences from CES (stated on the panel).**
- Respondents come from online opt-in panels (Cint, Dynata, Prodege), weighted to Census
  figures on age, race, ethnicity, gender, education, income and home ownership.
- Each proposal comes with brief background before people answer.

**No respondent data, so the loader reads the published PDFs.**
- PPC publishes one questionnaire PDF per topic for each state. Each PDF has the exact
  wording, a Favor / Oppose / Ref-DK table for the state and its surveyed districts, and
  each sample's size and confidence interval.
- `fetch` reads each state's page, picks the topic's questionnaire PDF by words in its file
  name (punctuation ignored), downloads it, and extracts the text with pypdf in layout mode.
- The reader was designed from PDFs saved in a browser, then run on the server, which
  downloads every state's PDFs itself.

**Special handling in the PDF reader.** Each case is covered by a test in `tests/test_ppc.py`.
- **Party rows are skipped** (Republicans, Democrats, Independents); only whole-area rows are
  used.
- **Area labels come in several forms:** "Texas (Statewide)", "State of Texas", "Iowa CD2",
  "IA-1", "District 2", "3rd District", "AK At-Large".
- **"(Statewide)" alone on a line.** Some PDFs wrap the state name onto the line above. The
  reader takes the state from the PDF's title ("- STATE OF GEORGIA and NATIONAL -").
- **Header labels without a colon, or with the value on the next line.** Examples: Maine's
  "State of Maine +/- 6.6%", Michigan's "Michigan CD4+/-6.7%", and "Michigan CD8:" with
  "+/-6.6%" on the following line. The header is read as one stream of "place, then number"
  pairs, so line breaks and colons don't matter.
- **Several areas per header line.** Example: "State of Iowa: 2000   Iowa CD1: 500   Iowa
  CD2: 500". Every label-value pair is read.
- **One interval shared by several districts, given as a range.** Example: "Iowa CD1, Iowa
  CD2, Iowa CD3, Iowa CD4: +/-5.5-6.0%". The larger end is used for each, so the range shown
  is never narrower than the survey supports.
- **A short question that relies on the paragraph before it.** "Q10. Members of Congress"
  only makes sense with the lead-in, which asks about prohibiting officials from trading
  stocks in individual companies. The paragraph between one question's table and the next
  question is attached to that next question for matching.
- **Methodology pages are ignored.** Questions are read only up to the "Methodology"
  heading.
- **Unrecognized labels are never guessed.** Any row label that isn't a recognized place,
  and any area without a sample size or interval, is listed under PROBLEMS in the review
  file and left out.
- **At-large states.** A state with one House seat (e.g. Alaska) uses its statewide figure
  for the district too, unless the district is reported separately.

**Estimates** (method `published-results-v1`). There is no pooling, because each area is its
own sample of roughly 400 to 2,000 people.
- support = Favor ÷ (Favor + Oppose), i.e. among people who answered either way.
- range = support ± CI × (1.9 ÷ 1.96) ÷ (Favor + Oppose).
- CI is PPC's published 95% confidence interval for that sample, which already includes
  the effect of weighting: PPC's formula is CI = √((1 + weight variance) / n). It is
  converted to the same 90% level and the same 1.9 multiplier used for CES.
- Effective sample size is stored as 1 / CI².
- "See the exact question" links to that state's questionnaire PDF.

**Items and the votes they're compared with (119th Congress).**

| Item | Vote | Handling |
|---|---|---|
| Renew the expired enhanced ACA subsidies | House: passage, 8 Jan 2026, 230–196 (h-119-2-11). Senate: cloture on S. 3385, 11 Dec 2025, 51–48 (s-119-1-644). | Scored. The Senate note explains that cloture failed short of 60. The House bill's title is "Breaking the Gridlock Act". |
| Continue U.S. military aid to Ukraine | House: Greene amendment to the FY2026 defense policy bill (H.R. 3838) to prohibit Ukraine aid, 10 Sep 2025, 60–372 (h-119-1-255) | Scored, with **Nay on the support side** (`support_side: nay`). The member's mark is drawn at the end their vote supported. |
| Ban members of Congress from trading individual stocks | House: Stop Insider Trading Act, 22 Jul 2026, 232–198 (h-119-2-280) | **Related, not scored.** The bill barred buying new stocks but let members keep existing holdings, and many who voted against it said they wanted a complete ban. |

- **Vote rules double-check the tally.** They can name an exact roll call (`roll_call`) or a
  date (`date`), and `expect: "Yea-Nay"` accepts only a vote with that tally, so a rule can't
  quietly pick up a different vote.
- **Considered and left out.**
  - Medicaid spending: the only vote, H.R. 1 in 2025, bundled many other changes.
  - War powers: the survey asked about a 60-day automatic funding cutoff, which no vote
    addressed.
  - Other proposals had no 119th Congress floor vote.
- **Coverage.** Only senators from surveyed states and representatives from surveyed
  districts get PPC comparisons. Texas was surveyed statewide, with no Texas districts.

## 6. Residents per area: Census Bureau

| | |
|---|---|
| Source | American Community Survey 1-year estimates, table B01003 (total population), via `api.census.gov` (needs a free key, `CENSUS_API_KEY`) |
| Loaded | ACS 2024 (119th Congress district lines) and ACS 2023 (118th Congress lines) |
| Fetched | `population <year>` by hand. The monthly survey watcher loads each new release automatically (usually published in September). |
| Code | `ingest/population.py` |

- **District lines.** Each release reports districts as drawn for one Congress, and names
  it in the district names ("… (119th Congress), Texas"). Rows are filed under that
  Congress, so survey answers are paired with the matching lines.
- **District codes.** 00 (at-large) and 98 (non-voting delegate) are both stored as
  district 0.
- **Territories.** Guam, the Virgin Islands, American Samoa and the Northern Mariana Islands
  aren't in the ACS, so their delegates show no population.
- **Senators** use the latest statewide figure. A state's population doesn't depend on
  district lines.
- **Context shown.** The panel compares each district with the average House district, and
  each state with the smallest and largest states. DC and Puerto Rico are left out of both.
- **Key problems.** A missing or rejected key is reported as a clear error, not a confusing
  redirect.

## 7. Keeping sources current

- **Survey watcher.** The `survey-watch` job runs on the 1st of each month.
  - **CES:** it watches Dataverse for new releases. Cumulative, panel and module releases
    are ignored. A new year is downloaded and inspected, and a draft item list with
    candidate votes is written for review; it is never loaded automatically. A new version
    of a year already loaded is flagged.
  - **Census:** new releases load automatically, because population figures need no
    judgment. The watcher reports them as updates.
  - **Notifications:** the watcher writes `logs/review_needed.txt` and can notify a phone
    (`NOTIFY_URL`).
- **Monitoring.** Each scheduled job can report to healthchecks.io, which emails when a job
  fails or doesn't run on time.
- **Backups.** A nightly database dump is checked for readability and kept for 14 days.

## 8. Candidate sources not yet added

- **State ballot-measure results.** These are actual votes on topics like abortion, minimum
  wage and marijuana. They would mostly be "related" matches, compared with senators
  statewide.
- **AP VoteCast.** Every state, election years only. Reuse terms need checking first.
