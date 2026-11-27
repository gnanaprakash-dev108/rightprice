/* RightPrice: dated yarn rates (stage 5) on the Yarn prices page, and "Add as dated yarn rates" on Bring in prices.
   Self-contained (its own small helpers), so it can sit on any page of the app: RPDated.card() returns the card,
   RPDated.fromIntake(rows, source, box) the step that gives each reviewed row a yarn of the yarn master.
   Every figure comes from the server (rules/dated.py); nothing is worked out here but the drawing. */
"use strict";
window.RPDated = (() => {
  const el = (tag, attrs, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v; else if (k === "html") e.innerHTML = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) e.append(kid);
    return e;
  };
  const call = async (path, body) => {
    const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let d = null; try { d = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) throw new Error((d && d.detail) || r.statusText);
    return d;
  };
  const money = (v, d = 0) => v === null || v === undefined ? "" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: 2 });
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const label = m => `${MON[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const SOURCE = { typed: "Typed here", "brought in": "Brought in", "market history": "Market history" };
  const say = (box, text, kind) => box.replaceChildren(text ? el("div", { class: "notice" + (kind ? " " + kind : ""), role: kind === "err" ? "alert" : "status" }, text) : "");

  // the one tooltip: the page's own (#tip) where it has one
  const tipEl = () => document.getElementById("tip") || document.body.appendChild(el("div", { id: "tip", class: "tip", role: "tooltip", hidden: true }));
  const tip = (html, x, y) => { const t = tipEl(); t.innerHTML = html; t.hidden = false; const r = t.getBoundingClientRect(); t.style.left = Math.max(8, Math.min(x + 14, innerWidth - r.width - 8)) + "px"; t.style.top = Math.max(8, Math.min(y + 14, innerHeight - r.height - 8)) + "px"; };
  const untip = () => { const t = document.getElementById("tip"); if (t) t.hidden = true; };

  /* One yarn's dated rates by month. Months without a rate are left as gaps: no line crosses them, and a grey mark on the
     baseline shows each one (today's rate is used there). The thin level line is today's rate, for comparison. */
  function yarnChart(s, months) {
    const W = 360, H = 170, m = { l: 50, r: 70, t: 14, b: 30 };
    const pts = s.points.map((p, i) => p ? { i, ...p } : null), have = pts.filter(Boolean);
    const vals = have.map(p => p.rate).concat(s.today !== null ? [s.today] : []);
    let lo = Math.min(...vals), hi = Math.max(...vals); const pad = Math.max((hi - lo) * 0.15, hi * 0.03, 5); lo -= pad; hi += pad;
    const step = (() => { const raw = (hi - lo) / 3, p = 10 ** Math.floor(Math.log10(raw)); return [1, 2, 2.5, 5, 10].map(k => k * p).find(k => k >= raw) || raw; })();
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    const n = months.length, bw = (W - m.l - m.r) / n, X = i => m.l + (i + 0.5) * bw, Y = v => m.t + (1 - (v - lo) / ((hi - lo) || 1)) * (H - m.t - m.b);
    let g = "";
    for (let v = lo; v <= hi + 1e-9; v += step) g += `<line class="dr-grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="dr-axis" x="${m.l - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${money(v)}</text>`;
    const gw = Math.min(Math.max(bw - 4, 1), 22);         // a gap month: a short grey mark on the baseline, no line across it
    pts.forEach((p, i) => { if (!p) g += `<rect class="dr-gap" x="${(X(i) - gw / 2).toFixed(1)}" y="${H - m.b - 4}" width="${gw.toFixed(1)}" height="3" rx="1.5"/>`; });
    const every = Math.max(1, Math.ceil(n / 6));
    months.forEach((mo, i) => { if (i % every === 0 || i === n - 1) g += `<text class="dr-axis" x="${X(i).toFixed(1)}" y="${H - 10}" text-anchor="middle">${MON[Number(mo.slice(5, 7)) - 1]}${i === 0 || mo.endsWith("-01") ? " " + mo.slice(2, 4) : ""}</text>`; });
    if (s.today !== null) g += `<line class="dr-today" x1="${m.l}" x2="${W - m.r}" y1="${Y(s.today).toFixed(1)}" y2="${Y(s.today).toFixed(1)}"/><text class="dr-axis" x="${W - m.r + 6}" y="${(Y(s.today) + 4).toFixed(1)}">today ${money(s.today)}</text>`;
    let path = "";            // a line only between neighbouring months that both have a rate: a gap stays a gap
    pts.forEach((p, i) => { if (p) path += (i && pts[i - 1] ? "L" : "M") + X(i).toFixed(1) + " " + Y(p.rate).toFixed(1); });
    g += `<path class="dr-line" d="${path}"/>`;
    have.forEach(p => { g += `<circle class="dr-dot" cx="${X(p.i).toFixed(1)}" cy="${Y(p.rate).toFixed(1)}" r="4.5"/>`; });
    const last = have[have.length - 1];
    if (last) g += `<text class="dr-val" x="${X(last.i).toFixed(1)}" y="${(Y(last.rate) - 9).toFixed(1)}" text-anchor="middle">${money(last.rate)}</text>`;
    months.forEach((mo, i) => { g += `<rect class="dr-hit" data-i="${i}" x="${(m.l + i * bw).toFixed(1)}" y="${m.t}" width="${bw.toFixed(1)}" height="${H - m.t - m.b}"/>`; });
    const gaps = pts.filter(p => !p).length;
    const svgText = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.key)}: dated rates in ${have.length} of ${n} months, ${have.map(p => label(p.month) + " Rs " + money(p.rate)).join(", ")}; today's rate Rs ${money(s.today)}.">${g}</svg>`;
    const box = el("div", { class: "dr-chart", html: svgText });
    box.querySelectorAll(".dr-hit").forEach(r => {
      const i = Number(r.dataset.i), p = pts[i];
      const html = () => `<b>${label(months[i])}</b><br>` + (p ? `Rs ${money(p.rate, 2)} a kilo` + (p.low !== null && p.high !== null && p.low !== p.high ? ` (Rs ${money(p.low)} to ${money(p.high)})` : "") + `<br>${esc(SOURCE[p.source] || p.source)}`
        : `No dated rate: today's rate (Rs ${money(s.today)}) is used`) + (p && s.today !== null ? `<br>Today: Rs ${money(s.today)}` : "");
      r.addEventListener("mousemove", e => tip(html(), e.clientX, e.clientY)); r.addEventListener("mouseleave", untip);
    });
    return el("figure", { class: "dr-fig" }, el("figcaption", {}, el("b", {}, s.key), el("span", {}, ` ${have.length} of ${n} months` + (gaps ? `, ${gaps} without` : "") + (s.in_master ? "" : " · no longer in the yarn master"))), box);
  }

  function table(columns, rows, opts = {}) {
    return el("div", { class: "table-wrap dr-table", tabindex: "0", role: "region", "aria-label": opts.label || "Table" },
      el("table", {}, el("thead", {}, el("tr", {}, columns.map(c => el("th", { scope: "col", class: c.n ? "n" : null }, c.t)))),
        el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: String(columns.length), class: "dr-empty" }, opts.empty || "None")))));
  }

  /* The card on the Yarn prices page. */
  function card() {
    const host = el("div", { class: "card dr-card" }, el("p", { class: "dr-empty" }, "Loading the dated yarn rates…"));
    const load = async () => {
      let d;
      try { d = await call("/api/dated-rates"); }
      catch (e) { host.replaceChildren(el("div", { class: "card-head" }, el("h2", {}, "Dated yarn rates")), el("div", { class: "notice info" }, e.message)); return; }
      const msg = el("div", { "aria-live": "polite" });
      // purchase orders by order month, and whether their yarns have a dated rate then
      const orders = d.orders.length ? el("div", { class: "dr-orders" }, d.orders.map(o => el("div", { class: "dr-month" },
        el("b", {}, o.label), el("span", { class: "num" }, `${money(o.fabrics)} purchase-order fabrics`),
        el("span", { class: o.both ? "" : "dr-none" }, o.both === o.fabrics ? "dated rates for both yarns" : o.both || o.one ? `${money(o.both)} with dated rates for both yarns, ${money(o.one)} for one` : "no dated yarn rate yet: today's rates")))) : null;
      const charts = d.series.length ? el("div", { class: "dr-multiples" }, d.series.map(s => yarnChart(s, d.months)))
        : el("p", { class: "dr-empty" }, "No dated yarn rates yet. Type one below, bring prices in (Bring in prices, then Add as dated yarn rates), or load the market history in hand.");
      // the form: one yarn, one month, a rate (or a low and a high, counted as their midpoint)
      const yarn = el("select", { id: "dr-yarn" }, el("option", { value: "" }, "Choose a yarn"), d.yarns.map(y => el("option", { value: y.key }, `${y.key} · today Rs ${money(y.rate)}${String(y.basis).startsWith("Placeholder") ? " · placeholder" : ""}`)));
      const month = el("input", { id: "dr-month", type: "month", min: d.first_month, max: d.this_month, value: d.this_month, required: true });
      const rate = el("input", { id: "dr-rate", type: "number", step: "0.01", min: String(d.limits[0]), max: String(d.limits[1]), inputmode: "decimal", placeholder: "Rs a kilo" });
      const low = el("input", { id: "dr-low", type: "number", step: "0.01", inputmode: "decimal", placeholder: "optional" });
      const high = el("input", { id: "dr-high", type: "number", step: "0.01", inputmode: "decimal", placeholder: "optional" });
      const note = el("input", { id: "dr-note", type: "text", maxlength: "300", placeholder: "Where it is from (a circular, a mill's quote…)" });
      const f = (id, text, input, hint) => el("div", { class: "field" }, el("label", { for: id }, text), input, hint ? el("span", { class: "hint" }, hint) : null);
      const form = el("form", { class: "dr-form", onsubmit: async e => {
        e.preventDefault();
        try {
          const r = await call("/api/dated-rates", { yarn_key: yarn.value, month: month.value, rate: rate.value || null, low: low.value || null, high: high.value || null, note: note.value });
          say(msg, `Saved: ${r.yarn_key}, ${label(r.month)}, Rs ${money(r.rate, 2)} a kilo. Purchase orders of that month are costed on it from now on.`); await load();
        } catch (err) { say(msg, err.message, "err"); }
      } }, el("div", { class: "fields dr-fields" }, f("dr-yarn", "Yarn (of the yarn master)", yarn), f("dr-month", "Month", month), f("dr-rate", "Rate, Rs a kilo", rate, "Or give a low and a high"),
        f("dr-low", "Low", low), f("dr-high", "High", high), f("dr-note", "Note", note)),
        el("div", { class: "row-actions" }, el("button", { class: "btn primary", type: "submit" }, "Save the dated rate")),
        el("p", { class: "dr-small" }, "A rate for a yarn and month that already has one takes its place; the earlier one is kept below, marked replaced. The yarn master (today's rates) is not changed."));
      // the market history in hand
      const market = el("div", { class: "dr-market" });
      const preview = async () => {
        market.replaceChildren(el("p", { class: "dr-empty" }, "Reading the market history…"));
        try {
          const p = await call("/api/dated-rates/market");
          const fresh = p.rates.filter(r => !r.held);
          market.replaceChildren(
            el("p", {}, `${p.file}, sheet ${p.sheet}: ${money(p.rows)} prices. ${money(p.used_rows)} of them are of a yarn that surely is in the yarn master, giving ${p.rates.length} monthly ${p.rates.length === 1 ? "rate" : "rates"}:`),
            table([{ t: "Yarn" }, { t: "Month" }, { t: "Rate", n: true }, { t: "From" }, { t: "" }], p.rates.map(r => el("tr", {}, el("td", {}, r.yarn_key), el("td", {}, r.label), el("td", { class: "n" }, money(r.rate, 2)), el("td", { class: "w" }, r.basis), el("td", {}, r.held ? "a person's rate is kept" : ""))), { label: "Rates the market history gives", empty: "None" }),
            el("p", { class: "dr-small" }, "Left out, and why:"),
            el("ul", { class: "dr-why" }, p.left_out.map(x => el("li", {}, el("b", { class: "num" }, money(x.rows)), " ", x.why))),
            el("div", { class: "row-actions" }, el("button", { class: "btn" + (fresh.length ? " primary" : ""), type: "button", disabled: !p.rates.length, onclick: async () => {
              try { const r = await call("/api/dated-rates/market", {}); say(msg, `Loaded ${r.added} monthly ${r.added === 1 ? "rate" : "rates"} from the market history` + (r.kept ? `; ${r.kept} kept as a person entered them` : "") + "."); await load(); }
              catch (err) { say(msg, err.message, "err"); }
            } }, `Load ${p.rates.length} monthly ${p.rates.length === 1 ? "rate" : "rates"}`)));
        } catch (err) { market.replaceChildren(el("div", { class: "notice err" }, err.message)); }
      };
      const entryRow = (r, removable) => el("tr", {}, el("td", {}, r.yarn_key), el("td", {}, r.label), el("td", { class: "n" }, money(r.rate, 2)),
        el("td", { class: "n" }, r.low !== null && r.high !== null && r.low !== r.high ? `${money(r.low)} to ${money(r.high)}` : ""), el("td", { class: "n" }, String(r.entries)),
        el("td", {}, SOURCE[r.source] || r.source), el("td", { class: "w" }, r.basis), el("td", {}, [r.entered_by || "", r.entered_at ? " " + r.entered_at.slice(0, 10) : ""].join("").trim()),
        el("td", {}, removable ? el("button", { class: "btn small", type: "button", "aria-label": `Remove the rate for ${r.yarn_key}, ${r.label}`, onclick: async () => {
          if (!confirm(`Remove the dated rate for ${r.yarn_key}, ${r.label}? Purchase orders of that month go back to today's rate for it.`)) return;
          try { await call("/api/dated-rates/remove", { id: r.id }); await load(); } catch (err) { say(msg, err.message, "err"); }
        } }, "Remove") : `${r.removed_why || "removed"} ${String(r.removed_at || "").slice(0, 10)}${r.removed_by ? " by " + r.removed_by : ""}`));
      const cols = [{ t: "Yarn" }, { t: "Month" }, { t: "Rs a kilo", n: true }, { t: "Range", n: true }, { t: "Prices", n: true }, { t: "Source" }, { t: "Where from" }, { t: "Entered" }, { t: "" }];
      host.replaceChildren(...[         // never a null into replaceChildren: it would show as the word "null"
        el("div", { class: "card-head" }, el("div", {}, el("h2", {}, "Dated yarn rates: the rates of a month"),
          el("p", { class: "dr-small", style: "margin:2px 0 0" }, "A purchase order is costed on the yarn rates of its order month where there is a dated rate; quotes and Create cost on today's rates (the yarn master above). Every costing says which."))),
        orders, charts, d.series.length ? el("p", { class: "dr-small" }, "Each chart is one yarn, in rupees a kilo, on its own scale. A grey mark on the baseline is a month with no dated rate: there the line stops, and today's rate is used. The level line is today's rate.") : null,
        el("h3", { class: "dr-h" }, "Enter a dated rate"), form, msg,
        el("h3", { class: "dr-h" }, "The market history in hand"),
        d.market_file ? el("div", {}, el("p", { class: "dr-small" }, `Only prices of a yarn that surely is in the yarn master are used. Nothing is loaded until you press Load.`), market.childElementCount ? market : el("button", { class: "btn", type: "button", onclick: e => { e.currentTarget.replaceWith(market); preview(); } }, "See what it holds"))
          : el("p", { class: "dr-empty" }, "The market history file is not on this server."),
        el("h3", { class: "dr-h" }, `In force (${d.entries.length})`),
        table(cols, d.entries.map(r => entryRow(r, true)), { label: "Dated yarn rates in force", empty: "No dated rate yet." }),
        d.history.length ? el("details", { class: "dr-details" }, el("summary", {}, `Replaced or removed (${d.history.length}, newest first)`), table(cols, d.history.map(r => entryRow(r, false)), { label: "Dated rates replaced or removed" })) : null,
        el("details", { class: "dr-details", open: !d.entries.length }, el("summary", {}, "How the rate of a month is worked out"), el("ol", { class: "dr-rule" }, d.rule.map(t => el("li", {}, t))))].filter(Boolean));
    };
    load();
    return host;
  }

  /* Bring in prices: the reviewed rows, each given a yarn of the yarn master, added as dated rates. A row is matched for
     you only when its yarn and count are exactly a yarn key ("Cotton" and "40s" is Cotton 40S); otherwise you choose. */
  async function fromIntake(rows, source, box) {
    let yarns;
    try { yarns = (await call("/api/meta")).yarns; } catch (e) { say(box, e.message, "err"); return; }
    const norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9/]/g, "");
    const exact = r => (yarns.find(y => norm(y.key) === norm(`${r[1] || ""} ${r[2] || ""}`)) || {}).key || "";
    const groups = new Map();
    rows.forEach(r => { if (!r[2] || r[3] === null) return; const k = `${r[1] || ""} | ${r[2]}`; if (!groups.has(k)) groups.set(k, { rows: [], pick: exact(r) }); groups.get(k).rows.push(r); });
    if (!groups.size) { say(box, "No row has a count and a rate to add.", "err"); return; }
    const picks = new Map();
    const body = [...groups.entries()].map(([k, g]) => {
      const s = el("select", { "aria-label": `Yarn of the yarn master for ${k}` }, el("option", { value: "" }, "Leave out"), yarns.map(y => el("option", { value: y.key }, y.key)));
      s.value = g.pick; picks.set(k, s);
      const months = [...new Set(g.rows.map(r => String(r[0] || "").slice(0, 7)))].join(", ");
      return el("tr", {}, el("td", {}, k), el("td", { class: "n" }, String(g.rows.length)), el("td", {}, months), el("td", {}, s));
    });
    const msg = el("div", { "aria-live": "polite" });
    box.replaceChildren(el("div", { class: "card dr-card" }, el("div", { class: "card-head" }, el("h2", {}, "Add as dated yarn rates")),
      el("p", { class: "dr-small" }, "Give each kind of yarn read here the yarn of the yarn master it is. Only a sure match should be given: a different kind of yarn (semi-combed for combed, say) would cost purchase orders on the wrong rate. Each row's month is taken from its date; a range counts as its midpoint, and several prices of a yarn in one month as their average."),
      table([{ t: "Yarn and count as read" }, { t: "Rows", n: true }, { t: "Months" }, { t: "Yarn of the yarn master" }], body, { label: "Yarns read" }), msg,
      el("div", { class: "row-actions" }, el("button", { class: "btn primary", type: "button", onclick: async () => {
        const out = rows.map(r => r.slice(0, 6).concat([(picks.get(`${r[1] || ""} | ${r[2]}`) || {}).value || ""]));
        try {
          const r = await call("/api/intake/add-dated", { rows: out, source });
          say(msg, `${r.added} dated ${r.added === 1 ? "rate" : "rates"} added from ${r.rows} rows` + (r.left_out ? `; ${r.left_out} rows left out (no yarn given)` : "") + ": " + r.rates.map(x => `${x.yarn_key} ${label(x.month)} Rs ${money(x.rate, 2)}`).join("; ") + ". They are on the Yarn prices page.");
        } catch (err) { say(msg, err.message, "err"); }
      } }, "Add the dated rates"), el("a", { class: "btn", href: "#yarn" }, "Yarn prices"))));
  }

  return { card, fromIntake };
})();
