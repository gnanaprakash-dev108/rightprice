/* Stage 2: purchase history and Fab groups. Loaded before rightcost.js and kept apart from it: everything here is
   inside one function, and only RP_PAGES (the pages this file draws) and RP_PURCH (the price popup, the Fab group cell)
   are seen outside. It uses the shell's own helpers (h, fill, svg, ib, tipOn, n0, n2, pc, toast, dayOf, state ...)
   when it runs, never while it loads.
   Pages: #group/<Fab code> (a Fab group), #groups (every Fab group; the admin merge), #purchase-files (the admin
   upload). Charts are plain SVG drawn here. Prices and supplier names come from this server only. */
"use strict";
(function () {
  // ---------------------------------------------------------------- small helpers
  // who may (stage 3, web/access.js): a page's data is asked for only once the person's permissions are known
  const may = perm => typeof can !== "function" || can(perm);
  const known = async () => { if (typeof RPA !== "undefined") await RPA.ready; };
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    let body = null; try { body = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) throw new Error((body && body.detail) || r.statusText || "Request failed");
    return body;
  };
  const day = iso => iso ? dayOf(String(iso).slice(0, 10)) : "";
  const crumbs = (...parts) => h("div", { class: "crumb noprint" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }),
    parts.map(p => [" › ", typeof p === "string" ? h("span", {}, p) : h("button", { type: "button", onclick: () => { location.hash = p[1]; } }, p[0])]));
  const tile = (label, big, sub, cls) => h("div", { class: "stile" + (cls ? " " + cls : "") }, h("div", { class: "sl" }, label), h("div", { class: "sb" }, big), sub ? h("div", { class: "ss" }, sub) : null);
  const table = (heads, rows, numeric) => h("div", { class: "gridscroll sup pgt" }, h("table", { class: "grid", style: { width: "100%" } },
    h("thead", {}, h("tr", {}, heads.map((t, i) => h("th", { class: numeric.includes(i) ? "n" : "" }, t)))),
    h("tbody", {}, rows.map(cells => h("tr", {}, cells.map((c, i) => h("td", { class: numeric.includes(i) ? "n" : (c && c.wide ? "w" : "") }, c && c.wide ? c.el : c)))))));
  const wide = el => ({ wide: true, el });
  const groupLink = code => may("page:groups") ? h("button", { type: "button", class: "code", onclick: () => { closePopups(); location.hash = "#group/" + encodeURIComponent(code); } }, code) : code;
  const codeLink = code => h("button", { type: "button", class: "code", title: "Price over time for this code", onclick: () => openHistory(code) }, code);
  const closePopups = () => document.querySelectorAll(".scrim.pdlg").forEach(e => e.remove());
  const millLink = (name, key) => (state.rows || []).some(r => r.mill === key) ? h("button", { type: "button", class: "code", onclick: () => { closePopups(); location.hash = "#supplier/" + encodeURIComponent(key); } }, name) : name;
  const needsDb = msg => /kept in the database/.test(msg || "");

  // ---------------------------------------------------------------- the chart: price over time, one dot per purchase
  // series: [{key, name, cls}] in a fixed order; points: [{date, price, metres, series, text}]; band: {lower, upper, label};
  // marks: [{y, label, cls}] horizontal lines (should-cost, median). Drawn at the width the box has, again when it changes.
  function priceChart(o) {
    const box = h("div", { class: "pchart" });
    const legend = h("div", { class: "plegend" }, o.series.filter(s => o.points.some(p => p.series === s.key)).map(s => h("span", {}, h("i", { class: "dot " + s.cls }), s.name)),
      (o.marks || []).filter(m => m.y).map(m => h("span", {}, h("i", { class: "key " + m.cls }), m.label)),
      o.band ? h("span", {}, h("i", { class: "bandkey" }), o.band.label) : null,
      o.points.some(p => p.inside === false) ? h("span", {}, h("i", { class: "dot s0 faded" }), "Faded: bought outside the period chosen") : null);
    const draw = () => {
      const W = Math.max(300, box.clientWidth || 600), H = o.height || 260, m = { l: 52, r: 16, t: 12, b: 28 };
      const t = p => new Date(p + "T00:00:00").getTime();
      const xs = o.points.map(p => t(p.date)), DAY = 86400000;
      let x0 = Math.min(...xs), x1 = Math.max(...xs);
      if (x1 - x0 < 30 * DAY) { const mid = (x0 + x1) / 2; x0 = mid - 20 * DAY; x1 = mid + 20 * DAY; } else { const pad = (x1 - x0) * 0.04; x0 -= pad; x1 += pad; }
      const ys = o.points.map(p => p.price).concat((o.marks || []).filter(k => k.y).map(k => k.y), o.band ? [o.band.lower, o.band.upper] : []);
      let y0 = Math.min(...ys), y1 = Math.max(...ys);
      const span = Math.max(y1 - y0, y1 * 0.06, 1); y0 -= span * 0.12; y1 += span * 0.12; y0 = Math.max(0, y0);
      const step = niceStep((y1 - y0) / 4), yt = []; y0 = Math.max(0, Math.floor(y0 / step) * step); y1 = Math.ceil(y1 / step) * step;
      for (let v = y0; v <= y1 + step / 1000; v += step) yt.push(v);
      const X = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r), Y = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
      const NS = "http://www.w3.org/2000/svg", el = (tag, a, ...kids) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(a || {})) if (v !== null && v !== undefined) e.setAttribute(k, v); kids.forEach(k => e.append(k)); return e; };
      const s = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": o.label || "Price over time" });
      for (const v of yt) { s.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: "grid" }), el("text", { x: m.l - 6, y: Y(v) + 4, class: "tick", "text-anchor": "end" }, n0(v))); }
      const months = []; const d = new Date(x0); d.setDate(1); d.setHours(0, 0, 0, 0); d.setMonth(d.getMonth() + 1);
      while (d.getTime() <= x1) { months.push(new Date(d)); d.setMonth(d.getMonth() + 1); }
      const every = Math.max(1, Math.ceil(months.length / Math.max(1, Math.floor((W - m.l - m.r) / 70))));
      months.forEach((mo, i) => { if (i % every) return; s.append(el("line", { x1: X(mo.getTime()), x2: X(mo.getTime()), y1: H - m.b, y2: H - m.b + 4, class: "axis" }), el("text", { x: X(mo.getTime()), y: H - m.b + 16, class: "tick", "text-anchor": "middle" }, mo.toLocaleDateString("en-IN", { month: "short", year: months.length > 10 ? "2-digit" : undefined }))); });
      s.append(el("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: "axis" }));
      // the band is the usual range of the period chosen (the last 12 months by default): drawn over that period only
      const bx0 = o.period ? Math.max(m.l, Math.min(W - m.r, X(t(o.period.from)))) : m.l, bx1 = o.period ? Math.max(m.l, Math.min(W - m.r, X(t(o.period.to)))) : W - m.r;
      if (o.band && bx1 > bx0) s.append(el("rect", { x: bx0, width: bx1 - bx0, y: Y(o.band.upper), height: Math.max(1, Y(o.band.lower) - Y(o.band.upper)), class: "band" }));
      for (const k of (o.marks || []).filter(k => k.y)) s.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(k.y), y2: Y(k.y), class: "mark " + k.cls }));
      // one dot per date, price and series: lines of one order at one price sit on one dot
      const dots = {};
      for (const p of o.points) { const key = p.series + "|" + p.date + "|" + p.price + "|" + (p.inside === false ? "out" : "in"); (dots[key] = dots[key] || Object.assign({ n: 0, metres: 0, texts: [] }, p)).n++; dots[key].metres += p.metres || 0; dots[key].texts.push(p.text); }
      const order = o.series.map(x => x.key);
      for (const p of Object.values(dots).sort((a, b) => order.indexOf(b.series) - order.indexOf(a.series))) {
        const ser = o.series.find(x => x.key === p.series) || {}, cx = X(t(p.date)), cy = Y(p.price);
        const g = el("g", { class: "pt" + (p.inside === false ? " out" : "") }, el("circle", { cx, cy, r: ser.big ? 5.5 : 4.5, class: "dotm " + (ser.cls || "") }), el("circle", { cx, cy, r: 10, class: "hit" }));
        const words = `${day(p.date)} · Rs ${n2(p.price)} · ${n0(p.metres)} m` + (p.n > 1 ? ` (${p.n} lines)` : "") + " · " + [...new Set(p.texts)].slice(0, 3).join("; ") + (p.inside === false ? " · outside the period chosen" : "");
        g.addEventListener("mouseenter", ev => { tip.textContent = words; tip.hidden = false; tip.style.left = Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (ev.clientY + 14) + "px"; });
        g.addEventListener("mouseleave", () => { tip.hidden = true; });
        s.append(g);
      }
      // labels of the lines, on the right, inside the plot; kept apart if two are close
      let lastY = -99;
      for (const k of (o.marks || []).filter(k => k.y).sort((a, b) => Y(a.y) - Y(b.y))) {
        let y = Y(k.y) - 5; if (y - lastY < 13) y = lastY + 13; lastY = y;
        s.append(el("text", { x: W - m.r - 4, y, class: "mlabel", "text-anchor": "end" }, `${k.label} ${n2(k.y)}`));
      }
      fill(box, legend, s);
    };
    box.redraw = draw;
    requestAnimationFrame(draw);
    if (window.ResizeObserver) { let w = 0; new ResizeObserver(() => { if (box.isConnected && Math.abs(box.clientWidth - w) > 20) { w = box.clientWidth; draw(); } }).observe(box); }
    return box;
  }
  function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p; }
  // mills: the three with the most metres in their own colours, the rest together (four or more colours on one scatter
  // cannot all be told apart); the legend and the table below name every mill
  function millSeries(mills) {
    const top = mills.slice(0, 3).map((m, i) => ({ key: m.key, name: m.name, cls: "s" + (i + 1) }));
    return mills.length > 3 ? top.concat([{ key: "*", name: `${mills.length - 3} other ${mills.length - 3 === 1 ? "mill" : "mills"}`, cls: "s0" }]) : top;
  }
  const rangeWords = r => r.enough ? `Rs ${n2(r.lower)} to ${n2(r.upper)}` : "Too few purchases";
  const rangeSub = (r, min) => r.enough ? `${pc(r.lo)} to ${pc(r.hi)} round the median` + ((r.lo !== r.p25 || r.hi !== r.p75) ? `; its middle half (${pc(r.p25)} to ${pc(r.p75)}) kept within 5% to 10%` : ": the middle half of its prices")
    : `${r.orders || 0} separate ${r.orders === 1 ? "order" : "orders"}; a usual range needs at least ${min}`;
  // ---------------------------------------------------------------- the period: what we usually pay over time (GP, 28 Nov 2026)
  // By default the last 12 months, ending today; the slider runs over the months the purchase history holds and chooses
  // another period, from the start of a month to the end of a month. A view only: every verdict elsewhere (Right cost, the
  // brief, alerts, supplier pages, the dashboard) stays on the last 12 months.
  const monthWords = ym => new Date(ym + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  function periodBar(d, choose) {
    const per = d.period, months = d.months || [];
    const said = h("span", { class: "pwords" }, `What we usually pay rests on ${per.label}`);
    const reset = per.default ? null : h("button", { type: "button", class: "btn line", onclick: () => choose(null) }, "Last 12 months");
    const view = h("p", { class: "muted pnote" }, "A view only: Right cost, the negotiation brief, quote alerts, supplier pages and the Dashboard stay on the last 12 months. Every purchase stays on the chart.");
    if (months.length < 2) return h("div", { class: "pbar noprint" }, h("div", { class: "prow" }, said, reset), view);
    const at = (day, end) => { const i = months.indexOf(String(day).slice(0, 7)); return i >= 0 ? i : end ? months.length - 1 : day < months[0] ? 0 : months.length - 1; };
    const a = h("input", { type: "range", min: "0", max: String(months.length - 1), step: "1", value: String(at(per.from, false)), "aria-label": "From the month" });
    const b = h("input", { type: "range", min: "0", max: String(months.length - 1), step: "1", value: String(at(per.to, true)), "aria-label": "To the month" });
    const shown = h("b", { class: "pmonths" });
    const show = () => { shown.textContent = `${monthWords(months[Math.min(+a.value, +b.value)])} to ${monthWords(months[Math.max(+a.value, +b.value)])}`; };
    const go = () => { const i = Math.min(+a.value, +b.value), j = Math.max(+a.value, +b.value); choose({ from: months[i], to: months[j] }); };
    for (const x of [a, b]) { x.addEventListener("input", show); x.addEventListener("change", go); }
    show();
    return h("div", { class: "pbar noprint" }, h("div", { class: "prow" }, said, reset),
      h("div", { class: "prow" }, h("span", { class: "muted" }, "Period:"), shown, h("span", { class: "muted" }, `(the history holds ${monthWords(months[0])} to ${monthWords(months[months.length - 1])})`)),
      h("div", { class: "pslide" }, h("label", {}, "From ", a), h("label", {}, "To ", b)), view);
  }
  const periodQuery = per => per ? `from=${encodeURIComponent(per.from)}&to=${encodeURIComponent(per.to)}` : "";

  // every other row of the purchase files (GP, 28 Nov 2026): stored and shown by its type, in no rupees-per-metre figure;
  // imports converted on their month's exchange rate, kept apart; domestic bulk lines per kg with their own per-kg figures
  const OTHER_WORDS = "Every row of the purchase files is stored (GP's decision, 28 Nov 2026): sampling orders, stock transfers, returns, lines deleted or blocked in SAP, imports, other units. Only domestic bulk orders (BO, BF) per metre count in prices, ranges and verdicts; ZLOI is kept apart; imports are shown in rupees on their month's exchange rate, apart; lines per kg have their own per-kg figures.";
  const unitWords = u => u === "M" ? "m" : u === "KG" ? "kg" : (u || "").toLowerCase();
  const qtyWords = o => o.qty === null ? "" : `${n0(o.qty)} ${unitWords(o.unit)}`.trim();
  const priceWords = o => o.price === null ? "" : (o.currency && o.currency !== "INR" ? `${o.currency} ` : "Rs ") + n2(o.price) + (o.unit && o.unit !== "M" ? ` per ${unitWords(o.unit)}` : "");
  const rsWords = o => o.currency && o.currency !== "INR" ? (o.price_rs === null ? h("span", { class: "muted", title: o.rate_why || "" }, "no rate yet") : `Rs ${n2(o.price_rs)}` + (o.unit && o.unit !== "M" ? ` per ${unitWords(o.unit)}` : "") + ` (at ${n2(o.rate)})`) : "";
  function otherTable(list, whose, withCode, total) {
    if (!list || !list.length) return null;
    const heads = ["Date", "Order", "SAP type", "Order type"].concat(withCode ? ["Fabric code"] : [], ["Mill", "Sourcing", "Quantity", "Price", "In rupees", "Why it counts in no figure"]);
    return h("div", { class: "othl" }, h("h3", {}, `Other order lines of ${whose}, in no rupees-per-metre figure: ${n0(total || list.length)}`),
      h("p", { class: "muted" }, OTHER_WORDS),
      table(heads, list.map(o => [day(o.date), `${o.po}/${o.item}`, o.type || "", o.order_type || ""].concat(withCode ? [codeLink(o.code)] : [], [o.mill, o.sourcing + (o.currency && o.currency !== "INR" ? `, ${o.currency}` : ""), qtyWords(o), priceWords(o), rsWords(o),
        wide(h("span", { class: "muted" }, o.why + (o.detail && o.detail !== o.why ? `: ${o.detail}` : "")))])), withCode ? [7, 8] : [6, 7]),
      total && total > list.length ? h("p", { class: "muted" }, `The newest ${list.length} are shown.`) : null);
  }
  // what is kept apart, in tiles: the per-kg figures (their own range; no should-cost per kg yet) and the imports
  function apartTiles(d) {
    const k = d.per_kg, im = d.imports;
    if (!k || !im || (!k.lines && !im.lines)) return null;
    const r = k.range || {};
    return h("div", { class: "stiles apart" },
      k.lines ? tile("Bought per kg (domestic bulk)", r.median ? `Rs ${n2(r.median)} per kg` : `${n0(k.lines)} lines`, `${n0(k.lines)} ${k.lines === 1 ? "line" : "lines"}, ${n0(k.kg)} kg in the period; ` +
        (r.enough ? `usual range Rs ${n2(r.lower)} to ${n2(r.upper)} per kg` + (r.above ? `, ${r.above} above it` : "") : `${r.orders || 0} separate ${r.orders === 1 ? "order" : "orders"}: too few for a range`) + `. Never mixed with metres; ${k.should}.`) : null,
      im.lines ? tile("Imports, kept apart", `${n0(im.lines)} ${im.lines === 1 ? "line" : "lines"}`, `${im.currencies.join(", ")}; ${im.no_rate ? `${n0(im.no_rate)} with no exchange rate yet (Prices > Exchange rates)` : "each converted on its month's rate"}. ${im.note}`, im.no_rate ? "amber" : "") : null);
  }
  const imports = (list, whose) => list && list.length ? h("div", { class: "othl" }, h("h3", {}, `Imports of ${whose}: ${n0(list.length)} ${list.length === 1 ? "line" : "lines"}, kept apart`),
    h("p", { class: "muted" }, "Bulk orders priced in another currency, shown in rupees on their order month's exchange rate (Prices > Exchange rates; blank where none is entered). They are in none of the rupee figures on this page."),
    table(["Date", "Order", "Fabric code", "Quantity", "Price", "Exchange rate", "In rupees", "Value Rs"], list.map(o => [day(o.date), `${o.po}/${o.item}`, codeLink(o.code), qtyWords(o), priceWords(o),
      o.rate === null ? h("span", { class: "muted", title: o.rate_why || "" }, "no rate yet") : n2(o.rate), rsWords(o), o.value_rs === null ? "" : n0(o.value_rs)]), [3, 4, 5, 7])) : null;

  // ZLOI order lines: kept, in no figure, listed apart (GP, 27 Nov 2026)
  const ZLOI_WORDS = "ZLOI order lines are left out of every figure on this page (price paid, metres, medians, ranges, should-cost): GP's decision of 27 Nov 2026.";
  function outliers(list, whose, withCode) {
    if (!list || !list.length) return null;
    const heads = withCode ? ["Date", "Order", "Fabric code", "Mill", "Metres", "Price Rs/m"] : ["Date", "Order", "Mill", "Metres", "Price Rs/m"];
    const cells = o => withCode ? [day(o.date), `${o.po}/${o.item}`, codeLink(o.code), o.mill, n0(o.metres), n2(o.price)] : [day(o.date), `${o.po}/${o.item}`, o.mill, n0(o.metres), n2(o.price)];
    return h("div", { class: "outl" }, h("h3", {}, `Outliers (ZLOI): ${list.length} ${list.length === 1 ? "line" : "lines"} of ${whose}`),
      h("p", { class: "muted" }, ZLOI_WORDS), table(heads, list.map(cells), withCode ? [4, 5] : [3, 4]));
  }

  // ---------------------------------------------------------------- the price popup: one fabric code
  async function openHistory(code, per) {
    closePopups();
    const body = h("div", { class: "pbody" }, h("div", { class: "empty" }, "Loading…"));
    const d = h("div", { class: "dialog pdialog rp-purch", role: "dialog", "aria-modal": "true", "aria-label": "Price over time: " + code },
      h("div", { class: "phead" }, h("h2", {}, "Price over time: " + code), ib("x", "Close", () => s.remove())), body);
    const s = h("div", { class: "scrim pdlg", onmousedown: e => { if (e.target === s) s.remove(); } }, d);
    $("#layer").append(s);
    d.querySelector("button").focus();
    let x;
    try { x = await api("/api/purchases/history?code=" + encodeURIComponent(code) + (per ? "&" + periodQuery(per) : "")); }
    catch (e) { fill(body, h("p", { class: needsDb(e.message) ? "muted" : "err" }, e.message)); return; }
    const g = x.group, sp = x.spec;
    const num = v => v === "" || isNaN(Number(v)) ? v : String(Number(v));
    const specLine = sp ? "PLM: " + [sp.blend_name, sp.dyemethod_name, sp.weavetype_name, `${sp.warpcount} x ${sp.weftcount}`, `${num(sp.epi)} x ${num(sp.ppi)}`, `${num(sp.finishedwidth)} ${sp.finishedwidth_uom}`, String(sp.finish_name || "").replace(/^F\s*-\s*/, "")].filter(Boolean).join(" · ") : "No PLM specification for this code";
    const inside = l => l.date >= x.period.from && l.date <= x.period.to, ip = x.in_period;
    const pts = x.lines.map(l => ({ date: l.date, price: l.price, metres: l.metres, series: "this", inside: inside(l), text: `${l.mill}, order ${l.po}/${l.item}` }));
    if (g) for (const l of g.lines) if (l.code !== x.code) pts.push({ date: l.date, price: l.price, metres: l.metres, series: "group", inside: l.inside !== false, text: `${l.code}, ${l.mill}` });
    for (const o of x.others || []) if (o.plotted) pts.push({ date: o.date, price: o.price_rs_m, metres: o.qty || 0, series: o.import ? "import" : "other", text: `${o.type || "no type"} (${o.order_type}): ${o.import ? `import, ${o.currency} ${n2(o.price)} at ${n2(o.rate)}` : o.why}, ${o.mill}, order ${o.po}/${o.item}` });
    const series = [{ key: "this", name: `This code, ${x.code}`, cls: "s1", big: true }, { key: "group", name: g ? `Other codes of ${g.code} (the same construction, any colour)` : "", cls: "s0" },
      { key: "import", name: "This code's imports, in rupees on their month's rate (kept apart)", cls: "imp" },
      { key: "other", name: "This code's other orders, in no figure (sampling, stock transfer, deleted ...)", cls: "oth" }];
    const marks = [x.should ? { y: x.should, label: "Should-cost", cls: "should" } : null, g && g.range.enough ? { y: g.range.median, label: `${g.code} median`, cls: "median" } : null].filter(Boolean);
    const others = g ? g.lines.filter(l => l.code !== x.code).length : 0;
    const outside = x.lines.length - ip.lines;
    fill(body,
      h("p", { class: "muted" }, specLine),
      periodBar(x, per2 => openHistory(code, per2)),
      h("div", { class: "stiles" },
        tile("Bought", `${n0(ip.lines)} ${ip.lines === 1 ? "purchase" : "purchases"}`, `${n0(ip.metres)} m on ${ip.orders} ${ip.orders === 1 ? "order" : "orders"} in the period` + (outside ? `; ${outside} more outside it` : "")),
        tile("Price paid", ip.lines ? (ip.lines > 1 && ip.low !== ip.high ? `Rs ${n2(ip.low)} to ${n2(ip.high)}` : `Rs ${n2(ip.low)}`) : "None", x.lines.length ? `last on ${day(x.lines[x.lines.length - 1].date)}` + (ip.lines ? "" : " (outside the period)") : ""),
        tile("Should-cost", x.should ? `Rs ${n2(x.should)}` : "Not costed", x.should ? (x.should_on || "on today's rates") : x.should_why),
        g ? tile(`Fab group ${g.code}`, g.range.enough ? rangeWords(g.range) : `${g.purchases} ${g.purchases === 1 ? "purchase" : "purchases"}`, g.range.enough ? `its usual range; median Rs ${n2(g.range.median)} on ${g.purchases} purchases, ${g.range.orders} orders` : `on ${g.range.orders || 0} separate ${g.range.orders === 1 ? "order" : "orders"} in the period: too few for a usual range (needs ${g.min_for_range})`) : tile("Fab group", "Not grouped", x.not_grouped)),
      pts.length ? priceChart({ points: pts, series, marks, period: x.period, band: g && g.range.enough ? { lower: g.range.lower, upper: g.range.upper, label: `${g.code} usual range` } : null, label: `Price over time for ${x.code}` }) : null,
      g ? h("p", { class: "muted" }, others ? `Grey dots: the ${others} other ${others === 1 ? "purchase" : "purchases"} of ${g.codes - 1} other ${g.codes - 1 === 1 ? "code" : "codes"} in Fab group ${g.code}, ${g.name}. Most codes are ordered once, so the group shows the history.`
        : `No other code of Fab group ${g.code} has been bought yet.`) : h("p", { class: "muted" }, `Not in a Fab group: ${x.not_grouped}. Nothing is guessed, so there is no group history to show.`),
      (x.moved || []).map(m => h("p", { class: "note" }, m.from && m.from === m.to ? `On ${day(m.at)}: ${m.why}.` : `Moved ${m.from ? "from " + m.from + " " : ""}on ${day(m.at)}: ${m.why}.`)),
      h("h3", {}, "Purchases of this code"),
      x.lines.length ? table(["Date", "Order", "Mill", "Metres", "Price Rs/m", "Against should-cost"], x.lines.map(l => [inside(l) ? day(l.date) : h("span", { class: "muted", title: "Outside the period chosen" }, day(l.date) + " (outside)"), `${l.po}/${l.item}`, l.mill, n0(l.metres), n2(l.price), x.should ? pc((l.price / x.should - 1) * 100) : ""]), [3, 4, 5])
        : h("p", { class: "muted" }, x.outliers.length ? "None but ZLOI orders, which are listed apart below: no price paid is shown." : "None."),
      outliers(x.outliers, "this code"),
      apartTiles(x),
      otherTable(x.others, "this code", false, x.others_count),
      h("div", { class: "acts" }, g && may("page:groups") ? h("button", { type: "button", class: "btn fill", onclick: () => { s.remove(); location.hash = "#group/" + encodeURIComponent(g.code); } }, `Open Fab group ${g.code}`) : null,
        h("button", { type: "button", class: "btn line", onclick: () => s.remove() }, "Close")),
      h("p", { class: "muted" }, "Should-cost is as Right cost has it: for the metres bought (ZLOI left out), on the yarn rates of the order month (today's where none is dated) and today's other rates. Prices are the net price on each purchase-order line (ex-mill, Rs per metre)."));
  }

  // ---------------------------------------------------------------- #group/<code>: one Fab group
  const page = { group: null };
  async function enterGroup(p) {
    await known(); if (!may("page:groups")) return;
    const code = p.arg;
    if (page.group && page.group.code === code && page.group.data) return;
    const per = page.group && page.group.code === code ? page.group.per : null;          // the period chosen stays while on the group
    page.group = { code, data: null, error: null, per };
    try { page.group.data = await api("/api/groups/" + encodeURIComponent(code) + (per ? "?" + periodQuery(per) : "")); } catch (e) { page.group.error = e.message; }
    if (state.page && state.page.id === "group") render();
  }
  function renderGroup(main) {
    tip.hidden = true;
    const p = page.group || {}, d = p.data;
    const top = crumbs(["Right cost", "#rightcost"], ["Fab groups", "#groups"], (d && d.code) || p.code || "");
    $("#selbar").hidden = true;
    if (p.error) return fillP(main, top, h("div", { class: "empty" }, p.error));
    if (!d) return fillP(main, top, h("div", { class: "empty" }, "Loading…"));
    document.title = d.code + " - RightPrice";
    const r = d.range, sh = d.should, series = millSeries(d.mills_all || d.mills), shown = new Set(series.map(x => x.key));
    const pts = d.lines.map(l => ({ date: l.date, price: l.price, metres: l.metres, inside: l.inside !== false, series: shown.has(l.mill_key) ? l.mill_key : "*", text: `${l.mill}, ${l.code}` }));
    const choose = async per => { p.per = per; p.data = null; render(); try { p.data = await api("/api/groups/" + encodeURIComponent(p.code) + (per ? "?" + periodQuery(per) : "")); } catch (e) { p.error = e.message; } render(); };
    const marks = [sh.median ? { y: sh.median, label: "Should-cost", cls: "should" } : null, r.enough ? { y: r.median, label: "Median paid", cls: "median" } : null].filter(Boolean);
    const vsShould = sh.median && r.median ? (r.median / sh.median - 1) * 100 : null;
    const inList = (state.rows || []).filter(x => x.fab_group === d.code).length;
    fillP(main, top,
      h("div", { class: "dhead" }, h("div", {}, h("div", { class: "small" }, `Fab group · ${n0(d.fabrics.length)} fabric ${d.fabrics.length === 1 ? "code" : "codes"} · the same construction in any colour` + (d.first ? ` · bought ${day(d.first)} to ${day(d.last)}` : "")),
        h("h1", {}, d.code), h("div", { class: "gname" }, d.name)),
        h("div", { class: "dicons noprint" }, ib("pdf", "Print this page", () => print()),
          inList ? ib("pin", `Show its ${inList} purchase-order ${inList === 1 ? "costing" : "costings"} in Right cost`, () => { state.filters = { fab_group: [d.code] }; state.cls = "Purchase orders"; state.saved = "Default"; state.tab = "items"; location.hash = "#rightcost"; }) : null)),
      d.asked ? h("p", { class: "note" }, `${d.asked.code} (${d.asked.name}) was merged into this group` + (d.asked.merged_at ? ` on ${day(d.asked.merged_at)}` : "") + (d.asked.merged_by ? ` by ${d.asked.merged_by}` : "") + `. Its code stays ${d.asked.code} and is never given to another group.`) : null,
      periodBar(d, choose),
      h("div", { class: "stiles" },
        tile("Purchases", `${n0(d.purchases)}`, `${n0(d.orders)} ${d.orders === 1 ? "order" : "orders"}, ${n0(d.metres)} m in the period` + (d.outside_period ? `; ${n0(d.outside_period)} more outside it` : "") + (d.outliers.length ? `; ${d.outliers.length} ZLOI ${d.outliers.length === 1 ? "line" : "lines"} left out` : "")),
        (() => { const bought = d.mills.filter(m => m.lines), only = d.mills.length - bought.length;
          return tile("Mills", `${bought.length}`, [bought.slice(0, 3).map(m => m.name).join(", ") + (bought.length > 3 ? ` and ${bought.length - 3} more` : ""),
            only ? `${bought.length ? only + " more" : only} with ZLOI lines only, not counted` : ""].filter(Boolean).join(" · ")); })(),
        tile("Median price paid", r.median ? `Rs ${n2(r.median)}` : "None", r.median ? `paid Rs ${n2(r.low)} to ${n2(r.high)}` : ""),
        tile("Usual range", rangeWords(r), rangeSub(r, d.min_for_range), r.enough ? "" : "amber"),
        tile("Should-cost", sh.median ? `Rs ${n2(sh.median)}` : "Not costed", sh.median ? (sh.low !== sh.high ? `Rs ${n2(sh.low)} to ${n2(sh.high)} across its codes (order size, pattern); ` : "") + (sh.dated && sh.dated.length ? `on the order months' yarn rates (some dated)` : `on today's rates`) + (vsShould !== null ? `; the median paid is ${pc(vsShould)} against it` : "") : (sh.why_not[0] || "")),
        tile("Priced well above the group", r.enough ? `${d.above.length} ${d.above.length === 1 ? "purchase" : "purchases"}` : "No range yet", r.enough ? (d.above.length ? `Rs ${n0(d.above_rs)} above the top of the usual range` : "none above the top of its usual range") : "too few orders to say", d.above.length ? "red" : "")),
      h("section", { class: "sec" }, h("h2", {}, "Price over time, by mill"),
        d.lines.length ? priceChart({ points: pts, series, marks, period: d.period, band: r.enough ? { lower: r.lower, upper: r.upper, label: "Usual range" } : null, label: `Prices paid for ${d.code} by date and mill`, height: 300 }) : h("p", { class: "muted" }, "No purchase on record."),
        h("p", { class: "muted" }, "One dot per purchase (lines of one order at one price share a dot). Point at a dot for its date, price, metres, mill and code." + (r.enough ? " The band is the group's usual range." : ""))),
      h("section", { class: "sec" }, h("h2", {}, "By mill"),
        table(["Mill", "Purchases", "Orders", "Metres", "Share of metres", "Median Rs/m", "Lowest", "Highest", "Median against the group", "Last bought", "Outliers (ZLOI)"],
          d.mills.map(m => [millLink(m.name, m.key), n0(m.lines), n0(m.orders), n0(m.metres), m.share === null ? "" : Math.round(m.share * 100) + "%", m.median === null ? "" : n2(m.median), m.low === null ? "" : n2(m.low), m.high === null ? "" : n2(m.high),
            m.vs_group === null ? "" : pc(m.vs_group), day(m.last), m.outliers.length ? wide(h("span", {}, `${m.outliers.length}: ` + m.outliers.map(o => `${day(o.date)} ${n0(o.metres)} m at Rs ${n2(o.price)}`).join("; "))) : ""]), [1, 2, 3, 4, 5, 6, 7, 8]),
        outliers(d.outliers, "this group", true),
        apartTiles(d),
        d.others_count ? [h("p", { class: "muted" }, "In no figure, by why: " + d.others_by_kind.map(([k, n]) => `${k}: ${n0(n)}`).join("; ") + "."), otherTable(d.others, "this group", true, d.others_count)] : null),
      h("section", { class: "sec" }, h("h2", {}, "Priced well above the group"),
        !r.enough ? h("p", { class: "muted" }, `${r.n} ${r.n === 1 ? "purchase" : "purchases"} on ${r.orders || 0} separate ${r.orders === 1 ? "order" : "orders"} in the period: too few for a usual range (it needs purchases on at least ${d.min_for_range} orders, ZLOI left out), so no purchase is called high. Load more purchase files as they come.`)
          : !d.above.length ? h("p", { class: "muted" }, `None: every purchase is at or below the top of the usual range, Rs ${n2(r.upper)}.`)
            : [h("p", { class: "muted" }, `Above Rs ${n2(r.upper)}, the top of the usual range. Already paid: use them for the next order of the same cloth.`),
              table(["Date", "Fabric code", "Mill", "Metres", "Price Rs/m", "Above the range Rs/m", "Against the median", "Above the range, Rs"],
                d.above.map(a => [day(a.date), codeLink(a.code), millLink(a.mill, a.mill_key), n0(a.metres), n2(a.price), n2(a.above), pc(a.pct), n0(a.above_rs)]), [3, 4, 5, 6, 7])]),
      h("section", { class: "sec" }, h("h2", {}, "Fabric codes in this group"),
        table(["Fabric code", "Mills", "Purchases", "Metres", "Last price Rs/m", "Last bought", "Should-cost Rs/m", "Note on the last order"],
          d.fabrics.slice(0, p.all ? undefined : 25).map(f => [codeLink(f.code), wide(f.mills.join(", ")), n0(f.lines), n0(f.metres), f.last_price === null ? "" : n2(f.last_price), day(f.last_date), f.should ? n2(f.should) : h("span", { class: "muted", title: f.should_why || "" }, "not costed"),
            wide(h("span", { class: "muted" }, (f.in_group !== d.code ? `(from ${f.in_group}) ` : "") + (f.description || "")))]), [2, 3, 4, 6]),
        d.fabrics.length > 25 && !p.all ? h("p", { class: "noprint" }, h("button", { type: "button", class: "btn line", onclick: () => { p.all = true; render(); } }, `Show all ${n0(d.fabrics.length)} codes (the 25 bought most often are shown)`)) : null),
      h("section", { class: "sec" }, h("h2", {}, "What makes this group"),
        h("dl", { class: "kv gfields" }, [["Content", d.fields.content], ["Dye method", d.fields.route], ["Weave", d.fields.weave], ["Warp", d.fields.warp], ["Weft", d.fields.weft], ["EPI x PPI", `${d.fields.epi} x ${d.fields.ppi}`], ["Finished width", d.fields.width_to && d.fields.width_to !== d.fields.width_in ? `${d.fields.width_in} to ${d.fields.width_to} in` : `${d.fields.width_in} in`], ["Finish", d.fields.finish]].map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
        h("p", { class: "muted" }, "The nine fields of each code's PLM specification, tidied (spellings of a count or a fibre made one) and then matched exactly, but for the finished width: codes whose widths are within half an inch of each other (directly or through other codes) are one group. A code whose specification is missing or incomplete is not put in any group."),
        (d.renamed || []).length ? [h("h3", {}, "Renamed"), h("ul", { class: "mon" }, d.renamed.map(x => h("li", {}, `On ${day(x.at)}: ${x.why}. It was ${x.from}; it is ${x.to}. Its code stays ${d.code}.`)))] : null,
        (d.respecified || []).length ? [h("h3", {}, "Specifications corrected"), h("ul", { class: "mon" }, d.respecified.map(m => h("li", {}, `${m.code} on ${day(m.at)}: ${m.why}.`)))] : null,
        (d.merges || []).length ? [h("h3", {}, "Merges"), h("ul", { class: "mon" }, d.merges.map(m => h("li", {}, `${m.code} ${m.why} on ${day(m.at)}${m.by ? " by " + m.by : ""}.`)))] : null,
        d.merged_in.length ? h("p", {}, "Also counted here, merged in by an admin: " + d.merged_in.map(x => `${x.code} (${x.name})`).join("; ") + ".") : null,
        d.moved_in.length || d.moved_out.length ? [h("h3", {}, "Codes moved since"), h("ul", { class: "mon" },
          d.moved_in.map(m => h("li", {}, `${m.code} came in${m.from ? " from " + m.from : ""} on ${day(m.at)}: ${m.why}.`)),
          d.moved_out.map(m => h("li", {}, `${m.code} went ${m.to ? "to " + m.to : "out of every group"} on ${day(m.at)}: ${m.why}.`)))] : null),
      h("p", { class: "muted", style: "margin-top:18px" }, `"Priced well above the group" uses the negotiation brief's own rule: the usual range is the middle half of the group's prices in the period (by default the last 12 months, ending today; GP, 28 Nov 2026), kept between 5% and 10% either side of its median, and it needs purchases on at least ${d.min_for_range} separate orders. ${ZLOI_WORDS} Should-cost is as Right cost has it: each code for the metres bought, on the yarn rates of its order month (today's where none is dated) and today's other rates.`));
  }

  // ---------------------------------------------------------------- #groups: every Fab group, and the admin merge
  const list = { data: null, error: null, q: "", shown: 100 };
  async function enterGroups(force) {
    await known(); if (!may("page:groups")) return;
    if (list.data && !force) return;
    try { list.data = await api("/api/groups"); list.error = null; } catch (e) { list.error = e.message; }
    if (state.page && state.page.id === "groups") render();
  }
  function renderGroups(main) {
    tip.hidden = true;
    const top = crumbs(["Right cost", "#rightcost"], "Fab groups");
    $("#selbar").hidden = true;
    if (list.error) return fillP(main, top, h("h1", { class: "ptitle" }, "Fab groups"), h("p", { class: needsDb(list.error) ? "note" : "err" }, list.error));
    if (!list.data) return fillP(main, top, h("div", { class: "empty" }, "Loading…"));
    const d = list.data, q = list.q.trim().toLowerCase();
    const rows = d.groups.filter(g => !q || (g.code + " " + g.name).toLowerCase().includes(q)).sort((a, b) => b.purchases - a.purchases || a.code.localeCompare(b.code));
    const search = h("input", { type: "search", class: "search", placeholder: "Search a code or the construction (e.g. Twill 40s)", value: list.q, "aria-label": "Search the Fab groups" });
    search.addEventListener("keydown", e => { if (e.key === "Enter") { list.q = search.value; list.shown = 100; render(); } });
    const a = h("input", { type: "text", placeholder: "Fab-0012", "aria-label": "The group to merge" }), b = h("input", { type: "text", placeholder: "Fab-0003", "aria-label": "The group to merge it into" });
    const merge = async () => {
      const from = a.value.trim(), into = b.value.trim();
      if (!from || !into) return toast("Give both Fab group codes", false);
      const ga = d.groups.find(g => g.code.toLowerCase() === from.toLowerCase()), gb = d.groups.find(g => g.code.toLowerCase() === into.toLowerCase());
      const ok = await confirmBox(`Merge ${from} into ${into}?`, [h("p", {}, `${from}: ${ga ? ga.name : "?"}`), h("p", {}, `into ${into}: ${gb ? gb.name : "?"}`),
        h("p", { class: "muted" }, `From now on the codes of ${from} count in ${into}, and its page says so. The code ${from} is kept and never given to another group. It can be undone below.`)], "Merge");
      if (!ok) return;
      const send = body => api("/api/groups/merge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      try {
        let res = await send({ code: from, into });
        if (res.needs_confirm) {
          const sure = await confirmBox(`${res.code} and ${res.into} are different cloths?`, [h("p", { class: "err" }, res.detail),
            h("ul", { class: "mon" }, res.differences.map(x => h("li", {}, `${x.field}: ${x.a} against ${x.b}`))),
            h("p", {}, "Width and finish may differ in a merge; these may not, unless the two really are one cloth. Merge anyway?")], "Merge anyway");
          if (!sure) return;
          res = await send({ code: from, into, confirm: true });
        }
        toast(`${res.merged} merged into ${res.into}`); page.group = null; reloadCosts(); await enterGroups(true);
      } catch (e) { toast(e.message, false); }
    };
    const undo = async code => {
      if (!await confirmBox(`Undo the merge of ${code}?`, [h("p", {}, `${code} counts on its own again.`)], "Undo the merge")) return;
      try { await api("/api/groups/unmerge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) }); toast(`${code} is on its own again`); page.group = null; reloadCosts(); await enterGroups(true); }
      catch (e) { toast(e.message, false); }
    };
    const c = d.counts;
    fillP(main, top, h("div", { class: "headrow" }, h("h1", { class: "ptitle" }, "Fab groups")),
      h("p", { class: "muted" }, `${n0(c.groups)} groups of ${n0(c.fabrics_grouped)} fabric codes (the same construction in any colour, across mills), from ${n0(c.lines)} purchase lines` + (c.first ? `, ${day(c.first)} to ${day(c.last)}` : "") + `. ${n0(c.fabrics - c.fabrics_grouped)} codes are not grouped` + (d.not_grouped.length ? ` (${d.not_grouped.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")})` : "") + ".",
        " ", may("page:purchase_files") ? h("a", { href: "#purchase-files" }, "Purchase files") : null),
      h("div", { class: "toolbar" }, search, h("button", { type: "button", class: "btn line", onclick: () => { list.q = search.value; list.shown = 100; render(); } }, "Search"), h("span", { class: "count" }, `${n0(rows.length)} groups`)),
      rows.length ? table(["Fab group", "Construction", "Codes", "Purchases", "Metres", "Median Rs/m, last 12 months", "Last bought"],
        rows.slice(0, list.shown).map(g => [groupLink(g.code), wide(g.name), n0(g.codes), n0(g.purchases), n0(g.metres), g.median === null ? "" : n2(g.median), day(g.last)]), [2, 3, 4, 5]) : h("div", { class: "empty" }, c.groups ? "No group matches." : "No Fab groups yet: load a purchase file first."),
      rows.length > list.shown ? h("p", {}, h("button", { type: "button", class: "btn line", onclick: () => { list.shown += 200; render(); } }, `Show more (${n0(rows.length - list.shown)} more)`)) : null,
      may("do:merge_groups") ? h("section", { class: "sec noprint" }, h("h2", {}, "Admin: merge two Fab groups"),
        h("p", { class: "muted" }, "When two groups are really one cloth (a finish or a count written two ways), merge one into the other. When they differ in more than width or finish you are asked twice."),
        h("div", { class: "mergerow" }, h("label", {}, "Merge ", a), h("label", {}, " into ", b), h("button", { type: "button", class: "btn fill", onclick: merge }, "Merge…"))) : null,
      d.merged.length ? h("section", { class: "sec" }, h("h3", {}, "Merged so far"), table(["Fab group", "Construction", "Counts in", "When", "By", ""], d.merged.map(m => [m.code, wide(m.name), groupLink(m.into), day(m.merged_at), m.merged_by || "",
        may("do:merge_groups") ? h("button", { type: "button", class: "btn line", onclick: () => undo(m.code) }, "Undo") : ""]), [])) : null);
  }
  function confirmBox(title, body, yes) {
    return new Promise(done => {
      const s = dialog(title, h("div", { class: "rp-purch" }, body), [h("button", { type: "button", class: "btn", onclick: () => { s.remove(); done(false); } }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => { s.remove(); done(true); } }, yes)]);
    });
  }
  // stage 2's pages draw inside a wrapper of their own, so this file's styles (.note, .err ...) never reach other pages
  const fillP = (main, ...kids) => fill(main, h("div", { class: "rp-purch" }, ...kids));
  const reloadCosts = () => { try { load(); } catch (e) { /* the list reloads at its next look */ } };

  // ---------------------------------------------------------------- #purchase-files: the admin upload
  const files = { data: null, error: null, open: null, detail: null, timer: null, rows: 30 };
  async function enterFiles() {
    clearTimeout(files.timer);
    await known(); if (!may("page:purchase_files")) return;
    try { files.data = await api("/api/purchases/uploads"); files.error = null; } catch (e) { files.error = e.message; }
    if (!(state.page && state.page.id === "purchase-files")) return;
    const busy = (files.data && files.data.uploads || []).some(u => u.status === "queued" || u.status === "working");
    if (files.open && files.data) {
      const u = files.data.uploads.find(x => x.id === files.open);
      if (u && (!files.detail || files.detail.id !== u.id || files.detail.status !== u.status)) { try { files.detail = await api("/api/purchases/uploads/" + u.id); } catch (e) { files.detail = null; } }
    }
    if (busy) files.timer = setTimeout(() => { if (state.page && state.page.id === "purchase-files") enterFiles(); }, 2000);
    else if (files.wasBusy) { reloadCosts(); list.data = null; page.group = null; }
    files.wasBusy = busy;
    render();
  }
  const STATUS_WORDS = { queued: "Waiting to be read", working: "Being read", done: "Read", failed: "Failed" };
  function renderFiles(main) {
    tip.hidden = true;
    const top = crumbs("Purchase files");
    $("#selbar").hidden = true;
    const title = h("div", { class: "headrow" }, h("h1", { class: "ptitle" }, "Purchase files"));
    if (files.error) return fillP(main, top, title, h("p", { class: needsDb(files.error) ? "note" : "err" }, files.error));
    if (!files.data) return fillP(main, top, title, h("div", { class: "empty" }, "Loading…"));
    const d = files.data, c = d.counts;
    // one file box for as long as the page is open: the page is drawn again when a file is chosen (and every two seconds
    // while a file is read), and a new box would lose the file chosen
    const fresh = !files.input;
    const input = files.input || (files.input = h("input", { type: "file", accept: ".xlsx,.xlsm", "aria-label": "Purchase-order file" }));
    const big = () => input.files.length ? tooBig(input.files[0].size, d.max_bytes, input.files[0].name) : null;
    if (fresh) input.addEventListener("change", () => { files.uploadError = big(); render(); });     // said at once, before anything is sent
    const send = async () => {
      if (!input.files.length) return toast("Choose the purchase-order file first", false);
      files.uploadError = big();
      if (files.uploadError) return render();
      const fd = new FormData(); fd.append("file", input.files[0]);
      try { const r = await api("/api/purchases/upload", { method: "POST", body: fd }); files.open = r.id; files.detail = null; input.value = ""; toast(r.shipped_first ? "Uploaded: the purchase file that came with the code is read first, then this one, in the background" : "Uploaded: it is read in the background"); enterFiles(); }
      catch (e) { files.uploadError = e.message; render(); }
    };
    const shipped = async () => {
      try { const r = await api("/api/purchases/load-shipped", { method: "POST" }); files.open = r.id; files.detail = null; toast("Loading the purchase file that came with the code"); enterFiles(); }
      catch (e) { toast(e.message, false); }
    };
    const row = u => {
      const counts = u.status === "done" || u.rows_loaded !== null ? [u.rows_total !== null ? `${n0(u.rows_total)} rows` : null, u.rows_loaded !== null ? `${n0(u.rows_loaded)} order lines kept (` + [`${n0(u.rows_new || 0)} new`, `${n0(u.rows_changed || 0)} changed`, `${n0(u.rows_same || 0)} already in, the same`,
          u.rows_older ? `${n0(u.rows_older)} not used: a newer file has them (newer by what it covers, or saved later)` : null, u.rows_disagree ? `${n0(u.rows_disagree)} not used: the history disagrees and which is newer cannot be told, nor by when they were saved` : null].filter(Boolean).join(", ") + ")" : null,
        savedNote(u), u.disagree_open ? `${n0(u.disagree_open)} ${u.disagree_open === 1 ? "disagreement" : "disagreements"} open, for an admin` : null,
        (u.summary || {}).disagreements ? `${n0(u.summary.disagreements)} ${u.summary.disagreements === 1 ? "disagreement" : "disagreements"} with the history listed for an admin (open the upload)` : null, u.rows_removed ? `${n0(u.rows_removed)} removed (this newer file shows them deleted, blocked or no longer bulk)` : null,
        u.rows_outliers ? `${n0(u.rows_outliers)} ZLOI ${u.rows_outliers === 1 ? "line" : "lines"}, kept apart` : null,
        u.rows_stored !== null && u.rows_stored !== undefined ? `${n0(u.rows_stored)} rows stored, of which ${n0(u.rows_other || 0)} in no figure (sample and yardage orders, deleted lines, other currencies or units: shown in the price history by type)` : null,
        u.rows_skipped !== null ? `${n0(u.rows_skipped - (u.rows_other || 0))} left out, not stored` : null].filter(Boolean).join(" · ") : "";
      return h("tr", { class: files.open === u.id ? "picked" : null },
        h("td", {}, h("button", { type: "button", class: "code", onclick: async () => { files.open = files.open === u.id ? null : u.id; files.detail = null; if (files.open) { try { files.detail = await api("/api/purchases/uploads/" + u.id); } catch (e) { toast(e.message, false); } } render(); } }, `#${u.id}`)),
        h("td", { class: "w" }, u.filename, h("div", { class: "muted" }, `${day(u.uploaded_at)}${u.uploaded_by ? " by " + u.uploaded_by : ""}` + (u.file_date_from ? ` · ${u.file_date_from}` : ""))),
        h("td", { class: "w" }, h("span", { class: "upst " + u.status }, STATUS_WORDS[u.status] || u.status), u.step ? h("div", { class: "muted" }, u.step) : null, u.error ? h("div", { class: "err" }, u.error) : null),
        h("td", { class: "w" }, counts, u.status === "done" ? h("div", { class: "muted" }, `${n0(u.fabrics_new || 0)} new fabric codes, ${n0(u.groups_new || 0)} new Fab groups, ${n0(u.mills_new || 0)} new mills`) : null));
    };
    const det = files.open && files.detail && files.detail.id === files.open ? files.detail : null;
    fillP(main, top, title,
      h("p", { class: "muted" }, "Purchase-order files, as SAP exports them (Purchasing Document, Item, Document Date, Material, Short Text, Order Quantity, Net Price, Name of Supplier, Purchasing Doc. Type, Deletion Indicator ...). Each is read in the background: the page shows where it stands. The same order line uploaded twice is one line. Uploading is an admin action (Admin and Rates editor; see Users and roles)."),
      h("div", { class: "stiles" }, tile("Purchase lines on record", n0(c.lines), c.first ? `${day(c.first)} to ${day(c.last)}` : "none yet"), tile("Fabric codes", n0(c.fabrics), `${n0(c.fabrics_grouped)} in Fab groups`),
        tile("Fab groups", n0(c.groups), c.groups_merged ? `${c.groups_merged} merged into others` : "", ""), tile("Mills", n0(c.mills), "every spelling kept")),
      // where Right cost's purchase-order rows come from: the file that came with the code until the history holds a file, then the history alone
      d.shipped.available && !d.shipped.loaded ? h("p", { class: "note" }, d.shipped.history
        ? "The purchase file that came with the code (the pilot's purchases, 1 Aug to 23 Nov 2026) is not loaded. Right cost's purchase-order rows, the price popup and the Fab groups read only the files uploaded here, so a pilot fabric that is in none of them shows no price paid." + (may("do:upload_purchases") ? " Load it below to have them all." : " An admin can load it here.")
        : "Nothing is loaded yet: Right cost's purchase-order rows show the pilot's purchases as the purchase file that came with the code has them. The purchase history always starts from that file (GP, 28 Nov 2026): it is loaded first, as its own upload, when the first file is uploaded here (or with the button below), and from then on Right cost, the price popup and the Fab groups read the history.") : null,
      !may("do:upload_purchases") ? h("p", { class: "note" }, `Your role${typeof RPA !== "undefined" && RPA.me && RPA.me.role ? " (" + RPA.me.role + ")" : ""} may look at the uploads but not upload: that is an admin action.`) :
      h("section", { class: "sec" }, h("h2", {}, "Upload a purchase-order file"), h("div", { class: "uprow" }, input, h("button", { type: "button", class: "btn fill", onclick: send }, "Upload")),
        files.uploadError ? h("p", { class: "err", role: "alert" }, files.uploadError) : h("p", { class: "muted" }, `Up to ${Math.floor(d.max_bytes / 1048576)} MB a file: a longer period goes in as several files, by 6 months or by year.`),
        d.shipped.available ? [h("h3", {}, "Or load the file that came with the code" + (d.shipped.loaded ? " (loaded already)" : "")),
          h("p", { class: "muted" }, "inputs/Fabric _ 3Months_4746.xlsx: the purchase orders of 1 Aug to 23 Nov 2026 that the pilot was run on, as SAP exported them on 23 Nov 2026. Each order line is kept once, and it never undoes a newer file, nor one covering the same orders saved later."),
          h("button", { type: "button", class: "btn line", onclick: shipped }, "Load the purchase file that came with the code")] : null),
      h("section", { class: "sec" }, h("h2", {}, "Uploads"), c.disagreements ? h("p", { class: "note" }, `${n0(c.disagreements)} ${c.disagreements === 1 ? "disagreement" : "disagreements"} between a file and the history ${c.disagreements === 1 ? "is" : "are"} open, for an admin: the uploads with them are listed below, however old.`) : null,
        d.uploads.length ? h("div", { class: "gridscroll sup pgt" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Upload", "File", "Where it stands", "What was read"].map(t => h("th", {}, t)))), h("tbody", {}, d.uploads.map(row))))
          : h("p", { class: "muted" }, "No file uploaded yet."),
        det ? skippedView(det) : null),
      h("p", { class: "muted", style: "margin-top:14px" }, "Every row of a file is stored (GP, 28 Nov 2026) and shown in the price history by its type; what counts in prices, ranges and verdicts is as the pilot keeps it: bulk orders (BO, BF), priced, in rupees, per metre, not deleted or blocked in SAP; ZLOI lines are kept apart and left out of every figure. The newest file wins. Which is newer is read first from what a file covers: a file was taken no earlier than its latest document date (or the report date it carries in a column of its own) and no later than it was saved; one file taken after the other for certain is newer, and that decides. Where what they cover cannot tell (a correction of the same orders, the same file saved again), the file saved later wins, exactly as a newer file does (GP's decision, 28 Nov 2026). Nothing dated after the upload is trusted: a saved date after it (a clock set wrong), or before the file's latest order, is not used, and the file is dated by its upload instead; a report date counts only between its latest order and when it was saved; a document date after the upload is not used to date the file. Document dates are days in India; saved times are UTC. The upload's page says which file won and why, with both saved times, and every date it did not use. Every order line keeps the word of the newest file that covered it: its figures, or that it was deleted, blocked, no longer bulk, not in rupees or not per metre; an older or earlier-saved file never changes it or brings it back. A line simply not in a newer file is never taken as cancelled: the history keeps it (GP, 28 Nov 2026), so a later download covering a longer span takes each line once. Only where two files carry the very same dates, to the second, and a file disagrees with the history, the history stands and the upload lists the disagreement, for an admin to keep or to take the file's figures. A date written as text is read as year-month-day (2026-04-03 is 3 April); one that could be read two ways is left out with why. Fabric codes are matched to their PLM specification and Fab group; a code whose specification is missing or incomplete is not grouped. The PLM specifications come from the Fab library once the PLM fabric code list is uploaded there (a list that corrects a code moves it to its Fab group and costs it again at once); before that, from the extract deployed with the code (data/plm_specs_for_po.csv in the code's own folder, not the data folder)."));
  }
  // TOO BIG: what a file over the limit is told on the screen at once, before it is sent (as rules/purchases.py too_big;
  // check_server.py runs this function and compares the two)
  function tooBig(size, max, name) {
    return size > max ? `${name} is ${(size / 1048576).toFixed(1)} MB: larger than ${Math.floor(max / 1048576)} MB, the most read at once. Split it in SAP by 6 months or by year, and upload each part.` : null;
  }
  // END TOO BIG
  // what the saved date decided (GP, 28 Nov 2026): where what two files cover cannot tell which is newer, the file saved
  // later wins; the upload's page says which won and why, with both saved times
  const utc = t => `${t.slice(0, 16).replace("T", " ")} UTC`;
  const savedWhen = x => (x.report_used ? `taken on ${x.report_used.slice(0, 10)} (the report date it carries), ` : "") +
    (x.covers_saved && x.covers_saved === x.saved_at ? `saved ${utc(x.covers_saved)}` : x.covers_saved ? `uploaded ${utc(x.covers_saved)} (no saved date it can be dated by)` : "no saved date");
  const upName = x => `upload #${x.id}${x.filename ? " (" + x.filename + ")" : ""}`;
  const nLines = k => `${n0(k)} ${k === 1 ? "line" : "lines"}`;
  function savedNote(u) {
    const s = u.summary || {}, won = (s.saved_later_than || []).reduce((a, x) => a + x.lines, 0), lost = (s.saved_earlier_than || []).reduce((a, x) => a + x.lines, 0);
    return won || lost ? [won ? `saved later than another file covering the same orders: its word taken on ${nLines(won)}` : null,
      lost ? `${nLines(lost)} where a file covering the same orders, saved later, stands` : null].filter(Boolean).join("; ") + " (open the upload)" : null;
  }
  function savedView(u) {
    const s = u.summary || {}, later = s.saved_later_than || [], earlier = s.saved_earlier_than || [];
    if (!later.length && !earlier.length) return null;
    return [h("h3", {}, "Decided by when the files were saved"),
      h("p", { class: "muted" }, "What these files cover cannot tell which is newer (each could have been taken before the other), so the file saved later wins, as a newer file does: its figures, and the lines it shows deleted or no longer bulk (GP's decision, 28 Nov 2026)."),
      later.map(x => h("p", {}, `This file won on ${nLines(x.lines)} over ${upName(x)}, because it was saved later: this file ${savedWhen(u)}; ${upName(x)} ${savedWhen(x)}. This file's word replaced that one's.`)),
      earlier.map(x => h("p", {}, `${upName(x)} won on ${nLines(x.lines)} where this file says otherwise, because it was saved later: ${upName(x)} ${savedWhen(x)}; this file ${savedWhen(u)}. Its word stands there; this file's is not used.`))];
  }
  // what a file and the history disagree on (which is newer could not be told, nor by the saved dates): listed, to keep or to take the file's
  const side = x => x.code ? `${x.code} · ${day(x.date)} · ${x.type} · ${x.mill} · ${n0(x.metres)} m at Rs ${n2(x.price)}` + (x.removed ? ` (not counted: ${x.removed})` : "") : `not counted: ${x.removed || "no figures"}`;
  function disagreeView(u) {
    if (!u.disagree_count) return null;
    const settle = async take => {
      if (!confirm(take === "file" ? `Take this file's figures for the ${u.disagree_open} lines still open? Each line the history still holds as it did then takes this file's word.` : `Keep the history's figures for the ${u.disagree_open} lines still open?`)) return;
      try { const r = await api("/api/purchases/disagreements", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ upload_id: u.id, take }) }); toast(`Settled ${r.settled}: ${r.took} kept` + (r.left_as_they_are ? `; ${r.left_as_they_are} left as they are (decided since)` : "")); files.detail = null; enterFiles(); }
      catch (e) { toast(e.message, false); }
    };
    return [h("h3", {}, `This file and the history disagree on ${n0(u.disagree_count)} ${u.disagree_count === 1 ? "line" : "lines"}`),
      h("p", { class: "muted" }, "Which of the two is newer could not be told: not from what they cover (their latest document dates, a report date), and not from when they were saved, because both carry the very same dates, to the second (a file with no saved date it can be dated by counts as saved when it was uploaded). So nothing was guessed: the history's figures were kept." +
        (u.disagree_open ? " An admin can keep them, or take this file's." : u.disagreements.some(x => x.settled_as === "file") ? " Settled: this file's figures were taken." : " Settled: the history's figures were kept.")),
      u.disagree_open && may("do:upload_purchases") ? h("div", { class: "acts" }, h("button", { type: "button", class: "btn line", onclick: () => settle("kept") }, "Keep the history's figures"), h("button", { type: "button", class: "btn fill", onclick: () => settle("file") }, "Take this file's figures")) : null,
      table(["Order", "Item", "Kept (from)", "This file says", "Settled"], u.disagreements.map(x => [x.po, x.item, wide(side(x.kept) + (x.kept.file ? ` [${x.kept.file}]` : "")), wide(side(x.file)), x.settled_at ? `${day(x.settled_at)}${x.settled_by ? " by " + x.settled_by : ""}: ${x.settled_as === "file" ? "this file's taken" : "the history's kept"}` : "open"]), []),
      u.disagree_count > u.disagreements.length ? h("p", { class: "muted" }, `The first ${u.disagreements.length} are shown; settling covers all ${n0(u.disagree_count)}.`) : null];
  }
  function skippedView(u) {
    const s = u.summary || {};
    const fut = s.future || [], notes = s.dating_notes || [], ch = s.changed_lines || [];
    const brief = x => x.removed ? `not counted: ${x.removed}` : `${day(x.date)} · ${x.type} · ${n0(x.metres)} m at Rs ${n2(x.price)}`;
    const noSpec = (s.not_grouped || []).filter(([k]) => /PLM specification/.test(k)).reduce((a, [, n]) => a + n, 0);
    return h("div", { class: "updetail" }, h("h3", {}, `Upload #${u.id}: ${u.filename}`), savedView(u), disagreeView(u),
      u.status === "done" ? h("p", {}, `Already in the history: ${n0(u.rows_same || 0)} order lines, the same in this file (one line each, counted once). Updated by this file: ${n0((u.rows_changed || 0) + (u.rows_removed || 0))}` +
        ((u.rows_changed || 0) + (u.rows_removed || 0) ? ` (${n0(u.rows_changed || 0)} with its newer figures, ${n0(u.rows_removed || 0)} it shows no longer bought)` : "") + ". New: " + n0(u.rows_new || 0) + ".") : null,
      ch.length ? table(["Order", "Item", "Was", "Now (this file)"], ch.map(x => [x.po, x.item, wide(brief(x.was)), wide(brief(x.now))]), []) : null,
      ch.length && ch.length < (u.rows_changed || 0) + (u.rows_removed || 0) ? h("p", { class: "muted" }, `The first ${ch.length} are shown.`) : null,
      noSpec ? h("p", { class: "note" }, `${n0(noSpec)} ${noSpec === 1 ? "code has" : "codes have"} no PLM specification, or an incomplete one: ${noSpec === 1 ? "its lines are" : "their lines are"} loaded and counted in ${noSpec === 1 ? "its" : "their"} prices like any other, with the construction blank (not in a Fab group, no should-cost).`) : null,
      notes.filter(t => !/dated after it was uploaded/.test(t)).length ? h("p", { class: "note" }, "Dates not used to put this file in order: " + notes.filter(t => !/dated after it was uploaded/.test(t)).join("; ") + ".") : null,
      s.future_count ? h("p", { class: "note" }, `${n0(s.future_count)} ${s.future_count === 1 ? "row is" : "rows are"} dated after the file was uploaded, so the ${s.future_count === 1 ? "date is" : "dates are"} not used to date the file: ` +
        fut.slice(0, 5).map(x => `row ${x.row} (order ${x.po}/${x.item}, ${x.date})`).join(", ") + (s.future_count > 5 ? ` and ${n0(s.future_count - 5)} more` : "") + ". Check them in SAP; the rows are kept as they are.") : null,
      u.status === "done" ? h("p", {}, `Order lines dated ${day(s.first)} to ${day(s.last)}, from ${n0(s.mills)} ${s.mills === 1 ? "spelling of a mill" : "mill spellings"}, for ${n0(s.fabrics)} fabric codes: ${n0(s.grouped)} in Fab groups, ${n0(s.costed)} costed.` +
        (s.not_grouped && s.not_grouped.length ? ` Not grouped: ${s.not_grouped.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")}.` : "")) : null,
      u.status === "done" && u.rows_stored !== null && u.rows_stored !== undefined ? h("p", {}, `Stored: ${n0(u.rows_stored)} rows. They count in prices, ranges and verdicts: ${n0((u.rows_loaded || 0) - (u.rows_outliers || 0))} (bulk orders BO and BF, in rupees per metre)` +
        `; kept apart: ${n0(u.rows_outliers || 0)} ZLOI; in no figure, shown in the price history by type: ${n0(u.rows_other || 0)}` + ((s.other_by_kind || []).length ? ` (${s.other_by_kind.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")})` : "") + ".") : null,
      u.skipped_count ? [h("p", {}, `Not counted: ${n0(u.skipped_count)} rows, ${n0(u.skipped_count - (u.rows_other || 0))} of them left out, not stored (no order number, repeated, no material or supplier, a date that cannot be read). ` + (s.skipped_by_kind || []).map(([k, n]) => `${k}: ${n0(n)}`).join("; ") + ".",
        " ", h("a", { href: `/api/purchases/skipped/${u.id}`, download: "" }, "Download every row not counted (Excel)")),
      table(["Row", "Order", "Item", "Material", "Why it is not counted", "Stored"], u.skipped.slice(0, files.rows).map(x => [String(x.row), x.po, x.item, x.material, wide(x.why), x.stored ? "stored, in the price history" : "left out"]), [0]),
      u.skipped.length > files.rows ? h("p", {}, h("button", { type: "button", class: "btn line", onclick: () => { files.rows = u.skipped.length; render(); } }, `Show the first ${u.skipped.length}`)) : null,
      u.skipped_count > Math.min(files.rows, u.skipped.length) ? h("p", { class: "muted" }, `The first ${Math.min(files.rows, u.skipped.length)} are shown; the download has ${u.skipped_listed < u.skipped_count ? "the first " + n0(u.skipped_listed) + " (the counts above cover all " + n0(u.skipped_count) + ")" : "all " + n0(u.skipped_count)}.`) : null] : (u.status === "done" ? h("p", { class: "muted" }, "No row was left out.") : null));
  }

  // ---------------------------------------------------------------- #purchase-lines: every stored line, filtered (GP, 28 Nov 2026)
  // Filtered and paged on the server (it stays quick with a million lines); the Excel download has what is filtered. The
  // table of order types is on this page too: a rates editor or an admin corrects it, and the lines are counted again.
  const pl = { data: null, error: null, f: {}, page: 1, types: null, busy: false };
  const LINE_FILTERS = [["order_type", "Order type"], ["sourcing", "Mode of sourcing"], ["unit", "Unit"], ["currency", "Currency"], ["month", "Month"], ["mill", "Mill"], ["counts", "Counts"]];
  const plQuery = (extra) => Object.entries(Object.assign({}, pl.f, extra || {})).filter(([, v]) => v !== "" && v !== null && v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  async function enterLines() {
    await known(); if (!may("page:purchase_lines")) return;
    pl.busy = true;
    try { [pl.data, pl.types] = await Promise.all([api("/api/purchases/lines?" + plQuery({ page: pl.page })), api("/api/purchases/order-types")]); pl.error = null; } catch (e) { pl.error = e.message; }
    pl.busy = false;
    if (state.page && state.page.id === "purchase-lines") render();
  }
  function renderLines(main) {
    tip.hidden = true;
    $("#selbar").hidden = true;
    const top = crumbs("Purchase lines"), title = h("div", { class: "headrow" }, h("h1", { class: "ptitle" }, "Purchase lines"));
    if (pl.error) return fillP(main, top, title, h("p", { class: needsDb(pl.error) ? "note" : "err" }, pl.error));
    if (!pl.data) return fillP(main, top, title, h("div", { class: "empty" }, "Loading…"));
    const d = pl.data, fc = d.facets;
    const opts = (k) => k === "order_type" ? fc.order_types : k === "sourcing" ? [["Domestic", null], ["Import", null]] : k === "unit" ? fc.units : k === "currency" ? fc.currencies
      : k === "month" ? fc.months : k === "mill" ? fc.mills : [["counts", "Counts in the figures"], ["apart", "Kept apart (in no rupees-per-metre figure)"]];
    const sel = {}, text = {};
    const bar = h("div", { class: "plfilters" }, LINE_FILTERS.map(([k, label]) => {
      sel[k] = h("select", { "aria-label": label }, h("option", { value: "" }, `${label}: all`), opts(k).map(([v, n]) => h("option", { value: v, selected: pl.f[k] === v ? true : null },
        k === "counts" ? n : `${k === "month" ? monthWords(v) : v || "(blank)"}${n !== null && n !== undefined && k !== "counts" ? ` (${n0(n)})` : ""}`)));
      return h("label", {}, sel[k]);
    }), [["group", "Fab group", "Fab-0012"], ["code", "Fabric code", "a code"]].map(([k, label, ph]) => { text[k] = h("input", { type: "text", "aria-label": label, placeholder: `${label}: ${ph}`, value: pl.f[k] || "" }); return h("label", {}, text[k]); }),
      h("button", { type: "button", class: "btn fill", onclick: () => { pl.f = {}; for (const k in sel) pl.f[k] = sel[k].value; for (const k in text) pl.f[k] = text[k].value.trim(); pl.page = 1; enterLines(); } }, "Filter"),
      h("button", { type: "button", class: "btn line", onclick: () => { pl.f = {}; pl.page = 1; enterLines(); } }, "Clear"));
    const go = n => { pl.page = n; enterLines(); };
    const rs = r => r.price_rs === null ? h("span", { class: "muted", title: r.rate_why || "" }, r.rate_why ? "no rate yet" : "") : n2(r.price_rs);
    fillP(main, top, title, h("p", { class: "muted" }, d.note),
      bar,
      h("div", { class: "toolbar" }, h("span", { class: "count" }, `${n0(d.total)} ${d.total === 1 ? "line" : "lines"} of ${n0(fc.total)}` + (d.pages > 1 ? ` · page ${d.page} of ${n0(d.pages)}` : "")),
        d.total && d.total <= d.excel_max ? h("a", { class: "btn line", href: "/api/purchases/lines/download?" + plQuery(), download: "" }, "Download Excel (what is filtered)") : h("span", { class: "muted" }, d.total ? "Too many lines for one Excel sheet: filter by month or order type first" : "")),
      d.rows.length ? table(["Date", "Order", "Fabric code", "Mill", "SAP type", "Order type", "Sourcing", "Quantity", "Price", "Rate", "Price Rs", "Value Rs", "Counts", "Fab group", "Construction"],
        d.rows.map(r => [day(r.date), `${r.po}/${r.item}`, r.code ? codeLink(r.code) : "", wide(h("span", {}, r.mill || "")), r.sap_type, r.order_type, r.sourcing + (r.currency && r.currency !== "INR" ? `, ${r.currency}` : ""),
          qtyWords(r), priceWords(r), r.rate === null ? "" : n2(r.rate), rs(r), r.value_rs === null ? "" : n0(r.value_rs),
          r.counts ? "yes" : h("span", { class: "muted", title: r.why || "" }, "no: " + (r.why || "")), r.group ? groupLink(r.group) : "", wide(h("span", { class: "muted" }, r.construction || ""))]), [7, 8, 9, 10, 11])
        : h("div", { class: "empty" }, "No line matches."),
      d.pages > 1 ? h("div", { class: "acts noprint" }, h("button", { type: "button", class: "btn line", disabled: d.page <= 1 || pl.busy ? true : null, onclick: () => go(d.page - 1) }, "Previous"),
        h("button", { type: "button", class: "btn line", disabled: d.page >= d.pages || pl.busy ? true : null, onclick: () => go(d.page + 1) }, "Next")) : null,
      orderTypes());
  }
  function orderTypes() {
    const t = pl.types;
    if (!t) return null;
    const edit = may("do:edit_rates");
    const put = async (sap_type, category) => {
      try { const r = await api("/api/purchases/order-types", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sap_type, category }) });
        toast(`${r.sap_type} is ${r.category} now` + (r.lines_now_counted || r.lines_now_apart ? `: ${n0(r.lines_now_counted)} lines count, ${n0(r.lines_now_apart)} kept apart` : "")); reloadCosts(); list.data = null; page.group = null; enterLines(); }
      catch (e) { toast(e.message, false); }
    };
    const pick = (sap, now) => edit ? h("select", { "aria-label": `Order type of ${sap}`, onchange: e => put(sap, e.target.value) }, (now ? [] : [h("option", { value: "" }, "Other (not in the table)")]).concat(t.categories.map(cat => h("option", { value: cat, selected: cat === now ? true : null }, cat)))) : (now || "Other");
    return h("section", { class: "sec" }, h("h2", {}, "Order types"), h("p", { class: "muted" }, t.rule + (edit ? " Changing one counts its lines again at once." : " A rates editor or an admin changes them.")),
      table(["SAP type", "Order type", "Lines", "From"], t.types.map(x => [x.sap_type, pick(x.sap_type, x.category), n0(x.lines), wide(h("span", { class: "muted" }, x.basis + (x.changed_by ? `, ${x.changed_by}` : "") + (x.basis.startsWith("Set") ? ` on ${day(x.changed_at)}` : "")))]), [2]),
      t.not_in_table.length ? [h("h3", {}, "Types the history has that the table does not (counted as Other)"),
        table(["SAP type", "Order type", "Lines"], t.not_in_table.map(x => [x.sap_type || "(blank)", x.sap_type ? pick(x.sap_type, null) : "Other", n0(x.lines)]), [2])] : null);
  }

  // ---------------------------------------------------------------- what the shell sees
  window.RP_PAGES = {
    group: { enter: enterGroup, render: renderGroup, title: p => p.arg || "Fab group", rail: "costs" },
    groups: { enter: () => enterGroups(true), render: renderGroups, title: () => "Fab groups", rail: "costs" },
    "purchase-files": { enter: enterFiles, render: renderFiles, title: () => "Purchase files", rail: null },
    "purchase-lines": { enter: enterLines, render: renderLines, title: () => "Purchase lines", rail: null },
  };
  window.RP_PURCH = {
    openHistory, outliers, imports,
    // Right cost's Fab group cell: the group (to its page) and the price popup
    cell(r) {
      if (r.source !== "Purchase orders" || (r.fab_group === undefined && r.fab_group_name === undefined) || (r.fab_group === null && !r.fab_group_name)) return "";
      const chart = tipOn(h("button", { type: "button", class: "ib pib", onclick: e => { e.stopPropagation(); openHistory(r.code); }, html: svg("chart") }), "Price over time for " + r.code);
      return h("span", { class: "fgcell" }, r.fab_group ? tipOn(may("page:groups") ? h("button", { type: "button", class: "code", onclick: () => { location.hash = "#group/" + encodeURIComponent(r.fab_group); } }, r.fab_group) : h("span", {}, r.fab_group), r.fab_group_name || "")
        : tipOn(h("span", { class: "muted" }, "Not grouped"), r.fab_group_name || "Not grouped"), chart);
    },
  };
})();
