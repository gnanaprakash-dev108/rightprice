/* Prices > Yarn prices: the yarn master (used in every costing; edited here), the market reference (for comparison
   only, never used in a costing), and the master set against the market. #yarn/<yarn key> opens it filtered. */
(function () {
  "use strict";
  const { h, getJSON, dataTable, tableCard, pageHead } = RP.kit;

  RP.page("yarn", { title: "Yarn prices", section: "Prices" }, async (query) => {
    const [yrCard, mkCard, d] = await Promise.all([
      tableCard("Yarn_Rates", "Yarn master", { query }),
      tableCard("Market_Yarn", "Market reference", { extra: h("a", { class: "btn", href: "#intake" }, "Bring in prices") }),
      getJSON("/api/dashboard")]);
    RP.state.dash = d;
    const cmp = { columns: ["Yarn key", "Master Rs/kg", "Market low", "Market high", "Position"],
      rows: d.yarns.filter(y => y.position).map(y => [y.key, y.rate, y.market_low, y.market_high, { inside: "Inside range", above: "Above market", below: "Below market" }[y.position]]) };
    return [...pageHead("Yarn prices", "The yarn master is used in every costing; edit a rate and its date, then save. The market reference is for comparison only and is never used in a costing."),
      yrCard,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Master against market, combed compact cotton")), dataTable(cmp, { label: "Master against market", empty: "No yarn in the master has a market reference yet." })),
      mkCard];
  });
})();
