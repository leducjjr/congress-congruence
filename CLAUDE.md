# Notes for working on this repository

## Always keep the site's change log current

Every change a reader could notice (new data, new pages or features, changed wording of figures,
privacy changes) gets a line in the same commit, or before publishing, in:

- `site/pages/upcoming.md`, under **Recently added**, in a dated entry (newest first), with the page's
  "*Last updated ...*" line set to the same date. This also feeds the updates feed (feed.xml).
- `site/pages/corrections.md`, under **Since launch**, when a published figure or listing was wrong.

Internal-only changes (tests, refactoring, server scripts) don't need an entry.
