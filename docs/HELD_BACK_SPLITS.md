# The calibration's held-back test, split fairly (stage 5, 27 Nov 2026)

**Nothing was applied and no rate changed.** `pilot/Proposed_Rate_Changes.xlsx` is untouched. The figures below come from
`python calibrate_splits.py`, which writes `pilot/Held_Back_Splits.xlsx` (every table in full).

## Why it was re-run

The calibration draft holds back a third of the 1,696 costed purchase-order fabrics by a rule on the fabric code, and is
tested on them. But the 1,696 are only 433 constructions: the same cloth under several codes. With that split, **481 of
the 552 tested fabrics (87%) have their construction among the fabrics the draft was fitted on** (188 constructions on
both sides). The draft was being tested largely on cloth it had already seen.

So the same draft (order size added to the rate card's bands, weaving per route and weave group, one printing rate) was
worked out again on three fairer splits and tested on what each held back:

- **By construction**: a third of the constructions held back, so the same construction is never on both sides. A
  construction is the nine fields of a Fab group (content, route, weave, warp, weft, EPI, PPI, finished width, finish),
  tidied and joined by `construction.py`. **Stage 2's Fab groups are not merged yet; this small function stands in for
  them and can be replaced by stage 2's signature.**
- **By time**: fitted on the fabrics ordered in August and September 2026, tested on October and November. A fabric
  code's month is the month that holds most of its metres (230 codes were ordered in two or three months).
- **By time, last month only**: fitted on August to October, tested on November (113 fabrics: a second look only).

Gap = price paid above should-cost. "Today" is the tool as it stands; "draft" adds the draft's proposals.

## The held-back fabrics

| Split | Tested | Their construction also in the fit | Within 10%: today → draft | Within 5% | Within 20% | Median size of gap | Median gap |
|---|---|---|---|---|---|---|---|
| By fabric code (the draft's own) | 552 | 87% | 52.4% → 53.6% (+1.2) | 28.4% → 30.1% | 78.1% → 78.6% | 9.2% → 9.3% | −0.4% → −1.6% |
| **By construction** | 531 | **0%** | **48.6% → 49.7% (+1.1)** | **24.3% → 23.0%** | 79.3% → 79.1% | 10.4% → 10.1% | −0.7% → −1.1% |
| **By time: fit Aug–Sep, test Oct–Nov** | 449 | 33% | **44.3% → 45.0% (+0.7)** | 23.6% → 24.3% | 73.3% → 73.7% | 12.5% → 11.6% | +3.2% → +2.9% |
| By time: fit Aug–Oct, test Nov | 113 | 36% | 36.3% → 43.4% (+7.1) | 21.2% → 18.6% | 59.3% → 63.7% | 14.3% → 17.3% | +3.9% → +3.9% |

What this says:

1. **The draft adds about one point within 10% on cloth it has not seen**, much the same as the old test said (+1.1
   against +1.2). The old split did not flatter the draft's gain much; it flattered the level: on unseen constructions
   today's rates are within 10% for 48.6% of fabrics, not 52.4%.
2. **Some things got worse with the draft.** On the construction split the share within 5% falls (24.3% → 23.0%) and
   within 20% barely moves. In November alone the median size of the gap grows from 14.3% to 17.3% though more fabrics
   land within 10%. By kind of cloth (sheet "Tested by cell", cells of 8 or more):
   - construction split: piece-dyed satin within 10% 55% → 35% (29 fabrics); printed plain 58% → 33% (12); yarn-dyed
     plain 38% → 33% (93); piece-dyed twill 45% → 43% (44). Better: yarn-dyed oxford 40% → 61% (57), yarn-dyed twill
     55% → 66% (58).
   - time split: printed satin 29% → 14% (14), printed twill 11% → 0% (27), yarn-dyed satin 56% → 44% (9). Better:
     piece-dyed dobby 31% → 44% (16), piece-dyed plain 46% → 54% (26).
3. **Several proposals change with the split, so they are not to be trusted as they stand** (sheet "Proposals"):
   - printing, Rs a kilo greige (now 390): 410 on the code split, **345** by construction, **440** by time (Aug–Sep),
     375 by time (Aug–Oct). It does not even agree on the direction.
   - order size below 1,000 m (points added to the card's band): 5 on the code split, 7.5 by construction, 2.5 and 4.5
     by time.
   - yarn-dyed oxford weaving 0.32 → 0.19 on two splits, kept on the others; piece-dyed oxford 0.16 → **0.69** on two
     splits (21 to 23 fabrics: not believable as a weaving rate); piece-dyed dobby 0.55 → 0.60 on one.
   - **Steady on every split: piece-dyed satin 0.22 → 0.29 or 0.30, and piece-dyed twill 0.18 → 0.22 to 0.25 a pick.**
     These two are the only proposals the fair tests support as they are.
4. **Today's rates fit the later months worse** (sheet "Today's fit by month", every fabric):

   | Order month | Fabrics | Median gap | Within 10% | Within 20% |
   |---|---|---|---|---|
   | Aug 2026 | 200 | −4.8% | 53.5% | 84.5% |
   | Sep 2026 | 1,047 | +1.3% | 58.5% | 81.0% |
   | Oct 2026 | 336 | +3.0% | 47.0% | 78.0% |
   | Nov 2026 | 113 | +3.9% | 36.3% | 59.3% |

   The price paid moves from about 5% below should-cost in August to about 4% above in November. The yarn rates are of
   one date, so a rising yarn market between August and November would look exactly like this; so would a different mix
   of cloth each month. Yarn prices for July to November (GP is sending them) would tell the two apart: with them in as
   dated rates, each order is costed on its own month's yarn.

## What this test does not show

- Today's rates were themselves calibrated on 23 Nov on the code split's fitting two thirds, so "today" on a held-back
  set is not a clean test of that calibration either; only the new draft is tested fairly here.
- The time split keeps a construction bought in both periods on both sides (33% of the tested fabrics), as it would be
  in use. October and November are only four months after August; a longer history would be a stronger test.
- No rate changed and no proposal was applied (rules 2 and 5). The decision on the draft is still GP's; on this evidence
  only the piece-dyed satin and twill weaving rates hold up.
