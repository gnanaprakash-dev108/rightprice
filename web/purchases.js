/* Stage 2: purchase history and Fab groups. Loaded before rightcost.js and kept apart from it: everything here is
   inside one function, and only RP_PAGES (the pages this file draws) and RP_PURCH (the price popup, the Fab group cell)
   are seen outside. It uses the shell's own helpers (h, fill, svg, ib, tipOn, n0, n2, pc, toast, dayOf, state ...)
   when it runs, never while it loads.
   Pages: #group/<Fab code> (a Fab group), #groups (every Fab group; the admin merge), #purchase-files (the admin
   upload). Charts are plain SVG drawn here. Prices and supplier names come from this server only. */
"use strict";
(function () {
  // ---------------------------------------------------------------- small helpers
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
  const groupLink = code => h("button", { type: "button", class: "code", onclick: () => { closePopups(); location.hash = "#group/" + encodeURIComponent(code); } }, code);
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
      o.band ? h("span", {}, h("i", { class: "bandkey" }), o.band.label) : null);
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
      if (o.band) s.append(el("rect", { x: m.l, width: W - m.l - m.r, y: Y(o.band.upper), height: Math.max(1, Y(o.band.lower) - Y(o.band.upper)), class: "band" }));
      for (const k of (o.marks || []).filter(k => k.y)) s.append(el("line", { x1: m.l, x2: W - m.r, y1: Y(k.y), y2: Y(k.y), class: "mark " + k.cls }));
      // one dot per date, price and series: lines of one order at one price sit on one dot
      const dots = {};
      for (const p of o.points) { const key = p.series + "|" + p.date + "|" + p.price; (dots[key] = dots[key] || Object.assign({ n: 0, metres: 0, texts: [] }, p)).n++; dots[key].metres += p.metres || 0; dots[key].texts.push(p.text); }
      const order = o.series.map(x => x.key);
      for (const p of Object.values(dots).sort((a, b) => order.indexOf(b.series) - order.indexOf(a.series))) {
        const ser = o.series.find(x => x.key === p.series) || {}, cx = X(t(p.date)), cy = Y(p.price);
        const g = el("g", { class: "pt" }, el("circle", { cx, cy, r: ser.big ? 5.5 : 4.5, class: "dotm " + (ser.cls || "") }), el("circle", { cx, cy, r: 10, class: "hit" }));
        const words = `${day(p.date)} · Rs ${n2(p.price)} · ${n0(p.metres)} m` + (p.n > 1 ? ` (${p.n} lines)` : "") + " · " + [...new Set(p.texts)].slice(0, 3).join("; ");
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
    : `${r.n} ${r.n === 1 ? "purchase" : "purchases"}; a usual range needs at least ${min}`;

  // ---------------------------------------------------------------- the price popup: one fabric code
  async function openHistory(code) {
    closePopups();
    const body = h("div", { class: "pbody" }, h("div", { class: "empty" }, "Loading…"));
    const d = h("div", { class: "dialog pdialog", role: "dialog", "aria-modal": "true", "aria-label": "Price over time: " + code },
      h("div", { class: "phead" }, h("h2", {}, "Price over time: " + code), ib("x", "Close", () => s.remove())), body);
    const s = h("div", { class: "scrim pdlg", onmousedown: e => { if (e.target === s) s.remove(); } }, d);
    $("#layer").append(s);
    d.querySelector("button").focus();
    let x;
    try { x = await api("/api/purchases/history?code=" + encodeURIComponent(code)); }
    catch (e) { fill(body, h("p", { class: needsDb(e.message) ? "muted" : "err" }, e.message)); return; }
    const g = x.group, sp = x.spec;
    const num = v => v === "" || isNaN(Number(v)) ? v : String(Number(v));
    const specLine = sp ? "PLM: " + [sp.blend_name, sp.dyemethod_name, sp.weavetype_name, `${sp.warpcount} x ${sp.weftcount}`, `${num(sp.epi)} x ${num(sp.ppi)}`, `${num(sp.finishedwidth)} ${sp.finishedwidth_uom}`, String(sp.finish_name || "").replace(/^F\s*-\s*/, "")].filter(Boolean).join(" · ") : "No PLM specification for this code";
    const pts = x.lines.map(l => ({ date: l.date, price: l.price, metres: l.metres, series: "this", text: `${l.mill}, order ${l.po}/${l.item}` }));
    if (g) for (const l of g.lines) if (l.code !== x.code) pts.push({ date: l.date, price: l.price, metres: l.metres, series: "group", text: `${l.code}, ${l.mill}` });
    const series = [{ key: "this", name: `This code, ${x.code}`, cls: "s1", big: true }, { key: "group", name: g ? `Other codes of ${g.code} (the same construction, any colour)` : "", cls: "s0" }];
    const marks = [x.should ? { y: x.should, label: "Should-cost", cls: "should" } : null, g && g.range.median ? { y: g.range.median, label: `${g.code} median`, cls: "median" } : null].filter(Boolean);
    const others = g ? g.lines.filter(l => l.code !== x.code).length : 0;
    fill(body,
      h("p", { class: "muted" }, specLine),
      h("div", { class: "stiles" },
        tile("Bought", `${n0(x.lines.length)} ${x.lines.length === 1 ? "purchase" : "purchases"}`, `${n0(x.metres)} m on ${x.orders} ${x.orders === 1 ? "order" : "orders"}`),
        tile("Price paid", x.lines.length ? (x.lines.length > 1 ? `Rs ${n2(Math.min(...x.lines.map(l => l.price)))} to ${n2(Math.max(...x.lines.map(l => l.price)))}` : `Rs ${n2(x.lines[0].price)}`) : "None", x.lines.length ? `last on ${day(x.lines[x.lines.length - 1].date)}` : ""),
        tile("Should-cost", x.should ? `Rs ${n2(x.should)}` : "Not costed", x.should ? "on today's rates" : x.should_why),
        g ? tile(`Fab group ${g.code}`, g.range.enough ? rangeWords(g.range) : `${g.purchases} ${g.purchases === 1 ? "purchase" : "purchases"}`, g.range.enough ? `its usual range; median Rs ${n2(g.range.median)} on ${g.purchases} purchases` : `too few for a usual range (needs ${g.min_for_range})`) : tile("Fab group", "Not grouped", x.not_grouped)),
      pts.length ? priceChart({ points: pts, series, marks, band: g && g.range.enough ? { lower: g.range.lower, upper: g.range.upper, label: `${g.code} usual range` } : null, label: `Price over time for ${x.code}` }) : null,
      g ? h("p", { class: "muted" }, others ? `Grey dots: the ${others} other ${others === 1 ? "purchase" : "purchases"} of ${g.codes - 1} other ${g.codes - 1 === 1 ? "code" : "codes"} in Fab group ${g.code}, ${g.name}. Most codes are ordered once, so the group shows the history.`
        : `No other code of Fab group ${g.code} has been bought yet.`) : h("p", { class: "muted" }, `Not in a Fab group: ${x.not_grouped}. Nothing is guessed, so there is no group history to show.`),
      h("h3", {}, "Purchases of this code"),
      table(["Date", "Order", "Mill", "Metres", "Price Rs/m", "Against should-cost"], x.lines.map(l => [day(l.date), `${l.po}/${l.item}`, l.mill, n0(l.metres), n2(l.price), x.should ? pc((l.price / x.should - 1) * 100) : ""]), [3, 4, 5]),
      h("div", { class: "acts" }, g ? h("button", { type: "button", class: "btn fill", onclick: () => { s.remove(); location.hash = "#group/" + encodeURIComponent(g.code); } }, `Open Fab group ${g.code}`) : null,
        h("button", { type: "button", class: "btn line", onclick: () => s.remove() }, "Close")),
      h("p", { class: "muted" }, "Should-cost is on today's rates. Prices are the net price on each purchase-order line (ex-mill, Rs per metre)."));
  }

  // ---------------------------------------------------------------- #group/<code>: one Fab group
  const page = { group: null };
  async function enterGroup(p) {
    const code = p.arg;
    if (page.group && page.group.code === code && page.group.data) return;
    page.group = { code, data: null, error: null };
    try { page.group.data = await api("/api/groups/" + encodeURIComponent(code)); } catch (e) { page.group.error = e.message; }
    if (state.page && state.page.id === "group") render();
  }
  function renderGroup(main) {
    tip.hidden = true;
    const p = page.group || {}, d = p.data;
    const top = crumbs(["Right cost", "#rightcost"], ["Fab groups", "#groups"], (d && d.code) || p.code || "");
    $("#selbar").hidden = true;
    if (p.error) return fill(main, top, h("div", { class: "empty" }, p.error));
    if (!d) return fill(main, top, h("div", { class: "empty" }, "Loading…"));
    document.title = d.code + " - RightPrice";
    const r = d.range, sh = d.should, series = millSeries(d.mills), shown = new Set(series.map(x => x.key));
    const pts = d.lines.map(l => ({ date: l.date, price: l.price, metres: l.metres, series: shown.has(l.mill_key) ? l.mill_key : "*", text: `${l.mill}, ${l.code}` }));
    const marks = [sh.median ? { y: sh.median, label: "Should-cost", cls: "should" } : null, r.median ? { y: r.median, label: "Median paid", cls: "median" } : null].filter(Boolean);
    const vsShould = sh.median && r.median ? (r.median / sh.median - 1) * 100 : null;
    const inList = (state.rows || []).filter(x => x.fab_group === d.code).length;
    fill(main, top,
      h("div", { class: "dhead" }, h("div", {}, h("div", { class: "small" }, `Fab group · ${n0(d.fabrics.length)} fabric ${d.fabrics.length === 1 ? "code" : "codes"} · the same construction in any colour` + (d.first ? ` · bought ${day(d.first)} to ${day(d.last)}` : "")),
        h("h1", {}, d.code), h("div", { class: "gname" }, d.name)),
        h("div", { class: "dicons noprint" }, ib("pdf", "Print this page", () => print()),
          inList ? ib("pin", `Show its ${inList} purchase-order ${inList === 1 ? "costing" : "costings"} in Right cost`, () => { state.filters = { fab_group: [d.code] }; state.cls = "Purchase orders"; state.saved = "Default"; state.tab = "items"; location.hash = "#rightcost"; }) : null)),
      d.asked ? h("p", { class: "note" }, `${d.asked.code} (${d.asked.name}) was merged into this group` + (d.asked.merged_at ? ` on ${day(d.asked.merged_at)}` : "") + (d.asked.merged_by ? ` by ${d.asked.merged_by}` : "") + `. Its code stays ${d.asked.code} and is never given to another group.`) : null,
      h("div", { class: "stiles" },
        tile("Purchases", `${n0(d.purchases)}`, `${n0(d.orders)} ${d.orders === 1 ? "order" : "orders"}, ${n0(d.metres)} m`),
        tile("Mills", `${d.mills.length}`, d.mills.slice(0, 3).map(m => m.name).join(", ") + (d.mills.length > 3 ? ` and ${d.mills.length - 3} more` : "")),
        tile("Median price paid", r.median ? `Rs ${n2(r.median)}` : "None", r.median ? `paid Rs ${n2(r.low)} to ${n2(r.high)}` : ""),
        tile("Usual range", rangeWords(r), rangeSub(r, d.min_for_range), r.enough ? "" : "amber"),
        tile("Should-cost", sh.median ? `Rs ${n2(sh.median)}` : "Not costed", sh.median ? (sh.low !== sh.high ? `Rs ${n2(sh.low)} to ${n2(sh.high)} across its codes (order size, pattern); ` : "") + `on today's rates` + (vsShould !== null ? `; the median paid is ${pc(vsShould)} against it` : "") : (sh.why_not[0] || "")),
        tile("Priced well above the group", r.enough ? `${d.above.length} ${d.above.length === 1 ? "purchase" : "purchases"}` : "No range yet", r.enough ? (d.above.length ? `Rs ${n0(d.above_rs)} above the top of the usual range` : "none above the top of its usual range") : "too few purchases to say", d.above.length ? "red" : "")),
      h("section", { class: "sec" }, h("h2", {}, "Price over time, by mill"),
        d.lines.length ? priceChart({ points: pts, series, marks, band: r.enough ? { lower: r.lower, upper: r.upper, label: "Usual range" } : null, label: `Prices paid for ${d.code} by date and mill`, height: 300 }) : h("p", { class: "muted" }, "No purchase on record."),
        h("p", { class: "muted" }, "One dot per purchase (lines of one order at one price share a dot). Point at a dot for its date, price, metres, mill and code." + (r.enough ? " The band is the group's usual range." : ""))),
      h("section", { class: "sec" }, h("h2", {}, "By mill"),
        table(["Mill", "Purchases", "Metres", "Share of metres", "Median Rs/m", "Lowest", "Highest", "Median against the group", "Last bought"],
          d.mills.map(m => [millLink(m.name, m.key), n0(m.lines), n0(m.metres), m.share === null ? "" : Math.round(m.share * 100) + "%", n2(m.median), n2(m.low), n2(m.high), m.vs_group === null ? "" : pc(m.vs_group), day(m.last)]), [1, 2, 3, 4, 5, 6, 7])),
      h("section", { class: "sec" }, h("h2", {}, "Priced well above the group"),
        !r.enough ? h("p", { class: "muted" }, `${r.n} ${r.n === 1 ? "purchase" : "purchases"} so far: too few for a usual range (it needs at least ${d.min_for_range}), so no purchase is called high. Load more purchase files as they come.`)
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
        h("dl", { class: "kv gfields" }, [["Content", d.fields.content], ["Dye method", d.fields.route], ["Weave", d.fields.weave], ["Warp", d.fields.warp], ["Weft", d.fields.weft], ["EPI x PPI", `${d.fields.epi} x ${d.fields.ppi}`], ["Finished width", `${d.fields.width_in} in`], ["Finish", d.fields.finish]].map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
        h("p", { class: "muted" }, "The nine fields of each code's PLM specification, tidied (spellings of a count or a fibre made one) and then matched exactly. A code whose specification is missing or incomplete is not put in any group."),
        d.merged_in.length ? h("p", {}, "Also counted here, merged in by an admin: " + d.merged_in.map(x => `${x.code} (${x.name})`).join("; ") + ".") : null),
      h("p", { class: "muted", style: "margin-top:18px" }, `"Priced well above the group" uses the negotiation brief's own rule: the usual range is the middle half of the group's past prices, kept between 5% and 10% either side of its median. Should-cost is on today's rates.`));
  }

  // ---------------------------------------------------------------- #groups: every Fab group, and the admin merge
  const list = { data: null, error: null, q: "", shown: 100 };
  async function enterGroups(force) {
    if (list.data && !force) return;
    try { list.data = await api("/api/groups"); list.error = null; } catch (e) { list.error = e.message; }
    if (state.page && state.page.id === "groups") render();
  }
  function renderGroups(main) {
    tip.hidden = true;
    const top = crumbs(["Right cost", "#rightcost"], "Fab groups");
    $("#selbar").hidden = true;
    if (list.error) return fill(main, top, h("h1", { class: "ptitle" }, "Fab groups"), h("p", { class: needsDb(list.error) ? "note" : "err" }, list.error));
    if (!list.data) return fill(main, top, h("div", { class: "empty" }, "Loading…"));
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
      try { const res = await api("/api/groups/merge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: from, into }) }); toast(`${res.merged} merged into ${res.into}`); page.group = null; reloadCosts(); await enterGroups(true); }
      catch (e) { toast(e.message, false); }
    };
    const undo = async code => {
      if (!await confirmBox(`Undo the merge of ${code}?`, [h("p", {}, `${code} counts on its own again.`)], "Undo the merge")) return;
      try { await api("/api/groups/unmerge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) }); toast(`${code} is on its own again`); page.group = null; reloadCosts(); await enterGroups(true); }
      catch (e) { toast(e.message, false); }
    };
    const c = d.counts;
    fill(main, top, h("div", { class: "headrow" }, h("h1", { class: "ptitle" }, "Fab groups")),
      h("p", { class: "muted" }, `${n0(c.groups)} groups of ${n0(c.fabrics_grouped)} fabric codes (the same construction in any colour, across mills), from ${n0(c.lines)} purchase lines` + (c.first ? `, ${day(c.first)} to ${day(c.last)}` : "") + `. ${n0(c.fabrics - c.fabrics_grouped)} codes are not grouped` + (d.not_grouped.length ? ` (${d.not_grouped.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")})` : "") + ".",
        " ", h("a", { href: "#purchase-files" }, "Purchase files")),
      h("div", { class: "toolbar" }, search, h("button", { type: "button", class: "btn line", onclick: () => { list.q = search.value; list.shown = 100; render(); } }, "Search"), h("span", { class: "count" }, `${n0(rows.length)} groups`)),
      rows.length ? table(["Fab group", "Construction", "Codes", "Purchases", "Metres", "Median Rs/m", "Last bought"],
        rows.slice(0, list.shown).map(g => [groupLink(g.code), wide(g.name), n0(g.codes), n0(g.purchases), n0(g.metres), g.median === null ? "" : n2(g.median), day(g.last)]), [2, 3, 4, 5]) : h("div", { class: "empty" }, c.groups ? "No group matches." : "No Fab groups yet: load a purchase file first."),
      rows.length > list.shown ? h("p", {}, h("button", { type: "button", class: "btn line", onclick: () => { list.shown += 200; render(); } }, `Show more (${n0(rows.length - list.shown)} more)`)) : null,
      h("section", { class: "sec noprint" }, h("h2", {}, "Admin: merge two Fab groups"),
        h("p", { class: "muted" }, "When two groups are really one cloth (a finish or a count written two ways), merge one into the other. Anyone signed in may do this for now; who may do what comes with the next stage."),
        h("div", { class: "mergerow" }, h("label", {}, "Merge ", a), h("label", {}, " into ", b), h("button", { type: "button", class: "btn fill", onclick: merge }, "Merge…")),
        d.merged.length ? [h("h3", {}, "Merged so far"), table(["Fab group", "Construction", "Counts in", "When", "By", ""], d.merged.map(m => [m.code, wide(m.name), groupLink(m.into), day(m.merged_at), m.merged_by || "", h("button", { type: "button", class: "btn line", onclick: () => undo(m.code) }, "Undo")]), [])] : null));
  }
  function confirmBox(title, body, yes) {
    return new Promise(done => {
      const s = dialog(title, h("div", {}, body), [h("button", { type: "button", class: "btn", onclick: () => { s.remove(); done(false); } }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => { s.remove(); done(true); } }, yes)]);
    });
  }
  const reloadCosts = () => { try { load(); } catch (e) { /* the list reloads at its next look */ } };

  // ---------------------------------------------------------------- #purchase-files: the admin upload
  const files = { data: null, error: null, open: null, detail: null, timer: null, rows: 30 };
  async function enterFiles() {
    clearTimeout(files.timer);
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
    if (files.error) return fill(main, top, title, h("p", { class: needsDb(files.error) ? "note" : "err" }, files.error));
    if (!files.data) return fill(main, top, title, h("div", { class: "empty" }, "Loading…"));
    const d = files.data, c = d.counts;
    const input = h("input", { type: "file", accept: ".xlsx,.xlsm", "aria-label": "Purchase-order file" });
    const send = async () => {
      if (!input.files.length) return toast("Choose the purchase-order file first", false);
      const fd = new FormData(); fd.append("file", input.files[0]);
      try { const r = await api("/api/purchases/upload", { method: "POST", body: fd }); files.open = r.id; files.detail = null; toast("Uploaded: it is read in the background"); enterFiles(); }
      catch (e) { toast(e.message, false); }
    };
    const shipped = async () => {
      try { const r = await api("/api/purchases/load-shipped", { method: "POST" }); files.open = r.id; files.detail = null; toast("Loading the purchase file that came with the code"); enterFiles(); }
      catch (e) { toast(e.message, false); }
    };
    const row = u => {
      const counts = u.status === "done" || u.rows_loaded !== null ? [u.rows_total !== null ? `${n0(u.rows_total)} rows` : null, u.rows_loaded !== null ? `${n0(u.rows_loaded)} order lines kept (${n0(u.rows_new || 0)} new, ${n0(u.rows_changed || 0)} changed, ${n0(u.rows_same || 0)} already in)` : null,
        u.rows_removed ? `${n0(u.rows_removed)} removed (deleted in SAP since)` : null, u.rows_skipped !== null ? `${n0(u.rows_skipped)} left out` : null].filter(Boolean).join(" · ") : "";
      return h("tr", { class: files.open === u.id ? "picked" : null },
        h("td", {}, h("button", { type: "button", class: "code", onclick: async () => { files.open = files.open === u.id ? null : u.id; files.detail = null; if (files.open) { try { files.detail = await api("/api/purchases/uploads/" + u.id); } catch (e) { toast(e.message, false); } } render(); } }, `#${u.id}`)),
        h("td", { class: "w" }, u.filename, h("div", { class: "muted" }, `${day(u.uploaded_at)}${u.uploaded_by ? " by " + u.uploaded_by : ""}`)),
        h("td", { class: "w" }, h("span", { class: "upst " + u.status }, STATUS_WORDS[u.status] || u.status), u.step ? h("div", { class: "muted" }, u.step) : null, u.error ? h("div", { class: "err" }, u.error) : null),
        h("td", { class: "w" }, counts, u.status === "done" ? h("div", { class: "muted" }, `${n0(u.fabrics_new || 0)} new fabric codes, ${n0(u.groups_new || 0)} new Fab groups, ${n0(u.mills_new || 0)} new mills`) : null));
    };
    const det = files.open && files.detail && files.detail.id === files.open ? files.detail : null;
    fill(main, top, title,
      h("p", { class: "muted" }, "Purchase-order files, as SAP exports them (Purchasing Document, Item, Document Date, Material, Short Text, Order Quantity, Net Price, Name of Supplier, Purchasing Doc. Type, Deletion Indicator ...). Each is read in the background: the page shows where it stands. The same order line uploaded twice is one line. Anyone signed in may upload for now; who may do what comes with the next stage."),
      h("div", { class: "stiles" }, tile("Purchase lines on record", n0(c.lines), c.first ? `${day(c.first)} to ${day(c.last)}` : "none yet"), tile("Fabric codes", n0(c.fabrics), `${n0(c.fabrics_grouped)} in Fab groups`),
        tile("Fab groups", n0(c.groups), c.groups_merged ? `${c.groups_merged} merged into others` : "", ""), tile("Mills", n0(c.mills), "every spelling kept")),
      h("section", { class: "sec" }, h("h2", {}, "Upload a purchase-order file"), h("div", { class: "uprow" }, input, h("button", { type: "button", class: "btn fill", onclick: send }, "Upload")),
        d.shipped.available ? [h("h3", {}, "Or load the file that came with the code"),
          h("p", { class: "muted" }, "inputs/Fabric _ 3Months_4746.xlsx: the purchase orders of 1 Aug to 23 Nov 2026 that the pilot was run on. Loading it again changes nothing: each order line is kept once."),
          h("button", { type: "button", class: "btn line", onclick: shipped }, "Load the purchase file that came with the code")] : null),
      h("section", { class: "sec" }, h("h2", {}, "Uploads"),
        d.uploads.length ? h("div", { class: "gridscroll sup pgt" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Upload", "File", "Where it stands", "What was read"].map(t => h("th", {}, t)))), h("tbody", {}, d.uploads.map(row))))
          : h("p", { class: "muted" }, "No file uploaded yet."),
        det ? skippedView(det) : null),
      h("p", { class: "muted", style: "margin-top:14px" }, "Kept from each file, as the pilot keeps it: bulk orders (BO, ZLOI, BF), priced, in rupees, per metre, not deleted or blocked in SAP. A line already on record with other figures takes the newer ones; one a later file shows deleted is marked removed and no longer counted. Fabric codes are matched to their PLM specification (data/plm_specs_for_po.csv) and Fab group; a code whose specification is missing or incomplete is not grouped."));
  }
  function skippedView(u) {
    const s = u.summary || {};
    return h("div", { class: "updetail" }, h("h3", {}, `Upload #${u.id}: ${u.filename}`),
      u.status === "done" ? h("p", {}, `Order lines dated ${day(s.first)} to ${day(s.last)}, from ${n0(s.mills)} ${s.mills === 1 ? "spelling of a mill" : "mill spellings"}, for ${n0(s.fabrics)} fabric codes: ${n0(s.grouped)} in Fab groups, ${n0(s.costed)} costed.` +
        (s.not_grouped && s.not_grouped.length ? ` Not grouped: ${s.not_grouped.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")}.` : "")) : null,
      u.skipped_count ? [h("p", {}, `Left out: ${n0(u.skipped_count)} rows. ` + (s.skipped_by_kind || []).map(([k, n]) => `${k}: ${n0(n)}`).join("; ") + ".",
        " ", h("a", { href: `/api/purchases/uploads/${u.id}/skipped`, download: "" }, "Download every row left out (Excel)")),
      table(["Row", "Order", "Item", "Material", "Why it was left out"], u.skipped.slice(0, files.rows).map(x => [String(x.row), x.po, x.item, x.material, wide(x.why)]), [0]),
      u.skipped.length > files.rows ? h("p", {}, h("button", { type: "button", class: "btn line", onclick: () => { files.rows = u.skipped.length; render(); } }, `Show the first ${u.skipped.length}`)) : null,
      u.skipped_count > Math.min(files.rows, u.skipped.length) ? h("p", { class: "muted" }, `The first ${Math.min(files.rows, u.skipped.length)} are shown; the download has all ${n0(u.skipped_count)}.`) : null] : (u.status === "done" ? h("p", { class: "muted" }, "No row was left out.") : null));
  }

  // ---------------------------------------------------------------- what the shell sees
  window.RP_PAGES = {
    group: { enter: enterGroup, render: renderGroup, title: p => p.arg || "Fab group", rail: "costs" },
    groups: { enter: () => enterGroups(true), render: renderGroups, title: () => "Fab groups", rail: "costs" },
    "purchase-files": { enter: enterFiles, render: renderFiles, title: () => "Purchase files", rail: null },
  };
  window.RP_PURCH = {
    openHistory,
    // Right cost's Fab group cell: the group (to its page) and the price popup
    cell(r) {
      if (r.source !== "Purchase orders" || (r.fab_group === undefined && r.fab_group_name === undefined) || (r.fab_group === null && !r.fab_group_name)) return "";
      const chart = tipOn(h("button", { type: "button", class: "ib pib", onclick: e => { e.stopPropagation(); openHistory(r.code); }, html: svg("chart") }), "Price over time for " + r.code);
      return h("span", { class: "fgcell" }, r.fab_group ? tipOn(h("button", { type: "button", class: "code", onclick: () => { location.hash = "#group/" + encodeURIComponent(r.fab_group); } }, r.fab_group), r.fab_group_name || "")
        : tipOn(h("span", { class: "muted" }, "Not grouped"), r.fab_group_name || "Not grouped"), chart);
    },
  };
})();
