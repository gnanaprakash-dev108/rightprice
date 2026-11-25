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
const tidy = (v, d) => (Math.abs(Number(v)) < 0.5 / 10 ** d ? 0 : Number(v));          // never "-0.00"
const fmt = (v, d = 2) => tidy(v, d).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−");
const rs = (v, d = 2) => (tidy(v, d) < 0 ? "−" : "") + "Rs " + fmt(Math.abs(v), d);
const day = iso => { const d = new Date(iso); return isNaN(d) ? String(iso ?? "") : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); };
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
  compare: '<path d="M9 4v16M15 4v16M4 8h5M4 16h5M15 8h5M15 16h5"/>',
  intake: '<path d="M12 4v12m0 0-4-4m4 4 4-4M5 20h14"/>',
  yarn: '<path d="M4 17l5-5 4 4 7-8M15 8h5v5"/>',
  cotton: '<circle cx="12" cy="9" r="4"/><circle cx="8" cy="14" r="3.5"/><circle cx="16" cy="14" r="3.5"/><path d="M12 17v4"/>',
  rates: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M10 4v16"/>',
  ratecard: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  pilot: '<path d="M5 20V10M10 20V4M15 20v-8M20 20v-5"/>',
  rightcost: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  pack: '<path d="M8 4h8l3 3v13H5V4z"/><path d="M8 10h8M8 14h8M8 18h5"/>',
};
const NAV = [
  ["Costing", [["dashboard", "Dashboard"], ["rightcost", "Right cost"], ["cost", "Cost a fabric"], ["bulk", "Bulk upload and list"], ["compare", "Compare"], ["pack", "Negotiation pack"]]],
  ["Prices", [["yarn", "Yarn prices"], ["cotton", "Cotton prices"], ["intake", "Bring in prices"]]],
  ["Rates", [["rates", "Rate tables"], ["ratecard", "Mill rate card"], ["settings", "Settings"]]],
  ["Analysis", [["pilot", "Pilot results"]]],
];
const PAGES = {};
const state = { meta: null, sel: null, list: null, listId: null, sim: null, visited: new Set(), bySize: true, chart: "bars", wfMode: "groups", wfOpen: new Set(), showZero: false, bulk: null, dash: null };

function buildNav() {
  const nav = $("#nav");
  for (const [group, items] of NAV) {
    nav.append(h("div", { class: "nav-group" }, group));
    for (const [id, label] of items)
      nav.append(h("a", { class: "nav-link", href: id === "rightcost" ? "/rightcost" : "#" + id, "data-page": id, title: label, html: svg(ICON[id]) + `<span>${label}</span>` }));
  }
}
function route() {
  const [id, ...rest] = decodeURIComponent(location.hash.slice(1) || "dashboard").split("/");
  const page = PAGES[id] ? id : "dashboard";
  document.querySelectorAll(".nav-link").forEach(a => a.dataset.page === page ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  closeMenu(); hideTip();
  if (document.activeElement && document.activeElement.closest("#side")) document.activeElement.blur();     // let the folded panel close once a page is chosen
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

// display preferences, kept in this browser: a pinned left panel and a tall header both cost space
const PREFS = { pin: false, roomy: false };
function loadPrefs() { try { Object.assign(PREFS, JSON.parse(localStorage.getItem("rp-display") || "{}")); } catch (e) { /* private window */ } applyPrefs(); }
function applyPrefs() {
  document.body.classList.toggle("rail", !PREFS.pin);
  document.body.classList.toggle("compact", !PREFS.roomy);
  const b = $("#pin"); if (b) { b.setAttribute("aria-pressed", String(PREFS.pin)); b.title = PREFS.pin ? "Unpin: fold the panel to icons" : "Pin the panel open"; }
  const sw = $("#pref-pin"); if (sw) sw.checked = PREFS.pin;
  const sc = $("#pref-compact"); if (sc) sc.checked = !PREFS.roomy;
}
function setPref(key, value) { PREFS[key] = value; try { localStorage.setItem("rp-display", JSON.stringify(PREFS)); } catch (e) { /* private window */ } applyPrefs(); dispatchEvent(new Event("resize")); }

// phone menu
function closeMenu() { $("#side").classList.remove("open"); $("#scrim").hidden = true; $("#menu").setAttribute("aria-expanded", "false"); }
$("#menu").addEventListener("click", () => { const open = $("#side").classList.toggle("open"); $("#scrim").hidden = !open; $("#menu").setAttribute("aria-expanded", String(open)); });
$("#scrim").addEventListener("click", closeMenu);
document.addEventListener("keydown", e => { if (e.key === "Escape" && document.activeElement && document.activeElement.closest("#side")) { document.activeElement.blur(); closeMenu(); } });

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

/* A table as inputs: change cells, add or remove rows, save the whole sheet back to the rate master.
   The server checks it (numbers where numbers belong, no duplicate keys, the example still costs). */
function editTable(t, sheet, done) {
  const numeric = t.columns.map((c, i) => !(sheet === "Settings" && c === "Value") && t.rows.length > 0 && t.rows.every(r => blank(r[i]) || typeof r[i] === "number"));
  const body = h("tbody");
  const addRow = r => {
    const tr = h("tr", {}, t.columns.map((c, i) => h("td", {}, h("input", { class: "cell" + (numeric[i] ? " n" : ""), type: numeric[i] ? "number" : "text", step: numeric[i] ? "any" : null, value: r ? (r[i] ?? "") : "", "aria-label": c }))),
      h("td", {}, h("button", { class: "icon-btn sm", type: "button", "aria-label": "Remove this row", title: "Remove this row", onclick: () => tr.remove() }, "\u00D7")));
    body.append(tr); return tr;
  };
  t.rows.forEach(addRow);
  const msg = h("div", { "aria-live": "polite" });
  const save = h("button", { class: "btn primary", type: "button", onclick: async () => {
    const rows = [...body.rows].map(tr => [...tr.querySelectorAll("input")].map((inp, i) => inp.value.trim() === "" ? null : (numeric[i] ? Number(inp.value) : inp.value.trim())));
    save.disabled = true;
    try { await api("/api/table/" + sheet, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ columns: t.columns, rows }) }); state.meta = await getJSON("/api/meta"); state.dash = null; toast("Saved to the rate master"); done(); }
    catch (e) { msg.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); save.disabled = false; }
  } }, "Save");
  return h("div", {},
    h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Editing " + t.label }, h("table", { class: "edit" }, h("thead", {}, h("tr", {}, t.columns.map(c => h("th", { scope: "col" }, c)), h("th", {}, h("span", { class: "visually-hidden" }, "Remove")))), body)),
    msg,
    h("div", { class: "row-actions" }, save, h("button", { class: "btn", type: "button", onclick: () => { addRow(null).querySelector("input").focus(); } }, "Add a row"), h("button", { class: "btn", type: "button", onclick: done }, "Cancel")),
    h("p", { class: "sub", style: "margin:12px 0 0" }, "Saving changes the rate master for every costing from now on. The first change of each day keeps a dated copy of the workbook beside it."));
}
function tableCard(sheet, title, opts = {}) {
  const box = h("div"), editBtn = h("button", { class: "btn", type: "button" }, "Edit");
  const view = async () => { editBtn.hidden = !state.meta.editable.includes(sheet); const t = await getJSON("/api/table/" + sheet); box.replaceChildren(dataTable(t, { filter: t.rows.length > 12, label: t.label, query: opts.query })); };
  editBtn.addEventListener("click", async () => { editBtn.hidden = true; box.replaceChildren(editTable(await getJSON("/api/table/" + sheet), sheet, view)); });
  const card = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, title), h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, opts.extra, editBtn)), box);
  return view().then(() => card);
}

// ------------------------------------------------------------------ dashboard
/* Everything on this page is the buyer's own data: purchase orders costed by the tool, the rate
   master, and the cotton price history. Nothing here is an outside benchmark. */
// a gap is coloured only where the tool can be leaned on; elsewhere it is shown plainly with a caution
function gapTag(gap, trust) {
  if (trust === "weak") return h("span", { class: "tag warn", title: "The tool fits past prices of this group poorly, so this gap says more about the tool than about the price" }, `${pctSigned(gap)} \u00B7 tool unsure`);
  return h("span", { class: "tag " + (Math.abs(gap) <= 5 ? "flat" : gap > 0 ? "down" : "up"), title: Math.abs(gap) <= 5 ? "Within 5%: treat as noise" : gap > 0 ? "You paid above should-cost" : "You paid below should-cost" }, pctSigned(gap));
}
const pctSigned = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
function yarnWhatIf(ins, list) {
  const ref = ins.reference, costed = list.rows.filter(r => r.should_cost !== null && r.inputs);
  const pick = h("select", { id: "wi-yarn" }, h("option", { value: "*" }, "All yarns"), state.meta.yarns.map(y => h("option", { value: y.key }, `${y.key} · Rs ${fmt(y.rate, 0)}/kg`)));
  const slider = h("input", { id: "wi-pct", type: "range", min: "-20", max: "20", step: "1", value: "5" });
  const num = h("input", { id: "wi-num", type: "number", min: "-50", max: "50", step: "1", value: "5", "aria-label": "Yarn price change, per cent" });
  const out = h("div", { class: "whatif-out", "aria-live": "polite" });
  let turn = 0;
  const run = async () => {
    const p = Number(num.value) || 0, mine = ++turn, key = pick.value;
    const parts = [];
    // the reference fabric: worked out here from its rupees per Rs 10 a kilo
    const uses = key === "*" || key === state.meta.example["Warp yarn"];
    const dRef = uses ? (ref.warp_per_10 * ref.warp_rate + ref.weft_per_10 * ref.weft_rate) / 10 * p / 100 : 0;
    parts.push(h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, "Reference shirting, 40s × 40s, 132 × 84"), h("b", { class: "num" }, `${rs(ref.total)} → ${rs(ref.total + dRef)}`), h("span", { class: "tag " + (dRef > 0.005 ? "down" : dRef < -0.005 ? "up" : "flat") }, uses ? `${dRef >= 0 ? "+" : "−"}${fmt(Math.abs(dRef))} /m (${pctSigned(dRef / ref.total * 100)})` : "does not use this yarn")));
    if (costed.length) {
      parts.push(h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `Your ${costed.length} listed fabrics`), h("b", { class: "num" }, "working out…")));
      out.replaceChildren(...parts);
      try {
        const v = await (await postJSON("/api/list", { yarn_pct: { [key]: p } })).json(); if (mine !== turn) return;
        const moved = v.rows.filter(r => r.should_cost !== null && (p === 0 || r.simulated !== null)).map(r => p === 0 ? Object.assign({}, r, { simulated: r.should_cost }) : r);
        const d = moved.map(r => r.simulated - r.should_cost), avg = d.reduce((a, x) => a + x, 0) / (d.length || 1), base = moved.reduce((a, r) => a + r.should_cost, 0) / (moved.length || 1);
        const hit = d.filter(x => Math.abs(x) >= 0.005).length;
        parts[1] = h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `Your ${moved.length} listed fabrics, average`), h("b", { class: "num" }, `${rs(base)} → ${rs(base + avg)}`), h("span", { class: "tag " + (avg > 0.005 ? "down" : avg < -0.005 ? "up" : "flat") }, `${avg >= 0 ? "+" : "−"}${fmt(Math.abs(avg))} /m (${pctSigned(base ? avg / base * 100 : 0)})`), h("a", { href: "#bulk", class: "sub", style: "margin:0", onclick: () => { state.listUI = state.listUI || { groups: { Fabric: true, Order: false, "Mill's price build-up": true }, picked: new Set(), filter: "", show: "all" }; state.listUI.yarn = key; state.listUI.pct = String(p || ""); } }, p === 0 ? "see each in the list" : `${hit} of ${moved.length} use this yarn and move \u00B7 see each in the list`));
      } catch (e) { parts[1] = h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, "Your listed fabrics"), h("span", { class: "sub", style: "margin:0" }, e.message)); }
    }
    out.replaceChildren(...parts);
  };
  slider.addEventListener("input", () => { num.value = slider.value; run(); });
  num.addEventListener("input", () => { slider.value = Math.max(-20, Math.min(20, Number(num.value) || 0)); run(); });
  pick.addEventListener("change", run); run();
  return h("div", { class: "card whatif" },
    h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "If yarn prices move"), h("div", { class: "sub", style: "margin:2px 0 0" }, `A yarn price move does not reach the fabric in full. On the reference shirting, 10% on yarn is about ${(ref.yarn_share * 10).toFixed(1)}% on the fabric. Each Rs 10 a kilo on the warp yarn is ${rs(ref.warp_per_10)} a metre; on the weft, ${rs(ref.weft_per_10)}.`))),
    h("div", { class: "whatif-controls" }, h("div", { class: "field" }, h("label", { for: "wi-yarn" }, "Yarn"), pick), h("div", { class: "field grow" }, h("label", { for: "wi-pct" }, "Price change"), h("div", { class: "slider-row" }, h("span", { class: "sub", style: "margin:0" }, "−20%"), slider, h("span", { class: "sub", style: "margin:0" }, "+20%"), num, h("span", {}, "%")))),
    out);
}

PAGES.dashboard = async () => {
  const [ins, list] = await Promise.all([getJSON("/api/insights"), (await postJSON("/api/list", {})).json()]);
  state.list = list;
  const p = ins.pilot, nodes = [...pageHead("Dashboard", "What you pay against what it should cost, where the money goes, and what to ask before you negotiate. Panels 1, 2 and 4 are your purchase orders costed on your rate master; panel 3 is the cotton price history; panel 5 is from published accounts.")];
  nodes.push(yarnWhatIf(ins, list));

  if (p) {
    // 1. cost per metre by fabric type
    const top = Math.max(...p.categories.map(c => Math.max(c.paid, c.should)));
    const rows = p.categories.map(c => h("tr", {}, h("td", {}, h("b", {}, c.route), " · ", c.weave), h("td", { class: "cmp-cell" }, h("div", { class: "cmp-bars", "aria-hidden": "true" }, h("div", { class: "cmp-bar", style: `width:${c.paid / top * 100}%;background:var(--total)` }), h("div", { class: "cmp-bar", style: `width:${c.should / top * 100}%;background:var(--g1)` }))),
      h("td", { class: "n" }, fmt(c.paid, 0)), h("td", { class: "n" }, fmt(c.should, 0)), h("td", { class: "n" }, gapTag(c.gap, c.trust)), h("td", { class: "n" }, c.p25 === undefined ? "" : `${pctSigned(c.p25)} to ${pctSigned(c.p75)}`), h("td", { class: "n" }, pct(c.within10, 0)), h("td", { class: "n" }, fmt(c.fabrics, 0))));
    nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "1. Cost per metre by fabric type"), h("div", { class: "sub", style: "margin:2px 0 0" }, `${fmt(p.fabrics, 0)} 100% cotton fabrics bought Aug to Nov 2026, averaged over the metres bought; fabric types with fewer than 20 fabrics are left out, so the rows add up to less. Dark bar: price paid. Blue bar: should-cost. Plus means you paid above should-cost. Paid above should-cost is the average over the metres; the middle half is by fabric, half of them priced between the two figures. The average can sit outside the middle half when a few large orders were priced far from should-cost. Where the tool fits past prices poorly the gap is marked \u201Ctool unsure\u201D: it says more about the tool than about the price.`))),
      h("div", { class: "table-wrap tall" }, h("table", { class: "cmp" }, h("thead", {}, h("tr", {}, h("th", {}, "Fabric type"), h("th", { class: "cmp-cell" }, ""), h("th", { class: "n" }, "Paid Rs/m"), h("th", { class: "n" }, "Should-cost Rs/m"), h("th", { class: "n" }, "Paid above should-cost"), h("th", { class: "n", title: "Half of these fabrics were priced between these two figures against should-cost; one in four above the higher, one in four below the lower. The negotiation brief treats this range (at least 5% and at most 10% either way) as in line" }, "Middle half of fabrics"), h("th", { class: "n", title: "Share of these fabrics where the should-cost is within 10% of the price paid" }, "Tool within 10%"), h("th", { class: "n" }, "Fabrics"))), h("tbody", {}, rows))),
      h("p", { class: "sub", style: "margin:10px 0 0" }, "Poly cotton and linen are not here: there are no costed purchases of them yet.")));

    // 2. where the rupee goes
    const names = p.split[0].shares.map(s => s.name);
    const bars = p.split.map(sp => { const conv = 1 - sp.shares[0].share; const seg = sp.shares.filter(s => s.share > 0.0005).map(s => { const i = names.indexOf(s.name); const el = h("div", { class: "stack-seg", tabindex: "0", style: `width:${s.share * 100}%;background:var(${GROUP_COLOR[i % 8]})` }, s.share > 0.06 ? h("span", {}, pct(s.share, 0)) : null); withTip(el, () => `<b>${s.name}</b>${pct(s.share)} of the should-cost of ${sp.route.toLowerCase()} fabrics`); return el; });
      return h("div", { class: "stack-row" }, h("div", { class: "stack-name" }, h("b", {}, sp.route), h("small", {}, `${fmt(sp.fabrics, 0)} fabrics · median Rs ${fmt(sp.median_cost, 0)}/m`)), h("div", { class: "stack", role: "img", "aria-label": `${sp.route}: ` + sp.shares.map(s => `${s.name} ${pct(s.share, 0)}`).join(", ") }, seg), h("div", { class: "stack-note num" }, `conversion ${pct(conv, 0)}`)); });
    const tbl = { columns: ["Cost group", ...p.split.map(s => s.route)], rows: names.map(n => [n, ...p.split.map(sp => pct((sp.shares.find(s => s.name === n) || { share: 0 }).share))]) };
    nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "2. Where the rupee goes, by process"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Share of the should-cost, which is the tool's estimate, not the mill's accounts. Yarn, dyeing and weaving rest on rates and purchase prices; losses, overhead and margin are the percentages assumed in the rate master. Conversion is everything except yarn: what the mill adds, and where negotiation has room."))),
      h("div", { class: "stacks" }, bars), h("div", { class: "legend", "aria-hidden": "true" }, names.map((n, i) => h("span", {}, h("i", { style: `background:var(${GROUP_COLOR[i % 8]})` }), n))),
      h("details", { style: "margin-top:12px" }, h("summary", { style: "cursor:pointer;color:var(--muted)" }, "The same as a table"), h("div", { style: "margin-top:8px" }, dataTable(tbl, { label: "Share of should-cost by cost group and route" })))));
  } else nodes.push(h("div", { class: "notice info" }, "Panels 1 and 2 need the pilot results, which are not on this server."));

  // 3. the trend there is data for: cotton
  const yrs = ins.cotton_years.filter(y => y.year >= 2022), ytop = Math.max(...yrs.map(y => y.average), 1), last = yrs[yrs.length - 1];
  nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "3. Cost trend, 2022 to 2026: cotton"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Shankar-6 cotton, average of the year, rupees per candy. Cotton is the trend the tool has data for; the yarn rates are of one date (Nov 2026), so a fabric cost per metre for earlier years cannot be drawn yet."))),
    h("div", { class: "bars" }, yrs.map((y, i) => { const prev = yrs[i - 1]; const chg = prev ? y.average / prev.average - 1 : null; const el = h("div", { class: "bar-row grp", tabindex: "0" }, h("span", { class: "year num" }, String(y.year)), h("div", { class: "bar", style: `width:${y.average / ytop * 56}%;background:var(--g1)` }), h("span", { class: "bar-text" }, h("span", { class: "bar-amt num" }, `Rs ${fmt(y.average, 0)}`), chg === null ? null : h("span", { class: "bar-pct num" }, `${pctSigned(chg * 100)} on ${prev.year}`), y === last ? h("span", { class: "bar-pct" }, `to ${day(y.to)}`) : null)); withTip(el, () => `<b>${y.year}</b>average Rs ${fmt(y.average, 0)} per candy<br>low Rs ${fmt(y.low, 0)}, high Rs ${fmt(y.high, 0)}`); return el; })),
    h("p", { class: "sub", style: "margin:10px 0 0" }, "To see what a yarn move does to a fabric, use “If yarn prices move” above, or on Cost a fabric. ", h("a", { href: "#cotton" }, "Cotton prices in full"))));

  nodes.push(askCard(ins));

  // 5. supplier cost ratios, and suppliers against should-cost
  const sup = p ? h("div", { class: "table-wrap tall" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Supplier"), h("th", { class: "n" }, "Fabrics costed"), h("th", { class: "n" }, "Paid above should-cost, middle fabric"), h("th", { class: "n" }, "Tool within 10%"), h("th", {}, "Mostly buys"))),
    h("tbody", {}, p.suppliers.map(s => h("tr", {}, h("td", {}, s.supplier), h("td", { class: "n" }, String(s.fabrics)), h("td", { class: "n" }, gapTag(s.gap, s.trust)), h("td", { class: "n" }, pct(s.within10, 0)), h("td", {}, `${s.mostly} (${pct(s.mostly_share, 0)})`)))))) : null;
  nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "5. Supplier cost ratios, % of sales")),
    h("p", { class: "sub" }, "Whole-company figures from published accounts; they include yarn, garments and other businesses. Operating profit shows how much room a supplier has."),
    dataTable(ins.benchmarks, { label: "Supplier cost ratios" }),
    sup ? h("div", { style: "margin-top:16px" }, h("h3", {}, "Your purchases from each supplier, against should-cost"), sup) : null));
  return nodes;
};

