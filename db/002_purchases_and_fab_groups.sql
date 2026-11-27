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
--   - fab_group says who merged it and when; fabric says why it is not grouped.

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
    width_in     @REAL@ NOT NULL,
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
    spec          TEXT,                     -- JSON: its row of the PLM specification (data/plm_specs_for_po.csv), as received
    choices       TEXT,                     -- JSON: the costing choices worked out from it as pilot.py does; empty: not costed
    problems      TEXT NOT NULL DEFAULT '[]',   -- JSON: why it is not costed
    updated_at    TEXT NOT NULL
);
CREATE INDEX fabric_group ON fabric (fab_group_id);

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
    error         TEXT,                     -- why it failed
    rows_total    BIGINT,                   -- rows in the file
    rows_loaded   BIGINT,                   -- order lines kept (new + changed + already in)
    rows_new      BIGINT,
    rows_changed  BIGINT,                   -- in an earlier file with other figures: the newer figures are kept
    rows_same     BIGINT,                   -- in an earlier file with the same figures: one line, not two
    rows_removed  BIGINT,                   -- in an earlier file, shown deleted in SAP in this one: marked removed
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
    upload_id          BIGINT NOT NULL REFERENCES upload(id),   -- the upload its figures came from (the latest that had it)
    po_number          TEXT NOT NULL,       -- Purchasing Document
    item               TEXT NOT NULL,       -- Item
    doc_date           TEXT NOT NULL,       -- Document Date
    doc_type           TEXT NOT NULL,       -- Purchasing Doc. Type (BO, ZLOI, BF: bulk)
    fabric_id          BIGINT NOT NULL REFERENCES fabric(id),
    mill_id            BIGINT NOT NULL REFERENCES mill(id),
    supplier           TEXT NOT NULL,       -- Name of Supplier, as written
    qty_m              @REAL@ NOT NULL,     -- Order Quantity, metres
    price              @REAL@ NOT NULL,     -- Net Price, rupees per metre (ex-mill)
    removed_upload_id  BIGINT REFERENCES upload(id),   -- a later file showed it deleted in SAP: kept, not counted
    UNIQUE (po_number, item)                -- the same order line uploaded twice is one line
);
CREATE INDEX purchase_line_fabric ON purchase_line (fabric_id, doc_date);
CREATE INDEX purchase_line_mill ON purchase_line (mill_id);

INSERT INTO store_state (kind, version) VALUES ('purchases', 0);
