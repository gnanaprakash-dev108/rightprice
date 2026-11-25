/* Right cost: every fabric costed, in one list page laid out after the PLM list screens.
   Data: /api/costs (the 1,696 purchase-order costings and the fabric list). Nothing is costed here;
   the "+" opens Cost a fabric itself, in a popup. Sections: CONFIG, STATE, UTILS, RENDER, EVENTS. */
"use strict";

// ================================================================== CONFIG
const BAND_COLOR = { "In range": "#2E9E5B", "Below range": "#3D8BFD", "Tool unsure": "#F5C542", "Above range": "#E5484D", "Not costed": "#B9BEC7", "No price": "#B9BEC7", "Check quote": "#B98900", "Working it out": "#DADADA" };
const ROUTE_COLOR = { "Yarn Dyed": "#5C6BC0", "Piece Dyed": "#26A69A", "Printed": "#EF6C00", "RFD / Bleached": "#90A4AE" };
const STATUS = ["Not started", "To negotiate", "In negotiation", "Agreed", "Dropped"];
const n0 = v => v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const n2 = v => v === null || v === undefined || v === "" ? "" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
        { id: "code", header: "Fabric Code", width: 130, pinned: true, type: "link" },
        { id: "band", header: "Against Range", width: 120, type: "band", help: "The negotiation brief's verdict on today's rates: in the usual range for this fabric type, above it, below it, or unsure (a type the tool fits poorly, or placeholder rates)" },
        { id: "status", header: "Status", width: 120, type: "edit-dd", options: STATUS, help: "Your negotiation status. Kept in this browser" },
        { id: "description", header: "Description", width: 230 },
        { id: "supplier", header: "Supplier", width: 170 },
        { id: "route", header: "Route", width: 90 },
        { id: "weave", header: "Weave", width: 90 },
        { id: "finish", header: "Finish", width: 140 },
        { id: "pattern", header: "Pattern", width: 80 },
        { id: "warp", header: "Warp", width: 100 },
        { id: "weft", header: "Weft", width: 100 },
        { id: "epippi", header: "EPI × PPI", width: 80, value: r => r.epi ? `${n0(r.epi)} × ${n0(r.ppi)}` : "" },
        { id: "width", header: "Width (in)", width: 70, type: "num", fmt: v => v ? Number(v).toFixed(1) : "" },
        { id: "should", header: "Should-cost Rs/m", width: 110, type: "num", fmt: n2 },
        { id: "price", header: "Price Rs/m", width: 90, type: "num", fmt: n2, help: "Purchase orders: the price paid. Fabric list: the mill's quote" },
        { id: "gap_pct", header: "Above Should-cost", width: 110, type: "num", fmt: pc },
        { id: "metres", header: "Metres", width: 80, type: "num", fmt: n0 },
        { id: "excess", header: "Paid Above, Rs", width: 110, type: "num", fmt: n0, help: "Price minus should-cost, times the metres" },
        { id: "order_size", header: "Order Size", width: 110 },
        { id: "source", header: "Source", width: 110 },
        { id: "remarks", header: "Remarks", width: 170, type: "edit-text", help: "Your note. Kept in this browser" },
        { id: "rowstatus", header: "", width: 50, type: "status" },
      ],
      savedSearches: [
        { name: "Default", filters: {} },
        { name: "Above the usual range", filters: { band: ["Above range"] } },
        { name: "Tool unsure", filters: { band: ["Tool unsure"] } },
        { name: "Held-back third", filters: { held_back: ["Yes"] } },
        { name: "Orders of 3,000 m and above", filters: { order_size: ["3,000 m and above"] } },
      ],
      sortFields: [["code", "Fabric Code"], ["description", "Description"], ["supplier", "Supplier"], ["should", "Should-cost"], ["price", "Price"], ["gap_pct", "Above Should-cost"], ["excess", "Paid Above"], ["metres", "Metres"], ["added", "Added On"]],
      filterAttrs: [
        { id: "supplier", label: "Supplier" }, { id: "route", label: "Route" }, { id: "weave_group", label: "Weave group" }, { id: "weave", label: "Weave" },
        { id: "finish", label: "Finish" }, { id: "pattern", label: "Pattern" }, { id: "warp", label: "Warp yarn" }, { id: "weft", label: "Weft yarn" },
        { id: "order_size", label: "Order size" }, { id: "band", label: "Against range" }, { id: "status", label: "Status" }, { id: "held_back", label: "Held back (calibration test)" },
        { id: "placeholder", label: "Placeholder rates used" }, { id: "should", label: "Should-cost Rs/m", num: true }, { id: "price", label: "Price Rs/m", num: true },
        { id: "gap_pct", label: "Above should-cost %", num: true }, { id: "metres", label: "Metres", num: true }, { id: "added", label: "Added on", date: true },
      ],
      moreActions: ["Download Excel", "Download Excel with Images", "Bulk Upload", "Download Templatised Data", "Negotiation Pack", "Reports and Utilities"],
    },
  },
  rail: {
    top: [
      { id: "home", icon: "home", label: "Home (Dashboard)", href: "/#dashboard" },
      "div",
      { id: "costs", icon: "list", label: "Right cost", page: true },
      { id: "costing", icon: "fabric", label: "Costing", fly: "costing" },
      { id: "prices", icon: "chart", label: "Prices", fly: "prices" },
      { id: "rates", icon: "table", label: "Rates", fly: "rates" },
      { id: "library", icon: "box", label: "Library", fly: "library" },
      { id: "tools", icon: "tools", label: "Tools", fly: "tools" },
    ],
    bottom: [
      { id: "notes", icon: "bell", label: "Notifications", fly: "notes" },
      { id: "recent", icon: "clock", label: "Recent Visits", fly: "recent" },
      { id: "bookmarks", icon: "bookmark", label: "Bookmarks", fly: "bookmarks" },
      { id: "downloads", icon: "download", label: "Downloads", fly: "downloads" },
      { id: "settings", icon: "gear", label: "Settings", fly: "settings" },
    ],
  },
  flyouts: {
    costing: { title: "Costing", icon: "fabric", groups: [["Costing", [["Right cost", "/rightcost"], ["Cost a fabric (popup)", "popup:cost"], ["Bulk upload and list", "/#bulk"], ["Compare", "/#compare"], ["Negotiation pack", "/#pack"]]], ["Analysis", [["Dashboard", "/#dashboard"], ["Pilot results", "/#pilot"]]]] },
    prices: { title: "Prices", icon: "chart", groups: [["Prices", [["Yarn prices", "/#yarn"], ["Cotton prices", "/#cotton"], ["Bring in prices", "/#intake"]]]] },
    rates: { title: "Rates", icon: "table", groups: [["Rate master", [["Rate tables", "/#rates"], ["Mill rate card", "/#ratecard"], ["Settings", "/#settings"]]]] },
    tools: { title: "Tools", icon: "tools", groups: [["Utilities", [["Bulk Uploads", "/#bulk"], ["Earlier screens", "/classic/"]]]] },
    settings: { title: "Settings", icon: "gear", groups: [["Application", [["Light or dark", "theme:toggle"], ["Settings", "/#settings"], ["Rate tables", "/#rates"]]]] },
    library: { title: "Library", icon: "box", groups: [
      ["Relationships", [["Suppliers", "lib:Suppliers"]]],
      ["Standard Specifications", ["Product Life Cycle Stages", "Color Cards", "Size Cards", "Seasons", "Units of measurement", "Points of Measure", "Body Types", "Approval Forms", "Genders", "BOM Layouts", "Material Contents", "Care Label Instructions", "Constructions", "Made In"].map(n => [n, "lib:" + n])],
      ["Costing", ["Rating Scale Types", "Rating Scales", "Cost Sheet Types", "Material Cost Configuration", "Seasonal Exchange Rates"].map(n => [n, "lib:" + n])],
      ["Sourcing", ["Payment Terms", "Delivery Terms", "Sample Type"].map(n => [n, "lib:" + n])],
      ["Templates", [["Page Templates", "lib:Page Templates"]]]] },
  },
};
const ICONS = {
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
  edits: store.get("edits", {}), pending: {}, userSearches: store.get("searches", []), recent: store.get("recent", []), bookmarks: store.get("bookmarks", []),
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
const keyOf = r => `${r.source}|${r.id || r.code}`;
const val = (r, id) => {
  const col = CONFIG.modules.costs.columns.find(c => c.id === id);
  if (id === "status") return (state.pending[keyOf(r)] || {}).status ?? (state.edits[keyOf(r)] || {}).status ?? "Not started";
  if (id === "remarks") return (state.pending[keyOf(r)] || {}).remarks ?? (state.edits[keyOf(r)] || {}).remarks ?? "";
  if (id === "held_back") return r.held_back === null || r.held_back === undefined ? "" : r.held_back ? "Yes" : "No";
  if (id === "placeholder") return r.placeholders ? "Yes" : "No";
  if (col && col.value) return col.value(r);
  return r[id];
};
function toast(msg, ok = true) {
  const t = $("#toast"); t.replaceChildren(ok ? h("span", { class: "ok" }, "✓") : null, msg); t.hidden = false;
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
async function download(path, body, name) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(r.statusText);
  const url = URL.createObjectURL(await r.blob()), a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000);
  state.downloads.unshift({ name, at: new Date().toISOString() });
}