/* What to ask before a negotiation, from the buyer's chair. The answers quote the buyer's own figures. */
function askCard(ins) {
  const p = ins.pilot, ref = ins.reference, q = ins.card.quantity, col = n => q.columns.indexOf(n);
  const small = q.rows.filter(r => r[col("Small-lot upcharge %")] > 0).map(r => `${r[col("Quantity band")]} +${r[col("Small-lot upcharge %")]}%`).join(", ");
  const disc = q.rows.filter(r => r[col("Volume discount Rs per metre")] > 0).map(r => `${r[col("Quantity band")]} −Rs ${r[col("Volume discount Rs per metre")]}`).join(", ");
  const share = ref.yarn_share;
  const firm = p ? p.suppliers.filter(s => s.gap > 5 && s.trust === "firm").sort((a, b) => b.gap - a.gap) : [];
  const unsure = p ? p.suppliers.filter(s => s.gap > 5 && s.trust === "weak").sort((a, b) => b.gap - a.gap) : [];
  const above = firm.map(s => `${s.supplier} ${pctSigned(s.gap)} on ${s.fabrics} fabrics`).join(", ");
  const qty = p ? p.quantity.filter(x => x.paid).map(x => `${x.band}: Rs ${fmt(x.paid, 0)}`).join("; ") : "";
  const items = [
    ["What should this fabric cost, and how sure is the figure?", `Cost it on Cost a fabric, or load the mill's sheet under Bulk upload. ${p ? `Across ${fmt(p.fabrics, 0)} of your cotton purchases the should-cost lands within 10% of the price paid for ${pct(p.within10, 0)} of fabrics, with a median gap of ${pctSigned(p.median_gap)}.` : ""} What counts as in line depends on the fabric type: the negotiation brief uses the range where half your past purchases of that type were priced (panel 1, middle half), kept between 5% and 10% either way.`],
    ["The mill says yarn has gone up. How much should the fabric go up?", `Not by the same percentage. On the reference shirting 5% on yarn is about ${(share * 5).toFixed(1)}% on the fabric, and each Rs 10 a kilo is ${rs(ref.warp_per_10 + ref.weft_per_10)} a metre for warp and weft together. Ask which count went up, from what rate to what, and on what date; then move that yarn in “If yarn prices move”.`],
    ["What is the base price, for which construction, and what do I pay for each extra end and pick?", "Ask for the standard EPI and PPI behind the base price. On Arvind's rate card an extra end is Rs 0.60 and an extra pick Rs 0.90 (Rs 1.00 above 90 picks); on their sheet the base for 40s yarn dyed twill is Rs 164 at 122 \u00D7 76. Other mills will have their own figures: ask for them in the same form. The list under Bulk upload checks every row of a mill's sheet: base plus upcharges must equal the price."],
    ["Am I paying for a small order, or missing a volume discount?", `Arvind's rate card adds ${small || "a percentage"} for yarn dyed lots below 800 m, and takes off ${disc || "a few rupees"} a metre for volume. The card gives no volume discount on its basic 40s quality, split deliveries or end-of-season orders. ${qty ? `Your median price paid by order size: ${qty}.` : ""} Ask whether lots of the same fabric code can be clubbed to reach the next band.`],
    ["Which finish, print and dobby charges are in the price?", `Ask for each as its own line. Arvind's card: rotary print Rs ${ins.card.print.Rotary}, digital Rs ${ins.card.print.Digital} a metre; dobby 9 to 12 shafts Rs 8, 13 and above Rs 10, top beam Rs 10; ETI or Easy Care Rs 4, liquid ammonia Rs 10. A charge with no process behind it is the first to challenge.`],
    ["Which suppliers are above should-cost?", (above ? `More than 5% above should-cost, where the tool fits well: ${above}.` : "No supplier is more than 5% above should-cost on fabrics where the tool fits well.") + (unsure.length ? ` Also above, but the tool fits this supplier's own fabrics poorly, so ask for the break-up before raising it: ${unsure.map(s => `${s.supplier} ${pctSigned(s.gap)} (mostly ${s.mostly}; the tool is within 10% on ${pct(s.within10, 0)} of its fabrics)`).join(", ")}.` : "") + " Panel 5 has every supplier."],
    ["What break-up should I ask the mill for?", "Yarn count and rate per kilo for warp and weft; wastage per cent; weaving charge per pick; dyeing per kilo; finish; process loss; overhead and margin. With those seven the gap between the quote and the should-cost can be put on one line, instead of argued as a total."],
    ["Is there a financing charge in the price?", "The mill's sheet carries an early-payment column (C2FO at 2.84%). Compare ex-mill prices, not the financed ones, and decide the payment terms separately."],
    ["Where is the tool's figure weak, so I do not push on the wrong point?", `${ins.placeholders} rates are placeholders, mostly finishes; the cost view says so whenever one is used. Yarn dyed plain is over-costed by about 10% (most of it is in Amsler or slub yarn), and printed twill and plain by more. Poly cotton and linen run on placeholder yarn rates. On those, ask for the break-up before quoting a number.`],
  ];
  return h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "4. Ask before you negotiate"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Questions from the buyer's side, each answered with your own figures."))),
    h("div", { class: "asks" }, items.map(([qn, an], i) => h("details", { class: "ask", open: i === 0 || null }, h("summary", {}, qn), h("p", {}, an)))));
}

// ------------------------------------------------------------------ cost a fabric
const GROUP_COLOR = ["--g1", "--g2", "--g3", "--g4", "--g5", "--g6", "--g7", "--g8"];
const NUM_FIELDS = ["EPI", "PPI", "Finished width (in)", "Reed space (in)", "Quoted price (Rs/m)", "Extra charge (Rs/m)", "Weaving rate override (Rs/pick)"];
const contentOfYarn = key => (state.meta.yarns.find(y => y.key === key) || {}).content;
function blankSel() { return { Content: "", Route: "" }; }
function exampleSel() {
  const ex = state.meta.example;
  return Object.assign(blankSel(), ex, { Content: contentOfYarn(ex["Warp yarn"]) || state.meta.contents[0], "Weft (yarn dyed)": state.meta.lists["Weft (yarn dyed)"][0] });
}
function selFromRow(row) {          // a bulk upload row opened in the cost view
  const s = Object.assign(blankSel(), Object.fromEntries(Object.entries(row).filter(([, v]) => !blank(v))));
  s.Content = contentOfYarn(s["Warp yarn"]) || state.meta.contents[0];
  return s;
}
// what each route asks for in the colouring step; anything else is not shown and not sent
const ROUTE_FIELDS = { "Yarn Dyed": ["Warp yarn dyeing", "Weft (yarn dyed)", "Weft yarn dyeing", "Print method"], "Piece Dyed": ["Piece shade"], "Printed": ["Print method"], "RFD / Bleached": [] };
const yarnText = (sel, side) => blank(sel[side + " count"]) ? sel[side + " yarn"] : `${sel[side + " yarn"]} typed as ${sel[side + " count"]} ${String(sel["Count system"] || "English count (Ne)").replace(/ count| \(linen\)/g, "")}`;
const COUNT_TO_NE = { "English count (Ne)": v => v, "Metric count (Nm)": v => v / 1.6934, Tex: v => 590.5 / v, Denier: v => 5315 / v, "Lea (linen)": v => v * 300 / 840, "Worsted count (Nw)": v => v * 560 / 840 };
const NE_TO_COUNT = { "English count (Ne)": v => v, "Metric count (Nm)": v => v * 1.6934, Tex: v => 590.5 / v, Denier: v => 5315 / v, "Lea (linen)": v => v * 840 / 300, "Worsted count (Nw)": v => v * 840 / 560 };
function fieldOn(sel, name) {
  const L = state.meta.lists, first = n => L[n][0];
  if (["Warp yarn dyeing", "Weft (yarn dyed)", "Weft yarn dyeing", "Piece shade", "Print method"].includes(name)) {
    if (!(ROUTE_FIELDS[sel.Route] || []).includes(name)) return false;
    if (name === "Weft yarn dyeing") return (sel["Weft (yarn dyed)"] || first("Weft (yarn dyed)")) === first("Weft (yarn dyed)");
    return true;
  }
  if (name === "Dobby shafts" || name === "Top beam") return state.meta.weave_group[sel.Weave] === "Dobby/Matt";
  if (name === "Order size") return (sel["Rate card quantity"] || first("Rate card quantity")) === first("Rate card quantity");
  return true;
}
// what /api/cost is sent: the choices, plus the remarks of the list row the fabric was opened from
const costBody = sel => Object.assign(payload(sel), state.listId && state.rowNotes && state.rowNotes.length ? { _notes: state.rowNotes } : {});
function payload(sel) {
  const out = {};
  for (const [k, v] of Object.entries(sel)) if (!blank(v) && fieldOn(sel, k)) out[k] = v;
  return out;
}
const STEPS = [
  { id: "fabric", title: "Fabric", need: "Choose the fabric", done: s => !!s.Content, sum: s => s.Content },
  { id: "route", title: "How it is coloured", need: "Choose yarn dyed, piece dyed, bleached or printed", done: s => !!s.Route, sum: s => s.Route },
  { id: "yarn", title: "Yarn", need: "Choose the warp and weft yarn", done: s => !!s["Warp yarn"] && !!s["Weft yarn"], sum: s => `${yarnText(s, "Warp")} \u00D7 ${yarnText(s, "Weft")}` },
  { id: "dye", title: s => ({ "Yarn Dyed": "Yarn dyeing", "Piece Dyed": "Piece dyeing", Printed: "Printing", "RFD / Bleached": "Bleaching" }[s.Route] || "Dyeing"), done: () => true, sum: s => [["Warp yarn dyeing", "warp "], ["Weft (yarn dyed)", "weft "], ["Weft yarn dyeing", "weft shade "], ["Piece shade", ""], ["Print method", "print: "]].filter(([f]) => fieldOn(s, f) && s[f]).map(([f, p]) => p + s[f]).join(" \u00B7 ") },
  { id: "cons", title: "Weave and construction", need: "Choose the weave and type EPI, PPI and width", done: s => !!s.Weave && s.EPI > 0 && s.PPI > 0 && s["Finished width (in)"] > 0, sum: s => `${s.Weave} · ${s.EPI} × ${s.PPI} · ${s["Finished width (in)"]} in` },
  { id: "finish", title: "Finish, mill and order", done: () => true, sum: s => [s.Finish, fieldOn(s, "Order size") ? s["Order size"] : s["Rate card quantity"]].filter(Boolean).join(" \u00B7 ") },
  { id: "name", title: "Name and compare (optional)", done: () => true, sum: s => [s["Fabric code"], s["Quoted price (Rs/m)"] ? "quote Rs " + s["Quoted price (Rs/m)"] : ""].filter(Boolean).join(" \u00B7 ") },
];
const ready = sel => STEPS.every(st => st.done(sel));

