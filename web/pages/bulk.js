/* New cost > Bulk upload: one list of every fabric costed, added from Create cost or uploaded many at a time (the
   RightPrice template, or a mill's price sheet as it comes). The columns are the mill sheet's own headings. Rows are
   ticked to open, compare or remove them; the list stays until rows are removed. */
(function () {
  "use strict";
  const { $, h, fmt, day, pctSigned, plural, blank, api, postJSON, download, toast, pageHead } = RP.kit;
  const state = RP.state;

  RP.page("bulk", { title: "Bulk upload", popup: true }, async (arg, ctx) => {
    const { STANCE, stanceFor, STEPS, selFromRow } = RP.cost;
    state.listUI = state.listUI || { groups: { Fabric: true, Order: false, "Mill's price build-up": true }, picked: new Set(), filter: "", show: "all" };
    const ui = state.listUI;
    if (ui.yarn === undefined) ui.yarn = "*"; if (ui.pct === undefined) ui.pct = ""; if (ui.byStake === undefined) ui.byStake = false;
    // a yarn move handed over from the Dashboard, applied once
    try { const mv = JSON.parse(sessionStorage.getItem("rp-list-move") || "null"); sessionStorage.removeItem("rp-list-move"); if (mv) { ui.yarn = mv.yarn; ui.pct = String(mv.pct); } } catch (e) { /* none */ }
    // with a yarn move on, the gap that counts is the one after the move
    const moving = () => ui.pct !== "" && !!Number(ui.pct);
    const gapOf = r => moving() && r.sim_gap !== null && r.sim_gap !== undefined ? { rs: r.sim_gap, pct: r.sim_gap_pct } : { rs: r.gap, pct: r.gap_pct };
    // money at stake on the gap as printed (to the paisa), so it can be checked by hand
    const stakeOf = r => { const g = gapOf(r); return g.rs === null || g.rs === undefined || !r.quantity ? null : Math.round(Math.round(g.rs * 100) / 100 * r.quantity); };
    const rowStance = r => r.brief ? (r.brief.implausible ? "check" : stanceFor(r.brief, gapOf(r).pct)) : null;
    const box = h("div"), status = h("div", { "aria-live": "polite" });
    let data = null;
    const load = async () => {
      const moves = ui.pct !== "" && Number(ui.pct) ? { [ui.yarn]: Number(ui.pct) } : null;
      data = state.list = await (await postJSON("/api/list", moves ? { yarn_pct: moves } : {})).json();
      for (const id of [...ui.picked]) if (!data.rows.some(r => r.id === id)) ui.picked.delete(id);
      paint();
    };
    const visible = () => {
      const q = ui.filter.trim().toLowerCase();
      const rows = data.rows.filter(r => (ui.show === "all" || (ui.show === "notcosted" && r.problems.length) || (ui.show === "sums" && r.sums && r.sums.length) || (ui.show === "above" && rowStance(r) === "push")) && (!q || JSON.stringify([r.mill, r.supplier, r.description]).toLowerCase().includes(q)));
      for (const id of [...ui.picked]) if (!rows.some(r => r.id === id)) ui.picked.delete(id);      // a tick never outlives the row being in view
      return ui.byStake ? [...rows].sort((a, b) => (stakeOf(b) ?? -Infinity) - (stakeOf(a) ?? -Infinity)) : rows;
    };
    const remarks = r => [...r.problems.map(x => "Not costed: " + x), ...(r.sums || []).map(x => "Sum off: " + x), ...r.notes.map(x => x.charAt(0).toUpperCase() + x.slice(1)), r.placeholders.length ? "Placeholder rates: " + r.placeholders.join(", ") : null].filter(Boolean);
    const stanceCell = r => { const b = r.brief; if (!b) return ""; const st = rowStance(r); return h("span", { class: "tag " + STANCE[st][0], title: STANCE[st][1] + (st === "ask" ? ": " + b.weak.join("; ") : `. Usual range for this fabric: ${pctSigned(b.band.lo * 100)} to ${pctSigned(b.band.hi * 100)} against should-cost`) }, { push: "Push", fair: "Fair", below: "Below", ask: "Ask break-up", check: "Check quote" }[st]); };
    const openRow = r => { if (!r.inputs) return toast("This row has no choices to open", false); state.sel = selFromRow(r.inputs); if (r.quantity) state.sel["Order quantity (m)"] = r.quantity; state.listId = r.id; state.rowNotes = r.notes; state.reopened = r.then ? { then: r.then, on: r.added } : null;
      if (moving()) { const p = Number(ui.pct), on = k => ui.yarn === "*" || r.inputs[k] === ui.yarn; state.sim = { warp: on("Warp yarn") ? p : 0, weft: on("Weft yarn") ? p : 0, both: on("Warp yarn") && on("Weft yarn") }; toast(`Opened with the list's yarn move (${ui.yarn === "*" ? "all yarns" : ui.yarn} ${pctSigned(p, 0)}) on the sliders; the brief follows it`); }
      else state.sim = null; state.openStep = r.problems.length ? "route" : null; STEPS.forEach(st => state.visited.add(st.id)); if (r.problems.length) toast(`${r.mill["Fab Code"] || "This row"} is not costed yet: ${r.problems[0]}`, false); ctx.tab("cost"); };
    // the pack is another tab: the ticked rows go with it
    const toPack = e => { e.preventDefault(); try { if (ui.picked.size) sessionStorage.setItem("rp-pack-ids", JSON.stringify([...ui.picked])); else sessionStorage.removeItem("rp-pack-ids"); } catch (err) { /* no handover */ } ctx.tab("pack"); };
    const cell = (c, v) => blank(v) ? "" : typeof v === "number" ? (Number.isInteger(v) ? String(v) : fmt(v, Math.abs(v) < 100 && !Number.isInteger(v * 10) ? 2 : 1).replace(/\.0$/, "")) : (/^\d{4}-\d\d-\d\d$/.test(v) ? day(v) : String(v));

    const paint = () => {
      const rows = visible(), cols = data.columns.filter(c => c !== "Fab Code" && Object.entries(data.groups).some(([g, list]) => ui.groups[g] && list.includes(c)));
      const sim = data.rows.some(r => r.simulated !== null);
      const all = h("input", { type: "checkbox", "aria-label": "Select every row shown" }); all.checked = rows.length > 0 && rows.every(r => ui.picked.has(r.id)); all.indeterminate = !all.checked && rows.some(r => ui.picked.has(r.id));
      all.addEventListener("change", () => { rows.forEach(r => all.checked ? ui.picked.add(r.id) : ui.picked.delete(r.id)); paint(); });
      const body = rows.map(r => {
        const tick = h("input", { type: "checkbox", "aria-label": `Select ${r.mill["Fab Code"] || "row"}` }); tick.checked = ui.picked.has(r.id);
        tick.addEventListener("change", () => { tick.checked ? ui.picked.add(r.id) : ui.picked.delete(r.id); paint(); });
        const price = r.inputs && r.inputs["Quoted price (Rs/m)"];
        const sc = r.problems.length ? h("span", { class: "tag warn", title: r.problems.join("; ") }, "⚠ not costed") : [fmt(r.should_cost), r.placeholders.length ? h("span", { class: "tag warn", title: "Placeholder rates used: " + r.placeholders.join(", "), style: "margin-left:6px" }, "⚠") : null];
        const g = gapOf(r), rst = rowStance(r), weakRow = rst === "ask";
        const gap = g.pct === null || g.pct === undefined ? "" : h("span", { class: "tag " + (weakRow || rst === "check" ? "warn" : rst === "fair" || !rst ? "flat" : rst === "push" ? "down" : "up"), title: weakRow ? "The tool is unsure here: " + r.brief.weak.join("; ") : rst === "fair" ? "Inside the usual range for this fabric: treat as noise" : rst === "push" ? "Above the usual range for this fabric: room to negotiate" : "Below the usual range for this fabric" }, `${g.rs >= 0 ? "+" : "−"}${fmt(Math.abs(g.rs))} (${pctSigned(g.pct * 100)})`);
        const stake = stakeOf(r), rem = remarks(r);
        const sums = r.sums === null ? h("span", { class: "sub", style: "margin:0" }, "—") : r.sums.length ? h("span", { class: "tag down", title: r.sums.join("; ") }, `✗ ${r.sums.length} off`) : h("span", { class: "tag ok" }, "✓ add up");
        const simCells = sim ? [h("td", { class: "n rp" }, r.simulated === null ? "" : fmt(r.simulated)), h("td", { class: "n rp" }, r.simulated === null || r.should_cost === null ? "" : Math.abs(r.simulated - r.should_cost) < 0.005 ? "no change" : `${r.simulated - r.should_cost >= 0 ? "+" : "−"}${fmt(Math.abs(r.simulated - r.should_cost))}`)] : [];
        return h("tr", { class: ui.picked.has(r.id) ? "picked" : null },
          h("td", { class: "stick s0" }, tick),
          h("td", { class: "stick s1" }, h("button", { type: "button", class: "linkish", title: "Open in Create cost", onclick: () => openRow(r) }, r.mill["Fab Code"] || "(no code)")),
          h("td", { class: "n rp stick s2" }, sc), ...simCells, h("td", { class: "n rp" }, blank(price) ? "" : fmt(price)), h("td", { class: "n rp" }, gap), h("td", { class: "n rp" }, stake === null ? "" : (stake < 0 ? "−" : "") + "Rs " + fmt(Math.abs(stake), 0)), h("td", { class: "rp" }, stanceCell(r)), h("td", { class: "rp" }, sums),
          h("td", { class: "rp remarks" }, rem.length ? rem.map(x => h("div", {}, x)) : ""),
          cols.map(c => h("td", { class: "millcol" + (typeof r.mill[c] === "number" ? " n" : "") }, cell(c, r.mill[c]))));
      });
      const n = ui.picked.size, picked = data.rows.filter(r => ui.picked.has(r.id));
      const counts = { all: data.rows.length, notcosted: data.rows.filter(r => r.problems.length).length, sums: data.rows.filter(r => r.sums && r.sums.length).length, above: data.rows.filter(r => rowStance(r) === "push").length };
      const stakeBox = h("input", { type: "checkbox", id: "ls-stake" }); stakeBox.checked = ui.byStake; stakeBox.addEventListener("change", () => { ui.byStake = stakeBox.checked; paint(); });
      const chip = (key, label) => h("button", { type: "button", class: "chip", "aria-pressed": String(ui.show === key), onclick: () => { ui.show = key; paint(); } }, `${label} ${counts[key]}`);
      const grp = g => h("button", { type: "button", class: "chip", "aria-pressed": String(!!ui.groups[g]), onclick: () => { ui.groups[g] = !ui.groups[g]; paint(); } }, g);
      const filter = h("input", { class: "filter", type: "search", placeholder: "Filter the list...", "aria-label": "Filter the list", value: ui.filter, style: "max-width:220px" });
      filter.addEventListener("input", () => { ui.filter = filter.value; const pos = filter.selectionStart; paint(); const f = $(".list-tools .filter"); if (f) { f.focus(); f.setSelectionRange(pos, pos); } });
      const yarnPick = h("select", { id: "ls-yarn", "aria-label": "Yarn to move" }, h("option", { value: "*" }, "All yarns"), data.yarns_in_use.map(y => h("option", { value: y }, y))); yarnPick.value = data.yarns_in_use.includes(ui.yarn) ? ui.yarn : "*";
      const pctBox = h("input", { id: "ls-pct", type: "number", step: "1", min: "-50", max: "50", value: ui.pct, placeholder: "0", "aria-label": "Yarn price change, per cent", style: "width:84px" });
      const apply = () => { ui.yarn = yarnPick.value; const v = Number(pctBox.value); if (pctBox.value !== "" && Math.abs(v) > 50) { toast("A yarn move is limited to 50% either way", false); pctBox.value = String(Math.sign(v) * 50); } ui.pct = pctBox.value; load(); };
      yarnPick.addEventListener("change", apply); pctBox.addEventListener("change", apply);
      const costedRows = data.rows.filter(r => r.should_cost !== null && gapOf(r).rs !== null && gapOf(r).rs !== undefined);
      // the money in the sheet, kept apart by what to do: savings never net off what to push for, and rows the
      // tool is unsure of are counted on their own
      const withQty = costedRows.filter(r => stakeOf(r) !== null), metres = withQty.reduce((a, r) => a + r.quantity, 0);
      const part = st => withQty.filter(r => rowStance(r) === st), sumOf = rs_ => rs_.reduce((a, r) => a + stakeOf(r), 0);
      const priced = data.rows.filter(r => r.inputs && !blank(r.inputs["Quoted price (Rs/m)"]));
      const uncosted = priced.filter(r => r.should_cost === null), allM = priced.reduce((a, r) => a + (r.quantity || Number(r.mill["Total order qnty"]) || 0), 0);
      const money = v => `Rs ${fmt(Math.abs(v), 0)} ${v >= 0 ? "above" : "below"} should-cost`;
      const moveText = moving() ? `${ui.yarn === "*" ? "all yarns" : ui.yarn} ${pctSigned(Number(ui.pct), 0)}` : "";
      const tot = costedRows.length ? h("p", { class: "sub", style: "margin:10px 0 0" }, `${costedRows.length} costed rows carry a mill price${moving() ? ` (with the yarn move applied: ${moveText})` : ""}${uncosted.length ? `; ${uncosted.length} more ${uncosted.length === 1 ? "has" : "have"} a price but ${uncosted.length === 1 ? "is" : "are"} not costed (${uncosted.map(r => r.mill["Fab Code"] || "no code").join(", ")})` : ""}.`,
        metres ? [` On the ${fmt(metres, 0)} m costed${allM > metres ? ` of ${fmt(allM, 0)} m ordered` : ""}: `,
          h("b", {}, `Push ${part("push").length}, ${money(sumOf(part("push")))}`), "; ",
          `in line ${part("fair").length}, ${money(sumOf(part("fair")))} net; `,
          `below ${part("below").length}, Rs ${fmt(Math.abs(sumOf(part("below"))), 0)} under should-cost; `,
          `ask for the break-up ${part("ask").length}${part("check").length ? ` and check the quote ${part("check").length}` : ""}, not counted because the tool is unsure of them or the quote needs checking.`] : null,
        " Red: above the usual range for that fabric type (Push); grey: inside it. ", h("a", { href: "#pack", onclick: toPack }, "The negotiation pack"), " puts this on one printable page.") : null;
      box.replaceChildren(...[
        h("div", { class: "list-tools" },
          h("div", { class: "chips", role: "group", "aria-label": "Rows to show" }, chip("all", "All"), chip("above", "Push"), chip("notcosted", "Not costed"), chip("sums", "Mill's sums off")),
          h("div", { class: "chips", role: "group", "aria-label": "Column groups to show" }, h("span", { class: "sub", style: "margin:0;align-self:center" }, "Columns:"), Object.keys(data.groups).map(grp)),
          h("label", { for: "ls-stake", class: "opt" }, stakeBox, "Most at stake first"),
          filter),
        h("div", { class: "list-tools" },
          h("div", { class: "simbar" }, h("span", { class: "sub", style: "margin:0" }, "If yarn moves:"), yarnPick, pctBox, h("span", {}, "%"), ui.pct !== "" && Number(ui.pct) ? h("button", { class: "btn small", type: "button", onclick: () => { ui.pct = ""; load(); } }, "Clear") : null),
          h("div", { class: "actionbar" + (n ? " on" : "") }, h("b", {}, n ? `${n} selected` : "Tick rows to act on them"),
            h("button", { class: "btn small", type: "button", disabled: n !== 1 || null, onclick: () => openRow(picked[0]) }, "Open"),
            h("button", { class: "btn small", type: "button", disabled: n !== 2 || null, title: "Tick exactly two rows", onclick: () => { state.cmp = { a: picked[0].id, b: picked[1].id }; try { sessionStorage.setItem("rp-compare-ids", JSON.stringify([picked[0].id, picked[1].id])); } catch (e) { /* no handover */ } ctx.tab("compare"); } }, "Compare"),
            h("button", { class: "btn small danger", type: "button", disabled: !n || null, onclick: async e => {
              if (e.currentTarget.dataset.sure !== "1") { const b = e.currentTarget; b.dataset.sure = "1"; b.textContent = `Remove ${n}: sure?`; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = "Remove"; } }, 4000); return; }
              try { const r = await (await postJSON("/api/list/remove", { ids: [...ui.picked] })).json(); ui.picked.clear(); toast(`${r.removed} removed from the list`); load(); } catch (err) { toast(err.message, false); }
            } }, "Remove"),
            h("a", { class: "btn small", href: "#pack", title: "One printable page for the sheet: ticked rows, or the whole list", onclick: toPack }, "Negotiation pack"),
            h("button", { class: "btn small", type: "button", onclick: async () => download(await postJSON("/api/list/download", ui.pct !== "" && Number(ui.pct) ? { yarn_pct: { [ui.yarn]: Number(ui.pct) } } : {}), "RightPrice_fabric_list.xlsx") }, "Download list"))),
        data.rows.length ? h("p", { class: "list-hint" }, "Fabric code and should-cost stay in place; swipe the table sideways for the mill price, the gap, money at stake and what to do.") : null,
        data.rows.length ? h("div", { class: "table-wrap list-wrap", tabindex: "0", role: "region", "aria-label": "Fabric list" }, h("table", { class: "list" },
          h("thead", {}, h("tr", {}, h("th", { class: "stick s0" }, all), h("th", { class: "stick s1" }, "Fab Code"), h("th", { class: "n rp stick s2" }, "Should-cost"), sim ? [h("th", { class: "n rp" }, "With yarn moved"), h("th", { class: "n rp" }, "Change")] : null, h("th", { class: "n rp" }, "Mill price"), h("th", { class: "n rp", title: "Plus: the mill is above should-cost" }, sim ? "Mill above should-cost, yarn moved" : "Mill above should-cost"), h("th", { class: "n rp", title: "Gap per metre times the order quantity" }, "At stake"), h("th", { class: "rp" }, "What to do"), h("th", { class: "rp" }, "Mill's sums"), h("th", { class: "rp" }, "Remarks"), cols.map(c => h("th", { class: "millcol" }, c)))),
          h("tbody", {}, body.length ? body : h("tr", {}, h("td", { colspan: String(9 + cols.length + (sim ? 2 : 0)) }, "No row matches."))))) : h("p", { class: "empty" }, "The list is empty. Upload a file above, or cost a fabric and press Add to list."),
        tot].filter(Boolean));
    };

    const file = h("input", { type: "file", accept: ".xlsx,.xls", id: "bulk-file", style: "max-width:100%" });
    file.addEventListener("change", async () => {
      if (!file.files[0]) return;
      const fd = new FormData(); fd.append("file", file.files[0]);
      status.replaceChildren(h("p", { class: "empty" }, "Reading and costing every row..."));
      try { const r = await (await api("/api/list/upload", { method: "POST", body: fd })).json(); status.replaceChildren(...[h("div", { class: "notice info", style: "margin-top:12px" }, `${plural(r.added, "row")} added from a ${r.kind}.` + (r.already ? ` ${r.already} ${r.already === 1 ? "was" : "were"} already in the list and ${r.already === 1 ? "was" : "were"} not added again.` : "") + (r.added ? (r.not_costed ? ` ${r.not_costed} could not be costed yet; the reason is in Remarks.` : " All were costed.") : "")),
        r.alerts && r.alerts.length ? h("div", { class: "notice warn", style: "margin-top:12px" }, h("b", {}, `${plural(r.alerts.length, "row")} of this sheet ${r.alerts.length === 1 ? "needs" : "need"} a look before the price is accepted:`),
          h("ul", { class: "alert-list" }, ...[...r.alerts].reverse().map(a => h("li", {}, h("b", {}, a.code), ...a.flags.map(f => h("div", { class: "alert-flag" }, f.text))))),
          h("p", { class: "sub", style: "margin:6px 0 0" }, "They stay on the Dashboard, on the Right cost item of the left rail and on each fabric's Negotiation tab until marked seen or agreed.")) : r.added && r.alerts ? h("div", { class: "notice info", style: "margin-top:12px" }, "No quote alert on this sheet: no row is above its usual range, has sums that are off, repeats an order or is far below should-cost.") : null].filter(Boolean));
        RP.shell.alertsChanged(); file.value = ""; await load(); }
      catch (e) { status.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); }
    });
    await load();
    return [...pageHead("Bulk upload", "Upload a mill's price sheet as it comes, or the RightPrice template. Every row joins the list below, costed beside the mill's price."),
      h("div", { class: "card upload" }, h("div", { class: "upload-row" },
        h("div", {}, h("label", { for: "bulk-file", class: "lbl-strong" }, "Excel file"), file),
        h("p", { class: "sub", style: "margin:0;flex:1;min-width:240px" }, "A mill sheet is recognised by its headings (Fab Code, Base Price, EPI, PPI and the rest). NYD rows are listed but not costed until you open them and choose piece dyed, printed or bleached."),
        h("a", { class: "btn small", href: "/api/template" }, "RightPrice template")), status),
      h("div", { class: "card" }, h("div", { class: "card-head", style: "margin-bottom:8px" }, h("h2", {}, "Fabric list"), h("span", { class: "sub", style: "margin:0" }, "Re-costed on today's rates each time it opens. It stays until rows are removed.")), box)];
  });
})();
