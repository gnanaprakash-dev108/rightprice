# The calibration's held-back test, split fairly (stage 5, 27 Nov 2026; re-run after the cold review)

**Nothing was applied and no rate changed.** `pilot/Proposed_Rate_Changes.xlsx` is untouched. The figures below come from
`python calibrate_splits.py`, which writes `pilot/Held_Back_Splits.xlsx` (every table in full).

## In one line

**On cloth the draft was not fitted on, it shows no measurable gain.** On the construction split and the main time split
the change in the share of fabrics within 10% of the price paid is about one point, with a 95% interval that runs from a
loss of several points to a gain of several. On November alone (135 fabrics) the change is larger, +5.9 points (+13.5 on
its unseen constructions), but its interval is wide (−1.7 to +16.7; −7.3 to +32.3 on the unseen ones), so it shows no
measurable gain either. Some kinds of cloth get clearly worse with the draft, and several of its proposals change with
the split. On this evidence the draft should not be applied.

## Why it was re-run

The calibration draft holds back a third of the 1,696 costed purchase-order fabrics by a rule on the fabric code, and is
tested on them. But the 1,696 are only 433 constructions: the same cloth under several codes. With that split **481 of
the 552 tested fabrics (87%) have their construction among the fabrics the draft was fitted on** (188 constructions on
both sides).