PAGES.cost = async () => {
  const L = state.meta.lists, M = state.meta;
  if (!state.sel) state.sel = blankSel();
  const sel = state.sel;
  const flow = h("div", { class: "flow" }), out = h("div", { class: "cost-out", "aria-live": "polite" });

  let timer, last = 0;
  const recalc = () => {
    clearTimeout(timer);
    if (!ready(sel)) { ++last; return out.replaceChildren(waiting(sel)); }
    timer = setTimeout(async () => {
      const mine = ++last;
      try { const res = await (await postJSON("/api/cost", costBody(sel))).json(); if (mine === last) out.replaceChildren(...costView(res, sel)); }
      catch (e) { if (mine === last) { const old = out.querySelector(".cannot"); if (old) old.remove(); out.prepend(h("div", { class: "notice err cannot", role: "alert", style: "margin-top:0" }, h("b", {}, "Cannot cost this as typed: "), e.message + (out.children.length ? " The figures below are from before this change." : ""))); } }
    }, 160);
  };
  const doneNow = () => STEPS.map(st => st.done(sel));
  const advance = before => {            // the open step has just been finished: fold it and open the next
    const after = doneNow(), i = STEPS.findIndex(st => st.id === state.openStep);
    if (i >= 0 && !before[i] && after[i] && i < STEPS.length - 1) { state.openStep = STEPS[i + 1].id; return true; }
    return false;
  };
  const set = (name, value, repaint = true) => {
    if (!["Fabric code", "Description", "Supplier", "Quoted price (Rs/m)", "Order quantity (m)"].includes(name)) state.reopened = null;      // once a costed choice changes, it is no longer the costing that was saved
    const before = doneNow();
    if (name === "Count system") {          // the same yarn, written in the new system: the typed numbers follow
      const from = COUNT_TO_NE[sel["Count system"] || "English count (Ne)"], to = NE_TO_COUNT[value];
      for (const f of ["Warp count", "Weft count"]) if (!blank(sel[f]) && sel[f] > 0 && from && to) sel[f] = Number(to(from(sel[f])).toPrecision(6));
    }
    sel[name] = value;
    if (name === "Content") { let cleared = false; for (const y of ["Warp yarn", "Weft yarn"]) if (sel[y] && contentOfYarn(sel[y]) !== value) { sel[y] = ""; cleared = true; } if (cleared) toast(`Yarn cleared: choose a ${value.toLowerCase()} yarn in step 3`); }
    if (name === "Route") {                    // each route starts from its own defaults
      // choices made for another route are kept, out of sight, in case the buyer comes back to it
      const fill = (f, v) => { if (blank(sel[f])) sel[f] = v; };
      if (value === "Yarn Dyed") { fill("Warp yarn dyeing", "Medium"); fill("Weft yarn dyeing", "Medium"); fill("Weft (yarn dyed)", L["Weft (yarn dyed)"][0]); }
      if (value === "Piece Dyed") fill("Piece shade", "Medium");
      if (value !== "Yarn Dyed" && M.small_lot_bands.includes(sel["Rate card quantity"])) { sel["Rate card quantity"] = L["Rate card quantity"][0]; toast("Quantity band cleared: bands below 800 m are for yarn dyed fabrics only"); }
    }
    if (name === "Warp yarn" && !sel["Weft yarn"]) sel["Weft yarn"] = value;      // most fabrics use one yarn both ways
    const moved = repaint && (name === "Content" || name === "Route") && advance(before);     // a chip finishes its step; elsewhere "Next" moves on
    if (repaint) paint(moved ? null : name, moved);
    recalc();
  };

  // --- field builders
  const idOf = n => "f-" + n.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
  const wrap = (name, label, input, hint, wide) => h("div", { class: "field" + (wide ? " wide" : "") }, h("label", { for: idOf(name) }, label || name), input, hint ? h("span", { class: "hint" }, hint) : null);
  const pick = (name, list, o = {}) => {
    const opts = (o.options || L[list]).map(v => typeof v === "string" ? { value: v, text: v } : v);
    if (blank(sel[name]) && !o.blank) sel[name] = opts[0].value;
    const input = h("select", { id: idOf(name) }, o.blank ? h("option", { value: "" }, o.blank) : null, opts.map(v => h("option", { value: v.value, disabled: v.disabled || null }, v.text)));
    input.value = sel[name] ?? "";
    input.addEventListener("change", () => set(name, input.value));
    return wrap(name, o.label, input, o.hint, o.wide);
  };
  const typed = (name, o = {}) => {
    const input = h("input", { id: idOf(name), type: o.text ? "text" : "number", value: sel[name] ?? "", step: o.step || (o.text ? null : "any"), min: o.text ? null : "0", inputmode: o.text ? null : "decimal", placeholder: o.placeholder });
    let wasDone = doneNow();
    input.addEventListener("input", () => { set(name, o.text ? input.value : (input.value === "" ? "" : Number(input.value)), false); });
    input.addEventListener("change", () => {      // typing finished (or unfinished) the step: unlock what follows, keep the buyer where they are
      const before = wasDone.join(); wasDone = doneNow();
      if (wasDone.join() !== before) setTimeout(() => { const id = document.activeElement && document.activeElement.id; paint(); const el = id && document.getElementById(id); if (el) el.focus({ preventScroll: true }); }, 0);
    });
    return wrap(name, o.label, input, o.hint, o.wide);
  };
  const chipset = (name, values, label) => h("div", { class: "field wide" }, h("span", { class: "lbl", id: idOf(name) + "-l" }, label),
    h("div", { class: "chips", role: "group", "aria-labelledby": idOf(name) + "-l" }, values.map(v => h("button", { type: "button", class: "chip", "aria-pressed": String(sel[name] === v), "data-v": v, onclick: () => set(name, v) }, v))));
  const yarnOptions = () => M.yarns.filter(y => y.content === sel.Content).map(y => ({ value: y.key, text: `${y.key} · Rs ${fmt(y.rate, 0)}/kg${y.basis.startsWith("Placeholder") ? " · placeholder" : ""}` }));

  const bodies = {
    fabric: () => [chipset("Content", M.contents, "Fabric content"),
      sel.Content && sel.Content !== M.contents[0] ? h("div", { class: "notice wide", style: "margin:0" }, "Yarn rates for this content are placeholders, and the weaving, dyeing and finishing rates were measured on 100% cotton. Treat the cost as provisional.") : null],
    route: () => [chipset("Route", L.Route, "Route")],
    yarn: () => { const opts = yarnOptions(); return opts.length ? [pick("Warp yarn", null, { options: opts, blank: "Choose...", wide: true }), pick("Weft yarn", null, { options: opts, blank: "Choose...", wide: true }),
      h("details", { class: "wide more", open: state.countOpen || !blank(sel["Warp count"]) || !blank(sel["Weft count"]) || null, ontoggle: e => { state.countOpen = e.target.open; } }, h("summary", {}, "Type a different count (optional)"),
        h("div", { class: "fields", style: "margin-top:10px" }, pick("Count system", "Count system", { wide: true, hint: "Ne for cotton, lea for linen, denier for filament" }),
          typed("Warp count", { hint: "Blank = the yarn's own" }), typed("Weft count", { hint: "Blank = the yarn's own" }),
          h("p", { class: "sub wide", style: "margin:0;font-size:12px" }, "A typed count changes the weight of yarn in the cloth. The rate per kg stays that of the yarn chosen above.")))] : [h("div", { class: "notice wide", style: "margin:0" }, "No yarn of this content is in the yarn master yet. Add one under Yarn prices.")]; },
    dye: () => {
      const f = [];
      if (fieldOn(sel, "Warp yarn dyeing")) f.push(pick("Warp yarn dyeing", "Yarn shade", { label: "Warp shade" }));
      if (fieldOn(sel, "Weft (yarn dyed)")) f.push(pick("Weft (yarn dyed)", "Weft (yarn dyed)", { label: "Weft: dyed or undyed" }));
      if (fieldOn(sel, "Weft yarn dyeing")) f.push(pick("Weft yarn dyeing", "Yarn shade", { label: "Weft shade" }));
      if (fieldOn(sel, "Piece shade")) f.push(pick("Piece shade", "Piece shade"));
      if (fieldOn(sel, "Print method")) f.push(pick("Print method", "Print method", sel.Route === "Printed" ? { hint: "Not selected = the calibrated printing rate per kg. Rotary or Digital uses the mill rate card instead", wide: true } : { label: "Print over the cloth", hint: "Leave at Not selected for no print" }));
      return f.length ? f : [h("p", { class: "sub wide", style: "margin:0" }, "Bleached only: nothing to choose here.")];
    },
    cons: () => [pick("Weave", "Weave", { blank: "Choose..." }), pick("Pattern", "Pattern", { hint: "No price uplift is set for any pattern yet" }),
      typed("EPI", { label: "Ends per inch (EPI)" }), typed("PPI", { label: "Picks per inch (PPI)" }), typed("Finished width (in)", { label: "Finished width (inch)" }), typed("Reed space (in)", { label: "Reed space (inch)", hint: "Blank = from width" }),
      fieldOn(sel, "Dobby shafts") ? pick("Dobby shafts", "Dobby shafts") : null, fieldOn(sel, "Top beam") ? pick("Top beam", "Top beam") : null],
    finish: () => [pick("Finish", "Finish", { wide: true }), pick("Loom type", "Loom type"), pick("Mill tier", "Mill tier"),
      pick("Rate card quantity", null, { label: "Quantity band (mill rate card)", hint: "When set, used instead of Order size", options: L["Rate card quantity"].map(v => ({ value: v, text: v, disabled: sel.Route !== "Yarn Dyed" && M.small_lot_bands.includes(v) })) }),
      fieldOn(sel, "Order size") ? pick("Order size", "Order size", { label: "Order size (pilot slabs)" }) : null],
    name: () => [typed("Fabric code", { text: true }), typed("Supplier", { text: true }), typed("Description", { text: true, wide: true }),
      typed("Quoted price (Rs/m)", { label: "Supplier's quote (Rs/m)" }), typed("Order quantity (m)", { hint: "Shows the money at stake" }), typed("Extra charge (Rs/m)", { wide: true }), typed("Weaving rate override (Rs/pick)", { step: "0.01", wide: true, hint: "Blank = use the rate table" })],
  };

  /* One step is open at a time. A finished step folds to a line that says what was chosen;
     clicking it opens it again. A step cannot be opened before the ones above it are done. */
  const paint = (focusName, moved) => {
    let reachable = true;
    if (!state.openStep || !STEPS.some(st => st.id === state.openStep)) state.openStep = (STEPS.find(st => !st.done(sel)) || {}).id || null;
    flow.replaceChildren(...STEPS.map((st, i) => {
      const title = typeof st.title === "function" ? st.title(sel) : st.title;
      const open = reachable && state.openStep === st.id;
      if (open) state.visited.add(st.id);
      const mine = reachable, done = mine && st.done(sel) && (!!st.need || state.visited.has(st.id));
      if (mine && !st.done(sel)) reachable = false;
      const sum = mine && st.done(sel) && !open ? ((done ? "" : "default: ") + st.sum(sel)).replace(/^default: $/, "") : "";
      const head = [h("span", { class: "step-n", "aria-hidden": "true" }, done ? "\u2713" : String(i + 1)), h("h2", {}, title), sum ? h("span", { class: "step-sum" }, sum) : null, mine ? h("span", { class: "step-caret", html: svg('<path d="m6 9 6 6 6-6"/>', 14) }) : null];
      const next = STEPS[i + 1];
      return h("section", { class: "step" + (mine ? "" : " locked") + (done ? " done" : "") + (open ? " open" : ""), "aria-label": `Step ${i + 1}: ${title}` },
        mine ? h("button", { type: "button", class: "step-head", "aria-expanded": String(open), "data-step": st.id, onclick: () => { state.openStep = open ? null : st.id; paint(null, true); } }, head) : h("div", { class: "step-head" }, head),
        open ? h("div", { class: "fields" }, bodies[st.id](), next && st.done(sel) ? h("div", { class: "wide" }, h("button", { type: "button", class: "btn small", onclick: () => { state.openStep = next.id; paint(null, true); } }, "Next: " + (typeof next.title === "function" ? next.title(sel) : next.title))) : null) : null);
    }));
    if (focusName) { const el = flow.querySelector(`[data-v="${CSS.escape(String(sel[focusName] ?? ""))}"]`) || $("#" + idOf(focusName), flow); if (el) el.focus({ preventScroll: true }); }
    else if (moved) { const el = flow.querySelector(".step.open .fields button, .step.open .fields select, .step.open .fields input") || flow.querySelector(`[data-step="${state.openStep}"]`); if (el) el.focus({ preventScroll: true }); const sec = flow.querySelector(".step.open"); if (sec) sec.scrollIntoView({ block: "nearest" }); }
  };
  state.setChoice = (name, value) => { set(name, value); };
  paint(); recalc();

  const actions = h("div", { class: "row-actions", style: "margin:0" },
    h("button", { class: "btn small", type: "button", onclick: () => { state.sel = blankSel(); state.listId = null; state.rowNotes = null; state.sim = null; state.reopened = null; state.openStep = null; state.visited.clear(); route(); } }, "New fabric"),
    h("button", { class: "btn small", type: "button", onclick: () => { state.sel = exampleSel(); state.listId = null; state.rowNotes = null; state.sim = null; state.reopened = null; state.openStep = null; STEPS.forEach(st => state.visited.add(st.id)); route(); } }, "Load the example"));
  // the two panes take exactly the height left on the screen, so the page itself does not scroll
  const split = h("div", { class: "cost-split" }, h("div", { class: "pane pane-in", role: "form", "aria-label": "Fabric inputs" }, flow), h("div", { class: "pane pane-out" }, out));
  const fit = () => { if (!split.isConnected) return removeEventListener("resize", fit); split.style.height = innerWidth > 1000 ? Math.max(420, innerHeight - split.getBoundingClientRect().top - scrollY - 14) + "px" : ""; };
  addEventListener("resize", fit); requestAnimationFrame(fit); setTimeout(fit, 300);
  split.firstChild.prepend(h("div", { class: "pane-head" }, h("h1", {}, "Cost a fabric"), actions));
  return [h("p", { class: "sub cost-intro" }, "Work down the steps on the left; each choice decides what the next step asks. The cost on the right updates as you go."), split];
};

/* The negotiation brief: what to say about one quote. Where the tool is unsure of this kind of fabric it
   gives no target and says to ask for the break-up instead. Every figure is compared as printed, so the
   sums can be checked on the page. */
const STANCE = { check: ["warn", "Check the quote first: it is more than 30% below should-cost"], push: ["down", "Push: the quote is above the usual range"], fair: ["flat", "Fair: in line with the usual range"], below: ["up", "Below should-cost: a saving, if the specification holds"], ask: ["warn", "Ask for the break-up before naming a price"] };
// the stance of a row once its gap has moved (a yarn move on the list): the same range, the new gap
const stanceFor = (b, gapPct) => b.stance === "ask" ? "ask" : gapPct > b.band.hi + 1e-9 ? "push" : gapPct < b.band.lo - 1e-9 ? "below" : "fair";
function briefCard(b, sel, moved) {
  const w = b.would_need, above = b.gap > 0, st = b.implausible ? ["warn", "Check the quote first"] : STANCE[b.stance];
  const lines = [], gapText = `${rs(Math.abs(b.gap))} (${pct(Math.abs(b.gap_pct))}) ${b.gap > 0 ? "above" : b.gap < 0 ? "below" : "at"} should-cost`;
  const band = `${rs(b.lower)} to ${rs(b.settle_up_to)}`;
  for (const c of b.caveats || []) lines.push(h("li", { class: "caveat" }, h("b", {}, "Before you use these figures: "), c));
  if (b.stance === "ask") {
    if (b.qty_only) lines.push(h("li", {}, h("b", {}, "Set the quantity first. "), b.weak[0].charAt(0).toUpperCase() + b.weak[0].slice(1) + ". Change it in step 6, and the brief will give a stance."));
    else lines.push(h("li", {}, h("b", {}, "Do not open with a number. "), "The should-cost is not firm here: " + b.weak.join("; ") + ". Ask for yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish and margin, then cost it again."));
    if (b.qty_fix && state.setChoice) lines.push(h("li", {}, h("button", { type: "button", class: "btn small", onclick: () => state.setChoice(b.qty_fix.field, b.qty_fix.value) }, `Set ${b.qty_fix.field === "Order size" ? "the order size" : "the quantity band"} to ${b.qty_fix.value}`), " to cost it on the quantity typed."));
  } else if (b.stance === "push") lines.push(h("li", {}, h("b", {}, `Open at ${rs(b.open_at)} a metre and aim to settle at ${rs(b.settle_up_to)}, the top of the usual range. `), `The usual range for this fabric is ${band}: ${b.band.why}. The quote is ${rs(b.above_band)} above its top; ask the mill to show where that comes from. ` + (b.open_at > b.should + 0.005 ? `The opening figure is as far below the top of the range as the quote is above it, so it moves with the quote; it never goes below the should-cost, ${rs(b.should)}, which is where it stops once the quote is ${rs(b.settle_up_to - b.should)} or more above the range.` : `The opening figure is the should-cost: the quote is so far above the range that the mill has to justify all of the gap.`)));
  else if (b.stance === "fair") lines.push(h("li", {}, h("b", {}, "The quote is in line. "), `It is ${gapText}, inside the usual range of ${band}: ${b.band.why}. Use the time on quantity terms, finish and delivery instead.`));
  else if (b.implausible) lines.push(h("li", {}, h("b", {}, "Check the quote first. "), `It is ${gapText}. No saving is counted until the quote is confirmed for this cloth, per metre.`));
  else lines.push(h("li", {}, h("b", {}, "The quote is below the usual range: a saving, if the specification holds. "), `It is ${gapText}; the usual range is ${band}. Before taking it, confirm the yarn, the construction and the finish are the ones costed here: a low price sometimes means a lighter cloth or a different yarn.`));
  if (above && (b.stance === "push" || b.stance === "ask")) {
    const parts = [], about = v => `about ${v}`;
    const phNote = " (the tool's own rate here is a placeholder, so ask for the mill's figure)";
    if (w.yarn) {
      const same = Math.abs(w.yarn.weft_now - w.yarn.warp_now) < 0.5;
      const t = same ? `warp and weft yarn both cost ${about("Rs " + fmt(w.yarn.warp, 0))} a kilo` + (w.yarn.placeholder ? phNote : `, not Rs ${fmt(w.yarn.warp_now, 0)}`)
        : `warp yarn costs ${about("Rs " + fmt(w.yarn.warp, 0))} a kilo and weft yarn ${about("Rs " + fmt(w.yarn.weft, 0))}` + (w.yarn.placeholder ? phNote : `, not Rs ${fmt(w.yarn.warp_now, 0)} and Rs ${fmt(w.yarn.weft_now, 0)}`);
      parts.push(h("li", {}, `${t} (${pctSigned(w.yarn.pct, 1)})`));
    }
    parts.push(h("li", {}, `or weaving is ${about("Rs " + w.weaving.rate.toFixed(3))} a pick` + (w.weaving.placeholder ? phNote : `, not Rs ${w.weaving.now.toFixed(3)}`) + ` (the gap less the losses, overhead and margin the mill adds on it is ${rs(w.weaving.per_m_before)} a metre, over ${fmt(w.weaving.picks, 0)} picks)`));
    parts.push(h("li", {}, `or the mill's margin is ${about(pct(w.margin.rate, 1))}` + (w.margin.placeholder ? phNote : `, not ${pct(w.margin.now, 1)}`)));
    lines.push(h("li", {}, h("b", {}, `For the quote to be right, one of these would have to be true; each alone explains the whole ${rs(b.gap)} a metre: `), h("ul", {}, parts), "Ask which it is. Each can be checked: the yarn against the yarn master and the market, the others against the mill's own sheet."));
  }
  if (b.at_stake !== null && b.quantity && !b.implausible) {
    const amt = `Rs ${fmt(Math.abs(b.at_stake), 0)}`, per = `${fmt(b.quantity, 0)} m × ${rs(Math.abs(b.gap))} a metre`;
    lines.push(h("li", {}, b.gap > 0 ? [h("b", {}, `At stake: ${amt} `), `above should-cost (${per}).`] : b.gap < 0 ? [h("b", {}, `Saving against should-cost: ${amt} `), `(${per}).`] : [h("b", {}, "Nothing at stake: "), "the quote equals the should-cost."]));
  }
  const fit = b.fit ? h("p", { class: "sub", style: "margin:8px 0 0;font-size:12px" }, `On ${b.fit.type} the tool is within 10% of the price paid for ${pct(b.fit.within10, 0)} of ${fmt(b.fit.fabrics, 0)} fabrics bought; on average they were paid ${pctSigned(b.fit.gap)} against should-cost, and the middle half between ${pctSigned(b.fit.p25)} and ${pctSigned(b.fit.p75)} (dashboard panel 1).`) : null;
  return h("div", { class: "card brief" }, h("div", { class: "card-head", style: "margin-bottom:8px" }, h("h2", {}, "For the negotiation" + (moved ? ` · ${moved}` : "")), h("span", { class: "tag " + st[0] }, st[1])),
    h("p", { class: "sub", style: "margin:0 0 8px" }, `Quote ${rs(b.quote)}, should-cost ${rs(b.should)}: the quote is ${gapText}.`),
    h("ul", { class: "brief-list" }, lines), fit);
}

