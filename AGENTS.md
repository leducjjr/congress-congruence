# Start here (for developers and AI coding agents)

This is the code behind [US Congress vs Voters](https://uscongressvsvoters.org). The repository is
meant to be self-explanatory: everything needed to understand, run, change and deploy the site is in
it. Read in this order:

1. **README.md**: what the site does, the code layout, and how to run it.
2. **docs/DECISIONS.md**: decisions already made and why. Several are the site's founding rules;
   don't reverse one without the maintainer's agreement.
3. **PROJECT_NOTES.md**: current status, open items and the agreed next steps.
4. **docs/DATA_SOURCES.md**: every data source and every special case in handling it.
5. **docs/SITE_PLAN.md**: the site's structure and pages.
6. **deploy/README.md**: how the server is set up, updated and backed up.
7. **docs/HANDOVER.md**: accounts and resources that change hands with the project.
8. **CONTRIBUTING.md** and **SECURITY.md**: how outside people suggest changes and report problems.

## The site's rules (not negotiable)

- **Neutral.** The same methods, wording and design for every member and party. The site never
  mentions or links to a political party, campaign or advocacy group.
- **Survey sources are never blended.** Each source is shown on its own.
- **Like for like.** Only votes on the same proposal a survey asked about are counted; related votes
  are shown and labeled, never counted.
- **Visible data, not verdicts.** Counts and estimates people can check against the sources. No
  rankings, grades, or aggregate or trend analysis of our own.
- **No data about visitors.** No accounts, cookies or analytics; pages contact no outside company
  (the typeface is self-hosted).
- **Every figure links back to its source.**

## Rules for changing the code

- **Keep the site's change log current.** Every change a reader could notice (new data, new pages or
  features, changed wording of figures, privacy changes) gets a line in the same commit, or before
  publishing, in:
  - `site/pages/whats-new.md` (the What's new page), under **Recently added**, in a dated entry
    (newest first), with the page's "*Last updated ...*" line set to the same date. This also feeds
    the updates feed (feed.xml). `upcoming.md` is only for what's planned.
  - `site/pages/corrections.md`, under **Since launch**, when a published figure or listing was wrong.
  Internal-only changes (tests, refactoring, server scripts) don't need an entry.
- Any change to how a data source is handled updates `docs/DATA_SOURCES.md` in the same commit.
- New decisions go in `docs/DECISIONS.md`; status changes in `PROJECT_NOTES.md`; new accounts or
  services in `docs/HANDOVER.md`.
- Database changes go in a new numbered file in `sql/`; never edit one that has been applied.
- Run `pytest` (database tests need `TEST_DATABASE_URL`) and commit only when all tests pass.
- Give the person running the server complete, copy-pasteable commands (`python -m ...`, with the
  project's venv active: `source .venv/bin/activate`).
- This repository is public. Never commit secrets, private email addresses or anything from the
  server's `.env`.
