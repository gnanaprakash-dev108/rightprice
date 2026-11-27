-- RightPrice: the full table design for the database (the rebuild agreed with GP on 27 Nov 2026).
-- The tables IN USE are created by the numbered files beside this one, applied once at start by store.py:
--   001_files_moved_in.sql (stage 1): store_state, store_meta, import_run, rate_version, quote, negotiation,
--   negotiation_step, alert_seen, cost_sheet_row. They hold what the files held, as it was; their columns differ from the
--   draft below where the files needed it (cells kept as the list file's text, so every row reads back exactly).
-- Everything else below is the design for stages 2 to 6, still a draft: each stage brings its tables in its own numbered
-- file, and may change them. PostgreSQL 16 accepts this file; nothing applies it.
-- Money is rupees; prices are per metre; quantities are metres.
--
-- Three ideas run through it:
--   1. One record per mill, per cloth (Fab group), per fabric code and per order line, so nothing is matched by name twice.
--   2. One meaning of "price": the sheet's price is on the quote; what happened since is negotiation steps. Nothing is overwritten.
--   3. Every costing is stored with the rate version (and, from stage 5, the rate date) that produced it, so a figure can be reproduced.

-- ---------------------------------------------------------------- people and what they may do (stage 3)
-- In use since stage 3: db/003_users_and_roles.sql, which differs from this draft: app_user keyed by e-mail, the roles
-- and their default permissions in rules/access.py, role_permission holding only what admins changed, and audit_log.
CREATE TABLE role (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE                      -- Admin, Buyer, Viewer, Assistant (the MCP token)
);
CREATE TABLE role_permission (
    role_id     int  NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    permission  text NOT NULL,                            -- 'page:dashboard', 'page:rates', 'do:edit_rates', 'do:upload', 'do:record_step' ...
    PRIMARY KEY (role_id, permission)
);
CREATE TABLE app_user (
    id          serial PRIMARY KEY,
    email       text NOT NULL UNIQUE,                     -- as Microsoft sign-in gives it, lower case
    name        text NOT NULL DEFAULT '',
    role_id     int  REFERENCES role(id),                 -- null = signed in but not yet let in
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- mills
CREATE TABLE mill (
    id          serial PRIMARY KEY,
    name        text NOT NULL,                            -- the spelling shown
    key         text NOT NULL UNIQUE                      -- what mill_key() gives today: 'arvind'
);
CREATE TABLE mill_alias (
    spelling    text PRIMARY KEY,                         -- every way the mill has been written, as received
    mill_id     int NOT NULL REFERENCES mill(id)
);

-- ---------------------------------------------------------------- cloth: Fab groups and fabric codes (stage 2)
CREATE TABLE fab_group (
    id          serial PRIMARY KEY,
    code        text NOT NULL UNIQUE,                     -- Fab-0001, Fab-0002 ...; never changed, never reused
    name        text NOT NULL,                            -- '100% Cotton · Yarn Dyed · 2/1 Twill · 40s x 40s · 136 x 90 · 58 in · Normal'
    content     text NOT NULL, route text NOT NULL, weave text NOT NULL,
    warp        text NOT NULL, weft  text NOT NULL,
    epi         numeric(7,2) NOT NULL, ppi numeric(7,2) NOT NULL,
    width_in    numeric(7,2) NOT NULL, finish text NOT NULL,
    signature   text NOT NULL UNIQUE,                     -- the nine fields above, tidied and joined: what makes two fabrics one group
    merged_into int REFERENCES fab_group(id),             -- an admin merged this group into another; its code is kept, never handed out again
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE fabric (
    id            serial PRIMARY KEY,
    code          text NOT NULL UNIQUE,                   -- the company's fabric (material) code
    description   text NOT NULL DEFAULT '',
    fab_group_id  int REFERENCES fab_group(id),           -- null = specification incomplete: 'not grouped', never guessed
    spec          jsonb NOT NULL DEFAULT '{}',            -- the PLM specification as received (blend, dye method, pattern, counts ...)
    choices       jsonb,                                  -- the tool's costing choices worked out from it; null = cannot be costed, with why in problems
    problems      jsonb NOT NULL DEFAULT '[]'
);

-- ---------------------------------------------------------------- everything that comes in as a file
CREATE TABLE upload (
    id           serial PRIMARY KEY,
    kind         text NOT NULL,                           -- purchase_orders | fabric_specs | mill_sheet | template | yarn_prices | cost_sheet
    filename     text NOT NULL,
    uploaded_by  int REFERENCES app_user(id),
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    status       text NOT NULL DEFAULT 'queued',          -- queued | working | done | failed (bulk costing runs in the background)
    rows_total   int, rows_loaded int, rows_skipped int,
    skipped      jsonb NOT NULL DEFAULT '[]'              -- which rows were left out, and why
);

-- ---------------------------------------------------------------- what was bought (dated)
CREATE TABLE purchase_line (
    id          bigserial PRIMARY KEY,
    upload_id   int NOT NULL REFERENCES upload(id),
    po_number   text NOT NULL, item text NOT NULL,
    doc_date    date NOT NULL,
    doc_type    text NOT NULL,
    fabric_id   int NOT NULL REFERENCES fabric(id),
    mill_id     int NOT NULL REFERENCES mill(id),
    qty_m       numeric(14,3) NOT NULL,
    price       numeric(12,4) NOT NULL,                   -- net price, rupees per metre
    UNIQUE (po_number, item)                              -- the same order line uploaded twice is one line
);
CREATE INDEX ON purchase_line (fabric_id, doc_date);
CREATE INDEX ON purchase_line (mill_id);

-- ---------------------------------------------------------------- what is quoted (the fabric list)
CREATE TABLE quote (
    id            bigserial PRIMARY KEY,
    legacy_id     text UNIQUE,                            -- the Id in today's costing_log.csv, so addresses and keys keep working
    upload_id     int REFERENCES upload(id),              -- null = added on screen
    fabric_code   text NOT NULL,                          -- as on the sheet; may match no fabric row
    mill_id       int REFERENCES mill(id),
    supplier_text text NOT NULL DEFAULT '',               -- as written on the sheet
    sheet_row     jsonb,                                  -- the mill's own columns, untouched (base price, upcharges ...)
    choices       jsonb,                                  -- the tool's costing choices; null = not costed
    sheet_price   numeric(12,4),                          -- the price on the sheet. Never overwritten: later prices are negotiation steps
    quantity_m    numeric(14,3),
    problems      jsonb NOT NULL DEFAULT '[]',
    notes         jsonb NOT NULL DEFAULT '[]',
    repeats_quote_id bigint REFERENCES quote(id),         -- the same order as another row
    added_by      int REFERENCES app_user(id),
    added_at      timestamptz NOT NULL DEFAULT now(),
    removed_at    timestamptz                             -- removed rows are kept, marked
);

-- ---------------------------------------------------------------- negotiation: the tracker
CREATE TABLE negotiation_step (
    id           bigserial PRIMARY KEY,
    legacy_key   text NOT NULL,                           -- 'Fabric list|<id>' or 'Purchase orders|<code>', as today
    quote_id     bigint REFERENCES quote(id),             -- one of these two is set
    fabric_id    int REFERENCES fabric(id),
    step_date    date NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('Mill''s quote', 'Our counter', 'Mill''s revised quote', 'Agreed')),
    price        numeric(12,2) NOT NULL CHECK (price >= 1 AND price <= 50000),
    note         text NOT NULL DEFAULT '',
    recorded_by  text NOT NULL DEFAULT '',                -- the signed-in person, or 'AI assistant'
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    removed_at   timestamptz, removed_by text             -- a removed step is kept for the Log
);
CREATE INDEX ON negotiation_step (legacy_key);
CREATE TABLE alert_seen (
    quote_id  bigint PRIMARY KEY REFERENCES quote(id),
    seen_by   text NOT NULL DEFAULT '', seen_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- rates: the rate master, versioned and dated
CREATE TABLE rate_version (
    id          serial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL DEFAULT '',
    reason      text NOT NULL                             -- 'Moved from Rate_Master.xlsx', 'Yarn prices brought in', 'Mill cost sheet applied: Arvind' ...
);
CREATE TABLE rate_sheet (                                  -- each sheet of the rate master, whole, per version: Excel in and out stays exact
    version_id  int  NOT NULL REFERENCES rate_version(id),
    sheet       text NOT NULL,                            -- 'Yarn_Rates', 'Weaving_Rates', 'Settings' ...
    rows        jsonb NOT NULL,                           -- the rows, each with its Basis ('Placeholder' included)
    PRIMARY KEY (version_id, sheet)
);
-- stage 5 AS BUILT: db/005_dated_rates.sql. One rate per yarn per month (valid_from is the first of the month, not carried
-- into the next), with its source (typed | brought in | market history), the prices behind it, and replaced or removed
-- rows kept, marked. The draft below was its starting point.
CREATE TABLE yarn_rate_dated (                             -- stage 5: a yarn's rate from a date, so an order is costed on the rate of its month
    yarn_key    text NOT NULL,
    valid_from  date NOT NULL,
    rate        numeric(10,2) NOT NULL,                   -- rupees per kilo
    basis       text NOT NULL,                            -- 'Market circular', 'Placeholder' ...
    source      text NOT NULL DEFAULT '',
    entered_by  text NOT NULL DEFAULT '', entered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (yarn_key, valid_from)
);

-- ---------------------------------------------------------------- costings: worked out once, kept
CREATE TABLE costing (
    id               bigserial PRIMARY KEY,
    fabric_id        int REFERENCES fabric(id),           -- one of these two is set
    quote_id         bigint REFERENCES quote(id),
    rate_version_id  int NOT NULL REFERENCES rate_version(id),
    rate_date        date,                                -- null = on the latest rates; a date = on the rates of that day (stage 5)
    should_per_m     numeric(12,4) NOT NULL,
    per_kg           numeric(12,4), gsm numeric(10,3),
    buckets          jsonb NOT NULL,                      -- yarn, yarn dyeing, sizing and weaving ... rupees per metre
    placeholders     jsonb NOT NULL DEFAULT '[]',
    computed_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ON costing (fabric_id, rate_version_id, COALESCE(rate_date, DATE '0001-01-01')) WHERE fabric_id IS NOT NULL;
CREATE UNIQUE INDEX ON costing (quote_id,  rate_version_id, COALESCE(rate_date, DATE '0001-01-01')) WHERE quote_id  IS NOT NULL;

-- ---------------------------------------------------------------- each person's own marks (in the browser today)
CREATE TABLE user_mark (
    user_id     int  NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    subject_key text NOT NULL,                            -- the row's key
    status      text NOT NULL DEFAULT '', remarks text NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, subject_key)
);
CREATE TABLE saved_search (
    user_id     int  NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name        text NOT NULL, definition jsonb NOT NULL,
    PRIMARY KEY (user_id, name)
);

-- ---------------------------------------------------------------- mill cost sheets, the learned benchmark, and the record of who did what
CREATE TABLE cost_sheet_row (
    id         bigserial PRIMARY KEY,
    upload_id  int REFERENCES upload(id), mill_id int REFERENCES mill(id),
    row        jsonb NOT NULL                             -- the mill's own figures for one fabric
);
CREATE TABLE benchmark_model (                             -- stage 6
    id            serial PRIMARY KEY,
    trained_at    timestamptz NOT NULL DEFAULT now(),
    data_through  date NOT NULL,                          -- purchases up to this date were used
    metrics       jsonb NOT NULL,                         -- against the Fab-group-median baseline, on constructions it never saw
    artifact      bytea NOT NULL,
    active        boolean NOT NULL DEFAULT false          -- switched on only where it beats the baseline
);
CREATE TABLE audit_log (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    who     text NOT NULL DEFAULT '',
    action  text NOT NULL,                                -- 'rate changed', 'draft applied', 'upload', 'user added', 'step recorded' ...
    subject text NOT NULL DEFAULT '', detail jsonb NOT NULL DEFAULT '{}'
);
