/* Right cost: every fabric costed, in one list page laid out after the PLM list screens.
   Data: /api/costs (the 1,696 purchase-order costings and the fabric list). Nothing is costed here;
   the "+" opens Cost a fabric itself, in a popup. Sections: CONFIG, STATE, UTILS, RENDER, EVENTS. */
"use strict";

// ================================================================== CONFIG
const BAND_COLOR = { "Fair": "#2E9E5B", "Below": "#3D8BFD", "Ask break-up": "#F5C542", "Ask break-up, above range": "#EF7D32", "Push": "#E5484D", "Not costed": "#B9BEC7", "No price": "#B9BEC7", "Check quote": "#B98900", "Working it out": "#DADADA" };
const ROUTE_COLOR = { "Yarn Dyed": "#3F6E9E", "Piece Dyed": "#2F8F63", "Printed": "#C9772B", "RFD / Bleached": "#8C9A92" };
const STATUS = ["Not started", "To negotiate", "In negotiation", "Agreed", "Dropped"];
const n0 = v => v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }).replace("-", "\u2212");
const n2 = v => v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).replace("-", "\u2212");
const pc = v => v === null || v === undefined || v === "" ? "" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1) + "%";

const CONFIG = {
  appName: "Right cost",
  pageSize: 100,
  modules: {
    costs: {
      crumbs: ["Costing", "Right cost"],
      classes: [["Purchase orders", "Purchase-order costings"], ["Fabric list", "Fabric list (mill sheets)"], ["*", "All costings"]],
      tabs: [["items", "Items"], ["suppliers", "Suppliers"]],
      // id, header, width, pinned, type (num, link, band, edit-dd, edit-text, thumb, select, status), value
      columns: [
        { id: "select", header: "", width: 40, pinned: true, type: "select" },
        { id: "image", header: "Image", width: 60, pinned: true, type: "thumb" },
        { id: "code", header: "Fabric code", width: 130, pinned: true, type: "link" },
        { id: "band", header: "Against range", width: 120, type: "band", help: "The price on the row (the mill's quote, or the price paid) against the usual range for this fabric type (measured on today's rates; a quote is costed on today's rates, a purchase order on the yarn rates of its order month where a dated rate exists, see Rates of): in it, above it, below it, or unsure (a type the tool fits poorly, or placeholder rates). Where the talks have reached since is in the Negotiation column" },
        { id: "nego", header: "Negotiation", width: 270, help: "From the tracker on the fabric's Negotiation tab: the agreed price, or while it is open the mill's latest price (our counter if the mill has not quoted)" },
        { id: "alert", header: "Quote alert", width: 290, help: "Why a newly quoted fabric needs a look before its price is accepted: above its usual range, the mill's sums are off, it repeats an order, or the quote is far below should-cost. It goes when marked seen (the cell then says Seen), or when the price is agreed in the tracker" },
        { id: "status", header: "Status", width: 120, type: "edit-dd", options: STATUS, help: "Your own label. Kept in this browser" },
        { id: "description", header: "Description", width: 230 },
        { id: "supplier", header: "Supplier", width: 170 },
        { id: "fab_group", header: "Fab group", width: 130, type: "fabgroup", help: "Purchase orders: the fabric's Fab group (the same construction in any colour, across mills), from the purchase history. Click it for the group's page; the chart button shows the price over time" },
        { id: "route", header: "Route", width: 90 },
        { id: "weave", header: "Weave", width: 90 },
        { id: "finish", header: "Finish", width: 140 },
        { id: "pattern", header: "Pattern", width: 80 },
        { id: "warp", header: "Warp", width: 100 },
        { id: "weft", header: "Weft", width: 100 },
        { id: "epippi", header: "EPI × PPI", width: 80, value: r => r.epi ? `${n0(r.epi)} × ${n0(r.ppi)}` : "" },
        { id: "width", header: "Width (in)", width: 70, type: "num", fmt: v => v ? Number(v).toFixed(1) : "" },
        { id: "should", header: "Should-cost Rs/m", width: 110, type: "num", fmt: n2 },
        { id: "price", header: "Paid or quoted Rs/m", width: 110, type: "num", fmt: n2, help: "Purchase orders: the price paid. Fabric list: the mill's quote, not yet paid" },
        { id: "gap_pct", header: "Above should-cost", width: 110, type: "num", fmt: pc },
        { id: "metres", header: "Metres", width: 80, type: "num", fmt: n0 },
        { id: "excess", header: "Above should-cost, Rs", width: 120, type: "num", fmt: n0, help: "Price minus should-cost, times the metres. Purchase orders: money paid above should-cost. Fabric list: on a quote, not yet paid" },
        { id: "order_size", header: "Order size", width: 110 },
        { id: "rates_of", header: "Rates of", width: 200, help: "Which rates the costing is on: a quote on today's rates; a purchase order on the yarn rates of its order month where a dated rate exists, else today's (stage 5)" },
        { id: "source", header: "Source", width: 110 },
        { id: "remarks", header: "Remarks", width: 170, type: "edit-text", help: "Your note. Kept in this browser" },
        { id: "rowstatus", header: "", width: 50, type: "status" },
      ],
      savedSearches: [
        { name: "Default", filters: {} },
        { name: "Above the usual range", filters: { band: ["Push", "Ask break-up, above range"] } },
        { name: "Ask for the break-up", filters: { band: ["Ask break-up"] } },
        { name: "More than 20% above should-cost (any verdict)", filters: { gap_pct: { min: "20", max: "" } } },
        { name: "Held-back third", filters: { held_back: ["Yes"] } },
        { name: "Orders of 3,000 m and above", filters: { order_size: ["3,000 m and above"] } },
      ],
      sortFields: [["code", "Fabric code"], ["description", "Description"], ["supplier", "Supplier"], ["should", "Should-cost"], ["price", "Price"], ["gap_pct", "Above should-cost, %"], ["excess", "Above should-cost, Rs"], ["band", "Against range (most to ask about first)"], ["nego", "Negotiation (agreed first, then open)"], ["metres", "Metres"], ["added", "Added on"]],
      filterAttrs: [
        { id: "supplier", label: "Supplier" }, { id: "mill", label: "Mill (every spelling)" }, { id: "route", label: "Route" }, { id: "weave_group", label: "Weave group" }, { id: "weave", label: "Weave" },
        { id: "finish", label: "Finish" }, { id: "pattern", label: "Pattern" }, { id: "warp", label: "Warp yarn" }, { id: "weft", label: "Weft yarn" },
        { id: "order_size", label: "Order size" }, { id: "fab_group", label: "Fab group" }, { id: "nego_status", label: "Negotiation" }, { id: "has_alert", label: "Quote alert to look at" }, { id: "band", label: "Against range" }, { id: "status", label: "Status" }, { id: "held_back", label: "Held back (calibration test)" },
        { id: "placeholder", label: "Placeholder rates used" }, { id: "should", label: "Should-cost Rs/m", num: true }, { id: "price", label: "Price Rs/m", num: true },
        { id: "gap_pct", label: "Above should-cost %", num: true }, { id: "metres", label: "Metres", num: true }, { id: "added", label: "Added on", date: true },
      ],
      moreActions: ["Download Excel", "Create cost", "Bulk upload", "Compare", "Negotiation pack"],
    },
  },
  // the left rail: Home, Right cost and one Prices menu. Everything about costing a fabric is in the "+" popup.
  rail: [
    { id: "home", icon: "home", label: "Home", hash: "dashboard" },
    { id: "costs", icon: "list", label: "Right cost", hash: "rightcost" },
    { id: "prices", icon: "chart", label: "Prices", fly: "prices" },
  ],
  flyouts: {
    prices: { title: "Prices and rates", icon: "chart", groups: [
      ["Market prices", [["Yarn prices", "#yarn"], ["Cotton prices", "#cotton"], ["Bring in prices", "#intake"]]],
      ["Rate master", [["Rate tables", "#rates"], ["Mill rate card", "#ratecard"], ["Mill cost sheets", "#costsheets"], ["Calculation settings", "#settings"]]],
      ["Costing setup", ["Rating scale types", "Rating scales", "Cost sheet types", "Material cost configuration", "Seasonal exchange rates"].map(n => [n, "#lib/" + n])],
      ["Sourcing setup", ["Payment terms", "Delivery terms", "Sample type"].map(n => [n, "#lib/" + n])]] },
  },
  // the pages of the shell under Home and Prices (their code is in web/pages/): section and title, and each section's tabs
  frames: {
    dashboard: ["Home", "Dashboard"], pilot: ["Home", "Pilot results"],
    yarn: ["Prices", "Yarn prices"], cotton: ["Prices", "Cotton prices"], intake: ["Prices", "Bring in prices"],
    rates: ["Prices", "Rate tables"], ratecard: ["Prices", "Mill rate card"], costsheets: ["Prices", "Mill cost sheets"], settings: ["Prices", "Calculation settings"],
  },
  sections: { Home: ["dashboard", "pilot"], Prices: ["yarn", "cotton", "intake", "rates", "ratecard", "costsheets", "settings"] },
  popupTabs: [["cost", "Create cost"], ["bulk", "Bulk upload"], ["compare", "Compare"], ["pack", "Negotiation pack"]],
};
const ICONS = {
  logo: '<path d="M7 19V5h6.5a4.5 4.5 0 0 1 0 9H10m3.5 0 4.5 5"/>',
  home: '<path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  fabric: '<path d="M4 6c3-2 5 2 8 0s5-2 8 0v12c-3 2-5-2-8 0s-5 2-8 0z"/>',
  chart: '<path d="M4 17l5-5 4 4 7-8M15 8h5v5"/>',
  table: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M10 4v16"/>',
  box: '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>',
  tools: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5 20 18M8 16.5 20 6"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  download: '<path d="M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 9.5a4 4 0 0 1-.5 8.5"/><path d="M12 11v9m0 0-3-3m3 3 3-3"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
  exact: '<circle cx="11" cy="11" r="6"/><circle cx="11" cy="11" r="2"/><path d="m20 20-4.5-4.5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  cards: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  rows: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  filter: '<path d="M4 5h16l-6 7v6l-4 2v-8z"/>',
  dots: '<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>',
  sort: '<path d="M8 4v16m0 0-3-3m3 3 3-3M16 20V4m0 0-3 3m3-3 3 3"/>',
  cols: '<path d="M4 5h16v14H4zM10 5v14M15 5v14"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  img: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-8 8"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  share: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="m8.2 11 7.6-4M8.2 13l7.6 4"/>',
  pin: '<path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z"/><circle cx="12" cy="10" r="2"/>',
  pdf: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 13h6M9 17h4"/>',
  comment: '<path d="M4 5h16v11H9l-5 4z"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
};
const svg = (name, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${ICONS[name] || ""}</svg>`;

// ================================================================== STATE
const store = {
  get(k, d) { try { const v = localStorage.getItem("rc-" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("rc-" + k, JSON.stringify(v)); } catch (e) { /* private window: kept for this visit only */ } },
};
const state = {
  module: "costs", cls: store.get("cls", "Purchase orders"), tab: "items", view: store.get("view", "list"),
  search: { text: "", mode: store.get("searchMode", "like"), active: null }, filters: {}, costedOnly: false,
  sort: { field: "excess", dir: "desc" }, saved: "Default", selection: new Set(), shown: CONFIG.pageSize, cardSize: store.get("cardSize", 115),
  colOrder: store.get("colOrder", null), colHidden: new Set(store.get("colHidden", [])), colWidth: store.get("colWidth", {}),
  negos: {}, negoKinds: [], alerts: { count: 0, ids: {}, kinds: {} }, edits: store.get("edits", {}), pending: {}, userSearches: store.get("searches", []), recent: store.get("recent", []), bookmarks: store.get("bookmarks", []),
  me: { initials: "RP", name: "Signed-in user", email: "" }, library: null, libs: store.get("libs", {}),
  downloads: [], log: store.get("log", []), rows: [], counts: {}, detail: null, loading: false,
};

// ================================================================== UTILS
const $ = (s, el = document) => el.querySelector(s);
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v; else if (k === "html") el.innerHTML = v; else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}
// replaceChildren turns an array or a null into text: flatten and drop the empties first
const fill = (el, ...kids) => { el.replaceChildren(...kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false)); return el; };
const keyOf = r => `${r.source}|${r.id || r.code}`;
const negoOf = k => { const n = state.negos[k]; return n && n.events && n.events.length ? n : null; };      // a fabric whose steps were all removed keeps only its log
const val = (r, id) => {
  const col = CONFIG.modules.costs.columns.find(c => c.id === id);
  if (id === "status") return (state.pending[keyOf(r)] || {}).status ?? (state.edits[keyOf(r)] || {}).status ?? "Not started";
  if (id === "remarks") return (state.pending[keyOf(r)] || {}).remarks ?? (state.edits[keyOf(r)] || {}).remarks ?? "";
  if (id === "held_back") return r.held_back === null || r.held_back === undefined ? "" : r.held_back ? "Yes" : "No";
  if (id === "placeholder") return r.placeholders ? "Yes" : "No";
  if (id === "added") return r.id || r.added || "";            // list ids carry the time they were added
  if (id === "nego" || id === "nego_status") { const n = negoOf(keyOf(r)); if (!n) return id === "nego" ? "" : "Not tracked"; const s_ = n.summary;
    if (id === "nego_status") return s_.status;
    const d = s_.won_per_m, chk = s_.warnings.length ? "Check a step \u00B7 " : "";
    if (s_.status === "Agreed") return chk + `Agreed Rs ${n2(s_.agreed)}` + (s_.first === null ? " (no mill quote)" : d === 0 ? " (the first quote)" : ` (${n2(Math.abs(d))} ${d > 0 ? "below" : "above"} first quote)`);
    return chk + (s_.reopened !== null ? "Open again, " : "Open, ") + (s_.latest !== null ? `mill at Rs ${n2(s_.latest)}` : `our counter Rs ${n2(s_.counter)}`); }
  if (id === "alert" || id === "has_alert") { const a = r.source === "Fabric list" ? (state.alerts.all || {})[r.id] : null, live = a && a.state === "live";
    if (id === "has_alert") return live ? "Yes" : a ? (a.state === "seen" ? "Seen" : "Agreed since") : "No";
    return a ? (live ? "" : a.state === "seen" ? "Seen \u00B7 " : "Agreed since \u00B7 ") + [...new Set(a.flags.map(f => (state.alerts.kinds || {})[f.kind] || f.kind))].join("; ") : ""; }
  if (id === "band_rank") return { "Push": 0, "Ask break-up, above range": 1, "Check quote": 2, "Ask break-up": 3, "Below": 4, "Fair": 5 }[r.band] ?? 6;
  if (col && col.value) return col.value(r);
  return r[id];
};
function toast(msg, ok = true) {
  const t = $("#toast"); fill(t, ok ? h("span", { class: "ok" }, "✓") : null, msg); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 3000);
}
const tip = $("#tip");
function tipOn(el, text) {
  el.setAttribute("aria-label", text);
  el.addEventListener("mouseenter", () => { tip.textContent = text; tip.hidden = false; const r = el.getBoundingClientRect(); tip.style.left = Math.min(r.left, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (r.bottom + 6) + "px"; });
  el.addEventListener("mouseleave", () => { tip.hidden = true; });
  el.addEventListener("focus", () => el.dispatchEvent(new Event("mouseenter")));
  el.addEventListener("blur", () => { tip.hidden = true; });
  return el;
}
const ib = (icon, label, onclick, extra = {}) => tipOn(h("button", Object.assign({ type: "button", class: "ib", onclick, html: svg(icon) }, extra)), label);
function closeLayers() { document.querySelectorAll(".menu, .scrim, .side, .colpanel").forEach(e => e.remove()); $("#drawer").hidden = true; $("#flyout").hidden = true; tip.hidden = true; railActive(); }
function menu(anchor, items, opts = {}) {
  document.querySelectorAll(".menu").forEach(e => e.remove());
  const m = h("div", { class: "menu", role: "menu" }, items.map(it => it === "-" ? h("hr") : it.head ? h("div", { class: "mh" }, it.head) : h("button", { type: "button", role: "menuitem", class: it.on ? "on" : null, onclick: () => { m.remove(); it.run(); } }, it.label)));
  document.body.append(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = Math.min(r.bottom + 4, innerHeight - m.offsetHeight - 8) + "px";
  m.style.left = Math.max(8, Math.min(opts.right ? r.right - m.offsetWidth : r.left, innerWidth - m.offsetWidth - 8)) + "px";
  const first = m.querySelector("button"); if (first) first.focus();
  setTimeout(() => addEventListener("mousedown", function off(e) { if (!m.contains(e.target)) { m.remove(); removeEventListener("mousedown", off); } }), 0);
  return m;
}
function dialog(title, body, actions) {
  const d = h("div", { class: "dialog", role: "dialog", "aria-modal": "true", "aria-label": title }, h("h2", {}, title), body, h("div", { class: "acts" }, actions));
  const s = h("div", { class: "scrim", onmousedown: e => { if (e.target === s) s.remove(); } }, d);
  $("#layer").append(s);
  const f = d.querySelector("input, select, textarea, button"); if (f) f.focus();
  return s;
}
function addLog(text) { state.log.unshift({ at: new Date().toISOString(), text }); state.log = state.log.slice(0, 300); store.set("log", state.log); }
const ago = iso => { const s = (Date.now() - new Date(iso)) / 1000; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} minutes ago` : s < 86400 ? `${Math.round(s / 3600)} hours ago` : `${Math.round(s / 86400)} days ago`; };
const extras = rows => Object.fromEntries(rows.map(r => [keyOf(r), { status: val(r, "status"), remarks: val(r, "remarks") }]));
async function download(path, body, name) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(r.statusText);
  const url = URL.createObjectURL(await r.blob()), a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000);
  state.downloads.unshift({ name, at: new Date().toISOString() });
}

