-- Where each survey comes from, so readers can check it.
create table core.survey (
    survey        text primary key,          -- e.g. 'CES 2025'
    title         text not null,             -- e.g. 'Cooperative Election Study 2025'
    fielded       text,                      -- when people were interviewed, e.g. 'November 2025'
    respondents   integer,                   -- total people interviewed
    dataset_url   text,                      -- the published data
    guide_url     text,                      -- questionnaire / codebook with exact wording
    about_url     text                       -- the survey's own site
);
