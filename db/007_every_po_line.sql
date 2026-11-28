-- RightPrice database: every row of a purchase file stored (GP's decisions, 28 Nov 2026), its order type, its mode of
-- sourcing, its unit and its price in three columns; the order types' table; the exchange rates by month.
--
-- Applied once, at start, by store.py (see 001_files_moved_in.sql for the @...@ words).
--
-- Until now a purchase file's rows that are not a bulk order in rupees per metre were left out, or kept only as a mark (a
-- line a newer file shows no longer bought). Now each is stored with its figures as the file gives them: sampling orders,
-- stock transfers, returns, lines deleted or blocked in SAP, imports (other currencies), lines per kg or in other units.
-- Only domestic (rupee) bulk orders per metre count in the woven figures (prices, usual ranges, verdicts), as before; a
-- yard or a centimetre is converted to metres exactly (qty_m, price) and said. A stored line that does not count carries
-- why (not_counted) and is marked removed by the file that gave its figures (removed_upload_id, removed_why), as a line a
-- newer file removed is, so every figure that leaves removed lines out leaves it out too. Import lines are shown converted
-- to rupees on the order month's exchange rate, apart; lines per kg have their own per-kg figures.

ALTER TABLE purchase_line ADD COLUMN currency TEXT;          -- Currency, as the file gives it (INR, USD, EUR ...)
ALTER TABLE purchase_line ADD COLUMN unit TEXT;              -- Order Unit, as the file gives it (M, KG, YD, CM, PC ...)
ALTER TABLE purchase_line ADD COLUMN qty_po @REAL@;          -- Order Quantity, in that unit
ALTER TABLE purchase_line ADD COLUMN price_po @REAL@;        -- Net Price, in that currency per that unit
ALTER TABLE purchase_line ADD COLUMN deletion TEXT;          -- Deletion Indicator (L deleted, S blocked); empty when live
ALTER TABLE purchase_line ADD COLUMN not_counted TEXT;       -- why it counts in no rupees-per-metre figure; empty: it counts
UPDATE purchase_line SET currency = 'INR', unit = 'M', qty_po = qty_m, price_po = price WHERE fabric_id IS NOT NULL;
CREATE INDEX purchase_line_date ON purchase_line (doc_date);

ALTER TABLE upload ADD COLUMN rows_stored BIGINT;            -- rows stored: those that count, ZLOI, and those in no rupees-per-metre figure
ALTER TABLE upload ADD COLUMN rows_other BIGINT;             -- of them, those in no rupees-per-metre figure (shown in the price history by type)

-- SAP's purchasing document types and the order type each is: Bulk (counts), Letter of intent (ZLOI, kept apart), Sampling,
-- Stock transfer (zero-price moves between own plants), Return, Other. Seeded from the data read on 28 Nov 2026 (basis says
-- so); an admin or rates editor corrects it on Purchase lines. A type not here is Other, and the upload lists it.
CREATE TABLE order_type (
    sap_type    TEXT PRIMARY KEY,
    category    TEXT NOT NULL,                 -- Bulk | Letter of intent | Sampling | Stock transfer | Return | Other
    basis       TEXT NOT NULL,                 -- where the mapping is from
    changed_by  TEXT NOT NULL DEFAULT '',
    changed_at  TEXT NOT NULL
);
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('BO', 'Bulk', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('BF', 'Bulk', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('ZLOI', 'Letter of intent', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('BA', 'Sampling', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('YB', 'Stock transfer', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('ZB', 'Stock transfer', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('UB1', 'Stock transfer', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('UB', 'Stock transfer', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('UBRF', 'Stock transfer', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');
INSERT INTO order_type (sap_type, category, basis, changed_at) VALUES ('RK', 'Return', 'Read from the data, 28 Nov 2026', '2026-11-28T00:00:00');

-- exchange rates by month: rupees per unit of a currency. GP, 28 Nov 2026: the RBI (FBIL) reference rate, the month's
-- average, by default (source 'RBI reference rate'); a person may enter the rate actually paid for a month (source 'rate
-- paid'), which takes its place for that month, the RBI one kept. Nothing is seeded: a line whose month has no rate shows
-- its rupee price blank, and says why. A rate entered with no source counts as a Placeholder (rule 4).
CREATE TABLE fx_rate (
    id          @ID@,
    currency    TEXT NOT NULL,                 -- USD, EUR ...
    month       TEXT NOT NULL,                 -- the month's first day: 2026-09-01
    rate        @REAL@ NOT NULL,               -- rupees per unit of the currency
    source      TEXT NOT NULL,                 -- RBI reference rate | rate paid | Placeholder (no source given)
    note        TEXT NOT NULL DEFAULT '',      -- where the figure is from (a circular, a bank advice ...)
    entered_by  TEXT NOT NULL DEFAULT '',
    entered_at  TEXT NOT NULL,
    removed_at  TEXT,                          -- replaced or removed: kept, marked
    removed_by  TEXT,
    removed_why TEXT
);
CREATE INDEX fx_rate_key ON fx_rate (currency, month);
INSERT INTO store_state (kind, version) VALUES ('fx', 0);
