/* Prices > Calculation settings: shrinkage, reed space factor, mill tiers, order size slabs, supplier benchmarks.
   #settings/<sheet> opens on that table. */
(function () {
  "use strict";
  const page = RP.kit.tabbed("Settings", "Calculation settings, mill tiers and order size slabs. Method: the corrected method of the V1 workbook; price basis ex-mill, so freight is left out.",
    ["Settings", "Mill_Tier", "Order_Slab", "Supplier_Benchmarks"]);
  RP.page("settings", { title: "Calculation settings", section: "Prices" }, want => page(want));
})();