// ------------------------------------------------------------------ the rows shown: class, search, filters, sort
function terms(text) { return (/[\n,\t]/.test(text) ? text.split(/[\n,\t]+/) : text.split(/ +/)).map(t => t.trim()).filter(Boolean); }
function filtered() {
  let rows = state.rows.filter(r => state.cls === "*" || r.source === state.cls);
  const s = state.search.active;
  if (s) {
    const ts = terms(s.text).map(t => t.toLowerCase());
    if (s.mode === "exact") rows = rows.filter(r => ts.includes(String(r.code).toLowerCase()));
    else {
      // a pasted list (commas or new lines) finds any of its entries; words typed with spaces must all match
      const list = /[\n,\t]/.test(s.text), hay = r => [r.code, r.description, r.supplier].map(v => String(v || "").toLowerCase()).join(" \u0001 ");
      rows = rows.filter(r => list ? ts.some(t => hay(r).includes(t)) : ts.every(t => hay(r).includes(t)));
    }
  }
  for (const [id, f] of Object.entries(state.filters)) {
    if (id === "_codes") { const set = new Set(f); rows = rows.filter(r => set.has(keyOf(r))); continue; }
    if (Array.isArray(f)) { if (f.length) rows = rows.filter(r => f.includes(String(val(r, id) ?? ""))); }
    else if (f.date) rows = rows.filter(r => { const v = String(r[id] || "").slice(0, 10); return v && (!f.from || v >= f.from) && (!f.to || v <= f.to); });
    else rows = rows.filter(r => { const v = Number(val(r, id)); return val(r, id) !== null && val(r, id) !== "" && (f.min === "" || f.min === undefined || v >= Number(f.min)) && (f.max === "" || f.max === undefined || v <= Number(f.max)); });
  }
  if (state.costedOnly) rows = rows.filter(r => r.should !== null && r.should !== undefined);
  const { field, dir } = state.sort, k = dir === "asc" ? 1 : -1, f2 = field === "band" ? "band_rank" : field;
  return [...rows].sort((a, b) => {
    const x = val(a, f2), y = val(b, f2);
    if (x === null || x === undefined || x === "") return 1; if (y === null || y === undefined || y === "") return -1;
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "en", { numeric: true })) * k;
  });
}
function missingCodes() {
  // codes not in this view: either in another view (say which) or nowhere
  const s = state.search.active; if (!s) return [];
  const here = new Set(state.rows.filter(r => state.cls === "*" || r.source === state.cls).map(r => String(r.code).toLowerCase()));
  const where = {}; for (const r of state.rows) where[String(r.code).toLowerCase()] = r.source;
  const ts = /[\n,\t]/.test(s.text) || s.mode === "exact" ? terms(s.text) : [];
  return ts.filter(t => s.mode === "exact" ? !here.has(t.toLowerCase()) : !state.rows.some(r => (state.cls === "*" || r.source === state.cls) && [r.code, r.description, r.supplier].some(v => String(v || "").toLowerCase().includes(t.toLowerCase()))))
    .map(t => ({ t, elsewhere: here.has(t.toLowerCase()) ? null : where[t.toLowerCase()] || null }));
}
function columns() {
  const all = CONFIG.modules.costs.columns, order = state.colOrder || all.map(c => c.id);
  const cols = order.map(id => all.find(c => c.id === id)).filter(Boolean);
  for (const c of all) if (!cols.includes(c)) cols.splice(cols.length - 1, 0, c);
  return cols.filter(c => c.pinned || c.type === "status" || !state.colHidden.has(c.id));
}
const widthOf = c => state.colWidth[c.id] || c.width;
function rerunWithSkeleton() { state.loading = true; state.shown = CONFIG.pageSize; render(); setTimeout(() => { state.loading = false; render(); }, 400); }

// ================================================================== RENDER
function railActive(id) {
  const first = decodeURIComponent(location.hash.slice(1)).split("/")[0] || "dashboard";
  const now = id || (first === "rightcost" || first === "item" || first === "supplier" || first === "group" || first === "groups" ? "costs" : first === "lib" || (CONFIG.frames[first] || [])[0] === "Prices" ? "prices" : "home");
  document.querySelectorAll(".rail .item").forEach(b => b.classList.toggle("active", b.dataset.id === now));
}
function renderRail() {
  const item = it => (h("button", { type: "button", class: "item", "data-id": it.id, "aria-label": it.label, onclick: e => {
    if (it.hash) { closeLayers(); if (location.hash.slice(1) === it.hash) route(); else location.hash = "#" + it.hash; }
    else openFly(it.fly, e.currentTarget);
  }, onmouseenter: it.fly ? e => openFly(it.fly, e.currentTarget, true) : null,
    onmouseleave: () => setTimeout(() => { const f = $("#flyout"); if (openFly.hover && !f.matches(":hover") && !document.querySelector(".rail .item:hover")) { f.hidden = true; railActive(); } }, 250) },
    h("span", { class: "ico", html: svg(it.icon) }), h("span", { class: "lbl" }, it.label),
    it.fly ? null : h("span", { class: "rtip", "aria-hidden": "true" }, it.label)));
  // the panel floats beside the page: folded it shows icons, the arrow opens it to icons with their names
  const setOpen = open => { document.body.classList.toggle("rail-open", open); const t = $("#railToggle"); if (t) { t.setAttribute("aria-expanded", String(open)); t.setAttribute("aria-label", open ? "Fold the side panel" : "Open the side panel"); } };
  const toggle = h("button", { type: "button", class: "rtoggle", id: "railToggle", onclick: () => { const open = !document.body.classList.contains("rail-open"); store.set("railOpen", open); closeLayers(); setOpen(open); },
    html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>' });
  fill($("#rail"), h("div", { class: "rhead" }, h("div", { class: "logo", html: svg("logo"), title: "RightPrice" }), h("b", { class: "lbl rname" }, "RightPrice"), toggle), h("div", { class: "grp" }, CONFIG.rail.map(item)),
    h("div", { class: "grp bottom" }, h("button", { type: "button", class: "avatar", id: "avatar", "aria-label": "Settings and account", onclick: e => openFly("profile", e.currentTarget) }, state.me.initials),
      h("button", { type: "button", class: "lbl racct", tabindex: "-1", "aria-hidden": "true", onclick: () => $("#avatar").click() }, "Settings and account")));
  setOpen(store.get("railOpen", false));
  railActive();
}
function go(href) {
  closeLayers();
  if (href === "theme:toggle") return toggleTheme();
  if (href.startsWith("#")) { if (location.hash === href) route(); else location.hash = href; return; }
  if (href.startsWith("detail:")) { const r = state.rows.find(x => keyOf(x) === href.slice(7)); if (r) return openDetail(r); }
  location.href = href;
}
function openFly(name, anchor, hover, keep) {
  const fly = $("#flyout");
  if (!keep && !fly.hidden && openFly.last === name && !hover) {
    if (openFly.hover) { openFly.hover = false; return; }         // a click on what the pointer opened: keep it open
    fly.hidden = true; railActive(); return;
  }
  openFly.last = name; railActive(name === "profile" ? null : name);
  const cfg = CONFIG.flyouts[name], kids = [], here = location.hash;
  const link = (label, href) => h("button", { type: "button", class: "lnk" + (here === href || here === encodeURI(href) ? " on" : ""), onclick: () => go(href) }, label);
  if (cfg) { kids.push(h("div", { class: "ttl", html: svg(cfg.icon) + `<span>${cfg.title}</span>` })); for (const [g, links] of cfg.groups) kids.push(h("div", { class: "g" }, g), links.map(([l, href]) => link(l, href))); }
  else if (name === "profile") {
    const dark = document.documentElement.dataset.theme === "dark";
    kids.push(h("div", { class: "ttl" }, h("span", {}, state.me.name)), state.me.email ? h("div", { class: "note" }, state.me.email) : null,
      h("div", { class: "g" }, "Settings"),
      h("button", { type: "button", class: "lnk", onclick: () => { toggleTheme(); openFly("profile", null, false, true); } }, dark ? "Light colours" : "Dark colours"),
      can("page:prices") ? [link("Calculation settings", "#settings"), link("Rate tables", "#rates")] : null,
      canAny("page:groups", "page:purchase_files") ? h("div", { class: "g" }, "Purchase history") : null,      // stage 2: web/purchases.js
      can("page:groups") ? link("Fab groups", "#groups") : null, can("page:purchase_files") ? link("Purchase files", "#purchase-files") : null,
      h("div", { class: "g" }, "Account"), profileExtras(),
      h("button", { type: "button", class: "lnk", onclick: () => { location.href = "/.auth/logout"; } }, "Log out"));
  }
  fill(fly, ...kids); fly.hidden = false;
  if (!openFly.bound) { openFly.bound = true; fly.addEventListener("mouseleave", () => { if (openFly.hover) { fly.hidden = true; railActive(); } }); }
  openFly.hover = !!hover;
}

// ------------------------------------------------------------------ pages: the address decides
const LIB_NAMES = () => CONFIG.flyouts.prices.groups.flatMap(g => g[1]).map(x => x[1]).filter(x => x.startsWith("#lib/")).map(x => x.slice(5));
function route() {
  let full = decodeURIComponent(location.hash.slice(1)) || "dashboard";
  // the earlier addresses of the costing screens open them in the popup, over the Dashboard
  if (CONFIG.popupTabs.some(t => t[0] === full.split("/")[0])) { history.replaceState(null, "", "#dashboard?new=" + full.split("/")[0]); full = "dashboard?new=" + full.split("/")[0]; }
  let [hsh, q] = full.split("?"), want = new URLSearchParams(q || "").get("new"), open = document.querySelector(".scrim[data-popup]");
  if (want && !CONFIG.popupTabs.length) { want = null; history.replaceState(null, "", "#" + hsh); }      // no screen of the popup open to this person (web/access.js)
  else if (want && !CONFIG.popupTabs.some(t => t[0] === want)) { want = "cost"; history.replaceState(null, "", "#" + hsh + "?new=cost"); }
  if (want && !open) openPopup(want, undefined, true);
  else if (!want && open) { open.remove(); load(); }
  else if (want && open && open.dataset.tab !== want) open.switchTo(want, true);
  if (route.page === hsh && (want || open)) return;            // only the popup changed
  route.page = hsh;
  const [id, ...rest] = hsh.split("/");
  document.querySelectorAll(".menu, .side, .colpanel").forEach(e => e.remove()); $("#drawer").hidden = true; $("#flyout").hidden = true;
  state.frame = null; state.library = null; state.supplier = id === "supplier" && rest.join("/") ? { key: rest.join("/"), data: state.supplier && state.supplier.key === rest.join("/") ? state.supplier.data : null } : null;
  if (id === "item") { state.detail = { key: rest.join("/"), tab: (state.detail && state.detail.key === rest.join("/") && state.detail.tab) || tabMemo(rest.join("/")) || "item", editing: false }; }
  else state.detail = null;
  state.users = id === "users";            // Users and roles (web/access.js)
  state.page = typeof RP_PAGES !== "undefined" && RP_PAGES[id] ? { id, arg: rest.join("/") } : null;      // stage 2: web/purchases.js
  if (id === "lib" && LIB_NAMES().includes(rest.join("/"))) state.library = { name: rest.join("/"), page: 0, size: 20 };
  else if (CONFIG.frames[id]) state.frame = hsh;
  else if (id !== "rightcost" && id !== "item" && !state.supplier && !state.users && !state.page) { state.frame = "dashboard"; if (hsh !== "dashboard") history.replaceState(null, "", "#dashboard"); }
  $("#main").className = "main" + (state.frame ? " fixed framepage" : !state.detail && !state.library && !state.supplier && !state.users && !state.page ? " fixed listpage" : "");
  railActive(); render();
  if (state.supplier) loadSupplier();
  if (state.users) loadUsers();
  if (state.page) RP_PAGES[state.page.id].enter(state.page);
  if ((id === "rightcost" || id === "item") && state.rows.length) loadNegos();
  document.title = (state.users ? "Users and roles" : state.frame ? CONFIG.frames[state.frame.split("/")[0]][1] : state.library ? state.library.name : state.supplier ? (state.supplier.data ? state.supplier.data.name : "Supplier") : state.page ? RP_PAGES[state.page.id].title(state.page) : state.detail ? rest.join("/").split("|").pop() : CONFIG.appName) + " - RightPrice";
}
const newCostButton = () => tipOn(h("button", { type: "button", class: "fab", onclick: () => openPopup("cost") }, h("span", { html: svg("plus") }), "New cost"), "Create cost, bulk upload, compare, negotiation pack");

// ------------------------------------------------------------------ the pages of the shell (web/pages/*.js)
/* A page registered with RP.page() (web/pages/common.js says how) is drawn under its heading: the crumb, the title, its
   section's tabs and New cost. The page itself is in its own box, which scrolls while the heading stays; asked for again
   at the same address, it keeps what it shows. A page that names a section is added at the end of that section's tabs. */
for (const p of Object.values(RP.pages)) if (!p.popup && !CONFIG.frames[p.id]) { CONFIG.frames[p.id] = [p.section, p.title]; if (CONFIG.sections[p.section]) CONFIG.sections[p.section].push(p.id); }
function renderPage(main) {
  const [id, ...rest] = state.frame.split("/"), [section, title] = CONFIG.frames[id], inSection = CONFIG.sections[section] || [];
  const tabs = inSection.length ? h("div", { class: "tabs", role: "tablist" }, inSection.map(k => h("button", { type: "button", role: "tab", class: "tab" + (k === id ? " on" : ""), "aria-selected": String(k === id), onclick: () => { location.hash = "#" + k; } }, CONFIG.frames[k][1]))) : null;
  const head = h("div", { class: "framehead" }, h("div", { class: "crumb" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }), section ? ["\u00A0\u203A\u00A0", section] : null, "\u00A0\u203A\u00A0", h("span", {}, title)),
    h("div", { class: "tabsrow" }, h("div", {}, h("div", { class: "headrow" }, h("h1", { class: "title", style: "cursor:default" }, title)), tabs), newCostButton()));
  const old = main.querySelector(":scope > .pgbox");
  $("#selbar").hidden = true;
  if (old && old.dataset.address === state.frame && main.firstElementChild && main.firstElementChild.classList.contains("framehead")) main.firstElementChild.replaceWith(head);
  else {
    const box = h("div", { class: "pgbox", "data-address": state.frame });
    fill(main, head, box);
    if (RP.pages[id]) RP.show(id, rest.join("/"), box, { freshMeta: true });
    else fill(box, h("div", { class: "empty" }, "This page could not be loaded: its file is missing from web/pages/."));
  }
  const on = main.querySelector(".tab.on"); if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
}
// what a page may ask of the shell
RP.shell = { toast, go: hash => { location.hash = "#" + hash; }, showAlerts, alertsChanged: () => loadAlerts(), listChanged: () => { load(); loadAlerts(); }, popup: (tab, r) => openPopup(tab, r) };

function render() {
  const main = $("#main");
  if (!pageOk()) return noPage(main);          // a page this person's role may not see (the server refuses its data too)
  if (state.users) return renderUsers(main);
  if (state.frame) return renderPage(main);
  if (state.library) return renderLibrary(main);
  if (state.supplier) return renderSupplier(main);
  if (state.page) return RP_PAGES[state.page.id].render(main);
  if (state.detail) return renderDetail(main);
  const mod = CONFIG.modules.costs, rows = filtered(), cls = mod.classes.find(c => c[0] === state.cls) || mod.classes[0];
  const crumbs = h("div", { class: "crumb" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }), "\u00A0\u203A\u00A0", CONFIG.appName, "\u00A0\u203A\u00A0", h("span", {}, cls[1]));
  const title = h("button", { type: "button", class: "title", "aria-haspopup": "menu", onclick: e => menu(e.currentTarget, mod.classes.map(([k, label]) => ({ label: `${label} (${k === "*" ? state.rows.length : state.counts[k] || 0})`, on: k === state.cls, run: () => { state.cls = k; store.set("cls", k); state.selection.clear(); rerunWithSkeleton(); } }))) },
    CONFIG.appName, h("span", { class: "caret" }, "▾"));
  const tabs = h("div", { class: "tabs", role: "tablist" }, mod.tabs.map(([k, label]) => h("button", { type: "button", role: "tab", class: "tab" + (state.tab === k ? " on" : ""), "aria-selected": String(state.tab === k), onclick: () => { state.tab = k; render(); } }, label)));
  fill(main, crumbs, h("div", { class: "tabsrow" }, h("div", {}, h("div", { class: "headrow" }, title, h("span", { class: "headsub" }, cls[1] + (state.updating ? " · being brought up to date (the figures shown are the last worked out)" : ""))), tabs), newCostButton()), toolbar(rows), chipsRow(), state.tab === "items" ? body(rows) : state.tab === "suppliers" ? suppliersTab(rows) : h("div", { class: "empty" }, "No records to view"));
  renderSelbar();
}