/* What a move in the yarn price does to this fabric. The sliders re-cost it with the warp and weft
   rates moved; nothing is saved and the rate master is untouched. */
function yarnSim(res, sel) {
  const y = res.yarn, sim = state.sim = state.sim || { warp: 0, weft: 0, both: true };
  const out = h("div", { class: "whatif-out", "aria-live": "polite" });
  let turn = 0, timer;
  const show = async () => {
    const mine = ++turn;
    const swapBrief = (b, label) => { const old = document.querySelector(".cost-out .brief"); if (old && b) old.replaceWith(briefCard(b, sel, label)); };
    const heroMoved = r => { const el = document.querySelector(".cost-out .hero-moved"); if (!el) return; el.hidden = !r; if (r) el.textContent = `With the yarn moved on the sliders below (warp Rs ${fmt(y.warp_rate * (1 + sim.warp / 100), 0)}/kg, weft Rs ${fmt(y.weft_rate * (1 + sim.weft / 100), 0)}/kg) the should-cost is ${rs(r.total_per_m)}` + (r.quote !== null ? `, and the quote is ${rs(Math.abs(r.gap))} (${pct(Math.abs(r.gap_pct))}) ${r.gap >= 0 ? "above" : "below"} it.` : "."); };
    if (!sim.warp && !sim.weft) { heroMoved(null); swapBrief(res.brief, null); return out.replaceChildren(h("span", { class: "sub", style: "margin:0" }, "Move a slider to see the price at a different yarn rate.")); }
    try {
      const body = Object.assign(costBody(sel), { "Warp yarn price override": y.warp_rate * (1 + sim.warp / 100), "Weft yarn price override": y.weft_rate * (1 + sim.weft / 100) });
      const r = await (await postJSON("/api/cost", body)).json(); if (mine !== turn) return;
      heroMoved(r);
      swapBrief(r.brief, sim.warp === sim.weft ? `with yarn ${pctSigned(sim.warp, 0)}` : `with warp ${pctSigned(sim.warp, 0)}, weft ${pctSigned(sim.weft, 0)}`);
      const d = r.total_per_m - res.total_per_m;
      out.replaceChildren(h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `Warp at Rs ${fmt(y.warp_rate * (1 + sim.warp / 100), 0)}/kg, weft at Rs ${fmt(y.weft_rate * (1 + sim.weft / 100), 0)}/kg`), h("b", { class: "num" }, `${rs(res.total_per_m)} \u2192 ${rs(r.total_per_m)}`), h("span", { class: "tag " + (d > 0.005 ? "down" : d < -0.005 ? "up" : "flat") }, `${d >= 0 ? "+" : "\u2212"}${fmt(Math.abs(d))} /m (${pctSigned(d / res.total_per_m * 100)})`),
        r.quote !== null ? h("span", { class: "sub", style: "margin:0" }, `the quote would be ${pct(Math.abs(r.gap_pct))} ${r.gap >= 0 ? "above" : "below"}`) : null));
    } catch (e) { if (mine === turn) out.replaceChildren(h("span", { class: "sub", style: "margin:0" }, e.message)); }
  };
  const row = (key, label, rate) => {
    const span = String(Math.max(20, Math.abs(sim.warp), Math.abs(sim.weft)));
    const slider = h("input", { type: "range", min: "-" + span, max: span, step: "1", value: String(sim[key]), id: "sim-" + key, "aria-label": label + " yarn price change, per cent" });
    const val = h("span", { class: "num simval" }, pctSigned(sim[key], 0));
    slider.addEventListener("input", () => { sim[key] = Number(slider.value); if (sim.both) { sim.warp = sim.weft = sim[key]; for (const k of ["warp", "weft"]) { $("#sim-" + k).value = sim[k]; $("#sim-" + k).nextSibling.textContent = pctSigned(sim[k], 0); } } else val.textContent = pctSigned(sim[key], 0); clearTimeout(timer); timer = setTimeout(show, 120); });
    return h("div", { class: "simrow" }, h("label", { for: "sim-" + key }, `${label} \u00B7 Rs ${fmt(rate, 0)}/kg`), slider, val);
  };
  const both = h("input", { type: "checkbox", id: "sim-both" }); both.checked = sim.both; both.addEventListener("change", () => { sim.both = both.checked; });
  show();
  return h("div", { class: "card whatif" }, h("div", { class: "card-head", style: "margin-bottom:8px" }, h("div", {}, h("h2", {}, "If yarn prices move"), h("div", { class: "sub", style: "margin:2px 0 0" }, `On this fabric 10% on yarn is about ${(y.yarn_share * 10).toFixed(1)}% on the price. Each Rs 10 a kilo on the warp is ${rs(y.warp_per_10)} a metre; on the weft, ${rs(y.weft_per_10)}.`)),
      h("div", { style: "display:flex;gap:12px;align-items:center" }, h("label", { for: "sim-both", class: "opt" }, both, "Move both together"), h("button", { class: "btn small", type: "button", onclick: () => { state.sim = null; const c = document.querySelector(".cost-out .whatif"); c.replaceWith(yarnSim(res, sel)); } }, "Reset"))),
    row("warp", "Warp", y.warp_rate), row("weft", "Weft", y.weft_rate), out);
}

/* A saved costing opened again is costed on today's rates. Say what it cost then, what it costs now,
   and which rates behind it have changed. */
function movedCard(res, re) {
  const then = re.then, diff = res.total_per_m - then.total_per_m, same = Math.abs(diff) < 0.005;
  const was = Object.fromEntries((then.rates || []).map(u => [u.Item, u]));
  const show = u => `${typeof u.Value === "number" ? fmt(u.Value, Math.abs(u.Value) < 10 ? 3 : 2).replace(/\.?0+$/, "") : u.Value}${u.Unit ? " " + u.Unit : ""}`;
  const rates = res.rates_used.filter(u => was[u.Item] && (String(was[u.Item].Value) !== String(u.Value) || String(was[u.Item].Choice) !== String(u.Choice)))
    .map(u => h("tr", {}, h("td", {}, u.Item), h("td", {}, show(was[u.Item])), h("td", {}, show(u)), h("td", { class: "wrap" }, String(was[u.Item].Choice) !== String(u.Choice) ? `${was[u.Item].Choice} \u2192 ${u.Choice}` : String(u.Choice))));
  const groupWas = Object.fromEntries(then.buckets.map(b => [b.name, b.amount]));
  const groups = res.buckets.filter(b => Math.abs(b.amount - (groupWas[b.name] ?? 0)) >= 0.005)
    .map(b => h("tr", {}, h("td", {}, b.name), h("td", { class: "n" }, fmt(groupWas[b.name] ?? 0)), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, (b.amount >= (groupWas[b.name] ?? 0) ? "+" : "") + fmt(b.amount - (groupWas[b.name] ?? 0)))));
  return h("div", { class: "card moved" },
    h("div", { class: "card-head", style: "margin-bottom:8px" }, h("h2", {}, `Since it was added on ${day(re.on)}`),
      h("span", { class: "tag " + (same ? "flat" : diff > 0 ? "down" : "up") }, same ? "no change" : `${diff > 0 ? "\u25B2" : "\u25BC"} ${rs(Math.abs(diff))} (${pct(Math.abs(diff) / then.total_per_m)}) ${diff > 0 ? "dearer" : "cheaper"}`)),
    h("p", { class: "sub", style: "margin:0 0 10px" }, same ? `It cost ${rs(then.total_per_m)} per metre then and costs the same on today's rates.` : `It cost ${rs(then.total_per_m)} per metre then and costs ${rs(res.total_per_m)} on today's rates.`),
    rates.length && !same ? h("div", { class: "table-wrap tall" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Rate that changed"), h("th", {}, "Then"), h("th", {}, "Now"), h("th", {}, "Choice"))), h("tbody", {}, rates))) : (same ? null : h("p", { class: "sub", style: "margin:0" }, "No single rate in the list differs; a table behind the costing (for example crimp, wastage or a setting) has changed.")),
    groups.length ? h("details", { style: "margin-top:10px" }, h("summary", { style: "cursor:pointer;color:var(--muted)" }, "By cost group, Rs per metre"), h("div", { class: "table-wrap tall", style: "margin-top:8px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Group"), h("th", { class: "n" }, "Then"), h("th", { class: "n" }, "Now"), h("th", { class: "n" }, "Change"))), h("tbody", {}, groups)))) : null);
}

function waiting(sel) {
  const todo = STEPS.filter(st => st.need);
  let reached = true;
  return h("div", { class: "card waiting" }, h("h2", {}, "The cost appears here"), h("p", { class: "sub" }, "Finish these steps on the left. Everything after them has a default you can change."),
    h("ol", { class: "todo" }, todo.map(st => { const ok = reached && st.done(sel); if (!ok) reached = false; return h("li", { class: ok ? "ok" : "" }, h("span", { "aria-hidden": "true" }, ok ? "✓" : "○"), " ", st.need, ok ? h("span", { class: "visually-hidden" }, " (done)") : null); })));
}

