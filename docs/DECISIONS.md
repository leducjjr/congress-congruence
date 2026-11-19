# Decisions

Decisions made so far, with the reason for each. To change one, agree it with the maintainer first,
then record the change here (don't delete the original entry). Details of individual data sources are
in `DATA_SOURCES.md`; current status is in `../PROJECT_NOTES.md`.

## Purpose and founding rules

1. **Purpose:** let voters easily track, in near real time, how their members of Congress vote compared
   with what surveys say the people they represent want, now and historically.
2. **Credibility comes first.** If readers think the analysis is biased or flawed, the site is worthless.
   Hence the rules in AGENTS.md: neutral treatment, no party mentions or links, sources never blended,
   like-for-like matching, visible data rather than verdicts, and every figure linked to its source.
3. **Members are judged on their own votes, not their party.** The design shows vote shapes rather than
   party colors, and there is a party-blind view.
4. **No aggregate or trend analysis**, on the site or internally: only tools that help readers view the
   collected data themselves.
5. **No data about visitors.** No accounts, cookies or analytics; addresses are used only for lookup;
   personal choices stay in the browser; the typeface is self-hosted so pages contact no outside
   company. Feedback-form messages are emailed and never stored.
6. **Several independent survey sources**, shown side by side, so readers aren't relying on one or two.

## Project

7. **Volunteer, non-profit exercise:** no funding, no advertising, no donations. Hence the .org as the
   primary domain; .com and .online redirect to it.
8. **Open source under the AGPL v3**, with the source linked from every page, for full transparency.
   The repository is public but read-only for others: only the maintainer changes the code; anyone may
   suggest changes through issues and pull requests (CONTRIBUTING.md).
9. **The maintainer is credited by name** on the site (About, Press, How it was built) as owner and
   maintainer, which lends the project credibility. A new maintainer updates those pages.
10. **Built by the maintainer with an AI model writing much of the code** (described openly on the How
    it was built page). The maintainer makes every decision.
11. **Outreach to data sources states what has been done and invites corrections**, rather than asking
    open questions, since people more readily correct an action than answer a question.

## Technical

12. **Both chambers from the start**, rather than adding the Senate later.
13. **Python, PostgreSQL (schema `core`), FastAPI read-only API, static site.** Bioguide ID is the
    member key.
14. **Senate votes come from Voteview** while senate.gov refuses downloads from the server; official
    files take precedence if loaded later.
15. **Dev and prod share one Bluehost VPS for now**, distinguished by name (dev.uscongressvsvoters.org
    behind a password); a separate production server is under consideration.
16. **Historical votes:** 1973 onward load into the main site; 1789-1972 may get a separate historical
    section.
17. **AP VoteCast is on hold:** permission was requested (Nov 2026) because its terms bar AI tools from
    processing the data.
18. **Members' stock trading** overlaid on votes is a possible addition, not core.

## 19 November 2026

19. **The setup is summarized in `docs/system_info.xlsx`**, by ID and status (see its About tab), in
    the same format as the maintainer's other projects, so anyone picking up the project sees every
    decided and open item in one place.