function toolbar(rows) {
  const mod = CONFIG.modules.costs, s = state.search;
  const input = h("input", { class: "search", id: "search", type: "search", placeholder: "Search code, name or supplier", value: s.text, "aria-label": "Search code, name or supplier" });
  input.addEventListener("input", () => { s.text = input.value; });
  input.addEventListener("keydown", e => { if (e.key === "Enter") runSearch(s.mode); });
  input.addEventListener("paste", e => { const t = e.clipboardData.getData("text"); if (/[\n\t]/.test(t)) { e.preventDefault(); s.text = terms(t).join(", "); input.value = s.text; } });
  const views = [ib("cards", "Cards", () => setView("card"), { class: "ib" + (state.view === "card" ? " on" : ""), "aria-pressed": String(state.view === "card") }),
    ib("rows", "List", () => setView("list"), { class: "ib" + (state.view === "list" ? " on" : ""), "aria-pressed": String(state.view === "list") })];
  const slider = state.view === "card" ? h("input", { type: "range", class: "slider", min: "80", max: "200", value: String(state.cardSize), "aria-label": "Card size", oninput: e => { state.cardSize = Number(e.target.value); store.set("cardSize", state.cardSize); const c = $(".cards"); if (c) c.style.gridTemplateColumns = `repeat(auto-fill, minmax(${Math.round(state.cardSize * 1.3)}px, 1fr))`; } }) : null;
  const saved = h("button", { type: "button", class: "selbtn", "aria-haspopup": "menu", onclick: e => menu(e.currentTarget, [...mod.savedSearches, ...state.userSearches].map(x => ({ label: x.name, on: state.saved === x.name, run: () => applySaved(x) })).concat(state.userSearches.length ? ["-", { label: "Delete a saved search…", run: deleteSaved }] : [])) }, state.saved, h("span", {}, "▾"));
  const sortName = (mod.sortFields.find(f => f[0] === state.sort.field) || [0, state.sort.field])[1];
  const sortIcon = tipOn(h("button", { type: "button", class: "selbtn", html: svg("sort"), onclick: () => { state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc"; rerunWithSkeleton(); } }), state.sort.dir === "asc" ? (state.sort.field === "added" ? "Oldest to latest" : "Ascending") + ": click for descending" : (state.sort.field === "added" ? "Latest to oldest" : "Descending") + ": click for ascending");
  const sortSel = h("button", { type: "button", class: "selbtn", "aria-haspopup": "menu", onclick: e => menu(e.currentTarget, mod.sortFields.map(([k, l]) => ({ label: l, on: state.sort.field === k, run: () => { state.sort.field = k; if (k === "band" || k === "nego") state.sort.dir = "asc"; rerunWithSkeleton(); } }))) }, sortName, h("span", {}, "▾"));
  const active = Object.keys(state.filters).filter(k => k !== "_codes").length > 0 || state.costedOnly;
  const filt = ib("filter", "Filters", () => openDrawer()); if (active) filt.append(h("span", { class: "dot" }));
  const more = ib("dots", "More", e => menu(e.currentTarget, mod.moreActions.map(a => ({ label: a, run: () => moreAction(a, rows) })), { right: true }));
  const sch = s.active ? h("span", { class: "chip" }, `${s.active.mode === "exact" ? "Exact" : "Search"}: ${s.active.text.length > 40 ? s.active.text.slice(0, 40) + "…" : s.active.text}`, tipOn(h("button", { type: "button", onclick: () => { s.active = null; s.text = ""; rerunWithSkeleton(); } }, "✕"), "Clear the search")) : null;
  return h("div", { class: "toolbar" },
    ib("search", "Search: code, description or supplier contains", () => runSearch("like"), { class: "ib" + (s.mode === "like" ? " on" : "") }),
    ib("exact", "Exact search: the fabric code matches exactly", () => runSearch("exact"), { class: "ib" + (s.mode === "exact" ? " on" : "") }),
    h("span", { class: "vdiv" }), input, ib("arrow", "Search", () => runSearch(s.mode)),
    state.tab !== "items" ? null : h("span", { class: "count", "aria-live": "polite" }, `Showing ${Math.min(state.shown, rows.length).toLocaleString("en-IN")} of ${rows.length.toLocaleString("en-IN")} records`), sch,
    h("span", { class: "spacer" }), slider, ...views, saved, h("span", { style: "display:inline-flex;align-items:center" }, sortIcon, sortSel), filt, more);
}
function chipsRow() {
  const chips = [];
  for (const m of missingCodes()) chips.push(m.elsewhere ? h("span", { class: "chip" }, `${m.t} is under ${m.elsewhere === "Fabric list" ? "Fabric list" : "Purchase-order costings"}`, h("button", { type: "button", title: "Show all costings", onclick: () => { state.cls = "*"; store.set("cls", "*"); rerunWithSkeleton(); } }, "\u2192")) : h("span", { class: "chip bad" }, `No Results For: ${m.t}`));
  for (const [id, f] of Object.entries(state.filters)) {
    const a = CONFIG.modules.costs.filterAttrs.find(x => x.id === id);
    const text = id === "_codes" ? `${state.saved}: ${f.length} items` : Array.isArray(f) ? `${a.label}: ${f.join(", ")}` : f.date ? `${a.label}: ${f.from || "…"} to ${f.to || "…"}` : `${a.label}: ${f.min === "" || f.min === undefined ? "…" : f.min} to ${f.max === "" || f.max === undefined ? "…" : f.max}`;
    chips.push(h("span", { class: "chip" }, text.length > 70 ? text.slice(0, 70) + "…" : text, tipOn(h("button", { type: "button", onclick: () => { delete state.filters[id]; state.saved = "Default"; rerunWithSkeleton(); } }, "✕"), "Remove this filter")));
  }
  if (state.alerts.count && !state.filters.has_alert) chips.push(tipOn(h("button", { type: "button", class: "chip alertchip", onclick: showAlerts }, `${state.alerts.count} quote ${state.alerts.count === 1 ? "alert" : "alerts"} to look at \u2192`), "Show only the fabrics with a quote alert"));
  if (state.costedOnly) chips.push(h("span", { class: "chip" }, "Costed only", h("button", { type: "button", onclick: () => { state.costedOnly = false; rerunWithSkeleton(); } }, "✕")));
  return chips.length ? h("div", { class: "chips" }, chips) : h("div");
}

function body(rows) {
  if (!state.rows.length) return h("div", { class: "empty" }, "Loading…");
  if (state.loading) return state.view === "list" ? gridView([], true) : h("div", { class: "empty" }, "Loading…");
  if (!rows.length) return h("div", { class: "empty" }, "No records to view");
  return state.view === "list" ? gridView(rows) : cardView(rows);
}
function gridView(rows, skeleton) {
  const cols = columns(), mod = CONFIG.modules.costs;
  let left = 0; const lefts = {}; const pinned = cols.filter(c => c.pinned);
  for (const c of pinned) { lefts[c.id] = left; left += widthOf(c); }
  const shown = rows.slice(0, state.shown);
  const allBox = h("input", { type: "checkbox", class: "cb", "aria-label": "Select all loaded rows" });
  allBox.checked = shown.length > 0 && shown.every(r => state.selection.has(keyOf(r)));
  allBox.indeterminate = !allBox.checked && shown.some(r => state.selection.has(keyOf(r)));
  allBox.addEventListener("change", () => { shown.forEach(r => allBox.checked ? state.selection.add(keyOf(r)) : state.selection.delete(keyOf(r))); render(); });
  const pinStyle = c => c.pinned ? { left: lefts[c.id] + "px" } : null;
  const cls = (c, extra) => [c.type === "num" ? "n" : "", c.pinned ? "pin" : "", c === pinned[pinned.length - 1] ? "pinlast" : "", extra || ""].join(" ").trim();
  const head = h("tr", {}, cols.map(c => {
    if (c.type === "select") return h("th", { class: cls(c), style: pinStyle(c) }, allBox);
    const sorted = state.sort.field === c.id;
    const th = h("th", { class: cls(c), style: pinStyle(c), scope: "col", "aria-sort": sorted ? (state.sort.dir === "asc" ? "ascending" : "descending") : null, onclick: e => {
      if (e.target.classList.contains("rs") || !c.header || ["image", "rowstatus"].includes(c.id)) return;
      const f = c.id === "epippi" ? "epi" : c.id;
      state.sort = { field: f, dir: state.sort.field === f && state.sort.dir === "asc" ? "desc" : "asc" }; rerunWithSkeleton();
    } }, c.header, sorted ? h("span", { class: "sorted" }, state.sort.dir === "asc" ? "▲" : "▼") : null, c.type && c.type.startsWith("edit") ? h("span", { class: "mark", title: "Editable" }, "▾") : null,
      c.type !== "select" ? h("span", { class: "rs", onmousedown: e => startResize(e, c) }) : null);
    if (c.help) tipOn(th, c.help);
    return th;
  }));
  const bodyRows = skeleton ? Array.from({ length: 12 }, () => h("tr", { class: "skel" }, cols.map(c => h("td", { class: cls(c), style: pinStyle(c) }, h("span", { class: "b", style: { width: Math.min(widthOf(c) - 16, 30 + Math.random() * 60) + "px" } }))))) :
    shown.map(r => {
      const k = keyOf(r), pend = state.pending[k];
      return h("tr", { class: state.selection.has(k) ? "picked" : null }, cols.map(c => cellFor(r, c, cls, pinStyle, pend)));
    });
  const table = h("table", { class: "grid", style: { width: cols.reduce((a, c) => a + widthOf(c), 0) + "px" } },
    h("colgroup", {}, cols.map(c => h("col", { style: { width: widthOf(c) + "px" } }))), h("thead", {}, head), h("tbody", {}, bodyRows));
  const scroller = h("div", { class: "gridscroll", tabindex: "0", role: "region", "aria-label": "Costings" }, table, !skeleton && rows.length > state.shown ? h("div", { class: "more" }, `Scroll for the next ${Math.min(CONFIG.pageSize, rows.length - state.shown)}…`) : null);
  scroller.addEventListener("scroll", () => { if (scroller.scrollTop + scroller.clientHeight > scroller.scrollHeight - 60 && state.shown < rows.length) { const top = scroller.scrollTop, lft = scroller.scrollLeft; state.shown += CONFIG.pageSize; render(); const s2 = $(".gridscroll"); if (s2) { s2.scrollTop = top; s2.scrollLeft = lft; } } });
  return h("div", { class: "gridwrap" }, scroller, h("div", { class: "colside" }, tipOn(h("button", { type: "button", onclick: e => columnChooser(e.currentTarget) }, h("span", { html: svg("cols") }), "Columns"), "Show, hide or reorder columns")));
}
function cellFor(r, c, cls, pinStyle, pend) {
  const k = keyOf(r), st = pinStyle(c);
  if (c.type === "select") { const b = h("input", { type: "checkbox", class: "cb", "aria-label": `Select ${r.code}` }); b.checked = state.selection.has(k); b.addEventListener("change", () => { b.checked ? state.selection.add(k) : state.selection.delete(k); render(); }); return h("td", { class: cls(c), style: st }, b); }
  if (c.type === "fabgroup") return h("td", { class: cls(c), style: st }, typeof RP_PURCH !== "undefined" ? RP_PURCH.cell(r) : "");     // stage 2: web/purchases.js
  if (c.type === "thumb") return h("td", { class: cls(c), style: st }, h("div", { class: "thumb", style: { background: ROUTE_COLOR[r.route] || "#B9BEC7" }, title: r.route || "" }, (r.route || "—").split(/[ /]/)[0].slice(0, 5).toUpperCase()));
  if (c.type === "link") return h("td", { class: cls(c), style: st }, h("button", { type: "button", class: "code", onclick: () => openDetail(r) }, r.code));
  if (c.type === "band" && r.duplicate_of) return h("td", { class: cls(c), style: st }, h("span", { class: "pill", title: "Same order as " + r.duplicate_of + ": counted once in the negotiation pack" }, h("i", { style: { background: "#B9BEC7" } }), h("span", { class: "pt" }, "Duplicate of " + r.duplicate_of)));
  if (c.type === "band") return h("td", { class: cls(c), style: st }, h("span", { class: "pill", title: r.band === "Ask break-up" && r.why_unsure ? r.why_unsure.join("; ") : null }, h("i", { style: { background: BAND_COLOR[r.band] || "#B9BEC7" } }), h("span", { class: "pt" }, r.band)));
  if (c.type === "status") return h("td", { class: cls(c), style: st }, pend ? tipOn(h("button", { type: "button", class: "discard", onclick: () => { delete state.pending[k]; render(); } }, "✕"), "Discard the unsaved change") : "");
  if (c.type === "edit-dd" || c.type === "edit-text") {
    const changed = pend && pend[c.id] !== undefined;
    const td = h("td", { class: cls(c, "edit" + (c.type === "edit-dd" ? " dd" : "") + (changed ? " changed" : "")), style: st, tabindex: "0" }, String(val(r, c.id) || ""));
    const startEdit = () => {
      if (td.querySelector("input, select")) return;
      const inp = c.type === "edit-dd" ? h("select", {}, c.options.map(o => h("option", {}, o))) : h("input", { type: "text" });
      inp.value = val(r, c.id) || (c.type === "edit-dd" ? c.options[0] : "");
      const done = keep => { if (keep && inp.value !== String(val(r, c.id) || "")) { state.pending[k] = Object.assign(state.pending[k] || {}, { [c.id]: inp.value }); toast("Changed: press Save on the bar below to keep it", false); } render(); };
      inp.addEventListener("keydown", e => { if (e.key === "Enter") done(true); if (e.key === "Escape") { e.stopPropagation(); done(false); } });
      inp.addEventListener("blur", () => done(true)); if (c.type === "edit-dd") inp.addEventListener("change", () => done(true));
      fill(td, inp); inp.focus();
    };
    td.addEventListener("click", startEdit); td.addEventListener("keydown", e => { if (e.key === "Enter") startEdit(); });
    return td;
  }
  const v = val(r, c.id);
  return h("td", { class: cls(c), style: st, title: typeof v === "string" && v.length > 18 ? v : null }, c.fmt ? c.fmt(v) : v === null || v === undefined ? "" : String(v));
}
function cardView(rows) {
  const shown = rows.slice(0, state.shown);
  const grid = h("div", { class: "cards", style: { gridTemplateColumns: `repeat(auto-fill, minmax(${Math.round(state.cardSize * 1.3)}px, 1fr))` } }, shown.map(r => {
    const k = keyOf(r), ck = h("input", { type: "checkbox", class: "cb ck", "aria-label": `Select ${r.code}` }); ck.checked = state.selection.has(k);
    ck.addEventListener("change", () => { ck.checked ? state.selection.add(k) : state.selection.delete(k); render(); });
    const bar = tipOn(h("div", { class: "bar", tabindex: "0", style: { background: BAND_COLOR[r.band] || "#B9BEC7" } }), r.band + (r.range ? ` (usual range ${pc(r.range[0])} to ${pc(r.range[1])})` : ""));
    return h("div", { class: "card" + (state.selection.has(k) ? " picked" : "") },
      h("div", { class: "img", style: { background: (ROUTE_COLOR[r.route] || "#B9BEC7") + "22" }, html: svg("fabric") }), bar,
      h("div", { class: "txt" }, h("button", { type: "button", class: "code", onclick: () => openDetail(r) }, r.code), h("div", { class: "desc", title: r.description }, r.description || ""),
        h("div", { class: "fig" }, r.should !== null && r.should !== undefined ? `Should-cost ${n2(r.should)} \u00B7 ${r.price ? `${r.source === "Purchase orders" ? "paid" : "quoted"} ${n2(r.price)} (${pc(r.gap_pct)})` : "no price"}` : r.band),
        val(r, "nego") ? h("div", { class: "fig nego" }, val(r, "nego")) : null),
      ck, h("button", { type: "button", class: "qv", onclick: () => quickView(r) }, "Quick view"));
  }));
  grid.addEventListener("scroll", () => { if (grid.scrollTop + grid.clientHeight > grid.scrollHeight - 80 && state.shown < rows.length) { const t = grid.scrollTop; state.shown += CONFIG.pageSize; render(); const g = $(".cards"); if (g) g.scrollTop = t; } });
  return grid;
}
// SUPPLIER COUNTS: what the Suppliers tab counts for each mill, as /api/suppliers counts it (rules/supplier.py): a
// purchase-order code only with a price paid (one bought only on ZLOI orders is never counted: GP, 27 Nov 2026); a
// fabric-list row unless it repeats another. Beside them, each mill's codes it sold on ZLOI orders and is not counted
// for, named by the ZLOI lines' own mill (not the row's supplier). check_server.py runs this function on the server's
// rows and compares it with /api/suppliers.
function supplierCounts(rows) {
  const by = {}, at = k => by[k] = by[k] || { counted: [], zloi: [], names: {}, ids: new Set() };
  for (const r of rows) {
    if (r.source === "Purchase orders" ? r.price !== null && r.price !== undefined : !r.duplicate_of) { const x = at(r.mill || "(none)"); x.counted.push(r); x.ids.add(r); }
  }
  for (const r of rows) {
    if (r.source !== "Purchase orders") continue;
    const seen = new Set();
    for (const o of r.outliers || []) {
      const k = o.mill_key || "(none)", x = at(k);
      x.names[o.mill] = (x.names[o.mill] || 0) + 1;
      if (!seen.has(k) && !x.ids.has(r)) x.zloi.push(r);
      seen.add(k);
    }
  }
  return by;
}
// END SUPPLIER COUNTS
function suppliersTab(rows) {
  if (!rows.length) return h("div", { class: "empty" }, "No records to view");
  const by = supplierCounts(rows);
  const nameOf = rs => { const n = {}; rs.forEach(r => { if (r.supplier) n[r.supplier] = (n[r.supplier] || 0) + 1; }); return (Object.entries(n).sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)[0] || ["(no supplier)"])[0]; };
  const list = Object.entries(by).filter(([, x]) => x.counted.length).map(([k, x]) => { const rs = x.counted, m = rs.filter(r => r.metres && r.price && r.should && !r.duplicate_of); const met = m.reduce((a, r) => a + r.metres, 0); return { k, s: nameOf(rs), n: rs.length, zloi: x.zloi.length, met, paid: met ? m.reduce((a, r) => a + r.price * r.metres, 0) / met : null, should: met ? m.reduce((a, r) => a + r.should * r.metres, 0) / met : null, above: rs.filter(r => r.band === "Push" && !r.duplicate_of).length, high: rs.filter(r => r.band === "Ask break-up, above range").length, unsure: rs.filter(r => r.band === "Ask break-up").length }; }).sort((a, b) => b.n - a.n);
  const zName = x => (Object.entries(x.names).sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)[0] || ["(no supplier)"])[0];
  const zOnly = Object.entries(by).filter(([, x]) => !x.counted.length && x.zloi.length).map(([k, x]) => ({ k, s: zName(x), n: x.zloi.length })).sort((a, b) => b.n - a.n);
  const anyZ = list.some(x => x.zloi) || zOnly.length;
  const millLink = x => x.k === "(none)" ? x.s : h("button", { type: "button", class: "code", onclick: () => { location.hash = "#supplier/" + encodeURIComponent(x.k); } }, x.s);
  return h("div", {}, list.length ? h("div", { class: "gridscroll" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Supplier (opens its page)", "Fabrics", "Metres", "Price Rs/m (average over metres)", "Should-cost Rs/m", "Price above (average over metres)", "Above range (Push)", "Look high, tool unsure", "Other unsure", ""].map((t, i) => h("th", { class: i && i < 9 ? "n" : "" }, t)))),
    h("tbody", {}, list.map(x => h("tr", {}, h("td", {}, millLink(x)), h("td", { class: "n" }, n0(x.n), x.zloi ? h("div", { class: "muted", style: "font-size:11px" }, `+ ${n0(x.zloi)} ZLOI only, not counted`) : null), h("td", { class: "n" }, n0(x.met)), h("td", { class: "n" }, n2(x.paid)), h("td", { class: "n" }, n2(x.should)), h("td", { class: "n" }, x.paid ? pc((x.paid / x.should - 1) * 100) : ""), h("td", { class: "n" }, n0(x.above)), h("td", { class: "n" }, n0(x.high)), h("td", { class: "n" }, n0(x.unsure)),
      h("td", {}, h("button", { type: "button", class: "btn line", style: "height:26px;font-size:12px", onclick: () => { state.filters.mill = [x.k]; state.tab = "items"; rerunWithSkeleton(); } }, "In the list"))))))) : h("div", { class: "empty" }, "No fabric bought (with a price paid) or quoted among these rows"),
    anyZ ? h("p", { class: "muted", style: "margin-top:10px;font-size:12px" }, "A fabric bought from a mill only on ZLOI orders (letters of intent) is not counted for that mill (GP, 27 Nov 2026): the figure under a mill's count is how many it sold only on ZLOI, named by the ZLOI lines' own mill; its page lists them apart." +
      (zOnly.length ? " Bought only on ZLOI orders, so not in the table: " : ""), zOnly.map((x, i) => [i ? ", " : "", millLink(x), ` (${n0(x.n)} ${x.n === 1 ? "fabric" : "fabrics"})`])) : null);
}

// ------------------------------------------------------------------ supplier page: one mill, for the meeting with it
async function loadSupplier() {
  await RPA.ready; if (!can("page:rightcost")) return;            // who may see it is known first (web/access.js)
  const sp = state.supplier; if (!sp) return;
  try {
    const res = await fetch("/api/supplier?mill=" + encodeURIComponent(sp.key));
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const d = await res.json(); if (state.supplier !== sp) return;
    sp.data = d; sp.error = null; document.title = d.name + " - RightPrice";
  } catch (e) { if (state.supplier !== sp) return; sp.error = e.message; }
  render();
}
const bandPill = band => h("span", { class: "pill" }, h("i", { style: { background: BAND_COLOR[band] || "#B9BEC7" } }), h("span", { class: "pt" }, band));
const BAND_WORDS = [["Push", "above the usual range (Push)"], ["Ask break-up, above range", "above the range, but the tool is unsure"], ["Ask break-up", "tool unsure (ask for the break-up)"], ["Check quote", "price far below should-cost (check it)"], ["Fair", "in the usual range"], ["Below", "below the usual range"], ["Not costed", "not costed"], ["No price", "no price"], ["Working it out", "being worked out"]];
function renderSupplier(main) {
  const sp = state.supplier, d = sp.data;
  $("#selbar").hidden = true;
  const crumbs = h("div", { class: "crumb noprint" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }), " › ", h("button", { type: "button", onclick: () => { state.tab = "suppliers"; location.hash = "#rightcost"; } }, "Right cost: suppliers"), " › ", h("span", {}, d ? d.name : sp.key));
  if (sp.error) return fill(main, crumbs, h("div", { class: "empty" }, sp.error));
  if (!d) return fill(main, crumbs, h("div", { class: "empty" }, "Loading…"));
  const B = d.bought, Q = d.quoted, T = d.tracker, qs = d.questions;
  const openRow = r => { const row = state.rows.find(x => x.source === r.source && (r.id ? x.id === r.id : x.code === r.code)); if (row) { openDetail(row); state.detail.tab = "negotiation"; tabMemo(keyOf(row), "negotiation"); } };
  const code = r => h("button", { type: "button", class: "code", onclick: () => openRow(r) }, r.code);
  const tile = (label, big, sub, cls) => h("div", { class: "stile" + (cls ? " " + cls : "") }, h("div", { class: "sl" }, label), h("div", { class: "sb" }, big), sub ? h("div", { class: "ss" }, sub) : null);
  const counts = side => BAND_WORDS.filter(([b]) => side.counts[b]).map(([b, w]) => `${n0(side.counts[b])} ${w}`).join("; ");
  const money = (side, bought) => [
    side.counts.Push ? h("li", {}, h("b", {}, `Rs ${n0(side.above_range)} above the top of the usual range`), ` on ${n0(side.counts.Push)} Push ${side.counts.Push === 1 ? "fabric" : "fabrics"} (Rs ${n0(side.push_excess)} above should-cost on them). `,
        bought ? "These are paid: the figure is the case for a better price on the next order of the same cloth. " + (side.rates ? side.rates.text : "It is on today's rates, not the rates of the order date.") : "This is the figure the mill has to explain" + (side.moved ? "; where the mill has moved since its sheet, it is on the price it is at now." : "."))
      : h("li", {}, side.unsure_high ? "None the tool is sure of is above its usual range." : "No fabric is above its usual range."),
    side.unsure_high ? h("li", {}, h("b", {}, `${n0(side.unsure_high)} ${side.counts.Push ? "more " : ""}${side.unsure_high === 1 ? "looks" : "look"} high`), ` (Rs ${n0(side.unsure_high_excess)} above should-cost), but the tool is unsure of ${side.unsure_high === 1 ? "it" : "them"} (placeholder rates, or a fabric type it fits poorly): get the break-up before pushing. Not counted in the figure above.`) : null,
    side.unsure_other ? h("li", {}, `${n0(side.unsure_other)} more the tool is unsure of, in or below the range: no rupee figure is given for them.`) : null,
    side.agreed ? h("li", {}, `${n0(side.agreed)} already agreed in the tracker: closed, and not in the figures above` + (side.agreed_above_range ? ` (those the tool is sure of were agreed Rs ${n0(side.agreed_above_range)} above the top of the usual range in all` : " (none above the top of its usual range") + (side.agreed_unsure ? `; ${n0(side.agreed_unsure)} of the agreed ${side.agreed_unsure === 1 ? "is a fabric" : "are fabrics"} the tool is unsure of, with no figure).` : ").")) : null,
    side.below_saving > 0 ? h("li", {}, `Below the usual range: Rs ${n0(side.below_saving)} under should-cost. A saving only if the specification held; never netted off the figure above.`) : null,
    side.counts["Check quote"] ? h("li", {}, `${n0(side.counts["Check quote"])} priced more than 30% below should-cost: check the price and the specification; counted nowhere.`) : null,
    side.no_metres ? h("li", {}, `${n0(side.no_metres)} with no metres: no rupee figure for them.`) : null];
  const swipe = () => h("p", { class: "muted swipe noprint" }, "Swipe the table sideways for the verdict and the money.");
  const table = (rows, paidWord, withNego) => h("div", { class: "gridscroll sup" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Fabric", "Description", "Should-cost", paidWord, "Against", "Metres", "Verdict", "Above range, Rs", withNego ? "Negotiation" : null].filter(Boolean).map((t, i) => h("th", { class: [2, 3, 4, 5, 7].includes(i) ? "n" : i === 1 ? "desc" : "" }, t)))),
    h("tbody", {}, rows.map(r => h("tr", {}, h("td", {}, code(r)), h("td", { class: "w desc" }, r.description || ""), h("td", { class: "n" }, n2(r.should)), h("td", { class: "n" }, n2(r.price), r.tracked && r.sheet_price && Math.abs(r.sheet_price - r.price) >= 0.005 ? h("div", { class: "muted" }, `${r.tracked === "Agreed" ? "agreed" : "now"}; sheet ${n2(r.sheet_price)}`) : null), h("td", { class: "n" }, pc(r.gap_pct)), h("td", { class: "n" }, n0(r.metres)),
      h("td", { class: "w" }, r.duplicate_of ? "Repeats " + r.duplicate_of : [r.tracked === "Agreed" ? h("b", {}, "Agreed \u00B7 ") : null, bandPill(r.band)]), h("td", { class: "n" }, r.above_range ? n0(r.above_range) : ""),
      withNego ? h("td", { class: "w" }, (() => { const row = state.rows.find(x => x.source === r.source && x.id === r.id); return row ? val(row, "nego") : ""; })()) : null)))));
  const qlist = (items, empty) => items.length ? h("ol", { class: "qs" }, items.map(q => h("li", {}, q.text || q))) : h("p", { class: "muted" }, empty);
  const shown = sp.all ? B.rows : B.rows.slice(0, 25);
  const trackWords = t => (t.warnings.length ? "Check a step · " : "") + (t.status === "Agreed" ? `Agreed Rs ${n2(t.agreed)}` + (t.first === null ? " (no mill quote recorded)" : t.won_per_m === 0 ? " (the first quote)" : ` (${n2(Math.abs(t.won_per_m))} ${t.won_per_m > 0 ? "below" : "above"} the first quote of ${n2(t.first)})`)
    : (t.reopened !== null ? "Open again: " : "Open: ") + (t.latest !== null ? `mill at Rs ${n2(t.latest)}` : "no mill quote yet") + (t.counter !== null ? `, our counter Rs ${n2(t.counter)}` : ""));
  fill(main, crumbs,
    h("div", { class: "dhead" }, h("div", {}, h("div", { class: "small" }, "Supplier" + (d.names.length > 1 ? " \u00B7 also written " + d.names.slice(1).join(", ") : "")), h("h1", {}, d.name), h("div", { class: "muted" }, `As of ${d.today}: quotes on that day's rates, purchases on the rates said at the foot of the page.`)),
      h("div", { class: "dicons noprint" }, can("do:draft") ? h("button", { type: "button", class: "btn line", onclick: () => draftDialog({ type: "supplier", mill: d.key }, d.name, d.key) }, "Draft a message to the mill") : null, ib("pdf", "Print this page", () => print()), ib("pin", "Show this mill's fabrics in the list", () => { state.filters.mill = [d.key]; state.cls = "*"; store.set("cls", "*"); state.tab = "items"; location.hash = "#rightcost"; }))),
    !d.ready ? h("p", { class: "muted" }, "The verdicts on the purchase orders are still being worked out; this page fills in when they are ready (about 20 seconds).") : null,
    h("div", { class: "stiles" },
      tile("Bought (purchase orders)", `${n0(B.fabrics)} ${B.fabrics === 1 ? "fabric" : "fabrics"}`, B.fabrics ? `${n0(B.metres)} m · Rs ${n0(B.value)} paid` : "none on record"),
      tile("Paid above the usual range", !B.above_range && B.unsure_high ? "Not sure yet" : `Rs ${n0(B.above_range)}`, (B.counts.Push ? `on ${n0(B.counts.Push)} Push ${B.counts.Push === 1 ? "fabric" : "fabrics"}, on ${B.rates && B.rates.dated ? "the order months' yarn rates where dated" : "today's rates"}` : B.unsure_high ? "none the tool is sure of" : "no fabric above its range") + (B.unsure_high ? ` \u00B7 ${n0(B.unsure_high)} more look high but the tool is unsure` : ""), B.above_range ? "red" : B.unsure_high ? "amber" : ""),
      tile("Quoted now (fabric list)", `${n0(Q.fabrics)} ${Q.fabrics === 1 ? "fabric" : "fabrics"}`, Q.fabrics ? `Rs ${n0(Q.above_range)} above the usual range, still to settle` + (Q.unsure_high ? ` \u00B7 ${n0(Q.unsure_high)} more look high but the tool is unsure` : "") + (Q.agreed ? ` \u00B7 ${Q.agreed} agreed` : "") + (Q.duplicates ? ` \u00B7 ${Q.duplicates} repeated ${Q.duplicates === 1 ? "row" : "rows"} left out` : "") : "no quote in the fabric list"),
      tile("Its sheets' sums", d.sums.length ? `${d.sums.length} off` : Q.sheets ? "none off" : "not checked", d.sums.length ? "see below" : Q.sheets ? "the mill's arithmetic agrees" : "no price sheet from this mill has been uploaded"),
      tile("Negotiation tracker", T.fabrics ? `${T.agreed} agreed, ${T.open} open` : "nothing tracked", T.agreed ? (T.won < 0 ? `Rs ${n0(Math.abs(T.won))} lost against first quotes` : `Rs ${n0(T.won)} won against first quotes` + (T.lost ? `, after Rs ${n0(T.lost)} lost` : "")) : "", T.won < 0 ? "red" : "")),
    h("section", { class: "sec" }, h("h2", {}, "Questions for the next meeting"),
      h("h3", { class: Q.fabrics ? null : "noprint" }, "On the quotes in hand"), qs.quoted.length ? qlist(qs.quoted, "") : h("p", { class: "muted" + (Q.fabrics ? "" : " noprint") }, Q.fabrics ? "Nothing to ask on the quotes in hand." : "No quote from this mill is in the fabric list. Upload its price sheet (New cost > Bulk upload) to get questions on it."),
      h("h3", {}, "From past purchases (already paid: use them for the next order of the same cloth)"), qlist(qs.bought, !B.fabrics ? "No purchase on record." : B.unsure_high ? "No purchase the tool is sure of was above its usual range; those that look high are asked about under Also." : "No purchase from this mill was above its usual range."),
      qs.general.length ? [h("h3", {}, "Also"), qlist(qs.general, "")] : null,
      d.hint ? h("p", { class: "muted noprint" }, d.hint) : null),
    Q.rows.length ? h("section", { class: "sec" }, h("h2", {}, "Quoted now"), h("p", { class: "muted" }, counts(Q) + "."), h("ul", { class: "mon" }, money(Q, false)), swipe(), table(Q.rows, "Quote", true),
      Q.not_costed.length ? h("p", { class: "muted" }, "Not costed: " + Q.not_costed.map(n => `${n.code} (${n.why})`).join("; ") + ".") : null) : null,
    d.sums.length ? h("section", { class: "sec" }, h("h2", {}, "The mill's own sums that are off"), h("ul", { class: "mon" }, d.sums.map(x => h("li", {}, h("b", {}, x.code), ": " + x.sums.join("; ") + (x.own_gap !== null && x.own_gap !== undefined && Math.abs(x.own_gap) >= 0.01 ? `. Its own build-up comes to Rs ${n2(x.own_price)}, Rs ${n2(Math.abs(x.own_gap))} ${x.own_gap > 0 ? "less than" : "more than"} the price it asks` + (x.own_at_stake ? ` (Rs ${n0(Math.abs(x.own_at_stake))} on the order)` : "") : "") + ".")))) : null,
    T.items.length ? h("section", { class: "sec" }, h("h2", {}, "Negotiations with this mill"), h("div", { class: "gridscroll sup" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Fabric", "Where it stands", "Last step", "Won, Rs"].map((t, i) => h("th", { class: i === 3 ? "n" : "" }, t)))),
      h("tbody", {}, T.items.map(t => h("tr", {}, h("td", {}, (() => { const row = state.rows.find(x => keyOf(x) === t.key); return row ? h("button", { type: "button", class: "code", onclick: () => { openDetail(row); state.detail.tab = "negotiation"; tabMemo(t.key, "negotiation"); } }, t.code) : t.code; })()), h("td", { class: "w" }, trackWords(t)), h("td", {}, t.last_date ? dayOf(t.last_date) : ""),
        h("td", { class: "n" + (t.won < 0 ? " loss" : "") }, t.status !== "Agreed" ? "open" : !t.counted ? "not counted" : t.won < 0 ? `${n0(Math.abs(t.won))} lost` : n0(t.won)))))))) : null,
    B.rows.length ? h("section", { class: "sec" }, h("h2", {}, "Bought"), h("p", { class: "muted" }, counts(B) + "."), h("ul", { class: "mon" }, money(B, true)), swipe(), table(shown, "Paid", false),
      B.rows.length > shown.length ? h("p", { class: "noprint" }, h("button", { type: "button", class: "btn line", onclick: () => { sp.all = true; render(); } }, `Show all ${n0(B.rows.length)} (the ${shown.length} with the most money above the range are shown)`)) : null,
      B.rows.length > shown.length ? h("p", { class: "muted printonly" }, `The ${shown.length} purchases with the most money above the range are printed, of ${n0(B.rows.length)}.`) : null) : null,
    typeof RP_PURCH !== "undefined" && (d.outliers || []).length ? h("section", { class: "sec" }, RP_PURCH.outliers(d.outliers, "this mill", true)) : null,      // stage 2
    h("p", { class: "muted", style: "margin-top:18px" }, "Quotes: should-cost and verdicts on today's rates. " + (B.rates && B.rates.text ? B.rates.text + " " : "") + "“Above the usual range” is the price less the top of the range for that fabric type, times the metres; it is counted only where the tool is sure of the fabric."));
}
function renderSelbar() {
  const bar = $("#selbar"), n = state.selection.size, pend = Object.keys(state.pending).length;
  if (!n && !pend) { bar.hidden = true; return; }
  bar.hidden = false;
  const picked = state.rows.filter(r => state.selection.has(keyOf(r)));
  fill(bar, 
    n ? [tipOn(h("button", { type: "button", class: "clear", onclick: () => { state.selection.clear(); render(); } }), "Clear the selection"), h("span", { class: "n" }, String(n)), h("span", { class: "lbl" }, n === 1 ? "row selected" : "rows selected")] : null,
    pend ? h("span", { class: "lbl", style: "margin-left:16px" }, `${pend} unsaved ${pend === 1 ? "change" : "changes"}`) : null,
    pend ? h("button", { type: "button", class: "btn fill", onclick: saveEdits }, "Save") : null,
    pend ? h("button", { type: "button", class: "btn", onclick: () => { state.pending = {}; render(); } }, "Discard") : null,
    h("span", { class: "spacer" }),
    n ? [h("button", { type: "button", class: "btn", onclick: () => bulkEdit(picked) }, "Edit"), h("button", { type: "button", class: "btn", onclick: () => share(picked) }, "Share"),
      ib("dots", "More", e => menu(e.currentTarget, [
        { label: "Add to a saved search", run: () => addToSaved(picked) },
        { label: "Download selected", run: () => download("/api/costs/download", { keys: picked.map(keyOf), extra: extras(picked) }, "RightCost selected.xlsx").then(() => toast("Downloaded")).catch(err => toast(err.message, false)) },
        { label: picked.length === 1 ? "Open in Create cost" : "Open in Create cost (tick one)", run: () => picked.length === 1 ? openCostPopup(picked[0]) : toast("Tick one row to open it", false) },
        { label: "Negotiation pack for the ticked rows", run: () => moreAction("Negotiation pack", picked) },
        !can("do:draft") ? null : { label: "Draft a message to the mill on the ticked rows", run: () => draftDialog({ type: "rows", keys: picked.map(keyOf) }, [...new Set(picked.map(r => r.supplier).filter(Boolean))][0] || "the mill", (picked.find(r => r.mill) || {}).mill) },
        !can("do:mark_seen") ? null : { label: "Mark quote alerts seen (for everyone)", run: () => { const ids = picked.filter(r => val(r, "has_alert") === "Yes").map(r => r.id); if (!ids.length) return toast("None of the ticked rows has a quote alert to look at", false); markSeen(ids); } },
        !can("do:mark_seen") ? null : { label: "Bring back quote alerts marked seen", run: () => { const ids = picked.filter(r => val(r, "has_alert") === "Seen").map(r => r.id); if (!ids.length) return toast("None of the ticked rows has an alert marked seen", false); markSeen(ids, true); } },
      ].filter(Boolean), { right: true }))] : null);
}

// ------------------------------------------------------------------ detail page and quick view
function fields(r) {
  return [["Fabric code", r.code], ["Source", r.source], ["Description", r.description], ["Supplier", r.supplier], ["Route", r.route], ["Weave", r.weave], ["Weave group", r.weave_group],
    ["Finish", r.finish], ["Pattern", r.pattern], ["Warp yarn", r.warp], ["Weft yarn", r.weft], ["EPI × PPI", r.epi ? `${n0(r.epi)} × ${n0(r.ppi)}` : ""], ["Finished width (in)", r.width],
    ["Weight (g/m²)", r.gsm ? Number(r.gsm).toFixed(0) : ""], ["Should-cost Rs/m", n2(r.should)], ["Should-cost Rs/kg", r.per_kg ? n0(r.per_kg) : ""], [r.source === "Purchase orders" ? "Price paid Rs/m" : "Mill's quote Rs/m", r.source === "Purchase orders" && r.price === null && (r.outliers || []).length ? "None: bought only on ZLOI orders (see Outliers below)" : r.source === "Purchase orders" && r.price === null && /^not in the purchase history/.test(r.worked_out_again || "") ? "None: not in the purchase history (see Worked out again)" : n2(r.price)],
    ["Against should-cost", r.price && r.gap !== null && r.gap !== undefined ? `Rs ${n2(Math.abs(r.gap))} ${r.gap >= 0 ? "above" : "below"} (${pc(r.gap_pct)})` : ""], ["Against the usual range", r.band + (r.range ? ` (usual ${pc(r.range[0])} to ${pc(r.range[1])})` : "")], ["Why the tool is unsure", (r.band === "Ask break-up" && r.why_unsure || []).join("; ")], ["Metres", n0(r.metres)],
    [r.source === "Purchase orders" ? "Paid against should-cost, Rs" : "Quote against should-cost, Rs (not paid)", r.excess === null || r.excess === undefined ? "" : `${n0(Math.abs(r.excess))} ${r.excess >= 0 ? "above" : "below"}`],
    ["Duplicate of", r.duplicate_of || ""], ["Fab group", r.fab_group ? `${r.fab_group}: ${r.fab_group_name}` : r.fab_group_name ? "Not grouped: " + r.fab_group_name : ""], ["Order size (pilot slab)", r.qty_band && r.qty_band !== "Not applied" ? `${r.order_size || ""} (not used: the quantity band is)` : r.order_size], ["Quantity band (mill rate card)", r.qty_band], ["Placeholder rates used", r.placeholders || "None"], ["Held back (calibration test)", val(r, "held_back")],
    ["Added on", r.added || ""], ["Not costed because", (r.problems || []).join("; ")],
    ["Worked out again", r.worked_out_again ? r.worked_out_again.charAt(0).toUpperCase() + r.worked_out_again.slice(1) : ""], ["Outliers (ZLOI)", (r.outliers || []).length ? `${r.outliers.length}, left out of every figure (listed below)` : ""]].filter(([, v]) => v !== "" && v !== null && v !== undefined);
}
function quickView(r) {
  document.querySelectorAll(".side").forEach(e => e.remove());
  const p = h("aside", { class: "side", "aria-label": "Quick view" }, h("div", { style: "display:flex;justify-content:space-between;align-items:center" }, h("h2", {}, r.code), ib("x", "Close", () => p.remove())),
    h("div", { style: "color:var(--text2);font-size:12px" }, r.description || ""), h("dl", { class: "kv" }, fields(r).map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
    h("div", { style: "margin-top:14px;display:flex;gap:8px" }, h("button", { type: "button", class: "btn fill", onclick: () => { p.remove(); openDetail(r); } }, "Open"), h("button", { type: "button", class: "btn line", onclick: () => openCostPopup(r) }, "Open in Create cost")));
  document.body.append(p);
}
// the tab a fabric was left on, so a reload or Back returns to it (this browser tab only)
function tabMemo(key, tab) {
  try { const m = JSON.parse(sessionStorage.getItem("rc-tabs") || "{}"); if (tab === undefined) return m[key]; m[key] = tab; sessionStorage.setItem("rc-tabs", JSON.stringify(m)); } catch (e) { /* no memory */ }
}
function openDetail(r) {
  closeLayers(); state.library = null; state.frame = null;
  state.detail = { key: keyOf(r), tab: "item", editing: false }; tabMemo(keyOf(r), "item");
  if (decodeURIComponent(location.hash.slice(1)) !== "item/" + keyOf(r)) { location.hash = "#item/" + encodeURIComponent(keyOf(r)); return; }
  state.recent = [{ key: keyOf(r), code: r.code, at: new Date().toISOString() }, ...state.recent.filter(v => v.key !== keyOf(r))].slice(0, 12); store.set("recent", state.recent);
  scrollTo(0, 0); render();
}
function renderDetail(main) {
  const r = state.rows.find(x => keyOf(x) === state.detail.key);
  if (!r) { if (!state.rows.length) return fill(main, h("div", { class: "empty" }, "Loading\u2026")); location.hash = "#rightcost"; return; }
  const d = state.detail, k = keyOf(r);
  const crumbs = h("div", { class: "crumb" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }), "\u00A0\u203A\u00A0", h("button", { type: "button", onclick: () => { location.hash = "#rightcost"; } }, CONFIG.appName), "\u00A0\u203A\u00A0", h("span", {}, r.code));
  const headIcons = h("div", { class: "dicons" }, ib("pin", "Show in the list", () => { state.search.active = { text: r.code, mode: "exact" }; state.search.text = r.code; state.cls = r.source; location.hash = "#rightcost"; }),
    ib("pdf", "Print this page", () => print()), ib("comment", "Remarks", () => { d.tab = "item"; d.editing = true; render(); setTimeout(() => { const el = $("#f-remarks"); if (el) el.focus(); }, 0); }),
    ib("open", "Open in Create cost", () => openCostPopup(r)), r.source === "Purchase orders" && typeof RP_PURCH !== "undefined" ? ib("chart", "Price over time (purchase history)", () => RP_PURCH.openHistory(r.code)) : null);
  const head = h("div", { class: "dhead" }, h("div", { class: "bigimg", style: { background: ROUTE_COLOR[r.route] || "#B9BEC7" } }, (r.route || "").split(/[ /]/)[0].toUpperCase()), h("div", {}, h("div", { class: "small" }, `${r.code} · ${r.source}`), h("h1", {}, r.description || r.code)), headIcons);
  const tabs = h("div", { class: "tabs" }, [["item", "Item"], ["costing", "Costing"], ["negotiation", "Negotiation"], ["log", "Log"]].map(([t, l]) => h("button", { type: "button", class: "tab" + (d.tab === t ? " on" : ""), onclick: () => { d.tab = t; tabMemo(k, t); render(); if (t === "negotiation" || t === "log") loadNegos(); } }, l)));
  let content;
  if (d.tab === "item") {
    const edit = state.edits[k] || {};
    const statusIn = h("select", { id: "f-status", disabled: !d.editing || null }, STATUS.map(o => h("option", {}, o))); statusIn.value = edit.status || "Not started";
    const remIn = h("input", { id: "f-remarks", type: "text", value: edit.remarks || "", disabled: !d.editing || null });
    content = [h("div", { style: "margin-top:12px;display:flex;gap:8px" }, d.editing ? [h("button", { type: "button", class: "btn fill", onclick: () => { state.edits[k] = { status: statusIn.value, remarks: remIn.value }; store.set("edits", state.edits); addLog(`${r.code}: status ${statusIn.value}${remIn.value ? `, remarks "${remIn.value}"` : ""}`); d.editing = false; toast("Saved"); render(); } }, "Save"), h("button", { type: "button", class: "btn", onclick: () => { d.editing = false; render(); } }, "Discard")] : h("button", { type: "button", class: "btn line", onclick: () => { d.editing = true; render(); } }, "Edit status and remarks")),
      h("div", { class: "form2" }, h("div", { class: "f" }, h("span", {}, "Status"), statusIn), h("div", { class: "f" }, h("label", { for: "f-remarks" }, "Remarks"), remIn), fields(r).map(([k2, v]) => h("div", { class: "f" }, h("span", {}, k2), h("span", {}, String(v))))),
      h("p", { style: "color:var(--text2);font-size:11px;margin-top:10px" }, "Status and remarks are kept in this browser only."),
      typeof RP_PURCH !== "undefined" ? RP_PURCH.outliers(r.outliers, "this fabric") : null];       // stage 2: ZLOI lines, shown apart
  } else if (d.tab === "costing") {
    if (r.buckets) content = costingTab(r);
    else if (r.problems && r.problems.length) content = h("div", { class: "empty" }, "Not costed yet: " + r.problems.join("; ") + ".", h("div", { style: "margin-top:10px" }, h("button", { type: "button", class: "btn fill", onclick: () => openCostPopup(r) }, "Open in Create cost")));
    else { content = h("div", { class: "buckets" }, "Working it out…"); liveCosting(r, content); }
  } else if (d.tab === "negotiation") {
    const brief = h("div", { class: "brief" }, "Working it out\u2026"), slot = h("div", {}, trackerCard(r));
    const al = r.source === "Fabric list" ? (state.alerts.all || {})[r.id] : null;
    const flagged = al ? h("div", { class: "brief flagged" }, h("h3", { style: "margin:0 0 6px;font-size:15px" }, "Flagged on this quote" + (al.state === "seen" ? " (marked seen)" : al.state === "agreed" ? " (agreed since)" : "")),
      h("ul", {}, al.flags.map(f => h("li", {}, h("b", {}, ((state.alerts.kinds || {})[f.kind] || f.kind) + ": "), f.text))),
      !can("do:mark_seen") ? null : al.state === "live" ? h("button", { type: "button", class: "btn line", onclick: () => markSeen([r.id]) }, "Mark seen (for everyone)") : al.state === "seen" ? h("button", { type: "button", class: "btn line", onclick: () => markSeen([r.id], true) }, "Bring the alert back") : null) : null;
    const was = briefShould[k]; negotiationTab(r, brief).then(() => { if (briefShould[k] !== was && slot.isConnected) fill(slot, trackerCard(r)); });        // the tracker measures against the brief's should-cost
    content = [flagged, brief, slot];
  } else {
    const mine = state.log.filter(x => x.text.startsWith(r.code + ":")).map(x => ({ at: x.at, text: x.text.slice(r.code.length + 2) + " (this browser)" }));
    const ng = state.negos[k] || {}, who = x => x ? ` (${x})` : "", stepText = e => `${e.kind} Rs ${n2(e.price)}, dated ${dayOf(e.date)}${e.note ? ` \u2013 ${e.note}` : ""}`;
    const steps = [...(ng.events || []).map(e => ({ at: e.at, text: `Negotiation step recorded${who(e.by)}: ${stepText(e)}` })),
      ...(ng.removed || []).flatMap(e => [{ at: e.at, text: `Negotiation step recorded${who(e.by)}, since removed: ${stepText(e)}` }, { at: e.removed_at, text: `Negotiation step removed${who(e.removed_by)}: ${stepText(e)}` }])];
    const all = [...mine, ...steps].sort((a, b) => String(b.at).localeCompare(String(a.at)));
    content = h("div", { class: "log" }, all.length ? all.map(x => h("div", {}, `${new Date(x.at).toLocaleString("en-IN")} · ${x.text}`)) : h("div", { class: "empty" }, "Nothing recorded yet: no negotiation steps (recorded or removed), and no changes in this browser."));
  }
  fill(main, crumbs, head, tabs, content);
  renderSelbar();
}
function costingTab(r, when) {
  const b = r.buckets, top = Math.max(...Object.values(b).map(v => Math.abs(v || 0)), 1);
  return h("div", { class: "buckets" }, Object.entries(b).map(([name, v]) => h("div", { class: "bk" }, h("span", {}, name), h("div", {}, h("div", { class: "b", style: { width: Math.abs(v || 0) / top * 100 + "%" } })), h("span", { style: "text-align:right" }, n2(v)), h("span", { style: "text-align:right;color:var(--text2)" }, r.should ? (100 * (v || 0) / r.should).toFixed(1) + "%" : ""))),
    h("div", { class: "bk tot" }, h("span", {}, "Should-cost"), h("span"), h("span", { style: "text-align:right" }, n2(r.should)), h("span", { style: "text-align:right" }, "100%")),
    r.price ? h("div", { class: "bk" }, h("span", {}, r.source === "Purchase orders" ? "Price paid" : "Mill's quote"), h("span"), h("span", { style: "text-align:right" }, n2(r.price)), h("span", { style: "text-align:right" }, pc(r.gap_pct))) : null,
    h("p", { style: "color:var(--text2);font-size:11px" }, when === "today" ? "Rs per metre, on today's rates." : r.rates && r.rates.dated ? "Rs per metre, with the yarn on the dated rates of the order month (below) and every other rate today's. Create cost works on today's rates." : "Rs per metre, as costed in the purchase-order pilot (worked out again from the purchase lines where ZLOI orders or later purchases change its metres), on today's rates. The Negotiation tab and Create cost give the same should-cost."),
    when !== "today" && r.rates ? h("p", { class: "rates-note", style: "color:var(--text2);font-size:11px" }, "Rates: " + r.rates.note) : null,         // stage 5: which month's rates
    h("button", { type: "button", class: "btn fill", onclick: () => openCostPopup(r) }, "Open in Create cost"));
}
async function liveCosting(r, box) {
  // a fabric-list row is costed on today's rates, as the list does
  try {
    const res = await (await fetch("/api/cost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r.choices) })).json();
    const b = Object.fromEntries(res.buckets.map(x => [x.name, x.amount]));
    fill(box, costingTab(Object.assign({}, r, { buckets: b, should: res.total_per_m }), "today"));
  } catch (e) { box.textContent = "Could not cost it: " + e.message; }
}
async function negotiationTab(r, box) {
  if (r.problems && r.problems.length) { box.textContent = "Not costed yet: " + r.problems.join("; ") + ". Open it in Create cost to finish it."; return; }
  // the price the brief judges: the agreed price or the mill's latest in the tracker, else the price on the row
  const ng = negoOf(keyOf(r)), s_ = ng && ng.summary, tracked = s_ ? (s_.status === "Agreed" ? s_.agreed : s_.latest) : null, price = tracked ?? r.price;
  if (!r.choices || !price) { box.textContent = "No price on this row and no mill price in the tracker yet, so there is nothing to judge."; return; }
  const what = tracked === null ? "the price" : s_.status === "Agreed" ? "the agreed price" : "the mill's latest price";
  try {
    // stage 5: a purchase order is judged on the yarn rates of its order month (GP's decision), a quote on today's
    const onMonth = r.source === "Purchase orders" && r.rates && r.rates.month ? { _rates_on: r.rates.month } : {};
    const res = await (await fetch("/api/cost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({}, r.choices, { "Quoted price (Rs/m)": price }, r.metres ? { "Order quantity (m)": r.metres } : {}, onMonth)) })).json();
    const ratesWords = res.rates_of && res.rates_of.month ? (res.rates_of.dated ? `On the yarn rates of ${res.rates_of.label} (the order month) and today's other rates` : `On today's rates (there is no dated yarn rate for the order month, ${res.rates_of.label})`) : "On today's rates";
    if (res.total_per_m) briefShould[keyOf(r)] = res.total_per_m;
    const b = res.brief; if (!b) { box.textContent = "No brief: the price is not usable."; return; }
    const label = { push: ["Push", "#E5484D"], fair: ["Fair", "#2E9E5B"], below: ["Below", "#3D8BFD"], ask: ["Ask for the break-up", "#B98900"] }[b.stance];
    const done = s_ && s_.status === "Agreed";
    fill(box, h("div", {}, h("span", { class: "st", style: { background: label[1] + "22", color: label[1] } }, b.implausible ? "Check the quote first" : done ? { push: "Agreed above the usual range", fair: "Agreed in the usual range", below: "Agreed below the usual range", ask: "Agreed; the tool is unsure of this fabric" }[b.stance] : label[0]),
        ` ${ratesWords} the should-cost is Rs ${n2(b.should)}; ${what} is Rs ${n2(b.quote)}, Rs ${n2(Math.abs(b.gap))} ${b.gap >= 0 ? "above" : "below"}.`,
        tracked !== null && r.price && Math.abs(tracked - r.price) >= 0.005 ? ` (The ${r.source === "Purchase orders" ? "purchase order" : "fabric list"} has Rs ${n2(r.price)}; this brief follows the tracker below.)` : ""),
      h("ul", {}, h("li", {}, `Usual range for this fabric: Rs ${n2(b.lower)} to Rs ${n2(b.settle_up_to)} (${b.band.why}).`), b.stance === "push" && !done ? h("li", {}, s_ && s_.counter !== null ? `You have countered at Rs ${n2(s_.counter)}` + (s_.counter <= b.settle_up_to ? `: do not open above it. Aim for Rs ${n2(s_.counter)} to Rs ${n2(b.settle_up_to)}, the top of the usual range.` : `, which is above the top of the usual range (Rs ${n2(b.settle_up_to)}).`) : `Open at Rs ${n2(b.open_at)}; aim for Rs ${n2(b.settle_up_to)}.`) : null,
        b.weak.length ? h("li", {}, "Why no target: " + b.weak.join("; ") + ".") : null, (b.caveats || []).map(c => h("li", {}, c)),
        b.at_stake !== null && b.quantity ? h("li", {}, `On ${n0(b.quantity)} m that is Rs ${n0(Math.abs(b.at_stake))} ${b.gap >= 0 ? "above" : "below"} should-cost.`) : null),
      h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, h("button", { type: "button", class: "btn fill", onclick: () => openCostPopup(r) }, tracked !== null && r.price && Math.abs(tracked - r.price) >= 0.005 ? "Open in Create cost (on the row's own price)" : "Full brief in Create cost"),
        r.supplier && !done && can("do:draft") ? h("button", { type: "button", class: "btn line", onclick: () => draftDialog({ type: "fabric", key: keyOf(r) }, r.supplier, r.mill) }, "Draft a message to the mill") : null));
  } catch (e) { box.textContent = "Could not work it out: " + e.message; }
}

// ------------------------------------------------------------------ negotiation tracker
/* Each step with the mill, in order: its quote, our counter, a revised quote, the agreed price. What was
   won is the first quote less the agreed price, times the metres. Kept on the server for everyone. */
const briefShould = {}, drafts = {};
const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const dayOf = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
function negoWords(rec, should) {
  const s_ = rec.summary, ref = s_.status === "Agreed" ? s_.agreed : s_.latest, out = [];
  let head = s_.status === "Agreed" ? `Agreed at Rs ${n2(s_.agreed)}` : s_.latest !== null ? `Open: the mill is at Rs ${n2(s_.latest)}` + (s_.counter !== null ? `, our counter Rs ${n2(s_.counter)}` : "")
    : `Open: our counter is Rs ${n2(s_.counter)}; no mill quote recorded yet`;
  if (s_.reopened !== null && s_.reopened !== undefined) head += ` (open again after an agreement at Rs ${n2(s_.reopened)})`;
  if (s_.won_per_m !== null && (s_.status === "Agreed" || s_.won_per_m !== 0)) {
    const d = s_.won_per_m, money = s_.status === "Agreed" && s_.warnings.length ? " (no rupee total, and not counted as won, until the step flagged below is put right)" : s_.won === null ? " (no metres on this fabric, so no rupee total)"
      : d === 0 ? "" : s_.status === "Agreed" ? ` (Rs ${n0(Math.abs(s_.won))} ${d > 0 ? "saved" : "more"} on ${n0(rec.metres)} m${d > 0 ? "" : ": a loss"})` : ` (Rs ${n0(Math.abs(s_.won))} ${d > 0 ? "less" : "more"} on ${n0(rec.metres)} m if agreed there)`;
    out.push(d === 0 ? `the same as the first quote of Rs ${n2(s_.first)}` : `Rs ${n2(Math.abs(d))} a metre ${d > 0 ? "below" : "above"} the first quote of Rs ${n2(s_.first)}${money}`);

  }
  if (s_.status === "Agreed" && s_.first === null) out.push("no mill quote is recorded, so nothing is counted as won: record the mill's first quote, with its date");
  if (ref !== null && should) { const g = ref - should, w = s_.status === "Agreed" ? "the agreed price is" : "the mill's price is"; out.push(Math.abs(g) < 0.005 ? `${w} today's should-cost of Rs ${n2(should)}` : `${w} Rs ${n2(Math.abs(g))} a metre ${g > 0 ? "above" : "below"} today's should-cost of Rs ${n2(should)}`); }
  return [head, out];
}
function trackerCard(r) {
  const k = keyOf(r), rec = negoOf(k), s_ = rec && rec.summary, should = briefShould[k] || r.should;
  const box = h("div", { class: "brief tracker" });
  const steps = rec ? rec.events : [];           // in the server's order: by date, the agreed price last on its day
  const lastKind = steps.length ? steps[steps.length - 1].kind : null, dr = drafts[k] || {};
  const kind = h("select", { "aria-label": "What happened" }, state.negoKinds.map(x => h("option", {}, x)));
  kind.value = dr.kind || (!lastKind ? "Mill's quote" : lastKind === "Our counter" || lastKind === "Agreed" ? "Mill's revised quote" : "Our counter");
  const minDay = (() => { const d = new Date(); d.setDate(d.getDate() - 730); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); })();
  const price = h("input", { type: "number", step: "0.01", min: "0", inputmode: "decimal", placeholder: "Rs per metre", "aria-label": "Price, Rs per metre", value: dr.price ?? (!rec && r.price ? r.price : "") });
  const date = h("input", { type: "date", value: dr.date || today(), max: today(), min: minDay, "aria-label": "Date" });
  const note = h("input", { type: "text", maxlength: "500", placeholder: "Note (optional): what was said", "aria-label": "Note", value: dr.note || "" });
  const msg = h("p", { class: "formmsg", role: "alert", hidden: true }), say = t => { msg.textContent = t; msg.hidden = !t; };
  const asked = { stamp: null, at: 0 }; let busy = false;
  const btn = h("button", { type: "button", class: "btn fill" }, "Record");
  const keep = () => { drafts[k] = { kind: kind.value, price: price.value, date: date.value, note: note.value }; };
  [kind, price, date, note].forEach(el => { el.addEventListener("input", keep); el.addEventListener("change", keep); });
  const add = async () => {
    const p = Number(price.value);
    if (!price.value || !(p > 0)) { say("Type the price in rupees per metre."); price.focus(); return; }
    if (!date.value) { say("Choose the date."); date.focus(); return; }
    if (date.value > today()) { say("The date is in the future."); date.focus(); return; }
    if (date.value < minDay) { say(`The date is ${dayOf(date.value)}, more than two years ago: check the year.`); date.focus(); return; }
    if (p < 1 || p > 50000) { say("A price per metre is between Rs 1 and Rs 50,000: check what was typed."); price.focus(); return; }
    // a figure that looks mistyped is asked about once: against the should-cost (or the row's price), and against the first quote
    const base = should || r.price, first = s_ && s_.first;
    const odd = base && (p > 1.5 * base || p < 0.67 * base) ? `${should ? "the should-cost" : "the price on the row"} of Rs ${n2(base)}` : first && (p > 1.25 * first || p < 0.75 * first) ? `the mill's first quote of Rs ${n2(first)}` : null;
    const stamp = `${kind.value}|${price.value}`;
    if (odd && (asked.stamp !== stamp || Date.now() - asked.at < 700)) { if (asked.stamp !== stamp) { asked.stamp = stamp; asked.at = Date.now(); } say(`Rs ${n2(p)} is a long way from ${odd}. If it is right, press Record again.`); price.focus(); return; }
    if (busy) return; busy = true; btn.disabled = true; say("");
    try {
      const res = await fetch("/api/negotiations/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        key: k, kind: kind.value, price: price.value, date: date.value, note: note.value, code: r.code, supplier: r.supplier, description: r.description, source: r.source, metres: r.metres, should, row_price: r.price, seen: steps.length }) });
      if (res.status === 409) { const t = (await res.json()).detail; await loadNegos(true); toast(t, false); return; }
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      state.negos[k] = await res.json(); delete drafts[k]; if (state.detail) state.detail.further = false; toast("Recorded"); render(); loadAlerts();
    } catch (e) { say(e.message); toast(e.message, false); } finally { busy = false; btn.disabled = false; }
  };
  const words = rec ? negoWords(rec, should) : null;
  const other = r.duplicate_of ? state.rows.find(x => x.source === r.source && x.code === r.duplicate_of && !x.duplicate_of) : null, otherN = other && negoOf(keyOf(other));
  fill(box, h("h3", { style: "margin:0 0 6px;font-size:15px" }, "Where it stands with the mill"),
    !rec && r.duplicate_of ? null : !rec ? h("p", { style: "margin:4px 0 10px;color:var(--text2)" }, "Nothing recorded yet. Record the mill's quote, then each counter and revision, and the agreed price.")
      : h("p", { style: "margin:4px 0 10px" }, h("b", { class: s_.status === "Agreed" && s_.won_per_m < 0 ? "loss" : null }, words[0]), words[1].map(w => " · " + w)),
    rec && s_.warnings.length ? h("ul", { class: "warns" }, s_.warnings.map(w => h("li", {}, w))) : null,
    steps.length ? h("table", { class: "steps" }, h("tbody", {}, steps.map(e => h("tr", {}, h("td", { class: "d" }, dayOf(e.date)), h("td", { class: "k" }, e.kind), h("td", { class: "n" }, "Rs " + n2(e.price)),
      h("td", { class: "note" }, e.note || ""),
      !can("do:record_steps") ? null : h("td", { class: "x" }, h("button", { type: "button", class: "btn rm", "aria-label": `Remove this step: ${e.kind} Rs ${n2(e.price)}`, title: "Remove this step", onclick: async ev => { const b = ev.currentTarget; if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Sure?"; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = "Remove"; } }, 4000); return; }
        try { const res = await fetch("/api/negotiations/remove", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k, id: e.id }) }); if (!res.ok) throw new Error((await res.json()).detail || res.statusText); toast("Removed (the Log tab keeps a record)"); } catch (err) { toast(err.message, false); }
        await loadNegos(true); loadAlerts(); } }, "Remove")))))) : null,
    r.duplicate_of && !rec ? h("p", { style: "margin:4px 0 0" }, `This row repeats the order of ${r.duplicate_of}, so its negotiation is kept there and the order is counted once. `,
        otherN ? h("b", {}, `On ${r.duplicate_of}: ${val(other, "nego")}. `) : `Nothing is recorded on ${r.duplicate_of} yet. `, other ? h("button", { type: "button", class: "code", onclick: () => { openDetail(other); state.detail.tab = "negotiation"; tabMemo(keyOf(other), "negotiation"); } }, `Open ${r.duplicate_of}`) : null)
      : !can("do:record_steps") ? h("p", { style: "margin:4px 0 0;color:var(--text2)" }, `Your role (${RPA.me.role}) may look at the steps but not record them.`)
      : s_ && s_.status === "Agreed" && !(state.detail && state.detail.further) && !drafts[k] ? h("div", {}, h("button", { type: "button", class: "btn line", onclick: () => { state.detail.further = true; render(); } }, "The price was reopened: record a further step"))
      : [h("div", { class: "stepform" }, kind, price, date, note, btn), msg],
    r.duplicate_of && rec ? h("p", { style: "margin:8px 0 0;font-size:12px" }, `This row repeats the order of ${r.duplicate_of}: it is not counted in what was won. Keep the steps on ${r.duplicate_of}.`) : null,
    h("p", { style: "margin:8px 0 0;font-size:12px;color:var(--text2)" }, "Kept on the server: everyone using RightPrice sees the same steps (this page looks for new ones every half minute). Steps run in date order; on one day the agreed price comes last. What was won is the mill's first quote less the agreed price, times the metres; a fabric with a step to check is not counted until it is put right."));
  btn.addEventListener("click", add);
  [price, note].forEach(el => el.addEventListener("keydown", e => { if (e.key === "Enter") add(); }));
  return box;
}
/* The steps are shared, so another person (or another tab) may have added one: read them again when the
   Negotiation tab or the list opens and when the window is looked at again. Only a change redraws the page. */
// ------------------------------------------------------------------ a draft to the mill: e-mail and WhatsApp, edited and copied here, never sent
/* scope: {type: "fabric", key} | {type: "rows", keys} | {type: "supplier", mill}. Each press of Draft writes a fresh one. */
function draftDialog(scope, title, millKey) {
  const me = store.get("draftMe", { writer: "", contact: {} }), millId = millKey || scope.mill || title;
  const ask = h("select", { "aria-label": "What to ask for" }, [["both", "The break-up and a revised price"], ["breakup", "The cost break-up only"], ["price", "A revised price"]].map(([v, l]) => h("option", { value: v }, l)));
  const writer = h("input", { type: "text", maxlength: "60", placeholder: "Your name, as you sign", value: me.writer || "", "aria-label": "Your name" });
  const contact = h("input", { type: "text", maxlength: "60", placeholder: "Who it goes to at the mill", value: (me.contact || {})[millId] || "", "aria-label": "Contact at the mill" });
  const out = h("div", { class: "draftout" }), go = h("button", { type: "button", class: "btn fill" }, "Write the draft");
  let dirty = false, armed = false;
  const copy = (el, what) => h("button", { type: "button", class: "btn line", onclick: async () => {
    try { await navigator.clipboard.writeText(el.value); } catch (e) { el.select(); document.execCommand("copy"); }
    const left = (el.value.match(/\[(Name|Your name)\]/g) || []).length;
    toast(left ? `${what} copied, but it still has ${left === 1 ? "a blank" : "blanks"} to fill: ${[...new Set(el.value.match(/\[(Name|Your name)\]/g))].join(", ")}` : what + " copied", !left); } }, "Copy " + what.toLowerCase());
  const run = async () => {
    if (dirty && !armed) { armed = true; go.textContent = "Your edits will be replaced: press again"; setTimeout(() => { if (armed) { armed = false; go.textContent = "Write another"; } }, 5000); return; }
    armed = false; dirty = false;
    store.set("draftMe", { writer: writer.value, contact: Object.assign({}, me.contact, { [millId]: contact.value }) });
    go.disabled = true; go.textContent = "Writing…"; fill(out, h("p", { class: "muted" }, "Writing a fresh draft: this can take up to half a minute."));
    try {
      const res = await fetch("/api/draft", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope, ask: ask.value, writer: writer.value, contact: contact.value }) });
      const d = await res.json(); if (!res.ok) throw new Error(d.detail || res.statusText);
      const subj = h("input", { type: "text", value: d.subject, "aria-label": "Subject" }), mail = h("textarea", { rows: "12", "aria-label": "E-mail" }), wa = h("textarea", { rows: "4", "aria-label": "WhatsApp message" });
      mail.value = d.email; wa.value = d.whatsapp;
      [subj, mail, wa].forEach(el => el.addEventListener("input", () => { dirty = true; if (armed) { armed = false; go.textContent = "Write another"; } }));
      fill(out, h("p", { class: "draftnote" + (d.source === "claude" ? "" : " warn") }, d.note),
        h("p", { class: "muted" }, `To ${d.mill}, about ${d.fabrics.join(", ")}.`,
          d.left_out.length ? ` Left for a second message (one stays readable with at most 12 fabrics): ${d.left_out.length > 12 ? d.left_out.length + " more fabrics; tick the ones you want in Right cost and draft on those" : d.left_out.join(", ")}.` : "",
          d.skipped.length ? " Not in this message: " + d.skipped.map(x => `${x.code} (${x.why})`).join("; ") + "." : ""),
        d.adjusted.length ? h("p", { class: "muted" }, "What is asked differs by fabric: " + d.adjusted.join("; ") + ".") : null,
        h("label", {}, "Subject", subj), h("label", {}, "E-mail, for the mill (edit it here before copying)", mail), h("div", { class: "acts2" }, copy(mail, "E-mail"), copy(subj, "Subject")),
        h("label", {}, "WhatsApp, for the mill", wa), h("div", { class: "acts2" }, copy(wa, "WhatsApp")),
        h("div", { class: "mynotes" }, h("b", {}, "Your notes, not for the mill"), h("p", { class: "muted", style: "margin:2px 0 6px" }, "The working behind this message. It is never copied. It may name figures you would not show a mill (the top of your range, your counter)."),
          h("ul", {}, d.notes.map(pt => h("li", {}, pt)))));
      go.textContent = d.source === "claude" ? "Write another (a fresh draft)" : "Fill the template again";
    } catch (e) { fill(out, h("p", { class: "draftnote warn" }, e.message)); go.textContent = "Write the draft"; }
    go.disabled = false;
  };
  go.addEventListener("click", run);
  ask.addEventListener("change", () => { if (out.firstChild) go.textContent = "Write it again for this choice"; });
  [writer, contact].forEach(el => el.addEventListener("keydown", e => { if (e.key === "Enter") run(); }));
  const s = dialog("Draft a message to " + title, h("div", { class: "draftbox" },
    h("p", { class: "muted" }, "An e-mail and a WhatsApp-length message asking the mill for the break-up or a better price, with the figures of the fabrics chosen and nothing else. You edit and copy it; RightPrice sends nothing. Closing this window discards the draft."),
    h("div", { class: "draftform" }, ask, writer, contact, go), out),
    [h("button", { type: "button", class: "btn", onclick: () => s.remove() }, "Close")]);
  s.querySelector(".dialog").classList.add("wide");
}

