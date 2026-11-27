/* Users and roles (stage 3 of the rebuild): who may use RightPrice, and what each role may do.
   /api/me says what this person may do, and the shell hides what they may not use. The server is what enforces it: it
   refuses every request the person's role does not allow, whatever the page shows.
   The admin page (#users, reached from the user icon's menu) adds people, changes their role, switches them off, and
   changes what each role may do; every change is kept in the record at the foot of the page.
   Loaded before rightcost.js; it uses that file's helpers (h, fill, toast, svg, state, render) only when called. */
"use strict";

const RPA = { me: null, view: null, error: null, pending: {}, msg: "" };
const can = perm => !RPA.me || (RPA.me.allowed || []).includes(perm);
// which permission each page of the shell, and each costing screen of the "New cost" popup, needs
const PAGE_NEEDS = { dashboard: "page:dashboard", pilot: "page:pilot", yarn: "page:prices", cotton: "page:prices", rates: "page:prices", ratecard: "page:prices",
  settings: "page:prices", costsheets: "page:costsheets", intake: "do:edit_rates", rightcost: "page:rightcost", item: "page:rightcost", supplier: "page:rightcost", users: "page:users" };
const TAB_NEEDS = { cost: "page:cost", compare: "page:cost", bulk: "page:list", pack: "page:pack" };
const ACTION_TABS = { "Create cost": "cost", "Compare": "compare", "Bulk upload": "bulk", "Negotiation pack": "pack" };