// ------------------------------------------------------------------ the rows shown: class, search, filters, sort
function terms(text) { return text.split(/[\n,\t ]+/).map(t => t.trim()).filter(Boolean); }
function filtered() {
  let rows = state.rows.filter(r => state.cls === "*" || r.source === state.cls);
  const s = state.search.active;
  if (s) {
    const ts = terms(s.text).map(t => t.toLowerCase());
    if (s.mode === "exact") rows = rows.filter(r => ts.includes(String(r.code).toLowerCase()));
    else rows = rows.filter(r => ts.some(t => [r.code, r.description, r.supplier].some(v => String(v || "").toLowerCase().includes(t))));
  }
  for (const [id, f] of Object.entries(state.filters)) {
    if (id === "_codes") { const set = new Set(f); rows = rows.filter(r => set.has(keyOf(r))); continue; }
    if (Array.isArray(f)) { if (f.length) rows = rows.filter(r => f.includes(String(val(r, id) ?? ""))); }
    else if (f.date) rows = rows.filter(r => { const v = String(r[id] || "").slice(0, 10); return v && (!f.from || v >= f.from) && (!f.to || v <= f.to); });
    else rows = rows.filter(r => { const v = Number(val(r, id)); return val(r, id) !== null && val(r, id) !== "" && (f.min === "" || f.min === undefined || v >= Number(f.min)) && (f.max === "" || f.max === undefined || v <= Number(f.max)); });
  }
  if (state.costedOnly) rows = rows.filter(r => r.should !== null && r.should !== undefined);
  const { field, dir } = state.sort, k = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = val(a, field), y = val(b, field);
    if (x === null || x === undefined || x === "") return 1; if (y === null || y === undefined || y === "") return -1;
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "en", { numeric: true })) * k;
  });
}
function missingCodes() {
  const s = state.search.active; if (!s || s.mode !== "exact") return [];
  const have = new Set(state.rows.filter(r => state.cls === "*" || r.source === state.cls).map(r => String(r.code).toLowerCase()));
  return terms(s.text).filter(t => !have.has(t.toLowerCase()));
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
  document.querySelectorAll(".rail .item").forEach(b => b.classList.toggle("active", b.dataset.id === (id || "costs")));
}
function renderRail() {
  const item = it => it === "div" ? h("div", { class: "div" }) : tipOn(h("button", { type: "button", class: "item", "data-id": it.id, html: svg(it.icon), onclick: e => {
    if (it.href) location.href = it.href; else if (it.page) { state.detail = null; state.library = null; closeLayers(); render(); }
    else openFly(it.fly, e.currentTarget);
  }, onmouseenter: it.fly && ["costing", "prices", "rates", "library", "tools"].includes(it.fly) ? e => openFly(it.fly, e.currentTarget, true) : null }, it.id === "notes" ? h("span", { class: "badge", id: "notebadge", hidden: true }) : null), it.label);
  $("#rail").replaceChildren(h("div", { class: "grp" }, CONFIG.rail.top.map(item)), h("div", { class: "grp bottom" }, CONFIG.rail.bottom.map(item),
    tipOn(h("button", { type: "button", class: "avatar", id: "avatar", onclick: e => openFly("profile", e.currentTarget) }, state.me.initials), state.me.name)));
  railActive();
}
function bookmarkBtn(label, href) {
  const on = state.bookmarks.some(b => b.href === href);
  return tipOn(h("button", { type: "button", class: "bm" + (on ? " on" : ""), html: svg("bookmark"), onclick: e => {
    e.stopPropagation();
    state.bookmarks = on ? state.bookmarks.filter(b => b.href !== href) : [...state.bookmarks, { label, href }]; store.set("bookmarks", state.bookmarks);
    toast(on ? "Bookmark removed" : "Bookmarked"); openFly(openFly.last, null, false, true);
  } }), on ? "Remove bookmark" : "Bookmark this page");
}
function go(href) { closeLayers(); if (href === "popup:cost") return openCostPopup(); if (href === "theme:toggle") return toggleTheme(); if (href.startsWith("lib:")) { state.detail = null; state.library = { name: href.slice(4), page: 0, size: 20 }; return render(); } if (href.startsWith("detail:")) { const r = state.rows.find(x => keyOf(x) === href.slice(7)); if (r) return openDetail(r); } location.href = href; }
function openFly(name, anchor, hover, keep) {
  const fly = $("#flyout");
  if (!keep && !fly.hidden && openFly.last === name && !hover) { fly.hidden = true; railActive(); return; }
  openFly.last = name; railActive(name === "profile" ? null : { notes: "notes", recent: "recent", bookmarks: "bookmarks", downloads: "downloads" }[name] || name);
  const cfg = CONFIG.flyouts[name], kids = [];
  const link = (label, href) => h("div", { class: "lnkrow" }, bookmarkBtn(label, href), h("button", { type: "button", class: "lnk", onclick: () => go(href) }, label));
  if (cfg) { kids.push(h("div", { class: "ttl", html: svg(cfg.icon) + `<span>${cfg.title}</span>` })); for (const [g, links] of cfg.groups) kids.push(h("div", { class: "g" }, g), links.map(([l, href]) => link(l, href))); }
  else if (name === "notes") {
    const above = state.rows.filter(r => r.source === "Fabric list" && r.band === "Above range");
    kids.push(h("div", { class: "ttl", html: svg("bell") + "<span>Notifications</span>" }), h("div", { class: "tabs2" }, h("b", {}, "Messages"), h("span", {}, "System Messages")),
      above.length ? above.map(r => h("button", { type: "button", class: "lnk", onclick: () => go("detail:" + keyOf(r)) }, `${r.code}: the mill's quote is ${pc(r.gap_pct)} against should-cost, above the usual range`)) : h("div", { class: "empty" }, "No Unread Message!"),
      h("div", { class: "btnrow" }, h("button", { type: "button", onclick: () => toast("Archived") }, "Archive"), h("button", { type: "button", onclick: () => toast("Marked as read") }, "Mark As Read")));
  } else if (name === "recent") {
    kids.push(h("div", { class: "ttl", html: svg("clock") + "<span>Recent Visits</span>" }), state.recent.length ? state.recent.map(v => h("button", { type: "button", class: "lnk", onclick: () => go("detail:" + v.key) }, h("span", {}, h("b", {}, v.code), ` · ${ago(v.at)}`))) : h("div", { class: "empty" }, "No visits yet. Open a fabric code from the list."));
  } else if (name === "bookmarks") {
    kids.push(h("div", { class: "ttl", html: svg("bookmark") + "<span>Bookmarks</span>" }), state.bookmarks.length ? state.bookmarks.map(b => link(b.label, b.href)) : h("div", { class: "empty" }, "No Bookmarked Pages! Click the bookmark icon on the menu to bookmark a page."));
  } else if (name === "downloads") {
    kids.push(h("div", { class: "ttl", html: svg("download") + "<span>Download Center</span>" }), h("div", { class: "note" }, "Files made in this visit. The browser keeps the files themselves."),
      state.downloads.length ? state.downloads.map(d => h("div", { class: "lnk" }, `${d.name} · ${ago(d.at)}`)) : h("div", { class: "empty", style: "margin-top:8px" }, "No downloads yet."));
  } else if (name === "profile") {
    kids.push(h("div", { class: "ttl" }, h("span", {}, state.me.name)), h("div", { class: "note" }, state.me.email || "RightPrice"), h("div", { class: "g" }, "Account"),
      h("button", { type: "button", class: "lnk", onclick: () => go("/#settings") }, "User Preferences"), h("button", { type: "button", class: "lnk", onclick: () => go("/.auth/logout") }, "Log Out"));
  }
  fly.replaceChildren(...kids); fly.hidden = false;
  if (!openFly.bound) { openFly.bound = true; fly.addEventListener("mouseleave", () => { if (openFly.hover) { fly.hidden = true; railActive(); } }); }
  openFly.hover = !!hover;
}

