/* New cost > Compare: two fabrics from the list (or the one open in Create cost) side by side, both on today's rates:
   every group and sub-cost, the difference, a sentence naming the largest differences, and the choices that differ. */
(function () {
  "use strict";
  const { h, fmt, rs, day, pct, blank, postJSON, dataTable, pageHead, GROUP_COLOR } = RP.kit;
  const state = RP.state;

  RP.page("compare", { title: "Compare", popup: true }, async (arg, ctx) => {
    const { ready, payload } = RP.cost;
    const list = state.list = await (await postJSON("/api/list", {})).json();
    const sources = [];
    if (state.sel && ready(state.sel)) sources.push({ id: "now", label: "Open in Create cost now" + (state.sel["Fabric code"] ? ": " + state.sel["Fabric code"] : ""), inputs: payload(state.sel) });
    for (const r of list.rows) if (r.inputs && !r.problems.length) sources.push({ id: r.id, label: [r.mill["Fab Code"], r.supplier, r.description, "added " + day(r.added)].filter(v => !blank(v)).join(" · "), inputs: r.inputs });
    const head = pageHead("Compare", "Two fabrics from the list side by side, both on today's rates: two suppliers' quotes for one fabric, or one fabric built two ways.");
    if (sources.length < 2) return [...head, h("div", { class: "card" }, h("p", { class: "empty" }, "Comparing needs two costed fabrics in the list. Upload a sheet under Bulk upload, or cost a fabric and press Add to list; a fabric open on Create cost counts as one."), h("a", { class: "btn primary", href: "#cost", onclick: e => { e.preventDefault(); ctx.tab("cost"); } }, "Create cost"))];
    const pickBox = (id, label, start) => { const sel = h("select", { id }, sources.map(s => h("option", { value: s.id }, s.label))); sel.value = sources[start].id; return [h("div", { class: "field" }, h("label", { for: id }, label), sel), sel]; };
    state.cmp = state.cmp || {};
    // two rows handed over from Right cost or the list
    try { const ids = JSON.parse(sessionStorage.getItem("rp-compare-ids") || "null"); sessionStorage.removeItem("rp-compare-ids"); if (ids && ids.length === 2) state.cmp = { a: ids[0], b: ids[1] }; } catch (e) { /* none handed over */ }
    const startA = Math.max(0, sources.findIndex(s => s.id === state.cmp.a)), startB = sources.findIndex(s => s.id === state.cmp.b);
    const [fa, sa] = pickBox("cmp-a", "A", startA), [fb, sb] = pickBox("cmp-b", "B", startB >= 0 ? startB : (startA === 0 ? 1 : 0));
    const out = h("div", { "aria-live": "polite", style: "margin-top:16px" });
    let turn = 0;
    const run = async () => {
      const mine = ++turn;
      state.cmp = { a: sa.value, b: sb.value };
      const A = sources.find(s => s.id === sa.value), B = sources.find(s => s.id === sb.value);
      if (A.id === B.id) return out.replaceChildren(h("div", { class: "notice info" }, "Choose two different costings."));
      out.replaceChildren(h("p", { class: "empty" }, "Costing both..."));
      try { const [ra, rb] = await Promise.all([A, B].map(async s => (await postJSON("/api/cost", s.inputs)).json())); if (mine === turn) out.replaceChildren(...compareView(A, ra, B, rb)); }
      catch (e) { if (mine === turn) out.replaceChildren(h("div", { class: "notice err", role: "alert" }, "One of these can no longer be costed: " + e.message)); }
    };
    sa.addEventListener("change", run); sb.addEventListener("change", run); run();
    return [...head, h("div", { class: "card" }, h("div", { class: "fields" }, fa, fb), h("div", { class: "row-actions" }, h("button", { class: "btn small", type: "button", onclick: () => { const t = sa.value; sa.value = sb.value; sb.value = t; run(); } }, "Swap A and B"))), out];
  });

  function compareView(A, ra, B, rb) {
    const delta = (a, b) => { const dlt = b - a; return Math.abs(dlt) < 0.005 ? h("span", { class: "tag flat" }, "same") : h("span", { class: "tag " + (dlt > 0 ? "down" : "up") }, `${dlt > 0 ? "+" : "−"}${fmt(Math.abs(dlt))}${a ? ` (${dlt > 0 ? "+" : "−"}${pct(Math.abs(dlt) / Math.abs(a))})` : ""}`); };
    const side = (tagText, S, r) => h("div", { class: "card hero" }, h("div", { class: "lbl" }, h("span", { class: "tag ok" }, tagText), " ", S.label),
      h("div", { class: "big num" }, `${rs(r.total_per_m)} / m`),
      h("div", { class: "facts" }, h("span", {}, [S.inputs.Route, S.inputs.Weave, `${S.inputs["Warp yarn"]} × ${S.inputs["Weft yarn"]}`, `${S.inputs.EPI} × ${S.inputs.PPI}`, `${S.inputs["Finished width (in)"]} in`].join(" · "))),
      h("div", { class: "facts num" }, h("span", {}, `${rs(r.per_kg, 0)} / kg`), h("span", {}, `about ${fmt(r.gsm, 0)} g/m²`)),
      r.quote !== null ? h("div", { class: "quote" }, h("span", { class: "tag flat" }, `Quote ${rs(r.quote)}/m, ${pct(Math.abs(r.gap_pct))} ${r.gap >= 0 ? "above" : "below"} its should-cost today`)) : null,
      r.placeholders.length ? h("div", { class: "quote" }, h("span", { class: "tag warn", title: r.placeholders.join(", ") }, "⚠ provisional: placeholder rates used")) : null);
    const dlt = rb.total_per_m - ra.total_per_m;
    const build = ["Route", "Weave", "Warp yarn", "Weft yarn", "EPI", "PPI", "Finished width (in)", "Warp count", "Weft count", "Count system"];
    const otherFabric = build.filter(k => String(A.inputs[k] ?? "") !== String(B.inputs[k] ?? ""));
    const caution = otherFabric.length ? h("div", { class: "notice", style: "margin-top:16px" }, h("b", {}, "These are not the same fabric. "), `They differ in ${otherFabric.join(", ")}, so the difference below is the fabric as much as the supplier.`) : null;
    const verdict = h("div", { class: "notice info", style: "margin-top:16px" }, Math.abs(dlt) < 0.005 ? "A and B have the same should-cost." : [h("b", {}, `B's should-cost is ${rs(Math.abs(dlt))} per metre (${pct(Math.abs(dlt) / ra.total_per_m)}) ${dlt > 0 ? "higher" : "lower"} than A's. `),
      (() => { const top = ra.buckets.map((b, i) => ({ name: b.name, d: rb.buckets[i].amount - b.amount })).filter(x => Math.abs(x.d) >= 0.005).sort((p, q) => Math.abs(q.d) - Math.abs(p.d)).slice(0, 3); return top.length ? "Largest differences, B against A: " + top.map(x => `${x.name} ${x.d > 0 ? "+" : "−"}${fmt(Math.abs(x.d))}`).join(", ") + "." : ""; })()]);
    const top = Math.max(...ra.buckets.map(b => Math.abs(b.amount)), ...rb.buckets.map(b => Math.abs(b.amount)), 0.01);
    const rows = [];
    ra.buckets.forEach((b, i) => {
      const c = rb.buckets[i], color = GROUP_COLOR[i % 8];
      const bars = h("div", { class: "cmp-bars", "aria-hidden": "true" }, h("div", { class: "cmp-bar", style: `width:${Math.abs(b.amount) / top * 100}%;background:var(${color})` }), h("div", { class: "cmp-bar b", style: `width:${Math.abs(c.amount) / top * 100}%;background:var(${color})` }));
      rows.push(h("tr", { class: "grp" }, h("td", {}, b.name), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, fmt(c.amount)), h("td", { class: "n" }, delta(b.amount, c.amount)), h("td", { class: "cmp-cell" }, bars)));
      b.lines.forEach((l, j) => { const m = c.lines[j]; if (Math.abs(l.amount) >= 0.005 || Math.abs(m.amount) >= 0.005) rows.push(h("tr", {}, h("td", { style: "padding-left:26px;color:var(--muted)" }, l.name), h("td", { class: "n" }, fmt(l.amount)), h("td", { class: "n" }, fmt(m.amount)), h("td", { class: "n" }, Math.abs(m.amount - l.amount) < 0.005 ? "" : (m.amount > l.amount ? "+" : "−") + fmt(Math.abs(m.amount - l.amount))), h("td", {}))); });
    });
    rows.push(h("tr", { class: "grp" }, h("td", {}, "Should-cost"), h("td", { class: "n" }, fmt(ra.total_per_m)), h("td", { class: "n" }, fmt(rb.total_per_m)), h("td", { class: "n" }, delta(ra.total_per_m, rb.total_per_m)), h("td", {})));
    if (ra.quote !== null || rb.quote !== null) {
      const q = r => r.quote === null ? "—" : fmt(r.quote), g = r => r.quote === null ? "—" : (r.gap >= 0 ? "+" : "−") + fmt(Math.abs(r.gap)) + ` (${r.gap >= 0 ? "+" : "−"}${pct(Math.abs(r.gap_pct))})`;
      rows.push(h("tr", { class: "grp" }, h("td", {}, "Supplier's quote"), h("td", { class: "n" }, q(ra)), h("td", { class: "n" }, q(rb)), h("td", { class: "n" }, ra.quote !== null && rb.quote !== null ? delta(ra.quote, rb.quote) : ""), h("td", {})));
      rows.push(h("tr", {}, h("td", { style: "padding-left:26px;color:var(--muted)" }, "Quote against its own should-cost"), h("td", { class: "n" }, g(ra)), h("td", { class: "n" }, g(rb)), h("td", {}), h("td", {})));
    }
    // a choice left blank means its default (the first value on its list), so blank against the default is not a difference
    const eff = (S, k) => { const v = S.inputs[k]; return blank(v) ? String((state.meta.lists[k] || [""])[0]) : String(v); };
    const keys = [...new Set([...Object.keys(A.inputs), ...Object.keys(B.inputs)])].filter(k => eff(A, k) !== eff(B, k));
    const differ = keys.length ? dataTable({ columns: ["Choice", "A", "B"], rows: keys.map(k => [k, String(A.inputs[k] ?? "—"), String(B.inputs[k] ?? "—")]) }, { label: "Choices that differ" }) : h("p", { class: "empty" }, "The two were built from the same choices.");
    return [h("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(280px,1fr))" }, side("A", A, ra), side("B", B, rb)), caution, verdict,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Cost by group and sub-cost, Rs per metre"), h("span", { class: "sub", style: "margin:0" }, "Red: B is higher. Green: B is lower. Upper bar A, lower bar B")),
        h("div", { class: "table-wrap tall" }, h("table", { class: "cmp" }, h("thead", {}, h("tr", {}, h("th", {}, "Cost"), h("th", { class: "n" }, "A"), h("th", { class: "n" }, "B"), h("th", { class: "n" }, "B minus A"), h("th", { class: "cmp-cell" }, ""))), h("tbody", {}, rows)))),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Choices that differ")), differ)].filter(Boolean);
  }
})();
