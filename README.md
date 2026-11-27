# RightPrice: Fabric Should-Cost Tool

Works out what a woven fabric should cost ex-mill, in Rs per metre and Rs per kg, from its
construction and a set of rate tables, and compares that with a quote or a purchase order price.

Version 1 is calibrated for 100% cotton woven fabrics. Poly cotton and linen can be costed, but only
on placeholder yarn rates and cotton's process rates, so their cost is provisional. Status, findings and open items are in
[PROGRESS.md](PROGRESS.md).

> **Keep this repository private.** `inputs/`, `data/plm_specs_for_po.csv` and `pilot/` contain
> purchase prices, supplier names and fabric specifications.

## Run it

```
pip install -r requirements.txt
python -m uvicorn server:app --port 8000
```

Then open `http://localhost:8000`. The app needs only `data/Rate_Master.xlsx`. None of the source
workbooks are needed to cost a fabric. On Windows, `Start RightPrice.bat` does the same on port 8502.

The front end is hand-built (`web/`, plain HTML, CSS and JavaScript, no build step) and reads its
numbers from `server.py`. The back end has three layers (since 27 Nov 2026): the costing engine
(`engine.py`, `masters.py`: every number, every rate from the rate master), the business rules
(`rules/`: briefs, the fabric list, the pack, Right cost, the tracker, supplier pages, alerts, drafts,
the dashboard, rate edits) and the web requests (`server.py`, which reads a request, calls one rule
and shapes the answer). The rules read and write only through the data layer, `store.py`. The
earlier Streamlit screens stay reachable at `/classic` ("Earlier screens" in the left panel).

Where the data is kept, chosen by one setting:
- `DATABASE_URL` not set: files in the data folder, as before (`RIGHTPRICE_DATA`, or `data/`).
- `DATABASE_URL=postgresql://user:password@host:5432/postgres?sslmode=require`: a PostgreSQL database.
- `DATABASE_URL=sqlite:////full/path/rightprice.db`: a database file.

With a database set and empty, the app copies the files in at its first start, checks them and
never changes them. `/api/store` says which store is in use and what it holds. `python store.py
export <new folder>` writes a database back out as files. The tables are in `db/` (numbered files,
applied once at start); the full design for the later stages is `db/schema.sql`.

To host it on Azure, follow [docs/AZURE_DEPLOY.md](docs/AZURE_DEPLOY.md). The environment variable
`RIGHTPRICE_DATA` moves the rate master, saved costings and imported price files to a folder that
survives redeploys.

## Users and roles

