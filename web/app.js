/* RightPrice front end. No build step: plain JavaScript, one file.
   Every number shown comes from the server (masters.py and engine.py); nothing is costed here. */
"use strict";

// ------------------------------------------------------------------ small helpers
const $ = (s, el = document) => el.querySelector(s);
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}
const svg = (d, size = 18) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const fmt = (v, d = 2) => Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const rs = (v, d = 2) => (v < 0 ? "−" : "") + "Rs " + fmt(Math.abs(v), d);
const pct = (v, d = 1) => (v * 100).toFixed(d) + "%";
const blank = v => v === null || v === undefined || v === "";

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return r;
}
const getJSON = async path => (await api(path)).json();
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
async function download(resp, name) {
  const url = URL.createObjectURL(await resp.blob());
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 2600);
}

// tooltip: one element, positioned beside the pointer or the focused row
const tip = $("#tip");
function showTip(html, x, y) {
  tip.innerHTML = html; tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - r.width - 8)) + "px";
  tip.style.top = Math.max(8, Math.min(y + 14, innerHeight - r.height - 8)) + "px";
}
const hideTip = () => { tip.hidden = true; };
function withTip(el, html) {
  el.addEventListener("mousemove", e => showTip(html(), e.clientX, e.clientY));
  el.addEventListener("mouseleave", hideTip);
  el.addEventListener("focusin", () => { const r = el.getBoundingClientRect(); showTip(html(), r.left + 40, r.bottom - 10); });
  el.addEventListener("focusout", hideTip);
}

// ------------------------------------------------------------------ pages and navigation
const ICON = {
  dashboard: '<path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
  cost: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h2M13 12h2M9 16h2M13 16h2"/>',
  bulk: '<path d="M12 16V4m0 0-4 4m4-4 4 4M5 20h14"/>',
  yarn: '<path d="M4 17l5-5 4 4 7-8M15 8h5v5"/>',
  cotton: '<circle cx="12" cy="9" r="4"/><circle cx="8" cy="14" r="3.5"/><circle cx="16" cy="14" r="3.5"/><path d="M12 17v4"/>',
  rates: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M10 4v16"/>',
  ratecard: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  pilot: '<path d="M5 20V10M10 20V4M15 20v-8M20 20v-5"/>',
};
const NAV = [
  ["Costing", [["dashboard", "Dashboard"], ["cost", "Cost a fabric"], ["bulk", "Bulk upload"]]],
  ["Prices", [["yarn", "Yarn prices"], ["cotton", "Cotton prices"]]],
  ["Rates", [["rates", "Rate tables"], ["ratecard", "Mill rate card"], ["settings", "Settings"]]],
  ["Analysis", [["pilot", "Pilot results"]]],
];
const PAGES = {};
const state = { meta: null, sel: null, wfMode: "groups", wfOpen: new Set(), showZero: false, bulk: null, dash: null };

function buildNav() {
  const nav = $("#nav");
  for (const [group, items] of NAV) {
    nav.append(h("div", { class: "nav-group" }, group));
    for (const [id, label] of items)
      nav.append(h("a", { class: "nav-link", href: "#" + id, "data-page": id, html: svg(ICON[id]) + `<span>${label}</span>` }));
  }
}
function route() {
  const [id, ...rest] = decodeURIComponent(location.hash.slice(1) || "dashboard").split("/");
  const page = PAGES[id] ? id : "dashboard";
  document.querySelectorAll(".nav-link").forEach(a => a.dataset.page === page ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  closeMenu(); hideTip();
  const main = $("#main");
  main.replaceChildren(h("p", { class: "empty" }, "Loading..."));
  const label = NAV.flatMap(g => g[1]).find(p => p[0] === page)[1];
  document.title = label + " - RightPrice";
  const token = route.token = Symbol();
  Promise.resolve(PAGES[page](rest.join("/"))).then(nodes => {
    if (route.token !== token) return;
    main.replaceChildren(...[nodes].flat());
    scrollTo(0, 0);
  }).catch(e => { if (route.token === token) main.replaceChildren(h("div", { class: "notice err" }, "This page could not be loaded: " + e.message)); });
}
function pageHead(title, sub) { return [h("h1", {}, title), h("p", { class: "sub" }, sub)]; }

// phone menu
function closeMenu() { $("#side").classList.remove("open"); $("#scrim").hidden = true; $("#menu").setAttribute("aria-expanded", "false"); }
$("#menu").addEventListener("click", () => { const open = $("#side").classList.toggle("open"); $("#scrim").hidden = !open; $("#menu").setAttribute("aria-expanded", String(open)); });
$("#scrim").addEventListener("click", closeMenu);

// theme
function paintThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("#theme").innerHTML = svg(dark ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/>' : '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>');
  $("#theme").title = dark ? "Switch to light" : "Switch to dark";
}
$("#theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("rp-theme", next); } catch (e) { /* private window */ }
  paintThemeButton();
});

