-- Citizens among each area's residents, from the same ACS release as the population:
--   citizens        U.S. citizens of any age (B05001 total minus "Not a U.S. citizen")
--   adult_citizens  U.S. citizens 18 and over, the "citizen voting-age population" (B29001)
-- Null where the Census doesn't publish them (e.g. Puerto Rico uses its own tables).
alter table core.area_population add column citizens integer, add column adult_citizens integer;
