# RightPrice: progress and handover

As of 25 November 2026. **Start with "Handover" below**; the sections after it are the record of
how the tool got here, oldest first.

## Handover, 25 November 2026

**The aim of the tool is a better negotiation with the vendor.** Every screen is judged by whether
it helps a fabric buyer walk into a meeting with a mill better prepared.

### Where things stand

- Everything built is merged to `main` (pull requests 1 to 8) and deployed; the last deploy run was
  green. Nothing is waiting to be merged except this handover note.
- Live site: `https://rightprice-bnf2bwbga8bga6eb.indiasouthcentral-01.azurewebsites.net`, behind
  Microsoft sign-in. A build session cannot sign in, so the owner confirms the live site by eye.
  The owner last confirmed it working before pull requests 5 to 8.
- `python check_engine.py` and `python check_server.py` both print ALL OK. The seven V1 qualities
  match to the paisa (Qlty-1 = Rs 181.40).

### What the tool is now

| Part | What it does |
|---|---|
| `engine.py`, `masters.py` | The costing. Unchanged method; the rate master workbook is the source of every rate |
| `server.py` (FastAPI) + `web/` | The screens: hand-built HTML, CSS and JavaScript, no build step, no database |
| `app.py` (Streamlit) | The earlier screens, kept at `/classic` as a fallback |
| `mill_sheet.py` | Reads a mill's price sheet (base price plus upcharges), costs each row, checks the mill's sums |
| `rate_card.py`, `yarn_seed.py` | The mill rate card tables; placeholder yarns for poly cotton and linen |
| `pilot.py`, `calibrate.py` | Should-cost against purchase orders; a calibration draft that is never applied automatically |

Screens: Dashboard (yarn what-if, five panels from own data), Cost a fabric (numbered steps, live
cost, five chart views, yarn what-if, negotiation brief, print), Bulk upload and list (mill sheet or
template, one list with should-cost, gap, money at stake, what to do, mill's sums), Compare, Yarn
prices, Cotton prices, Bring in prices, Rate tables, Mill rate card, Settings, Pilot results.

### Rules that have held throughout

1. Work on a branch and open a pull request. Never push to `main`: every push there redeploys.
2. `data/Rate_Master.xlsx` is the source of truth for rates. Never run `build_masters.py --force`.
   Save a dated backup before any script changes it. **Never change a rate without being asked.**
3. Run `python check_engine.py` and `python check_server.py` after changes; both must print ALL OK.
4. A rate with no data behind it gets the Basis "Placeholder" so the app warns.
5. Calibration proposals are drafts for review; nothing from `pilot/Proposed_Rate_Changes.xlsx` is
   applied without the owner's word.
6. Merge when the pull request's "checks" job passes; then confirm the deploy run is green. If the
   live site goes down, revert the merge (or set the Azure app setting `RIGHTPRICE_UI` = `classic`).
7. After building screens, run a cold review ("elephant and goldfish"): a fresh reviewer that has
   not seen the code uses the running app and reports what would trip up or mislead a buyer. Fix
   what it finds before, or straight after, merging. Eight rounds so far (two on the fixes of the sixth); each found real problems.
8. The live server keeps its own rate master in `/home/rightprice-data`. New tables reach it only
   through `masters.load()` (`_add_missing_tables`), which saves a dated copy first.
9. Report plainly: what was checked, what was not, and anything that did not improve.

### Sixth cold review: the negotiation brief (fixed 25 Nov, pull request 10)

All ten findings were fixed and two further cold reviews were run on the fixes; each found more,
and those were fixed too. What the brief does now:

- **"In line" comes from the fabric type's fit**, not a fixed 5%: the middle half of past purchases
  of that type against should-cost (dashboard panel 1 shows it), kept between 5% and 10% either way.
  Without purchase history, 5% either way. Constants `BAND_MIN`, `BAND_MAX` in `server.py`.
  **The 5% floor and 10% cap are the build session's choice; the owner may want other figures.**
- **Opening figure** for a Push: as far below the top of the range as the quote is above it, never
  below the should-cost, so it moves smoothly with the quote. Aim: the top of the range.
- A placeholder blocks the target only when more than 10% of the price rests on it
  (`PLACEHOLDER_SHARE_LIMIT`); otherwise a caveat says whether it could change the advice.
- Placeholders are never quoted as "not X". Weaving to 3 decimals, margin to 1, each "about".
- Quotes below the range are "a saving, if the specification holds"; more than 30% below is
  "Check the quote first" and counts no saving; a quote of zero is ignored with a warning.
- At stake = printed gap x quantity; negative quantity refused; yarn moves limited to 50%.
- Quantity outside the band the cost uses: "Set the quantity first", with a button, but only when
  the band would change the cost.
- A list row's notes travel into its brief; a list yarn move travels onto the sliders, and the
  brief and headline follow them.
- Comparisons on printed figures; the list total is split by stance and never nets savings off.

Not fixed: the description does not follow a weave change (the title still says "Dobby" after
the weave is changed); the list and panel 1 still scroll sideways on a phone (see "Next to build" 6).

### Negotiation pack (25 Nov, pull request 11)

One printable page (A4 landscape, about 20 rows) for a whole mill sheet, one upload, or the rows
ticked on the list: totals counted on Push and in-line rows only (rows the tool is unsure of shown
apart), "lead with" the money above the usual range, every row with open and aim prices, the mill's
own sums done again (`mill_sheet.own_sums`), questions per row (the whole gap and what would explain
it, a missing volume discount from 2,000 m except on 40s, the second yarn, an unknown finish), and
rows not costed. A row repeating an order is counted once. With a yarn move on the list every figure
follows it. Two cold reviews; the second's last three points (duplicates, uploads, a Push only paise
over its range) were fixed after it and checked by `check_server.py`, not by a third reviewer.