// ------------------------------------------------------------------ tables
const PCT_COLS = /^(Within |.*\(share\)|Share of total)/;
function cellText(col, v) {
  if (blank(v)) return "";
  if (typeof v === "number") {
    if (PCT_COLS.test(col)) return pct(v, 0);
    if (Number.isInteger(v)) return /year|ne\b|count|code/i.test(col) ? String(v) : v.toLocaleString("en-IN");
    return v.toLocaleString("en-IN", { maximumFractionDigits: Math.abs(v) < 10 ? 3 : 2 });
  }
  return String(v);
}
function basisTag(text) {
  const t = String(text);
  if (t.startsWith("Placeholder")) return h("span", { class: "tag warn", title: t }, "⚠ " + t);
  if (t === "Not set") return h("span", { class: "tag flat" }, t);
  return t;
}
function dataTable(data, opts = {}) {
  const { columns, rows } = data;
  const numeric = columns.map((c, i) => rows.length > 0 && rows.every(r => blank(r[i]) || typeof r[i] === "number"));
  const body = h("tbody");
  const paint = list => body.replaceChildren(...list.map(r => {
    const tr = h("tr", { class: opts.onRow ? "click" : null, tabindex: opts.onRow ? "0" : null },
      r.map((v, i) => h("td", { class: numeric[i] ? "n" : (typeof v === "string" && v.length > 60 ? "wrap" : null) },
        columns[i] === "Basis" && !blank(v) ? basisTag(v) : cellText(columns[i], v))));
    if (opts.onRow) { tr.addEventListener("click", () => opts.onRow(r)); tr.addEventListener("keydown", e => { if (e.key === "Enter") opts.onRow(r); }); }
    return tr;
  }));
  paint(rows);
  const table = h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": opts.label || "Table" },
    h("table", {}, h("thead", {}, h("tr", {}, columns.map((c, i) => h("th", { class: numeric[i] ? "n" : null, scope: "col" }, c)))), body));
  if (!rows.length) return h("p", { class: "empty" }, opts.empty || "No rows.");
  if (!opts.filter) return table;
  const count = h("span", { class: "sub", style: "margin:0" }, `${rows.length} rows`);
  const input = h("input", { class: "filter", type: "search", placeholder: "Filter rows...", "aria-label": "Filter rows", style: "max-width:280px", value: opts.query || "" });
  const apply = () => {
    const q = input.value.trim().toLowerCase();
    const list = q ? rows.filter(r => r.some(v => String(v ?? "").toLowerCase().includes(q))) : rows;
    paint(list); count.textContent = `${list.length} of ${rows.length} rows`;
  };
  input.addEventListener("input", apply); if (opts.query) apply();
  return h("div", {}, h("div", { class: "card-head" }, input, count), table);
}

// ------------------------------------------------------------------ dashboard
PAGES.dashboard = async () => {
  const d = state.dash = await getJSON("/api/dashboard");
  const c = d.cotton;
  const stat = (lbl, val, note) => h("div", { class: "card stat" }, h("div", { class: "lbl" }, lbl), h("div", { class: "val num" }, val), note ? h("div", { class: "note" }, note) : null);
  const stats = h("div", { class: "grid g4" },
    stat("Fabrics costed and saved", String(d.saved_count)),
    stat("Average quote gap", d.avg_gap_pct === null ? "—" : d.avg_gap_pct.toFixed(1) + "%", "Quote above should-cost, saved costings"),
    stat("Shankar-6 cotton", c ? "Rs " + fmt(c.price, 0) : "—", c ? `per candy, as of ${c.date}${c.age_days > 30 ? " · " + c.age_days + " days old" : ""}` : "No history loaded"),
    stat("Placeholder rates", String(d.placeholders), "Starting guesses with no data behind them"));

  const pos = { inside: ["flat", "● inside market range"], above: ["down", "▲ above market"], below: ["up", "▼ below market"] };
  const yarnCards = d.yarns.map(y => h("a", { class: "card price-card click", href: "#yarn/" + encodeURIComponent(y.key) },
    h("div", { class: "name" }, y.key, y.basis.startsWith("Placeholder") ? h("span", { class: "tag warn", title: y.basis }, "⚠ placeholder") : null),
    h("div", { class: "big num" }, `Rs ${fmt(y.rate, 0)}/kg`),
    y.position ? h("span", { class: "tag " + pos[y.position][0] }, pos[y.position][1]) : h("span", { class: "tag flat" }, "no market reference"),
    h("div", { class: "meta" }, y.market_low !== null ? `Market Rs ${fmt(y.market_low, 0)}–${fmt(y.market_high, 0)} · ` : "", "rate of ", y.date || "")));

  const cols = d.saved.columns, ix = n => cols.indexOf(n);
  const savedCards = d.saved.rows.slice(0, 8).map(r => {
    const gap = r[ix("Gap %")];
    return h("div", { class: "card price-card" },
      h("div", { class: "name" }, String(r[ix("Fabric code")] ?? "")),
      h("div", { class: "big num" }, `Rs ${fmt(r[ix("Should-cost Rs/m")])}/m`),
      blank(gap) ? h("span", { class: "tag flat" }, "no quote") : h("span", { class: "tag " + (gap > 0 ? "down" : "up") }, `${gap > 0 ? "▲" : "▼"} quote ${Math.abs(gap).toFixed(1)}% ${gap > 0 ? "above" : "below"}`),
      h("div", { class: "meta" }, [r[ix("Description")], r[ix("Supplier")], r[ix("Saved on")]].filter(v => !blank(v)).join(" · ")));
  });
  return [
    ...pageHead("Dashboard", "Saved costings, the yarn and cotton rates behind them, and how the yarn master sits against the market."),
    stats,
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Saved costings"), h("a", { class: "btn primary", href: "#cost" }, "Cost a fabric")),
      savedCards.length ? h("div", { class: "grid cards" }, savedCards) : h("p", { class: "empty" }, "Nothing saved yet. Cost a fabric and press Save to dashboard."),
      d.saved.rows.length ? h("details", { style: "margin-top:14px" }, h("summary", { style: "cursor:pointer;color:var(--muted)" }, `All ${d.saved.rows.length} saved costings as a table`), h("div", { style: "margin-top:12px" }, dataTable(d.saved, { filter: true, label: "Saved costings" }))) : null),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Cotton yarn rates in the yarn master"), h("a", { href: "#yarn" }, "All yarn prices")),
      h("div", { class: "grid cards" }, yarnCards)),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Supplier cost ratios, % of sales")),
      h("p", { class: "sub" }, "Whole-company figures from published accounts; they include yarn, garments and other businesses."),
      dataTable(d.benchmarks, { label: "Supplier cost ratios" })),
  ];
};