function render() {
  const main = $("#main");
  if (state.library) return renderLibrary(main);
  if (state.detail) return renderDetail(main);
  const mod = CONFIG.modules.costs, rows = filtered(), cls = mod.classes.find(c => c[0] === state.cls) || mod.classes[0];
  const crumbs = h("div", { class: "crumb" }, h("a", { href: "/#dashboard", html: svg("home", 'width="12" height="12"') }), "›", mod.crumbs[0], "›", h("span", {}, cls[1]));
  const title = h("button", { type: "button", class: "title", "aria-haspopup": "menu", onclick: e => menu(e.currentTarget, mod.classes.map(([k, label]) => ({ label: `${label} (${k === "*" ? state.rows.length : state.counts[k] || 0})`, on: k === state.cls, run: () => { state.cls = k; store.set("cls", k); state.selection.clear(); rerunWithSkeleton(); } }))) },
    CONFIG.appName, h("span", { class: "caret" }, "▾"));
  const fab = tipOn(h("button", { type: "button", class: "fab", html: svg("plus"), onclick: () => openCostPopup() }), "Create cost: cost a new fabric");
  const tabs = h("div", { class: "tabs", role: "tablist" }, mod.tabs.map(([k, label]) => h("button", { type: "button", role: "tab", class: "tab" + (state.tab === k ? " on" : ""), "aria-selected": String(state.tab === k), onclick: () => { state.tab = k; render(); } }, label, h("span", { class: "dots", "aria-hidden": "true" }, "⋮"))), fab);
  main.replaceChildren(crumbs, h("div", {}, title, h("span", { style: "margin-left:12px;color:var(--text2);font-size:13px" }, cls[1])), tabs, toolbar(rows), chipsRow(), state.tab === "items" ? body(rows) : state.tab === "suppliers" ? suppliersTab(rows) : h("div", { class: "empty" }, "No records to view"));
  renderSelbar();
  const badge = $("#notebadge"); if (badge) { const n = state.rows.filter(r => r.source === "Fabric list" && r.band === "Above range").length; badge.hidden = !n; badge.textContent = n; }
}

