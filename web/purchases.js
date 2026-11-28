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
  // one price for every purchase is said once: "Rs 208.00 (every purchase)", never "Rs 208.00 to 208.00"
  const priceSpan = (lo, hi) => n2(lo) === n2(hi) ? `Rs ${n2(lo)} (every purchase)` : `Rs ${n2(lo)} to ${n2(hi)}`;
  // GROUP SEARCH: every word of the search, anywhere in the code or the name ("Twill 40s" finds "Twill-2/1 · 40s x 40s")
  function groupMatches(g, q) {
    const t = (g.code + " " + g.name).toLowerCase();
    return String(q || "").toLowerCase().split(/\s+/).filter(Boolean).every(w => t.includes(w));
  }
  // END GROUP SEARCH
  const rangeWords = r => r.enough ? `Rs ${n2(r.lower)} to ${n2(r.upper)}` : "Too few purchases";
  const rangeSub = (r, min) => r.enough ? `${pc(r.lo)} to ${pc(r.hi)} round the median` + ((r.lo !== r.p25 || r.hi !== r.p75) ? `; its middle half (${pc(r.p25)} to ${pc(r.p75)}) kept within 5% to 10%` : ": the middle half of its prices")
    : `${r.orders || 0} separate ${r.orders === 1 ? "order" : "orders"}; a usual range needs at least ${min}`;
  // ZLOI order lines: kept, in no figure, listed apart (GP, 27 Nov 2026)
  const ZLOI_WORDS = "ZLOI order lines are left out of every figure on this page (price paid, metres, medians, ranges, should-cost): GP's decision of 27 Nov 2026.";
  // prices held apart to check in SAP (more than ten times, or under a tenth of, the code's other purchases): counted
  // nowhere until an admin counts them (the build lead's guard, 28 Nov 2026)
  function toCheck(list, whose, withCode, after) {
    if (!list || !list.length) return null;
    const count = async (x, yes) => {
      try { await api("/api/purchases/price-check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ line_id: x.id, count: yes }) });
        toast(yes ? `Counted: ${x.po}/${x.item} at Rs ${n2(x.price)}` : `Held apart again: ${x.po}/${x.item}`); if (after) after(); }
      catch (e) { toast(e.message, false); }
    };
    const act = x => may("do:upload_purchases") ? h("button", { type: "button", class: "btn line", onclick: () => count(x, !x.counted_by) }, x.counted_by ? "Hold apart again" : "Count it") : "";
    const heads = (withCode ? ["Date", "Order", "Fabric code", "Mill"] : ["Date", "Order", "Mill"]).concat(["Metres", "Price Rs/m", "Why", ""]);
    const cells = x => (withCode ? [day(x.date), `${x.po}/${x.item}`, codeLink(x.code), x.mill] : [day(x.date), `${x.po}/${x.item}`, x.mill])
      .concat([n0(x.metres), n2(x.price), wide(x.counted_by ? `counted by ${x.counted_by} (${x.why})` : x.why), act(x)]);
    return h("div", { class: "outl" }, h("h3", {}, `Prices to check in SAP: ${list.length} ${list.length === 1 ? "line" : "lines"} of ${whose}`),
      h("p", { class: "muted" }, "A price more than ten times, or under a tenth of, the code's other purchases is held apart: it is in no figure (price paid, metres, ranges) until an admin, having checked it in SAP, counts it."),
      table(heads, list.map(cells), withCode ? [4, 5] : [3, 4]));
  }
  function outliers(list, whose, withCode) {
    if (!list || !list.length) return null;
    const heads = withCode ? ["Date", "Order", "Fabric code", "Mill", "Metres", "Price Rs/m"] : ["Date", "Order", "Mill", "Metres", "Price Rs/m"];
    const cells = o => withCode ? [day(o.date), `${o.po}/${o.item}`, codeLink(o.code), o.mill, n0(o.metres), n2(o.price)] : [day(o.date), `${o.po}/${o.item}`, o.mill, n0(o.metres), n2(o.price)];
    return h("div", { class: "outl" }, h("h3", {}, `Outliers (ZLOI): ${list.length} ${list.length === 1 ? "line" : "lines"} of ${whose}`),
      h("p", { class: "muted" }, ZLOI_WORDS), table(heads, list.map(cells), withCode ? [4, 5] : [3, 4]));
  }

  // ---------------------------------------------------------------- the price popup: one fabric code
  async function openHistory(code) {
    closePopups();
    const body = h("div", { class: "pbody" }, h("div", { class: "empty" }, "Loading…"));
    const d = h("div", { class: "dialog pdialog rp-purch", role: "dialog", "aria-modal": "true", "aria-label": "Price over time: " + code },
      h("div", { class: "phead" }, h("h2", {}, "Price over time: " + code), ib("x", "Close", () => s.remove())), body);
    const s = h("div", { class: "scrim pdlg", onmousedown: e => { if (e.target === s) s.remove(); } }, d);
    $("#layer").append(s);
    d.querySelector("button").focus();
    let x;
    try { x = await api("/api/purchases/history?code=" + encodeURIComponent(code)); }
    catch (e) { fill(body, h("p", { class: needsDb(e.message) ? "muted" : "err" }, e.message)); return; }
    const g = x.group, sp = x.spec;
    const num = v => v === "" || isNaN(Number(v)) ? v : String(Number(v));
    const specLine = sp ? "PLM: " + [sp.blend_name, sp.dyemethod_name, sp.weavetype_name, `${sp.warpcount} x ${sp.weftcount}`, sp.epi || sp.ppi ? `${sp.epi ? num(sp.epi) : "blank"} x ${sp.ppi ? num(sp.ppi) : "blank"}` : "EPI and PPI blank", sp.finishedwidth ? `${num(sp.finishedwidth)} ${sp.finishedwidth_uom}` : "width blank", String(sp.finish_name || "").replace(/^F\s*-\s*/, "")].filter(Boolean).join(" · ") : "No PLM specification for this code";
    const pts = x.lines.map(l => ({ date: l.date, price: l.price, metres: l.metres, series: "this", text: `${l.mill}, order ${l.po}/${l.item}` }));
    if (g) for (const l of g.lines) if (l.code !== x.code) pts.push({ date: l.date, price: l.price, metres: l.metres, series: "group", text: `${l.code}, ${l.mill}` });
    const series = [{ key: "this", name: `This code, ${x.code}`, cls: "s1", big: true }, { key: "group", name: g ? `Other codes of ${g.code} (the same construction, any colour)` : "", cls: "s0" }];
    const marks = [x.should ? { y: x.should, label: "Should-cost", cls: "should" } : null, g && g.range.enough ? { y: g.range.median, label: `${g.code} median`, cls: "median" } : null].filter(Boolean);
    const others = g ? g.lines.filter(l => l.code !== x.code).length : 0;
    fill(body,
      h("p", { class: "muted" }, specLine),
      h("div", { class: "stiles" },
        tile("Bought", `${n0(x.lines.length)} ${x.lines.length === 1 ? "purchase" : "purchases"}`, `${n0(x.metres)} m on ${x.orders} ${x.orders === 1 ? "order" : "orders"}`),
        tile("Price paid", x.lines.length ? (x.lines.length > 1 ? priceSpan(Math.min(...x.lines.map(l => l.price)), Math.max(...x.lines.map(l => l.price))) : `Rs ${n2(x.lines[0].price)}`) : "None", x.lines.length ? `last on ${day(x.lines[x.lines.length - 1].date)}` : ""),
        tile("Should-cost", x.should ? `Rs ${n2(x.should)}` : "Not costed", x.should ? (x.should_on || "on today's rates") : x.should_why),
        g ? tile(`Fab group ${g.code}`, g.range.enough ? rangeWords(g.range) : `${g.purchases} ${g.purchases === 1 ? "purchase" : "purchases"}`, g.range.enough ? `its usual range; median Rs ${n2(g.range.median)} on ${g.purchases} purchases, ${g.range.orders} orders` : `on ${g.range.orders || 0} separate ${g.range.orders === 1 ? "order" : "orders"}: too few for a usual range (needs ${g.min_for_range})`) : tile("Fab group", "Not grouped", x.not_grouped)),
      pts.length ? priceChart({ points: pts, series, marks, band: g && g.range.enough ? { lower: g.range.lower, upper: g.range.upper, label: `${g.code} usual range` } : null, label: `Price over time for ${x.code}` }) : null,
      g ? h("p", { class: "muted" }, others ? `Grey dots: the ${others} other ${others === 1 ? "purchase" : "purchases"} of ${g.codes - 1} other ${g.codes - 1 === 1 ? "code" : "codes"} in Fab group ${g.code}, ${g.name}. Most codes are ordered once, so the group shows the history.`
        : `No other code of Fab group ${g.code} has been bought yet.`) : h("p", { class: "muted" }, `Not in a Fab group: ${x.not_grouped}. Nothing is guessed, so there is no group history to show.`),
      (x.moved || []).map(m => h("p", { class: "note" }, m.from && m.from === m.to ? `On ${day(m.at)}: ${m.why}.` : `Moved ${m.from ? "from " + m.from + " " : ""}on ${day(m.at)}: ${m.why}.`)),
      h("h3", {}, "Purchases of this code"),
      x.lines.length ? table(["Date", "Order", "Mill", "Metres", "Price Rs/m", "Against should-cost"], x.lines.map(l => [day(l.date), `${l.po}/${l.item}`, l.mill, n0(l.metres), n2(l.price), x.should ? pc((l.price / x.should - 1) * 100) : ""]), [3, 4, 5])
        : h("p", { class: "muted" }, x.outliers.length ? "None but ZLOI orders, which are listed apart below: no price paid is shown." : "None."),
      outliers(x.outliers, "this code"),
      toCheck(x.to_check, "this code", false, () => { s.remove(); openHistory(code); }),
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
    page.group = { code, data: null, error: null };
    try { page.group.data = await api("/api/groups/" + encodeURIComponent(code)); } catch (e) { page.group.error = e.message; }
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
    const r = d.range, sh = d.should, series = millSeries(d.mills), shown = new Set(series.map(x => x.key));
    const pts = d.lines.map(l => ({ date: l.date, price: l.price, metres: l.metres, series: shown.has(l.mill_key) ? l.mill_key : "*", text: `${l.mill}, ${l.code}` }));
    const marks = [sh.median ? { y: sh.median, label: "Should-cost", cls: "should" } : null, r.enough ? { y: r.median, label: "Median paid", cls: "median" } : null].filter(Boolean);
    const vsShould = sh.median && r.median ? (r.median / sh.median - 1) * 100 : null;
    const inList = (state.rows || []).filter(x => x.fab_group === d.code).length;
    fillP(main, top,
      h("div", { class: "dhead" }, h("div", {}, h("div", { class: "small" }, `Fab group · ${n0(d.fabrics.length)} fabric ${d.fabrics.length === 1 ? "code" : "codes"} · the same construction in any colour` + (d.first ? ` · bought ${day(d.first)} to ${day(d.last)}` : "")),
        h("h1", {}, d.code), h("div", { class: "gname" }, d.name)),
        h("div", { class: "dicons noprint" }, ib("pdf", "Print this page", () => print()),
          inList ? ib("pin", `Show its ${inList} purchase-order ${inList === 1 ? "costing" : "costings"} in Right cost`, () => { state.filters = { fab_group: [d.code] }; state.cls = "Purchase orders"; state.saved = "Default"; state.tab = "items"; location.hash = "#rightcost"; }) : null)),
      d.asked ? h("p", { class: "note" }, `${d.asked.code} (${d.asked.name}) was merged into this group` + (d.asked.merged_at ? ` on ${day(d.asked.merged_at)}` : "") + (d.asked.merged_by ? ` by ${d.asked.merged_by}` : "") + `. Its code stays ${d.asked.code} and is never given to another group.`) : null,
      h("div", { class: "stiles" },
        tile("Purchases", `${n0(d.purchases)}`, `${n0(d.orders)} ${d.orders === 1 ? "order" : "orders"}, ${n0(d.metres)} m` + (d.outliers.length ? `; ${d.outliers.length} ZLOI ${d.outliers.length === 1 ? "line" : "lines"} left out` : "")),
        (() => { const bought = d.mills.filter(m => m.lines), only = d.mills.length - bought.length;
          return tile("Mills", `${bought.length}`, [bought.slice(0, 3).map(m => m.name).join(", ") + (bought.length > 3 ? ` and ${bought.length - 3} more` : ""),
            only ? `${bought.length ? only + " more" : only} with ZLOI lines only, not counted` : ""].filter(Boolean).join(" · ")); })(),
        tile("Median price paid", r.median ? `Rs ${n2(r.median)}` : "None", r.median ? "paid " + priceSpan(r.low, r.high) : ""),
        tile("Usual range", rangeWords(r), rangeSub(r, d.min_for_range), r.enough ? "" : "amber"),
        tile("Should-cost", sh.median ? `Rs ${n2(sh.median)}` : "Not costed", sh.median ? (sh.low !== sh.high ? `Rs ${n2(sh.low)} to ${n2(sh.high)} across its codes (order size, pattern); ` : "") + (sh.dated && sh.dated.length ? `on the order months' yarn rates (some dated)` : `on today's rates`) + (vsShould !== null ? `; the median paid is ${pc(vsShould)} against it` : "") : (sh.why_not[0] || "")),
        tile("Priced well above the group", r.enough ? `${d.above.length} ${d.above.length === 1 ? "purchase" : "purchases"}` : "No range yet", r.enough ? (d.above.length ? `Rs ${n0(d.above_rs)} above the top of the usual range` : "none above the top of its usual range") : "too few orders to say", d.above.length ? "red" : "")),
      h("section", { class: "sec" }, h("h2", {}, "Price over time, by mill"),
        d.lines.length ? priceChart({ points: pts, series, marks, band: r.enough ? { lower: r.lower, upper: r.upper, label: "Usual range" } : null, label: `Prices paid for ${d.code} by date and mill`, height: 300 }) : h("p", { class: "muted" }, "No purchase on record."),
        h("p", { class: "muted" }, "One dot per purchase (lines of one order at one price share a dot). Point at a dot for its date, price, metres, mill and code." + (r.enough ? " The band is the group's usual range." : ""))),
      h("section", { class: "sec" }, h("h2", {}, "By mill"),
        table(["Mill", "Purchases", "Orders", "Metres", "Share of metres", "Median Rs/m", "Lowest", "Highest", "Median against the group", "Last bought", "Outliers (ZLOI)"],
          d.mills.map(m => [millLink(m.name, m.key), n0(m.lines), n0(m.orders), n0(m.metres), m.share === null ? "" : Math.round(m.share * 100) + "%", m.median === null ? "" : n2(m.median), m.low === null ? "" : n2(m.low), m.high === null ? "" : n2(m.high),
            m.vs_group === null ? "" : pc(m.vs_group), day(m.last), m.outliers.length ? wide(h("span", {}, `${m.outliers.length}: ` + m.outliers.map(o => `${day(o.date)} ${n0(o.metres)} m at Rs ${n2(o.price)}`).join("; "))) : ""]), [1, 2, 3, 4, 5, 6, 7, 8]),
        outliers(d.outliers, "this group", true)),
      h("section", { class: "sec" }, h("h2", {}, "Priced well above the group"),
        !r.enough ? h("p", { class: "muted" }, `${r.n} ${r.n === 1 ? "purchase" : "purchases"} on ${r.orders || 0} separate ${r.orders === 1 ? "order" : "orders"} so far: too few for a usual range (it needs purchases on at least ${d.min_for_range} orders, ZLOI left out), so no purchase is called high. Load more purchase files as they come.`)
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
      h("p", { class: "muted", style: "margin-top:18px" }, `"Priced well above the group" uses the negotiation brief's own rule: the usual range is the middle half of the group's past prices, kept between 5% and 10% either side of its median, and it needs purchases on at least ${d.min_for_range} separate orders. ${ZLOI_WORDS} Should-cost is as Right cost has it: each code for the metres bought, on the yarn rates of its order month (today's where none is dated) and today's other rates.`));
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
    const rows = d.groups.filter(g => groupMatches(g, q)).sort((a, b) => b.purchases - a.purchases || a.code.localeCompare(b.code));
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
      h("p", { class: "muted" }, `${n0(c.groups)} ${c.groups === 1 ? "group" : "groups"} of ${n0(c.fabrics_grouped)} fabric codes (the same construction in any colour, across mills), from ${n0(c.lines)} purchase lines` + (c.first ? `, ${day(c.first)} to ${day(c.last)}` : "") + `. ${n0(c.fabrics - c.fabrics_grouped)} codes are not grouped` + (d.not_grouped.length ? ` (${d.not_grouped.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")})` : "") + ".",
        " ", may("page:purchase_files") ? h("a", { href: "#purchase-files" }, "Purchase files") : null),
      h("div", { class: "toolbar" }, search, h("button", { type: "button", class: "btn line", onclick: () => { list.q = search.value; list.shown = 100; render(); } }, "Search"), h("span", { class: "count" }, `${n0(rows.length)} ${rows.length === 1 ? "group" : "groups"}`)),
      rows.length ? table(["Fab group", "Construction", "Codes", "Purchases", "Metres", "Median Rs/m", "Last bought"],
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
    files.max = d.max_bytes;
    const [input, fileNote] = fileBox(files, h, tooBig);       // kept across redraws: a chosen file is never lost
    const send = async () => {
      if (!input.files.length) return toast("Choose the purchase-order file first", false);
      files.serverError = null; sayFile(files, tooBig);
      if (files.uploadError) return;
      const fd = new FormData(); fd.append("file", input.files[0]);
      try { const r = await api("/api/purchases/upload", { method: "POST", body: fd }); files.open = r.id; files.detail = null; input.value = ""; sayFile(files, tooBig); toast(r.shipped_first ? "Uploaded: the purchase file that came with the code is read first, then this one, in the background" : "Uploaded: it is read in the background"); enterFiles(); }
      catch (e) { files.serverError = e.message; sayFile(files, tooBig); }
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
        u.rows_skipped !== null ? `${n0(u.rows_skipped)} left out` : null].filter(Boolean).join(" · ") : "";
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
        fileNote,
        d.shipped.available ? [h("h3", {}, "Or load the file that came with the code" + (d.shipped.loaded ? " (loaded already)" : "")),
          h("p", { class: "muted" }, "inputs/Fabric _ 3Months_4746.xlsx: the purchase orders of 1 Aug to 23 Nov 2026 that the pilot was run on, as SAP exported them on 23 Nov 2026. Each order line is kept once, and it never undoes a newer file, nor one covering the same orders saved later."),
          h("button", { type: "button", class: "btn line", onclick: shipped }, "Load the purchase file that came with the code")] : null),
      h("section", { class: "sec" }, h("h2", {}, "Uploads"), c.disagreements ? h("p", { class: "note" }, `${n0(c.disagreements)} ${c.disagreements === 1 ? "disagreement" : "disagreements"} between a file and the history ${c.disagreements === 1 ? "is" : "are"} open, for an admin: the uploads with them are listed below, however old.`) : null,
        d.uploads.length ? h("div", { class: "gridscroll sup pgt" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Upload", "File", "Where it stands", "What was read"].map(t => h("th", {}, t)))), h("tbody", {}, d.uploads.map(row))))
          : h("p", { class: "muted" }, "No file uploaded yet."),
        det ? skippedView(det) : null),
      h("p", { class: "muted", style: "margin-top:14px" }, "Kept from each file, as the pilot keeps it: bulk orders (BO, ZLOI, BF), priced, in rupees, per metre, not deleted or blocked in SAP; ZLOI lines are kept apart and left out of every figure. The newest file wins. Which is newer is read first from what a file covers: a file was taken no earlier than its latest document date (or the report date it carries in a column of its own) and no later than it was saved; one file taken after the other for certain is newer, and that decides. Where what they cover cannot tell (a correction of the same orders, the same file saved again), the file saved later wins, exactly as a newer file does (GP's decision, 28 Nov 2026). A saved date after the upload (a clock set wrong) is not used: such a file, or one with no saved date, is taken by its upload at the latest and never wins by a saved date. A row dated after the file was saved (a forward-dated order, or a typo) is left out, listed with why, so the file keeps its saved date; a report date counts only between its latest order and its saved date. Document dates are days in India; saved times are UTC. The upload's page says which file won and why, with both saved times, and every date it did not use. Every order line keeps the word of the newest file that covered it: its figures, or that it was deleted, blocked, no longer bulk, not in rupees or not per metre; an older or earlier-saved file never changes it or brings it back. A line simply not in a newer file is never taken as cancelled: the history keeps it (GP, 28 Nov 2026), so a later download covering a longer span takes each line once. Only where nothing can tell (saved at the very same moment, or either file without a saved date it can be dated by) and a file disagrees with the history, the history stands and the upload lists the disagreement, for an admin to keep or to take the file's figures. A date written as text is read as year-month-day (2026-04-03 is 3 April); one that could be read two ways is left out with why. Fabric codes are matched to their PLM specification and Fab group; a code whose specification is missing or incomplete is not grouped. The PLM specifications are the extract deployed with the code (data/plm_specs_for_po.csv in the code's own folder, not the data folder): a corrected extract goes in with a code change, and is read at the next upload."));
  }
  // FILE BOX: the file box and the words under it are made once and kept across the page's redraws (it redraws every two
  // seconds while a file is read, and redrew on choosing a file: the chosen file was lost, the cold review of 28 Nov), so a
  // chosen file stays chosen; a file too large is said at once, in place, before anything is sent. check_server.py drives
  // these two functions under node.
  function fileBox(files, h, tooBig) {
    if (!files.input) {
      files.input = h("input", { type: "file", accept: ".xlsx,.xlsm", "aria-label": "Purchase-order file" });
      files.note = h("p", { class: "muted" });
      files.input.addEventListener("change", () => { files.serverError = null; sayFile(files, tooBig); });
    }
    sayFile(files, tooBig);
    return [files.input, files.note];
  }
  function sayFile(files, tooBig) {
    const f = files.input.files && files.input.files[0];
    files.uploadError = files.serverError || (f ? tooBig(f.size, files.max, f.name) : null);
    files.note.className = files.uploadError ? "err" : "muted";
    if (files.uploadError) files.note.setAttribute("role", "alert"); else files.note.removeAttribute("role");
    files.note.textContent = files.uploadError || `Up to ${Math.floor(files.max / 1048576)} MB a file: a longer period goes in as several files, by 6 months or by year.`;
  }
  // END FILE BOX
  // TOO BIG: what a file over the limit is told on the screen at once, before it is sent (as rules/purchases.py too_big;
  // check_server.py runs this function and compares the two)
  function tooBig(size, max, name) {
    return size > max ? `${name} is ${(size / 1048576).toFixed(1).replace(/\.0$/, "")} MB: larger than ${Math.floor(max / 1048576)} MB, the most read at once. Split it in SAP by 6 months or by year, and upload each part.` : null;
  }
  // END TOO BIG
  // what the saved date decided (GP, 28 Nov 2026): where what two files cover cannot tell which is newer, the file saved
  // later wins; the upload's page says which won and why, with both saved times
  const utc = t => `${t.slice(0, 16).replace("T", " ")} UTC`;
  const savedWhen = x => (x.report_used ? `taken on ${x.report_used.slice(0, 10)} (the report date it carries), ` : "") +
    (x.covers_saved ? `saved ${utc(x.covers_saved)}` : "with no saved date it can be dated by");
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
      h("p", { class: "muted" }, "Which of the two is newer could not be told: not from what they cover (their latest document dates, a report date), and not from when they were saved, because they were saved at the very same moment, or one of them has no saved date it can be dated by (none, or one after it was uploaded). So nothing was guessed: the history's figures were kept." +
        (u.disagree_open ? " An admin can keep them, or take this file's." : u.disagreements.some(x => x.settled_as === "file") ? " Settled: this file's figures were taken." : " Settled: the history's figures were kept.")),
      u.disagree_open && may("do:upload_purchases") ? h("div", { class: "acts" }, h("button", { type: "button", class: "btn line", onclick: () => settle("kept") }, "Keep the history's figures"), h("button", { type: "button", class: "btn fill", onclick: () => settle("file") }, "Take this file's figures")) : null,
      table(["Order", "Item", "Kept (from)", "This file says", "Settled"], u.disagreements.map(x => [x.po, x.item, wide(side(x.kept) + (x.kept.file ? ` [${x.kept.file}]` : "")), wide(side(x.file)), x.settled_at ? `${day(x.settled_at)}${x.settled_by ? " by " + x.settled_by : ""}: ${x.settled_as === "file" ? "this file's taken" : "the history's kept"}` : "open"]), []),
      u.disagree_count > u.disagreements.length ? h("p", { class: "muted" }, `The first ${u.disagreements.length} are shown; settling covers all ${n0(u.disagree_count)}.`) : null];
  }
  function skippedView(u) {
    const s = u.summary || {};
    const fut = (u.skipped || []).filter(x => x.kind === "Dated after the file was saved"), notes = s.dating_notes || [], ch = s.changed_lines || [];
    const brief = x => x.removed ? `not counted: ${x.removed}` : `${day(x.date)} · ${x.type} · ${n0(x.metres)} m at Rs ${n2(x.price)}`;
    const noSpec = (s.not_grouped || []).filter(([k]) => /PLM specification/.test(k)).reduce((a, [, n]) => a + n, 0);
    return h("div", { class: "updetail" }, h("h3", {}, `Upload #${u.id}: ${u.filename}`), savedView(u), disagreeView(u),
      u.status === "done" ? h("p", {}, `Already in the history: ${n0(u.rows_same || 0)} order lines, the same in this file (one line each, counted once). Updated by this file: ${n0((u.rows_changed || 0) + (u.rows_removed || 0))}` +
        ((u.rows_changed || 0) + (u.rows_removed || 0) ? ` (${n0(u.rows_changed || 0)} with its newer figures, ${n0(u.rows_removed || 0)} it shows no longer bought)` : "") + ". New: " + n0(u.rows_new || 0) + ".") : null,
      (s.price_checks || []).length ? h("p", { class: "note" }, `${n0(s.price_checks.length)} ${s.price_checks.length === 1 ? "price is" : "prices are"} held apart to check in SAP (counted nowhere until an admin counts ${s.price_checks.length === 1 ? "it" : "them"}, in the price popup of the code): ` +
        s.price_checks.slice(0, 5).map(x => `${x.code} ${x.po}/${x.item} at Rs ${n2(x.price)} (the others' median Rs ${n2(x.reference)})`).join("; ") + (s.price_checks.length > 5 ? `; and ${n0(s.price_checks.length - 5)} more` : "") + ".") : null,
      s.read_again_own ? h("p", { class: "note" }, `Read again from the start after the server restarted: ${n0(s.read_again_own)} of the lines counted as already in had been written by this file's own first reading, before the restart.`) : null,
      ch.length ? table(["Order", "Item", "Was", "Now (this file)"], ch.map(x => [x.po, x.item, wide(brief(x.was)), wide(brief(x.now))]), []) : null,
      ch.length && ch.length < (u.rows_changed || 0) + (u.rows_removed || 0) ? h("p", { class: "muted" }, `The first ${ch.length} are shown.`) : null,
      noSpec ? h("p", { class: "note" }, `${n0(noSpec)} ${noSpec === 1 ? "code has" : "codes have"} no PLM specification, or an incomplete one: ${noSpec === 1 ? "its lines are" : "their lines are"} loaded and counted in ${noSpec === 1 ? "its" : "their"} prices like any other, with the construction blank (not in a Fab group, no should-cost).`) : null,
      notes.filter(t => !/left out \(check them in SAP\)/.test(t)).length ? h("p", { class: "note" }, "Dates not used to put this file in order: " + notes.filter(t => !/left out \(check them in SAP\)/.test(t)).join("; ") + ".") : null,
      s.future_count ? h("p", { class: "note" }, `${n0(s.future_count)} ${s.future_count === 1 ? "row is" : "rows are"} dated after the file was saved (a forward-dated order, or a typo), so ${s.future_count === 1 ? "it is" : "they are"} left out and the file keeps its saved date: check ${s.future_count === 1 ? "it" : "them"} in SAP. ` +
        (fut.length ? fut.slice(0, 5).map(x => `row ${x.row} (order ${x.po}/${x.item}): ${x.why}`).join("; ") + (s.future_count > 5 ? `; and ${n0(s.future_count - 5)} more (in the rows left out below)` : "") : "")) : null,
      u.status === "done" ? h("p", {}, `Order lines dated ${day(s.first)} to ${day(s.last)}, from ${n0(s.mills)} ${s.mills === 1 ? "spelling of a mill" : "mill spellings"}, for ${n0(s.fabrics)} fabric codes: ${n0(s.grouped)} in Fab groups, ${n0(s.costed)} costed.` +
        (s.not_grouped && s.not_grouped.length ? ` Not grouped: ${s.not_grouped.map(([k, n]) => `${k}: ${n0(n)}`).join("; ")}.` : "")) : null,
      u.skipped_count ? [h("p", {}, `Left out: ${n0(u.skipped_count)} rows. ` + (s.skipped_by_kind || []).map(([k, n]) => `${k}: ${n0(n)}`).join("; ") + ".",
        " ", h("a", { href: `/api/purchases/skipped/${u.id}`, download: "" }, "Download every row left out (Excel)")),
      table(["Row", "Order", "Item", "Material", "Why it was left out"], u.skipped.slice(0, files.rows).map(x => [String(x.row), x.po, x.item, x.material, wide(x.why)]), [0]),
      u.skipped.length > files.rows ? h("p", {}, h("button", { type: "button", class: "btn line", onclick: () => { files.rows = u.skipped.length; render(); } }, `Show the first ${u.skipped.length}`)) : null,
      u.skipped_count > Math.min(files.rows, u.skipped.length) ? h("p", { class: "muted" }, `The first ${Math.min(files.rows, u.skipped.length)} are shown; the download has ${u.skipped_listed < u.skipped_count ? "the first " + n0(u.skipped_listed) + " (the counts above cover all " + n0(u.skipped_count) + ")" : "all " + n0(u.skipped_count)}.`) : null] : (u.status === "done" ? h("p", { class: "muted" }, "No row was left out.") : null));
  }

  // ---------------------------------------------------------------- what the shell sees
  window.RP_PAGES = {
    group: { enter: enterGroup, render: renderGroup, title: p => p.arg || "Fab group", rail: "costs" },
    groups: { enter: () => enterGroups(true), render: renderGroups, title: () => "Fab groups", rail: "costs" },
    "purchase-files": { enter: enterFiles, render: renderFiles, title: () => "Purchase files", rail: null },
  };
  window.RP_PURCH = {
    openHistory, outliers, toCheck,
    // Right cost's Fab group cell: the group (to its page) and the price popup
    cell(r) {
      if (r.source !== "Purchase orders" || (r.fab_group === undefined && r.fab_group_name === undefined) || (r.fab_group === null && !r.fab_group_name)) return "";
      const chart = tipOn(h("button", { type: "button", class: "ib pib", onclick: e => { e.stopPropagation(); openHistory(r.code); }, html: svg("chart") }), "Price over time for " + r.code);
      return h("span", { class: "fgcell" }, r.fab_group ? tipOn(may("page:groups") ? h("button", { type: "button", class: "code", onclick: () => { location.hash = "#group/" + encodeURIComponent(r.fab_group); } }, r.fab_group) : h("span", {}, r.fab_group), r.fab_group_name || "")
        : tipOn(h("span", { class: "muted" }, "Not grouped"), r.fab_group_name || "Not grouped"), chart);
    },
  };
})();