// ------------------------------------------------------------------ cost a fabric
const GROUP_COLOR = ["--g1", "--g2", "--g3", "--g4", "--g5", "--g6", "--g7", "--g8"];
function defaultSel() {
  const L = state.meta.lists, ex = state.meta.example;
  return { "Fabric code": ex["Fabric code"], Description: ex.Description, Supplier: "", Route: ex.Route, Weave: ex.Weave,
    Pattern: ex.Pattern, Finish: ex.Finish, "Warp yarn": ex["Warp yarn"], "Weft yarn": ex["Weft yarn"],
    "Warp yarn dyeing": "Medium", "Weft yarn dyeing": "Medium", "Piece shade": "Medium",
    "Weft (yarn dyed)": L["Weft (yarn dyed)"][0], EPI: ex.EPI, PPI: ex.PPI, "Finished width (in)": ex["Finished width (in)"],
    "Reed space (in)": ex["Reed space (in)"], "Loom type": L["Loom type"][0], "Mill tier": L["Mill tier"][0],
    "Rate card quantity": L["Rate card quantity"][0], "Order size": L["Order size"][0], "Print method": L["Print method"][0],
    "Dobby shafts": L["Dobby shafts"][0], "Top beam": L["Top beam"][0], "Quoted price (Rs/m)": "", "Extra charge (Rs/m)": "",
    "Weaving rate override (Rs/pick)": "" };
}
// which fields apply to the fabric as it stands; the rest are greyed and not sent
function applies(sel) {
  const L = state.meta.lists, yd = sel.Route === "Yarn Dyed", dobby = state.meta.weave_group[sel.Weave] === "Dobby/Matt";
  return { "Piece shade": sel.Route === "Piece Dyed", "Weft (yarn dyed)": yd, "Dobby shafts": dobby, "Top beam": dobby,
    "Order size": sel["Rate card quantity"] === L["Rate card quantity"][0] };
}
function payload(sel) {
  const on = applies(sel), out = {};
  for (const [k, v] of Object.entries(sel)) if (on[k] !== false && !blank(v)) out[k] = v;
  return out;
}