// ------------------------------------------------------------------ quote alerts: the count on the rail, the column and the filter
function showAlerts() { state.cls = "Fabric list"; store.set("cls", state.cls); state.filters = { has_alert: ["Yes"] }; state.saved = "Default"; state.tab = "items"; state.search.active = null; state.search.text = ""; if (decodeURIComponent(location.hash.slice(1)).split("?")[0] !== "rightcost") location.hash = "#rightcost"; else rerunWithSkeleton(); }
function paintBadge() {
  const b = document.querySelector('.rail .item[data-id="costs"]'); if (!b) return;
  b.querySelectorAll(".badge").forEach(e => e.remove());
  const n = state.alerts.count;
  b.setAttribute("aria-label", n ? `Right cost, ${n} quote ${n === 1 ? "alert" : "alerts"} to look at` : "Right cost");
  if (n) b.append(h("span", { class: "badge", title: `${n} newly quoted ${n === 1 ? "fabric needs" : "fabrics need"} a look: above the usual range, sums off, a repeated order, or far below should-cost` }, n > 99 ? "99+" : String(n)));
}
async function loadAlerts() {
  await RPA.ready; if (!canAny("page:rightcost", "page:dashboard")) return;
  try {
    const a = await (await fetch("/api/alerts")).json(), wasAll = JSON.stringify(state.alerts.all);
    state.alerts = a; paintBadge();
    if (wasAll !== JSON.stringify(a.all) && !state.frame && !state.library && !state.supplier && !document.querySelector(".grid td.edit select, .grid td.edit input")) render();
  } catch (e) { /* the next look will try again */ }
}
async function markSeen(ids, undo) {
  try {
    const res = await fetch("/api/alerts/seen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids, undo: !!undo }) });
    if (!res.ok) throw new Error(res.statusText);
    state.alerts = await res.json(); paintBadge(); toast(`${undo ? "Brought back" : "Marked seen"}: ${ids.length}`); state.selection.clear(); render();
  } catch (e) { toast(e.message, false); }
}
async function loadNegos(always) {
  await RPA.ready; if (!can("page:rightcost")) return;
  try {
    const ng = await (await fetch("/api/negotiations")).json(), was = JSON.stringify(state.negos);
    state.negos = ng.items || {}; state.negoKinds = ng.kinds || state.negoKinds;
    if ((always || was !== JSON.stringify(state.negos)) && !state.frame && !state.library && !document.querySelector(".grid td.edit select, .grid td.edit input")) render();
  } catch (e) { /* the next look will try again */ }
}

// ------------------------------------------------------------------ the "+" popup: create cost, bulk upload, compare, negotiation pack
/* One window over the page with the four costing screens as tabs (web/pages/cost.js, bulk.js, compare.js, pack.js),
   drawn in the popup's own box. They share what is open (RP.state), so a fabric opened from the list in Bulk upload
   carries on in Create cost. Each opening starts afresh. */
function popupHash(tab) { return "#" + (decodeURIComponent(location.hash.slice(1)).split("?")[0] || "dashboard") + (tab ? "?new=" + tab : ""); }
function openPopup(tab = "cost", r = null, fromAddress = false) {
  closeLayers();
  document.querySelectorAll(".scrim[data-popup]").forEach(e => e.remove());
  if (!fromAddress) history.pushState({ popup: tab }, "", popupHash(tab));          // Back closes the popup
  RP.fresh();
  const box = h("div", { class: "pgbox" }, h("div", { class: "pg" }, h("p", { class: "empty" }, "Loading...")));
  const close = () => { if (history.state && history.state.popup) history.back(); else { history.replaceState(null, "", popupHash(null)); s.remove(); load(); } };
  const tabs = h("div", { class: "ptabs", role: "tablist" });
  const mark = id => { s.dataset.tab = id; tabs.querySelectorAll(".ptab").forEach(b => { const on = b.dataset.tab === id; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); }); };
  const switchTo = (id, fromAddr) => {
    if (RP.pages[id]) RP.show(id, "", box, { inPopup: true, tab: t => switchTo(t) });
    else fill(box, h("div", { class: "empty" }, "This tab could not be loaded: its file is missing from web/pages/."));
    mark(id); if (!fromAddr) history.replaceState(history.state, "", popupHash(id));
  };
  const note = r ? h("span", { class: "pnote" }, `${r.code}${r.source === "Purchase orders" ? ": a purchase order (its price was paid); Add to list copies it into the fabric list" : ""}`) : null;
  const pop = h("div", { class: "popup", role: "dialog", "aria-modal": "true", "aria-label": "New cost" },
    h("div", { class: "ph" }, h("h2", {}, "New cost"), h("div", { class: "ptabwrap" }, tabs), note, ib("x", "Close", close)), box);
  const s = h("div", { class: "scrim", onmousedown: e => { if (e.target === s) close(); } }, pop);
  s.dataset.popup = "1"; s.dataset.tab = tab; s.switchTo = switchTo; s.close = close;
  $("#layer").append(s);
  // first what this person may use (web/access.js) and the rate master's lists, read afresh: a fabric opened from Right
  // cost needs the lists to find its yarns, and a yarn added by someone else since shows without a reload
  (async () => {
    try { if (RP.known()) await RP.known(); } catch (e) { /* asked again by web/access.js */ }
    if (!s.isConnected) return;
    // not let in, or no screen of the popup open to this role: no popup, and nothing asked of the server (the page says why)
    if (shutOut() || !CONFIG.popupTabs.length) { s.remove(); history.replaceState(null, "", popupHash(null)); return; }
    try { await RP.loadMeta(); } catch (e) { /* the tab says the rate master could not be read */ }
    if (!s.isConnected) return;
    let now = s.dataset.tab;                       // the address may have moved to another tab meanwhile
    if (!CONFIG.popupTabs.some(t => t[0] === now)) now = (CONFIG.popupTabs[0] || ["cost"])[0];
    for (const [id, label] of CONFIG.popupTabs) tabs.append(h("button", { type: "button", role: "tab", class: "ptab", "data-tab": id, onclick: () => switchTo(id) }, label));
    if (tab === "cost" && r !== undefined && RP.cost && RP.state.meta) RP.cost.open(r ? r.choices : null, r && r.source === "Fabric list" ? r.id : null);
    switchTo(now, fromAddress && s.dataset.tab === now);
  })();
}
const openCostPopup = r => can("page:cost") ? openPopup("cost", r || null) : toast(`Your role (${RPA.me.role}) may not use Create cost`, false);

