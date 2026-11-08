-- Residents of each state and House district, as drawn for a given Congress.
-- district is null for a statewide figure; 0 for an at-large seat or a delegate.
create table core.area_population (
    congress     smallint not null,      -- district lines in effect (read from the Census data itself)
    state        char(2) not null,
    district     smallint,
    population   integer not null,
    source       text not null,          -- e.g. 'ACS 2024 1-year estimate'
    loaded_at    timestamptz not null default now()
);
create unique index area_population_area on core.area_population (congress, state, coalesce(district, -1));