PAGES.cost = async () => {
  const L = state.meta.lists;
  if (!state.sel) state.sel = defaultSel();
  const sel = state.sel, inputs = {};
  const out = h("div", { "aria-live": "polite" });

  const field = (name, o = {}) => {
    const id = "f-" + name.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    let input;
    if (o.list) {
      input = h("select", { id }, L[o.list].map(v => h("option", { value: v }, v)));
      if (!L[o.list].includes(sel[name])) sel[name] = L[o.list][0];
      input.value = sel[name];
    } else {
      input = h("input", { id, type: o.number ? "number" : "text", value: sel[name] ?? "", step: o.step || (o.number ? "any" : null), min: o.number ? "0" : null, placeholder: o.placeholder, inputmode: o.number ? "decimal" : null });
    }
    inputs[name] = input;
    input.addEventListener(o.list ? "change" : "input", () => {
      sel[name] = o.number ? (input.value === "" ? "" : Number(input.value)) : input.value;
      if (name === "Route") {           // shades follow the route, as in the bulk template
        const shade = sel.Route === "Yarn Dyed" ? "Medium" : "Undyed";
        for (const s of ["Warp yarn dyeing", "Weft yarn dyeing"]) { sel[s] = shade; inputs[s].value = shade; }
      }
      sync(); recalc();
    });
    return h("div", { class: "field" + (o.wide ? " wide" : "") }, h("label", { for: id }, o.label || name), input, o.hint ? h("span", { class: "hint" }, o.hint) : null);
  };
  const sync = () => { const on = applies(sel); for (const [k, el] of Object.entries(inputs)) el.disabled = on[k] === false; };
  const card = (title, ...fields) => h("div", { class: "card" }, h("h3", {}, title), h("div", { class: "fields" }, fields));

  const form = h("form", { class: "form-grid", onsubmit: e => e.preventDefault() },
    card("Fabric", field("Fabric code"), field("Supplier"), field("Description", { wide: true }), field("Route", { list: "Route" }), field("Weave", { list: "Weave" }), field("Pattern", { list: "Pattern" }), field("Finish", { list: "Finish" })),
    card("Yarn and dyeing", field("Warp yarn", { list: "Yarn" }), field("Weft yarn", { list: "Yarn" }), field("Warp yarn dyeing", { list: "Yarn shade" }), field("Weft yarn dyeing", { list: "Yarn shade" }), field("Weft (yarn dyed)", { list: "Weft (yarn dyed)", hint: "Undyed takes weft yarn dyeing away" }), field("Piece shade", { list: "Piece shade" })),
    card("Construction", field("EPI", { number: true, label: "Ends per inch (EPI)" }), field("PPI", { number: true, label: "Picks per inch (PPI)" }), field("Finished width (in)", { number: true, label: "Finished width (inch)" }), field("Reed space (in)", { number: true, label: "Reed space (inch)", hint: "Blank = worked out from width" })),
    card("Mill and order", field("Loom type", { list: "Loom type" }), field("Mill tier", { list: "Mill tier" }), field("Rate card quantity", { list: "Rate card quantity", hint: "Takes the place of Order size" }), field("Order size", { list: "Order size" })),
    card("Mill rate card upcharges", field("Print method", { list: "Print method", hint: "Not selected = printing rate per kg" }), field("Dobby shafts", { list: "Dobby shafts" }), field("Top beam", { list: "Top beam" })),
    card("Compare and overrides (optional)", field("Quoted price (Rs/m)", { number: true, label: "Supplier's quote (Rs/m)" }), field("Extra charge (Rs/m)", { number: true }), field("Weaving rate override (Rs/pick)", { number: true, step: "0.01", wide: true, hint: "Blank = use the rate table" })));
  sync();

  let timer, last = 0;
  const recalc = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++last;
      try {
        const res = await (await postJSON("/api/cost", payload(sel))).json();
        if (mine === last) out.replaceChildren(...costView(res, sel));
      } catch (e) {
        if (mine === last) out.replaceChildren(h("div", { class: "notice err", role: "alert" }, "Cannot cost this fabric: " + e.message));
      }
    }, 180);
  };
  recalc();
  return [...pageHead("Cost a fabric", "Every cost driver is a drop-down from the rate master. Only EPI, PPI, width and reed space are typed. The cost updates as you change a choice."), form,
    h("div", { class: "row-actions" }, h("button", { class: "btn", type: "button", onclick: () => { state.sel = null; route(); } }, "Reset to the example fabric")),
    h("div", { style: "margin-top:16px" }, out)];
};

