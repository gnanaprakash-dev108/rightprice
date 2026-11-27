/* Prices > Rate tables: every drop-down choice looks up a number here; one table at a time, edited in place.
   #rates/<sheet> opens on that table. */
(function () {
  "use strict";
  const page = RP.kit.tabbed("Rate tables", "Every drop-down choice looks up a number here. The rate master workbook is the source of truth for all of them.",
    ["Weaving_Rates", "Weaving_Uplifts", "Sizing_Rates", "Yarn_Dyeing", "Piece_Dyeing", "Finishing_Rates", "Class_Defaults", "Weaves", "Content_Groups"]);
  RP.page("rates", { title: "Rate tables", section: "Prices" }, want => page(want));
})();
