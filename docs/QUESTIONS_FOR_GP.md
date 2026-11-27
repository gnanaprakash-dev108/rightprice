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
