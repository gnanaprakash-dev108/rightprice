/* The Fab library (GP's decision, 28 Nov 2026): the PLM fabric code list, every code with its construction, its Fab group
   and its purchases; and the admin upload of the list (read in the background, like purchase files). Loaded after
   purchases.js (it adds its pages to RP_PAGES and uses RP_PURCH's price popup) and before rightcost.js; it uses the
   shell's own helpers (h, fill, svg, ib, tipOn, n0, n2, toast, dayOf, state ...) when it runs, never while it loads.
   Pages: #fab-library (search, uploads) and #fab-library/<code> (one code). Drawn inside .rp-purch, with stage 2's look. */
"use strict";
(function () {
  const may = perm => typeof can !== "function" || can(perm);
  const known = async () => { if (typeof RPA !== "undefined") await RPA.ready; };
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    let body = null; try { body = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) throw new Error((body && body.detail) || r.statusText || "Request failed");
    return body;
  };
  const day = iso => iso ? dayOf(String(iso).slice(0, 10)) : "";
  const fillP = (main, ...kids) => fill(main, h("div", { class: "rp-purch rp-lib" }, ...kids));
  const crumbs = (...parts) => h("div", { class: "crumb noprint" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }),
    parts.map(p => [" › ", typeof p === "string" ? h("span", {}, p) : h("button", { type: "button", onclick: () => { location.hash = p[1]; } }, p[0])]));
  const tile = (label, big, sub, cls) => h("div", { class: "stile" + (cls ? " " + cls : "") }, h("div", { class: "sl" }, label), h("div", { class: "sb" }, big), sub ? h("div", { class: "ss" }, sub) : null);
  const table = (heads, rows, numeric) => h("div", { class: "gridscroll sup pgt" }, h("table", { class: "grid", style: { width: "100%" } },
    h("thead", {}, h("tr", {}, heads.map((t, i) => h("th", { class: numeric.includes(i) ? "n" : "" }, t)))),
    h("tbody", {}, rows.map(cells => h("tr", {}, cells.map((c, i) => h("td", { class: numeric.includes(i) ? "n" : (c && c.wide ? "w" : "") }, c && c.wide ? c.el : c)))))));
  const wide = el => ({ wide: true, el });
  const needsDb = msg => /kept in the database/.test(msg || "");
  const codeLink = code => h("button", { type: "button", class: "code", onclick: () => { location.hash = "#fab-library/" + encodeURIComponent(code); } }, code);
  const popupOk = () => may("page:groups") || may("page:rightcost");
  const groupCell = g => {
    if (!g) return "";
    if (g.code) {
      const link = may("page:groups") ? h("button", { type: "button", class: "code", onclick: () => { location.hash = "#group/" + encodeURIComponent(g.code); } }, g.code) : h("span", {}, g.code);
      return tipOn(h("span", {}, link, g.how === "construction" ? h("span", { class: "muted" }, " (its construction; not bought under this code)") : null), g.name || "");
    }
    return h("span", { class: "muted" }, g.how === "none yet" ? "No group yet" : "Not grouped: " + String(g.why || "").replace(/^PLM specification /, ""));
  };
  const boughtCell = (code, b) => !b ? h("span", { class: "muted" }, "Not bought") :
    h("span", { class: "fgcell" }, `${n0(b.lines)} ${b.lines === 1 ? "line" : "lines"}, ${n0(b.metres)} m` + (b.last_price !== null ? `; last Rs ${n2(b.last_price)} on ${day(b.last)}` : "")
      + (b.other_lines ? `; ${n0(b.other_lines)} other order ${b.other_lines === 1 ? "line" : "lines"} in no figure` : ""),
      popupOk() && (b.lines || b.other_lines) && window.RP_PURCH ? tipOn(h("button", { type: "button", class: "ib pib", onclick: e => { e.stopPropagation(); RP_PURCH.openHistory(code); }, html: svg("chart") }), "Price over time for " + code) : null);

  // TOO BIG: what a file over the limit is told on the screen at once, before it is sent (as rules/fab_library.py too_big;
  // check_server.py runs this function and compares the two). A .zip is checked by the server as soon as it arrives.
  function tooBig(size, max, name) {
    return size > max ? `${name} is ${(size / 1048576).toFixed(1)} MB: larger than ${Math.floor(max / 1048576)} MB, the most read at once. Send it as a .zip (the full list is about 4 MB zipped), or split it into parts.` : null;
  }
  // END TOO BIG

  // ---------------------------------------------------------------- #fab-library: search, and the uploads
  const lib = { data: null, error: null, q: "", found: null, searching: false, open: null, detail: null, timer: null };
  async function enterLibrary(p) {
    clearTimeout(lib.timer);
    await known(); if (!may("page:fab_library")) return;
    if (p && p.arg) return enterCode(p);
    try { lib.data = await api("/api/fab-library"); lib.error = null; } catch (e) { lib.error = e.message; }
    if (!(state.page && state.page.id === "fab-library" && !state.page.arg)) return;
    const busy = (lib.data && lib.data.uploads || []).some(u => u.status === "queued" || u.status === "working" || (u.status === "done" && !(u.summary || {}).regroup));
    if (lib.open && lib.data) {
      const u = lib.data.uploads.find(x => x.id === lib.open);
      if (u && (!lib.detail || lib.detail.id !== u.id || lib.detail.status !== u.status || busy)) { try { lib.detail = await api("/api/fab-library/uploads/" + u.id); } catch (e) { lib.detail = null; } }
    }
    if (busy) lib.timer = setTimeout(() => { if (state.page && state.page.id === "fab-library" && !state.page.arg) enterLibrary({}); }, 2000);
    else if (lib.wasBusy) { lib.found = null; try { if (lib.q) await find(lib.q, true); } catch (e) { /* the next search says */ } }
    lib.wasBusy = busy;
    render();
  }
  async function find(q, quiet) {
    lib.q = q; lib.searching = true; if (!quiet) render();
    try { lib.found = await api("/api/fab-library/search?q=" + encodeURIComponent(q) + "&limit=50"); lib.found.error = null; }
    catch (e) { lib.found = { error: e.message, results: [] }; }
    lib.searching = false;
    if (!quiet) render();
  }
  const mb = b => b === null || b === undefined ? "" : b < 1048576 ? `${n0(Math.ceil(b / 1024))} KB` : `${(b / 1048576).toFixed(1)} MB`;
  const STATUS_WORDS = { queued: "Waiting to be read", working: "Being read", done: "Read", failed: "Failed" };
  function renderLibrary(main) {
    tip.hidden = true;
    $("#selbar").hidden = true;
    if (state.page.arg) return renderCode(main);
    const top = crumbs("Fab library"), title = h("div", { class: "headrow" }, h("h1", { class: "ptitle" }, "Fab library"));
    if (lib.error) return fillP(main, top, title, h("p", { class: needsDb(lib.error) ? "note" : "err" }, lib.error));
    if (!lib.data) return fillP(main, top, title, h("div", { class: "empty" }, "Loading…"));
    const d = lib.data;
    if (!d.available) return fillP(main, top, title, h("p", { class: "note" }, d.why));
    const latest = d.uploads.find(u => u.id === d.latest);
    const search = h("input", { type: "search", class: "search", placeholder: "A code, or words of its construction (twill 40s, 136 x 90)", value: lib.q, "aria-label": "Search the Fab library" });
    search.addEventListener("keydown", e => { if (e.key === "Enter") find(search.value.trim()); });
    const f = lib.found;
    const results = !f ? null : f.error ? h("p", { class: "err" }, f.error) : !f.results.length ? h("div", { class: "empty" }, lib.q ? `No code of the library matches “${lib.q}”.` : "Type a code or words of a construction.")
      : [h("div", { class: "libfound" }, table(["Fabric code", "Construction", "Product", "Fab group", "Purchases"], f.results.map(r => [codeLink(r.code), wide(h("span", {}, r.construction || h("span", { class: "muted" }, "blank in the PLM"))), wide(h("span", { class: "muted" }, r.product)), wide(groupCell(r.group)), wide(boughtCell(r.code, r.bought))]), [])),
        f.more ? h("p", { class: "muted" }, `The first ${f.limit} are shown: more codes match. Add a word to narrow it.`) : null];
    fillP(main, top, title,
      h("p", { class: "muted" }, "The PLM fabric code list: every code with its construction, its Fab group and its purchases. Once a list is uploaded, the purchase history takes each code's PLM specification from here (in place of the file deployed with the code), and a code whose specification a later list corrects is moved to its Fab group and costed again at once."),
      h("div", { class: "stiles" }, tile("Codes in the library", n0(d.codes), latest ? `from ${latest.filename}` : "no list uploaded yet"),
        tile("Latest list", latest ? `#${latest.id}` : "None", latest ? `${day(latest.uploaded_at)}${latest.uploaded_by ? " by " + latest.uploaded_by : ""}` : ""),
        tile("Specifications come from", d.latest ? "The Fab library" : "The deployed file", d.source)),
      h("section", { class: "sec" }, h("h2", {}, "Find a code"),
        h("div", { class: "toolbar" }, search, h("button", { type: "button", class: "btn line", onclick: () => find(search.value.trim()) }, lib.searching ? "Searching…" : "Search"),
          f && f.results && f.results.length ? h("span", { class: "count" }, `${f.results.length}${f.more ? "+" : ""} ${f.results.length === 1 ? "code" : "codes"}`) : null),
        results),
      may("do:upload_fab_library") ? uploadBox(d) : h("p", { class: "note" }, `Your role${typeof RPA !== "undefined" && RPA.me && RPA.me.role ? " (" + RPA.me.role + ")" : ""} may look at the library but not upload a list: that is an admin action.`),
      h("section", { class: "sec" }, h("h2", {}, "Uploads"),
        d.uploads.length ? h("div", { class: "gridscroll sup pgt libups" }, h("table", { class: "grid", style: { width: "100%" } }, h("thead", {}, h("tr", {}, ["Upload", "File", "Where it stands", "What was read"].map(t => h("th", {}, t)))), h("tbody", {}, d.uploads.map(uploadRow))))
          : h("p", { class: "muted" }, "No list uploaded yet."),
        lib.open && lib.detail && lib.detail.id === lib.open ? uploadDetail(lib.detail) : null));
  }
  function uploadBox(d) {
    // one file box for as long as the page is open: the page is drawn again when a file is chosen, and a new box would lose it
    const fresh = !lib.input;
    const input = lib.input || (lib.input = h("input", { type: "file", accept: ".csv,.zip,.xlsx", "aria-label": "PLM fabric code list" }));
    const big = () => input.files.length ? tooBig(input.files[0].size, d.max_bytes, input.files[0].name) : null;
    if (fresh) input.addEventListener("change", () => { lib.uploadError = big(); render(); });
    const send = async () => {
      if (!input.files.length) return toast("Choose the PLM fabric code list first", false);
      lib.uploadError = big();
      if (lib.uploadError) return render();
      const fd = new FormData(); fd.append("file", input.files[0]);
      try { const r = await api("/api/fab-library/upload", { method: "POST", body: fd }); lib.open = r.id; lib.detail = null; input.value = ""; toast("Uploaded: it is read in the background"); enterLibrary({}); }
      catch (e) { lib.uploadError = e.message; render(); }
    };
    return h("section", { class: "sec" }, h("h2", {}, "Upload the PLM fabric code list"), h("div", { class: "uprow" }, input, h("button", { type: "button", class: "btn fill", onclick: send }, "Upload")),
      lib.uploadError ? h("p", { class: "err", role: "alert" }, lib.uploadError) : h("p", { class: "muted" }, `A .csv with the 26 columns plm_extract.py keeps (article_code to article_cust_weftcount), a .zip holding that one .csv, or an .xlsx with the same columns. Up to ${Math.floor(d.max_bytes / 1048576)} MB for the list itself (a .zip's list counts unzipped). Codes with a blank EPI, PPI, width or count are kept with the blanks.`));
  }
  const kept = u => [u.rows_total !== null ? `${n0(u.rows_total)} ${u.rows_total === 1 ? "row" : "rows"}` : null, u.codes_total !== null ? `${n0(u.codes_total)} ${u.codes_total === 1 ? "code" : "codes"}` : null,
    u.codes_new !== null ? `${n0(u.codes_new)} new, ${n0(u.codes_changed || 0)} corrected, ${n0(u.codes_same || 0)} the same` : null,
    u.codes_older ? `${n0(u.codes_older)} not used: a later list has them` : null, u.codes_kept ? `${n0(u.codes_kept)} from earlier lists not in this one, kept as they were` : null,
    u.rows_repeated ? `${n0(u.rows_repeated)} rows repeat a code (the first is used)` : null, u.rows_no_code ? `${n0(u.rows_no_code)} rows without a code, left out` : null].filter(Boolean).join(" · ");
  function uploadRow(u) {
    const rg = (u.summary || {}).regroup;
    return h("tr", { class: lib.open === u.id ? "picked" : null },
      h("td", {}, h("button", { type: "button", class: "code", onclick: async () => { lib.open = lib.open === u.id ? null : u.id; lib.detail = null; if (lib.open) { try { lib.detail = await api("/api/fab-library/uploads/" + u.id); } catch (e) { toast(e.message, false); } } render(); } }, `#${u.id}`)),
      h("td", { class: "w" }, u.filename, h("div", { class: "muted" }, `${day(u.uploaded_at)}${u.uploaded_by ? " by " + u.uploaded_by : ""} · ${mb(u.file_bytes)}` + (u.content_bytes && u.content_bytes !== u.file_bytes ? ` (${mb(u.content_bytes)} unzipped)` : ""))),
      h("td", { class: "w" }, h("span", { class: "upst " + u.status }, STATUS_WORDS[u.status] || u.status), u.step ? h("div", { class: "muted" }, u.step) : null, u.error ? h("div", { class: "err" }, u.error) : null),
      h("td", { class: "w" }, kept(u), rg ? h("div", { class: "muted" }, regroupWords(rg)) : null));
  }
  const regroupWords = rg => !rg.fabrics ? "No purchase history yet to group again." :
    `Purchase history grouped again on it: ${n0(rg.fabrics)} fabric codes (${n0(rg.with_spec)} with a specification in the library); ${n0(rg.grouped_now)} put in a Fab group, ${n0(rg.moved)} moved, ${n0(rg.respecified)} with a corrected specification, ${n0(rg.groups_new)} new groups; ${n0(rg.costed_again)} costed again.`;
  function uploadDetail(u) {
    const s = u.summary || {}, rg = s.regroup;
    return h("div", { class: "updetail" }, h("h3", {}, `Upload #${u.id}: ${u.filename}`),
      u.status === "done" ? h("p", {}, `${n0(u.codes_total)} codes in ${n0(u.rows_total)} rows: ${n0(u.codes_new)} new to the library, ${n0(u.codes_changed)} with a specification corrected (this list's is used now), ${n0(u.codes_same)} the same` +
        (u.codes_older ? `, ${n0(u.codes_older)} not used because a later list has them` : "") + `. ${n0(u.codes_kept || 0)} codes of earlier lists are not in this one: they keep the specification they had.`) : null,
      u.status === "done" ? h("p", { class: "muted" }, `Kept with blanks, as the PLM has them: ${n0(u.no_epi_ppi)} codes without EPI or PPI, ${n0(u.no_width)} without a finished width, ${n0(u.no_counts)} without a warp or weft count. Such a code is not put in a Fab group (nothing is guessed).`) : null,
      rg ? h("p", {}, regroupWords(rg)) : u.status === "done" ? h("p", { class: "note" }, "The purchase history is being grouped and costed again on this list…") : null,
      (s.columns_ignored || []).length ? h("p", { class: "muted" }, `Columns not read: ${s.columns_ignored.join(", ")}.`) : null,
      s.seconds ? h("p", { class: "muted" }, `Read and written in ${n0(s.seconds.read_and_write)} s; the purchase history grouped and costed again in ${n0(s.seconds.regroup_and_cost)} s.`) : null,
      (u.changes || []).length ? [h("h3", {}, "Specifications this list corrected"), table(["Fabric code", "What changed"], u.changes.map(x => [codeLink(x.code), wide(h("span", {}, x.what))]), []),
        u.changes.length < (u.codes_changed || 0) ? h("p", { class: "muted" }, `The first ${u.changes.length} are shown.`) : null] : null);
  }

  // ---------------------------------------------------------------- #fab-library/<code>: one code
  const one = { code: null, data: null, error: null };
  async function enterCode(p) {
    const code = p.arg;
    if (one.code === code && one.data) return;
    Object.assign(one, { code, data: null, error: null });
    try { one.data = await api("/api/fab-library/code/" + encodeURIComponent(code)); } catch (e) { one.error = e.message; }
    if (state.page && state.page.id === "fab-library" && state.page.arg === code) render();
  }
  function renderCode(main) {
    const top = crumbs(["Fab library", "#fab-library"], one.code || state.page.arg);
    if (one.error) return fillP(main, top, h("div", { class: "empty" }, one.error));
    const d = one.data;
    if (!d || d.code.toLowerCase() !== String(state.page.arg).toLowerCase()) return fillP(main, top, h("div", { class: "empty" }, "Loading…"));
    document.title = d.code + " - RightPrice";
    const g = d.group, b = d.bought, up = x => x ? `upload #${x.id} (${x.filename}), ${day(x.at)}${x.by ? " by " + x.by : ""}` : "";
    fillP(main, top,
      h("div", { class: "dhead" }, h("div", {}, h("div", { class: "small" }, "Fab library · PLM fabric code" + (d.product ? " · " + d.product : "")), h("h1", {}, d.code), h("div", { class: "gname" }, d.construction || "Its construction is blank in the PLM")),
        h("div", { class: "dicons noprint" }, ib("pdf", "Print this page", () => print()))),
      h("div", { class: "stiles" },
        tile("Fab group", g.code || (g.how === "none yet" ? "None yet" : "Not grouped"), g.code ? (g.how === "construction" ? "its construction is this group's; not bought under this code" : g.name) : g.why, g.code ? "" : "amber"),
        tile("Purchases", b ? `${n0(b.lines)} ${b.lines === 1 ? "line" : "lines"}` : "Not bought", b ? `${n0(b.metres)} m on ${n0(b.orders)} ${b.orders === 1 ? "order" : "orders"}` + (b.last ? `; last Rs ${n2(b.last_price)} on ${day(b.last)}` : "")
          + (b.other_lines ? `; ${n0(b.other_lines)} other order ${b.other_lines === 1 ? "line" : "lines"} (sample, yardage, deleted ...) in no figure` : "") : "no purchase of this code is in the purchase history"),
        tile("Specification from", d.spec_from ? `Upload #${d.spec_from.id}` : "", d.spec_from ? `${day(d.spec_from.at)}${d.spec_from.by ? " by " + d.spec_from.by : ""}` : ""),
        tile("In the latest list", d.in_latest ? "Yes" : "No", d.in_latest ? `upload #${d.latest}` : `last in ${up(d.last_in)}; it keeps that specification`, d.in_latest ? "" : "amber")),
      h("div", { class: "acts noprint" }, b && (b.lines || b.other_lines) && popupOk() && window.RP_PURCH ? h("button", { type: "button", class: "btn line", onclick: () => RP_PURCH.openHistory(d.code) }, "Price over time") : null,
        g.code && may("page:groups") ? h("button", { type: "button", class: "btn fill", onclick: () => { location.hash = "#group/" + encodeURIComponent(g.code); } }, `Open Fab group ${g.code}`) : null),
      h("section", { class: "sec" }, h("h2", {}, "Its PLM specification"),
        h("dl", { class: "kv gfields" }, d.values.map(v => [h("dt", {}, v.label), h("dd", {}, String(v.value).trim() ? v.value : h("span", { class: "muted" }, "blank"))])),
        h("p", { class: "muted" }, `As the PLM fabric code list gives it (${up(d.spec_from)}); first in ${up(d.first_in)}. A blank stays blank: a code without EPI, PPI, width or counts is not put in a Fab group.`)),
      d.changes.length ? h("section", { class: "sec" }, h("h2", {}, "Corrected by later lists"), h("ul", { class: "mon" }, d.changes.map(x => h("li", {}, `Upload #${x.upload} (${x.filename}) on ${day(x.at)}${x.by ? " by " + x.by : ""}: ${x.what}.`)))) : null,
      d.same_construction.codes > 1 ? h("section", { class: "sec" }, h("h2", {}, "The same construction in the library"),
        h("p", {}, `${n0(d.same_construction.codes)} codes of the library have the same eight fields (any width): `, d.same_construction.first.filter(c => c !== d.code).slice(0, 12).flatMap((c, i) => [i ? ", " : "", codeLink(c)]), d.same_construction.codes > 13 ? " …" : "", ".")) : null);
  }

  // ---------------------------------------------------------------- what the shell sees
  window.RP_PAGES = Object.assign(window.RP_PAGES || {}, {
    "fab-library": { enter: enterLibrary, render: renderLibrary, title: p => p.arg || "Fab library", rail: null },
  });
})();
