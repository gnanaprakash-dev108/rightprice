/* Prices > Cotton prices: the Shankar-6 history (rupees per candy), its chart, and a form to add a price. */
(function () {
  "use strict";
  const { $, h, fmt, day, pct, getJSON, postJSON, toast, showTip, hideTip, dataTable, pageHead } = RP.kit;

  RP.page("cotton", { title: "Cotton prices", section: "Prices" }, async (arg, ctx) => {
    const c = await getJSON("/api/cotton");
    const pts = c.points.map(([d, p]) => [new Date(d), p]);
    if (!pts.length) return [...pageHead("Cotton prices", "Shankar-6 history."), h("p", { class: "empty" }, "No cotton price history loaded yet.")];
    const last = pts[pts.length - 1], back = days => { const t = last[0] - days * 864e5; return pts.filter(p => p[0] <= t).pop(); };
    const y1 = back(365), m1 = back(30);
    const chg = p => p ? (last[1] / p[1] - 1) : null;
    const tag = v => v === null ? "—" : h("span", { class: "tag " + (v >= 0 ? "down" : "up") }, `${v >= 0 ? "▲" : "▼"} ${pct(Math.abs(v))}`);
    const stat = (lbl, val, note) => h("div", { class: "card stat" }, h("div", { class: "lbl" }, lbl), h("div", { class: "val num" }, val), note ? h("div", { class: "note" }, note) : null);
    const age = Math.round((Date.now() - last[0]) / 864e5);
    const box = h("div", { class: "chart" });
    let range = "3Y";
    const draw = () => { const days = { "1Y": 365, "3Y": 1095, All: 1e6 }[range]; box.replaceChildren(lineChart(pts.filter(p => p[0] >= last[0] - days * 864e5), c.unit)); };
    const chips = h("div", { class: "seg", role: "group", "aria-label": "Period" });
    for (const r of ["1Y", "3Y", "All"]) chips.append(h("button", { type: "button", "aria-pressed": String(r === range), onclick: e => { range = r; [...chips.children].forEach(b => b.setAttribute("aria-pressed", String(b === e.target))); draw(); } }, r));
    draw();
    return [...pageHead("Cotton prices", "Shankar-6 cotton, rupees per candy. One candy is 355.6 kg of lint."),
      h("div", { class: "grid g4" }, stat("Latest Shankar-6", "Rs " + fmt(last[1], 0), "per candy"), stat("As of", day(last[0]), age > 30 ? `${age} days old` : null), stat("Over 30 days", tag(chg(m1))), stat("Over 12 months", tag(chg(y1)))),
      age > 30 ? h("div", { class: "notice" }, `The latest cotton price is ${age} days old. Add a newer one below.`) : null,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Shankar-6, Rs per candy"), chips), box, h("p", { class: "sub", style: "margin:12px 0 0" }, "Source: " + c.source)),
      cottonForm(ctx),
      h("details", { class: "card" }, h("summary", {}, "Table of the last 60 prices"), dataTable({ columns: ["Date", "Rs per candy"], rows: pts.slice(-60).reverse().map(p => [p[0].toISOString().slice(0, 10), p[1]]) }, { label: "Cotton prices" }))];
  });

  function cottonForm(ctx) {
    const f = (id, label, attrs) => h("div", { class: "field" }, h("label", { for: id }, label), h("input", Object.assign({ id }, attrs)));
    const msg = h("div", { "aria-live": "polite" });
    return h("form", { class: "card", onsubmit: async e => {
      e.preventDefault();
      try { await postJSON("/api/cotton", { date: $("#cot-date").value, price: $("#cot-price").value, source: $("#cot-source").value }); toast("Cotton price added"); ctx.reload(); }
      catch (err) { msg.replaceChildren(h("div", { class: "notice err", role: "alert" }, err.message)); }
    } }, h("h3", {}, "Add a cotton price"),
      h("div", { class: "fields", style: "grid-template-columns:repeat(auto-fit,minmax(170px,1fr));align-items:end" },
        f("cot-date", "Date", { type: "date", required: true, value: new Date().toISOString().slice(0, 10) }), f("cot-price", "Shankar-6, Rs per candy", { type: "number", min: "1", step: "any", required: true }), f("cot-source", "Source", { type: "text", placeholder: "Where the price is from" }),
        h("button", { class: "btn primary", type: "submit" }, "Add price")), msg);
  }

  function lineChart(pts, unit) {
    const W = 900, H = 320, m = { l: 62, r: 16, t: 12, b: 28 };
    const xs = pts.map(p => +p[0]), ys = pts.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const step = 5000, y0 = Math.floor(Math.min(...ys) / step) * step, y1 = Math.ceil(Math.max(...ys) / step) * step || 1;
    const X = v => m.l + (v - x0) / ((x1 - x0) || 1) * (W - m.l - m.r), Y = v => m.t + (1 - (v - y0) / ((y1 - y0) || 1)) * (H - m.t - m.b);
    const path = pts.map((p, i) => (i ? "L" : "M") + X(+p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join("");
    let g = "";
    for (let v = y0; v <= y1; v += (y1 - y0) / 4 || 1) g += `<line class="grid-line" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis-text" x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, 0)}</text>`;
    const years = [...new Set(pts.map(p => p[0].getFullYear()))];
    for (const yr of years) { const t = +new Date(yr, 0, 1); if (t >= x0 && t <= x1) g += `<text class="axis-text" x="${X(t)}" y="${H - 8}" text-anchor="middle">${yr}</text>`; }
    const el = h("div", { html: `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Shankar-6 cotton price over time, ${unit}. Latest ${fmt(ys[ys.length - 1], 0)}.">${g}<path class="area" d="${path}L${X(x1)} ${H - m.b}L${X(x0)} ${H - m.b}Z"/><path class="line" d="${path}"/><line class="cross" y1="${m.t}" y2="${H - m.b}" visibility="hidden"/><circle class="dot" r="5" visibility="hidden"/><rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg>` }).firstChild;
    const cross = $(".cross", el), dot = $(".dot", el), hit = $("rect", el);
    hit.addEventListener("mousemove", e => {
      const r = el.getBoundingClientRect(), t = x0 + ((e.clientX - r.left) / r.width * W - m.l) / (W - m.l - m.r) * (x1 - x0);
      let best = 0; for (let i = 1; i < pts.length; i++) if (Math.abs(xs[i] - t) < Math.abs(xs[best] - t)) best = i;
      const cx = X(xs[best]), cy = Y(ys[best]);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("visibility", "visible");
      showTip(`<b>Rs ${fmt(ys[best], 0)} per candy</b>${day(pts[best][0])}`, e.clientX, e.clientY);
    });
    hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
    return el;
  }
})();
