# Questions for GP

## Built 28 Nov 2026 (GP's decisions of 28 Nov: the Fab library; what we usually pay over time)

- **The Fab library** (user icon > Purchase history > Fab library): the PLM fabric code list, uploaded by an admin (Admin and
  Rates editor: a new action permission, do:upload_fab_library, given as purchase files are), read in the background like a
  purchase file (its progress shown; read again from the start after a restart), kept with every upload (who, when, its file
  and its counts). A .csv with the 26 columns plm_extract.py keeps, a .zip holding that one .csv (the real list: 3.7 MB
  zipped, 80 MB unzipped, 418,877 codes), or an .xlsx; up to 200 MB for the list itself (a .zip's list counted unzipped),
  refused on the screen at once with the limit named. Every code is found by its code or words of its construction, with its
  construction, its Fab group (the one it is in, or, for a code never bought, the group its construction is) and its
  purchases; a code's page shows its 26 values, which list gave them and what later lists corrected.
- **Where the specifications come from:** once the library holds a list read in full, the purchase history takes every
  code's PLM specification from it (in place of data/plm_specs_for_po.csv deployed with the code); before any list, from the
  deployed file as before, so nothing changes on the live site until GP uploads the list. The real list holds every one of
  the deployed file's 19,669 codes with exactly the same values (checked by check_server.py when the file is on the
  machine). A code's specification is the latest list's that holds it (lists go in the order they were uploaded, so an older
  list read again never undoes a later one). Codes with a blank EPI, PPI, width or count are kept with the blanks and not
  grouped (8,741 have no EPI or PPI and 23,267 no width in the real list).
- **A list that gives a code a specification, or corrects one, groups and costs it again at once** (stage 2's own path, as a
  purchase upload takes it): a code bought before the library had it is grouped and costed when the list is read, without
  another purchase upload; a corrected EPI moves the code and the group page says what changed.
- **What we usually pay over time:** a Fab group's and a fabric type's usual range, median and "priced above its group / its
  range" rest by default on the purchases of the last 12 months, ending today (29 Nov 2025 to 28 Nov 2026 today: the same
  day a year back, the day after). The Fab group page and the price popup have a time slider over the months the history
  holds (from the start of a month to the end of a month); the figures are worked out again for the period chosen. A view
  only: Right cost, the brief, quote alerts, supplier pages and the Dashboard stay on the last 12 months. Every purchase stays
  on the price-over-time chart (those outside the period faded). For a fabric type, a fabric bought both inside and outside
  the 12 months counts its purchases inside them alone (its price and metres there, costed for those metres). With the
  history of Aug to Nov 2026 nothing changes today (checked: every page's figures as before; the brief says "bought in the
  last 12 months").

## Asked 28 Nov 2026 (the Fab library): built one way meanwhile, each can be changed

L-1. **A code missing from a later list** (a list of part of the codes, or a code taken out of the PLM): built as **kept with the
     specification it had**, its page saying it is not in the latest list (as a purchase line not in a newer file is kept).
     1. Keep it (as now, recommended: a part list then corrects without removing). 2. Take it out of the library at the next
     full list (the purchase history keeps the specification it was grouped by). 3. Keep it, and list such codes on the
     upload's page for an admin.
L-2. **The 12 months: rolling or calendar?** Built as **rolling, ending today** (29 Nov 2025 to 28 Nov 2026); the slider then
     chooses whole months. 1. Rolling (as now). 2. The last 12 whole months (Dec 2025 to Nov 2026, this month included).
     3. The last 12 complete months (Nov 2025 to Oct 2026).
L-3. **The AI assistant's upload of the list** takes the file as base64 in the chat, at most 25 MB, so it is sent zipped (the
     real list is 3.7 MB zipped). 1. As now (recommended). 2. Raise the assistant's limit for this one tool.

## Answered 28 Nov 2026 (the AI assistant, MCP)

- Switching off an admin, or taking Admin away: **stays with a person**. The assistant is refused it, so the admins
  cannot be locked out. Kept as built.
- The tool that brought in prices from a price service: **removed**. It took the service's key through the chat, and keys
  are never pasted in a chat. The screen keeps it (Prices > Bring in prices > A price service), with the same guards;
  the checks now test those guards on the screen's address. The assistant has 45 tools.