// ------------------------------------------------------------------ Library: setup lists (kept in this browser)
function libSeed(name) {
  if (name === "Suppliers") return [...new Set(state.rows.map(r => r.supplier).filter(Boolean))].sort().map(n => ({ name: n, active: true }));
  if (name === "Material Contents") return ["100% cotton", "Poly cotton", "Linen"].map(n => ({ name: n, active: true }));
  if (name === "Constructions") return [...new Set(state.rows.map(r => r.weave).filter(Boolean))].sort().map(n => ({ name: n, active: true }));
  if (name === "Units of measurement") return ["Metre", "Kilogram", "Yard"].map(n => ({ name: n, active: true }));
  return [];
}
function renderLibrary(main) {
  const L = state.library, saved = state.libs[L.name], base = () => JSON.parse(JSON.stringify(saved || libSeed(L.name)));
  const rows = L.draft || (L.draft = base());
  const pages = Math.max(1, Math.ceil(rows.length / L.size)); L.page = Math.min(L.page, pages - 1);
  const shown = rows.slice(L.page * L.size, (L.page + 1) * L.size);
  const clean = x => x.map(r => ({ name: r.name, active: r.active }));
  const changed = JSON.stringify(clean(rows)) !== JSON.stringify(clean(base()));
  const crumbs = h("div", { class: "crumb" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }), "\u00A0\u203A\u00A0", "Prices", "\u00A0\u203A\u00A0", h("span", {}, L.name));
  const tools = h("div", { class: "toolbar" },
    h("button", { type: "button", class: "btn fill", disabled: !changed || null, onclick: () => { state.libs[L.name] = clean(rows).filter(r => r.name.trim()); store.set("libs", state.libs); L.draft = null; toast("Saved"); render(); } }, "Save"),
    h("button", { type: "button", class: "btn line", onclick: () => { rows.push({ name: "", active: true }); L.page = Math.ceil(rows.length / L.size) - 1; render(); const ins = document.querySelectorAll(".libname"); if (ins.length) ins[ins.length - 1].focus(); } }, "Add"),
    h("button", { type: "button", class: "btn line", disabled: !rows.some(r => r.picked) || null, onclick: () => { L.draft = rows.filter(r => !r.picked); render(); } }, "Delete"),
    h("span", { class: "spacer" }), h("span", { class: "count" }, `${rows.length} ${rows.length === 1 ? "entry" : "entries"}${changed ? " · unsaved changes" : ""}`));
  const table = h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, h("th", { style: { width: "40px" } }, ""), h("th", {}, "Name"), h("th", { style: { width: "90px" } }, "Active"))),
    h("tbody", {}, shown.length ? shown.map(r => {
      const pick = h("input", { type: "checkbox", class: "cb", "aria-label": "Select " + (r.name || "new entry") }); pick.checked = !!r.picked; pick.addEventListener("change", () => { r.picked = pick.checked; render(); });
      const name = h("input", { type: "text", class: "libname", value: r.name, "aria-label": "Name" }); name.addEventListener("change", () => { r.name = name.value; render(); });
      const act = h("input", { type: "checkbox", class: "cb", "aria-label": "Active" }); act.checked = r.active; act.addEventListener("change", () => { r.active = act.checked; render(); });
      return h("tr", { class: r.picked ? "picked" : null }, h("td", {}, pick), h("td", {}, name), h("td", {}, act));
    }) : h("tr", {}, h("td", { colspan: "3", class: "empty" }, "No records to view"))));
  const pager = h("div", { class: "toolbar", style: "justify-content:flex-end" },
    h("button", { type: "button", class: "btn", "aria-label": "Previous page", disabled: L.page === 0 || null, onclick: () => { L.page--; render(); } }, "‹"),
    h("span", { class: "count" }, `Page ${L.page + 1} of ${pages}`),
    h("button", { type: "button", class: "btn", "aria-label": "Next page", disabled: L.page >= pages - 1 || null, onclick: () => { L.page++; render(); } }, "\u00A0\u203A\u00A0"),
    [20, 50, 100].map(n => h("button", { type: "button", class: "btn" + (L.size === n ? " fill" : ""), onclick: () => { L.size = n; L.page = 0; render(); } }, String(n))));
  fill(main, crumbs, h("div", { class: "tabsrow" }, h("div", { class: "headrow" }, h("h1", { class: "title", style: "cursor:default" }, L.name)), newCostButton()),
    h("p", { style: "color:var(--text2);font-size:11px" }, "A setup list kept in this browser. RightPrice's costing does not read it yet."), tools, table, pager);
  $("#selbar").hidden = true;
}
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t; try { localStorage.setItem("rp-theme", t); } catch (e) { /* kept for this visit */ }
  toast(t === "dark" ? "Dark" : "Light");
}
async function whoAmI() {
  // Azure's sign-in answers /.auth/me with the signed-in person's claims; off Azure there is none
  if (/^(localhost|127\.|0\.0\.0\.0)/.test(location.hostname)) return;      // no sign-in when run on this computer
  try {
    const r = await fetch("/.auth/me", { credentials: "same-origin" }); if (!r.ok) return;
    const d = await r.json(), u = Array.isArray(d) ? d[0] : null; if (!u) return;
    const claim = t => ((u.user_claims || []).find(c => c.typ === t || c.typ.endsWith("/" + t)) || {}).val;
    const name = claim("name") || u.user_id || "", email = claim("preferred_username") || claim("emailaddress") || u.user_id || "";
    const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
    state.me = { name: name || "Signed-in user", email, initials: (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] || "RP").slice(0, 2)).toUpperCase() };
    renderRail();
  } catch (e) { /* not on Azure: keep the default */ }
}

