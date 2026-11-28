/* Prices > Exchange rates (GP, 28 Nov 2026): rupees per unit of each currency, by month, so an import purchase line is shown
   in rupees, apart from the rupee figures. The RBI (FBIL) reference rate by default; the rate actually paid, where it is
   entered, holds for that month (the RBI rate kept, marked replaced). Nothing is seeded: a month with no rate leaves the
   rupee price blank, and says why. Entering a rate is a rates editor's or an admin's action. */
(function () {
  "use strict";
  const { $, h, fmt, day, getJSON, postJSON, toast, dataTable, pageHead, can } = RP.kit;
  const monthWords = ym => new Date(ym + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "numeric" });

  RP.page("fx", { title: "Exchange rates", section: "Prices" }, async (arg, ctx) => {
    let d;
    try { d = await getJSON("/api/fx-rates"); }
    catch (e) { return [...pageHead("Exchange rates", "Rupees per unit of each currency, by month."), h("div", { class: "notice" }, e.message)]; }
    const held = d.rates.filter(r => r.in_force), kept = d.rates.filter(r => !r.in_force);
    const need = d.needed;
    return [...pageHead("Exchange rates", "Rupees per unit of each currency, by month: the import purchase lines are shown in rupees on their order month's rate, apart from every rupee figure (never in a usual range or a verdict)."),
      h("div", { class: "notice info" }, d.rule),
      need.length ? h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "What the purchase history needs"),
        h("span", { class: "sub" }, d.missing ? `${d.missing} of ${need.length} months have no rate yet: their import lines show no rupee price` : "every month has a rate")),
        dataTable({ columns: ["Currency", "Month", "Import lines", "Rate in force (Rs)", "Source"], rows: need.map(x => [x.currency, monthWords(x.month), x.lines, x.rate === null ? "no rate yet" : x.rate, x.source || ""]) },
          { label: "Months and currencies the purchase history needs" })) : h("p", { class: "sub" }, "No import line is in the purchase history yet."),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Rates in force")),
        held.length ? dataTable({ columns: ["Currency", "Month", "Rs per unit", "Source", "Note", "Entered by", "On"], rows: held.map(r => [r.currency, monthWords(r.month), r.rate, r.source, r.note, r.entered_by, day(r.entered_at)]) }, { label: "Rates in force" })
          : h("p", { class: "empty" }, "No rate entered yet. The RBI reference rates (the monthly averages) are to come from GP; until then import lines show their own currency only.")),
      kept.length ? h("details", { class: "card" }, h("summary", {}, `Kept, not in force (${kept.length})`),
        dataTable({ columns: ["Currency", "Month", "Rs per unit", "Source", "Why", "Entered by", "On"], rows: kept.map(r => [r.currency, monthWords(r.month), r.rate, r.source, r.removed_why || "", r.entered_by, day(r.entered_at)]) }, { label: "Rates kept" })) : null,
      can("do:edit_rates") ? rateForm(ctx, d) : null];
  });

  function rateForm(ctx, d) {
    const f = (id, label, el) => h("div", { class: "field" }, h("label", { for: id }, label), el);
    const msg = h("div", { "aria-live": "polite" });
    const src = h("select", { id: "fx-source" }, d.sources.map(s => h("option", { value: s }, s)), h("option", { value: "" }, "No source (a Placeholder)"));
    return h("form", { class: "card", onsubmit: async e => {
      e.preventDefault();
      try {
        const r = await (await postJSON("/api/fx-rates", { currency: $("#fx-cur").value, month: $("#fx-month").value, rate: $("#fx-rate").value, source: src.value, note: $("#fx-note").value })).json();
        toast(`Rate entered: ${r.currency} ${monthWords(r.month)} Rs ${fmt(r.rate, 4)}` + (r.in_force ? "" : " (kept: the rate paid holds for that month)")); ctx.reload();
      } catch (err) { msg.replaceChildren(h("div", { class: "notice err", role: "alert" }, err.message)); }
    } }, h("h3", {}, "Enter a rate"),
      h("div", { class: "fields", style: "grid-template-columns:repeat(auto-fit,minmax(150px,1fr));align-items:end" },
        f("fx-cur", "Currency", h("input", { id: "fx-cur", type: "text", maxlength: "3", required: true, placeholder: "USD" })),
        f("fx-month", "Month", h("input", { id: "fx-month", type: "month", required: true })),
        f("fx-rate", "Rupees per unit", h("input", { id: "fx-rate", type: "number", min: "0.01", step: "any", required: true })),
        f("fx-source", "Source", src),
        f("fx-note", "Where the figure is from", h("input", { id: "fx-note", type: "text", placeholder: "RBI circular, bank advice ..." })),
        h("button", { class: "btn primary", type: "submit" }, "Enter the rate")), msg);
  }
})();
