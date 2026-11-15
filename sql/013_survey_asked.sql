-- Who each source's figures come from, shown beside every comparison so readers can see the difference:
-- 'adults' (everyone 18+ who answered), 'registered_voters', 'voters' (votes actually cast, e.g. a ballot
-- measure's certified result) or 'residents' (everyone who answered, as some state polls report).
alter table core.survey add column asked text
    check (asked in ('adults', 'registered_voters', 'voters', 'residents'));

update core.survey set asked = case
    when kind = 'ballot' then 'voters'
    when organization = 'Texas Politics Project' then 'registered_voters'
    else 'adults' end;

alter table core.survey alter column asked set not null;
