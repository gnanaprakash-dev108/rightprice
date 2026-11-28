/* The pages of the shell (stage 4 of the rebuild, 27 Nov 2026): the screens of the earlier front end, moved into
   the shell one by one, each in its own file in web/pages/.

   Adding a page is one small registration. The page's file calls
       RP.page("yarn", { title: "Yarn prices", section: "Prices" }, async (arg, ctx) => [nodes]);
   and rightcost.html loads the file (one <script> line, before rightcost.js; and a <link> for its stylesheet if
   it has one). The shell then shows the page at #yarn (anything after a "/" in the address is passed as arg), under
   its heading and, when it names a section, among that section's tabs. A page with { popup: true } is a tab of the
   New cost popup instead. Options:
     title    the heading, the browser tab's title and the tab's label
     section  "Home" or "Prices" (a tab there, and the rail item lit); leave it out for a page reached from elsewhere
     popup    true: a tab of the New cost popup (the shell's CONFIG.popupTabs lists those tabs)
     look     "shell" for a page drawn with the shell's own classes (rightcost.css); by default a page has the look
              of the earlier screens (web/pages/common.css), scoped to it
   ctx, given to the page: ctx.root (the page's own box), ctx.reload() (draw the page again), ctx.inPopup, and in the
   popup ctx.tab(id) (go to another tab of the popup).
   Who may open the page is web/access.js's PAGE_NEEDS (a page) or TAB_NEEDS (a popup tab): name the page there too.
   Inside the page, RP.kit.can("do:...") says whether this person's role may do something; offer only what it may
   (the server refuses the rest whatever the page shows).

   This file is what the pages share: the page list, the state they share (the fabric open in Create cost, the
   list's ticks), small helpers, tables, and the requests to the server. Every number comes from the server; nothing
   is costed here. Plain JavaScript, no build step. Each file is wrapped in a function, so its names stay its own;
   what is shared is under RP. */