function toolbar(rows) {
  const mod = CONFIG.modules.costs, s = state.search;
  const input = h("input", { class: "search", id: "search", type: "search", placeholder: "Search by Code, Name Or Reference", value: s.text, "aria-label": "Search by code, name or reference" });
  input.addEventListener("input", () => { s.text = input.value; });
  input.addEventListener("keydown", e => { if (e.key === "Enter") runSearch(s.mode); });
  input.addEventListener("paste", e => { const t = e.clipboardData.getData("text"); if (/[\n\t]/.test(t)) { e.preventDefault(); s.text = terms(t).join(", "); input.value = s.text; } });
  const views = [ib("cards", "Card View", () => setView("card"), { class: "ib" + (state.view === "card" ? " on" : ""), "aria-pressed": String(state.view === "card") }),
    ib("rows", "List View", () => setView("list"), { class: "ib" + (state.view === "list" ? " on" : ""), "aria-pressed": String(state.view === "list") })];
  const slider = state.view === "card" ? h("input", { type: "range", class: "slider", min: "80", max: "200", value: String(state.cardSize), "aria-label": "Card size", oninput: e => { state.cardSize = Number(e.target.value); store.set("cardSize", state.cardSize); const c = $(".cards"); if (c) c.style.gridTemplateColumns = `repeat(auto-fill, minmax(${Math.round(state.cardSize * 1.3)}px, 1fr))`; } }) : null;
  const saved = h("button", { type: "button", class: "selbtn", "aria-haspopup": "menu", onclick: e => menu(e.currentTarget, [...mod.savedSearches, ...state.userSearches].map(x => ({ label: x.name, on: state.saved === x.name, run: () => applySaved(x) })).concat(state.userSearches.length ? ["-", { label: "Delete a saved search…", run: deleteSaved }] : [])) }, state.saved, h("span", {}, "▾"));
  const sortName = (mod.sortFields.find(f => f[0] === state.sort.field) || [0, state.sort.field])[1];
  const sortIcon = tipOn(h("button", { type: "button", class: "selbtn", html: svg("sort"), onclick: () => { state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc"; rerunWithSkeleton(); } }), state.sort.dir === "asc" ? (state.sort.field === "added" ? "Oldest to latest" : "Ascending") + ": click for descending" : (state.sort.field === "added" ? "Latest to oldest" : "Descending") + ": click for ascending");
  const sortSel = h("button", { type: "button", class: "selbtn", "aria-haspopup": "menu", onclick: e => menu(e.currentTarget, mod.sortFields.map(([k, l]) => ({ label: l, on: state.sort.field === k, run: () => { state.sort.field = k; rerunWithSkeleton(); } }))) }, sortName, h("span", {}, "▾"));
  const active = Object.keys(state.filters).filter(k => k !== "_codes").length > 0 || state.costedOnly;
  const filt = ib("filter", "Advanced Filter", () => openDrawer()); if (active) filt.append(h("span", { class: "dot" }));
  const more = ib("dots", "More", e => menu(e.currentTarget, mod.moreActions.map(a => ({ label: a, run: () => moreAction(a, rows) })), { right: true }));
  const sch = s.active ? h("span", { class: "chip" }, `${s.active.mode === "exact" ? "Exact" : "Search"}: ${s.active.text.length > 40 ? s.active.text.slice(0, 40) + "…" : s.active.text}`, tipOn(h("button", { type: "button", onclick: () => { s.active = null; s.text = ""; rerunWithSkeleton(); } }, "✕"), "Clear the search")) : null;
  return h("div", { class: "toolbar" },
    ib("search", "Like Search: code, description or supplier contains", () => runSearch("like"), { class: "ib" + (s.mode === "like" ? " on" : "") }),
    ib("exact", "Exact Search: fabric code matches exactly", () => runSearch("exact"), { class: "ib" + (s.mode === "exact" ? " on" : "") }),
    h("span", { class: "vdiv" }), input, ib("arrow", "Search", () => runSearch(s.mode)),
    h("span", { class: "count", "aria-live": "polite" }, `Showing ${Math.min(state.shown, rows.length).toLocaleString("en-IN")} of ${rows.length.toLocaleString("en-IN")} Records`), sch,
    h("span", { class: "spacer" }), slider, ...views, saved, h("span", { style: "display:inline-flex;align-items:center" }, sortIcon, sortSel), filt, more);
}
function chipsRow() {
  const chips = [];
  for (const id of missingCodes()) chips.push(h("span", { class: "chip bad" }, `No Results For: ${id}`));
  for (const [id, f] of Object.entries(state.filters)) {
    const a = CONFIG.modules.costs.filterAttrs.find(x => x.id === id);
    const text = id === "_codes" ? `${state.saved}: ${f.length} items` : Array.isArray(f) ? `${a.label}: ${f.join(", ")}` : f.date ? `${a.label}: ${f.from || "…"} to ${f.to || "…"}` : `${a.label}: ${f.min === "" || f.min === undefined ? "…" : f.min} to ${f.max === "" || f.max === undefined ? "…" : f.max}`;
    chips.push(h("span", { class: "chip" }, text.length > 70 ? text.slice(0, 70) + "…" : text, tipOn(h("button", { type: "button", onclick: () => { delete state.filters[id]; state.saved = "Default"; rerunWithSkeleton(); } }, "✕"), "Remove this filter")));
  }
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
  if (c.type === "thumb") return h("td", { class: cls(c), style: st }, h("div", { class: "thumb", style: { background: ROUTE_COLOR[r.route] || "#B9BEC7" }, title: r.route || "" }, (r.route || "—").split(/[ /]/)[0].slice(0, 5).toUpperCase()));
  if (c.type === "link") return h("td", { class: cls(c), style: st }, h("button", { type: "button", class: "code", onclick: () => openDetail(r) }, r.code));
  if (c.type === "band") return h("td", { class: cls(c), style: st }, h("span", { class: "pill", title: r.band === "Tool unsure" && r.why_unsure ? r.why_unsure.join("; ") : null }, h("i", { style: { background: BAND_COLOR[r.band] || "#B9BEC7" } }), r.band));
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
      td.replaceChildren(inp); inp.focus();
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
        h("div", { class: "fig" }, r.should !== null && r.should !== undefined ? `Rs ${n2(r.should)} · ${r.price ? pc(r.gap_pct) : "no price"}` : r.band)),
      ck, h("button", { type: "button", class: "qv", onclick: () => quickView(r) }, "Quick View"));
  }));
  grid.addEventListener("scroll", () => { if (grid.scrollTop + grid.clientHeight > grid.scrollHeight - 80 && state.shown < rows.length) { const t = grid.scrollTop; state.shown += CONFIG.pageSize; render(); const g = $(".cards"); if (g) g.scrollTop = t; } });
  return grid;
}
function suppliersTab(rows) {
  const by = {};
  for (const r of rows) { const s = r.supplier || "(none)"; (by[s] = by[s] || []).push(r); }
  const list = Object.entries(by).map(([s, rs]) => { const m = rs.filter(r => r.metres && r.price && r.should); const met = m.reduce((a, r) => a + r.metres, 0); return { s, n: rs.length, met, paid: met ? m.reduce((a, r) => a + r.price * r.metres, 0) / met : null, should: met ? m.reduce((a, r) => a + r.should * r.metres, 0) / met : null, above: rs.filter(r => r.band === "Above range").length, unsure: rs.filter(r => r.band === "Tool unsure").length }; }).sort((a, b) => b.n - a.n);
  return h("div", { class: "gridscroll" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Supplier", "Fabrics", "Metres", "Paid Rs/m (avg over metres)", "Should-cost Rs/m", "Paid above", "Above range", "Tool unsure"].map((t, i) => h("th", { class: i ? "n" : "" }, t)))),
    h("tbody", {}, list.map(x => h("tr", {}, h("td", {}, h("button", { type: "button", class: "code", onclick: () => { state.filters.supplier = [x.s]; state.tab = "items"; rerunWithSkeleton(); } }, x.s)), h("td", { class: "n" }, n0(x.n)), h("td", { class: "n" }, n0(x.met)), h("td", { class: "n" }, n2(x.paid)), h("td", { class: "n" }, n2(x.should)), h("td", { class: "n" }, x.paid ? pc((x.paid / x.should - 1) * 100) : ""), h("td", { class: "n" }, n0(x.above)), h("td", { class: "n" }, n0(x.unsure)))))));
}
function renderSelbar() {
  const bar = $("#selbar"), n = state.selection.size, pend = Object.keys(state.pending).length;
  if (!n && !pend) { bar.hidden = true; return; }
  bar.hidden = false;
  const picked = state.rows.filter(r => state.selection.has(keyOf(r)));
  bar.replaceChildren(
    n ? [tipOn(h("button", { type: "button", class: "clear", onclick: () => { state.selection.clear(); render(); } }), "Clear the selection"), h("span", { class: "n" }, String(n)), h("span", { class: "lbl" }, n === 1 ? "ITEM SELECTED" : "ITEMS SELECTED")] : null,
    pend ? h("span", { class: "lbl", style: "margin-left:16px" }, `${pend} unsaved ${pend === 1 ? "change" : "changes"}`) : null,
    pend ? h("button", { type: "button", class: "btn fill", onclick: saveEdits }, "Save") : null,
    pend ? h("button", { type: "button", class: "btn", onclick: () => { state.pending = {}; render(); } }, "Discard") : null,
    h("span", { class: "spacer" }),
    n ? [ib("edit", "Edit: set status or remarks on the selected rows", () => bulkEdit(picked)), ib("share", "Share: copy the codes and a note", () => share(picked)),
      ib("dots", "More", e => menu(e.currentTarget, [
        { label: "Add Items to Save Search", run: () => addToSaved(picked) },
        { label: "Download Selected", run: () => download("/api/costs/download", { keys: picked.map(keyOf) }, "RightCost selected.xlsx").then(() => toast("Downloaded")).catch(err => toast(err.message, false)) },
        { label: picked.length === 1 ? "Open in Cost a fabric" : "Open in Cost a fabric (tick one)", run: () => picked.length === 1 ? openCostPopup(picked[0]) : toast("Tick one row to open it", false) },
      ], { right: true }))] : null);
}

