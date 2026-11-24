# RightPrice: progress and handover

As of 24 November 2026. Version 1 is built, calibrated once against purchase orders, and running.
The mill rate card is built in as optional upcharges. It is not yet inside the 3–5% accuracy target.

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
- Rate master with 20 sheets; every rate carries its basis.
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

## Pilot result, first calibration (23 Nov, before the rate card)

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

1. **Yarn-dyed plain is over-costed**, by 14% before the rate card and 10% after (220 fabrics, mostly
   Amsler and slub). The undyed-weft explanation does not hold: checks are over-costed as much as stripes.
2. **Prints**: twill and plain were over-costed (−6% and −22%) on one rate per kg. On the card's
   rotary rate every print type is now under-costed. See "What did not improve".
3. **Yarn-dyed jacquard is under-costed by 42%**; too few fabrics to set a rate.
4. **Fabrics in 2/100 yarn are bought at about double the should-cost** (23 fabrics); the spec is
   probably missing a premium cotton or finish.
5. **Rajapalayam sits 8% below should-cost** across 289 fabrics while Arvind, NSL and Vardhman are within 4%.
   Mill tier is still set to zero.
6. **43 placeholder rates remain** (46 before the rate card), mostly finishes. Four yarn rates are placeholders: Cotton 20S and
   Slub 20S, 24S, 30S.
7. **66 fabrics have a finish the tool does not recognise** (303 before) and are costed as Normal.
8. **328 cotton fabrics are not costed** because one direction mixes yarns ("40s + 40s melange").
   60 more carry dye method "Solid", not yet mapped.
9. **2,428 woven fabrics are blends** and outside version 1. Largest groups by purchase-order codes:
   polyester viscose 2,866, cotton with stretch 1,206, CVC 1,163.
10. **Dollar purchases, per-kg purchases and knits** are not covered.
11. **Cotton price history stops at 24 June 2026.**
12. **Pictures are not read automatically** in the price intake; rates are typed beside the image.
13. **Yarn rates are one date.** Orders span August to November, costed on November rates.

## Mill rate card, built in 24 Nov 2026

The card is in [docs/Mill_Rate_Card.md](docs/Mill_Rate_Card.md), with a table of how each section is used.
Two things about it are unconfirmed: which mill it is from, and that its per-end and per-pick
figures are the price change for one extra end or pick.

### What changed

- New drop-downs, on screen and in the bulk upload template: Print method, Dobby shafts, Top beam,
  Weft (yarn dyed), Rate card quantity. Finishes carry the card's Rs per metre.
- New rate master sheets: `Print_Methods`, `Dobby_Charges`, `Weft_Options`, `Quantity_Terms`; a new
  column in `Finishing_Rates`; one new row in `Settings`. Added by `python rate_card.py`.
  Backup: `data/Rate_Master before rate card 20261124-0914.xlsx`.
- The printing rate of Rs 390 per kg is gone. A printed fabric now carries preparation at Rs 60 per kg
  (a placeholder, equal to RFD) plus the print method in Rs per metre.
- Every card item is added to the price and not marked up. Each is its own second-level line in a new
  bucket, "Upcharges and quantity terms".
- Defaults charge nothing. `check_engine.py` prints ALL OK: the seven V1 qualities match to the paisa,
  and 21 further checks confirm each card item adds what the card says.
- Order size and the card's quantity terms are reconciled by using one or the other, never both
  (see "Quantity" below).

### What the pilot could and could not set from PLM

| Input | Set from data? | How |
|---|---|---|
| Finish | Yes | PLM finish name. Unrecognised finishes fell from 303 to 66 |
| Rate card quantity | Yes | Metres of the fabric code across all orders, 1 Aug to 23 Nov. Not the size of one order, and split deliveries cannot be told apart |
| Weft (yarn dyed) | Partly | 357 checks and horizontal stripes: dyed. 5 chambrays: undyed, by definition. **560 stripes, solids and textures: PLM does not say; left as dyed** |
| Print method | **No** | Not in PLM. All 222 prints costed as rotary |
| Dobby shafts, top beam | **No** | Not in PLM. All 394 dobbies left at no charge |