const CHARTS = [["bars", "Bars"], ["waterfall", "Waterfall"], ["pie", "Pie"], ["treemap", "Treemap"], ["line", "Line"]];
const CHART_NOTE = { bars: "One bar per cost, from zero, largest at the top. Best for seeing what matters most.", waterfall: "Each step starts where the one before ended. Best for seeing how the price builds up.", pie: "Each group's share of the price.", treemap: "Area is rupees per metre; sub-costs sit inside their group. Best for seeing where the money is.", line: "The running total after each step." };
function costView(res, sel) {
  const title = [[sel["Fabric code"], sel.Description].filter(v => !blank(v)).join(" \u2014 "), sel.Supplier].filter(v => !blank(v)).join(" \u00B7 ");
  let quote = null;
  if (res.quote !== null) {
    const above = res.gap >= 0;
    quote = h("div", { class: "quote" }, h("span", { class: "tag " + (above ? "down" : "up") }, `${above ? "▲" : "▼"} Quote ${rs(res.quote)}/m is ${rs(Math.abs(res.gap))} (${pct(Math.abs(res.gap_pct))}) ${above ? "above" : "below"} should-cost`));
  }
  const hero = h("div", { class: "card hero" },
    h("div", { class: "hero-row" },
      h("div", {}, h("div", { class: "lbl" }, title ? title + " · " : "", "ex-mill should-cost"), h("div", { class: "big num" }, `${rs(res.total_per_m)} / m`)),
      h("div", { class: "row-actions", style: "margin:0" },
        h("button", { class: "btn primary", onclick: async e => { const b = e.currentTarget; b.disabled = true; try { const r = await (await postJSON("/api/list/add", Object.assign({}, payload(sel), state.listId ? { _id: state.listId } : {}))).json(); toast(state.listId ? "Row updated in the list" : "Added to the list under Bulk upload"); state.listId = r.id; tellParent(); state.list = null; b.textContent = "Update in list"; } catch (err) { toast("Not added: " + err.message); } b.disabled = false; } }, state.listId ? "Update in list" : "Add to list"),
        h("button", { class: "btn", onclick: async () => { try { await download(await postJSON("/api/cost-sheet", payload(sel)), `Should cost ${sel["Fabric code"] || "fabric"}.xlsx`); } catch (err) { toast(err.message); } } }, "Download cost sheet"),
        h("button", { class: "btn", onclick: printSheet }, "Print"))),
    h("div", { class: "facts" }, h("span", {}, [sel.Content, sel.Route, sel.Weave, `${yarnText(sel, "Warp")} \u00D7 ${yarnText(sel, "Weft")}`, `${sel.EPI} × ${sel.PPI}`, `${sel["Finished width (in)"]} in wide`].filter(Boolean).join(" · "))),
    h("div", { class: "facts num" }, h("span", {}, `${rs(res.per_kg, 0)} / kg`), h("span", {}, `about ${fmt(res.gsm, 0)} g/m²`), h("span", {}, `${fmt(res.finished_g_per_m, 0)} g per running metre`)),
    quote, h("div", { class: "notice info hero-moved", hidden: true, style: "margin:10px 0 0" }));

  const box = h("div"), note = h("div", { class: "sub", style: "margin:2px 0 0" });
  const negative = res.buckets.some(b => b.lines.some(l => l.amount < -0.005));
  const draw = () => {
    const fn = { bars: barsChart, waterfall, pie: pieChart, treemap: treemapChart, line: buildLine }[state.chart];
    box.replaceChildren(fn(res));
    if (negative && (state.chart === "pie" || state.chart === "treemap")) box.append(h("p", { class: "sub", style: "margin:10px 0 0" }, "A discount cannot be drawn as an area, so it is left out of this view. The bars and the waterfall show it."));
    note.textContent = state.chart === "pie" && state.wfMode === "all" ? "Each sub-cost's share of the price; sub-costs of one group share its colour and sit together."
      : state.chart === "bars" && !state.bySize ? "One bar per cost, from zero, in the order the price is built." : CHART_NOTE[state.chart];
    bigLabel.hidden = !(state.chart === "bars" || state.chart === "pie");
  };
  const seg = (items, key, label) => { const g = h("div", { class: "seg", role: "group", "aria-label": label }); for (const [v, text] of items) g.append(h("button", { type: "button", "aria-pressed": String(state[key] === v), onclick: () => { state[key] = v; state.wfOpen.clear(); [...g.children].forEach(b => b.setAttribute("aria-pressed", String(b.textContent === text))); draw(); } }, text)); return g; };
  const zero = h("input", { type: "checkbox", id: "zero" }); zero.checked = state.showZero;
  zero.addEventListener("change", () => { state.showZero = zero.checked; draw(); });
  const big = h("input", { type: "checkbox", id: "bysize" }); big.checked = state.bySize;
  big.addEventListener("change", () => { state.bySize = big.checked; draw(); });
  const bigLabel = h("label", { for: "bysize", class: "opt", title: "Largest cost first. Untick for the order the price is built in." }, big, "Largest first");
  draw();
  const chart = h("div", { class: "card" },
    h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Where the price comes from"), note),
      h("div", { style: "display:flex;gap:10px 14px;align-items:center;flex-wrap:wrap" }, seg(CHARTS, "chart", "Chart"), seg([["groups", "Groups"], ["all", "All sub-costs"]], "wfMode", "Level of detail"),
        bigLabel,
        h("label", { for: "zero", class: "opt" }, zero, "Lines at zero"))),
    box,
    h("div", { class: "legend", "aria-hidden": "true" }, res.buckets.map((b, i) => h("span", {}, h("i", { style: `background:var(${GROUP_COLOR[i % 8]})` }), b.name))));

  const lineRows = [];
  for (const b of res.buckets) {
    lineRows.push(h("tr", { class: "grp" }, h("td", {}, b.name), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, pct(b.pct)), h("td", {})));
    for (const l of b.lines) lineRows.push(h("tr", {}, h("td", {}, l.name), h("td", { class: "n" }, fmt(l.amount)), h("td", { class: "n" }, pct(res.total_per_m ? l.amount / res.total_per_m : 0)), h("td", { class: "wrap" }, l.basis)));
  }
  lineRows.push(h("tr", { class: "grp" }, h("td", {}, "Should-cost"), h("td", { class: "n" }, fmt(res.total_per_m)), h("td", { class: "n" }, "100.0%"), h("td", {})));
  const tableView = h("details", { class: "card" }, h("summary", {}, "Table of every line"),
    h("div", { class: "table-wrap tall" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Line"), h("th", { class: "n" }, "Rs/m"), h("th", { class: "n" }, "Share"), h("th", {}, "How it is worked out"))), h("tbody", {}, lineRows))));
  const used = { columns: ["Item", "Choice", "Value", "Unit", "Basis"], rows: res.rates_used.map(u => [u.Item, u.Choice, u.Value, u.Unit, u.Basis]) };
  const ratesView = h("details", { class: "card" }, h("summary", {}, "Rates used and where each came from"), dataTable(used, { label: "Rates used" }));
  const odd = (res.warnings || []).length ? h("div", { class: "notice err", role: "alert" }, h("b", {}, "Check what was typed. "), res.warnings.join(" ")) : null;
  const moved = state.reopened ? movedCard(res, state.reopened) : null;
  const chosen = Object.entries(payload(sel)).filter(([k]) => !["Fabric code", "Description", "Supplier"].includes(k));
  const choices = h("details", { class: "card" }, h("summary", {}, "Choices behind this cost"), dataTable({ columns: ["Choice", "Value"], rows: chosen.map(([k, v]) => [k, String(v)]) }, { label: "Choices behind this cost" }));
  const warn = res.placeholders.length ? h("div", { class: "notice", role: "status" }, h("b", {}, "Provisional. "), "Placeholder rates were used for: " + res.placeholders.join(", ") + ". These are starting guesses with no data behind them.") : null;
  return [hero, odd, res.brief ? briefCard(res.brief, sel) : null, yarnSim(res, sel), moved, warn, chart, tableView, choices, ratesView].filter(Boolean);
}

// printed from the browser's own menu: open the tables too, so nothing prints as an empty heading
addEventListener("beforeprint", () => { if (document.body.classList.contains("printing")) return; const closed = [...document.querySelectorAll(".cost-out details:not([open])")]; closed.forEach(d => { d.open = true; }); addEventListener("afterprint", () => closed.forEach(d => { d.open = false; }), { once: true }); });
/* Print the cost on paper or to PDF: the result pane only, in light colours, with every table opened. */
function printSheet() {
  const root = document.documentElement, theme = root.dataset.theme;
  const closed = [...document.querySelectorAll(".cost-out details:not([open])")];
  closed.forEach(d => { d.open = true; });
  root.dataset.theme = "light"; document.body.classList.add("printing");
  const stamp = h("p", { class: "print-stamp" }, `RightPrice ex-mill should-cost \u00B7 printed ${day(new Date())} \u00B7 on the rates in the rate master that day`);
  $(".cost-out").prepend(stamp);
  const done = () => { root.dataset.theme = theme; document.body.classList.remove("printing"); closed.forEach(d => { d.open = false; }); stamp.remove(); removeEventListener("afterprint", done); };
  addEventListener("afterprint", done);
  setTimeout(() => print(), 60);
}

// the steps a chart draws: groups, or every sub-cost, each with its group's colour
function chartItems(res, positiveOnly) {
  const items = [];
  res.buckets.forEach((b, i) => {
    const color = GROUP_COLOR[i % 8];
    if (state.wfMode === "groups") items.push({ name: b.name, group: b.name, amount: b.amount, color, basis: `${b.lines.length} sub-costs` });
    else for (const l of b.lines) items.push({ name: l.name, group: b.name, amount: l.amount, color, basis: l.basis });
  });
  return items.filter(it => positiveOnly ? it.amount > 0.005 : (state.showZero || Math.abs(it.amount) >= 0.005));
}
const bySize = (list, get) => state.bySize ? [...list].sort((p, q) => Math.abs(get(q)) - Math.abs(get(p))) : list;
const itemTip = (it, total) => () => `<b>${it.name}</b>${it.group !== it.name ? it.group + "<br>" : ""}${rs(it.amount)} per metre · ${pct(total ? it.amount / total : 0)} of the price${it.basis && it.group !== it.name ? "<br>" + it.basis : ""}`;

/* Bars: one bar per group from zero, with its name, share and rupees beside it. A group opens
   into its sub-costs on a click; 'All sub-costs' opens every group. */
function barsChart(res) {
  const total = res.total_per_m;
  // with a quote on the chart, every bar shares the scale of the quote and the should-cost
  const top = res.quote !== null ? Math.max(total, res.quote) : Math.max(...res.buckets.map(b => Math.abs(b.amount)), 0.01);
  const box = h("div", { class: "bars", role: "list" });
  const row = (name, amount, color, cls, tipFn, button) => {
    const bar = h("div", { class: "bar" + (amount < 0 ? " neg" : ""), style: `width:${Math.max(0.6, Math.abs(amount) / top * 62)}%;background-color:var(${color})` });
    const text = h("span", { class: "bar-text" }, button || h("span", { class: "bar-name" }, name), h("span", { class: "bar-pct num" }, pct(total ? amount / total : 0, 0)), h("span", { class: "bar-amt num" }, `${rs(amount)} / m`));
    const el = h("div", { class: "bar-row " + cls, role: "listitem", tabindex: button ? null : "0" }, bar, text);
    withTip(el, tipFn); box.append(el);
  };
  bySize(res.buckets.map((b, i) => ({ b, i })), g => g.b.amount).forEach(({ b, i }) => {      // colour stays with the group, whatever the order
    const color = GROUP_COLOR[i % 8], open = state.wfMode === "all" || state.wfOpen.has(b.name);
    const btn = h("button", { type: "button", class: "bar-name", "aria-expanded": String(open), onclick: () => { open ? state.wfOpen.delete(b.name) : state.wfOpen.add(b.name); box.replaceWith(barsChart(res)); } }, h("span", { class: "caret", html: svg('<path d="m9 6 6 6-6 6"/>', 10) }), b.name);
    row(b.name, b.amount, color, "grp", () => `<b>${b.name}</b>${rs(b.amount)} per metre · ${pct(b.pct)} of the price`, btn);
    if (open) for (const l of bySize(b.lines.filter(l => state.showZero || Math.abs(l.amount) >= 0.005), l => l.amount))
      row(l.name, l.amount, color, "sub-row", itemTip({ name: l.name, group: b.name, amount: l.amount, basis: l.basis }, total));
  });
  if (res.quote !== null) {
    box.append(h("div", { class: "wf-sep", role: "presentation" }));
    const top2 = top;
    for (const [name, v, cls] of [["Should-cost", total, "totalbar"], ["Supplier's quote", res.quote, "quotebar"]])
      box.append(h("div", { class: "bar-row grp" }, h("div", { class: "bar " + cls, style: `width:${v / top2 * 62}%` }), h("span", { class: "bar-text" }, h("span", { class: "bar-name" }, name), h("span", { class: "bar-amt num" }, `${rs(v)} / m`))));
  }
  return box;
}

function pieChart(res) {
  let items = chartItems(res, true);
  if (state.bySize) {            // largest group first, and inside a group its largest sub-cost first, so one colour stays in one piece
    const groupSize = {}; for (const it of items) groupSize[it.group] = (groupSize[it.group] || 0) + it.amount;
    items = [...items].sort((p, q) => groupSize[q.group] - groupSize[p.group] || q.amount - p.amount);
  }
  const sum = items.reduce((a, it) => a + it.amount, 0) || 1, total = res.total_per_m;
  const R = 100, r = 58, C = 110;
  let a0 = -Math.PI / 2;
  const g = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  g.setAttribute("viewBox", "0 0 220 220"); g.setAttribute("role", "img"); g.setAttribute("aria-label", "Share of the price by " + (state.wfMode === "groups" ? "cost group" : "sub-cost"));
  for (const it of items) {
    const a1 = a0 + it.amount / sum * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0, pt = (a, rad) => `${(C + rad * Math.cos(a)).toFixed(2)} ${(C + rad * Math.sin(a)).toFixed(2)}`;
    const p = document.createElementNS(g.namespaceURI, "path");
    p.setAttribute("d", items.length === 1 ? `M${C} ${C - R}A${R} ${R} 0 1 1 ${C - 0.01} ${C - R}L${C - 0.01} ${C - r}A${r} ${r} 0 1 0 ${C} ${C - r}Z` : `M${pt(a0, R)}A${R} ${R} 0 ${big} 1 ${pt(a1, R)}L${pt(a1, r)}A${r} ${r} 0 ${big} 0 ${pt(a0, r)}Z`);
    p.setAttribute("class", "slice"); p.style.fill = `var(${it.color})`; p.setAttribute("tabindex", "0");
    withTip(p, itemTip(it, total)); g.append(p); a0 = a1;
  }
  const mid = document.createElementNS(g.namespaceURI, "g");
  mid.innerHTML = `<text x="${C}" y="${C - 4}" text-anchor="middle" class="pie-big">${fmt(total)}</text><text x="${C}" y="${C + 16}" text-anchor="middle" class="pie-small">Rs per metre</text>`;
  g.append(mid);
  const list = h("div", { class: "pie-list" }, items.map(it => h("div", { class: "pie-item" }, h("span", { class: "dot", style: `background:var(${it.color})` }), h("span", { class: "pie-name" }, it.name), h("span", { class: "num" }, pct(it.amount / total, 0)), h("span", { class: "num pie-amt" }, fmt(it.amount)))));
  return h("div", { class: "pie" }, h("div", { class: "pie-svg" }, g), list);
}

function splitRects(items, x, y, w, hgt) {      // halve the list by value, cut the longer side, repeat
  if (!items.length) return [];
  if (items.length === 1) return [Object.assign({}, items[0], { x, y, w, h: hgt })];
  const total = items.reduce((a, it) => a + it.v, 0);
  let acc = 0, i = 0;
  while (i < items.length - 1 && (i === 0 || acc + items[i].v <= total / 2)) { acc += items[i].v; i++; }
  const f = acc / total, a = items.slice(0, i), b = items.slice(i);
  return w >= hgt ? [...splitRects(a, x, y, w * f, hgt), ...splitRects(b, x + w * f, y, w * (1 - f), hgt)] : [...splitRects(a, x, y, w, hgt * f), ...splitRects(b, x, y + hgt * f, w, hgt * (1 - f))];
}
function treemapChart(res) {
  const total = res.total_per_m, W = 100, H = 46;      // drawn in a 100 x 46 box, as percentages
  const groups = res.buckets.map((b, i) => ({ b, color: GROUP_COLOR[i % 8], v: b.lines.reduce((a, l) => a + Math.max(l.amount, 0), 0) })).filter(g => g.v > 0.005).sort((p, q) => q.v - p.v);
  const box = h("div", { class: "treemap", role: "list", style: `aspect-ratio:${W}/${H}` });
  const place = (el, r, bw, bh) => { el.style.cssText += `left:${r.x / bw * 100}%;top:${r.y / bh * 100}%;width:${r.w / bw * 100}%;height:${r.h / bh * 100}%;`; return el; };
  for (const g of splitRects(groups, 0, 0, W, H)) {
    const cell = place(h("div", { class: "tm-group", role: "listitem", tabindex: "0", style: `background-color:var(${g.color});` }), g, W, H);
    const fits = (r, bw, bh) => r.w / bw * (g.w / W) > 0.085 && r.h / bh * (g.h / H) > 0.11;      // room for a label, as a share of the whole chart
    const label = h("div", { class: "tm-label" }, h("b", {}, g.b.name), h("span", { class: "num" }, `${fmt(g.b.amount)} \u00B7 ${pct(g.b.pct, 0)}`));
    if (state.wfMode === "groups") { cell.append(label); withTip(cell, () => `<b>${g.b.name}</b>${rs(g.b.amount)} per metre · ${pct(g.b.pct)} of the price`); }
    else {
      const inner = h("div", { class: "tm-inner" });
      const kids = g.b.lines.filter(l => l.amount > 0.005).map(l => ({ l, v: l.amount })).sort((p, q) => q.v - p.v);
      for (const k of splitRects(kids, 0, 0, g.w, g.h)) {
        const kid = place(h("div", { class: "tm-kid", tabindex: "0", "aria-label": `${k.l.name}, ${fmt(k.l.amount)} rupees per metre` }, fits(k, g.w, g.h) ? h("div", { class: "tm-label" }, h("b", {}, k.l.name), h("span", { class: "num" }, fmt(k.l.amount))) : null), k, g.w, g.h);
        withTip(kid, itemTip({ name: k.l.name, group: g.b.name, amount: k.l.amount, basis: k.l.basis }, total)); inner.append(kid);
      }
      cell.removeAttribute("tabindex"); cell.append(inner);
    }
    box.append(cell);
  }
  return box;
}

function buildLine(res) {
  const items = chartItems(res, false), total = res.total_per_m;
  const narrow = innerWidth < 700, W = narrow ? 430 : 760, H = narrow ? 380 : 360, m = { l: 46, r: 16, t: 20, b: state.wfMode === "all" ? 130 : 100 };
  let run = 0; const pts = items.map(it => { run += it.amount; return { it, y: run }; });
  const top = Math.max(...pts.map(p => p.y), total, 1), n = pts.length;
  const X = i => m.l + (n === 1 ? 0.5 : i / (n - 1)) * (W - m.l - m.r), Y = v => m.t + (1 - v / top) * (H - m.t - m.b);
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = top * k / 4; g += `<line class="grid-line" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis-text" x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, 0)}</text>`; }
  const path = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(p.y).toFixed(1)}`).join("");
  const el = h("div", { class: "chart", html: `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Running total of the price after each step, ending at ${fmt(total)} rupees per metre">${g}<path class="line" style="stroke:var(--total)" d="${path}"/></svg>` });
  const s = el.firstChild, ns = s.namespaceURI;
  pts.forEach((p, i) => {
    const c = document.createElementNS(ns, "circle"); c.setAttribute("cx", X(i)); c.setAttribute("cy", Y(p.y)); c.setAttribute("r", 6); c.setAttribute("class", "pt"); c.style.fill = `var(${p.it.color})`; c.setAttribute("tabindex", "0");
    withTip(c, () => `<b>${p.it.name}</b>+${fmt(p.it.amount)} → running total ${rs(p.y)}`); s.append(c);
    const t = document.createElementNS(ns, "text"); t.setAttribute("class", "axis-text"); t.setAttribute("text-anchor", "end"); t.setAttribute("transform", `translate(${X(i) + 4} ${H - m.b + 16}) rotate(-50)`); const cut = narrow ? 15 : 22; t.textContent = p.it.name.length > cut ? p.it.name.slice(0, cut - 1) + "\u2026" : p.it.name; if (!(narrow && n > 12 && i % 2)) s.append(t);
  });
  const end = document.createElementNS(ns, "text"); end.setAttribute("class", "pie-small"); end.setAttribute("x", X(n - 1)); end.setAttribute("y", Y(pts[n - 1].y) - 12); end.setAttribute("text-anchor", "end"); end.textContent = `Rs ${fmt(total)} / m`; s.append(end);
  return el;
}

/* Waterfall: each step starts where the one before ended. In 'groups' a group is one bar that
   opens into its sub-costs; in 'all' every group is open. A discount steps back to the left. */
function waterfall(res) {
  const total = res.total_per_m;
  let run = 0, peak = 0;
  for (const b of res.buckets) for (const l of b.lines) { run += l.amount; peak = Math.max(peak, run); }
  if (res.quote !== null) peak = Math.max(peak, res.quote);
  const scale = v => (v / (peak || 1)) * 100;
  const box = h("div", { class: "wf", role: "list" });
  const bar = (from, amount, cls, color) => {
    const lo = Math.min(from, from + amount), w = Math.abs(amount);
    return h("div", { class: "wf-bar " + cls + (amount < 0 ? " neg" : ""), style: `left:${scale(lo)}%;width:${scale(w)}%;${color ? `background-color:var(${color})` : ""}` });
  };
  const row = (o) => {
    const el = h("div", { class: "wf-row " + (o.cls || ""), role: "listitem", tabindex: o.button ? null : "0" },
      h("div", { class: "wf-label " + (o.labelCls || ""), title: o.name || null }, o.button || [o.color ? h("span", { class: "dot", style: `background:var(${o.color})` }) : null, h("span", { class: "txt" }, o.name)]),
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
      h("span", { class: "caret", html: svg('<path d="m9 6 6 6-6 6"/>', 10) }), h("span", { class: "dot", style: `background:var(${color})` }), h("span", { class: "txt" }, b.name)) : null;
    if (!open || (state.wfMode === "all" && !lines.length)) {       // closed, or nothing in it to show
      if (!toggle) { row({ name: b.name, color, labelCls: "total", bar: bar(start, b.amount, "", color), value: fmt(b.amount), tip: tipG }); run += b.amount; return; }
      row({ button: toggle, bar: bar(start, b.amount, "", color), value: fmt(b.amount), tip: tipG });
      run += b.amount;
      return;
    }
    row({ cls: "head", button: toggle, name: b.name, color, labelCls: "total", bar: bar(start, b.amount, "sumbar"), value: [fmt(b.amount), h("small", {}, pct(b.pct))], tip: tipG });
    for (const l of lines) {
      const from = run;
      row({ name: l.name, labelCls: "step", bar: bar(from, l.amount, "", color), value: fmt(l.amount),
        tip: () => `<b>${l.name}</b>${rs(l.amount)} per metre · ${pct(total ? l.amount / total : 0)} of the price<br>${l.basis}` });
      run += l.amount;
    }
    run = start + b.amount;
  });
  box.append(h("div", { class: "wf-sep", role: "presentation" }));
  row({ cls: "sum", name: "Should-cost", labelCls: "total", bar: bar(0, total, "totalbar"), value: fmt(total), tip: () => `<b>Should-cost</b>${rs(total)} per metre, ex-mill` });
  if (res.quote !== null) {
    const above = res.gap >= 0;
    row({ cls: "sum", name: "Supplier's quote", labelCls: "total", bar: [bar(0, res.quote, "quotebar"), h("div", { class: "wf-gap " + (above ? "over" : "under"), style: `left:${scale(Math.min(total, res.quote))}%;width:${scale(Math.abs(res.gap))}%` })],
      value: [fmt(res.quote), h("small", {}, `${above ? "+" : "−"}${pct(Math.abs(res.gap_pct))}`)],
      tip: () => `<b>Supplier's quote</b>${rs(res.quote)} per metre<br>${rs(Math.abs(res.gap))} (${pct(Math.abs(res.gap_pct))}) ${above ? "above" : "below"} should-cost` });
  }
  box.append(h("div", { class: "wf-axis", "aria-hidden": "true" }, h("span", {}, "Rs 0"), h("span", { class: "mid" }, `Rs ${fmt(peak / 2, 0)}`), h("span", {}, `Rs ${fmt(peak, 0)}/m`)));
  return box;
}

