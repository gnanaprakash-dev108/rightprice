/* Prices > Bring in prices: yarn prices from a file, a web page or a price service. Every route ends in a table a
   person reviews; only then is anything added to the market reference. The yarn master is never changed here. */
(function () {
  "use strict";
  const { $, h, api, postJSON, toast, dataTable, pageHead } = RP.kit;

  RP.page("intake", { title: "Bring in prices", section: "Prices" }, async () => {
    const work = h("div", { "aria-live": "polite" });
    const fail = e => work.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message));
    const busy = () => work.replaceChildren(h("p", { class: "empty" }, "Reading..."));
    const COLS = ["Date", "Yarn", "Count", "Low Rs/kg", "High Rs/kg", "Source"];
    const review = (data) => {            // every source ends here: rows a person checks before they are added
      const body = h("tbody");
      const addRow = r => { const tr = h("tr", {}, COLS.map((c, i) => h("td", {}, h("input", { class: "cell" + (i === 3 || i === 4 ? " n" : ""), type: i === 3 || i === 4 ? "number" : "text", step: "any", value: r ? (r[i] ?? "") : (i === 0 ? new Date().toISOString().slice(0, 10) : ""), "aria-label": c }))), h("td", {}, h("button", { class: "icon-btn sm", type: "button", "aria-label": "Remove this row", onclick: () => tr.remove() }, "×"))); body.append(tr); return tr; };
      data.rows.forEach(addRow);
      const msg = h("div");
      work.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Review before adding")),
        data.note ? h("div", { class: "notice info", style: "margin:0 0 14px" }, data.note) : null,
        h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Rows to review" }, h("table", { class: "edit" }, h("thead", {}, h("tr", {}, COLS.map(c => h("th", { scope: "col" }, c)), h("th", {}))), body)), msg,
        h("div", { class: "row-actions" },
          h("button", { class: "btn primary", type: "button", onclick: async () => {
            const rows = [...body.rows].map(tr => [...tr.querySelectorAll("input")].map(i => i.value.trim() === "" ? null : i.value.trim()));
            try { const r = await (await postJSON("/api/intake/add", { rows, source: data.source })).json(); RP.state.dash = null; toast(`${r.added} rows added to the market reference`); location.hash = "#yarn"; }
            catch (e) { msg.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); }
          } }, "Add to market reference"),
          h("button", { class: "btn", type: "button", onclick: () => addRow(null).querySelector("input").focus() }, "Add a row"),
          h("button", { class: "btn", type: "button", onclick: () => work.replaceChildren() }, "Discard")),
        h("p", { class: "sub", style: "margin:12px 0 0" }, "Each row needs a count and a rate. Nothing reaches the market reference until you press Add, and the yarn master is never changed from here.")));
    };
    const mapper = (data) => {            // a table was read: say which column is which
      const names = Object.keys(data.sheets);
      const pickSheet = h("select", { id: "map-sheet" }, names.map(n => h("option", { value: n }, n)));
      const preview = h("div"), picks = h("div", { class: "fields", style: "grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-top:14px" });
      const sel = {};
      const draw = () => {
        const t = data.sheets[pickSheet.value];
        preview.replaceChildren(dataTable(t, { label: "First rows of the file" }));
        picks.replaceChildren(...[["count", "Count column"], ["low", "Rate (or low) column"], ["high", "High rate column"], ["yarn", "Yarn description column"], ["date", "Date column"]].map(([k, label]) => {
          sel[k] = h("select", { id: "map-" + k }, h("option", { value: "" }, k === "count" || k === "low" ? "Choose..." : "None"), t.columns.map(c => h("option", { value: c }, c)));
          return h("div", { class: "field" }, h("label", { for: "map-" + k }, label), sel[k]);
        }));
      };
      pickSheet.addEventListener("change", draw); draw();
      const msg = h("div");
      work.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Which column is which?"), names.length > 1 ? h("div", { class: "field", style: "min-width:220px" }, h("label", { for: "map-sheet" }, "Sheet or table"), pickSheet) : null),
        preview, picks, msg,
        h("div", { class: "row-actions" }, h("button", { class: "btn primary", type: "button", onclick: async () => {
          try { const r = await (await postJSON("/api/intake/map", { token: data.token, sheet: pickSheet.value, count: sel.count.value, low: sel.low.value, high: sel.high.value, yarn: sel.yarn.value, date: sel.date.value })).json(); review(Object.assign(r, { source: data.source })); }
          catch (e) { msg.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); }
        } }, "Send to review"))));
    };
    const got = d => d.kind === "tables" ? mapper(d) : review(d);
    const file = h("input", { type: "file", id: "in-file", accept: ".xlsx,.xls,.csv,.pdf,.png,.jpg,.jpeg,.webp" });
    file.addEventListener("change", async () => { if (!file.files[0]) return; const fd = new FormData(); fd.append("file", file.files[0]); busy(); try { got(await (await api("/api/intake/file", { method: "POST", body: fd })).json()); } catch (e) { fail(e); } });
    const inp = (id, label, attrs) => h("div", { class: "field" }, h("label", { for: id }, label), h("input", Object.assign({ id, type: "text" }, attrs)));
    const send = (path, body) => async e => { e.preventDefault(); busy(); try { got(await (await postJSON(path, body())).json()); } catch (err) { fail(err); } };
    return [...pageHead("Bring in yarn prices", "From a price list, a circular, a web page or a price service. Every route ends in a table you review; only then is anything added to the market reference."),
      h("div", { class: "grid g3" },
        h("div", { class: "card" }, h("h3", {}, "A file"), h("label", { for: "in-file", class: "sub", style: "display:block;margin-bottom:8px" }, "Excel, CSV, PDF or a picture of a price list"), file, h("p", { class: "sub", style: "margin:10px 0 0" }, "A scanned PDF or a picture cannot be read; it is kept as the source and you type its rates.")),
        h("form", { class: "card", onsubmit: send("/api/intake/link", () => ({ url: $("#in-url").value })) }, h("h3", {}, "A web page"), inp("in-url", "Page address", { placeholder: "https://...", required: true }), h("div", { class: "row-actions" }, h("button", { class: "btn", type: "submit" }, "Read page")), h("p", { class: "sub", style: "margin:10px 0 0" }, "Pages behind a login cannot be read.")),
        h("form", { class: "card", onsubmit: send("/api/intake/api", () => ({ url: $("#in-api").value, header_name: $("#in-hn").value, header_value: $("#in-hv").value })) }, h("h3", {}, "A price service (JSON)"), inp("in-api", "Endpoint address", { required: true }), h("div", { class: "fields", style: "margin-top:10px" }, inp("in-hn", "Header name", { placeholder: "x-api-key" }), inp("in-hv", "Header value", { type: "password", autocomplete: "off" })), h("div", { class: "row-actions" }, h("button", { class: "btn", type: "submit" }, "Call")), h("p", { class: "sub", style: "margin:10px 0 0" }, "The key is used for this one call and is not saved."))),
      h("div", { style: "margin-top:16px" }, work)];
  });
})();
