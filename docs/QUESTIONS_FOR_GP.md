# Questions for GP

## Answers given 25 Nov 2026, night

- Data: the 1,696 purchase-order costings (plus the fabric list). Done.
- Right cost stays its own page at /rightcost. Done.
- Status and Remarks: each browser only. Done.
- Other PLM modules: the Library setup pages only. Built (Library on the rail; lists kept in the browser).
- In-line band: 5% floor, 10% cap. Opening figure: the mirror rule. Placeholder limit: 10%. Kept.
- Real wastage, overhead and margin: GP will send mill cost sheets.
- Tabs: Views and Samples removed. Card colours: the verdict. Share: copy codes and note.
- Dark mode: added, following RightPrice's switch. Avatar: initials from the Microsoft sign-in
  (read from Azure's /.auth/me; off Azure it shows RP).

## Asked 27 Nov 2026, stage 5 (dated yarn rates): built one way meanwhile, each can be changed

S5-1. **Which kind are the yarn master's cotton yarns (Cotton 16S to 40S)?** The market history in hand has two years of
      KPR and SSM *semi-combed* prices for 16s, 20s, 24s, 30s, 34s and 40s (613 prices, July 2022 to June 2026). The yarn
      master does not say combed, combed compact or semi-combed, so they were **not** loaded (only a sure match is).
      1. Semi-combed: load them as dated rates. 2. Combed or combed compact: leave them out (as now). 3. Not sure: leave them out.
S5-2. **A price given as a range** (Rs 1,600 to 1,650): built as **the midpoint**. 1. Midpoint (as now). 2. The low end
      (what a mill buying well pays). 3. The high end.
S5-3. **Prices that include GST.** The only market prices loaded (Raymond linen 40 and 60 lea, June 2026) include GST and
      freight, as the file says; they are kept as they are, and the basis says so. 1. Keep as they are (as now).
      2. Take 5% GST out. 3. Leave GST-inclusive prices out.
S5-4. **A month with no dated rate** uses today's rate (the yarn master), and the costing says so per yarn. 1. Today's
      rate (as now). 2. The nearest earlier month's dated rate, if there is one within, say, two months.
S5-5. **Viscose 40/2 in the yarn master**: 2/40s TFO doubled or ring doubled? The market file has both; neither was
      loaded. 1. TFO doubled. 2. Ring doubled. 3. Leave it out.
S5-6. **A place in the side panel?** Dated yarn rates sit on Prices > Yarn prices (under the yarn master), and Bring in
      prices has "Add as dated yarn rates". Nothing was added to the side panel. 1. Fine where it is. 2. Wanted in the panel.
S5-7. **The linen placeholders look far too low.** Raymond's June 2026 linen is Rs 1,600 to 1,650 a kilo (40 lea) and
      Rs 2,200 to 2,250 (60 lea), with GST and freight; the yarn master has placeholders of Rs 900 and Rs 1,200. Nothing
      was changed (rule 2). A real linen quote would settle it.
S5-8. **The calibration draft, tested fairly.** On cloth it was not fitted on, and on later months, the draft shows no
      measurable gain (about +1 point within 10%, with a 95% interval from about −5 to +8; November alone +5.9, but from
      −1.7 to +16.7 on 135 fabrics), and it makes piece-dyed satin
      clearly worse (docs/HELD_BACK_SPLITS.md). 1. Do not apply it (recommended). 2. Apply only the piece-dyed twill
      weaving rate. 3. Wait for the July to November yarn prices and test again on dated rates.
S5-9. **A typed dated rate with no source** is kept as a Placeholder, like a rate of the rate master with no data behind
      it: the brief and the verdicts treat it as unsure. 1. As now. 2. Refuse a typed rate with no source.

## Built 28 Nov 2026 (the second review of stage 2): which purchase file is newer, and what happens when that cannot be told

- **Which file is newer is read from what it covers**, never from when the workbook was saved (a file saved again later
  is no newer): a file was taken no earlier than its latest document date (every row with a date, kept or not), or the
  report date it carries in a column of its own (Report Date, Export Date, Extracted On, Run Date, As of), and no later
  than it was saved. One file is newer than another only when it was taken after the other for certain: a later SAP
  export, with orders dated after the earlier one was saved, is. SAP's own export carries no report date.
- **Every order line keeps the word of the newest file that covered it**: its figures, or that it was deleted, blocked,
  no longer bulk, not in rupees or per metre, or left out of an order the file has, even before any file gave its
  figures. So an older file read after a newer one (or at the same time, in two server processes) brings nothing back.
- **When which is newer cannot be told** (a correction covering the same orders, a file with no saved date, the first
  file saved again) **and the file disagrees with the history, the history stands and the disagreement is listed** on
  the upload (Purchase files), line by line, for an admin to keep the history's figures or take the file's. Nothing is
  guessed. **To confirm:** 1. As now. 2. A file saved later wins after all when both cover the same orders.
- A code bought only on ZLOI orders is not counted as bought on the supplier list and pages; a group's mill with only
  ZLOI lines is listed, not counted; Pilot results says it is the pilot as run, ZLOI included (1,696 fabrics), beside
  the 1,512 every other page counts.
- A code whose PLM specification changes is costed again at the next upload; a group whose codes all changed keeps its
  code, is renamed, and its page says what changed (merges and undone merges are recorded there too, with who). Right
  cost's purchase-order rows cost each code on the choices the price popup costs (the purchase history's, from the PLM
  specification), so the two cannot disagree.

