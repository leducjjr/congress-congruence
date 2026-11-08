# Site plan: header, pages and reference material

Status: steps 1–2 under way (Nov 2026): the shared header and footer, Find your members,
Sources, Methods, Glossary, About, Contact (placeholder) and Privacy are built, and search
finds members (name, state, seat), survey questions and votes (search.html). Next: subject tags
from Congress.gov for plain-language search, then Surveyed votes.

Originally a proposal (Nov 2026). Today the site is one page (pick a state and a member, see the
panel). This plan turns it into a small site with a header, a footer, and reference pages, ready for
the public launch at uscongressvsvoters.com.

## What sets this site apart

Several sites already track roll-call votes (e.g. congressvotetracker.org: every House and
Senate vote, member scorecards, party loyalty, attendance, state pages, glossary, FAQ). This site's
reason to exist is the **overlap between how members vote and what their constituents say in public
surveys**. Every page should lead with that, and the vote-only features should support it rather
than compete with those sites.

Four commitments to state plainly and keep visible:

1. **Votes compared with constituents**, by state and district, on the bills surveys asked about.
2. **Several independent survey sources, side by side**, never blended into one score.
3. **Uncertainty shown**: ranges, "too close to call", "related vote, not counted".
4. **No tracking and no stored personal data.**

## Header (every page)

```
[US Congress vs Voters]   Find your members   Surveyed votes   All votes   Data & methods   About   [search]
```

- **Find your members**: pick a state, or enter an address (used once for the lookup, never stored),
  then see the senators and representative.
- **Search**: by member name or bill. Runs on the page; the API logs nothing that identifies a visitor.
- **Mobile**: the menu collapses to a "Menu" button. The search box is reached from the menu.

## Footer (every page)

- **Coverage**: "Voting records cover the 119th Congress, starting January 3, 2025. House votes
  through …; Senate votes through …". This line is already live on the dev page.
- **Primary sources**: House Clerk, Senate.gov, Congress.gov, Voteview, Cooperative Election Study,
  Program for Public Consultation, Census Bureau.
- **Independence**: "An independent civic project. Not affiliated with the U.S. government, Congress,
  any party, campaign, or survey organization."
- **Links**: Data & methods, Glossary, FAQ, Corrections, Privacy, Source code (once public).

## Pages

| Page | What it shows | Notes |
| --- | --- | --- |
| **Home** | One-line purpose; find-your-members box; coverage line; 2–3 examples of the comparison (e.g. a member who voted against a clear state majority, with the bar); "How it works" in three short steps | Lead with the comparison, not raw vote counts |
| **Member** (`/member/<id>`) | Today's panel | Clean shareable address instead of `#TX/C001098`; page title and preview text for sharing |
| **State** (`/state/<XX>`) | The delegation, each with one score line per survey source; which areas each source covered | Map optional; a list works on every screen |
| **Surveyed votes** (`/surveyed`) | Every survey question linked to a vote: wording, source, vote result, and how each chamber's members lined up with their own area | **The unique view.** Per question: "X of Y members voted with a clear majority where they live" |
| **Surveyed vote detail** | One question: national support, support by state and district (where surveyed), every member's vote placed against their area's band | A dot plot or table; same visual rules as the panel |
| **All votes** (`/votes`) | Every roll call, newest first, filter by chamber and date; "Surveyed" tag where a survey asked about it | Support role; link to official records |
| **Data & methods** | Public version of `docs/DATA_SOURCES.md`: each source, how it's fetched, special cases, the estimate method, ranges, related votes, update schedule | Sections linkable from the panel's "How this works" |
| **Survey sources** | One card per survey organization: who runs it, method, sample, years, what we use, links | Answers "why trust these surveys?" |
| **Glossary** | Roll call, cloture, suspension of the rules, motion to recommit, self-executing rule, margin of error, too close to call, related vote, at-large, delegate | Short entries; linked from wherever a term first appears |
| **FAQ** | Why not every vote? Why do sources differ? Why "too close to call"? Why is the Senate a few weeks behind? Is my address stored? | Plain language |
| **About** | Who runs it, why, independence, funding (none), contact | Contact by a project email at the domain, not a personal one |
| **Corrections** | How to report an error; a dated log of corrections | Credibility for a neutral site |
| **Privacy** | No accounts, no cookies, no analytics that identify visitors; how address lookup works | Short and specific |

## Building it

- **Same stack.** Static HTML pages served by nginx, using the same API and web component. No framework
  is needed: a shared header and footer are inserted by one small script, or generated when publishing.
- **Shareable addresses.** nginx serves `/member/<id>` and `/state/<XX>` from the same page and the
  page reads the address. Each page sets its own title and description so shared links preview well.
- **Content pages** (Data & methods, Glossary, FAQ, About, Privacy, Corrections) are written in
  Markdown in the repo and converted to HTML when publishing, so editing them needs no code.
- **Accessibility**: skip link, keyboard-usable menu, real headings, text alternatives for every chart,
  light and dark themes (already in the panel).

## Suggested order

1. Header, footer and the shared page frame; move the current page under it as **Find your members**
   and **Member**.
2. **Data & methods**, **Survey sources**, **About**, **Privacy**, **Glossary** (mostly writing; the
   material exists in `docs/`).
3. **Surveyed votes** list and detail (needs two new API endpoints).
4. **State** pages and **Home** examples.
5. **All votes**, **FAQ**, **Corrections**, search.
6. Before launch: address lookup, production copy without the dev password, separate production
   server, project contact email.