"use strict";
window.RP = (function () {
  // ------------------------------------------------------------------ the page list
  const pages = {};
  function page(id, spec, render) {
    pages[id] = Object.assign({ id, title: id, section: null, popup: false, look: "pages" }, spec, { render });
  }

  // what the pages share while the shell is open; the popup's part starts afresh each time the popup opens
  const state = { meta: null, sel: null, list: null, listId: null, sim: null, visited: new Set(), bySize: true, chart: "bars", wfMode: "groups", wfOpen: new Set(), showZero: false, dash: null };
  function fresh() {
    Object.assign(state, { sel: null, listId: null, rowNotes: null, sim: null, reopened: null, openStep: null, countOpen: false, listUI: null, cmp: null, packUI: null,
      bySize: true, chart: "bars", wfMode: "groups", showZero: false });
    state.visited.clear(); state.wfOpen.clear();
  }

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
    for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
    return el;
  }
  // replaceChildren turns an array or a null into text: flatten and drop the empties first
  const fill = (el, ...kids) => { el.replaceChildren(...kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false)); return el; };
  const svg = (d, size = 18) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const tidy = (v, d) => (Math.abs(Number(v)) < 0.5 / 10 ** d ? 0 : Number(v));          // never "-0.00"
  const fmt = (v, d = 2) => tidy(v, d).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−");
  const rs = (v, d = 2) => (tidy(v, d) < 0 ? "−" : "") + "Rs " + fmt(Math.abs(v), d);
  const day = iso => { const d = new Date(iso); return isNaN(d) ? String(iso ?? "") : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); };
  const pct = (v, d = 1) => (v * 100).toFixed(d) + "%";
  const pctSigned = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
  const plural = (n, w) => `${fmt(n, 0)} ${w}${n === 1 ? "" : "s"}`;
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
  // the shell's own message at the foot of the page (ok: false for something that went wrong)
  function toast(msg, ok = true) { if (RP.shell) RP.shell.toast(msg, ok); }
  // what this person's role may do (stage 3, web/access.js); everything while permissions are off or not yet known
  const allowed = perm => { try { return typeof can !== "function" || can(perm); } catch (e) { return true; } };
  const known = () => { try { return typeof RPA === "object" && RPA.ready ? RPA.ready : null; } catch (e) { return null; } };
  // the rate master's drop-down lists, read afresh: each page opened and each New cost popup reads them again, so a yarn
  // added by someone else shows without reloading the browser
  async function loadMeta() { state.meta = await getJSON("/api/meta"); return state.meta; }

  // tooltip: one element, beside the pointer or the focused row; it may hold a little HTML (a name in bold, a line break)
  let tipEl = null;
  function showTip(html, x, y) {
    if (!tipEl) { tipEl = h("div", { class: "pgtip", role: "tooltip", hidden: true }); document.body.append(tipEl); }
    tipEl.innerHTML = html; tipEl.hidden = false;
    const r = tipEl.getBoundingClientRect();
    tipEl.style.left = Math.max(8, Math.min(x + 14, innerWidth - r.width - 8)) + "px";
    tipEl.style.top = Math.max(8, Math.min(y + 14, innerHeight - r.height - 8)) + "px";
  }
  const hideTip = () => { if (tipEl) tipEl.hidden = true; };
  // Escape closes a chart's tooltip first (and nothing else); a second Escape is the shell's (it closes the popup)
  addEventListener("keydown", e => { if (e.key === "Escape" && tipEl && !tipEl.hidden) { hideTip(); e.stopImmediatePropagation(); } }, true);
  function withTip(el, html) {
    el.addEventListener("mousemove", e => showTip(html(), e.clientX, e.clientY));
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("focusin", () => { const r = el.getBoundingClientRect(); showTip(html(), r.left + 40, r.bottom - 10); });
    el.addEventListener("focusout", hideTip);
  }
  // the shell shows the page's title in its heading: the page itself starts with the line under it
  function pageHead(title, sub) { return [h("p", { class: "sub" }, sub)]; }

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
    const paint = list => fill(body, list.map(r => {
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
        h("td", {}, h("button", { class: "icon-btn sm", type: "button", "aria-label": "Remove this row", title: "Remove this row", onclick: () => tr.remove() }, "×")));
      body.append(tr); return tr;
    };
    t.rows.forEach(addRow);
    const msg = h("div", { "aria-live": "polite" });
    const save = h("button", { class: "btn primary", type: "button", onclick: async () => {
      const rows = [...body.rows].map(tr => [...tr.querySelectorAll("input")].map((inp, i) => inp.value.trim() === "" ? null : (numeric[i] ? Number(inp.value) : inp.value.trim())));
      save.disabled = true;
      try { await api("/api/table/" + sheet, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ columns: t.columns, rows }) }); state.meta = await getJSON("/api/meta"); state.dash = null; toast("Saved to the rate master"); done(); }
      catch (e) { fill(msg, h("div", { class: "notice err", role: "alert" }, e.message)); save.disabled = false; }
    } }, "Save");
    return h("div", {},
      h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Editing " + t.label }, h("table", { class: "edit" }, h("thead", {}, h("tr", {}, t.columns.map(c => h("th", { scope: "col" }, c)), h("th", {}, h("span", { class: "visually-hidden" }, "Remove")))), body)),
      msg,
      h("div", { class: "row-actions" }, save, h("button", { class: "btn", type: "button", onclick: () => { addRow(null).querySelector("input").focus(); } }, "Add a row"), h("button", { class: "btn", type: "button", onclick: done }, "Cancel")),
      h("p", { class: "sub", style: "margin:12px 0 0" }, "Saving changes the rate master for every costing from now on. The first change of each day keeps a dated copy of the workbook beside it."));
  }
  function tableCard(sheet, title, opts = {}) {
    const box = h("div"), editBtn = h("button", { class: "btn", type: "button" }, "Edit");
    const view = async () => { editBtn.hidden = !state.meta.editable.includes(sheet) || !allowed("do:edit_rates"); const t = await getJSON("/api/table/" + sheet); fill(box, dataTable(t, { filter: t.rows.length > 12, label: t.label, query: opts.query })); };
    editBtn.addEventListener("click", async () => { editBtn.hidden = true; fill(box, editTable(await getJSON("/api/table/" + sheet), sheet, view)); });
    const card = h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, title), h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, opts.extra, editBtn)), box);
    return view().then(() => card);
  }
  // a page of rate tables, one shown at a time, chosen by the chips above it (Rate tables, Mill rate card, Settings)
  function tabbed(title, sub, sheets, first) {
    return async (want) => {
      const box = h("div");
      const chips = h("div", { class: "chips", role: "tablist", "aria-label": title });
      const open = async sheet => {
        [...chips.children].forEach(c => c.setAttribute("aria-selected", String(c.dataset.sheet === sheet)));
        fill(box, h("p", { class: "empty" }, "Loading..."));
        current = sheet; editBtn.hidden = !state.meta.editable.includes(sheet) || !allowed("do:edit_rates");
        try { const t = await getJSON("/api/table/" + sheet); fill(box, dataTable(t, { filter: t.rows.length > 12, label: t.label })); }
        catch (e) { fill(box, h("div", { class: "notice err" }, e.message)); }
      };
      let current;
      const editBtn = h("button", { class: "btn", type: "button", onclick: async () => { editBtn.hidden = true; const sheet = current; fill(box, editTable(await getJSON("/api/table/" + sheet), sheet, () => open(sheet))); } }, "Edit this table");
      for (const s of sheets) chips.append(h("button", { class: "chip", role: "tab", "data-sheet": s, onclick: () => open(s) }, state.meta.tables[s]));
      await open(sheets.includes(want) ? want : first || sheets[0]);
      return [...pageHead(title, sub),
        h("div", { class: "card" }, h("div", { class: "card-head" }, chips, editBtn), box,
          h("div", { class: "notice info" }, "Basis shows where each number came from. ", h("span", { class: "tag warn" }, "⚠ Placeholder"), " marks a starting guess with no data behind it; the cost view warns whenever one is used."))];
    };
  }
  const GROUP_COLOR = ["--g1", "--g2", "--g3", "--g4", "--g5", "--g6", "--g7", "--g8"];

  // ------------------------------------------------------------------ showing a page
  /* Draws page id into box, the shell's scrolling box for it: "Loading..." first, then the page. A page drawn again
     over itself (ctx.reload) or replaced by another before it finished is never painted twice. */
  async function show(id, arg, box, ctx = {}) {
    const p = pages[id], token = box.rpToken = Symbol(), fresh = !!ctx.freshMeta;
    const root = h("div", { class: p.look === "shell" ? "pgshell" : "pg" });
    box.dataset.page = id;
    ctx = Object.assign({ inPopup: false }, ctx, { root: box, freshMeta: false, reload: () => show(id, arg, box, ctx) });
    hideTip();
    fill(box, fill(root, h("p", { class: "empty" }, "Loading...")));
    try {
      if (known()) await known();               // what this person may do is known before the page offers anything
      if (!state.meta || fresh) await loadMeta();
    } catch (e) { if (box.rpToken === token) fill(root, h("div", { class: "notice err" }, "The rate master could not be read: " + e.message)); return; }
    try {
      const nodes = await p.render(arg || "", ctx);
      if (box.rpToken !== token) return;
      fill(root, nodes);
      box.scrollTop = 0;
    } catch (e) { if (box.rpToken === token) fill(root, h("div", { class: "notice err" }, "This page could not be loaded: " + e.message)); }
  }

  return { pages, page, show, state, fresh, loadMeta, known, shell: null,
    kit: { $, h, fill, svg, fmt, rs, day, pct, pctSigned, plural, blank, api, getJSON, postJSON, download, toast, can: allowed, showTip, hideTip, withTip, pageHead,
      cellText, basisTag, dataTable, editTable, tableCard, tabbed, GROUP_COLOR } };
})();
