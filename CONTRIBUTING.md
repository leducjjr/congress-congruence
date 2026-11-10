# Contributing

Thank you for helping make this site accurate. Anyone can read this code and suggest changes;
only the project's maintainer changes it, after reviewing each suggestion.

## Report a data error

If a vote, a member's record, a survey match or an estimate looks wrong, please
[open a data error report](../../issues/new?template=data-error.yml). Say which page, which member
or vote, what you expected, and the source that shows it (an official roll call, a survey's
published data). We check every report against the original source. Fixes that change a figure
on the site are listed in the site's [corrections log](https://uscongressvsvoters.org/corrections.html).

You can also email corrections (at) uscongressvsvoters.org or use the site's contact form, if
you'd rather not use GitHub.

## Suggest a feature or a new source

[Open a suggestion](../../issues/new?template=suggestion.yml). New survey sources are welcome if
they publish their data, allow results to be republished, and ask about specific proposals that
Congress voted on.

## Proposing code changes

Pull requests are welcome. Please open an issue first for anything larger than a small fix, so
we can agree on the approach. Every pull request is reviewed before it's merged; nothing changes
on the site until then.

- Run the tests: `pytest` (database tests need `TEST_DATABASE_URL`; see `deploy/README.md`).
- Keep to the site's rules, which aren't negotiable:
  - **Neutral.** The same methods, wording and design for every member and party. The site
    never mentions or links to a political party, campaign or advocacy group.
  - **Survey sources are never blended.** Each source is shown on its own.
  - **Like for like.** Only votes on the same proposal a survey asked about are counted;
    related votes are shown and labeled, never counted.
  - **Visible data, not verdicts.** Counts and estimates people can check against the sources,
    with no rankings or grades of our own.
  - **No data about visitors** is collected or stored.
- Document any new source or special case in `docs/DATA_SOURCES.md`.

## Security problems

Please don't open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[GNU Affero General Public License v3.0](LICENSE), like the rest of the project.
