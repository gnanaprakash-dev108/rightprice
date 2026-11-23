# RightPrice: progress and handover

As of 23 November 2026. Version 1 is built, calibrated once against purchase orders, and running.
It is not yet inside the 3–5% accuracy target.

## Decisions taken

| Decision | Choice |
|---|---|
| Price basis | SAP net price is ex-mill, so the should-cost stops at the mill gate (no freight) |
| Weft method | Corrected: wastage on reed space, plus 4% finishing shrinkage |
| Inputs | Every cost driver is a drop-down; only EPI, PPI, width and reed space are typed |
| Input routes | One fabric on screen, or many through an Excel upload with the same lists |
| Output | Rs per metre and Rs per kg, with buckets and second-level lines |
| Scope of version 1 | 100% cotton woven, rupee purchases per metre |
| Yarn master in the V1 workbook | Left untouched. The tool has its own copy in `data/Rate_Master.xlsx` |
| Platform | Stay with the Streamlit tool for now; no larger web stack yet |
| Yarn price intake | Excel/CSV, PDF, image, web link or API, all ending in a review table |

## What is built

- Costing engine that reproduces all seven V1 qualities exactly (Qlty-1 = Rs 181.40/m).
- Seven-screen app, bulk upload template, cost sheet download.
- Rate master with 15 sheets; every rate carries its basis.
- PLM link: 19,669 of 19,770 purchase-order material codes have specs.
- Content grouping: 8,446 blend spellings folded into 17 groups; stretch tracked separately.
- 68 PLM woven weave types mapped to 7 weave groups.
- Pilot, calibration draft with a held-back test, and an apply step with backup.

## Data in hand

| Source | Size | What it gave |
|---|---|---|
| Purchase orders, 1 Aug–23 Nov 2026 | 32,322 lines | 4,495 priced rupee-per-metre bulk fabrics |
| PLM fabric code list | 418,877 codes | Blend, dye method, weave, EPI, PPI, counts, width, finish |
| Master data workbook | 8,446 blends, 60 weaves | Lists for grouping |
| V1 workbook | 7 qualities, 24 yarns | Method, yarn master, reference rates |
| Ichalkaranji circular, 21 Nov 2026 | 15 pages | Market yarn rates |
| Sourcing platform yarn file | 2022–Jun 2026 | Shankar-6 cotton history |
| Published accounts, 7 suppliers | FY 2025-26 | Material, employee, power, margin as % of sales |

## Pilot result

Funnel: 4,495 priced fabrics → 4,465 woven → 2,037 100% cotton → 1,582 costed.

| | Before calibration | After calibration |
|---|---|---|
| Median PO price above should-cost | 7.5% | −0.5% |
| Within 5% | 20% | 28% |
| Within 10% | 40% | 48% |
| Within 20% | 69% | 79% |

Held-back third only (the fair test): median gap 7.9% → −1.5%, within 10% 38% → 47%.

Applied on 23 Nov 2026 (backup: `data/Rate_Master before calibration 20261123-2154.xlsx`):

- Order size: 3,000 m and above +0; 1,000 to 3,000 m +2 points of overhead; below 1,000 m +9 points.
- Weaving, piece-dyed plain: Rs 0.15 → 0.39 per pick. **Uncertain**: the same gap closes with piece
  dyeing at Rs 233/kg instead of Rs 160. A mill cost sheet for a piece-dyed poplin would settle it.
- Weaving, piece-dyed dobby: Rs 0.28 → 0.55 per pick.
- Printing: Rs 180 → 390 per kg greige.
- Confirmed unchanged: yarn-dyed dobby 0.45, twill 0.32, oxford 0.32; piece-dyed twill 0.18, satin 0.22.