### Results

1,582 fabrics, held-back third 517. Gap is purchase price above should-cost.

| | Before | After |
|---|---|---|
| All: median gap | −0.5% | 3.0% |
| All: within 5% / 10% / 20% | 28% / 48% / 79% | 26% / 49% / 72% |
| Held-back: median gap | −1.5% | 4.3% |
| Held-back: within 5% / 10% / 20% | 27% / 47% / 78% | 24% / 47% / 71% |
| All except printed (1,363): median gap | −0.5% | 1.6% |
| All except printed: within 5% / 10% / 20% | 27% / 48% / 80% | 29% / 54% / 79% |
| Held-back except printed (434): within 5% / 10% / 20% | 26% / 47% / 79% | 27% / 51% / 78% |

The known over-costed groups:

| Type | Fabrics | Median gap before → after | Within 5% | Within 10% | Within 20% |
|---|---|---|---|---|---|
| Yarn-dyed plain | 220 | −13.9% → −10.4% | 7% → 14% | 19% → 38% | 86% → 90% |
| Yarn-dyed plain, held-back | 71 | −13.9% → −10.4% | 6% → 16% | 20% → 35% | 86% → 90% |
| Printed twill | 64 | −6.1% → 27.2% | 0% → 0% | 9% → 8% | 50% → 42% |
| Printed twill, held-back | 20 | −10.4% → 22.0% | 0% → 0% | 5% → 10% | 55% → 50% |
| Printed plain | 23 | −22.3% → 10.0% | 39% → 35% | 39% → 57% | 43% → 61% |
| Printed plain, held-back | 10 | −25.6% → 6.6% | 20% → 40% | 20% → 70% | 30% → 80% |

Other types, all fabrics, median gap and share within 10%: yarn-dyed dobby −1.7% → 1.4%, 47% → 58%;
yarn-dyed twill −0.2% → 3.1%, 70% → 70%; yarn-dyed oxford −2.6% → −0.8%, 46% → 39%;
piece-dyed plain 0.2% → 2.0%, 67% → 72%; piece-dyed twill 4.3% → 5.2%, 52% → 52%;
piece-dyed satin 3.1% → 5.1%, 57% → 57%; **printed satin 0.1% → 34.8%, 75% → 17%**.

Step by step (sheet "Rate card steps" in `pilot/Pilot_Results.xlsx`), all fabrics:

| Inputs | Median gap | Within 10% | Within 20% |
|---|---|---|---|
| Before | −0.5% | 48% | 79% |
| Print as rotary, finishes from the card | 1.0% | 45% | 74% |
| ...and weft from the PLM pattern | 1.0% | 45% | 74% |
| ...and rate card quantity in place of slabs (the result) | 3.0% | 49% | 72% |
| What if every print were digital | 2.2% | 50% | 79% |
| What if weft were undyed wherever PLM does not say | 6.6% | 48% | 69% |

### What did not improve

1. **Prints got worse.** They moved from over-costed to under-costed by 10% to 35%. The purchase
   prices imply a print charge of about Rs 80 per metre (middle half Rs 43 to 90) on top of the tool's
   greige and preparation cost, above even the card's digital Rs 55. Only one print in six sits nearer
   rotary than digital. Either most of these prints are digital and priced above the card, or the
   cloth under the print is under-costed (preparation is a Rs 60 per kg placeholder). Printed satin,
   which fitted at Rs 390 per kg, is the largest loss. Assuming every print is digital brings printed
   twill to 3.2% but leaves satin well under.
2. **Yarn-dyed plain is still over-costed by 10%.** The weft input did almost nothing, because the
   over-costing is the same on checks, where the weft is certainly dyed, as on stripes. Of the 220
   fabrics, 175 are Amsler 24s or slub 24s from two mills. The gain that did come was from quantity
   bands and finishes. Even with every unknown weft undyed the group is at −6.8%. The Amsler and slub
   yarn rates, and the higher wastage, overhead and margin given to yarn-dyed plain (5%, 5%, 8% against
   3%, 4%, 7% for twill), are the next places to look.