function costView(res, sel) {
  const title = [sel["Fabric code"], sel.Description].filter(v => !blank(v)).join(" — ");
  let quote = null;
  if (res.quote !== null) {
    const above = res.gap >= 0;
    quote = h("div", { class: "quote" }, h("span", { class: "tag " + (above ? "down" : "up") }, `${above ? "▲" : "▼"} Quote ${rs(res.quote)}/m is ${rs(Math.abs(res.gap))} (${pct(Math.abs(res.gap_pct))}) ${above ? "above" : "below"} should-cost`));
  }
  const hero = h("div", { class: "card hero" },
    h("div", { class: "lbl" }, title, title ? " · " : "", "ex-mill should-cost"),
    h("div", { class: "big num" }, `${rs(res.total_per_m)} / m`),
    h("div", { class: "facts num" }, h("span", {}, `${rs(res.per_kg, 0)} / kg`), h("span", {}, `about ${fmt(res.gsm, 0)} g/m²`), h("span", {}, `${fmt(res.finished_g_per_m, 0)} g per running metre`)),
    quote,
    h("div", { class: "row-actions" },
      h("button", { class: "btn primary", onclick: async e => { e.target.disabled = true; try { await postJSON("/api/save", payload(sel)); toast("Saved to the dashboard"); } catch (err) { toast("Not saved: " + err.message); } e.target.disabled = false; } }, "Save to dashboard"),
      h("button", { class: "btn", onclick: async () => { try { await download(await postJSON("/api/cost-sheet", payload(sel)), `Should cost ${sel["Fabric code"] || "fabric"}.xlsx`); } catch (err) { toast(err.message); } } }, "Download cost sheet")));

  const wfBox = h("div");
  const paint = () => wfBox.replaceChildren(waterfall(res));
  const modeBtn = (mode, label) => h("button", { type: "button", "aria-pressed": String(state.wfMode === mode), onclick: () => { state.wfMode = mode; state.wfOpen.clear(); chart.replaceWith(chart = chartCard()); } }, label);
  const chartCard = () => {
    paint();
    const zero = h("input", { type: "checkbox", id: "zero" }); zero.checked = state.showZero;
    zero.addEventListener("change", () => { state.showZero = zero.checked; paint(); });
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "How the price builds up"), h("div", { class: "sub", style: "margin:2px 0 0" }, state.wfMode === "groups" ? "One step per cost group. Click a group to open its sub-costs." : "Every sub-cost as its own step, under its group.")),
        h("div", { style: "display:flex;gap:14px;align-items:center;flex-wrap:wrap" },
          h("label", { for: "zero", style: "color:var(--muted);display:flex;gap:6px;align-items:center;min-height:38px" }, zero, "Show lines at zero"),
          h("div", { class: "seg", role: "group", "aria-label": "Level of detail" }, modeBtn("groups", "Groups"), modeBtn("all", "All sub-costs")))),
      wfBox,
      h("div", { class: "legend", "aria-hidden": "true" }, res.buckets.map((b, i) => h("span", {}, h("i", { style: `background:var(${GROUP_COLOR[i % 8]})` }), b.name)), h("span", {}, h("i", { style: "background:var(--total)" }), "Running total")));
  };
  let chart = chartCard();

  const lineRows = [];
  for (const b of res.buckets) {
    lineRows.push(h("tr", { class: "grp" }, h("td", { colspan: "2" }, b.name), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, pct(b.pct))));
    for (const l of b.lines) lineRows.push(h("tr", {}, h("td", {}, l.name), h("td", { class: "wrap" }, l.basis), h("td", { class: "n" }, fmt(l.amount)), h("td", { class: "n" }, pct(res.total_per_m ? l.amount / res.total_per_m : 0))));
  }
  lineRows.push(h("tr", { class: "grp" }, h("td", { colspan: "2" }, "Should-cost"), h("td", { class: "n" }, fmt(res.total_per_m)), h("td", { class: "n" }, "100.0%")));
  const tableView = h("details", { class: "card" }, h("summary", {}, "Table of every line"),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Line"), h("th", {}, "How it is worked out"), h("th", { class: "n" }, "Rs/m"), h("th", { class: "n" }, "Share of total"))), h("tbody", {}, lineRows))));
  const used = { columns: ["Item", "Choice", "Value", "Unit", "Basis"], rows: res.rates_used.map(u => [u.Item, u.Choice, u.Value, u.Unit, u.Basis]) };
  const ratesView = h("details", { class: "card" }, h("summary", {}, "Rates used and where each came from"), dataTable(used, { label: "Rates used" }));
  const warn = res.placeholders.length ? h("div", { class: "notice", role: "status" }, h("b", {}, "Provisional. "), "Placeholder rates were used for: " + res.placeholders.join(", ") + ". These are starting guesses with no data behind them.") : null;
  return [hero, warn, chart, tableView, ratesView].filter(Boolean);
}

/* Waterfall: each step starts where the one before ended. In 'groups' a group is one bar that
   opens into its sub-costs; in 'all' every group is open. A discount steps back to the left. */
