/* Home > Pilot results: the 100% cotton purchase-order fabrics costed on the current rate master against the price
   paid, and the calibration draft (for review; nothing in it is applied). */
(function () {
  "use strict";
  const { h, fmt, pct, getJSON, dataTable, pageHead } = RP.kit;

  RP.page("pilot", { title: "Pilot results", section: "Home" }, async () => {
    let p;
    try { p = await getJSON("/api/pilot"); }
    catch (e) { return [...pageHead("Pilot results", "Should-cost against purchase order prices."), h("div", { class: "notice info" }, e.message + ".")]; }
    const o = p.Overall, c = o.columns, all = o.rows[0], hb = o.rows[1], v = (r, n) => r[c.indexOf(n)];
    const stat = (lbl, val, note) => h("div", { class: "card stat" }, h("div", { class: "lbl" }, lbl), h("div", { class: "val num" }, val), h("div", { class: "note" }, note));
    const sect = (title, key, sub, open) => p[key] ? h("details", { class: "card", open: open || null }, h("summary", {}, title), sub ? h("p", { class: "sub" }, sub) : null, dataTable(p[key], { label: title, filter: p[key].rows.length > 15 })) : null;
    return [...pageHead("Pilot results", "100% cotton wovens costed with the current rate master and compared with the price paid. Gap is the purchase price above should-cost."),
      p.as_run ? h("div", { class: "notice info" }, p.as_run) : null,          // stage 2: the pilot as run, ZLOI included
      h("div", { class: "grid g4" },
        stat("Fabrics costed", fmt(v(all, "Fabrics"), 0), `${fmt(v(hb, "Fabrics"), 0)} held back as the fair test`),
        stat("Median gap", v(all, "Median gap %").toFixed(1) + "%", `Held-back third ${v(hb, "Median gap %").toFixed(1)}%`),
        stat("Within 10%", pct(v(all, "Within 10%"), 0), `Held-back third ${pct(v(hb, "Within 10%"), 0)}`),
        stat("Within 20%", pct(v(all, "Within 20%"), 0), `Within 5%: ${pct(v(all, "Within 5%"), 0)}`)),
      sect("Overall and the known over-costed groups", "Overall", null, true),
      sect("By route and weave", "By route and weave", null, true),
      sect("By supplier", "By supplier"),
      sect("Mill rate card, step by step", "Rate card steps", "The same fabrics with the rate card inputs switched on one at a time, then two what-ifs."),
      sect("What the pilot could set from PLM", "Rate card inputs"),
      sect("Funnel", "Funnel"),
      h("div", { class: "notice info" }, "The sheets below are a calibration draft for review. Nothing in them has been applied to the rate master."),
      sect("Draft: order size", "Draft: Order size"), sect("Draft: weaving rates", "Draft: Weaving"), sect("Draft: printing", "Draft: Printing"), sect("Draft: held-back test", "Draft: Held-back test")].filter(Boolean);
  });
})();