// ================================================================== EVENTS (actions)
function runSearch(mode) { state.search.mode = mode; store.set("searchMode", mode); const t = state.search.text.trim(); state.search.active = t ? { text: t, mode } : null; rerunWithSkeleton(); }
function setView(v) { state.view = v; store.set("view", v); state.shown = CONFIG.pageSize; render(); }
function applySaved(x) { state.saved = x.name; state.filters = JSON.parse(JSON.stringify(x.filters || {})); if (x.codes) state.filters._codes = x.codes; if (x.search) { state.search.active = x.search; state.search.text = x.search.text; } rerunWithSkeleton(); }
function deleteSaved() {
  const sel = h("select", {}, state.userSearches.map(s => h("option", {}, s.name)));
  const d = dialog("Delete a saved search", sel, [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => { state.userSearches = state.userSearches.filter(s => s.name !== sel.value); store.set("searches", state.userSearches); if (state.saved === sel.value) state.saved = "Default"; d.remove(); toast("Deleted"); render(); } }, "Delete")]);
}
function saveSearchPrompt() {
  const name = h("input", { type: "text", placeholder: "For example: Arvind twills above range" });
  const d = dialog("Save search", [h("p", { class: "sub" }, "Keep these filters and the search under a name, to choose again from the saved search list."), name],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Not now"), h("button", { type: "button", class: "btn fill", onclick: () => {
      const n = name.value.trim(); if (!n) return name.focus();
      const f = Object.assign({}, state.filters); delete f._codes;
      state.userSearches = [...state.userSearches.filter(s => s.name !== n), { name: n, filters: f, search: state.search.active }]; store.set("searches", state.userSearches);
      state.saved = n; d.remove(); toast("Saved"); render();
    } }, "Save")]);
  name.addEventListener("keydown", e => { if (e.key === "Enter") d.querySelector(".btn.fill").click(); });
}
function addToSaved(picked) {
  const mine = state.userSearches;
  const rNew = h("input", { type: "radio", name: "how", checked: true }), rOld = h("input", { type: "radio", name: "how", disabled: !mine.length || null });
  const name = h("input", { type: "text", placeholder: "Name of the new search" }), old = h("select", { disabled: !mine.length || null }, mine.map(s => h("option", {}, s.name)));
  const d = dialog("Add to a saved search", [h("label", { class: "row" }, rNew, "Create a new search"), name, h("label", { class: "row" }, rOld, "Add to an existing search"), old, !mine.length ? h("p", { class: "sub" }, "No saved search yet.") : null],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => {
      const codes = picked.map(keyOf);
      if (rNew.checked) { const n = name.value.trim(); if (!n) return name.focus(); state.userSearches = [...mine.filter(s => s.name !== n), { name: n, codes }]; }
      else { const s = mine.find(x => x.name === old.value); s.codes = [...new Set([...(s.codes || []), ...codes])]; }
      store.set("searches", state.userSearches); d.remove(); toast("Saved"); render();
    } }, "Save")]);
}
function bulkEdit(picked) {
  const st = h("select", {}, h("option", { value: "" }, "(leave as it is)"), STATUS.map(o => h("option", {}, o))), rem = h("input", { type: "text", placeholder: "Leave blank to keep each row's remarks" });
  const d = dialog(`Edit ${picked.length} ${picked.length === 1 ? "item" : "items"}`, [h("label", { class: "row" }, "Status"), st, h("label", { class: "row" }, "Remarks"), rem, h("p", { class: "sub" }, "Kept in this browser. Costing figures cannot be edited here; open a fabric in Create cost to change its choices.")],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => {
      for (const r of picked) { const k = keyOf(r), e = Object.assign({}, state.edits[k] || {}); if (st.value) e.status = st.value; if (rem.value.trim()) e.remarks = rem.value.trim(); state.edits[k] = e; addLog(`${r.code}: ${st.value ? "status " + st.value : ""}${st.value && rem.value.trim() ? ", " : ""}${rem.value.trim() ? `remarks "${rem.value.trim()}"` : ""}`); }
      store.set("edits", state.edits); d.remove(); toast("Saved"); render();
    } }, "Save")]);
}
function share(picked) {
  const msg = h("textarea", { rows: "4" }, `${picked.length} fabrics from Right cost: ${picked.map(r => r.code).join(", ")}`);
  const d = dialog("Share", [h("p", { class: "sub" }, "There are no user accounts in RightPrice to send to. Copy the codes and paste them where you need them; Exact Search finds them again."), msg],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Close"), h("button", { type: "button", class: "btn fill", onclick: async () => { try { await navigator.clipboard.writeText(msg.value); toast("Copied"); } catch (e) { msg.select(); toast("Select and copy the text", false); } } }, "Copy")]);
}
function saveEdits() {
  for (const [k, p] of Object.entries(state.pending)) { state.edits[k] = Object.assign({}, state.edits[k] || {}, p); const r = state.rows.find(x => keyOf(x) === k); addLog(`${r ? r.code : k}: ${Object.entries(p).map(([f, v]) => `${f} ${v}`).join(", ")}`); }
  store.set("edits", state.edits); state.pending = {}; toast("Saved"); render();
}
function moreAction(a, rows) {
  if (a === "Download Excel") return download("/api/costs/download", { keys: rows.map(keyOf), extra: extras(rows) }, "RightCost.xlsx").then(() => toast("Excel downloaded")).catch(e => toast(e.message, false));
  const tab = { "Create cost": "cost", "Bulk upload": "bulk", "Compare": "compare", "Negotiation pack": "pack" }[a];
  if (tab === "pack") {
    // the pack is made from the fabric list (mill sheets): ticked fabric-list rows go with it
    const ids = state.rows.filter(r => r.source === "Fabric list" && state.selection.has(keyOf(r)) && r.id).map(r => r.id);
    if (state.selection.size && !ids.length) return toast("The pack is made from fabric-list rows (mill sheets); none of the ticked rows is one. Untick them for the whole list", false);
    try { if (ids.length) sessionStorage.setItem("rp-pack-ids", JSON.stringify(ids)); else sessionStorage.removeItem("rp-pack-ids"); } catch (e) { /* no handover */ }
  }
  if (tab === "compare") {
    const ticked = state.rows.filter(r => state.selection.has(keyOf(r)));
    const listed = ticked.filter(r => r.source === "Fabric list" && r.id);
    try { if (listed.length === 2) sessionStorage.setItem("rp-compare-ids", JSON.stringify(listed.map(r => r.id))); else sessionStorage.removeItem("rp-compare-ids"); } catch (e) { /* no handover */ }
    if (ticked.length && listed.length !== 2) return toast("Compare takes exactly two fabric-list rows. To compare a purchase order, open it in Create cost and press Add to list first", false);
  }
  if (tab) openPopup(tab);
}
function startResize(e, c) {
  e.preventDefault(); e.stopPropagation();
  const x0 = e.clientX, w0 = widthOf(c);
  const move = ev => { state.colWidth[c.id] = Math.max(40, w0 + ev.clientX - x0); const tbl = $("table.grid"); if (tbl) { const i = columns().indexOf(c); tbl.querySelectorAll("col")[i].style.width = state.colWidth[c.id] + "px"; tbl.style.width = columns().reduce((a, x) => a + widthOf(x), 0) + "px"; } };
  const up = () => { removeEventListener("mousemove", move); removeEventListener("mouseup", up); store.set("colWidth", state.colWidth); render(); };
  addEventListener("mousemove", move); addEventListener("mouseup", up);
}
function columnChooser(anchor) {
  document.querySelectorAll(".colpanel").forEach(e => e.remove());
  const all = CONFIG.modules.costs.columns, order = state.colOrder || all.map(c => c.id);
  let dragId = null;
  const p = h("div", { class: "colpanel" }, h("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px" }, h("b", {}, "Columns"), ib("x", "Close", () => p.remove())),
    h("div", { style: "color:var(--text2);font-size:11px;margin-bottom:6px" }, "Tick to show. Drag to reorder."),
    order.map(id => all.find(c => c.id === id)).filter(c => c && !c.pinned && c.type !== "status").map(c => {
      const box = h("input", { type: "checkbox", class: "cb" }); box.checked = !state.colHidden.has(c.id);
      box.addEventListener("change", () => { box.checked ? state.colHidden.delete(c.id) : state.colHidden.add(c.id); store.set("colHidden", [...state.colHidden]); render(); $(".gridwrap").append(p); });
      const lab = h("label", { draggable: "true" }, box, c.header, h("span", { class: "grip" }, "≡"));
      lab.addEventListener("dragstart", () => { dragId = c.id; });
      lab.addEventListener("dragover", e => { e.preventDefault(); lab.classList.add("drop"); });
      lab.addEventListener("dragleave", () => lab.classList.remove("drop"));
      lab.addEventListener("drop", e => { e.preventDefault(); const o = [...(state.colOrder || all.map(x => x.id))]; o.splice(o.indexOf(dragId), 1); o.splice(o.indexOf(c.id), 0, dragId); state.colOrder = o; store.set("colOrder", o); render(); columnChooser(); });
      return lab;
    }),
    h("button", { type: "button", class: "btn", style: "margin-top:8px", onclick: () => { state.colOrder = null; state.colHidden.clear(); state.colWidth = {}; store.set("colOrder", null); store.set("colHidden", []); store.set("colWidth", {}); render(); } }, "Reset columns"));
  const wrap = $(".gridwrap"); if (wrap) wrap.append(p);
  void anchor;
}
function openDrawer() {
  closeLayers();
  const dr = $("#drawer"), attrs = CONFIG.modules.costs.filterAttrs, draft = JSON.parse(JSON.stringify(state.filters)); delete draft._codes;
  let costed = state.costedOnly;
  // each attribute counts the rows the other filters (as drafted) leave
  const poolFor = id => { const keep = state.filters; state.filters = Object.fromEntries(Object.entries(draft).filter(([k]) => k !== id)); const sAct = state.search.active; const rows = filtered(); state.filters = keep; state.search.active = sAct; return rows; };
  const open = new Set(Object.keys(draft));
  const list = h("div", { class: "body" });
  const paintList = q => fill(list, ...attrs.filter(a => !q || a.label.toLowerCase().includes(q)).map(a => {
    const cnt = Array.isArray(draft[a.id]) ? draft[a.id].length : draft[a.id] ? 1 : 0;
    const box = h("div", { class: "attr" }, h("button", { type: "button", "aria-expanded": String(open.has(a.id)), onclick: () => { open.has(a.id) ? open.delete(a.id) : open.add(a.id); paintList(q); } }, h("span", {}, a.label, cnt ? h("span", { class: "cnt" }, `(${cnt})`) : null), h("span", {}, open.has(a.id) ? "⌄" : "\u00A0\u203A\u00A0")));
    if (open.has(a.id)) {
      if (a.num || a.date) {
        const f = draft[a.id] || (a.date ? { date: true, from: "", to: "" } : { min: "", max: "" });
        const i1 = h("input", { type: a.date ? "date" : "number", value: a.date ? f.from : f.min, "aria-label": a.label + (a.date ? " from" : " minimum"), placeholder: a.date ? null : "Min" });
        const i2 = h("input", { type: a.date ? "date" : "number", value: a.date ? f.to : f.max, "aria-label": a.label + (a.date ? " to" : " maximum"), placeholder: a.date ? null : "Max" });
        const upd = () => { const v = a.date ? { date: true, from: i1.value, to: i2.value } : { min: i1.value, max: i2.value }; if ((a.date ? v.from || v.to : v.min !== "" || v.max !== "")) draft[a.id] = v; else delete draft[a.id]; };
        i1.addEventListener("input", upd); i2.addEventListener("input", upd);
        box.append(h("div", { class: "vals" }, a.date ? [h("span", {}, "From"), i1, h("span", {}, "To"), i2] : h("div", { class: "mm" }, i1, i2)));
      } else {
        const counts = {}; for (const r of poolFor(a.id)) { const v = String(val(r, a.id) ?? ""); if (v) counts[v] = (counts[v] || 0) + 1; }
        const values = Object.keys(counts).sort((x, y) => counts[y] - counts[x]);
        const mini = h("input", { type: "text", placeholder: "Search", "aria-label": `Search ${a.label}` });
        const vals = h("div");
        const paintVals = () => fill(vals, ...values.filter(v => !mini.value || v.toLowerCase().includes(mini.value.toLowerCase())).slice(0, 200).map(v => {
          const cb = h("input", { type: "checkbox", class: "cb" }); cb.checked = (draft[a.id] || []).includes(v);
          cb.addEventListener("change", () => { const cur = new Set(draft[a.id] || []); cb.checked ? cur.add(v) : cur.delete(v); if (cur.size) draft[a.id] = [...cur]; else delete draft[a.id]; const keep = list.scrollTop; paintList(search.value.toLowerCase()); list.scrollTop = keep; });
          return h("label", {}, cb, `${v} (${counts[v]})`);
        }));
        mini.addEventListener("input", paintVals); paintVals();
        box.append(h("div", { class: "vals" }, values.length > 8 ? mini : null, vals, values.length ? null : h("span", { style: "color:var(--text2)" }, "No values")));
      }
    }
    return box;
  }));
  const search = h("input", { type: "text", placeholder: "Search the filters", "aria-label": "Search the filter attributes" });
  search.addEventListener("input", () => paintList(search.value.toLowerCase()));
  const sw = h("input", { type: "checkbox", class: "cb" }); sw.checked = costed; sw.addEventListener("change", () => { costed = sw.checked; });
  fill(dr, h("div", { class: "hd" }, "Filters", ib("x", "Close", () => { dr.hidden = true; })), h("div", { class: "fs", html: svg("search", 'width="14" height="14"') }, search), list,
    h("div", { class: "ft" }, h("label", { class: "switch" }, "Costed only (leave out rows not costed)", sw), h("div", { style: "display:flex;justify-content:space-between" },
      h("button", { type: "button", class: "btn", onclick: () => { for (const k of Object.keys(draft)) delete draft[k]; costed = false; sw.checked = false; open.clear(); paintList(""); } }, "Clear"),
      h("button", { type: "button", class: "btn fill", onclick: () => { const codes = state.filters._codes; state.filters = draft; if (codes) state.filters._codes = codes; state.costedOnly = costed; state.saved = "Default"; dr.hidden = true; rerunWithSkeleton(); if (Object.keys(draft).length) setTimeout(saveSearchPrompt, 450); } }, "Apply"))));
  paintList(""); dr.hidden = false; search.focus();
}

