# Mill rate card

Received 23 November 2026, pasted as text. Mill not yet confirmed ("Arvisilk" suggests Arvind).
All figures are rupees; the "$" signs in the original were cell formatting.

Built into the tool on 24 November 2026 as optional upcharges (sections 2 to 7); see the end of this
page for how each section is used. Section 1 is not used in the calculation.

Unconfirmed, and assumed throughout: which mill the card is from is not known, and the per-end and
per-pick figures are read as the price change for one extra end or pick.

## 1. End and pick

| Item | Rs |
|---|---|
| Cost per end | 0.60 |
| Cost per pick, up to 90 picks | 0.90 |
| Cost per pick, above 90 picks | 1.00 |

## 2. Dobby (Rs per metre)

| Item | Rs |
|---|---|
| Dobby up to 8 shafts | 0 |
| Dobby 9 to 12 shafts | 8 |
| Dobby 13 shafts and above | 10 |
| Dobby top beam, up to 8 shafts | 10 |
| Dobby top beam, 9 to 12 shafts | 18 |
| Dobby top beam, 13 shafts and above | 20 |

## 3. Finish (Rs per metre)

| Finish | Rs |
|---|---|
| ETI | 4 |
| Easy Care | 4 |
| LA | 10 |
| LA + MC / LA + MXL | 30 |
| Immaculate | 35 |
| Peach | 5 |
| Aero | 5 |
| Carbonium | 5 |
| Diamond Peach | 5 |
| Diamer | 5 |
| Apricot Touch | 5 |
| Emerised | 5 |
| Cool Touch | 15 |
| Arvisilk | 5 |
| Silk Protein / Silk touch | 5 |
| Evershine | 9 |
| Prepress | 32 |
| Liquid Cotton | 5 |
| Teflon | 30 (branded and non-branded) |

## 4. Minimum order upcharge

Yarn dyed: minimum 800 m per colour per design.

| Quantity | Upcharge |
|---|---|
| 700 to 799 m | 4% |
| 600 to 699 m | 7% |
| 500 to 599 m | 8% |

Prints: minimum 1,000 m per design; no orders below it.
Piece dyed (solid): minimum 1,000 m per colour; no orders below it.

## 5. Chambray

Dyed weft: Rs 10 per metre.

## 6. Volume discount, at fabric code level

| Quantity | Discount |
|---|---|
| 2,000 to 3,999 m | Rs 2 per metre |
| 4,000 to 6,000 m | Rs 3 per metre |
| Above 6,000 m | Rs 4 per metre |

Not applicable for 40s quality, split deliveries or EOSS.

## 7. Print upcharges

| Method | Rs per metre |
|---|---|
| Rotary print | 18 |
| Digital print | 55 |

## How the tool uses the card

| Section | In the tool | Rate master sheet |
|---|---|---|
| 1. End and pick | Not used. Kept for comparison with the tool's own cost of one end or pick | none |
| 2. Dobby | Drop-downs "Dobby shafts" and "Top beam". The six figures are shafts (0, 8, 10) plus top beam (10) | `Dobby_Charges` |
| 3. Finish | The "Finish" drop-down. Finishing per kg stays at the Normal rate; the named finish adds the card's Rs per metre | `Finishing_Rates`, column "Upcharge Rs per metre" |
| 4. Minimum order upcharge | Drop-down "Rate card quantity", bands 500 to 799 m, yarn dyed only | `Quantity_Terms` |
| 5. Chambray | Drop-down "Weft (yarn dyed)": Dyed, Undyed, or "Chambray, dyed weft" at Rs 10 per metre in place of the per-kg dyeing | `Weft_Options` |
| 6. Volume discount | Drop-down "Rate card quantity", bands from 2,000 m. No discount when warp and weft are both 40s | `Quantity_Terms` |
| 7. Print upcharges | Drop-down "Print method". Replaces the single printing rate per kg; the cloth still carries preparation at the RFD rate (a placeholder) | `Print_Methods`, `Piece_Dyeing` |

Rules that follow from the card:

- Every item is rupees per metre on the price and is not marked up. The small-lot percentage is taken
  on the whole price.
- A rate card quantity band takes the place of the order size slab (Settings: "Order size slabs with
  rate card quantity" = Replaced). The slabs were measured from purchase orders without the card and
  already hold whatever small-lot premium and volume discount the mills gave, so charging both would
  count quantity twice.
- Combinations the card does not price as one item (LA + ETI, LA + Easy Care, LA + Arvisilk,
  LA + Peach, LA + Silk Protein, LA + MC + Silk Protein) are the sum of their parts and are marked
  Placeholder.
- "Not applicable for 40s quality" is read as warp and weft both 40s single. Split deliveries and
  EOSS cannot be seen by the tool; leave the band at 800 to 1,999 m for those.
- The card takes no print or piece-dyed order below 1,000 m, so it has no price for one. Use the
  order size slab for those.