// ------------------------------------------------------------------ compare two costings
PAGES.compare = async () => {
  const list = state.list = await (await postJSON("/api/list", {})).json();
  const sources = [];
  if (state.sel && ready(state.sel)) sources.push({ id: "now", label: "On the Cost a fabric page now" + (state.sel["Fabric code"] ? ": " + state.sel["Fabric code"] : ""), inputs: payload(state.sel) });
  for (const r of list.rows) if (r.inputs && !r.problems.length) sources.push({ id: r.id, label: [r.mill["Fab Code"], r.supplier, r.description, "added " + day(r.added)].filter(v => !blank(v)).join(" \u00B7 "), inputs: r.inputs });
  const head = pageHead("Compare", "Two fabrics from the list side by side, both on today's rates: two suppliers' quotes for one fabric, or one fabric built two ways.");
  if (sources.length < 2) return [...head, h("div", { class: "card" }, h("p", { class: "empty" }, "Comparing needs two costed fabrics in the list. Upload a sheet under Bulk upload, or cost a fabric and press Add to list; a fabric open on Cost a fabric counts as one."), h("a", { class: "btn primary", href: "#cost" }, "Cost a fabric"))];
  const pickBox = (id, label, start) => { const sel = h("select", { id }, sources.map(s => h("option", { value: s.id }, s.label))); sel.value = sources[start].id; return [h("div", { class: "field" }, h("label", { for: id }, label), sel), sel]; };
  state.cmp = state.cmp || {};
  const startA = Math.max(0, sources.findIndex(s => s.id === state.cmp.a)), startB = sources.findIndex(s => s.id === state.cmp.b);
  const [fa, sa] = pickBox("cmp-a", "A", startA), [fb, sb] = pickBox("cmp-b", "B", startB >= 0 ? startB : (startA === 0 ? 1 : 0));
  const out = h("div", { "aria-live": "polite", style: "margin-top:16px" });
  let turn = 0;
  const run = async () => {
    const mine = ++turn;
    state.cmp = { a: sa.value, b: sb.value };
    const A = sources.find(s => s.id === sa.value), B = sources.find(s => s.id === sb.value);
    if (A.id === B.id) return out.replaceChildren(h("div", { class: "notice info" }, "Choose two different costings."));
    out.replaceChildren(h("p", { class: "empty" }, "Costing both..."));
    try { const [ra, rb] = await Promise.all([A, B].map(async s => (await postJSON("/api/cost", s.inputs)).json())); if (mine === turn) out.replaceChildren(...compareView(A, ra, B, rb)); }
    catch (e) { if (mine === turn) out.replaceChildren(h("div", { class: "notice err", role: "alert" }, "One of these can no longer be costed: " + e.message)); }
  };
  sa.addEventListener("change", run); sb.addEventListener("change", run); run();
  return [...head, h("div", { class: "card" }, h("div", { class: "fields" }, fa, fb), h("div", { class: "row-actions" }, h("button", { class: "btn small", type: "button", onclick: () => { const t = sa.value; sa.value = sb.value; sb.value = t; run(); } }, "Swap A and B"))), out];
};
function compareView(A, ra, B, rb) {
  const delta = (a, b) => { const dlt = b - a; return Math.abs(dlt) < 0.005 ? h("span", { class: "tag flat" }, "same") : h("span", { class: "tag " + (dlt > 0 ? "down" : "up") }, `${dlt > 0 ? "+" : "\u2212"}${fmt(Math.abs(dlt))}${a ? ` (${dlt > 0 ? "+" : "\u2212"}${pct(Math.abs(dlt) / Math.abs(a))})` : ""}`); };
  const side = (tagText, S, r) => h("div", { class: "card hero" }, h("div", { class: "lbl" }, h("span", { class: "tag ok" }, tagText), " ", S.label),
    h("div", { class: "big num" }, `${rs(r.total_per_m)} / m`),
    h("div", { class: "facts" }, h("span", {}, [S.inputs.Route, S.inputs.Weave, `${S.inputs["Warp yarn"]} \u00D7 ${S.inputs["Weft yarn"]}`, `${S.inputs.EPI} \u00D7 ${S.inputs.PPI}`, `${S.inputs["Finished width (in)"]} in`].join(" \u00B7 "))),
    h("div", { class: "facts num" }, h("span", {}, `${rs(r.per_kg, 0)} / kg`), h("span", {}, `about ${fmt(r.gsm, 0)} g/m\u00B2`)),
    r.quote !== null ? h("div", { class: "quote" }, h("span", { class: "tag flat" }, `Quote ${rs(r.quote)}/m, ${pct(Math.abs(r.gap_pct))} ${r.gap >= 0 ? "above" : "below"} its should-cost today`)) : null,
    r.placeholders.length ? h("div", { class: "quote" }, h("span", { class: "tag warn", title: r.placeholders.join(", ") }, "\u26A0 provisional: placeholder rates used")) : null);
  const dlt = rb.total_per_m - ra.total_per_m;
  const build = ["Route", "Weave", "Warp yarn", "Weft yarn", "EPI", "PPI", "Finished width (in)", "Warp count", "Weft count", "Count system"];
  const otherFabric = build.filter(k => String(A.inputs[k] ?? "") !== String(B.inputs[k] ?? ""));
  const caution = otherFabric.length ? h("div", { class: "notice", style: "margin-top:16px" }, h("b", {}, "These are not the same fabric. "), `They differ in ${otherFabric.join(", ")}, so the difference below is the fabric as much as the supplier.`) : null;
  const verdict = h("div", { class: "notice info", style: "margin-top:16px" }, Math.abs(dlt) < 0.005 ? "A and B have the same should-cost." : [h("b", {}, `B's should-cost is ${rs(Math.abs(dlt))} per metre (${pct(Math.abs(dlt) / ra.total_per_m)}) ${dlt > 0 ? "higher" : "lower"} than A's. `),
    (() => { const top = ra.buckets.map((b, i) => ({ name: b.name, d: rb.buckets[i].amount - b.amount })).filter(x => Math.abs(x.d) >= 0.005).sort((p, q) => Math.abs(q.d) - Math.abs(p.d)).slice(0, 3); return top.length ? "Largest differences, B against A: " + top.map(x => `${x.name} ${x.d > 0 ? "+" : "\u2212"}${fmt(Math.abs(x.d))}`).join(", ") + "." : ""; })()]);
  const top = Math.max(...ra.buckets.map(b => Math.abs(b.amount)), ...rb.buckets.map(b => Math.abs(b.amount)), 0.01);
  const rows = [];
  ra.buckets.forEach((b, i) => {
    const c = rb.buckets[i], color = GROUP_COLOR[i % 8];
    const bars = h("div", { class: "cmp-bars", "aria-hidden": "true" }, h("div", { class: "cmp-bar", style: `width:${Math.abs(b.amount) / top * 100}%;background:var(${color})` }), h("div", { class: "cmp-bar b", style: `width:${Math.abs(c.amount) / top * 100}%;background:var(${color})` }));
    rows.push(h("tr", { class: "grp" }, h("td", {}, b.name), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, fmt(c.amount)), h("td", { class: "n" }, delta(b.amount, c.amount)), h("td", { class: "cmp-cell" }, bars)));
    b.lines.forEach((l, j) => { const m = c.lines[j]; if (Math.abs(l.amount) >= 0.005 || Math.abs(m.amount) >= 0.005) rows.push(h("tr", {}, h("td", { style: "padding-left:26px;color:var(--muted)" }, l.name), h("td", { class: "n" }, fmt(l.amount)), h("td", { class: "n" }, fmt(m.amount)), h("td", { class: "n" }, Math.abs(m.amount - l.amount) < 0.005 ? "" : (m.amount > l.amount ? "+" : "\u2212") + fmt(Math.abs(m.amount - l.amount))), h("td", {}))); });
  });
  rows.push(h("tr", { class: "grp" }, h("td", {}, "Should-cost"), h("td", { class: "n" }, fmt(ra.total_per_m)), h("td", { class: "n" }, fmt(rb.total_per_m)), h("td", { class: "n" }, delta(ra.total_per_m, rb.total_per_m)), h("td", {})));
  if (ra.quote !== null || rb.quote !== null) {
    const q = r => r.quote === null ? "\u2014" : fmt(r.quote), g = r => r.quote === null ? "\u2014" : (r.gap >= 0 ? "+" : "\u2212") + fmt(Math.abs(r.gap)) + ` (${r.gap >= 0 ? "+" : "\u2212"}${pct(Math.abs(r.gap_pct))})`;
    rows.push(h("tr", { class: "grp" }, h("td", {}, "Supplier's quote"), h("td", { class: "n" }, q(ra)), h("td", { class: "n" }, q(rb)), h("td", { class: "n" }, ra.quote !== null && rb.quote !== null ? delta(ra.quote, rb.quote) : ""), h("td", {})));
    rows.push(h("tr", {}, h("td", { style: "padding-left:26px;color:var(--muted)" }, "Quote against its own should-cost"), h("td", { class: "n" }, g(ra)), h("td", { class: "n" }, g(rb)), h("td", {}), h("td", {})));
  }
  // a choice left blank means its default (the first value on its list), so blank against the default is not a difference
  const eff = (S, k) => { const v = S.inputs[k]; return blank(v) ? String((state.meta.lists[k] || [""])[0]) : String(v); };
  const keys = [...new Set([...Object.keys(A.inputs), ...Object.keys(B.inputs)])].filter(k => eff(A, k) !== eff(B, k));
  const differ = keys.length ? dataTable({ columns: ["Choice", "A", "B"], rows: keys.map(k => [k, String(A.inputs[k] ?? "\u2014"), String(B.inputs[k] ?? "\u2014")]) }, { label: "Choices that differ" }) : h("p", { class: "empty" }, "The two were built from the same choices.");
  return [h("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(280px,1fr))" }, side("A", A, ra), side("B", B, rb)), caution, verdict,
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Cost by group and sub-cost, Rs per metre"), h("span", { class: "sub", style: "margin:0" }, "Red: B is higher. Green: B is lower. Upper bar A, lower bar B")),
      h("div", { class: "table-wrap tall" }, h("table", { class: "cmp" }, h("thead", {}, h("tr", {}, h("th", {}, "Cost"), h("th", { class: "n" }, "A"), h("th", { class: "n" }, "B"), h("th", { class: "n" }, "B minus A"), h("th", { class: "cmp-cell" }, ""))), h("tbody", {}, rows)))),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Choices that differ")), differ)];
}

// ------------------------------------------------------------------ bulk upload and the fabric list
/* One list of every fabric costed: added from Cost a fabric, or uploaded many at a time (the RightPrice
   template, or a mill's price sheet as it comes). The columns are the mill sheet's own headings. Rows
   are ticked to remove, open or compare them; the list stays until rows are removed. */
