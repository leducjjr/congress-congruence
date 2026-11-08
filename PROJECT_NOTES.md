# Project notes (for picking up in a new chat)

Purpose: a neutral, citizen-facing panel showing how members of the House and Senate vote
compared with what their constituents say in public surveys, now and historically.

## Decisions that stand
- Both chambers from the start; Python; PostgreSQL schema `core`; Bioguide ID is the member key.
- Dev site: https://congress-dev.monkeyinfinitum.com (Bluehost VPS, user `john`, repo cloned at
  ~/congress-congruence, read-only deploy key). Dev and prod share a server for now.
- **No user data is collected or stored.** Addresses only for lookup; personal choices stay in the browser.
- Several independent survey sources, **shown side by side, never blended** (per-source score lines).
- Only votes on the same proposal a survey asked about are scored; close-but-different bills are
  `match: related`, shown and never counted. Votes where Nay supports a proposal use `support_side: nay`.
- Senate votes come from Voteview (senate.gov returns 403 to the server); official files win if loaded later.
- Visual rule: the picture should tell the story before the text (vote shapes, not party colors).

Full details of every source and its special handling: `docs/DATA_SOURCES.md`
(keep it updated in the same commit as any change to how a source is handled).

## Sources loaded
- Votes: House Clerk (every 2 hours), Senate via Voteview (daily), members from congress-legislators.
- Opinion: CES 2024 and 2025 (respondent data, partial pooling, `opinion.py`);
  PPC 2026 Battlegrounds (published per-area results from PDFs, `ingest/ppc.py`).
- Population: Census ACS 1-year (2023 = 118th lines, 2024 = 119th lines).
- Watcher (monthly): new CES releases are drafted for review; new Census releases load automatically.

## Next candidates (agreed order)
1. State ballot-measure results (actual votes; good for senators; topic matches would be "related").
2. AP VoteCast (check reuse terms first).
Also open: make the repo public + send the Senate access email; healthchecks.io and NOTIFY_URL;
an "About this data" page; separate production server; earlier years; stock-trading overlay.

## Working conventions
- Tests: `pytest` (database tests need TEST_DATABASE_URL). Commit only when all tests pass.
- Give John full server commands (with `python -m ...`); his venv: `source .venv/bin/activate`.