- The two tracker remove tools (the assistant's own step; any step): **both kept**. Nothing changed.

## Answered 28 Nov 2026 (stage 2's second review: purchase files whose order cannot be told; widths)

- **Purchase files whose order cannot be told from what they cover: "Saved later wins"** (GP chose this over "an admin
  settles, as built"). What a file covers still decides first: a file was taken no earlier than its latest document date
  (or a report date it carries) and no later than it was saved, and one taken after the other for certain is newer.
  Only where that cannot tell (a correction covering the same orders, the same file saved again), **the file saved later
  replaces the history's figures automatically**, with no admin's choice: its figures, the lines it shows deleted or no
  longer bulk, exactly as a certainly newer file. So the first file saved again later now wins over the correction. A
  file whose saved date cannot be used is dated by its upload (see the date rules below). The upload's page says which
  file won and why ("saved later", with both saved times). An earlier-saved file read after, or at the same moment in
  another server process, brings nothing back. **What is left with no way to tell** (two files with the very same dates,
  to the second) keeps the earlier behaviour for that remainder only: the history stands and the disagreement is listed
  on the upload for an admin to keep or to take the file's figures (Purchase files, and the assistant's
  settle_purchase_disagreements). Done.
- **The history starts from the purchase file that came with the code** ("load it for entire analysis"; GP will upload
  the past 10 years himself). When the first file of any kind is uploaded and that one is not in yet, it is loaded
  first, as its own upload by the same person, and the uploaded one after it; the usual rules put them in order. The
  Load button stays. Done.
- **A line simply not in a newer file of the same order is kept** ("keep it"): never taken as cancelled or dropped.
  Only a line a file shows deleted, blocked, no longer bulk, not in rupees or per metre, or with other figures is
  changed or removed. So a later download covering a longer span (July to date after August to date) takes each line
  once; the upload says how many were already in and lists the ones it updated. Done.
- **Every purchase order is loaded, whatever its construction details**: a code with no PLM specification (or an
  incomplete one) is counted in its prices like any other, with its construction blank; the upload and the price popup
  say "No PLM specification". Done. (Sample and yardage order types: still being asked; the kept types are unchanged.)
- **File size: one file per year or per 6 months.** A file over the limit (40 MB now; the limit itself is still to be
  decided) is refused on the screen as soon as it is chosen, before anything is sent, naming the limit and saying to
  split it by 6 months or by year. Done.
- **Dates a file carries (the reviewers' data-validity rule, not a decision of GP's):** nothing dated after the upload
  is trusted. A saved date after the upload (a clock set wrong) or before the file's latest order is not used, and the
  file is dated by its upload; a report date counts only between its latest order and its saved date, and two files of
  the same report date go by their saved dates; a document date after the upload's day is kept but does not date the
  file. Document dates are compared as days in India with saved times in UTC. Each date not used is said on the upload.
- **Width tolerance: chain, as built.** Codes alike in the other eight fields whose widths are within half an inch of
  each other, directly or through other codes, are one group, so a group can run over more than half an inch from end
  to end (57, 57.4 and 57.8 in are one group). Kept; no change.

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

## Built 28 Nov 2026 (the second review of stage 2): which purchase file is newer

- **Which file is newer is read first from what it covers**: a file was taken no earlier than its latest document date
  (every row with a date, kept or not), or the report date it carries in a column of its own (Report Date, Export Date,
  Extracted On, Run Date, As of), and no later than it was saved. One file is newer than another for certain when it
  was taken after the other for certain: a later SAP export, with orders dated after the earlier one was saved, is.
  SAP's own export carries no report date. Where that cannot tell, the file saved later wins (GP, 28 Nov 2026, above).
- **Every order line keeps the word of the newest file that covered it**: its figures, or that it was deleted, blocked,
  no longer bulk, not in rupees or per metre, even before any file gave its figures. So an older file read after a newer
  one (or at the same time, in two server processes) brings nothing back.
- **Right cost's purchase-order rows read the purchase history alone once it holds a file**, as the price popup and the
  Fab group pages do, so the two never disagree. Before any file is loaded they show the pilot's purchases as the
  purchase file that came with the code has them; the first upload loads that file first (GP, 28 Nov 2026, above). The Suppliers tab of Right cost counts as the supplier list does (a code bought only on ZLOI is not
  counted). A code that moves group says what changed in its specification, or that a new code joined its widths; a
  code not costed now shows its specification as it is now.
- **Found and fixed in the second review of 28 Nov:** an older file's deletion never overrides a newer file's figures;
  a document date in the future (a mistyped year) no longer dates a file
  as newer than every export; costing choices a restart left half-done, or worked out on the rate master's lists as they
  were, are worked out again; Right cost's purchase-order rows keep their supplier in the choices they open in Cost a
  fabric. A row whose choices differ from the pilot's says what differs, not that its specification changed.
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
  come in; the group's name gives the widths it runs from and to. Through each other, a group can run over more than
  half an inch (57, 57.4 and 57.8 in are one group): GP confirmed this on 28 Nov 2026 ("chain, as built", above).
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
