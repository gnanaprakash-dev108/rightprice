/* New cost > Negotiation pack: one page to take into the meeting for a whole mill sheet (or the rows ticked on the
   list or in Right cost): every row with its stance and the money at stake, the mill's own sums that are off, and the
   questions to ask. Printable on one A4 landscape page for a sheet of up to about twenty rows. */
(function () {
  "use strict";
  const { h, fmt, rs, day, pctSigned, plural, postJSON, can } = RP.kit;
  const state = RP.state;
  const STANCE_ORDER = { push: 0, ask: 1, check: 2, below: 3, fair: 4 };

  RP.page("pack", { title: "Negotiation pack", popup: true }, async (arg, ctx) => {
    const ui = state.packUI = state.packUI || { scope: null };
    // rows ticked in Right cost (or on the list) come over once, through this tab's session storage
    let handed = null; try { handed = JSON.parse(sessionStorage.getItem("rp-pack-ids") || "null"); sessionStorage.removeItem("rp-pack-ids"); } catch (e) { /* none */ }
    const lu = state.listUI, picked = handed && handed.length ? handed : lu && lu.picked && lu.picked.size ? [...lu.picked] : null;
    const move = lu && lu.pct !== "" && lu.pct !== undefined && Number(lu.pct) ? { [lu.yarn]: Number(lu.pct) } : null;
    let first;
    try { first = await (await postJSON("/api/pack", move ? { yarn_pct: move } : {})).json(); }
    catch (e) { return [h("p", { class: "empty" }, "The list is empty. Upload a mill's price sheet under Bulk upload and list, then come back here.")]; }
    const scopes = [["all", `Whole list (${plural(first.totals.rows, "row")})`]];
    if (picked) scopes.push(["picked", `Rows ticked on the list (${picked.length})`]);
    first.sheets.forEach((g, i) => scopes.push(["sheet" + i, `${g.label} (${plural(g.ids.length, "row")})`]));
    // ticked rows on the list win whenever there are any; otherwise the last choice, or the whole list
    if (picked) ui.scope = "picked"; else if (!ui.scope || !scopes.some(x => x[0] === ui.scope)) ui.scope = "all";
    const idsFor = k => k === "all" ? null : k === "picked" ? picked : first.sheets[Number(k.slice(5))].ids;
    const body = h("div");
    const draw = async () => {
      const ids = idsFor(ui.scope);
      const p = ids ? await (await postJSON("/api/pack", Object.assign({ ids }, move ? { yarn_pct: move } : {}))).json() : first;
      body.replaceChildren(...packView(p, move, ui.scope === "picked" ? "ticked on the list" : ui.scope.startsWith("sheet") ? first.sheets[Number(ui.scope.slice(5))].label : null));
    };
    const pick = h("select", { id: "pack-scope", "aria-label": "Rows in the pack" }, scopes.map(([v, t]) => h("option", { value: v }, t))); pick.value = ui.scope;
    pick.addEventListener("change", () => { ui.scope = pick.value; draw(); });
    await draw();
    return [h("div", { class: "pack-tools" }, h("label", { for: "pack-scope", class: "sub", style: "margin:0" }, "Rows:"), pick,
      h("button", { class: "btn primary", type: "button", onclick: printPack }, "Print"), can("page:list") ? h("a", { class: "btn small", href: "#bulk", onclick: e => { e.preventDefault(); ctx.tab("bulk"); } }, "Back to the list") : null), body];
  });

  function packView(p, move, scopeNote) {
    const { STANCE } = RP.cost;
    const t = p.totals, R = v => `Rs ${fmt(Math.abs(v), 0)}`;
    const rows = [...p.rows].sort((a, b) => STANCE_ORDER[a.stance] - STANCE_ORDER[b.stance] || Math.abs(b.at_stake || 0) - Math.abs(a.at_stake || 0));
    const who = p.suppliers.length ? p.suppliers.join(", ") : "Mill not named on the sheet";
    const head = h("div", { class: "pack-head" },
      h("div", {}, h("div", { class: "pack-title" }, `${who} · negotiation pack`),
        h("div", { class: "sub", style: "margin:2px 0 0" }, `${t.rows < t.of ? `${t.rows} of ${t.of} rows in the list` : `${t.rows} rows`}${scopeNote ? `, ${scopeNote}` : ""}${p.added.length ? `, added ${p.added.map(day).join(", ")}` : ""} · should-cost on the rate master of ${day(new Date())}, ex-mill, Rs per metre` + (move ? ` · with yarn moved ${Object.entries(move).map(([k, v]) => `${k === "*" ? "all yarns" : k} ${pctSigned(v, 0)}`).join(", ")}, as on the list` : ""))));
    const tile = (label, value, note, cls) => h("div", { class: "pack-tile" + (cls ? " " + cls : "") }, h("div", { class: "lbl" }, label), h("div", { class: "num pack-big" }, value), note ? h("div", { class: "sub", style: "margin:0;font-size:12px" }, note) : null);
    const signed = v => `${v >= 0 ? "" : "−"}${R(v)}`;
    const tiles = h("div", { class: "pack-tiles" },
      tile("Ordered", `${fmt(t.metres, 0)} m`, `${t.duplicates ? `${plural(t.duplicates, "row")} repeating an order (${fmt(t.duplicate_metres, 0)} m) counted once; ` : ""}${t.ordered > t.metres ? `costed, of ${fmt(t.ordered, 0)} m ordered; ` : ""}${plural(t.costed, "row")} costed${t.not_costed ? `, ${t.not_costed} not costed` : ""}${t.no_quantity ? `; ${t.no_quantity} without a quantity` : ""}`),
      tile("Above should-cost, rows counted", signed(t.counted_stake), `Push ${signed(t.push_stake)} + in line ${signed(t.fair_stake)}${t.count.ask + t.count.check ? `. Not counted: ${plural(t.count.ask + t.count.check, "row")} the tool is unsure of or whose quote needs checking (${signed(t.flagged_stake)})` : ""}`),
      tile(`Push: ${plural(t.count.push, "row")}`, R(t.push_above_range), t.count.push ? `above the usual range, to be justified (${R(t.push_stake)} above should-cost)` : "no row is above its usual range", t.count.push ? "push" : ""),
      tile("Ask for the break-up", plural(t.count.ask, "row"), (t.count.ask ? "the tool is unsure of these; no target is named" : "") + (t.count.check ? `${t.count.ask ? ". " : ""}${plural(t.count.check, "quote")} more than 30% below should-cost to confirm first` : ""), t.count.ask || t.count.check ? "ask" : ""),
      tile("Mill's sums off", t.sums_money ? R(t.sums_money) : plural(t.sums_off, "row"), t.sums_off ? (t.sums_money ? `charged above what the sheet's own sums give, on ${plural(t.sums_off, "row")}` : "check them; none charges more than its own sums give") : p.rows.some(r => r.has_sheet) ? "every mill-sheet row's sums add up" : "no row comes from a mill sheet, so there are no sums to check", t.sums_off ? "sums" : ""),
      tile(`In line: ${t.count.fair} · below: ${t.count.below}`, t.savings ? R(t.savings) : "—", t.savings ? "below should-cost on the rows marked Below: a saving, if the specification holds" : "no row is below its usual range"));
    const byCode = Object.fromEntries(p.rows.map(r => [r.code, r]));
    const lead = p.lead.length ? h("div", { class: "pack-lead" }, h("b", {}, "Lead with: "), p.lead.map((c, i) => { const r = byCode[c]; return h("span", {}, `${i ? "; " : ""}${c}, ${R(r.above_range_money)} above the usual range on ${fmt(r.quantity, 0)} m (quote ${rs(r.quote)}; open at ${rs(r.open_at)}, aim for ${rs(r.upper)})`); }), ".") : (t.count.push ? h("div", { class: "pack-lead" }, h("b", {}, "Nothing large to lead with. "), `The ${plural(t.count.push, "Push row")} ${t.count.push === 1 ? "is" : "are"} only paise above the usual range: ask for the top of the range (the questions below).`) : h("div", { class: "pack-lead" }, h("b", {}, "No row to push on. "), "Every costed row is inside its usual range, below it, or on a fabric type the tool is unsure of."));
    const tag = st => h("span", { class: "tag " + STANCE[st][0] }, { push: "Push", fair: "Fair", below: "Below", ask: "Ask break-up", check: "Check quote" }[st]);
    const table = h("div", { class: "table-wrap pack-table" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Fabric"), h("th", { class: "n" }, "Metres"), h("th", { class: "n" }, "Mill price"), h("th", { class: "n" }, "Should-cost"), h("th", { class: "n" }, "Mill above should-cost"), h("th", { class: "n" }, "At stake"), h("th", {}, "What to do"), h("th", {}, "Mill's sums"))),
      h("tbody", {}, rows.map(r => h("tr", {},
        h("td", { class: "pack-fab" }, h("b", {}, r.code), h("div", { class: "pack-desc" }, r.description || "")),
        h("td", { class: "n", "data-l": "Metres" }, r.quantity ? fmt(r.quantity, 0) : "—"), h("td", { class: "n", "data-l": "Mill price" }, fmt(r.quote)), h("td", { class: "n", "data-l": "Should-cost" }, fmt(r.should)),
        h("td", { class: "n", "data-l": "Above should-cost" }, `${r.gap >= 0 ? "+" : "−"}${fmt(Math.abs(r.gap))} (${pctSigned(r.gap_pct * 100)})`),
        h("td", { class: "n", "data-l": "At stake" }, r.at_stake === null ? "—" : (r.at_stake < 0 ? "−" : "") + R(r.at_stake)),
        h("td", { "data-l": "What to do" }, r.duplicate_of ? h("span", { class: "tag warn", title: "Same mill reference and quantity as another row: counted once" }, `Duplicate of ${r.duplicate_of}`) : tag(r.stance), !r.duplicate_of && r.stance === "push" ? h("div", { class: "pack-desc" }, `open ${rs(r.open_at)} · aim ${rs(r.upper)}`) : null),
        h("td", { "data-l": "Mill's sums" }, !r.has_sheet ? h("span", { class: "sub", style: "margin:0" }, "no mill sheet") : r.sums.length ? h("span", { class: "tag down" }, `✗ ${r.sums.length} off`) : h("span", { class: "tag ok" }, "✓ add up")))))));
    const qs = rows.flatMap(r => r.questions.map(q => ({ code: r.code, q })));
    const sums = [...p.rows, ...p.not_costed].filter(r => r.sums.length);
    const foot = h("p", { class: "sub pack-foot" }, "Each fabric type has its own usual range: where half your past purchases of it were priced against should-cost, kept at least 5% and at most 10% either way. Push: above it. Fair: inside it. Below: under it, a saving if the specification holds. Check quote: over 30% below should-cost. Ask break-up: the tool is unsure, so no target. Open: as far below the top of the range as the quote is above it, never below should-cost; aim: the top of the range. At stake: printed gap times metres. A row repeating an order (same mill reference and quantity) is counted once.");
    const questions = h("div", { class: "pack-cols" },
      h("div", {}, h("h2", {}, "Questions to ask"), qs.length ? h("ol", { class: "pack-q" }, qs.map(x => h("li", {}, x.q))) : h("p", { class: "sub" }, "None: every row is in line and its sums add up. Use the time on quantity terms, finish and delivery.")),
      h("div", {}, h("h2", {}, "The mill's sums that are off"), sums.length ? h("ul", { class: "pack-q" }, sums.map(r => h("li", {}, h("b", {}, r.code + ": "), r.sums.join("; ") + ".", r.own_gap ? ` By its own sums the price is ${rs(r.own_price)}, ${rs(Math.abs(r.own_gap))} a metre ${r.own_gap > 0 ? "less than" : "more than"} quoted.` : ""))) : h("p", { class: "sub" }, "Every row's sums add up."),
        p.not_costed.length ? [h("h2", { style: "margin-top:12px" }, "Not costed"), h("ul", { class: "pack-q" }, p.not_costed.map(r => h("li", {}, h("b", {}, r.code + ": "), r.why)))] : null, foot));
    return [head, tiles, lead, table, questions];
  }

  // on paper: A4 landscape, light colours, the pack alone (the browser's own print menu too, while the pack is open)
  const packOpen = () => { const pop = document.querySelector(".scrim[data-popup]"); return !!pop && pop.dataset.tab === "pack"; };
  addEventListener("beforeprint", () => { if (packOpen() && !document.body.classList.contains("printing-pack")) { packPrintOn(); addEventListener("afterprint", packPrintOff, { once: true }); } });
  let packPrintOff = () => {};
  function packPrintOn() {
    const pg = document.querySelector(".scrim[data-popup] .pgbox > .pg");           // only the pack turns light, not the shell
    const page = h("style", {}, "@page { size: A4 landscape; margin: 8mm; }"); document.head.append(page);
    if (pg) pg.classList.add("paper");
    document.body.classList.add("printing-pack");
    packPrintOff = () => { if (pg) pg.classList.remove("paper"); document.body.classList.remove("printing-pack"); page.remove(); };
  }
  function printPack() {
    packPrintOn();
    addEventListener("afterprint", () => packPrintOff(), { once: true });
    setTimeout(() => print(), 60);
  }
})();