## Answered 27 Nov 2026 (stage 2's review: purchase history and Fab groups)

- **ZLOI order lines: kept out of every calculation, everywhere** ("Yes, everywhere"). 402 of the 1,377 priced ZLOI lines
  are at exactly Rs 550; 661 are followed by a regular BO order for the same code and mill (239 with the same metres); they
  made Rs 2.61 crore of the Rs 3.24 crore "above the range". They stay in the database and are shown apart as "Outliers
  (ZLOI)", with date, metres and price: beside the fabric (the price popup, Right cost's fabric page) and beside the mill
  (the supplier page, the group page's by-mill table). Left out of: price paid, metres, medians, ranges, "above the range",
  a should-cost's quantity band, and Right cost's purchase-order rows (price paid, metres, should-cost, verdict), so also the
  supplier pages, alerts, drafts and the dashboard's fit by fabric type. pilot/Pilot_Results.xlsx is not changed or re-run:
  Right cost works its rows out again from the purchase lines. A code bought only on ZLOI shows no price paid, only its
  outliers. Done. With stage 5's dated yarn rates, a code's order month leaves ZLOI out too: 155 codes' order month
  moves, and the 184 codes bought only on ZLOI have no order month, so they are costed on today's rates and say why.
  The price popup and the Fab group pages cost each code on its order month as Right cost does, so they still agree.
  (calibrate_splits.py keeps the pilot's own lines, ZLOI included, so its held-back test reads as before.)
- **Width: within half an inch is one group.** Done as a tolerance (the second review: rounding split 57.4 and 57.5 in):
  codes alike in the other eight fields whose widths are within half an inch of each other, directly or through other
  codes, are one group (57 in and 145 cm; 57.4 and 57.5 in). It depends only on the widths held, never on the order files
  come in; the group's name gives the widths it runs from and to. **To confirm:** through each other, a group can run
  over more than half an inch (57, 57.4 and 57.8 in are one group). 1. As now. 2. Never more than half an inch from end
  to end (then two widths 0.1 in apart can fall either side of a split).
- **A usual range needs purchases on at least 5 separate orders** (distinct order numbers, ZLOI left out), not 5 lines. The
  price popup draws a group's median only when the group has a range. Done.
- Finish names written differently ("Normal Soft" and "Soft Finish", "Regular" and "Normal Soft") stay apart unless an
  admin merges them. Kept.

## Answered 27 Nov 2026 (for stages 2, 3 and 5)

- Stage 2, "priced well above its group": **the same rule as the brief**: above the group's usual range (the middle half
  of its past prices, kept between 5% and 10% either side of the group's median).
- Stage 3, roles: **Admin, Rates editor, Buyer, Viewer**. Admin: everything, users included. Rates editor: may edit rates
  and apply mill cost sheet drafts, no user admin. Buyer: every page, uploads, tracker steps and drafts; no rate edits, no
  user admin. Viewer: read only. Nobody has access until an admin adds them; enforced on the server; page-wise
  permissions adjustable per role on the admin page. (The 10 names are still to come from GP.)
- Stage 5, which rates a costing uses: **order date for orders**: purchase orders on the rates of their order month;
  quotes and Cost a fabric on today's rates; each costing says which date's rates it used.

## Answered 27 Nov 2026 (stage 1 of the rebuild)

- The Azure database `rightprice-db` exists (deployment completed 27 Nov). `DATABASE_URL` is added only when the build
  session asks, after stage 1 is merged and deployed (steps: docs/AZURE_DEPLOY.md, "The database").
- 9 purchase-order verdicts changed at a server restart (a cost line resting on two placeholders went to whichever Python
  listed first). GP chose: work out the placeholder share every time (the line counts for both). Done; the 9 read Push (5)
  and Fair (4).

Doubts recorded while building, newest first. Each says what was done meanwhile, so nothing waits on
the answer. Answer beside a question (or just tell the build session) and it will be acted on.

## Answered 26 Nov 2026, morning

- Dating the yarn rates: wait for yarn prices for July to November 2026. Paused until they come.
- The 265 uncosted purchase-order fabrics: leave them out. The pilot is not re-run.
- Next: the mill cost sheet intake (built, pull request 16).

## Asked 26 Nov 2026, early morning (now answered above)

A. **Dating the yarn rates (Next to build, item 4).** The yarn price history in hand
   (`inputs/Yarn_Inteliigence_Master.xlsx`, sheet Yarn_Master: 5,275 prices by count, 2022 to June
   2026) stops in June 2026, and the purchase orders run August to November 2026, so no order can be
   costed on the rates of its own month yet. Choices:
   1. Build panel 3 by year now: a fabric's cost for 2022 to 2026, each yarn rate scaled by that year's
      average market price for its count (a what-if; no rate changes). Order-month costing waits.
   2. Wait for yarn prices for July to November 2026, then build both.
   3. Add a dated yarn rate table to the rate master now and cost each order on the nearest month
      with data, marking the months without any.
   *Which?* (Recommended: 1, and send July to November yarn prices when you can.)
B. **The 265 purchase-order fabrics not costed (item 5)**, mostly two yarns in one direction
   ("40s + 40s melange"). Costing them means re-running `pilot.py`, which changes the dashboard's fit
   figures and so the brief's usual ranges for every fabric type. Choices: cost them on the first
   yarn only (as mill sheets are, with a note), or on an even split of the two yarns, or leave them
   out. *Which, and may the pilot be re-run?*

## Right cost (the PLM-style list page), 25 Nov 2026, night

1. **Which "1,600+ existing costs"?** Taken as the 1,696 purchase-order fabrics costed in the pilot
   (`pilot/Pilot_Results.xlsx`), plus the rows of the fabric list. The attached `sample-data.json`
   holds 120 fabrics and 80 trims with no costs, so it is not loaded. *Right?*
2. **Where Right cost lives.** Built as its own page, `/rightcost`, with the PLM-style left rail; it is
   reached from "Right cost" in RightPrice's page list, and the rail links back to every RightPrice
   page. *Should it instead become the home page, or replace RightPrice's own left panel everywhere?*
3. **Other PLM modules.** The prompt also describes Trims, Gold Seals, Products → Styles, a dashboard
   tile and Library setup pages. Only the costing list (with its detail page) is built. The title
   dropdown switches Purchase-order costings / Fabric list / All. *Are the other modules wanted?*
4. **Tabs.** Items and Suppliers (cost and gap by supplier) have content; Views and Samples show "No
   records to view". *What should Views and Samples hold, or should they go?*
5. **Status and Remarks columns** (the editable cells, the bulk Edit and the detail page's Edit) are
   kept in the browser only, so each person sees their own. *Should they be saved on the server for
   everyone? That means a small store beside the rate master.*
6. **Colour bar in card view.** The PLM's Concept / Development / Bulk colours were replaced by the
   negotiation verdict: green in the usual range, red above it, blue below, yellow tool unsure,
   amber check the quote. *OK?*
7. **Share.** RightPrice has no user accounts, so Share copies the fabric codes and a note instead of
   sending to a person. *OK, or is there a mail or Teams address it should go to?*
8. **Light only.** The design tokens are a light theme, so Right cost has no dark mode, unlike the
   rest of RightPrice. *Want dark too?*
9. **Font and offline.** The prompt asks for a page that works offline; Right cost reads its data from
   the server (the live costings), so it needs the server and the sign-in like the rest of the app.
   Open Sans is loaded from Google Fonts. *OK?*
10. **Avatar** shows "GP" for everyone. Azure sign-in could give each person's initials. *Wanted?*

## What the data showed while building (needs your rates, not a yes/no)

11. **1,138 of the 1,696 purchase-order costings (67%) come out "Tool unsure"** on today's rates, so
    the brief names no target on them. 1,018 of those rest on placeholder rates: wastage, overhead and
    margin on 696 (whole route and weave combinations in the table "Crimp, wastage, overhead,
    margin"), sizing on 478, weaving on 258, a yarn rate on 223 (finishing appears on 833 but is small
    on its own). The rest are fabric types the tool fits poorly (yarn-dyed plain 218, yarn-dyed oxford
    110, printed twill 64 and others). The biggest single unlock is real wastage, overhead and margin
    for the combinations marked Placeholder, then sizing and weaving.

## Negotiation brief and pack, 25 Nov 2026

12. **"In line" range**: the middle half of past purchases of the fabric type, never narrower than 5%
    nor wider than 10% either way. *Are 5% and 10% the right floor and cap?*
13. **Opening figure for a Push**: as far below the top of the range as the quote is above it, never
    below the should-cost. *OK as a rule?*
14. **A placeholder blocks the target** only when more than 10% of the price rests on it. *OK?*