async function loadMe() {
  try {
    const r = await fetch("/api/me");
    if (!r.ok) return;
    RPA.me = await r.json();
    // the menus offer only what this person may use: the Prices links, the popup's screens, the list's ⋮ actions
    const linkOk = href => !href.startsWith("#") || href.startsWith("#lib/") || can(PAGE_NEEDS[href.slice(1)] || "");
    const fly = CONFIG.flyouts.prices;
    fly.groups = fly.groups.map(([g, links]) => [g, links.filter(([, href]) => linkOk(href))]).filter(([, links]) => links.length);
    CONFIG.popupTabs = CONFIG.popupTabs.filter(([id]) => can(TAB_NEEDS[id]));
    const mod = CONFIG.modules.costs;
    mod.moreActions = mod.moreActions.filter(a => !ACTION_TABS[a] || can(TAB_NEEDS[ACTION_TABS[a]]));
    render();
  } catch (e) { /* the server still refuses what this person may not do */ }
}
function pageNeed() {
  const id = state.users ? "users" : state.frame ? state.frame.split("/")[0] : state.library ? null : state.supplier ? "supplier" : state.detail ? "item" : "rightcost";
  return id ? PAGE_NEEDS[id] : null;
}
function pageOk() { const need = pageNeed(); return !need || can(need); }
function noPage(main) {
  $("#selbar").hidden = true;
  fill(main, h("div", { class: "crumb" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') })),
    h("div", { class: "empty ua-nopage" }, h("b", {}, "This page is not open to your role"), h("p", {},
      `Your role (${(RPA.me && RPA.me.role) || "none"}) may not use it. Ask an admin if you need to.`)));
}
function profileExtras() {
  // under the user icon: the role, and the admin page for those who may see it
  const me = RPA.me; if (!me) return [];
  return [me.permissions_on && me.role ? h("div", { class: "note" }, "Role: " + me.role + (me.from_setting ? " (from the app setting)" : "")) : null,
    can("page:users") ? h("button", { type: "button", class: "lnk", onclick: () => go("#users") }, "Users and roles") : null];
}

// ------------------------------------------------------------------ the admin page
const uaWhen = iso => { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); };
async function uaPost(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || r.statusText);
  return d;
}
async function loadUsers() {
  try {
    const r = await fetch("/api/users"), d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || r.statusText);
    RPA.view = d; RPA.error = null;
  } catch (e) { RPA.view = null; RPA.error = e.message; }
  if (state.users) render();
}
async function uaChange(path, body, done) {
  try { await uaPost(path, body); RPA.msg = ""; toast(done); }
  catch (e) { RPA.msg = e.message; toast(e.message, false); }
  await loadUsers();
}
function auditWords(a) {
  const d = a.detail || {};
  if (a.action === "person added") return `Added ${a.subject} as ${d.role}${d.name ? ` (${d.name})` : ""}`;
  if (a.action === "role changed") return `${a.subject}: role ${d.from} → ${d.to}`;
  if (a.action === "name changed") return `${a.subject}: name “${d.from}” → “${d.to}”`;
  if (a.action === "switched off") return `${a.subject}: switched off`;
  if (a.action === "switched on") return `${a.subject}: switched on again`;
  if (a.action === "permission given") return `${a.subject}: may now ${d.verb || d.label}${d.default ? " (back to the default)" : " (differs from the default)"}`;
  if (a.action === "permission taken away") return `${a.subject}: may no longer ${d.verb || d.label}${d.default ? " (differs from the default)" : " (back to the default)"}`;
  return `${a.action}: ${a.subject}`;
}
function renderUsers(main) {
  $("#selbar").hidden = true;
  const v = RPA.view, crumbs = h("div", { class: "crumb" }, h("a", { href: "#dashboard", html: svg("home", 'width="12" height="12"') }), " › ", "Settings and account", " › ", h("span", {}, "Users and roles"));
  const head = h("div", { class: "headrow" }, h("h1", { class: "title", style: "cursor:default" }, "Users and roles"));
  if (!v) return fill(main, crumbs, head, h("div", { class: "empty" }, RPA.error || "Loading…"));
  const editable = v.permissions_on, me = (RPA.me && RPA.me.email) || "";
  const status = h("div", { class: "ua-card" + (editable ? "" : " warn") },
    editable ? [h("p", {}, h("b", {}, "Permissions are on. "), "Nobody can use RightPrice until they are added here. The server checks every request against the person's role, whatever the screens show."),
      h("p", {}, "Always Admin, from the app setting RIGHTPRICE_ADMINS: ", h("b", {}, v.setting_admins.join(", ") || "(no address)"), ". Add yourself below as Admin too, so you stay an admin if that setting is changed."),
      v.setting_ignored.length ? h("p", { class: "ua-bad" }, `Not read as an e-mail address in that setting, so ignored: ${v.setting_ignored.join(", ")}`) : null]
      : [h("p", {}, h("b", {}, "Permissions are off: "), v.why_off.replace(/^Permissions are off: /, "")), h("p", {}, "Until then RightPrice cannot tell an admin from anyone else, so nothing can be changed on this page: what is shown is how it will start. The steps are in docs/AZURE_DEPLOY.md, “Users and roles”.")],
    h("p", { class: "muted" }, v.marks_note));
  // add a person
  const email = h("input", { type: "email", placeholder: "name@company.com", "aria-label": "E-mail address", autocomplete: "off", disabled: !editable || null });
  const name = h("input", { type: "text", placeholder: "Name", "aria-label": "Name", maxlength: "120", disabled: !editable || null });
  const role = h("select", { "aria-label": "Role", disabled: !editable || null }, v.roles.map(r => h("option", {}, r))); role.value = "Buyer";
  const add = h("button", { type: "button", class: "btn fill", disabled: !editable || null, onclick: () => { if (!email.value.trim()) { email.focus(); return; } uaChange("/api/users/add", { email: email.value, name: name.value, role: role.value }, "Added"); } }, "Add");
  [email, name].forEach(el => el.addEventListener("keydown", e => { if (e.key === "Enter") add.click(); }));
  const addBox = h("div", { class: "ua-card" }, h("h2", {}, "Add a person"), h("p", { class: "muted" }, "The address they sign in to Microsoft with. They must also be able to sign in to the site (see docs/AZURE_DEPLOY.md)."),
    h("div", { class: "ua-form" }, email, name, role, add), RPA.msg ? h("p", { class: "ua-bad", role: "alert" }, RPA.msg) : null);
  // the people
  const lastAdmin = v.admins_in_list.length === 1 ? v.admins_in_list[0] : null;
  const swipe = h("p", { class: "ua-swipe" }, "Swipe the table sideways for the rest.");
  const people = h("div", { class: "ua-card" }, h("h2", {}, `People (${v.people.length})`), v.people.length ? swipe.cloneNode(true) : null,
    v.people.length ? h("div", { class: "ua-scroll" }, h("table", { class: "ua-table" }, h("thead", {}, h("tr", {}, ["E-mail", "Name", "Role", "Access", "Added", "Last change"].map(t => h("th", {}, t)))),
      h("tbody", {}, v.people.map(p => {
        const sel = h("select", { "aria-label": "Role of " + p.email, disabled: !editable || null }, v.roles.map(r => h("option", {}, r))); sel.value = p.role;
        sel.addEventListener("change", () => uaChange("/api/users/change", { email: p.email, role: sel.value }, `${p.email} is now ${sel.value}`));
        const nm = h("input", { type: "text", value: p.name, maxlength: "120", "aria-label": "Name of " + p.email, disabled: !editable || null });
        nm.addEventListener("change", () => uaChange("/api/users/change", { email: p.email, name: nm.value }, "Name saved"));
        const sw = h("button", { type: "button", class: "btn line ua-sm", disabled: !editable || (p.active && p.email === lastAdmin) || null, title: p.active && p.email === lastAdmin ? "The last admin in the list stays on" : null, onclick: ev => {
          const b = ev.currentTarget; if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Sure?"; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = p.active ? "Switch off" : "Switch on"; } }, 4000); return; }
          uaChange("/api/users/change", { email: p.email, active: !p.active }, `${p.email} switched ${p.active ? "off" : "on"}`); } }, p.active ? "Switch off" : "Switch on");
        return h("tr", { class: p.active ? null : "off" }, h("td", {}, p.email, p.email === me ? h("span", { class: "muted" }, " (you)") : null), h("td", {}, nm),
          h("td", {}, sel, v.setting_admins.includes(p.email) && p.role !== "Admin" ? h("div", { class: "muted" }, "Admin while in the app setting") : null),
          h("td", {}, h("span", { class: "ua-state" }, p.active ? "On" : "Switched off"), " ", sw), h("td", { class: "muted" }, uaWhen(p.added_at), p.added_by ? h("div", {}, "by " + p.added_by) : null),
          h("td", { class: "muted" }, p.changed_at ? [uaWhen(p.changed_at), h("div", {}, "by " + p.changed_by)] : ""));
      })))) : h("p", { class: "muted" }, "Nobody is in the list yet."));
  // what each role may do
  const roles = [...v.roles, v.assistant.name], pend = RPA.pending, nPend = Object.keys(pend).length;
  const cell = (role, p) => {
    if (role === v.assistant.name) return h("td", { class: "c" }, h("span", { class: "ua-tick", "aria-label": v.assistant.allowed.includes(p.key) ? "yes" : "no" }, v.assistant.allowed.includes(p.key) ? "✓" : "–"));
    const g = v.grid[role][p.key], k = role + "|" + p.key, on = k in pend ? pend[k] : g.allowed;
    const fixed = role === "Admin" || p.fixed;
    const box = h("input", { type: "checkbox", class: "cb", "aria-label": `${role}: ${p.label}`, disabled: fixed || !editable || null }); box.checked = on;
    box.addEventListener("change", () => { if (box.checked === g.allowed) delete pend[k]; else pend[k] = box.checked; render(); });
    return h("td", { class: "c" + (on !== g.default ? " differs" : "") + (k in pend ? " pending" : ""), title: on !== g.default ? "Differs from the default" : null }, box);
  };
  const groups = ["Pages", "Actions"].map(gname => [h("tr", { class: "grp" }, h("td", { colspan: String(roles.length + 1) }, gname === "Pages" ? "Pages (to see)" : "Actions (to change)")),
    v.permissions.filter(p => p.group === gname).map(p => h("tr", {}, h("td", { class: "lbl" }, p.label, p.fixed ? h("span", { class: "muted" }, " (Admin only)") : null), roles.map(r => cell(r, p))))]);
  const grid = h("div", { class: "ua-card" }, h("h2", {}, "What each role may do"),
    h("p", { class: "muted" }, "Admin always has everything. A shaded box differs from the role's default. ", v.assistant.name, ": ", v.assistant.note),
    swipe.cloneNode(true), h("div", { class: "ua-scroll" }, h("table", { class: "ua-table ua-grid" }, h("thead", {}, h("tr", {}, h("th", {}, ""), roles.map(r => h("th", { class: "c" }, r)))), h("tbody", {}, groups))),
    h("div", { class: "ua-acts" }, h("button", { type: "button", class: "btn fill", disabled: !nPend || !editable || null, onclick: async () => {
      const changes = Object.entries(pend).map(([k, allowed]) => { const [role, permission] = k.split("|"); return { role, permission, allowed }; });
      RPA.pending = {}; await uaChange("/api/users/permissions", { changes }, `${changes.length} ${changes.length === 1 ? "change" : "changes"} saved`); } }, nPend ? `Save ${nPend} ${nPend === 1 ? "change" : "changes"}` : "Save changes"),
      h("button", { type: "button", class: "btn", disabled: !nPend || null, onclick: () => { RPA.pending = {}; render(); } }, "Discard")));
  // the record of changes
  const log = h("div", { class: "ua-card" }, h("h2", {}, "Record of changes"), v.audit.length ? h("div", { class: "ua-scroll" }, h("table", { class: "ua-table" }, h("thead", {}, h("tr", {}, ["When", "Who", "What"].map(t => h("th", {}, t)))),
    h("tbody", {}, v.audit.map(a => h("tr", {}, h("td", { class: "muted nowrap" }, uaWhen(a.at)), h("td", {}, a.who), h("td", {}, auditWords(a))))))) : h("p", { class: "muted" }, "No changes yet."));
  fill(main, crumbs, head, status, addBox, people, grid, log);
}
addEventListener("DOMContentLoaded", loadMe);      // after rightcost.js has run: its menus and render() exist then
