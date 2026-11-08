-- State ballot measures as a source shown beside the surveys (never blended).
-- kind: 'survey' (people asked a question) or 'ballot' (certified votes on a state ballot measure).
alter table core.survey add column kind text not null default 'survey' check (kind in ('survey', 'ballot'));

-- What a figure is, where that differs by area: for ballot measures, each state's own measure name
-- (e.g. 'Idaho HJR 5 (2024)').
alter table core.opinion_estimate add column area_note text;