// ------------------------------------------------------------------ detail page and quick view
function fields(r) {
  return [["Fabric code", r.code], ["Source", r.source], ["Description", r.description], ["Supplier", r.supplier], ["Route", r.route], ["Weave", r.weave], ["Weave group", r.weave_group],
    ["Finish", r.finish], ["Pattern", r.pattern], ["Warp yarn", r.warp], ["Weft yarn", r.weft], ["EPI × PPI", r.epi ? `${n0(r.epi)} × ${n0(r.ppi)}` : ""], ["Finished width (in)", r.width],
    ["Weight (g/m²)", r.gsm ? Number(r.gsm).toFixed(0) : ""], ["Should-cost Rs/m", n2(r.should)], ["Should-cost Rs/kg", r.per_kg ? n0(r.per_kg) : ""], [r.source === "Purchase orders" ? "Price paid Rs/m" : "Mill's quote Rs/m", n2(r.price)],
    ["Above should-cost", r.price ? `Rs ${n2(r.gap)} (${pc(r.gap_pct)})` : ""], ["Against the usual range", r.band + (r.range ? ` (usual ${pc(r.range[0])} to ${pc(r.range[1])})` : "")], ["Why the tool is unsure", (r.band === "Tool unsure" && r.why_unsure || []).join("; ")], ["Metres", n0(r.metres)],
    ["Paid above should-cost, Rs", n0(r.excess)], ["Order size", r.order_size], ["Quantity band", r.qty_band], ["Placeholder rates used", r.placeholders || "None"], ["Held back (calibration test)", val(r, "held_back")],
    ["Added on", r.added || ""], ["Not costed because", (r.problems || []).join("; ")]].filter(([, v]) => v !== "" && v !== null && v !== undefined);
}
function quickView(r) {
  document.querySelectorAll(".side").forEach(e => e.remove());
  const p = h("aside", { class: "side", "aria-label": "Quick view" }, h("div", { style: "display:flex;justify-content:space-between;align-items:center" }, h("h2", {}, r.code), ib("x", "Close", () => p.remove())),
    h("div", { style: "color:var(--text2);font-size:12px" }, r.description || ""), h("dl", { class: "kv" }, fields(r).map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
    h("div", { style: "margin-top:14px;display:flex;gap:8px" }, h("button", { type: "button", class: "btn fill", onclick: () => { p.remove(); openDetail(r); } }, "Open"), h("button", { type: "button", class: "btn line", onclick: () => openCostPopup(r) }, "Open in Cost a fabric")));
  document.body.append(p);
}
function openDetail(r) {
  closeLayers(); state.library = null;
  state.detail = { key: keyOf(r), tab: "item", editing: false };
  state.recent = [{ key: keyOf(r), code: r.code, at: new Date().toISOString() }, ...state.recent.filter(v => v.key !== keyOf(r))].slice(0, 12); store.set("recent", state.recent);
  scrollTo(0, 0); render();
}
function renderDetail(main) {
  const r = state.rows.find(x => keyOf(x) === state.detail.key);
  if (!r) { state.detail = null; return render(); }
  const d = state.detail, k = keyOf(r);
  const crumbs = h("div", { class: "crumb" }, h("a", { href: "/#dashboard", html: svg("home", 'width="12" height="12"') }), "›", "Costing", "›", h("button", { type: "button", onclick: () => { state.detail = null; render(); } }, CONFIG.appName), "›", h("span", {}, r.code));
  const headIcons = h("div", { class: "dicons" }, ib("pin", "Show in the list", () => { state.detail = null; state.search.active = { text: r.code, mode: "exact" }; state.search.text = r.code; state.cls = r.source; render(); }),
    ib("pdf", "Print this page", () => print()), ib("comment", "Remarks", () => { d.tab = "item"; d.editing = true; render(); setTimeout(() => { const el = $("#f-remarks"); if (el) el.focus(); }, 0); }),
    ib("open", "Open in Cost a fabric", () => openCostPopup(r)));
  const head = h("div", { class: "dhead" }, h("div", { class: "bigimg", style: { background: ROUTE_COLOR[r.route] || "#B9BEC7" } }, (r.route || "").split(/[ /]/)[0].toUpperCase()), h("div", {}, h("div", { class: "small" }, `${r.code} · ${r.source}`), h("h1", {}, r.description || r.code)), headIcons);
  const tabs = h("div", { class: "tabs" }, [["item", "Item"], ["costing", "Costing"], ["negotiation", "Negotiation"], ["log", "Log"]].map(([t, l]) => h("button", { type: "button", class: "tab" + (d.tab === t ? " on" : ""), onclick: () => { d.tab = t; render(); } }, l)));
  let content;
  if (d.tab === "item") {
    const edit = state.edits[k] || {};
    const statusIn = h("select", { id: "f-status", disabled: !d.editing || null }, STATUS.map(o => h("option", {}, o))); statusIn.value = edit.status || "Not started";
    const remIn = h("input", { id: "f-remarks", type: "text", value: edit.remarks || "", disabled: !d.editing || null });
    content = [h("div", { style: "margin-top:12px;display:flex;gap:8px" }, d.editing ? [h("button", { type: "button", class: "btn fill", onclick: () => { state.edits[k] = { status: statusIn.value, remarks: remIn.value }; store.set("edits", state.edits); addLog(`${r.code}: status ${statusIn.value}${remIn.value ? `, remarks "${remIn.value}"` : ""}`); d.editing = false; toast("Saved Successfully!"); render(); } }, "Save"), h("button", { type: "button", class: "btn", onclick: () => { d.editing = false; render(); } }, "Discard")] : h("button", { type: "button", class: "btn line", onclick: () => { d.editing = true; render(); } }, "Edit status and remarks")),
      h("div", { class: "form2" }, h("div", { class: "f" }, h("span", {}, "Status"), statusIn), h("div", { class: "f" }, h("label", { for: "f-remarks" }, "Remarks"), remIn), fields(r).map(([k2, v]) => h("div", { class: "f" }, h("span", {}, k2), h("span", {}, String(v))))),
      h("p", { style: "color:var(--text2);font-size:11px;margin-top:10px" }, "Status and remarks are kept in this browser only.")];
  } else if (d.tab === "costing") {
    content = r.buckets ? costingTab(r) : h("div", { class: "empty" }, "Open it in Cost a fabric for the full build-up.", h("div", { style: "margin-top:10px" }, h("button", { type: "button", class: "btn fill", onclick: () => openCostPopup(r) }, "Open in Cost a fabric")));
  } else if (d.tab === "negotiation") {
    content = h("div", { class: "brief" }, "Working it out…"); negotiationTab(r, content);
  } else {
    const mine = state.log.filter(x => x.text.startsWith(r.code + ":"));
    content = h("div", { class: "log" }, mine.length ? mine.map(x => h("div", {}, `${new Date(x.at).toLocaleString("en-IN")} · ${x.text.slice(r.code.length + 2)}`)) : h("div", { class: "empty" }, "No changes recorded in this browser."));
  }
  main.replaceChildren(crumbs, head, tabs, content);
  renderSelbar();
}
function costingTab(r) {
  const b = r.buckets, top = Math.max(...Object.values(b).map(v => Math.abs(v || 0)), 1);
  return h("div", { class: "buckets" }, Object.entries(b).map(([name, v]) => h("div", { class: "bk" }, h("span", {}, name), h("div", {}, h("div", { class: "b", style: { width: Math.abs(v || 0) / top * 100 + "%" } })), h("span", { style: "text-align:right" }, n2(v)), h("span", { style: "text-align:right;color:var(--text2)" }, r.should ? (100 * (v || 0) / r.should).toFixed(1) + "%" : ""))),
    h("div", { class: "bk tot" }, h("span", {}, "Should-cost"), h("span"), h("span", { style: "text-align:right" }, n2(r.should)), h("span", { style: "text-align:right" }, "100%")),
    r.price ? h("div", { class: "bk" }, h("span", {}, "Price paid"), h("span"), h("span", { style: "text-align:right" }, n2(r.price)), h("span", { style: "text-align:right" }, pc(r.gap_pct))) : null,
    h("p", { style: "color:var(--text2);font-size:11px" }, "Rs per metre, as costed in the pilot on the rates of 24 Nov 2026. Opened in Cost a fabric it is costed again on today's rates."),
    h("button", { type: "button", class: "btn fill", onclick: () => openCostPopup(r) }, "Open in Cost a fabric"));
}
async function negotiationTab(r, box) {
  if (!r.choices || !r.price) { box.textContent = "No price on this row, so there is nothing to negotiate yet."; return; }
  try {
    const res = await (await fetch("/api/cost", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r.choices) })).json();
    const b = res.brief; if (!b) { box.textContent = "No brief: the price is not usable."; return; }
    const label = { push: ["Push", "#E5484D"], fair: ["Fair", "#2E9E5B"], below: ["Below", "#3D8BFD"], ask: ["Ask for the break-up", "#B98900"] }[b.stance];
    box.replaceChildren(h("div", {}, h("span", { class: "st", style: { background: label[1] + "22", color: label[1] } }, b.implausible ? "Check the quote first" : label[0]), ` On today's rates the should-cost is Rs ${n2(b.should)}; the price is Rs ${n2(b.quote)}, Rs ${n2(Math.abs(b.gap))} ${b.gap >= 0 ? "above" : "below"}.`),
      h("ul", {}, h("li", {}, `Usual range for this fabric: Rs ${n2(b.lower)} to Rs ${n2(b.settle_up_to)} (${b.band.why}).`), b.stance === "push" ? h("li", {}, `Open at Rs ${n2(b.open_at)}; aim for Rs ${n2(b.settle_up_to)}.`) : null,
        b.weak.length ? h("li", {}, "Why no target: " + b.weak.join("; ") + ".") : null, (b.caveats || []).map(c => h("li", {}, c)),
        b.at_stake !== null && b.quantity ? h("li", {}, `On ${n0(b.quantity)} m that is Rs ${n0(Math.abs(b.at_stake))} ${b.gap >= 0 ? "above" : "below"} should-cost.`) : null),
      h("button", { type: "button", class: "btn fill", onclick: () => openCostPopup(r) }, "Full brief in Cost a fabric"));
  } catch (e) { box.textContent = "Could not work it out: " + e.message; }
}

