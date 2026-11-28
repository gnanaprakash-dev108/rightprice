/* Prices > Mill rate card: the optional upcharges of Arvind's rate card (print method, dobby, weft, quantity terms,
   finish), rupees per metre on the price. #ratecard/<sheet> opens on that table. */
(function () {
  "use strict";
  const page = RP.kit.tabbed("Mill rate card", "Optional upcharges from Arvind's mill rate card of 23 Nov 2026 (confirmed 25 Nov). Each is rupees per metre on the price and is not marked up.",
    ["Print_Methods", "Dobby_Charges", "Weft_Options", "Quantity_Terms", "Finishing_Rates"]);
  RP.page("ratecard", { title: "Mill rate card", section: "Prices" }, want => page(want));
})();
