-- RightPrice database, stage 2 of the rebuild (27 Nov 2026): what was bought, with dates; one record per mill, per
-- fabric code and per Fab group (the same construction in any colour, across mills).
--
-- Applied once, at start, by store.py, like 001_files_moved_in.sql (whose head explains the words @ID@, @BLOB@, @REAL@).
-- Times and dates are kept as text in ISO form (2026-11-27T15:02:11, 2026-11-27), as in 001.
--
-- Where these differ from the draft in db/schema.sql, and why:
--   - ids, money and metres use the words of 001 (a number given by the database, @REAL@), so one text serves PostgreSQL
--     and SQLite; JSON is kept as text, as in 001.
--   - upload.uploaded_by is the signed-in person's name as text: the table of people (app_user) comes with stage 3.
--   - upload keeps the file itself (the background job reads it from here), when it started and last showed it was alive,
--     and the counts of new, changed, repeated, removed and left-out lines; uploads of other kinds can use it later.
--   - purchase_line keeps the supplier as written, and is marked (not deleted) when a later file shows it deleted in SAP.
--   - fab_group says who merged it and when; fabric says why it is not grouped, and keeps the signature it was grouped by
--     (so a corrected PLM specification, or a change in how the fields are tidied, regroups it at the next upload);
--     fabric_regroup records each move, for the group pages.
--   - each order line keeps the evidence of the newest file that covered it (the second review, 27 Nov 2026): when that
--     file can have been taken, from its latest document date (or a later report date it carries) to when it was saved
--     (or uploaded, when it has no saved date that can be used). Where that cannot tell which of two files is newer, the
--     one saved later wins when both have a saved date (GP, 28 Nov 2026): the line keeps the file's state_from, state_to
--     and state_saved. A line a file shows deleted is kept as a mark even before any file gave its figures, so an older
--     file never brings it back; a line simply not in a newer file is never taken as cancelled (GP, 28 Nov 2026). Where
--     nothing can tell (the same saved moment, or a file without a saved date that can be used) and a file disagrees,
--     the figures kept stand and the disagreement is listed for a person to settle (line_disagreement).
--     ZLOI lines are kept, and left out of every calculation (GP's decision).

-- the mills: one record each, however the name is written (rules/mills.py, mill_key)
CREATE TABLE mill (
    id        @ID@,
    key       TEXT NOT NULL UNIQUE,         -- what mill_key() gives: 'arvind'
    name      TEXT NOT NULL,                -- the spelling shown: the fullest one received, without the vendor number
    added_at  TEXT NOT NULL
);
CREATE TABLE mill_alias (
    spelling  TEXT PRIMARY KEY,             -- every way the mill has been written, as received ('1200094    ARVIND LTD')
    mill_id   BIGINT NOT NULL REFERENCES mill(id),
    added_at  TEXT NOT NULL
);

-- Fab groups: what makes two fabric codes one cloth (any colour, any mill)
CREATE TABLE fab_group (
    id           @ID@,
    code         TEXT NOT NULL UNIQUE,      -- Fab-0001, Fab-0002 ... in order of first appearance; never changed, never reused
    name         TEXT NOT NULL,             -- '100% Cotton · Yarn Dyed · Twill-2/1 · 40s x 40s · 136 x 90 · 57.1 in · Normal Soft'
    content      TEXT NOT NULL,             -- the nine fields, tidied: what the group is
    route        TEXT NOT NULL,
    weave        TEXT NOT NULL,
    warp         TEXT NOT NULL,
    weft         TEXT NOT NULL,
    epi          @REAL@ NOT NULL,
    ppi          @REAL@ NOT NULL,
    width_in     @REAL@ NOT NULL,           -- the lowest width of its codes; widths within half an inch are one group
    width_to     @REAL@,                    -- the highest (the same when its codes are of one width)
    finish       TEXT NOT NULL,
    signature    TEXT NOT NULL UNIQUE,      -- the nine joined: two fabrics with the same signature are one group
    merged_into  BIGINT REFERENCES fab_group(id),   -- an admin merged this group into another: its code stays, never handed out again
    merged_at    TEXT,
    merged_by    TEXT,
    created_at   TEXT NOT NULL,
    upload_id    BIGINT                     -- the upload it first appeared in
);

-- the fabric codes: one record per company material code
CREATE TABLE fabric (
    id            @ID@,
    code          TEXT NOT NULL UNIQUE,     -- the company's fabric (material) code
    description   TEXT NOT NULL DEFAULT '', -- the purchase order's short text, the latest received
    fab_group_id  BIGINT REFERENCES fab_group(id),  -- empty: not grouped (why in not_grouped), never guessed
    not_grouped   TEXT,                     -- why it has no group: the PLM specification is missing or incomplete
    signature     TEXT,                     -- the signature it was grouped by (empty when not grouped)
    spec          TEXT,                     -- JSON: its row of the PLM specification (data/plm_specs_for_po.csv), as received
    spec_sha      TEXT,                     -- SHA-256 of that row, to see when the PLM list changes it
    choices       TEXT,                     -- JSON: the costing choices worked out from it as pilot.py does; empty: not costed
    problems      TEXT NOT NULL DEFAULT '[]',   -- JSON: why it is not costed
    -- what the choices were worked out on, so stale ones are worked out again (a restart part-way through an upload, the
    -- rate master's lists changed): empty until they are first worked out
    choices_lists  TEXT,                    -- a fingerprint of the rate master's lists (rules/purchases.py lists_fingerprint)
    choices_metres @REAL@,                  -- its metres then (they set the quantity band)
    choices_spec   TEXT,                    -- the spec_sha then
    updated_at    TEXT NOT NULL
);
CREATE INDEX fabric_group ON fabric (fab_group_id);

-- a fabric code moved from one Fab group to another (or out of any): its specification was corrected or completed, or
-- the way the fields are tidied changed. The group codes themselves never change.
CREATE TABLE fabric_regroup (
    id             @ID@,
    fabric_id      BIGINT NOT NULL REFERENCES fabric(id),
    from_group_id  BIGINT REFERENCES fab_group(id),
    to_group_id    BIGINT REFERENCES fab_group(id),
    why            TEXT NOT NULL,
    at             TEXT NOT NULL,
    upload_id      BIGINT
);
CREATE INDEX fabric_regroup_from ON fabric_regroup (from_group_id);
CREATE INDEX fabric_regroup_to ON fabric_regroup (to_group_id);

-- what happened to a Fab group since it was made (its code always stays the same): renamed when its codes'
-- specification was corrected or codes of other widths joined; merged into another by an admin; that merge undone
CREATE TABLE fab_group_change (
    id         @ID@,
    group_id   BIGINT NOT NULL REFERENCES fab_group(id),
    kind       TEXT NOT NULL,               -- renamed | merged | unmerged
    old_name   TEXT NOT NULL,
    new_name   TEXT NOT NULL,
    why        TEXT NOT NULL,
    at         TEXT NOT NULL,
    by_whom    TEXT NOT NULL DEFAULT '',    -- the person (or "AI assistant") who merged or undid a merge
    upload_id  BIGINT
);
CREATE INDEX fab_group_change_group ON fab_group_change (group_id);

-- everything that comes in as a file, read in the background
CREATE TABLE upload (
    id            @ID@,
    kind          TEXT NOT NULL,            -- purchase_orders
    filename      TEXT NOT NULL,
    uploaded_by   TEXT NOT NULL DEFAULT '', -- the signed-in person
    uploaded_at   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',   -- queued | working | done | failed
    step          TEXT NOT NULL DEFAULT '', -- what the job is doing now, in words
    started_at    TEXT,
    finished_at   TEXT,
    alive_at      TEXT,                     -- the job's last sign of life (a job stopped by a restart is told apart by it)
    runner        TEXT,                     -- the machine and process reading it
    file_date     TEXT,                     -- what the file covers: its latest document date (or the report date it carries)
    file_date_from TEXT,                    -- in words: what the file covers and when it was saved
    covers_from   TEXT,                     -- the earliest it can have been taken (UTC): its report date, else its latest
                                            -- document date (a day in India), from the day's start
    covers_to     TEXT,                     -- the latest: when the workbook was saved, else when it was uploaded
    covers_saved  TEXT,                     -- its saved date when it can be used (not after the upload), else empty: where
                                            -- what two files cover cannot tell, the later of two of these wins
    report_date   TEXT,                     -- a report or export date the file carries in a column of its own, if any
    report_used   TEXT,                     -- that date, when it counts (its latest order <= it <= its saved date or upload)
    saved_at      TEXT,                     -- when the workbook says it was saved, as read (UTC); not used when after the
                                            -- upload or before its latest order (file_date_from says so)
    error         TEXT,                     -- why it failed
    rows_total    BIGINT,                   -- rows in the file
    rows_loaded   BIGINT,                   -- order lines kept (new + changed + already in)
    rows_new      BIGINT,
    rows_changed  BIGINT,                   -- in an earlier file with other figures: the newer figures are kept
    rows_same     BIGINT,                   -- in an earlier file with the same figures: one line, not two
    rows_removed  BIGINT,                   -- in an earlier file; this newer one shows it deleted, blocked, not bulk, not rupees ...: marked removed
    rows_dropped  BIGINT,                   -- not used: a line simply not in a newer file is never taken as dropped (GP, 28 Nov 2026)
    rows_older    BIGINT,                   -- a newer (or later-saved) file already gave these lines: this file's figures are not used for them
    rows_disagree BIGINT,                   -- this file and the history disagree, and which is newer cannot be told even by the saved dates: kept as they were, listed
    rows_outliers BIGINT,                   -- ZLOI lines among those kept: left out of every calculation, shown apart
    rows_skipped  BIGINT,                   -- left out (why in skipped)
    fabrics_new   BIGINT,
    groups_new    BIGINT,
    mills_new     BIGINT,
    skipped       TEXT NOT NULL DEFAULT '[]',   -- JSON: each row left out, with why
    summary       TEXT NOT NULL DEFAULT '{}',   -- JSON: the rows left out counted by reason, dates covered, fabrics not grouped
    file          @BLOB@,                   -- the file as uploaded
    sha256        TEXT
);

-- what was bought: one row per purchase-order line
CREATE TABLE purchase_line (
    id                 @ID@,
    upload_id          BIGINT NOT NULL REFERENCES upload(id),   -- the upload its figures came from (or that first marked it)
    po_number          TEXT NOT NULL,       -- Purchasing Document
    item               TEXT NOT NULL,       -- Item
    -- its figures; empty on a mark: a line a file showed deleted or left out before any file gave its figures
    doc_date           TEXT,                -- Document Date
    doc_type           TEXT,                -- Purchasing Doc. Type (BO, BF: bulk; ZLOI: kept, but an outlier left out of every calculation)
    fabric_id          BIGINT REFERENCES fabric(id),
    mill_id            BIGINT REFERENCES mill(id),
    supplier           TEXT,                -- Name of Supplier, as written
    qty_m              @REAL@,              -- Order Quantity, metres
    price              @REAL@,              -- Net Price, rupees per metre (ex-mill)
    removed_upload_id  BIGINT REFERENCES upload(id),   -- a newer file removed it (deleted in SAP, no longer bulk ...): kept, not counted
    removed_why        TEXT,
    -- a price more than ten times, or under a tenth of, its code's other purchases (else its Fab group's): held apart as
    -- "price to check in SAP", counted nowhere (like ZLOI) until an admin counts it (the build lead's guard, 28 Nov 2026)
    price_check        TEXT,                -- why it is held
    price_ok_by        TEXT,                -- the admin who counted it after all
    price_ok_at        TEXT,
    state_upload_id    BIGINT NOT NULL,     -- the newest file that covered it (set its figures, or removed or marked it),
    state_from         TEXT NOT NULL,       -- when that file can have been taken: from (upload.covers_from)
    state_to           TEXT,                -- to (upload.covers_to: its saved date, or its upload)
    state_saved        TEXT,                -- and upload.covers_saved: where from and to cannot tell two files apart, the one
                                            -- saved later wins, when both have one (GP, 28 Nov 2026)
    UNIQUE (po_number, item)                -- the same order line uploaded twice is one line
);
CREATE INDEX purchase_line_fabric ON purchase_line (fabric_id, doc_date);
CREATE INDEX purchase_line_mill ON purchase_line (mill_id);

-- a file and the history disagree on a line and which is newer cannot be told, from what they cover nor from when they
-- were saved (the same moment, or either without a saved date that can be used): the history's figures were kept
CREATE TABLE line_disagreement (
    id          @ID@,
    upload_id   BIGINT NOT NULL REFERENCES upload(id),
    po_number   TEXT NOT NULL,
    item        TEXT NOT NULL,
    kept        TEXT NOT NULL,              -- JSON: what the history holds (its figures, or why it is removed) and from which upload
    file        TEXT NOT NULL,              -- JSON: what this file says (its figures, or why it leaves the line out)
    settled_at  TEXT,                       -- a person settled it: when, who,
    settled_by  TEXT,
    settled_as  TEXT                        -- and how: file (this file's figures taken) | kept (the history's kept)
);
CREATE INDEX line_disagreement_upload ON line_disagreement (upload_id);

INSERT INTO store_state (kind, version) VALUES ('purchases', 0);