function waterfall(res) {
  const total = res.total_per_m;
  let run = 0, peak = 0;
  for (const b of res.buckets) for (const l of b.lines) { run += l.amount; peak = Math.max(peak, run); }
  const scale = v => (v / (peak || 1)) * 100;
  const box = h("div", { class: "wf", role: "list" });
  const bar = (from, amount, cls, color) => {
    const lo = Math.min(from, from + amount), w = Math.abs(amount);
    return h("div", { class: "wf-bar " + cls + (amount < 0 ? " neg" : ""), style: `left:${scale(lo)}%;width:${scale(w)}%;${color ? `background-color:var(${color})` : ""}` });
  };
  const row = (o) => {
    const el = h("div", { class: "wf-row " + (o.cls || ""), role: "listitem", tabindex: o.button ? null : "0" },
      h("div", { class: "wf-label " + (o.labelCls || "") }, o.button || [o.color ? h("span", { class: "dot", style: `background:var(${o.color})` }) : null, o.name]),
      h("div", { class: "wf-track" }, o.bar),
      h("div", { class: "wf-val " + (o.labelCls || "") }, o.value));
    if (o.tip) withTip(el, o.tip);
    box.append(el);
  };
  run = 0;
  res.buckets.forEach((b, i) => {
    const color = GROUP_COLOR[i % 8], start = run, open = state.wfMode === "all" || state.wfOpen.has(b.name);
    const lines = b.lines.filter(l => state.showZero || Math.abs(l.amount) >= 0.005);
    const tipG = () => `<b>${b.name}</b>${rs(b.amount)} per metre · ${pct(b.pct)} of the price<br>Running total ${rs(start + b.amount)}`;
    const toggle = state.wfMode === "groups" ? h("button", { type: "button", "aria-expanded": String(open), onclick: () => { open ? state.wfOpen.delete(b.name) : state.wfOpen.add(b.name); box.replaceWith(waterfall(res)); } },
      h("span", { class: "caret", html: svg('<path d="m9 6 6 6-6 6"/>', 10) }), h("span", { class: "dot", style: `background:var(${color})` }), h("span", {}, b.name)) : null;
    if (!open) {
      row({ button: toggle, bar: bar(start, b.amount, "", color), value: fmt(b.amount), tip: tipG });
      run += b.amount;
      return;
    }
    row({ cls: "head", button: toggle, name: b.name, color, labelCls: "total", bar: bar(start, b.amount, "sumbar"), value: [fmt(b.amount), h("small", {}, pct(b.pct))], tip: tipG });
    for (const l of lines) {
      const from = run;
      row({ name: l.name, labelCls: "sub", bar: bar(from, l.amount, "", color), value: fmt(l.amount),
        tip: () => `<b>${l.name}</b>${rs(l.amount)} per metre · ${pct(total ? l.amount / total : 0)} of the price<br>${l.basis}` });
      run += l.amount;
    }
    run = start + b.amount;
  });
  box.append(h("div", { class: "wf-sep", role: "presentation" }));
  row({ cls: "sum", name: "Should-cost", labelCls: "total", bar: bar(0, total, "totalbar"), value: fmt(total), tip: () => `<b>Should-cost</b>${rs(total)} per metre, ex-mill` });
  box.append(h("div", { class: "wf-axis", "aria-hidden": "true" }, h("span", {}, "Rs 0"), h("span", {}, `Rs ${fmt(peak / 2, 0)}`), h("span", {}, `Rs ${fmt(peak, 0)} per metre`)));
  return box;
}

// ------------------------------------------------------------------ bulk upload
PAGES.bulk = async () => {
  const out = h("div", { "aria-live": "polite" });
  const show = () => {
    const b = state.bulk;
    if (!b) return out.replaceChildren();
    const cols = b.results.columns, total = b.results.rows.length;
    const stat = (lbl, val) => h("div", { class: "card stat" }, h("div", { class: "lbl" }, lbl), h("div", { class: "val num" }, String(val)));
    out.replaceChildren(
      h("div", { class: "grid g3", style: "margin-top:16px" }, stat("Rows read", total), stat("Costed", total - b.rejected), stat("Rejected", b.rejected)),
      b.rejected ? h("div", { class: "notice" }, "Rejected rows carry the reason in the Error column.") : null,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Results"),
        h("button", { class: "btn", onclick: async () => download(await postJSON("/api/bulk-download", b.results), "Should_Cost_Results.xlsx") }, "Download results")),
        h("p", { class: "sub" }, "Click a costed row to open its cost view."),
        dataTable(b.results, { filter: true, label: "Bulk results", onRow: r => {
          if (r[cols.indexOf("Error")]) return toast("This row was rejected: " + r[cols.indexOf("Error")]);
          const i = b.results.rows.indexOf(r);
          state.sel = Object.assign(defaultSel(), Object.fromEntries(Object.entries(b.inputs[i]).filter(([, v]) => !blank(v))));
          location.hash = "#cost";
        } })));
  };
  const file = h("input", { type: "file", accept: ".xlsx", id: "bulk-file", style: "max-width:100%" });
  file.addEventListener("change", async () => {
    if (!file.files[0]) return;
    const fd = new FormData(); fd.append("file", file.files[0]);
    out.replaceChildren(h("p", { class: "empty" }, "Costing every row..."));
    try { state.bulk = await (await api("/api/bulk", { method: "POST", body: fd })).json(); show(); }
    catch (e) { state.bulk = null; out.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); }
  });
  show();
  return [...pageHead("Bulk upload", "Cost many fabrics at once. The template's drop-downs carry the same lists as the tool, and a value not on a list is rejected."),
    h("div", { class: "card" }, h("div", { class: "grid g3" },
      h("div", {}, h("h3", {}, "1. Get the template"), h("a", { class: "btn", href: "/api/template" }, "Download upload template"), h("p", { class: "sub", style: "margin-top:10px" }, "Download a fresh one after any list changes.")),
      h("div", {}, h("h3", {}, "2. Fill one row per fabric"), h("p", { class: "sub" }, "Dark columns are required. Mill rate card columns are optional and charge nothing when left blank.")),
      h("div", {}, h("h3", {}, "3. Upload it"), h("label", { for: "bulk-file", class: "sub", style: "display:block;margin-bottom:8px" }, "Filled template (.xlsx)"), file))),
    out];
};

