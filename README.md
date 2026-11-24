# RightPrice: Fabric Should-Cost Tool

Works out what a woven fabric should cost ex-mill, in Rs per metre and Rs per kg, from its
construction and a set of rate tables, and compares that with a quote or a purchase order price.

Version 1 covers 100% cotton woven fabrics. Status, findings and open items are in
[PROGRESS.md](PROGRESS.md).

> **Keep this repository private.** `inputs/`, `data/plm_specs_for_po.csv` and `pilot/` contain
> purchase prices, supplier names and fabric specifications.

## Run it

```
pip install -r requirements.txt
streamlit run app.py
```

The app needs only `data/Rate_Master.xlsx`. None of the source workbooks are needed to cost a fabric.
On Windows, `Start RightPrice.bat` does the same on port 8502.

## Screens

| Screen | What it does |
|---|---|
| Dashboard | Saved costings, quote gap, key yarn and cotton rates, supplier cost ratios |
| Cost a fabric | Drop-downs for every cost driver; cost view with one bar per bucket and second-level detail |
| Bulk upload | Excel template with the same drop-downs; costs every row and rejects values not on a list |
| Yarn prices | Yarn master (editable), market reference, and price intake from Excel, PDF, image, web link or API |
| Cotton prices | Shankar-6 history and chart |
| Rate tables | Weaving, sizing, dyeing, finishing, print method, dobby, weft, rate card quantity, defaults, weave list, content groups |
| Settings | Shrinkage, reed space factor, mill tiers, order size slabs |

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
| `app.py` | The Streamlit screens |
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