addEventListener("keydown", e => {
  if (e.key === "Escape") { const pop = document.querySelector(".scrim"); if (pop) { if (pop.dataset.popup) pop.close(); else pop.remove(); return; } closeLayers(); }
  // Ctrl+F finds in the list when the list is what is in view; everywhere else it is the browser's own find
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f" && !state.detail && !state.frame && !state.library && !state.supplier && !state.users && !document.querySelector(".scrim")) {
    const s = $("#search"); if (s && s.offsetParent) { e.preventDefault(); s.focus(); } }
});
// the address follows the page: #item/<source|code> is a fabric's detail page; Back returns to the list
addEventListener("hashchange", route);
const catchUp = () => { if (!document.hidden && !state.frame && !state.library && !state.supplier && state.rows.length && !document.querySelector(".scrim")) loadNegos(); };
const alertsUp = () => { if (!document.hidden) loadAlerts(); };
addEventListener("focus", alertsUp); setInterval(alertsUp, 30000);
addEventListener("focus", catchUp); document.addEventListener("visibilitychange", catchUp); setInterval(catchUp, 30000);
addEventListener("beforeunload", e => { if (Object.keys(state.pending).length) { e.preventDefault(); e.returnValue = ""; } });

async function load() {
  await RPA.ready; if (!can("page:rightcost")) return;           // a role without Right cost has no costings to load
  try {
    const [d, ng] = await Promise.all([(await fetch("/api/costs")).json(), fetch("/api/negotiations").then(x => x.json()).catch(() => ({ items: {}, kinds: [] }))]);
    state.negos = ng.items || {}; state.negoKinds = ng.kinds || [];
    state.rows = d.rows; state.counts = d.counts; state.updating = !!d.updating;      // the rows last worked out, while new ones are
    clearTimeout(load.t); if (!d.ready) load.t = setTimeout(load, 4000);       // the verdicts are worked out in the background
    if (!state.counts[state.cls] && state.cls !== "*") state.cls = state.counts["Purchase orders"] ? "Purchase orders" : "Fabric list";
    if (!state.frame) render();
    if (state.supplier && !d.ready) loadSupplier();
  } catch (err) { if (shutOut()) return render(); fill($("#main"), h("div", { class: "empty" }, "The costings could not be loaded: " + err.message)); }
}
if (new URLSearchParams(location.search).get("from") === "rightcost") history.replaceState(null, "", "/" + (location.hash || "#rightcost"));     // the earlier address /rightcost
renderRail(); route(); load(); loadAlerts(); whoAmI();
