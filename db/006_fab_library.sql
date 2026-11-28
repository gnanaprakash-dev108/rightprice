-- RightPrice database: the Fab library (GP's decision, 28 Nov 2026): the PLM fabric code list, every code with its
-- construction, uploaded by an admin and read in the background, as purchase files are (rules/fab_library.py).
--
-- Applied once, at start, by store.py (see 001_files_moved_in.sql for the @...@ words). Read and written by
-- data_fab_library.py. Times are kept as text in ISO form (2026-11-28T15:02:11), as in the other tables.
--
-- Once it holds an upload, the library is where the purchase history (rules/purchases.py plm_specs) takes each fabric
-- code's PLM specification from, in place of data/plm_specs_for_po.csv deployed with the code; before any upload, that
-- file, as before. Each upload is kept with who sent it and when, its file and its counts. A code's specification is
-- the one of the latest upload that holds it (uploads go in order of their number); a code missing from a later upload
-- keeps the specification it had (nothing is taken as removed).

-- the version counter of the library (store.KINDS 'library'): writers of it wait for each other
INSERT INTO store_state (kind, version) VALUES ('library', 0);

-- every upload of the PLM fabric code list
CREATE TABLE fab_library_upload (
    id             @ID@,
    filename       TEXT NOT NULL,
    uploaded_by    TEXT NOT NULL DEFAULT '',  -- the signed-in person (or "AI assistant")
    uploaded_at    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'queued',   -- queued | working | done | failed
    step           TEXT NOT NULL DEFAULT '',  -- what the job is doing now, in words
    started_at     TEXT,
    finished_at    TEXT,
    alive_at       TEXT,                      -- the job's last sign of life (a job stopped by a restart is told apart by it)
    runner         TEXT,                      -- the machine and process reading it
    error          TEXT,                      -- why it failed
    file_format    TEXT NOT NULL,             -- how the file is kept: csv.gz (a .csv, kept compressed, the same bytes when
                                              -- unpacked) | zip (a .zip holding one .csv, as uploaded) | xlsx (as uploaded)
    file_bytes     BIGINT,                    -- its size as uploaded
    content_bytes  BIGINT,                    -- the size of the list itself (the .csv inside a .zip, unzipped)
    file           @BLOB@,                    -- the file (see file_format)
    sha256         TEXT,                      -- of the file as uploaded
    rows_total     BIGINT,                    -- rows in the list (the headings not counted)
    codes_total    BIGINT,                    -- the codes it holds, each once
    codes_new      BIGINT,                    -- not in the library before
    codes_changed  BIGINT,                    -- in it with another specification: this upload's is used now (a correction)
    codes_same     BIGINT,                    -- in it with the same specification
    codes_older    BIGINT,                    -- a later upload already gave these codes: this one's specification is not used
    codes_kept     BIGINT,                    -- in the library from earlier uploads, not in this one: kept as they were
    rows_repeated  BIGINT,                    -- a code a second time in the file: the first row is used, as pilot.py does
    rows_no_code   BIGINT,                    -- rows without a code: left out
    no_epi_ppi     BIGINT,                    -- codes stored with EPI or PPI blank (or 20 or less: the PLM's filler)
    no_width       BIGINT,                    -- codes stored with the finished width blank or unreadable
    no_counts      BIGINT,                    -- codes stored with the warp or weft count blank
    summary        TEXT NOT NULL DEFAULT '{}' -- JSON: the purchase history regrouped and costed again, columns ignored, times
);

-- the codes: one row each, with the specification of the latest upload that holds it
CREATE TABLE fab_code (
    code             TEXT PRIMARY KEY,        -- the company's fabric (material) code, as the list writes it, trimmed
    spec             TEXT NOT NULL,           -- JSON: the row's 26 values (rules/fab_library.py COLUMNS, in that order), as received
    spec_sha         TEXT NOT NULL,           -- SHA-256 of the row as the purchase history keeps it (fab_groups.spec_sha)
    search           TEXT NOT NULL,           -- the code and its construction in small letters, for the page's search
    sig_rest         TEXT,                    -- its Fab group's eight fields other than the width, tidied (empty: not grouped)
    width_in         @REAL@,                  -- its finished width in inches (the ninth field)
    not_grouped      TEXT,                    -- why it cannot be in a Fab group (the specification incomplete ...), or empty
    upload_id        BIGINT NOT NULL,         -- the upload its specification is from
    first_upload_id  BIGINT NOT NULL,         -- the upload that first held it
    seen_upload_id   BIGINT NOT NULL,         -- the latest upload that held it
    changed_at       TEXT NOT NULL
);
CREATE INDEX fab_code_rest ON fab_code (sig_rest);

-- a code whose specification a later upload changed: what it was before, and what changed
CREATE TABLE fab_code_change (
    id         @ID@,
    code       TEXT NOT NULL,
    upload_id  BIGINT NOT NULL,               -- the upload that changed it
    old_spec   TEXT NOT NULL,                 -- JSON: the 26 values before
    what       TEXT NOT NULL,                 -- in words: 'article_cust_epi 132 to 142'
    at         TEXT NOT NULL
);
CREATE INDEX fab_code_change_code ON fab_code_change (code);
CREATE INDEX fab_code_change_upload ON fab_code_change (upload_id);
