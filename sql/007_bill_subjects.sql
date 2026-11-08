-- Official subject tags for bills that have recorded votes, from the Congress.gov API, so a search
-- for "immigration" also finds a bill titled "Laken Riley Act". core.bill (title, policy area)
-- already exists; this adds its subjects and when they were last checked.

alter table core.bill add column checked_at timestamptz;   -- when Congress.gov was last asked

create table core.bill_subject (
    congress     smallint not null,
    bill_type    text not null,
    bill_number  integer not null,
    subject      text not null,       -- a Library of Congress legislative subject, e.g. 'Immigration status and procedures'
    primary key (congress, bill_type, bill_number, subject),
    foreign key (congress, bill_type, bill_number) references core.bill on delete cascade
);
