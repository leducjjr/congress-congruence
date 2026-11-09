-- Census profile of each House district as drawn for a given Congress (American Community Survey).
-- Used to sharpen district opinion estimates: each district's survey answers are pulled toward
-- what its state's estimate plus this profile predict, rather than toward the state alone.
create table core.district_profile (
    congress      smallint not null,     -- district lines (read from the Census data itself)
    state         char(2) not null,
    district      smallint not null,     -- 0 = at-large
    acs_year      smallint not null,
    pct_ba        real,                  -- share of adults 25+ with a bachelor's degree or more
    median_income real,                  -- median household income, dollars of that year
    pct_white_nh  real,                  -- non-Hispanic white share of residents
    pct_black     real,                  -- non-Hispanic Black share
    pct_hispanic  real,                  -- Hispanic or Latino share
    median_age    real,
    source        text not null,
    loaded_at     timestamptz not null default now(),
    primary key (congress, state, district)
);