Fit by type after calibration (median gap, share within 10%): yarn-dyed twill −0.2%, 70%;
printed satin 0.1%, 75%; piece-dyed plain 0.2%, 67%; yarn-dyed dobby −1.7%, 47%;
yarn-dyed oxford −2.7%, 46%; piece-dyed satin 3.1%, 57%; piece-dyed twill 4.3%, 52%.

## Known gaps

1. **Yarn-dyed plain is over-costed by 14%** (220 fabrics, mostly Amsler and slub). The mill rate card
   suggests the cause: the base yarn-dyed price assumes an undyed weft, and the tool dyes both.
2. **Printed twill and plain are over-costed** (−6% and −22%). The rate card gives rotary Rs 18/m and
   digital Rs 55/m; the tool has one rate that matches digital.
3. **Yarn-dyed jacquard is under-costed by 42%**; too few fabrics to set a rate.
4. **Fabrics in 2/100 yarn are bought at about double the should-cost** (23 fabrics); the spec is
   probably missing a premium cotton or finish.
5. **Rajapalayam sits 8% below should-cost** across 289 fabrics while Arvind, NSL and Vardhman are within 4%.
   Mill tier is still set to zero.
6. **46 placeholder rates remain**, mostly finishes. Four yarn rates are placeholders: Cotton 20S and
   Slub 20S, 24S, 30S.
7. **303 fabrics had a finish the tool did not recognise** and were costed as Normal.
8. **328 cotton fabrics are not costed** because one direction mixes yarns ("40s + 40s melange").
   60 more carry dye method "Solid", not yet mapped.
9. **2,428 woven fabrics are blends** and outside version 1. Largest groups by purchase-order codes:
   polyester viscose 2,866, cotton with stretch 1,206, CVC 1,163.
10. **Dollar purchases, per-kg purchases and knits** are not covered.
11. **Cotton price history stops at 24 June 2026.**
12. **Pictures are not read automatically** in the price intake; rates are typed beside the image.
13. **Yarn rates are one date.** Orders span August to November, costed on November rates.

## Mill rate card received 23 Nov 2026 (not yet built in)

Saved in [docs/Mill_Rate_Card.md](docs/Mill_Rate_Card.md). Comparison with the tool, for a 40s yarn-dyed shirting:

| | Rate card | Tool |
|---|---|---|
| One extra end | Rs 0.60 | Rs 0.62 |
| One extra pick, twill or plain | Rs 0.90 to 90 picks, Rs 1.00 above | Rs 1.03 |
| One extra pick, dobby | as above plus a shaft charge | Rs 1.13 |

To build in: print method (rotary, digital), dobby shafts and top beam, dyed or undyed weft,
finishes as Rs/m upcharges, small-lot steps (4%, 7%, 8% below 800 m) and volume discount
(Rs 2, 3, 4 per metre from 2,000, 4,000, 6,000 m).

Open questions on the card: which mill it is from, and whether the per-end and per-pick figures are
the price change for one end or pick (as read here).

## Next steps, in order

1. Build the rate card in as upcharges, then rerun `pilot.py` and `calibrate.py`.
2. Add a "share of yarn dyed" or "weft dyed" input for yarn-dyed fabrics.
3. Map the 303 unrecognised finishes and the "Solid" dye method.
4. Get one or two mill cost sheets (a piece-dyed poplin first) to settle weaving against dyeing.
5. Set mill tier adjustments from the by-supplier gaps.
6. Extend to cotton with stretch, then polyester viscose: yarn rates for blends are the main need.
7. Date the yarn rates so an order is costed on the rates of its month.
8. Dollar purchases and knits.

## Earlier roadmap

1. Calibration set (PO price + spec) — done through PLM.
2. Price basis — confirmed ex-mill.
3. Rate masters — built; partly calibrated.
4. Batch calculator — built (bulk upload, `pilot.py`).
5. Calibrate to within 3–5% — first pass done, not yet at target.
6. Flag gaps by supplier — first view in `pilot/Pilot_Results.xlsx`.
7. Put it in the sourcing platform — not started.
