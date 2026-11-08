# Project notes (for picking up in a new chat)

Purpose: a neutral, citizen-facing panel showing how members of the House and Senate vote
compared with what their constituents say in public surveys, now and historically.

## Decisions that stand
- Both chambers from the start; Python; PostgreSQL schema `core`; Bioguide ID is the member key.
- Primary domain: **uscongressvsvoters.org** (a non-profit exercise, so .org). Sister domain
  uscongressvsvoters.com and uscongressvsvoters.online (all registered Nov 2026 at Bluehost) should
  forward to .org at launch.
  Dev site: https://dev.uscongressvsvoters.org (dev. on .com and .online, and
  congress-dev.monkeyinfinitum.com, also answer; same nginx site and certificate). The bare
  domains and www are kept for the public launch.
- Server: Bluehost VPS, user `john`, repo cloned at
  ~/congress-congruence, read-only deploy key. Dev and prod share a server for now.
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

## Email
Bluehost Professional Email Plus (Titan) on uscongressvsvoters.org: `contact@` (public; aliases
corrections@, press@, privacy@, security@) and `admin@` (never published; login/recovery address for
Bluehost, GitHub, api.data.gov, Census, healthchecks). Catch-all: any other @.org address goes to
contact@. `feedback@` is send-only: the server uses it to email feedback-form messages to contact@
(its password is in the server's .env; nothing from the form is stored). .com/.online mail should forward to .org, and
those two domains get SPF `v=spf1 -all` + DMARC `p=reject`.
.org DMARC (`_dmarc`) set 2026-11-08 to `p=none` with reports to admin@; switch to `p=quarantine` once
a week or two of reports show only Titan sending. Addresses appear on the Contact page via
`data-email` (no full address in the page source). `site/static/.well-known/security.txt` has an
**Expires** date (2027-11-01): renew it yearly.

## Site plan
Source code is linked from every page (footer, About); the URL is in `site/site.yaml`. The repo
must be public for visitors to open it.
Pages live in `site/pages/` (Markdown for reference pages), built by `scripts/build_site.py`.
See `docs/SITE_PLAN.md`: header, footer and reference pages, leading with the vote-vs-survey comparison.

## Next candidates (agreed order)
1. State ballot-measure results (actual votes; good for senators; topic matches would be "related").
2. AP VoteCast (check reuse terms first).
Also open: make the repo public + send the Senate access email; healthchecks.io and NOTIFY_URL;
an "About this data" page; separate production server; earlier years; stock-trading overlay.

## Working conventions
- Tests: `pytest` (database tests need TEST_DATABASE_URL). Commit only when all tests pass.
- Give John full server commands (with `python -m ...`); his venv: `source .venv/bin/activate`.
