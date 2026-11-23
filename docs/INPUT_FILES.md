# Input files

Scripts look for these in `inputs/` (see `paths.py`). The app needs none of them.

## In `inputs/`

| File | What it is | Read by |
|---|---|---|
| `Fabric _ 3Months_4746.xlsx` | SAP purchase order export, 1 Aug–23 Nov 2026, 32,322 lines | `plm_extract.py`, `pilot.py`, `calibrate.py` |
| `Should be Cost V1 23rd Nov.xlsx` | The costing workbook the method comes from; seven earlier qualities | Reference; values copied into `build_masters.py` and `check_engine.py` |
| `Should be costing-11th Nov.xlsb` | Earlier version of the same workbook | Reference only |
| `Fabric Costing_Final.xlsx` | Older prototype with placeholder prices | Reference only |
| `SIS ICHALKARANJI 21.11.2026.pdf` | Yarn price circular, 15 pages, partly scanned | Market rates in the rate master; test file for PDF intake |
| `Yarn_Inteliigence_Master.xlsx` | Sourcing platform's yarn and cotton price file | `build_masters.py` (Shankar-6 cotton history) |

## Too large for a repository (GitHub rejects files over 100 MB; these also expand to 300–780 MB when read)

| File | Size | What it is | Read by |
|---|---|---|---|
| `PLM FABRIC CODE LIST20261123-150404-815777.xls` | 81 MB | PLM fabric list, 418,877 codes, 44 columns. An `.xlsx` despite the name. | `plm_extract.py` |
| `Master Data- Pending to WFX New.xlsx` | 57 MB | PLM master data; only `BlendsMapping` and `FabricDropDown` are used | `refresh_groups.py` |

Their useful content is already extracted into the repository:

- `data/plm_specs_for_po.csv`: specs for the 19,669 purchase-order codes.
- `data/plm_value_counts.xlsx`: how often each blend, weave, finish, dye method and count occurs across all PLM codes.
- `data/Rate_Master.xlsx`, sheets `Content_Groups` and `Weaves`.

To rerun the extraction, put both files in `inputs/` or point the environment variable
`SHOULD_COST_INPUTS` at their folder. Always stream them; never load them whole.

## Not copied

- `ABLBL SOURCING ZIP/` (the sourcing platform app and its vendor master). The first pilot used its
  vendor master for specs; PLM replaced it.
- `ablbl sourcing ppt 2.pptx`, `Textile Costing Guide_ Yarn, Fabric & Garment.mhtml`: background reading.

## Confidentiality

The purchase order file, the PLM extract and the pilot results hold prices paid, supplier names and
fabric specifications. Keep the repository private, or leave `inputs/`, `data/plm_specs_for_po.csv`
and `pilot/` out of it (uncomment the lines in `.gitignore`).