PAGES.bulk = async (arg) => {
  state.listUI = state.listUI || { groups: { Fabric: true, Order: false, "Mill's price build-up": true }, picked: new Set(), filter: "", show: "all" };
  const ui = state.listUI;
  if (ui.yarn === undefined) ui.yarn = "*"; if (ui.pct === undefined) ui.pct = ""; if (ui.byStake === undefined) ui.byStake = false;
  // with a yarn move on, the gap that counts is the one after the move
  const moving = () => ui.pct !== "" && !!Number(ui.pct);
  const gapOf = r => moving() && r.sim_gap !== null && r.sim_gap !== undefined ? { rs: r.sim_gap, pct: r.sim_gap_pct } : { rs: r.gap, pct: r.gap_pct };
  // money at stake on the gap as printed (to the paisa), so it can be checked by hand
  const stakeOf = r => { const g = gapOf(r); return g.rs === null || g.rs === undefined || !r.quantity ? null : Math.round(Math.round(g.rs * 100) / 100 * r.quantity); };
  const rowStance = r => r.brief ? (r.brief.implausible ? "check" : stanceFor(r.brief, gapOf(r).pct)) : null;
  const box = h("div"), status = h("div", { "aria-live": "polite" });
  let data = null;
  const load = async () => {
    const moves = ui.pct !== "" && Number(ui.pct) ? { [ui.yarn]: Number(ui.pct) } : null;
    data = state.list = await (await postJSON("/api/list", moves ? { yarn_pct: moves } : {})).json();
    for (const id of [...ui.picked]) if (!data.rows.some(r => r.id === id)) ui.picked.delete(id);
    paint();
  };
  const visible = () => {
    const q = ui.filter.trim().toLowerCase();
    const rows = data.rows.filter(r => (ui.show === "all" || (ui.show === "notcosted" && r.problems.length) || (ui.show === "sums" && r.sums && r.sums.length) || (ui.show === "above" && rowStance(r) === "push")) && (!q || JSON.stringify([r.mill, r.supplier, r.description]).toLowerCase().includes(q)));
    for (const id of [...ui.picked]) if (!rows.some(r => r.id === id)) ui.picked.delete(id);      // a tick never outlives the row being in view
    return ui.byStake ? [...rows].sort((a, b) => (stakeOf(b) ?? -Infinity) - (stakeOf(a) ?? -Infinity)) : rows;
  };
  const remarks = r => [...r.problems.map(x => "Not costed: " + x), ...(r.sums || []).map(x => "Sum off: " + x), ...r.notes.map(x => x.charAt(0).toUpperCase() + x.slice(1)), r.placeholders.length ? "Placeholder rates: " + r.placeholders.join(", ") : null].filter(Boolean);
  const stanceCell = r => { const b = r.brief; if (!b) return ""; const st = rowStance(r); return h("span", { class: "tag " + STANCE[st][0], title: STANCE[st][1] + (st === "ask" ? ": " + b.weak.join("; ") : `. Usual range for this fabric: ${pctSigned(b.band.lo * 100)} to ${pctSigned(b.band.hi * 100)} against should-cost`) }, { push: "Push", fair: "Fair", below: "Below", ask: "Ask break-up", check: "Check quote" }[st]); };
  const openRow = r => { if (!r.inputs) return toast("This row has no choices to open"); state.sel = selFromRow(r.inputs); if (r.quantity) state.sel["Order quantity (m)"] = r.quantity; state.listId = r.id; state.rowNotes = r.notes; state.reopened = r.then ? { then: r.then, on: r.added } : null;
    if (moving()) { const p = Number(ui.pct), on = k => ui.yarn === "*" || r.inputs[k] === ui.yarn; state.sim = { warp: on("Warp yarn") ? p : 0, weft: on("Weft yarn") ? p : 0, both: on("Warp yarn") && on("Weft yarn") }; toast(`Opened with the list's yarn move (${ui.yarn === "*" ? "all yarns" : ui.yarn} ${pctSigned(p, 0)}) on the sliders; the brief follows it`); }
    else state.sim = null; state.openStep = r.problems.length ? "route" : null; STEPS.forEach(st => state.visited.add(st.id)); if (r.problems.length) toast(`${r.mill["Fab Code"] || "This row"} is not costed yet: ${r.problems[0]}`); location.hash = "#cost"; };
  const cell = (c, v) => blank(v) ? "" : typeof v === "number" ? (Number.isInteger(v) ? String(v) : fmt(v, Math.abs(v) < 100 && !Number.isInteger(v * 10) ? 2 : 1).replace(/\.0$/, "")) : (/^\d{4}-\d\d-\d\d$/.test(v) ? day(v) : String(v));

  const paint = () => {
    const rows = visible(), cols = data.columns.filter(c => c !== "Fab Code" && Object.entries(data.groups).some(([g, list]) => ui.groups[g] && list.includes(c)));
    const sim = data.rows.some(r => r.simulated !== null);
    const all = h("input", { type: "checkbox", "aria-label": "Select every row shown" }); all.checked = rows.length > 0 && rows.every(r => ui.picked.has(r.id)); all.indeterminate = !all.checked && rows.some(r => ui.picked.has(r.id));
    all.addEventListener("change", () => { rows.forEach(r => all.checked ? ui.picked.add(r.id) : ui.picked.delete(r.id)); paint(); });
    const body = rows.map(r => {
      const tick = h("input", { type: "checkbox", "aria-label": `Select ${r.mill["Fab Code"] || "row"}` }); tick.checked = ui.picked.has(r.id);
      tick.addEventListener("change", () => { tick.checked ? ui.picked.add(r.id) : ui.picked.delete(r.id); paint(); });
      const price = r.inputs && r.inputs["Quoted price (Rs/m)"];
      const sc = r.problems.length ? h("span", { class: "tag warn", title: r.problems.join("; ") }, "⚠ not costed") : [fmt(r.should_cost), r.placeholders.length ? h("span", { class: "tag warn", title: "Placeholder rates used: " + r.placeholders.join(", "), style: "margin-left:6px" }, "⚠") : null];
      const g = gapOf(r), rst = rowStance(r), weakRow = rst === "ask";
      const gap = g.pct === null || g.pct === undefined ? "" : h("span", { class: "tag " + (weakRow || rst === "check" ? "warn" : rst === "fair" || !rst ? "flat" : rst === "push" ? "down" : "up"), title: weakRow ? "The tool is unsure here: " + r.brief.weak.join("; ") : rst === "fair" ? "Inside the usual range for this fabric: treat as noise" : rst === "push" ? "Above the usual range for this fabric: room to negotiate" : "Below the usual range for this fabric" }, `${g.rs >= 0 ? "+" : "\u2212"}${fmt(Math.abs(g.rs))} (${pctSigned(g.pct * 100)})`);
      const stake = stakeOf(r), rem = remarks(r);
      const sums = r.sums === null ? h("span", { class: "sub", style: "margin:0" }, "—") : r.sums.length ? h("span", { class: "tag down", title: r.sums.join("; ") }, `✗ ${r.sums.length} off`) : h("span", { class: "tag ok" }, "✓ add up");
      const simCells = sim ? [h("td", { class: "n rp" }, r.simulated === null ? "" : fmt(r.simulated)), h("td", { class: "n rp" }, r.simulated === null || r.should_cost === null ? "" : Math.abs(r.simulated - r.should_cost) < 0.005 ? "no change" : `${r.simulated - r.should_cost >= 0 ? "+" : "\u2212"}${fmt(Math.abs(r.simulated - r.should_cost))}`)] : [];
      return h("tr", { class: ui.picked.has(r.id) ? "picked" : null },
        h("td", { class: "stick s0" }, tick),
        h("td", { class: "stick s1" }, h("button", { type: "button", class: "linkish", title: "Open in Cost a fabric", onclick: () => openRow(r) }, r.mill["Fab Code"] || "(no code)")),
        h("td", { class: "n rp stick s2" }, sc), ...simCells, h("td", { class: "n rp" }, blank(price) ? "" : fmt(price)), h("td", { class: "n rp" }, gap), h("td", { class: "n rp" }, stake === null ? "" : (stake < 0 ? "\u2212" : "") + "Rs " + fmt(Math.abs(stake), 0)), h("td", { class: "rp" }, stanceCell(r)), h("td", { class: "rp" }, sums),
        h("td", { class: "rp remarks" }, rem.length ? rem.map(x => h("div", {}, x)) : ""),
        cols.map(c => h("td", { class: "millcol" + (typeof r.mill[c] === "number" ? " n" : "") }, cell(c, r.mill[c]))));
    });
    const n = ui.picked.size, picked = data.rows.filter(r => ui.picked.has(r.id));
    const counts = { all: data.rows.length, notcosted: data.rows.filter(r => r.problems.length).length, sums: data.rows.filter(r => r.sums && r.sums.length).length, above: data.rows.filter(r => rowStance(r) === "push").length };
    const stakeBox = h("input", { type: "checkbox", id: "ls-stake" }); stakeBox.checked = ui.byStake; stakeBox.addEventListener("change", () => { ui.byStake = stakeBox.checked; paint(); });
    const chip = (key, label) => h("button", { type: "button", class: "chip", "aria-pressed": String(ui.show === key), onclick: () => { ui.show = key; paint(); } }, `${label} ${counts[key]}`);
    const grp = g => h("button", { type: "button", class: "chip", "aria-pressed": String(!!ui.groups[g]), onclick: () => { ui.groups[g] = !ui.groups[g]; paint(); } }, g);
    const filter = h("input", { class: "filter", type: "search", placeholder: "Filter the list...", "aria-label": "Filter the list", value: ui.filter, style: "max-width:220px" });
    filter.addEventListener("input", () => { ui.filter = filter.value; const pos = filter.selectionStart; paint(); const f = $(".list-tools .filter"); if (f) { f.focus(); f.setSelectionRange(pos, pos); } });
    const yarnPick = h("select", { id: "ls-yarn", "aria-label": "Yarn to move" }, h("option", { value: "*" }, "All yarns"), data.yarns_in_use.map(y => h("option", { value: y }, y))); yarnPick.value = data.yarns_in_use.includes(ui.yarn) ? ui.yarn : "*";
    const pctBox = h("input", { id: "ls-pct", type: "number", step: "1", min: "-50", max: "50", value: ui.pct, placeholder: "0", "aria-label": "Yarn price change, per cent", style: "width:84px" });
    const apply = () => { ui.yarn = yarnPick.value; const v = Number(pctBox.value); if (pctBox.value !== "" && Math.abs(v) > 50) { toast("A yarn move is limited to 50% either way"); pctBox.value = String(Math.sign(v) * 50); } ui.pct = pctBox.value; load(); };
    yarnPick.addEventListener("change", apply); pctBox.addEventListener("change", apply);
    const costedRows = data.rows.filter(r => r.should_cost !== null && gapOf(r).rs !== null && gapOf(r).rs !== undefined);
    // the money in the sheet, kept apart by what to do: savings never net off what to push for, and rows the
    // tool is unsure of are counted on their own
    const withQty = costedRows.filter(r => stakeOf(r) !== null), metres = withQty.reduce((a, r) => a + r.quantity, 0);
    const part = st => withQty.filter(r => rowStance(r) === st), sumOf = rs_ => rs_.reduce((a, r) => a + stakeOf(r), 0);
    const priced = data.rows.filter(r => r.inputs && !blank(r.inputs["Quoted price (Rs/m)"]));
    const uncosted = priced.filter(r => r.should_cost === null), allM = priced.reduce((a, r) => a + (r.quantity || Number(r.mill["Total order qnty"]) || 0), 0);
    const money = v => `Rs ${fmt(Math.abs(v), 0)} ${v >= 0 ? "above" : "below"} should-cost`;
    const moveText = moving() ? `${ui.yarn === "*" ? "all yarns" : ui.yarn} ${pctSigned(Number(ui.pct), 0)}` : "";
    const tot = costedRows.length ? h("p", { class: "sub", style: "margin:10px 0 0" }, `${costedRows.length} costed rows carry a mill price${moving() ? ` (with the yarn move applied: ${moveText})` : ""}${uncosted.length ? `; ${uncosted.length} more ${uncosted.length === 1 ? "has" : "have"} a price but ${uncosted.length === 1 ? "is" : "are"} not costed (${uncosted.map(r => r.mill["Fab Code"] || "no code").join(", ")})` : ""}.`,
      metres ? [` On the ${fmt(metres, 0)} m costed${allM > metres ? ` of ${fmt(allM, 0)} m ordered` : ""}: `,
        h("b", {}, `Push ${part("push").length}, ${money(sumOf(part("push")))}`), "; ",
        `in line ${part("fair").length}, ${money(sumOf(part("fair")))} net; `,
        `below ${part("below").length}, Rs ${fmt(Math.abs(sumOf(part("below"))), 0)} under should-cost; `,
        `ask for the break-up ${part("ask").length}${part("check").length ? ` and check the quote ${part("check").length}` : ""}, not counted because the tool is unsure of them or the quote needs checking.`] : null,
      " Red: above the usual range for that fabric type (Push); grey: inside it. ", h("a", { href: "#pack" }, "The negotiation pack"), " puts this on one printable page.") : null;
    box.replaceChildren(
      h("div", { class: "list-tools" },
        h("div", { class: "chips", role: "group", "aria-label": "Rows to show" }, chip("all", "All"), chip("above", "Push"), chip("notcosted", "Not costed"), chip("sums", "Mill's sums off")),
        h("div", { class: "chips", role: "group", "aria-label": "Column groups to show" }, h("span", { class: "sub", style: "margin:0;align-self:center" }, "Columns:"), Object.keys(data.groups).map(grp)),
        h("label", { for: "ls-stake", class: "opt" }, stakeBox, "Most at stake first"),
        filter),
      h("div", { class: "list-tools" },
        h("div", { class: "simbar" }, h("span", { class: "sub", style: "margin:0" }, "If yarn moves:"), yarnPick, pctBox, h("span", {}, "%"), ui.pct !== "" && Number(ui.pct) ? h("button", { class: "btn small", type: "button", onclick: () => { ui.pct = ""; load(); } }, "Clear") : null),
        h("div", { class: "actionbar" + (n ? " on" : "") }, h("b", {}, n ? `${n} selected` : "Tick rows to act on them"),
          h("button", { class: "btn small", type: "button", disabled: n !== 1 || null, onclick: () => openRow(picked[0]) }, "Open"),
          h("button", { class: "btn small", type: "button", disabled: n !== 2 || null, title: "Tick exactly two rows", onclick: () => { state.cmp = { a: picked[0].id, b: picked[1].id }; location.hash = "#compare"; } }, "Compare"),
          h("button", { class: "btn small danger", type: "button", disabled: !n || null, onclick: async e => {
            if (e.currentTarget.dataset.sure !== "1") { const b = e.currentTarget; b.dataset.sure = "1"; b.textContent = `Remove ${n}: sure?`; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = "Remove"; } }, 4000); return; }
            try { const r = await (await postJSON("/api/list/remove", { ids: [...ui.picked] })).json(); ui.picked.clear(); toast(`${r.removed} removed from the list`); load(); } catch (err) { toast(err.message); }
          } }, "Remove"),
          h("a", { class: "btn small", href: "#pack", title: "One printable page for the sheet: ticked rows, or the whole list" }, "Negotiation pack"),
          h("button", { class: "btn small", type: "button", onclick: async () => download(await postJSON("/api/list/download", ui.pct !== "" && Number(ui.pct) ? { yarn_pct: { [ui.yarn]: Number(ui.pct) } } : {}), "RightPrice_fabric_list.xlsx") }, "Download list"))),
      data.rows.length ? h("p", { class: "list-hint" }, "Fabric code and should-cost stay in place; swipe the table sideways for the mill price, the gap, money at stake and what to do.") : null,
      data.rows.length ? h("div", { class: "table-wrap list-wrap", tabindex: "0", role: "region", "aria-label": "Fabric list" }, h("table", { class: "list" },
        h("thead", {}, h("tr", {}, h("th", { class: "stick s0" }, all), h("th", { class: "stick s1" }, "Fab Code"), h("th", { class: "n rp stick s2" }, "Should-cost"), sim ? [h("th", { class: "n rp" }, "With yarn moved"), h("th", { class: "n rp" }, "Change")] : null, h("th", { class: "n rp" }, "Mill price"), h("th", { class: "n rp", title: "Plus: the mill is above should-cost" }, sim ? "Mill above should-cost, yarn moved" : "Mill above should-cost"), h("th", { class: "n rp", title: "Gap per metre times the order quantity" }, "At stake"), h("th", { class: "rp" }, "What to do"), h("th", { class: "rp" }, "Mill's sums"), h("th", { class: "rp" }, "Remarks"), cols.map(c => h("th", { class: "millcol" }, c)))),
        h("tbody", {}, body.length ? body : h("tr", {}, h("td", { colspan: String(9 + cols.length + (sim ? 2 : 0)) }, "No row matches."))))) : h("p", { class: "empty" }, "The list is empty. Upload a file above, or cost a fabric and press Add to list."),
      tot);
  };

  const file = h("input", { type: "file", accept: ".xlsx,.xls", id: "bulk-file", style: "max-width:100%" });
  file.addEventListener("change", async () => {
    if (!file.files[0]) return;
    const fd = new FormData(); fd.append("file", file.files[0]);
    status.replaceChildren(h("p", { class: "empty" }, "Reading and costing every row..."));
    try { const r = await (await api("/api/list/upload", { method: "POST", body: fd })).json(); status.replaceChildren(h("div", { class: "notice info", style: "margin-top:12px" }, `${r.added} rows added from a ${r.kind}.` + (r.already ? ` ${r.already} were already in the list and were not added again.` : "") + (r.added ? (r.not_costed ? ` ${r.not_costed} could not be costed yet; the reason is in Remarks.` : " All were costed.") : ""))); file.value = ""; await load(); }
    catch (e) { status.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message)); }
  });
  await load();
  return [...pageHead("Bulk upload", "Upload a mill's price sheet as it comes, or the RightPrice template. Every row joins the list below, costed beside the mill's price."),
    h("div", { class: "card upload" }, h("div", { class: "upload-row" },
      h("div", {}, h("label", { for: "bulk-file", class: "lbl-strong" }, "Excel file"), file),
      h("p", { class: "sub", style: "margin:0;flex:1;min-width:240px" }, "A mill sheet is recognised by its headings (Fab Code, Base Price, EPI, PPI and the rest). NYD rows are listed but not costed until you open them and choose piece dyed, printed or bleached."),
      h("a", { class: "btn small", href: "/api/template" }, "RightPrice template")), status),
    h("div", { class: "card" }, h("div", { class: "card-head", style: "margin-bottom:8px" }, h("h2", {}, "Fabric list"), h("span", { class: "sub", style: "margin:0" }, "Re-costed on today's rates each time it opens. It stays until rows are removed.")), box)];
};

// ------------------------------------------------------------------ prices
// ------------------------------------------------------------------ negotiation pack
/* One page to take into the meeting for a whole mill sheet: every row with its stance and the money at
   stake, the mill's own sums that are off, and the questions to ask. Printable on one A4 landscape page
   for a sheet of up to about twenty rows. */