So the same draft (order size added to the rate card's bands, weaving per route and weave group, one printing rate) was
worked out again on fairer splits and tested on what each held back:

- **By construction**: a third of the constructions held back, so the same construction is never on both sides. A
  construction is the nine fields of a Fab group (content, route, weave, warp, weft, EPI, PPI, finished width, finish),
  tidied and joined by `construction.py`. **Stage 2's Fab groups are not merged yet; this small function stands in for
  them and can be replaced by stage 2's signature.** Caveat: 58 of the 151 tested constructions differ from a fitted one
  only in width, finish, or EPI and PPI within 3% (same yarns, route and weave), so "cloth it has not seen" holds with
  that caveat; the result without them is given too.
- **By time**: each purchase-order line on the side of its own date. A code bought in August or September and again in
  October or November is a fit fabric (its earlier lines, at their weighted average price) and a tested fabric (its later
  lines), as it would be in use. (The first version of this test put a code's whole price on the side of its order month:
  163 of the 1,247 fit codes then carried October and November lines, 12% of the fit metres, and 40 of the 449 tested
  codes carried August and September lines. The cold review found this; it is fixed.)
- **By time, last month only**: fitted on August to October lines, tested on November lines (135 fabrics: a second look).

## The held-back fabrics

Gap = price paid above should-cost. "Today" is the tool as it stands; "draft" adds the draft's proposals. "Gained" and
"lost": tested fabrics that come within 10% with the draft, and those that drop out of 10% with it. The interval comes
from 4,000 bootstrap draws that resample whole tested constructions (so a cloth bought under many codes counts once).

| Split | Tested | Within 10%: today → draft | Gained / lost | Change, 95% interval | Within 5% | Within 20% |
|---|---|---|---|---|---|---|
| By fabric code (the draft's own) | 552 | 52.4% → 53.6% | 20 / 13 | +1.3 (−1.8 to +4.1) | 28.4% → 30.1% | 78.1% → 78.6% |
| **By construction** | 531 | 48.6% → 49.7% | 29 / 23 | **+1.1 (−4.7 to +8.4)** | **24.3% → 23.0%** | 79.3% → 79.1% |
| ...without the 58 near constructions | 254 | | | −0.8 (−8.4 to +7.3) | | |
| **By time: fit Aug–Sep, test Oct–Nov** | 612 | 49.8% → 51.1% | 24 / 16 | **+1.3 (−2.1 to +4.9)** | 29.1% → 34.0% | **79.4% → 78.4%** |
| ...without constructions near or equal to a fitted one | 226 | | | −0.4 (−5.3 to +4.1) | | |
| By time: fit Aug–Oct, test Nov | 135 | 44.4% → 50.4% | 9 / 1 | +5.9 (−1.7 to +16.7) | **27.4% → 25.2%** | 64.4% → 68.1% |
| ...without constructions near or equal to a fitted one | 52 | | | +13.5 (−7.3 to +32.3) | | |

What this says:

1. **No measurable gain.** Every interval crosses zero. On unseen constructions the draft moves 29 fabrics into 10% and
   23 out (net 6 of 531). Leaving out the tested constructions that are near or equal to a fitted one, the change is
   −0.8 points on the construction split and −0.4 on the time split. November alone moves more (+5.9, 9 in and 1 out of
   135), but on so few fabrics the interval runs from −1.7 to +16.7.
2. **Things that got worse with the draft.** Within 5% falls on the construction split (24.3% → 23.0%) and in November
   (27.4% → 25.2%); within 20% falls on the time split (79.4% → 78.4%). By kind of cloth (sheet "Tested by cell", cells
   of 8 or more):
   - construction split: piece-dyed satin within 10% 55% → 35% (29 fabrics); printed plain 58% → 33% (12); yarn-dyed
     plain 38% → 33% (93); piece-dyed twill 45% → 43% (44). Better: yarn-dyed oxford 40% → 61% (57), yarn-dyed twill
     55% → 66% (58).
   - time split: piece-dyed satin 65% → 51% (43); printed satin 33% → 20% (15); printed twill 10% → 3% (30); yarn-dyed
     satin 89% → 78% (9). Better: piece-dyed dobby 39% → 50% (18), yarn-dyed twill 58% → 66% (111).
3. **Several proposals change with the split** (sheet "Proposals"):
   - printing, Rs a kilo greige (now 390): 410 on the code split, **345** by construction, **425** by time (Aug–Sep),
     370 by time (Aug–Oct). It does not agree on the direction.
   - order size below 1,000 m (points added to the card's band): 5, 7.5, 4 and 5.5.
   - yarn-dyed oxford weaving 0.32 → 0.19 on the construction split only; piece-dyed oxford 0.16 → **0.68 to 0.69** on two
     splits (21 to 24 fabrics: not believable as a weaving rate); piece-dyed dobby 0.55 → 0.60 on one.
   - steady on every split: piece-dyed satin 0.22 → 0.29 or 0.30, and piece-dyed twill 0.18 → 0.22 to 0.25 a pick.
     **Steady is not the same as right: on unseen piece-dyed satin the draft does worse (above), and on piece-dyed twill
     no better.**
4. **Today's rates fit the later months worse** (sheet "Today's fit by month", every fabric, by its order month):

   | Order month | Fabrics | Median gap | Within 10% | Within 20% |
   |---|---|---|---|---|
   | Aug 2026 | 200 | −4.8% | 53.5% | 84.5% |
   | Sep 2026 | 1,047 | +1.3% | 58.5% | 81.0% |
   | Oct 2026 | 336 | +3.0% | 47.0% | 78.0% |
   | Nov 2026 | 113 | +3.9% | 36.3% | 59.3% |

   The price paid moves from about 5% below should-cost in August to about 4% above in November. The yarn rates are of
   one date, so a rising yarn market between August and November would look like this; so would a different mix of cloth
   each month. Yarn prices for July to November (GP is sending them) would tell the two apart: with them in as dated
   rates, each order is costed on its own month's yarn.

## What this test does not show

- Today's rates were themselves calibrated on 23 Nov on the code split's fitting two thirds, so "today" on a held-back
  set is not a clean test of that calibration either; only the new draft is tested fairly here.
- The time split keeps a construction bought in both periods on both sides (54% of the tested fabrics), as in use.
  October and November are only four months after August; a longer history would be a stronger test.
- No rate changed and no proposal was applied (rules 2 and 5). The decision on the draft is still GP's.