// ------------------------------------------------------------------ prices
PAGES.yarn = async (query) => {
  const [yr, mk, d] = await Promise.all([getJSON("/api/table/Yarn_Rates"), getJSON("/api/table/Market_Yarn"), state.dash || getJSON("/api/dashboard")]);
  const cmp = { columns: ["Yarn key", "Master Rs/kg", "Market low", "Market high", "Position"],
    rows: d.yarns.filter(y => y.position).map(y => [y.key, y.rate, y.market_low, y.market_high, { inside: "Inside range", above: "Above market", below: "Below market" }[y.position]]) };
  return [...pageHead("Yarn prices", "The yarn master is used in every costing. The market reference is for comparison only."),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Yarn master"), h("a", { class: "btn", href: "/classic/" }, "Edit rates or bring in prices")), dataTable(yr, { filter: true, query, label: "Yarn master" })),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Master against market, combed compact cotton")), dataTable(cmp, { label: "Master against market", empty: "No yarn in the master has a market reference yet." })),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Market reference")), dataTable(mk, { filter: true, label: "Market reference" }))];
};

PAGES.cotton = async () => {
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
    h("div", { class: "grid g4" }, stat("Latest Shankar-6", "Rs " + fmt(last[1], 0), "per candy"), stat("As of", last[0].toISOString().slice(0, 10), age > 30 ? `${age} days old` : null), stat("Over 30 days", tag(chg(m1))), stat("Over 12 months", tag(chg(y1)))),
    age > 30 ? h("div", { class: "notice" }, `The latest cotton price is ${age} days old. Newer rows can be added under Edit rates.`) : null,
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Shankar-6, Rs per candy"), chips), box, h("p", { class: "sub", style: "margin:12px 0 0" }, "Source: " + c.source)),
    h("details", { class: "card" }, h("summary", {}, "Table of the last 60 prices"), dataTable({ columns: ["Date", "Rs per candy"], rows: pts.slice(-60).reverse().map(p => [p[0].toISOString().slice(0, 10), p[1]]) }, { label: "Cotton prices" }))];
};

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
    showTip(`<b>Rs ${fmt(ys[best], 0)} per candy</b>${pts[best][0].toISOString().slice(0, 10)}`, e.clientX, e.clientY);
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
  return el;
}

// ------------------------------------------------------------------ rates
function tabbed(title, sub, sheets, first) {
  return async (want) => {
    const box = h("div");
    const chips = h("div", { class: "chips", role: "tablist", "aria-label": title });
    const open = async sheet => {
      [...chips.children].forEach(c => c.setAttribute("aria-selected", String(c.dataset.sheet === sheet)));
      box.replaceChildren(h("p", { class: "empty" }, "Loading..."));
      try { const t = await getJSON("/api/table/" + sheet); box.replaceChildren(dataTable(t, { filter: t.rows.length > 12, label: t.label })); }
      catch (e) { box.replaceChildren(h("div", { class: "notice err" }, e.message)); }
    };
    for (const s of sheets) chips.append(h("button", { class: "chip", role: "tab", "data-sheet": s, onclick: () => open(s) }, state.meta.tables[s]));
    await open(sheets.includes(want) ? want : first || sheets[0]);
    return [...pageHead(title, sub),
      h("div", { class: "card" }, h("div", { class: "card-head" }, chips, h("a", { class: "btn", href: "/classic/" }, "Edit rates")), box,
        h("div", { class: "notice info" }, "Basis shows where each number came from. ", h("span", { class: "tag warn" }, "⚠ Placeholder"), " marks a starting guess with no data behind it; the cost view warns whenever one is used."))];
  };
}
PAGES.rates = (w) => tabbed("Rate tables", "Every drop-down choice looks up a number here. The rate master workbook is the source of truth for all of them.",
  ["Weaving_Rates", "Weaving_Uplifts", "Sizing_Rates", "Yarn_Dyeing", "Piece_Dyeing", "Finishing_Rates", "Class_Defaults", "Weaves", "Content_Groups"])(w);
PAGES.ratecard = (w) => tabbed("Mill rate card", "Optional upcharges from the mill rate card of 23 Nov 2026. Each is rupees per metre on the price and is not marked up. Which mill the card is from is not confirmed.",
  ["Print_Methods", "Dobby_Charges", "Weft_Options", "Quantity_Terms", "Finishing_Rates"])(w);
PAGES.settings = (w) => tabbed("Settings", "Calculation settings, mill tiers and order size slabs. Method: the corrected method of the V1 workbook; price basis ex-mill, so freight is left out.",
  ["Settings", "Mill_Tier", "Order_Slab", "Supplier_Benchmarks"])(w);