### Right cost (25 Nov, night, pull request 12)

`/rightcost`: every costing in one list page laid out after the company PLM list screens (design
tokens measured at 1366x768), asked for by GP on 25 Nov. Lists the 1,696 purchase-order costings and
the fabric list; "Against Range" is the brief's verdict on today's rates for every row (worked out in
the background, about 20 s, kept until the rate master changes). The "+" opens Cost a fabric in a
popup. Search, filters, saved searches, sort, list and card views, column chooser, selection bar,
detail pages with their own address, Library setup lists, light and dark. Status, Remarks, saved
searches and Library lists are kept in each browser (GP's choice). GP's answers to the questions are
in `docs/QUESTIONS_FOR_GP.md`. Two cold reviews; the second's findings were fixed after it and checked
in the browser by the build session, not by a third reviewer.

Known and left: Cost a fabric calls a purchase-order price a "quote" when one is opened from Right
cost; supplier names are cut short in the purchase-order data itself ("Rajapalayam Mills Limite").

### One shell for every screen (26 Nov, asked by GP)

The app now opens in the shell first built for Right cost, restyled in its own look (forest-green
rail with labelled icons, warm paper background, saffron for the one button to press, Manrope, pill
tabs), deliberately unlike the PLM it was modelled on. Rail: Home (Dashboard | Pilot results), Right
cost, Prices (market prices, rate master and settings, costing and sourcing setup lists). "New cost"
opens a popup with Create cost, Bulk upload, Compare and Negotiation pack as tabs; the list's ⋮ menu
has Download Excel and those four. Light or dark and settings sit under the user icon. The earlier
screens are shown inside the shell in an embedded frame with the shell's palette; a page there that
asks for a costing screen opens the popup instead. `/rightcost` now leads to `/#rightcost`.

### Mill cost sheets (26 Nov, pull request 16)

Prices > Mill cost sheets. A mill fills one row per fabric in the template (its yarn, sizing, weaving,
dyeing and finishing rates, wastage, overhead, margin and price). Each row is set beside the rate
master with each rate's basis, and the should-cost is worked again on the mill's own figures against
its price. Where the figures differ from the rate master, a draft change is made (the median of the
mills' figures for that rate, with the sheets behind it). Nothing changes until GP ticks drafts and
presses Apply (asked twice); the rate master is copied with the date first, and the new rate's Basis
names the mills. A wastage, overhead or margin for a route and weave the rate master has no row for
adds that row (today such fabrics fall back to the placeholder Default row). `costsheet.py`.

### Negotiation tracker (26 Nov)

GP asked on 26 Nov for five builds in order: the negotiation tracker, a supplier page, quote alerts, email
drafting with the Claude API, and an MCP server so an AI assistant can use RightPrice.

The tracker: on each fabric's Negotiation tab in Right cost, record each step (the mill's quote, our
counter, a revised quote, the agreed price) with date and note. It shows where it stands, what was won
against the first quote (per metre and on the metres), and where the price ended against should-cost.
A "Negotiation" column in Right cost, and a "Won in negotiation" panel on the Dashboard by mill. Kept on
the server (`negotiations.json` beside the rate master), so everyone sees the same steps.

### Waiting on the owner

1. Real yarn rates for poly cotton and linen (six placeholders are in the yarn master).
2. A current quote for Amsler 24s yarn, to settle why yarn-dyed plain is over-costed by 10%.
3. A decision on the calibration draft (order size below 1,000 m +5.5 points on top of the card's
   bands; piece-dyed twill Rs 0.18 to 0.25 a pick; piece-dyed satin Rs 0.22 to 0.29; printing
   Rs 390 to 410 a kilo).
4. Print method for printed fabrics, and a mill cost sheet for one print.
5. The Scribd fabric costing document as pasted text or a PDF (the site could not be opened).
6. Mill cost sheets for real wastage, overhead and margin (GP will send them, 25 Nov): 67% of the
   purchase-order costings are "ask break-up" mostly because those rates are placeholders.
7. Price sheets from mills other than Arvind: `mill_sheet.py` checks sums against Arvind's
   Rs 0.60 an end and Rs 0.90 a pick.

### Next to build, in the owner's order unless told otherwise

1. Done 25 Nov: the ten findings of the sixth cold review (pull request 10).
2. Done 25 Nov: the negotiation pack (pull request 11).
3. Done 25 Nov (pull request 13): mill sheet rows in poly cotton and linen are read (on the
   placeholder yarns, and said so); the per-end, per-pick and C2FO figures are per mill in the rate
   master sheet `Mill_Sheet_Terms` (Arvind's from the card; a sheet from a mill not in it is checked on
   its additions only, and says so). Base price stays per row: it is on each row of the mill's sheet.
4. Date the yarn rates, so an order is costed on the rates of its month and panel 3 of the
   dashboard can show fabric cost by year.
5. The 265 purchase-order fabrics still not costed (two yarns in one direction).
6. Should-cost pinned beside the fabric code on a phone in the list.

### Where the tool is weak (do not push a vendor on these)

- Yarn-dyed plain in Amsler or slub yarn: over-costed by about 10%.
- Printed twill and plain: over-costed by 7% and 22%. Yarn-dyed jacquard: under-costed by 47%.
- Poly cotton and linen: placeholder yarn rates and cotton's process rates.
- 48 placeholder rates, mostly finishes.
- Overall fit on 1,696 purchases: median gap 1.0%; 31% / 54% / 79% within 5% / 10% / 20%.

## Summary before the handover

Version 1 is built, calibrated once against purchase orders, and running. The mill rate card is
built in as optional upcharges. It is not yet inside the 3–5% accuracy target.

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
| Platform | Streamlit until 24 Nov 2026; from then a hand-built front end over the same engine, still no database |
| Yarn price intake | Excel/CSV, PDF, image, web link or API, all ending in a review table |

## What is built

- Costing engine that reproduces all seven V1 qualities exactly (Qlty-1 = Rs 181.40/m).
- Seven-screen app, bulk upload template, cost sheet download.
- Rate master with 20 sheets; every rate carries its basis. 48 are placeholders, six of them the new blend yarns.
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
2. **Printed twill and plain are over-costed** (−7% and −22%) on the rate per kg. The card's rotary
   and digital charges are optional and do not fix it. See "What did not improve".
3. **Yarn-dyed jacquard is under-costed by 42%**; too few fabrics to set a rate.
4. **Fabrics in 2/100 yarn are bought at about double the should-cost** (23 fabrics); the spec is
   probably missing a premium cotton or finish.
5. **Rajapalayam sits 8% below should-cost** across 289 fabrics while Arvind, NSL and Vardhman are within 4%.
   Mill tier is still set to zero.
6. **48 placeholder rates remain**, mostly finishes; six are the poly cotton and linen yarns added on 24 Nov. Four yarn rates are placeholders: Cotton 20S and
   Slub 20S, 24S, 30S.
7. **44 fabrics have a finish the tool does not recognise** (303 at the start) and are costed as Normal.
8. **265 cotton fabrics are not costed** because one direction mixes yarns ("40s + 40s melange") or
   the count cannot be read. 328 before the count fix of 24 Nov.
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
- **Printing keeps the calibrated Rs 390 per kg by default.** Print method is optional: only when
  Rotary or Digital is chosen does the card's Rs per metre take the place of the per-kg rate, and
  the cloth then carries preparation at the RFD rate (Rs 60 per kg, a placeholder). A first version
  made rotary the default; that under-costed every print by 10% to 35% and was withdrawn.
- Every card item is added to the price and not marked up. Each is its own second-level line in a new
  bucket, "Upcharges and quantity terms".
- Defaults charge nothing. `check_engine.py` prints ALL OK: the seven V1 qualities match to the paisa,
  and 22 further checks confirm each card item adds what the card says.
- Order size and the card's quantity terms are reconciled by using one or the other, never both
  (see "Quantity" below).
- The live server keeps its own rate master. The app adds the rate card tables to it the first time
  it opens after the merge, after saving a dated backup beside it; every rate on the server,
  including the printing rate, is kept. Tested against a copy of the pre-rate-card master with one
  edited rate.

### What the pilot could and could not set from PLM

| Input | Set from data? | How |
|---|---|---|
| Finish | Yes | PLM finish name. Unrecognised finishes fell from 303 to 66 |
| Rate card quantity | Yes | Metres of the fabric code across all orders, 1 Aug to 23 Nov. Not the size of one order, and split deliveries cannot be told apart |
| Weft (yarn dyed) | Partly | 357 checks and horizontal stripes: dyed. 5 chambrays: undyed, by definition. **560 stripes, solids and textures: PLM does not say; left as dyed** |
| Print method | **No** | Not in PLM. None is set, so all 219 prints stay on the printing rate per kg |
| Dobby shafts, top beam | **No** | Not in PLM. All 394 dobbies left at no charge |

### Results

1,582 fabrics, held-back third 517. Gap is purchase price above should-cost.

| | Before | After |
|---|---|---|
| All: median gap | −0.5% | 1.5% |
| All: within 5% / 10% / 20% | 28% / 48% / 79% | 30% / 53% / 79% |
| Held-back: median gap | −1.5% | 0.7% |
| Held-back: within 5% / 10% / 20% | 27% / 47% / 78% | 27% / 51% / 77% |

The known over-costed groups:

| Type | Fabrics | Median gap before → after | Within 5% | Within 10% | Within 20% |
|---|---|---|---|---|---|
| Yarn-dyed plain | 220 | −13.9% → −10.4% | 7% → 14% | 19% → 38% | 86% → 90% |
| Yarn-dyed plain, held-back | 71 | −13.9% → −10.4% | 6% → 16% | 20% → 35% | 86% → 90% |
| Printed twill | 64 | −6.1% → −7.0% | 0% → 0% | 9% → 13% | 50% → 53% |
| Printed twill, held-back | 20 | −10.4% → −10.5% | 0% → 0% | 5% → 5% | 55% → 55% |
| Printed plain | 23 | −22.3% → −22.3% | 39% → 26% | 39% → 39% | 43% → 43% |
| Printed plain, held-back | 10 | −25.6% → −25.0% | 20% → 10% | 20% → 20% | 30% → 30% |

Other types, all fabrics, median gap and share within 10%: yarn-dyed dobby −1.7% → 1.4%, 47% → 58%;
yarn-dyed twill −0.2% → 3.1%, 70% → 70%; yarn-dyed oxford −2.6% → −0.7%, 46% → 39%;
piece-dyed plain 0.2% → 2.0%, 67% → 72%; piece-dyed twill 4.3% → 5.2%, 52% → 52%;
piece-dyed satin 3.1% → 5.1%, 57% → 57%; printed satin 0.1% → 0.1%, 75% → 70%.

Step by step (sheet "Rate card steps" in `pilot/Pilot_Results.xlsx`), all fabrics:

| Inputs | Median gap | Within 10% | Within 20% |
|---|---|---|---|
| Before | −0.5% | 48% | 79% |
| Finishes from the card | −0.5% | 50% | 80% |
| ...and weft from the PLM pattern | −0.5% | 50% | 80% |
| ...and rate card quantity in place of slabs (the result) | 1.5% | 53% | 79% |
| What if every print were rotary | 3.1% | 49% | 72% |
| What if every print were digital | 2.3% | 50% | 79% |
| What if weft were undyed wherever PLM does not say | 3.5% | 52% | 75% |

### What did not improve

1. **Printed twill and plain are still over-costed** (−7% and −22%), as before the rate card. The
   card's print charges are not the fix as they stand: with every print on rotary all print types
   become under-costed by 10% to 35% (twill 27%, satin 35%), and with every print on digital twill
   fits (3.2%) but satin does not. Either the cloth under a print is costed too low when the card's
   method is used (preparation is a Rs 60 per kg placeholder), or these prints are priced above the card.
2. **Yarn-dyed plain is still over-costed by 10%.** The weft input did almost nothing, because the
   over-costing is the same on checks, where the weft is certainly dyed, as on stripes. Of the 220
   fabrics, 175 are Amsler 24s or slub 24s from two mills. The gain that did come was from quantity
   bands and finishes. The Amsler and slub yarn rates, and the higher wastage, overhead and margin
   given to yarn-dyed plain (5%, 5%, 8% against 3%, 4%, 7% for twill), are the next places to look.
3. **Yarn-dyed oxford** within 10% fell from 46% to 39% although its median improved.
4. **Yarn-dyed twill** median moved from −0.2% to 3.1% and its share within 5% fell from 46% to 35%.
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
- Printing: Rs 390 → 395 per kg, in effect no change.
- No change proposed for yarn-dyed plain: closing the gap through weaving would need Rs 0.04 per pick.
- Held-back third with the draft: median 0.7% → −1.6%, within 5% / 10% / 20% 27% / 51% / 77% → 29% / 51% / 78%.

## Open

1. Print method for the 219 prints, and a mill cost sheet for one print, before Rotary or Digital
   is used as a matter of course.
2. Whether stripes and solids are woven with an undyed weft: 560 fabrics.
3. Dobby shaft counts and top beam: not in PLM. The yarn-dyed dobby weaving rate (Rs 0.45 against
   0.32 for twill) may already hold part of the shaft charge.
4. Settled 25 Nov: the card is Arvind's, and per-end and per-pick are the price change for one end or pick.
5. Whether a combination finish is the sum of its parts (six placeholder rows).
6. 66 finishes still not recognised: Others 17, ETI Clat 14, ETI + Baby Skin 9, Stain Repellent 8.
7. "Not applicable for 40s quality" is read as warp and weft both 40s single.
8. The draft above awaits a decision.

## Pilot coverage, 24 Nov 2026 (after the rate card)

Three changes to how `pilot.py` reads PLM, none to any rate:

- **Yarn counts written "40/1", "(40/1)", "30/1s", "60comp" are now read.** A corrupted character in
  the script had been dropping every "40/1" fabric.
- **Dye method "Solid" with a solid pattern is read as piece dyed** (50 fabrics), as the mill rate
  card words it. This is an assumption. "Solid" with a print pattern (6) is still left out.
- **ETI Clat, ETI + Baby Skin and ETI + Silver Nano are costed as ETI.** Unrecognised finishes: 66 → 44.

Fabrics costed rose from 1,582 to 1,696. The 114 new fabrics had no part in any calibration, and
they fit better than the rest: median gap −1.8%, 54% within 5%, 70% within 10%, 91% within 20%.

| | 1,582 fabrics | 1,696 fabrics |
|---|---|---|
| All: median gap | 1.5% | 1.0% |
| All: within 5% / 10% / 20% | 30% / 53% / 79% | 31% / 54% / 79% |
| Held-back third: median gap | 0.7% | −0.4% |
| Held-back third: within 5% / 10% / 20% | 27% / 51% / 77% | 28% / 52% / 78% |

Still not costed: 265 with a yarn count the tool cannot read (mostly two yarns in one direction,
"40s + 40s melange"), 53 with no plausible width, 15 with no EPI or PPI, 8 with an unmapped dye method.

Calibration draft, rerun, not applied: order size below 1,000 m +5.5 points on top of the card's
bands (was +7); piece-dyed twill Rs 0.18 → 0.25 per pick and satin 0.22 → 0.29 as before; printing
Rs 390 → 410 per kg. Held-back third with the draft: median −1.6%, within 5% / 10% / 20% 30% / 54% / 79%.

### Yarn-dyed plain: what would close the 10% gap

223 fabrics, 175 of them Amsler 24s or slub 24s, from Arvind (−9.8%) and Rajapalayam (−12.3%).
Three what-ifs, each on its own, nothing applied:

| What if | Median gap | Within 10% |
|---|---|---|
| As it stands | −10.4% | 39% |
| Yarn-dyed plain given twill's wastage, overhead and margin (3%, 4%, 7% in place of 5%, 5%, 8%) | −6.1% | 78% |
| Amsler and slub 24s priced as plain 24s (Rs 315 in place of 372) | −2.7% | 77% |
| Both | 1.9% | 77% |
| Weaving at Rs 0.20 per pick in place of 0.32 | −6.2% | 77% |

With everything else held, the purchase prices imply an Amsler or slub 24s yarn rate of about
Rs 298 per kg (middle half Rs 285 to 316), against Rs 372 in the yarn master. The purchase data
cannot tell these explanations apart: each one alone lifts the share within 10% to about 78%. A
current quote for Amsler 24s yarn would settle it, and it is the cheapest thing to get.

## New front end (started 24 Nov 2026)

The "no new web stack" rule was lifted by decision on 24 Nov 2026. The costing engine, the rate
master and every rate are untouched; only the screens changed.

**Stage 1, built:**

- `server.py` (FastAPI) serves a hand-built front end in `web/`, styled after the FarmTicker site:
  dark navy with a green accent, plus a light version, switched in the header.
- Left panel grouped under Costing, Prices, Rates, Analysis; each page has its own address
  (`#cost`, `#rates/Weaving_Rates`, and so on).
- Cost a fabric: live costing as choices change, and a waterfall from yarn to the final price with
  a switch between cost groups and every sub-cost. A group opens into its sub-costs on a click.
- Dashboard cards, header search, phone layout, bulk upload, read-only prices, rate tables, mill
  rate card, settings and pilot results.
- The earlier Streamlit screens run beside it at `/classic`, so rates can still be edited.
- `check_server.py` confirms the server returns the engine's numbers (Qlty-1 = Rs 181.40).
- Reviewed cold by a separate reviewer that saw only the running screens (the "elephant and
  goldfish" method); its findings and what was done about each are in the pull request.

**Stage 1 is live** (confirmed on the Azure site, 24 Nov 2026).

**Stage 2, built and merged 24 Nov 2026:**

- Every rate table, the mill rate card tables, the yarn master, the market reference and the
  settings are edited in place. The server refuses text in a number column, a duplicate key, and
  any change after which the example fabric can no longer be costed. The first change of each day
  keeps `Rate_Master backup <date>.xlsx` beside the rate master.
- Cotton prices can be added. "Bring in prices" rebuilds the yarn price intake: Excel, CSV, PDF,
  picture, web page or price service, ending in a review table.
- `/classic` is kept as a fallback only.

**Cost a fabric, redesigned 24 Nov 2026:**

- Numbered steps on the left: fabric content, how it is coloured, yarn, dyeing, weave and
  construction, finish, name and compare. Each step shows only what the earlier choices call for:
  yarn dyeing shades for yarn dyed, a piece shade for piece dyed, a print method for printed,
  nothing for bleached. Finished steps fold to a one-line summary. The cost is on the right and
  updates as choices change; on a desktop the page fits one screen.
- Chart views: bars (the default, one bar per group from zero), waterfall, pie, treemap and line,
  each by cost group or by every sub-cost.
- Fabric content is 100% cotton, poly cotton or linen and filters the yarn list. It is not a cost
  driver in the engine.

**Poly cotton and linen are provisional.** Six yarn rates were added as placeholders
(`yarn_seed.py`): poly cotton 65/35 30s, 40s, 45s at Rs 215, 235, 245 per kg; linen 25, 40, 60 lea at
Rs 750, 900, 1,200. They are guesses, not market figures. Weaving, sizing, dyeing and finishing
rates for those fabrics are the ones measured on 100% cotton. None of this has been checked against
a purchase price.

**Added 24 Nov 2026, evening:**

- A saved costing keeps the choices behind it. From the dashboard it can be opened again in Cost a
  fabric, where it is re-costed on the rates of the day, or deleted.
- The cost view warns when what was typed looks like a slip: width outside 30 to 130 inches, EPI or
  PPI outside 20 to 400, reed space narrower than the cloth or more than 35% wider, weight outside
  40 to 600 g/m2. The cost is still shown.
- `.github/workflows/checks.yml` runs `check_engine.py`, `check_server.py` and a parse of the front
  end script on every pull request. It deploys nothing.

**Room on the screen, and use from a phone (24 Nov 2026, night):**

- The left panel folds to a strip of icons and opens when the pointer or the keyboard reaches it. A
  pin keeps it open. The header and headings are compact. Both are switches under Settings >
  Display and are remembered per device. Pages use the full width.
- On Cost a fabric the heading row is gone; "New fabric" and "Load the example" sit at the top of
  the steps. The example now fits one screen at 1440x900 with nothing scrolled.
- Bars and pie list costs largest first, with a switch back to the order the price is built in.
  Waterfall and line always keep the build order.
- The site can be added to a phone's home screen (web app manifest and icons) and then opens full
  screen from its own icon. It still needs the internet and the sign-in; nothing is kept offline.
- After a deploy the browser now fetches the new screens by itself; no hard refresh.

**Four additions asked for on 24 Nov 2026 (night):**

- **Count systems.** In the yarn step a count can be typed in Ne, Nm, tex, denier, linen lea or
  worsted count. It changes the weight of yarn in the cloth; the rate per kg stays the yarn's. The
  bulk template has the same three columns. This is a typed input beyond EPI, PPI, width and reed
  space, added on request.
- **Compare**, a page of its own under Costing: two saved costings (or the fabric open on Cost a
  fabric) side by side on today's rates, with every group and sub-cost, the difference, a sentence
  naming the three largest differences, and the choices that differ.
- **What has moved.** A saved costing keeps its cost and the rates it used. Opened again, it shows
  what it cost then, what it costs now, and each rate that changed.
- **Print.** A Print button lays the result out for paper or PDF: light colours, inputs and menus
  left off, every table opened, dated.

The four additions had their own cold review after they went live; seven problems were found and
fixed the same night. The ones that could have misled a buyer: Compare kept showing the previous
pair when the same costing was chosen on both sides; a typed count showed nowhere near the price;
changing the count system re-read "40" as 40 tex; and Compare's number columns were off-screen on a
phone. Compare now also warns when the two costings are different fabrics, and shows the two quotes
on their own rows.

**Dashboard, fabric list and yarn what-if (25 Nov 2026):**

- **The mill rate card is Arvind's, and the reading of it is confirmed.** The price sheet sent on
  25 Nov ("AS Sweetan": Allen Solly orders with an Arvind reference) prices 40s yarn-dyed twill at a
  base of Rs 164 for 122 x 76, plus Rs 0.60 for each extra end and Rs 0.90 for each extra pick. That
  is the card's section 1, read as the price change for one end or pick. The sheet also shows no
  volume discount on 40s quality at 2,255 to 3,244 m, as the card says.
- **Bulk upload takes a mill's price sheet as it comes** (41 headings, `mill_sheet.py`), as well as
  the RightPrice template. Each row is turned into the tool's choices and costed. On the six rows
  sent, the mill's price is 4.8% to 7.0% above should-cost.
- **One fabric list** replaces saved costings. It sits under Bulk upload, in the mill sheet's
  headings, with should-cost, the mill's price, the gap, and a check that the mill's own sums add up
  (base plus upcharges equals price; upcharge equals difference times the rate; quantity terms;
  C2FO). Rows are ticked to open, compare (two) or remove; the header box selects every row shown.
  "Add to list" on Cost a fabric adds one fabric; opening a row and pressing "Update in list" changes
  it in place. Compare and "what has moved" now work from the list.
- **NYD rows are not guessed.** They are listed with the reason and costed once opened and given a
  route.
- **Yarn what-if.** On Cost a fabric, two sliders move the warp and weft yarn rate and show the new
  price. On the list, a yarn and a percentage re-cost every row. On the dashboard, the same for the
  reference fabric and the list average. Nothing is saved and no rate changes. The cost view also
  states the rupees per metre for each Rs 10 a kilo on warp and weft.
- **Dashboard rebuilt from own data**: (1) price paid and should-cost by fabric type, (2) share of
  each cost group by route, (3) cotton price by year 2022 to 2026, (4) nine questions to ask before a
  negotiation, answered with the buyer's own figures, (5) supplier cost ratios and each supplier's
  gap to should-cost. Saved-costing cards are gone.
- **Not used:** the figures on the web page sent as a reference (a software vendor's article, in
  dollars, unsourced: 100% cotton at $5.40 a metre, more than double the prices paid here). Its three
  panel ideas and its question list were the pattern; the numbers are the buyer's own.
- **Panel 3 is cotton only.** Yarn rates in the tool are of one date, so a fabric cost per metre for
  earlier years cannot be drawn. Dating the yarn rates (next steps) would allow it.
- **Left panel:** the name at the top no longer scrolls out of view in a short window.

**The aim of the tool is a better negotiation with the vendor** (stated 25 Nov 2026). Added for that:

- **A negotiation brief** on Cost a fabric whenever a quote is entered, and one word per row in the
  list (Push, Fair, Below, Ask break-up). It gives the price to open at (the should-cost), the level
  up to which the difference is within the tool's 5% margin of error, and what would have to be true
  for the quote to be right: the yarn rate, the weaving rate per pick, or the mill's margin that
  alone would close the gap. With an order quantity it gives the money at stake.
- **No target where the tool is weak.** If placeholder rates are used, or the tool fits fewer than
  half of past purchases of that fabric type within 10% (or its middle gap is over 6%), the brief
  says to ask for the break-up first and gives the reason. The same rule decides colour everywhere:
  a gap on such a group is marked "tool unsure", never red or green.
- **Money at stake in the list**: gap per metre times order quantity for each row, a total for the
  sheet, and "most at stake first".

A fifth cold review covered the dashboard and the list; fourteen findings, all acted on. The ones
that could have misled a buyer: a yarn move changed the should-cost but left the old gap on screen;
panel 1 showed a gap that did not follow from the two prices beside it (now all three are averages
over the metres bought); green and red sat on fabric types where the tool is known to be weak; a
should-cost carried a small-lot upcharge the mill's sheet did not charge; and the same sheet could
be uploaded twice.

`PER_END`, `PER_PICK` and the C2FO factor in `mill_sheet.py` are the card's figures, used only to
check a mill's sheet. They are not costing rates and are not in the rate master.

**Read but not built: `inputs/Fabric Costing_Final.xlsx`** (the earlier prototype, sent again on
24 Nov). Its rates are placeholders (most cells are 1 or 10), so only its logic is of use. What it
has that RightPrice does not:

| In the workbook | In RightPrice today | Worth building? |
|---|---|---|
| Yarn price from a fibre blend (% of each fibre x fibre price) plus spinning stages | Yarn rate looked up per yarn | Only if fibre prices are tracked; a bought-yarn rate is firmer |
| Count systems: Ne, Nm, Tex, Denier, Worsted, Lea | Built 24 Nov: all six can be typed | Done |
| Weaving cost from the loom: speed x weave speed factor x efficiency, against loom cost per hour | A rate per pick by weave and route, calibrated on purchase orders | As a cross-check beside the calibrated rate, once real loom costs per hour are known |
| Shaft count as a multiplier on weaving | Rate card shaft charge in Rs per metre | Already covered |
| Sizing as pick-up % x size cost per kg | A rate per kg of warp | Same result; no change needed |
| Process loss % on dyeing and on finishing separately | One process wastage % | Not without data |
| Overheads as named lines (electricity, rent, utilities, maintenance), packing, shipping, marketing | One overhead % and one margin % | Not for an ex-mill should-cost |
| GSM = (EPI / warp count + PPI / weft count) x 25.64 | Weight worked out from the yarn in the cloth | Same idea; the tool's is the fuller version |
| Minimum order quantity noted, not calculated | Order size slabs and rate card quantity bands | Already covered |

The Scribd document linked from that workbook could not be opened from the build session.

**Open on the front end:**

1. Real yarn rates for poly cotton and linen, and process rates for those fabrics.
2. The web page and price service routes of the intake were not tried against a real site.
3. Several people editing rates at the same moment: the last save wins.

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