const plural = (n, w) => `${fmt(n, 0)} ${w}${n === 1 ? "" : "s"}`;
const STANCE_ORDER = { push: 0, ask: 1, check: 2, below: 3, fair: 4 };
PAGES.pack = async () => {
  const ui = state.packUI = state.packUI || { scope: null };
  // rows ticked in Right cost come over once, through this tab's session storage
  let handed = null; try { handed = JSON.parse(sessionStorage.getItem("rp-pack-ids") || "null"); sessionStorage.removeItem("rp-pack-ids"); } catch (e) { /* none */ }
  const lu = state.listUI, picked = handed && handed.length ? handed : lu && lu.picked && lu.picked.size ? [...lu.picked] : null;
  const move = lu && lu.pct !== "" && lu.pct !== undefined && Number(lu.pct) ? { [lu.yarn]: Number(lu.pct) } : null;
  let first;
  try { first = await (await postJSON("/api/pack", move ? { yarn_pct: move } : {})).json(); }
  catch (e) { return [...pageHead("Negotiation pack", "One page for a whole mill sheet, to take into the meeting."), h("p", { class: "empty" }, "The list is empty. Upload a mill's price sheet under Bulk upload and list, then come back here.")]; }
  const scopes = [["all", `Whole list (${first.totals.rows} rows)`]];
  if (picked) scopes.push(["picked", `Rows ticked on the list (${picked.length})`]);
  first.sheets.forEach((g, i) => scopes.push(["sheet" + i, `${g.label} (${g.ids.length} rows)`]));
  // ticked rows on the list win whenever there are any; otherwise the last choice, or the whole list
  if (picked) ui.scope = "picked"; else if (!ui.scope || !scopes.some(x => x[0] === ui.scope)) ui.scope = "all";
  const idsFor = k => k === "all" ? null : k === "picked" ? picked : first.sheets[Number(k.slice(5))].ids;
  const body = h("div");
  const draw = async () => {
    const ids = idsFor(ui.scope);
    const p = ids ? await (await postJSON("/api/pack", Object.assign({ ids }, move ? { yarn_pct: move } : {}))).json() : first;
    body.replaceChildren(...packView(p, move, ui.scope === "picked" ? "ticked on the list" : ui.scope.startsWith("sheet") ? first.sheets[Number(ui.scope.slice(5))].label : null));
  };
  const pick = h("select", { id: "pack-scope", "aria-label": "Rows in the pack" }, scopes.map(([v, t]) => h("option", { value: v }, t))); pick.value = ui.scope;
  pick.addEventListener("change", () => { ui.scope = pick.value; draw(); });
  await draw();
  return [h("div", { class: "pack-tools" }, h("h1", {}, "Negotiation pack"), h("label", { for: "pack-scope", class: "sub", style: "margin:0" }, "Rows:"), pick,
    h("button", { class: "btn primary", type: "button", onclick: printPack }, "Print"), h("a", { class: "btn small", href: "#bulk" }, "Back to the list")), body];
};
function packView(p, move, scopeNote) {
  const t = p.totals, R = v => `Rs ${fmt(Math.abs(v), 0)}`;
  const rows = [...p.rows].sort((a, b) => STANCE_ORDER[a.stance] - STANCE_ORDER[b.stance] || Math.abs(b.at_stake || 0) - Math.abs(a.at_stake || 0));
  const who = p.suppliers.length ? p.suppliers.join(", ") : "Mill not named on the sheet";
  const head = h("div", { class: "pack-head" },
    h("div", {}, h("div", { class: "pack-title" }, `${who} · negotiation pack`),
      h("div", { class: "sub", style: "margin:2px 0 0" }, `${t.rows < t.of ? `${t.rows} of ${t.of} rows in the list` : `${t.rows} rows`}${scopeNote ? `, ${scopeNote}` : ""}${p.added.length ? `, added ${p.added.map(day).join(", ")}` : ""} · should-cost on the rate master of ${day(new Date())}, ex-mill, Rs per metre` + (move ? ` · with yarn moved ${Object.entries(move).map(([k, v]) => `${k === "*" ? "all yarns" : k} ${pctSigned(v, 0)}`).join(", ")}, as on the list` : ""))));
  const tile = (label, value, note, cls) => h("div", { class: "pack-tile" + (cls ? " " + cls : "") }, h("div", { class: "lbl" }, label), h("div", { class: "num pack-big" }, value), note ? h("div", { class: "sub", style: "margin:0;font-size:12px" }, note) : null);
  const signed = v => `${v >= 0 ? "" : "\u2212"}${R(v)}`;
  const tiles = h("div", { class: "pack-tiles" },
    tile("Ordered", `${fmt(t.metres, 0)} m`, `${t.duplicates ? `${plural(t.duplicates, "row")} repeating an order (${fmt(t.duplicate_metres, 0)} m) counted once; ` : ""}${t.ordered > t.metres ? `costed, of ${fmt(t.ordered, 0)} m ordered; ` : ""}${plural(t.costed, "row")} costed${t.not_costed ? `, ${t.not_costed} not costed` : ""}${t.no_quantity ? `; ${t.no_quantity} without a quantity` : ""}`),
    tile("Above should-cost, rows counted", signed(t.counted_stake), `Push ${signed(t.push_stake)} + in line ${signed(t.fair_stake)}${t.count.ask + t.count.check ? `. Not counted: ${plural(t.count.ask + t.count.check, "row")} the tool is unsure of or whose quote needs checking (${signed(t.flagged_stake)})` : ""}`),
    tile(`Push: ${plural(t.count.push, "row")}`, R(t.push_above_range), t.count.push ? `above the usual range, to be justified (${R(t.push_stake)} above should-cost)` : "no row is above its usual range", t.count.push ? "push" : ""),
    tile("Ask for the break-up", plural(t.count.ask, "row"), (t.count.ask ? "the tool is unsure of these; no target is named" : "") + (t.count.check ? `${t.count.ask ? ". " : ""}${plural(t.count.check, "quote")} more than 30% below should-cost to confirm first` : ""), t.count.ask || t.count.check ? "ask" : ""),
    tile("Mill's sums off", t.sums_money ? R(t.sums_money) : plural(t.sums_off, "row"), t.sums_off ? (t.sums_money ? `charged above what the sheet's own sums give, on ${plural(t.sums_off, "row")}` : "check them; none charges more than its own sums give") : "every row's sums add up", t.sums_off ? "sums" : ""),
    tile(`In line: ${t.count.fair} \u00B7 below: ${t.count.below}`, t.savings ? R(t.savings) : "\u2014", t.savings ? "below should-cost on the rows marked Below: a saving, if the specification holds" : "no row is below its usual range"));
  const byCode = Object.fromEntries(p.rows.map(r => [r.code, r]));
  const lead = p.lead.length ? h("div", { class: "pack-lead" }, h("b", {}, "Lead with: "), p.lead.map((c, i) => { const r = byCode[c]; return h("span", {}, `${i ? "; " : ""}${c}, ${R(r.above_range_money)} above the usual range on ${fmt(r.quantity, 0)} m (quote ${rs(r.quote)}; open at ${rs(r.open_at)}, aim for ${rs(r.upper)})`); }), ".") : h("div", { class: "pack-lead" }, h("b", {}, "No row to push on. "), "Every costed row is inside its usual range, below it, or on a fabric type the tool is unsure of.");
  const tag = st => h("span", { class: "tag " + STANCE[st][0] }, { push: "Push", fair: "Fair", below: "Below", ask: "Ask break-up", check: "Check quote" }[st]);
  const table = h("div", { class: "table-wrap pack-table" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Fabric"), h("th", { class: "n" }, "Metres"), h("th", { class: "n" }, "Mill price"), h("th", { class: "n" }, "Should-cost"), h("th", { class: "n" }, "Mill above should-cost"), h("th", { class: "n" }, "At stake"), h("th", {}, "What to do"), h("th", {}, "Mill's sums"))),
    h("tbody", {}, rows.map(r => h("tr", {},
      h("td", { class: "pack-fab" }, h("b", {}, r.code), h("div", { class: "pack-desc" }, r.description || "")),
      h("td", { class: "n", "data-l": "Metres" }, r.quantity ? fmt(r.quantity, 0) : "—"), h("td", { class: "n", "data-l": "Mill price" }, fmt(r.quote)), h("td", { class: "n", "data-l": "Should-cost" }, fmt(r.should)),
      h("td", { class: "n", "data-l": "Above should-cost" }, `${r.gap >= 0 ? "+" : "−"}${fmt(Math.abs(r.gap))} (${pctSigned(r.gap_pct * 100)})`),
      h("td", { class: "n", "data-l": "At stake" }, r.at_stake === null ? "—" : (r.at_stake < 0 ? "−" : "") + R(r.at_stake)),
      h("td", { "data-l": "What to do" }, r.duplicate_of ? h("span", { class: "tag warn", title: "Same mill reference and quantity as another row: counted once" }, `Duplicate of ${r.duplicate_of}`) : tag(r.stance), !r.duplicate_of && r.stance === "push" ? h("div", { class: "pack-desc" }, `open ${rs(r.open_at)} \u00B7 aim ${rs(r.upper)}`) : null),
      h("td", { "data-l": "Mill's sums" }, r.sums.length ? h("span", { class: "tag down" }, `✗ ${r.sums.length} off`) : h("span", { class: "tag ok" }, "✓ add up")))))));
  const qs = rows.flatMap(r => r.questions.map(q => ({ code: r.code, q })));
  const sums = [...p.rows, ...p.not_costed].filter(r => r.sums.length);
  const foot = h("p", { class: "sub pack-foot" }, "Each fabric type has its own usual range: where half your past purchases of it were priced against should-cost, kept at least 5% and at most 10% either way. Push: above it. Fair: inside it. Below: under it, a saving if the specification holds. Check quote: over 30% below should-cost. Ask break-up: the tool is unsure, so no target. Open: as far below the top of the range as the quote is above it, never below should-cost; aim: the top of the range. At stake: printed gap times metres. A row repeating an order (same mill reference and quantity) is counted once.");
  const questions = h("div", { class: "pack-cols" },
    h("div", {}, h("h2", {}, "Questions to ask"), qs.length ? h("ol", { class: "pack-q" }, qs.map(x => h("li", {}, x.q))) : h("p", { class: "sub" }, "None: every row is in line and its sums add up. Use the time on quantity terms, finish and delivery.")),
    h("div", {}, h("h2", {}, "The mill's sums that are off"), sums.length ? h("ul", { class: "pack-q" }, sums.map(r => h("li", {}, h("b", {}, r.code + ": "), r.sums.join("; ") + ".", r.own_gap ? ` By its own sums the price is ${rs(r.own_price)}, ${rs(Math.abs(r.own_gap))} a metre ${r.own_gap > 0 ? "less than" : "more than"} quoted.` : ""))) : h("p", { class: "sub" }, "Every row's sums add up."),
      p.not_costed.length ? [h("h2", { style: "margin-top:12px" }, "Not costed"), h("ul", { class: "pack-q" }, p.not_costed.map(r => h("li", {}, h("b", {}, r.code + ": "), r.why)))] : null, foot));
  return [head, tiles, lead, table, questions];
}
addEventListener("beforeprint", () => { if (location.hash.startsWith("#pack") && !document.body.classList.contains("printing-pack")) { packPrintOn(); addEventListener("afterprint", packPrintOff, { once: true }); } });
let packPrintOff = () => {};
function packPrintOn() {
  const root = document.documentElement, theme = root.dataset.theme;
  const page = h("style", {}, "@page { size: A4 landscape; margin: 8mm; }"); document.head.append(page);
  root.dataset.theme = "light"; document.body.classList.add("printing-pack");
  packPrintOff = () => { root.dataset.theme = theme; document.body.classList.remove("printing-pack"); page.remove(); };
}
function printPack() {
  packPrintOn();
  addEventListener("afterprint", () => packPrintOff(), { once: true });
  setTimeout(() => print(), 60);
}

PAGES.yarn = async (query) => {
  const [yrCard, mkCard, d] = await Promise.all([
    tableCard("Yarn_Rates", "Yarn master", { query }),
    tableCard("Market_Yarn", "Market reference", { extra: h("a", { class: "btn", href: "#intake" }, "Bring in prices") }),
    getJSON("/api/dashboard")]);
  state.dash = d;
  const cmp = { columns: ["Yarn key", "Master Rs/kg", "Market low", "Market high", "Position"],
    rows: d.yarns.filter(y => y.position).map(y => [y.key, y.rate, y.market_low, y.market_high, { inside: "Inside range", above: "Above market", below: "Below market" }[y.position]]) };
  return [...pageHead("Yarn prices", "The yarn master is used in every costing; edit a rate and its date, then save. The market reference is for comparison only and is never used in a costing."),
    yrCard,
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Master against market, combed compact cotton")), dataTable(cmp, { label: "Master against market", empty: "No yarn in the master has a market reference yet." })),
    mkCard];
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
    h("div", { class: "grid g4" }, stat("Latest Shankar-6", "Rs " + fmt(last[1], 0), "per candy"), stat("As of", day(last[0]), age > 30 ? `${age} days old` : null), stat("Over 30 days", tag(chg(m1))), stat("Over 12 months", tag(chg(y1)))),
    age > 30 ? h("div", { class: "notice" }, `The latest cotton price is ${age} days old. Add a newer one below.`) : null,
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Shankar-6, Rs per candy"), chips), box, h("p", { class: "sub", style: "margin:12px 0 0" }, "Source: " + c.source)),
    cottonForm(),
    h("details", { class: "card" }, h("summary", {}, "Table of the last 60 prices"), dataTable({ columns: ["Date", "Rs per candy"], rows: pts.slice(-60).reverse().map(p => [p[0].toISOString().slice(0, 10), p[1]]) }, { label: "Cotton prices" }))];
};

function cottonForm() {
  const f = (id, label, attrs) => h("div", { class: "field" }, h("label", { for: id }, label), h("input", Object.assign({ id }, attrs)));
  const msg = h("div", { "aria-live": "polite" });
  return h("form", { class: "card", onsubmit: async e => {
    e.preventDefault();
    try { await postJSON("/api/cotton", { date: $("#cot-date").value, price: $("#cot-price").value, source: $("#cot-source").value }); toast("Cotton price added"); route(); }
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

// ------------------------------------------------------------------ yarn price intake
PAGES.intake = async () => {
  const work = h("div", { "aria-live": "polite" });
  const fail = e => work.replaceChildren(h("div", { class: "notice err", role: "alert" }, e.message));
  const busy = () => work.replaceChildren(h("p", { class: "empty" }, "Reading..."));
  const COLS = ["Date", "Yarn", "Count", "Low Rs/kg", "High Rs/kg", "Source"];
  const review = (data) => {            // every source ends here: rows a person checks before they are added
    const body = h("tbody");
    const addRow = r => { const tr = h("tr", {}, COLS.map((c, i) => h("td", {}, h("input", { class: "cell" + (i === 3 || i === 4 ? " n" : ""), type: i === 3 || i === 4 ? "number" : "text", step: "any", value: r ? (r[i] ?? "") : (i === 0 ? new Date().toISOString().slice(0, 10) : ""), "aria-label": c }))), h("td", {}, h("button", { class: "icon-btn sm", type: "button", "aria-label": "Remove this row", onclick: () => tr.remove() }, "\u00D7"))); body.append(tr); return tr; };
    data.rows.forEach(addRow);
    const msg = h("div");
    work.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Review before adding")),
      data.note ? h("div", { class: "notice info", style: "margin:0 0 14px" }, data.note) : null,
      h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Rows to review" }, h("table", { class: "edit" }, h("thead", {}, h("tr", {}, COLS.map(c => h("th", { scope: "col" }, c)), h("th", {}))), body)), msg,
      h("div", { class: "row-actions" },
        h("button", { class: "btn primary", type: "button", onclick: async () => {
          const rows = [...body.rows].map(tr => [...tr.querySelectorAll("input")].map(i => i.value.trim() === "" ? null : i.value.trim()));
          try { const r = await (await postJSON("/api/intake/add", { rows, source: data.source })).json(); state.dash = null; toast(`${r.added} rows added to the market reference`); location.hash = "#yarn"; }
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
};

// ------------------------------------------------------------------ rates
function tabbed(title, sub, sheets, first) {
  return async (want) => {
    const box = h("div");
    const chips = h("div", { class: "chips", role: "tablist", "aria-label": title });
    const open = async sheet => {
      [...chips.children].forEach(c => c.setAttribute("aria-selected", String(c.dataset.sheet === sheet)));
      box.replaceChildren(h("p", { class: "empty" }, "Loading..."));
      current = sheet; editBtn.hidden = !state.meta.editable.includes(sheet);
      try { const t = await getJSON("/api/table/" + sheet); box.replaceChildren(dataTable(t, { filter: t.rows.length > 12, label: t.label })); }
      catch (e) { box.replaceChildren(h("div", { class: "notice err" }, e.message)); }
    };
    let current;
    const editBtn = h("button", { class: "btn", type: "button", onclick: async () => { editBtn.hidden = true; const sheet = current; box.replaceChildren(editTable(await getJSON("/api/table/" + sheet), sheet, () => open(sheet))); } }, "Edit this table");
    for (const s of sheets) chips.append(h("button", { class: "chip", role: "tab", "data-sheet": s, onclick: () => open(s) }, state.meta.tables[s]));
    await open(sheets.includes(want) ? want : first || sheets[0]);
    return [...pageHead(title, sub),
      h("div", { class: "card" }, h("div", { class: "card-head" }, chips, editBtn), box,
        h("div", { class: "notice info" }, "Basis shows where each number came from. ", h("span", { class: "tag warn" }, "⚠ Placeholder"), " marks a starting guess with no data behind it; the cost view warns whenever one is used."))];
  };
}
PAGES.rates = (w) => tabbed("Rate tables", "Every drop-down choice looks up a number here. The rate master workbook is the source of truth for all of them.",
  ["Weaving_Rates", "Weaving_Uplifts", "Sizing_Rates", "Yarn_Dyeing", "Piece_Dyeing", "Finishing_Rates", "Class_Defaults", "Weaves", "Content_Groups"])(w);
PAGES.ratecard = (w) => tabbed("Mill rate card", "Optional upcharges from Arvind's mill rate card of 23 Nov 2026 (confirmed 25 Nov). Each is rupees per metre on the price and is not marked up.",
  ["Print_Methods", "Dobby_Charges", "Weft_Options", "Quantity_Terms", "Finishing_Rates"])(w);
function displayCard() {
  const toggle = (id, label, hint, key, invert) => { const box = h("input", { type: "checkbox", id }); box.checked = invert ? !PREFS[key] : PREFS[key]; box.addEventListener("change", () => setPref(key, invert ? !box.checked : box.checked)); return h("label", { for: id, class: "opt-row" }, box, h("span", {}, h("b", {}, label), h("small", {}, hint))); };
  return h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Display, on this device")),
    h("div", { class: "grid g3" },
      h("div", {}, h("div", { class: "desk-only" }, toggle("pref-pin", "Pin the left panel open", "Unpinned, it folds to a strip of icons and opens when the pointer or keyboard reaches it.", "pin")),
        toggle("pref-compact", "Compact header and headings", "Gives the page more room. Turn off for larger headings.", "roomy", true)),
      h("div", { style: "grid-column:span 2" }, h("h3", {}, "Use it like an app on a phone"),
        h("p", { class: "sub", style: "margin:0" }, h("b", {}, "Android (Chrome): "), "open the site, tap the three dots, then \u201CAdd to Home screen\u201D or \u201CInstall app\u201D. ", h("b", {}, "iPhone (Safari): "), "tap Share, then \u201CAdd to Home Screen\u201D. It then opens full screen from its own icon. It still needs the internet and your sign-in; nothing is stored on the phone."))));
}
PAGES.settings = async (w) => { const nodes = await settingsTables(w); nodes.splice(2, 0, displayCard()); return nodes; };
const settingsTables = (w) => tabbed("Settings", "Calculation settings, mill tiers and order size slabs. Method: the corrected method of the V1 workbook; price basis ex-mill, so freight is left out.",
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
  if (state.list) for (const r of state.list.rows) items.push({ text: [r.mill["Fab Code"], r.description, r.supplier].filter(v => !blank(v)).join(" \u2014 ") || "(no code)", kind: "In the list", href: "#bulk" });
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
  input.addEventListener("focus", async () => { if (!state.list) { try { state.list = await (await postJSON("/api/list", {})).json(); } catch (e) { /* search works without it */ } } paint(); });
  input.addEventListener("keydown", e => {
    const links = [...box.querySelectorAll("a")];
    if (e.key === "Escape") { close(); input.blur(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (!links.length) return; on = (on + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length; links.forEach((a, i) => a.classList.toggle("on", i === on)); links[on].scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter" && links.length) { e.preventDefault(); const href = links[Math.max(on, 0)].getAttribute("href"); input.value = ""; close(); input.blur(); location.hash = href; }
  });
  document.addEventListener("click", e => { if (!e.target.closest(".search")) close(); });
  document.addEventListener("keydown", e => { if (e.key === "/" && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); } });
}

// ------------------------------------------------------------------ start
// inside Right cost's popup (/?embed=1): Cost a fabric alone, with no page list or header
const EMBED = new URLSearchParams(location.search).get("embed") === "1";
if (EMBED) document.documentElement.classList.add("embed");
// Right cost opens a costing here: its choices, and the list row it came from (if any)
window.rpOpen = (choices, listId) => {
  if (!state.meta) return setTimeout(() => window.rpOpen(choices, listId), 100);
  state.sel = choices ? selFromRow(choices) : blankSel(); state.listId = listId || null; state.rowNotes = null; state.sim = null; state.reopened = null; state.openStep = null;
  if (choices) STEPS.forEach(st => state.visited.add(st.id)); else state.visited.clear();
  if (location.hash !== "#cost") location.hash = "#cost"; else route();
};
const tellParent = () => { if (EMBED && parent !== window) parent.postMessage({ rp: "listChanged" }, location.origin); };
(async function start() {
  buildNav(); paintThemeButton(); loadPrefs();
  $("#pin").addEventListener("click", e => { setPref("pin", !PREFS.pin); e.currentTarget.blur(); });
  $("#today").textContent = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  try { state.meta = await getJSON("/api/meta"); }
  catch (e) { $("#main").replaceChildren(h("div", { class: "notice err" }, "The rate master could not be read: " + e.message)); return; }
  setupSearch();
  addEventListener("hashchange", route);
  route();
})();
