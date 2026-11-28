/* Prices > Mill cost sheets: a mill's own figures for a fabric, set beside the rate master, and drafted into rate
   changes. Nothing changes a rate until GP ticks drafts and presses Apply, which keeps a dated copy of the rate master. */
(function () {
  "use strict";
  const { h, fmt, rs, pct, pctSigned, plural, api, getJSON, postJSON, pageHead, can } = RP.kit;

  // a button that asks once more before it acts
  function sureButton(label, ask, run) {
    const b = h("button", { class: "btn small", type: "button", onclick: async () => {
      if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = ask; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = label; } }, 4000); return; }
      await run();
    } }, label);
    return b;
  }

  RP.page("costsheets", { title: "Mill cost sheets", section: "Prices" }, async () => {
    const box = h("div"), status = h("div", { "aria-live": "polite" });
    const picked = new Set(), apply = can("do:apply_drafts"), change = can("do:upload");      // what this role may do (stage 3)
    const fig = (v, unit) => v === null || v === undefined ? "—" : unit === "%" ? pct(v, 1) : unit === "Rs/pick" ? "Rs " + Number(v).toFixed(3) : "Rs " + fmt(v, unit === "Rs/m" ? 2 : 0);
    const load = async () => {
      const d = await getJSON("/api/costsheet");
      if (!d.rows.length) return box.replaceChildren(h("div", { class: "card" }, h("p", { class: "empty" }, "No mill cost sheet yet. Download the template, ask the mill to fill one row per fabric with its own figures, and upload it here.")));
      const drafts = d.drafts.map(x => {
        const cb = h("input", { type: "checkbox", "aria-label": "Apply " + x.label }); cb.checked = picked.has(x.id);
        cb.addEventListener("change", () => { cb.checked ? picked.add(x.id) : picked.delete(x.id); applyBtn.disabled = !picked.size; applyBtn.textContent = picked.size ? `Apply ${plural(picked.size, "draft")}` : "Apply"; });
        const show = v => x.pct ? pct(v, 1) : x.table === "Weaving_Rates" ? "Rs " + Number(v).toFixed(3) : "Rs " + fmt(v, Number.isInteger(Number(v)) ? 0 : 2);
        // a percentage moves in points; a rupee rate in per cent; from nothing it is new
        const move = x.pct ? `${x.proposed >= x.now ? "+" : "−"}${(Math.abs(x.proposed - x.now) * 100).toFixed(1)} points` : x.now ? pctSigned((x.proposed / x.now - 1) * 100) : "new";
        return h("tr", {}, h("td", {}, apply ? cb : null), h("td", { class: "wrap" }, x.label, h("div", { class: "sub", style: "margin:2px 0 0;font-size:12px" }, "Changes " + x.scope), x.mill_count === 1 ? h("div", { class: "sub", style: "margin:2px 0 0;font-size:12px;color:var(--amber)" }, "From one mill only") : null),
          h("td", { class: "n" }, show(x.now)), h("td", { class: "n" }, h("b", {}, show(x.proposed))), h("td", { class: "n" }, move), h("td", { class: "wrap" }, x.basis),
          h("td", { class: "n" }, `${plural(x.mill_count, "mill")}, ${plural(x.sheets, "sheet")}`), h("td", { class: "wrap" }, x.values.map(show).join(", ") + " · " + x.rows.join(", ")));
      });
      const applyBtn = h("button", { class: "btn primary", type: "button", disabled: true, onclick: async e => {
        const b = e.currentTarget;
        if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = `Change ${plural(picked.size, "rate")} in the rate master: sure?`; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = `Apply ${plural(picked.size, "draft")}`; } }, 5000); return; }
        try { const r = await (await postJSON("/api/costsheet/apply", { ids: [...picked], expect: Object.fromEntries(d.drafts.filter(x => picked.has(x.id)).map(x => [x.id, { now: x.now, proposed: x.proposed }])) })).json(); picked.clear(); RP.state.meta = await getJSON("/api/meta");
          status.replaceChildren(h("div", { class: "notice info" }, h("b", {}, "Applied. "), r.applied.join("; ") + `. The rate master as it was is kept on the server, beside the rate master, as "${r.backup}".`)); load(); }
        catch (err) { status.replaceChildren(h("div", { class: "notice err", role: "alert" }, err.message)); picked.clear(); load(); }   // the drafts as they are now
      } }, "Apply");
      const rows = d.rows.map(r => h("details", { class: "card cs-row" },
        h("summary", {}, h("b", {}, [r.mill, r.code].filter(Boolean).join(" · ") || "Row"), " ",
          r.problems.length ? h("span", { class: "tag warn", style: "white-space:normal" }, "not read: " + r.problems[0]) :
          h("span", { class: "sub", style: "margin:0" }, `should-cost ${rs(r.should)} on the rate master · ${rs(r.own)} on the mill's own figures` + (r.partial ? " (some of its figures not used: see the notes)" : "") + (r.price !== null ? ` · the mill's price ${rs(r.price)}` : "")),
          r.own_gap !== null && r.own_gap !== undefined && Math.abs(r.own_gap) >= 0.5 ? h("span", { class: "tag down", style: "margin-left:8px;white-space:normal" }, `its own figures come to ${rs(Math.abs(r.own_gap))} ${r.own_gap > 0 ? "less" : "more"} than its price`) : null),
        (r.notes || []).length ? h("ul", { class: "sub", style: "margin:0 0 8px;padding-left:18px" }, r.notes.map(n => h("li", {}, n))) : null,
        r.problems.length ? h("p", { class: "sub" }, "Not read: " + r.problems.join("; ") + ".") : h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Figure"), h("th", { class: "n" }, "The mill's"), h("th", { class: "n" }, "Rate master"), h("th", {}, "Basis of the rate master's"), h("th", {}, "Where it lives"))),
          h("tbody", {}, r.figures.map(f => h("tr", {}, h("td", {}, f.column), h("td", { class: "n" }, fig(f.mill, f.unit)), h("td", { class: "n" }, f.ignored ? "not used" : fig(f.now, f.unit)), h("td", { class: "wrap" }, f.basis), h("td", { class: "wrap" }, f.target || "—")))))),
        h("div", { style: "display:flex;gap:8px;margin-top:8px;flex-wrap:wrap" },
          !change ? null : sureButton("Remove this row", "Remove this row: sure?", async () => { await postJSON("/api/costsheet/remove", { ids: [r.id] }); status.replaceChildren(h("div", { class: "notice info" }, "Row removed.")); load(); }),
          r.upload && change ? sureButton(`Remove every row of ${r.upload}`, `Remove every row of ${r.upload}: sure?`, async () => { const x = await (await postJSON("/api/costsheet/remove", { upload: r.upload })).json(); status.replaceChildren(h("div", { class: "notice info" }, `${plural(x.removed, "row")} removed.`)); load(); }) : null)));
      box.replaceChildren(
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Draft rate changes"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Each is the middle of the mills' figures for that rate, where they differ from the rate master. Nothing changes until you tick drafts and press Apply; the rate master before the change is kept with the date.")), apply ? applyBtn : null),
          drafts.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Rate"), h("th", { class: "n" }, "Now"), h("th", { class: "n" }, "Draft"), h("th", { class: "n" }, "Change"), h("th", {}, "Basis now"), h("th", { class: "n" }, "Behind it"), h("th", {}, "The mills' figures"))), h("tbody", {}, drafts)))
            : h("p", { class: "empty" }, "Every figure on the sheets matches the rate master.")),
        h("h2", { style: "margin:18px 0 8px" }, `${plural(d.rows.length, "row")} from the mills`), ...rows);
    };
    const file = h("input", { type: "file", accept: ".xlsx,.xls", id: "cs-file" });
    file.addEventListener("change", async () => {
      if (!file.files[0]) return;
      const fd = new FormData(); fd.append("file", file.files[0]);
      try { const r = await (await api("/api/costsheet/upload", { method: "POST", body: fd })).json(); status.replaceChildren(h("div", { class: r.not_read ? "notice" : "notice info" }, `${plural(r.added, "row")} brought in` + (r.replaced ? `, in place of ${plural(r.replaced, "earlier row")} from the same mills and fabrics` : "") + (r.not_read ? `. ${plural(r.not_read, "row")} could not be read; the reason is on each` : "") + ".")); file.value = ""; load(); }
      catch (e) { status.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); }
    });
    await load();
    return [...pageHead("Mill cost sheets", "A mill's own figures for a fabric (yarn, sizing, weaving, dyeing, finishing, wastage, overhead, margin), set beside the rate master. Where the tool uses a placeholder, this is how a real figure comes in."),
      h("div", { class: "card upload" }, h("div", { class: "upload-row" }, change ? h("div", {}, h("label", { for: "cs-file", class: "lbl-strong" }, "Mill's cost sheet (Excel)"), file) : null,
        h("p", { class: "sub", style: "margin:0;flex:1;min-width:240px" }, "One row per fabric in the template's columns. Percentages as numbers (7 for 7%)."),
        h("a", { class: "btn small", href: "/api/costsheet/template" }, "Cost sheet template")), status), box];
  });
})();