Off until the app setting `RIGHTPRICE_ADMINS` (the first admins' sign-in addresses) is added; until then everyone
signed in may use everything, as before. With it, nobody gets in until an admin adds them under the user icon >
Users and roles, with a role: Admin, Rates editor, Buyer or Viewer (what each may see and do can be changed there; every
change is recorded). Every address the server answers needs a permission (`rules/access.py`, `ROUTES`), checked in
one place before the request reaches it (`server.py`, `AccessGate`); `check_server.py` fails if an address has none.
Actions (edit rates, upload, record steps ...) are strict; a page's tick decides which pages a role can open, not which
figures it can read (data several pages read stays open to a role with any of them).
The people are kept in the database (`db/003_users_and_roles.sql`). Steps: [docs/AZURE_DEPLOY.md](docs/AZURE_DEPLOY.md),
"Users and roles".

## Screens

Since 26 Nov 2026 the app opens in one shell: a left rail with Home (Dashboard and Pilot results),
Right cost (every costing) and Prices (market prices, the rate master tables and settings, and the
costing and sourcing setup lists), and a "New cost" button that opens Create cost, Bulk upload,
Compare and Negotiation pack as tabs in a popup. Light or dark, and settings, are under the user
icon. The earlier screens are shown inside the shell (`/?embed=1` serves them on their own).
The left panel groups the pages under Costing, Prices, Rates and Analysis. Light and dark are
switched in the header; the search box finds yarns, saved costings, rate tables and pages.
The left panel folds to icons and opens on hover; pin it open, or turn the compact header off, under
Settings > Display. On a phone, "Add to Home screen" in the browser gives it its own icon and a
full-screen view.

| Screen | What it does |
|---|---|
| Dashboard | Yarn price what-if; price paid against should-cost by fabric type; share of each cost group by route; cotton price by year; questions to ask before a negotiation; supplier cost ratios. All from the buyer's own data |
| Cost a fabric | Numbered steps on the left (fabric content, route, yarn, dyeing, construction, finish), each deciding what the next asks; live cost on the right; chart switchable between bars, waterfall, pie, treemap and line, by cost group or every sub-cost |
| Right cost | `/rightcost`: every costing (1,696 purchase orders and the fabric list) in one PLM-style list with search, filters, saved searches, card and list views and detail pages; "+" opens Cost a fabric in a popup |
| Negotiation pack | One printable page for a whole mill sheet (or the rows ticked on the list): totals, the rows to lead with, every row with its stance and money at stake, the mill's sums that are off and what its own sums give, the questions to ask, and the rows not costed |
| Compare | Two costings side by side on today's rates: every group and sub-cost, the difference, and the choices that differ |
| Bulk upload and list | Upload a mill's price sheet as it comes, or the RightPrice template. One list of every fabric costed, in the mill sheet's headings, with should-cost, the gap and a check of the mill's sums; tick rows to open, compare or remove; move a yarn price across the whole list |
| Yarn prices | Yarn master and market reference, both editable; master against market |
| Bring in prices | Yarn prices from Excel, CSV, PDF, a picture, a web page or a price service, into a review table and then the market reference |
| Cotton prices | Shankar-6 history and chart |
| Rate tables | Weaving, sizing, dyeing, finishing, print method, dobby, weft, rate card quantity, defaults, weave list, content groups |
| Mill rate card | The rate card tables: print method, dobby, weft, quantity terms, finish upcharges |
| Settings | Shrinkage, reed space factor, mill tiers, order size slabs |
| Pilot results | Should-cost against purchase order prices, and the calibration draft |

## The calculation

Same arithmetic as `Should be Cost V1 23rd Nov.xlsx`, corrected method:

```
warp kg/m = EPI x finished width x K x (1 + warp crimp) x (1 + warp wastage) / warp Ne
weft kg/m = PPI x reed space x K x (1 + weft wastage) / weft Ne
base      = yarn + yarn dyeing + sizing + weaving + finishing + piece dyeing
price     = base / (1 - shrinkage) x (1 + process wastage + overhead) x (1 + margin) + extra
price     = (price + rate card upcharges in Rs/m) x (1 + small-lot upcharge) - volume discount
```

The second price line is the mill rate card ([docs/Mill_Rate_Card.md](docs/Mill_Rate_Card.md)): print
method, dobby shafts, top beam, chambray dyed weft and finish upcharges in Rs per metre, then the
quantity terms. Every one is optional and zero by default, so the V1 arithmetic is untouched. They
are charged on the price and are not marked up. A rate card quantity band takes the place of the
order size slab, so quantity is never charged twice.

K = 0.00059, shrinkage = 4%. `python check_engine.py` confirms the engine reproduces the seven
qualities in the V1 workbook to the paisa and that each rate card item adds what the card says; run
it after any change to `engine.py` or `masters.py`. It must print `ALL OK`.

## Files

| File | Purpose |
|---|---|
| `engine.py` | The calculation. Numbers in, numbers out. |
| `masters.py` | Reads and saves the rate master, turns drop-down choices into rates, upload template, bulk costing |
| `server.py` | The web requests: serves `web/`, turns each request into one call to `rules/`, and passes `/classic` through to the Streamlit screens |
| `rules/` | The business rules, one module per area (`costing`, `fabric_list`, `pack`, `rightcost`, `tracker`, `supplier`, `alerts`, `drafts`, `dashboard`, `rates`, `costsheets`, `mills`, `common`) |
| `store.py` | The data layer: files, or PostgreSQL / SQLite when `DATABASE_URL` is set; copies the files in once; `python store.py status`, `export <folder>`, `keep-database` |
| `db/` | `001_files_moved_in.sql` (the tables in use) and `schema.sql` (the full design for stages 2 to 6) |
| `web/` | The front end: `index.html`, `app.css`, `app.js` |
| `app.py` | The earlier Streamlit screens, now at `/classic` |
| `mill_sheet.py` | Reads a mill's price sheet (base price plus upcharges), turns each row into the tool's choices, and checks the mill's arithmetic |
| `yarn_seed.py` | Placeholder yarn rates for poly cotton and linen, added once to the rate master |
| `draft.py` | E-mail and WhatsApp drafts to a mill, written by Claude (app setting `ANTHROPIC_API_KEY`), with a fixed template when there is no key |
| `mcp_server.py` | RightPrice as an MCP server for an AI assistant: at `/mcp` on the web app behind the token `RIGHTPRICE_MCP_TOKEN`, or `python mcp_server.py` on a laptop. See [docs/AZURE_DEPLOY.md](docs/AZURE_DEPLOY.md) |
| `rules/access.py`, `data_users.py` | Users and roles: who is signed in (Azure's sign-in headers), the four roles and their default permissions, which permission each address needs, the admin page's changes and their record (the SQL is in `data_users.py`) |
| `web/access.js`, `web/access.css` | The Users and roles page, and what the shell hides from a role that may not use it |
| `check_server.py` | Checks the server gives the engine's numbers and refuses bad input, on the files, SQLite and PostgreSQL (`RIGHTPRICE_TEST_DATABASE_URL`, never `DATABASE_URL`), and proves the move from files to a database changes no answer. Must print `ALL OK` |
| `grouping.py` | Folds blend spellings into 17 content groups and weave names into 7 weave groups |
| `price_import.py` | Yarn price intake from Excel, PDF, image, link or API |
| `paths.py` | Finds the source workbooks (`inputs/`, or the env variable `SHOULD_COST_INPUTS`) |
| `check_engine.py` | Regression check against the V1 workbook |
| `rate_card.py` | The mill rate card tables. `python rate_card.py` adds them to the rate master after saving a dated backup; safe to run twice |
| `build_masters.py` | Creates a starting rate master. **`--force` overwrites `data/Rate_Master.xlsx` and loses the calibration; do not use it on a calibrated master.** |
| `plm_extract.py` | Streams the PLM fabric list and writes specs for purchase-order codes |
| `refresh_groups.py` | Adds content groups and PLM weave types to the rate master |
| `pilot.py` | Costs purchase-order fabrics and compares with the price paid |
| `calibrate.py` | Drafts rate changes from the pilot with a held-back test; applies nothing |
| `apply_proposals.py` | Applies the draft to the rate master, after saving a dated backup |
| `data/Rate_Master.xlsx` | **The source of truth for every rate.** Edited through the app or in Excel. |
| `data/plm_specs_for_po.csv` | PLM specs for the 19,669 purchase-order codes (output of `plm_extract.py`) |
| `pilot/` | Pilot results and the proposed rate changes |
| `templates/` | Bulk upload template |
| `docs/` | Input file list, the mill rate card, and the roadmap |

## Rerunning the analysis

```
python plm_extract.py     # needs the two large workbooks; about 90 seconds
python refresh_groups.py  # needs the master data workbook
python pilot.py           # needs inputs/Fabric _ 3Months_4746.xlsx and data/plm_specs_for_po.csv
python calibrate.py       # same inputs as pilot.py; writes a draft only
```

See [docs/INPUT_FILES.md](docs/INPUT_FILES.md) for what each source file is and which script reads it.

## Rates and their basis

Every rate carries a Basis: `V1 workbook`, `Pilot calibration <date>`, `Pilot-checked`,
`Market circular`, `Mill rate card <date>`, `Placeholder` (a starting guess with no data behind it) or `Not set`.
The app warns whenever a costing uses a placeholder.