// ------------------------------------------------------------------ Cost a fabric in a popup
function openCostPopup(r) {
  closeLayers();
  const frame = h("iframe", { src: "/?embed=1#cost", title: "Cost a fabric" });
  const close = () => { s.remove(); load(); };
  const pop = h("div", { class: "popup", role: "dialog", "aria-modal": "true", "aria-label": "Create cost" },
    h("div", { class: "ph" }, h("h2", {}, r ? `Cost ${r.code}` : "Create cost"), h("div", { style: "display:flex;gap:8px;align-items:center" }, h("span", { style: "color:var(--text2);font-size:11px" }, "Add to list keeps it; it then shows here under Fabric list"), ib("x", "Close", close))), frame);
  const s = h("div", { class: "scrim", onmousedown: e => { if (e.target === s) close(); } }, pop);
  s.dataset.popup = "1";
  frame.addEventListener("load", () => { const w = frame.contentWindow; const t = setInterval(() => { if (w.rpOpen) { clearInterval(t); w.rpOpen(r ? r.choices : null, r && r.source === "Fabric list" ? r.id : null); } }, 60); setTimeout(() => clearInterval(t), 8000); });
  $("#layer").append(s);
}

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
  const crumbs = h("div", { class: "crumb" }, h("a", { href: "/#dashboard", html: svg("home", 'width="12" height="12"') }), "›", "Library", "›", h("span", {}, L.name));
  const tools = h("div", { class: "toolbar" },
    h("button", { type: "button", class: "btn fill", disabled: !changed || null, onclick: () => { state.libs[L.name] = clean(rows).filter(r => r.name.trim()); store.set("libs", state.libs); L.draft = null; toast("Saved Successfully!"); render(); } }, "Save"),
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
    h("button", { type: "button", class: "btn", "aria-label": "Next page", disabled: L.page >= pages - 1 || null, onclick: () => { L.page++; render(); } }, "›"),
    [20, 50, 100].map(n => h("button", { type: "button", class: "btn" + (L.size === n ? " fill" : ""), onclick: () => { L.size = n; L.page = 0; render(); } }, String(n))));
  main.replaceChildren(crumbs, h("h1", { class: "title", style: "cursor:default" }, L.name),
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
function applySaved(x) { state.saved = x.name; state.filters = JSON.parse(JSON.stringify(x.filters || {})); if (x.codes) state.filters._codes = x.codes; if (x.search) { state.search.active = x.search; state.search.text = x.search.text; } else { state.search.active = null; state.search.text = ""; } rerunWithSkeleton(); }
function deleteSaved() {
  const sel = h("select", {}, state.userSearches.map(s => h("option", {}, s.name)));
  const d = dialog("Delete a saved search", sel, [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => { state.userSearches = state.userSearches.filter(s => s.name !== sel.value); store.set("searches", state.userSearches); if (state.saved === sel.value) state.saved = "Default"; d.remove(); toast("Deleted"); render(); } }, "Delete")]);
}
function saveSearchPrompt() {
  const name = h("input", { type: "text", placeholder: "For example: Arvind twills above range" });
  const d = dialog("Save Search", [h("p", { class: "sub" }, "Keep these filters and the search under a name, to choose again from the saved search list."), name],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Not now"), h("button", { type: "button", class: "btn fill", onclick: () => {
      const n = name.value.trim(); if (!n) return name.focus();
      const f = Object.assign({}, state.filters); delete f._codes;
      state.userSearches = [...state.userSearches.filter(s => s.name !== n), { name: n, filters: f, search: state.search.active }]; store.set("searches", state.userSearches);
      state.saved = n; d.remove(); toast("Saved Successfully!"); render();
    } }, "Save")]);
  name.addEventListener("keydown", e => { if (e.key === "Enter") d.querySelector(".btn.fill").click(); });
}
function addToSaved(picked) {
  const mine = state.userSearches;
  const rNew = h("input", { type: "radio", name: "how", checked: true }), rOld = h("input", { type: "radio", name: "how", disabled: !mine.length || null });
  const name = h("input", { type: "text", placeholder: "Name of the new search" }), old = h("select", { disabled: !mine.length || null }, mine.map(s => h("option", {}, s.name)));
  const d = dialog("Add Items to Save Search", [h("label", { class: "row" }, rNew, "Create a New Search"), name, h("label", { class: "row" }, rOld, "Update an Existing Search"), old, !mine.length ? h("p", { class: "sub" }, "No saved search yet.") : null],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => {
      const codes = picked.map(keyOf);
      if (rNew.checked) { const n = name.value.trim(); if (!n) return name.focus(); state.userSearches = [...mine.filter(s => s.name !== n), { name: n, codes }]; }
      else { const s = mine.find(x => x.name === old.value); s.codes = [...new Set([...(s.codes || []), ...codes])]; }
      store.set("searches", state.userSearches); d.remove(); toast("Saved Successfully!"); render();
    } }, "Save")]);
}
function bulkEdit(picked) {
  const st = h("select", {}, h("option", { value: "" }, "(leave as it is)"), STATUS.map(o => h("option", {}, o))), rem = h("input", { type: "text", placeholder: "Leave blank to keep each row's remarks" });
  const d = dialog(`Edit ${picked.length} ${picked.length === 1 ? "item" : "items"}`, [h("label", { class: "row" }, "Status"), st, h("label", { class: "row" }, "Remarks"), rem, h("p", { class: "sub" }, "Kept in this browser. Costing figures cannot be edited here; open a fabric in Cost a fabric to change its choices.")],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Cancel"), h("button", { type: "button", class: "btn fill", onclick: () => {
      for (const r of picked) { const k = keyOf(r), e = Object.assign({}, state.edits[k] || {}); if (st.value) e.status = st.value; if (rem.value.trim()) e.remarks = rem.value.trim(); state.edits[k] = e; addLog(`${r.code}: ${st.value ? "status " + st.value : ""}${st.value && rem.value.trim() ? ", " : ""}${rem.value.trim() ? `remarks "${rem.value.trim()}"` : ""}`); }
      store.set("edits", state.edits); d.remove(); toast("Saved Successfully!"); render();
    } }, "Save")]);
}
function share(picked) {
  const msg = h("textarea", { rows: "4" }, `${picked.length} fabrics from Right cost: ${picked.map(r => r.code).join(", ")}`);
  const d = dialog("Share", [h("p", { class: "sub" }, "There are no user accounts in RightPrice to send to. Copy the codes and paste them where you need them; Exact Search finds them again."), msg],
    [h("button", { type: "button", class: "btn", onclick: () => d.remove() }, "Close"), h("button", { type: "button", class: "btn fill", onclick: async () => { try { await navigator.clipboard.writeText(msg.value); toast("Copied"); } catch (e) { msg.select(); toast("Select and copy the text", false); } } }, "Copy")]);
}
function saveEdits() {
  for (const [k, p] of Object.entries(state.pending)) { state.edits[k] = Object.assign({}, state.edits[k] || {}, p); const r = state.rows.find(x => keyOf(x) === k); addLog(`${r ? r.code : k}: ${Object.entries(p).map(([f, v]) => `${f} ${v}`).join(", ")}`); }
  store.set("edits", state.edits); state.pending = {}; toast("Saved Successfully!"); render();
}
function moreAction(a, rows) {
  const src = state.cls === "*" ? null : state.cls;
  if (a === "Download Excel") download("/api/costs/download", { keys: rows.map(keyOf) }, "RightCost.xlsx").then(() => toast("Download Excel ready – see Downloads")).catch(e => toast(e.message, false));
  else if (a === "Download Excel with Images") download("/api/costs/download", { keys: rows.map(keyOf) }, "RightCost.xlsx").then(() => toast("There are no fabric images yet; downloaded without them – see Downloads")).catch(e => toast(e.message, false));
  else if (a === "Bulk Upload") location.href = "/#bulk";
  else if (a === "Download Templatised Data") { location.href = "/api/template"; state.downloads.unshift({ name: "RightPrice template.xlsx", at: new Date().toISOString() }); toast("Template downloading – see Downloads"); }
  else if (a === "Negotiation Pack") location.href = "/#pack";
  else toast(`${a}: the Dashboard and Pilot results hold the reports`, false);
  void src;
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
  const pool = state.rows.filter(r => state.cls === "*" || r.source === state.cls);
  const open = new Set(Object.keys(draft));
  const list = h("div", { class: "body" });
  const paintList = q => list.replaceChildren(...attrs.filter(a => !q || a.label.toLowerCase().includes(q)).map(a => {
    const cnt = Array.isArray(draft[a.id]) ? draft[a.id].length : draft[a.id] ? 1 : 0;
    const box = h("div", { class: "attr" }, h("button", { type: "button", "aria-expanded": String(open.has(a.id)), onclick: () => { open.has(a.id) ? open.delete(a.id) : open.add(a.id); paintList(q); } }, h("span", {}, a.label, cnt ? h("span", { class: "cnt" }, `(${cnt})`) : null), h("span", {}, open.has(a.id) ? "⌄" : "›")));
    if (open.has(a.id)) {
      if (a.num || a.date) {
        const f = draft[a.id] || (a.date ? { date: true, from: "", to: "" } : { min: "", max: "" });
        const i1 = h("input", { type: a.date ? "date" : "number", value: a.date ? f.from : f.min, "aria-label": a.label + (a.date ? " from" : " minimum"), placeholder: a.date ? null : "Min" });
        const i2 = h("input", { type: a.date ? "date" : "number", value: a.date ? f.to : f.max, "aria-label": a.label + (a.date ? " to" : " maximum"), placeholder: a.date ? null : "Max" });
        const upd = () => { const v = a.date ? { date: true, from: i1.value, to: i2.value } : { min: i1.value, max: i2.value }; if ((a.date ? v.from || v.to : v.min !== "" || v.max !== "")) draft[a.id] = v; else delete draft[a.id]; };
        i1.addEventListener("input", upd); i2.addEventListener("input", upd);
        box.append(h("div", { class: "vals" }, a.date ? [h("span", {}, "From"), i1, h("span", {}, "To"), i2] : h("div", { class: "mm" }, i1, i2)));
      } else {
        const counts = {}; for (const r of pool) { const v = String(val(r, a.id) ?? ""); if (v) counts[v] = (counts[v] || 0) + 1; }
        const values = Object.keys(counts).sort((x, y) => counts[y] - counts[x]);
        const mini = h("input", { type: "text", placeholder: "Search", "aria-label": `Search ${a.label}` });
        const vals = h("div");
        const paintVals = () => vals.replaceChildren(...values.filter(v => !mini.value || v.toLowerCase().includes(mini.value.toLowerCase())).slice(0, 200).map(v => {
          const cb = h("input", { type: "checkbox", class: "cb" }); cb.checked = (draft[a.id] || []).includes(v);
          cb.addEventListener("change", () => { const cur = new Set(draft[a.id] || []); cb.checked ? cur.add(v) : cur.delete(v); if (cur.size) draft[a.id] = [...cur]; else delete draft[a.id]; });
          return h("label", {}, cb, `${v} (${counts[v]})`);
        }));
        mini.addEventListener("input", paintVals); paintVals();
        box.append(h("div", { class: "vals" }, values.length > 8 ? mini : null, vals, values.length ? null : h("span", { style: "color:var(--text2)" }, "No values")));
      }
    }
    return box;
  }));
  const search = h("input", { type: "text", placeholder: "Search Filter", "aria-label": "Search the filter attributes" });
  search.addEventListener("input", () => paintList(search.value.toLowerCase()));
  const sw = h("input", { type: "checkbox", class: "cb" }); sw.checked = costed; sw.addEventListener("change", () => { costed = sw.checked; });
  dr.replaceChildren(h("div", { class: "hd" }, "Advanced Filter", ib("x", "Close", () => { dr.hidden = true; })), h("div", { class: "fs", html: svg("search", 'width="14" height="14"') }, search), list,
    h("div", { class: "ft" }, h("label", { class: "switch" }, "Costed only (leave out rows not costed)", sw), h("div", { style: "display:flex;justify-content:space-between" },
      h("button", { type: "button", class: "btn", onclick: () => { for (const k of Object.keys(draft)) delete draft[k]; costed = false; sw.checked = false; open.clear(); paintList(""); } }, "Clear Filter"),
      h("button", { type: "button", class: "btn fill", onclick: () => { const codes = state.filters._codes; state.filters = draft; if (codes) state.filters._codes = codes; state.costedOnly = costed; state.saved = "Default"; dr.hidden = true; rerunWithSkeleton(); if (Object.keys(draft).length) setTimeout(saveSearchPrompt, 450); } }, "Apply Filter"))));
  paintList(""); dr.hidden = false; search.focus();
}

addEventListener("keydown", e => {
  if (e.key === "Escape") { const pop = document.querySelector(".scrim"); if (pop) { if (pop.dataset.popup) { pop.remove(); load(); } else pop.remove(); return; } closeLayers(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f" && !state.detail) { e.preventDefault(); const s = $("#search"); if (s) s.focus(); }
});
addEventListener("message", e => { if (e.origin === location.origin && e.data && e.data.rp === "listChanged") load(); });
addEventListener("beforeunload", e => { if (Object.keys(state.pending).length) { e.preventDefault(); e.returnValue = ""; } });

async function load() {
  try {
    const d = await (await fetch("/api/costs")).json();
    state.rows = d.rows; state.counts = d.counts;
    clearTimeout(load.t); if (!d.ready) load.t = setTimeout(load, 4000);       // the verdicts are worked out in the background
    if (!state.counts[state.cls] && state.cls !== "*") state.cls = state.counts["Purchase orders"] ? "Purchase orders" : "Fabric list";
    render();
  } catch (err) { $("#main").replaceChildren(h("div", { class: "empty" }, "The costings could not be loaded: " + err.message)); }
}
renderRail(); render(); load(); whoAmI();
