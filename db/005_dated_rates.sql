-- RightPrice database, stage 5 of the rebuild (27 Nov 2026): dated yarn rates.
--
-- A yarn's rate for one month, so a purchase order is costed on the yarn rates of its order month (GP's decision,
-- 27 Nov 2026). The rate master's own Yarn_Rates stay what they are: the rates "of today", used by quotes and Cost a
-- fabric, and by any month that has no dated rate (the costing then says so for that yarn).
-- The rule for "the rate of a month" is in rules/dated.py (RULE) and on the Yarn prices page.
-- Same words as 001: @ID@ @REAL@ are filled in by store.py for PostgreSQL or SQLite.

CREATE TABLE yarn_rate_dated (
    id           @ID@,
    yarn_key     TEXT NOT NULL,               -- a Yarn key of the rate master's Yarn_Rates ('Cotton 40S')
    valid_from   TEXT NOT NULL,               -- the first day of the month the rate is for (2026-09-01); it holds for that month only
    rate         @REAL@ NOT NULL,             -- rupees per kilo, the month's figure
    low          @REAL@,                      -- the lowest and highest price it was worked out from (a range, or several prices)
    high         @REAL@,
    entries      INTEGER NOT NULL DEFAULT 1,  -- how many prices the month's figure is the average of
    basis        TEXT NOT NULL,               -- shown beside the rate in a costing: where it is from
    source       TEXT NOT NULL,               -- typed | brought in | market history: which way it came in
    detail       TEXT NOT NULL DEFAULT '{}',  -- JSON: the prices and dates behind it, the file, the note typed
    entered_by   TEXT NOT NULL DEFAULT '',    -- the signed-in person; 'market history' rows name who loaded them
    entered_at   TEXT NOT NULL,
    removed_at   TEXT,                        -- a removed or replaced rate is kept, marked
    removed_by   TEXT,
    removed_why  TEXT                         -- removed | replaced
);
CREATE INDEX yarn_rate_dated_key ON yarn_rate_dated (yarn_key, valid_from);

INSERT INTO store_state (kind, version) VALUES ('dated', 0);