// ------------------------------------------------------------------ pilot
PAGES.pilot = async () => {
  let p;
  try { p = await getJSON("/api/pilot"); }
  catch (e) { return [...pageHead("Pilot results", "Should-cost against purchase order prices."), h("div", { class: "notice info" }, e.message + ".")]; }
  const o = p.Overall, c = o.columns, all = o.rows[0], hb = o.rows[1], v = (r, n) => r[c.indexOf(n)];
  const stat = (lbl, val, note) => h("div", { class: "card stat" }, h("div", { class: "lbl" }, lbl), h("div", { class: "val num" }, val), h("div", { class: "note" }, note));
  const sect = (title, key, sub, open) => p[key] ? h("details", { class: "card", open: open || null }, h("summary", {}, title), sub ? h("p", { class: "sub" }, sub) : null, dataTable(p[key], { label: title, filter: p[key].rows.length > 15 })) : null;
  return [...pageHead("Pilot results", "100% cotton wovens costed with the current rate master and compared with the price paid. Gap is the purchase price above should-cost."),
    h("div", { class: "grid g4" },
      stat("Fabrics costed", fmt(v(all, "Fabrics"), 0), `${fmt(v(hb, "Fabrics"), 0)} held back as the fair test`),
      stat("Median gap", v(all, "Median gap %").toFixed(1) + "%", `Held-back third ${v(hb, "Median gap %").toFixed(1)}%`),
      stat("Within 10%", pct(v(all, "Within 10%"), 0), `Held-back third ${pct(v(hb, "Within 10%"), 0)}`),
      stat("Within 20%", pct(v(all, "Within 20%"), 0), `Within 5%: ${pct(v(all, "Within 5%"), 0)}`)),
    sect("Overall and the known over-costed groups", "Overall", null, true),
    sect("By route and weave", "By route and weave", null, true),
    sect("By supplier", "By supplier"),
    sect("Mill rate card, step by step", "Rate card steps", "The same fabrics with the rate card inputs switched on one at a time, then two what-ifs."),
    sect("What the pilot could set from PLM", "Rate card inputs"),
    sect("Funnel", "Funnel"),
    h("div", { class: "notice info" }, "The sheets below are a calibration draft for review. Nothing in them has been applied to the rate master."),
    sect("Draft: order size", "Draft: Order size"), sect("Draft: weaving rates", "Draft: Weaving"), sect("Draft: printing", "Draft: Printing"), sect("Draft: held-back test", "Draft: Held-back test")].filter(Boolean);
};

// ------------------------------------------------------------------ search
function searchIndex() {
  const items = NAV.flatMap(g => g[1]).map(([id, label]) => ({ text: label, kind: "Page", href: "#" + id }));
  const home = { Yarn_Rates: "#yarn", Market_Yarn: "#yarn", Cotton_Prices: "#cotton" };
  for (const s of ["Print_Methods", "Dobby_Charges", "Weft_Options", "Quantity_Terms"]) home[s] = "#ratecard/" + s;
  for (const s of ["Settings", "Mill_Tier", "Order_Slab", "Supplier_Benchmarks"]) home[s] = "#settings/" + s;
  for (const [sheet, label] of Object.entries(state.meta.tables)) items.push({ text: label, kind: "Rate table", href: home[sheet] || "#rates/" + sheet });
  for (const y of state.meta.yarns) items.push({ text: y.key, kind: `Yarn · Rs ${fmt(y.rate, 0)}/kg`, href: "#yarn/" + encodeURIComponent(y.key) });
  if (state.dash) { const c = state.dash.saved.columns; for (const r of state.dash.saved.rows) items.push({ text: [r[c.indexOf("Fabric code")], r[c.indexOf("Description")]].filter(v => !blank(v)).join(" — "), kind: "Saved costing", href: "#dashboard" }); }
  return items;
}
function setupSearch() {
  const input = $("#search"), box = $("#search-results");
  let on = -1;
  const close = () => { box.hidden = true; input.setAttribute("aria-expanded", "false"); on = -1; };
  const paint = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) return close();
    const hits = searchIndex().filter(i => i.text.toLowerCase().includes(q)).slice(0, 12);
    box.replaceChildren(...(hits.length ? hits.map(i => h("a", { href: i.href, role: "option", onclick: () => { input.value = ""; close(); } }, i.text, h("span", {}, i.kind))) : [h("p", {}, "Nothing matches.")]));
    box.hidden = false; input.setAttribute("aria-expanded", "true"); on = -1;
  };
  input.addEventListener("input", paint);
  input.addEventListener("focus", async () => { if (!state.dash) { try { state.dash = await getJSON("/api/dashboard"); } catch (e) { /* search works without it */ } } paint(); });
  input.addEventListener("keydown", e => {
    const links = [...box.querySelectorAll("a")];
    if (e.key === "Escape") { close(); input.blur(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (!links.length) return; on = (on + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length; links.forEach((a, i) => a.classList.toggle("on", i === on)); links[on].scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter" && links.length) { e.preventDefault(); links[Math.max(on, 0)].click(); location.hash = links[Math.max(on, 0)].getAttribute("href"); }
  });
  document.addEventListener("click", e => { if (!e.target.closest(".search")) close(); });
}

// ------------------------------------------------------------------ start
(async function start() {
  buildNav(); paintThemeButton();
  $("#today").textContent = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  try { state.meta = await getJSON("/api/meta"); }
  catch (e) { $("#main").replaceChildren(h("div", { class: "notice err" }, "The rate master could not be read: " + e.message)); return; }
  setupSearch();
  addEventListener("hashchange", route);
  route();
})();