3. **Overall fit is flat to worse.** Within 10% is unchanged at 48% to 49%; within 20% fell from 79%
   to 72%, nearly all of it prints. Leaving prints out, within 10% rose from 48% to 54%.
4. **Yarn-dyed oxford** within 10% fell from 46% to 39% although its median improved.
5. **The whole level moved up about 2 points** because the card's quantity terms price a mid-size
   order lower than the slabs did. The weaving rates were calibrated with the slabs in place.

### Quantity: how order size and the card are reconciled

The order size slabs (+9 points below 1,000 m, +2 from 1,000 to 3,000 m) were measured from purchase
orders before the card. They already hold whatever small-lot premium and volume discount the mills
gave, so adding the card's terms on top would count quantity twice.

- **Now:** one or the other. When a rate card quantity band is chosen, the order size slab is not
  charged (Settings: "Order size slabs with rate card quantity" = Replaced). The pilot uses the card
  wherever it has a figure and the slab elsewhere (yarn dyed below 500 m, prints and piece dyed below
  1,000 m, where the card takes no orders).
- **Proposed, in the draft, not applied:** keep the card's bands and re-set the slabs to what the
  card leaves unexplained, then switch the setting to Added. `calibrate.py` measures that remainder
  as 0 points from 1,000 to 3,000 m (the card's discounts explain it) and 7 points below 1,000 m
  (small orders cost more than the card says).

### Calibration draft (`pilot/Proposed_Rate_Changes.xlsx`), not applied

- Order size, added to the card's bands: below 1,000 m +7 points; 1,000 to 3,000 m +0; 3,000 m and above +0.
- Weaving, piece-dyed twill: Rs 0.18 → 0.25 per pick. Piece-dyed satin: Rs 0.22 → 0.29.
- No change proposed for yarn-dyed plain: closing the gap through weaving would need Rs 0.04 per pick.
- Printing: no proposal; the sheet shows the implied charge beside the card.
- Held-back third with the draft: median 4.3% → 1.8%, within 5% / 10% / 20% 24% / 47% / 71% → 27% / 47% / 72%.

## Open

1. Print method for the 222 prints, and a mill cost sheet for one print. Until then the tool
   under-costs prints.
2. Whether stripes and solids are woven with an undyed weft: 560 fabrics.
3. Dobby shaft counts and top beam: not in PLM. The yarn-dyed dobby weaving rate (Rs 0.45 against
   0.32 for twill) may already hold part of the shaft charge.
4. Which mill the card is from, and the reading of its per-end and per-pick figures.
5. Whether a combination finish is the sum of its parts (six placeholder rows).
6. 66 finishes still not recognised: Others 17, ETI Clat 14, ETI + Baby Skin 9, Stain Repellent 8.
7. "Not applicable for 40s quality" is read as warp and weft both 40s single.
8. The draft above awaits a decision.
9. `docs/AZURE_DEPLOY.md` is not in the repository.

## Next steps, in order

1. Done 24 Nov: rate card built in as upcharges; `pilot.py` and `calibrate.py` rerun.
2. Done 24 Nov: weft dyed or undyed input. PLM cannot fill it for stripes and solids.
3. Settle the print method and the cost of the cloth under a print.
4. Check the Amsler and slub 24s yarn rates and the yarn-dyed plain defaults.
5. Map the 66 unrecognised finishes and the "Solid" dye method.
6. Get one or two mill cost sheets (a piece-dyed poplin first) to settle weaving against dyeing.
7. Set mill tier adjustments from the by-supplier gaps.
8. Extend to cotton with stretch, then polyester viscose: yarn rates for blends are the main need.
9. Date the yarn rates so an order is costed on the rates of its month.
10. Dollar purchases and knits.

## Earlier roadmap

1. Calibration set (PO price + spec) — done through PLM.
2. Price basis — confirmed ex-mill.
3. Rate masters — built; partly calibrated.
4. Batch calculator — built (bulk upload, `pilot.py`).
5. Calibrate to within 3–5% — first pass done, not yet at target.
6. Flag gaps by supplier — first view in `pilot/Pilot_Results.xlsx`.
7. Put it in the sourcing platform — not started.
