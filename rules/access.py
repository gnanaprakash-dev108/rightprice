"""Who may use RightPrice, and what each person may do (stage 3 of the rebuild; GP's decisions of 27 Nov 2026).

Switched on by the app setting RIGHTPRICE_ADMINS: the sign-in addresses of the first admins, separated by commas. Without
it the app behaves as before: everyone signed in may use everything, and /api/me says permissions are off.

With it:
- a person is let in only once an admin has added them (Users and roles, under the user icon), with one of four roles.
  The admins named in the setting are always let in as Admin, whether or not they are in the list;
- every address the server answers needs one permission (ROUTES below: page:<name> to see, do:<action> to change),
  checked in one place (server.py, AccessGate) before the request reaches its route. An address with no permission
  assigned is refused to everyone, and check_server.py fails while one exists, so a later stage cannot forget one;
- a request with no sign-in is refused, never treated as an admin; a person not added is told so (403);
- on the files store (no DATABASE_URL) there is nowhere to keep the list of people: only the admins named in the setting
  get in, and everyone else is told why.

The person comes from Azure App Service's sign-in headers (X-MS-CLIENT-PRINCIPAL-NAME and X-MS-CLIENT-PRINCIPAL), which
requests from outside cannot set: Microsoft, "Work with user identities in AuthN/AuthZ" (read 27 Nov 2026). People are
known by their e-mail address, lower case. Off Azure anyone can send those headers: switch permissions on only where the
app is reached through App Service's sign-in (on a laptop, leave RIGHTPRICE_ADMINS unset).

The MCP token (RIGHTPRICE_MCP_TOKEN, server.py McpGate) is its own fixed role, "AI assistant": what its tools do today
(ASSISTANT_TOOLS), not changed on the admin page.

Each person's own marks (Status and Remarks in Right cost, saved searches, Library lists) stay in their browser in this
stage; moving them to the server is a separate choice for GP.
"""
import base64
import json
import os
import re

import data_users
import store
from rules.common import Refused

ADMINS_ENV = "RIGHTPRICE_ADMINS"
ADMIN, RATES, BUYER, VIEWER = "Admin", "Rates editor", "Buyer", "Viewer"
ROLES = [ADMIN, RATES, BUYER, VIEWER]
ASSISTANT = "AI assistant"

PUBLIC = "open to anyone"                   # the shell's files, and /api/me (which says who you are and what you may do)
MEMBER = "anyone let in"                    # the home page, the lists for the drop-downs, where the data is kept

# every permission, in the order the admin page shows them: (key, what it is, what a refusal says the role may not do)
PERMISSIONS = [
    ("page:dashboard", "Home: Dashboard", "see the Dashboard"),
    ("page:pilot", "Home: Pilot results", "see the pilot results"),
    ("page:rightcost", "Right cost: the list, each fabric's page, supplier pages, the tracker's steps and quote alerts (to look at)", "see Right cost"),
    ("page:cost", "Create cost and Compare (cost a fabric; download its cost sheet)", "cost a fabric"),
    ("page:list", "Bulk upload: the fabric list (to look at), costing a filled template, downloads", "see the fabric list"),
    ("page:pack", "Negotiation pack", "make a negotiation pack"),
    ("page:prices", "Prices: yarn and cotton prices, rate tables, mill rate card, calculation settings (to look at)", "see the rate tables and prices"),
    ("page:costsheets", "Prices: mill cost sheets (to look at)", "see the mill cost sheets"),
    ("page:users", "Users and roles (this page)", "see who may use RightPrice"),
    ("do:edit_rates", "Edit rates: rate tables, yarn and cotton prices, Bring in prices, and the earlier screens (classic)", "edit rates"),
    ("do:apply_drafts", "Apply mill cost sheet drafts to the rate master", "apply mill cost sheet drafts"),
    ("do:upload", "Upload and change: mill sheets, Add to list, update or remove list rows, mill cost sheets", "upload or change the fabric list and mill cost sheets"),
    ("do:record_steps", "Record and remove negotiation steps in the tracker", "record or remove negotiation steps"),
    ("do:mark_seen", "Mark quote alerts seen for everyone, or bring them back", "mark quote alerts seen"),
    ("do:draft", "Draft messages to mills (e-mail and WhatsApp; nothing is sent)", "draft messages to mills"),
    ("do:manage_users", "Add people, change their role, switch them off, change what each role may do", "change who may use RightPrice"),
]
LABEL = {k: label for k, label, _ in PERMISSIONS}
VERB = {k: verb for k, _, verb in PERMISSIONS}
ALL = [k for k, _, _ in PERMISSIONS]
FIXED = {"page:users", "do:manage_users"}           # Admin's alone; not given to another role on the admin page
_PAGES = {k for k in ALL if k.startswith("page:")} - FIXED
DEFAULTS = {                                         # GP, 27 Nov 2026
    ADMIN: set(ALL),                                 # everything, users included (always: not changed on the page)
    RATES: set(ALL) - FIXED,                         # may edit rates and apply mill cost sheet drafts; no user admin
    BUYER: _PAGES | {"do:upload", "do:record_steps", "do:mark_seen", "do:draft"},   # every page, uploads, steps, drafts
    VIEWER: set(_PAGES),                             # read only
}

# every address the server answers, and the one permission it needs. "METHOD /path" as the route is written in
# server.py ("* /path" for every method, "WS /path" for a web socket, "MOUNT /" for the static files). A later stage
# adds its addresses here; check_server.py fails while any address of the app is missing.
ROUTES = {
    "MOUNT /": PUBLIC,                       # the shell's scripts, styles and icons: no data in them
    "GET /rightcost": PUBLIC,                # a redirect to /#rightcost
    "GET /api/me": PUBLIC,
    "GET /": MEMBER,                         # the shell (and /?embed=1, the earlier screens); not let in: the refusal page
    "GET /openapi.json": MEMBER,
    "GET /api/store": MEMBER,
    "GET /api/meta": MEMBER,                 # the drop-down lists every screen loads first
    "GET /api/dashboard": "page:dashboard",
    "GET /api/insights": "page:dashboard",
    "GET /api/negotiations/summary": "page:dashboard",
    "GET /api/pilot": "page:pilot",
    "GET /api/costs": "page:rightcost",
    "POST /api/costs/download": "page:rightcost",
    "GET /api/negotiations": "page:rightcost",
    "GET /api/suppliers": "page:rightcost",
    "GET /api/supplier": "page:rightcost",
    "GET /api/alerts": "page:rightcost",
    "POST /api/cost": "page:cost",
    "POST /api/cost-sheet": "page:cost",
    "POST /api/list": "page:list",
    "POST /api/list/download": "page:list",
    "GET /api/template": "page:list",
    "POST /api/bulk": "page:list",           # costs a filled template and gives the results back; keeps nothing
    "POST /api/bulk-download": "page:list",
    "POST /api/pack": "page:pack",
    "GET /api/table/{sheet}": "page:prices",
    "GET /api/cotton": "page:prices",
    "GET /api/costsheet": "page:costsheets",
    "GET /api/costsheet/template": "page:costsheets",
    "GET /api/users": "page:users",
    "PUT /api/table/{sheet}": "do:edit_rates",
    "POST /api/cotton": "do:edit_rates",
    "POST /api/intake/file": "do:edit_rates",        # Bring in prices: each step leads to an addition to the rate master
    "POST /api/intake/link": "do:edit_rates",
    "POST /api/intake/api": "do:edit_rates",
    "POST /api/intake/map": "do:edit_rates",
    "POST /api/intake/add": "do:edit_rates",
    "GET /classic": "do:edit_rates",                 # the earlier Streamlit screens can change rates
    "* /classic/{path:path}": "do:edit_rates",
    "WS /classic/{path:path}": "do:edit_rates",
    "POST /api/costsheet/apply": "do:apply_drafts",
    "POST /api/save": "do:upload",
    "POST /api/list/add": "do:upload",
    "POST /api/list/upload": "do:upload",
    "POST /api/list/remove": "do:upload",
    "DELETE /api/saved/{saved_id}": "do:upload",
    "POST /api/costsheet/upload": "do:upload",
    "POST /api/costsheet/remove": "do:upload",
    "POST /api/negotiations/event": "do:record_steps",
    "POST /api/negotiations/remove": "do:record_steps",
    "POST /api/alerts/seen": "do:mark_seen",
    "POST /api/draft": "do:draft",
    "POST /api/users/add": "do:manage_users",
    "POST /api/users/change": "do:manage_users",
    "POST /api/users/permissions": "do:manage_users",
}

# the AI assistant (the MCP token): each of its tools and the permission it amounts to. Fixed: what the tools do today.
ASSISTANT_TOOLS = {
    "list_choices": "page:cost", "cost_fabric": "page:cost",
    "find_fabrics": "page:rightcost", "fabric_brief": "page:rightcost", "supplier_summary": "page:rightcost",
    "tracker_steps": "page:rightcost", "quote_alerts": "page:rightcost",
    "negotiation_pack": "page:pack",
    "record_tracker_step": "do:record_steps", "remove_my_tracker_step": "do:record_steps",
}
ASSISTANT_NOTE = ("The MCP token: one fixed role, what its tools do today. It records negotiation steps as \"AI assistant\" "
                  "and removes only steps it recorded itself; it cannot change rates, upload, remove rows, mark alerts seen, "
                  "draft messages or change users. It is switched on by the app setting RIGHTPRICE_MCP_TOKEN, not here.")
MARKS_NOTE = ("Each person's own marks (Status and Remarks in Right cost, saved searches, Library lists) are still kept in "
              "their own browser, as before; they are not shared and not part of these permissions.")
OFF_WORDS = ("Permissions are off: everyone signed in may use everything. They are switched on by the app setting "
             f"{ADMINS_ENV} (the first admins' sign-in addresses).")
FILES_WORDS = (f"Permissions are on (the app setting {ADMINS_ENV}), but RightPrice is keeping its data in files, which cannot "
               "hold the list of people. Until the app setting DATABASE_URL is added, only the admins named in "
               f"{ADMINS_ENV} can use it. Ask an admin.")
EMAIL = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")
EMAIL_CLAIMS = ("preferred_username", "email", "emails", "upn",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn")


# ------------------------------------------------------------------ the setting, and who is asking
def _address(text):
    """An e-mail address as people are keyed (lower case), from what the sign-in gives; None if it is not one.
    A personal Microsoft account can arrive as 'live.com#name@example.com': the address is the part after the '#'."""
    s = str(text or "").strip().lower()[:254]
    if "#" in s and "#ext#" not in s:
        s = s.rsplit("#", 1)[1]
    return s if EMAIL.fullmatch(s) else None


def admins_setting():
    """None when the setting is not there (permissions off); else (the admins' addresses, entries that are not one)."""
    raw = os.environ.get(ADMINS_ENV)
    if raw is None or not raw.strip():
        return None
    parts = [p for p in re.split(r"[,;\s]+", raw.strip()) if p]
    return [a for a in dict.fromkeys(_address(p) for p in parts) if a], [p for p in parts if not _address(p)]


def enforced():
    return admins_setting() is not None


def _principal(value):
    """X-MS-CLIENT-PRINCIPAL: base64 JSON {auth_typ, claims: [{typ, val}], name_typ, role_typ}; {} if it cannot be read."""
    if not value:
        return {}
    try:
        text = base64.b64decode(value + "=" * (-len(value) % 4)).decode("utf8")
        d = json.loads(text)
        return d if isinstance(d, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def identity(headers):
    """Who the sign-in says is asking: {signed_in, email, emails, name}. headers: names in lower case.
    `emails` are every address the sign-in gives for the person (the name header first), so a person is found whichever
    of them an admin typed."""
    name_header = (headers.get("x-ms-client-principal-name") or "").strip()
    p = _principal(headers.get("x-ms-client-principal"))
    claims = [c for c in p.get("claims") or [] if isinstance(c, dict)]
    values = [name_header]
    for typ in EMAIL_CLAIMS + ((p.get("name_typ"),) if p.get("name_typ") else ()):
        values += [str(c.get("val") or "") for c in claims if c.get("typ") == typ]
    emails = [e for e in dict.fromkeys(_address(v) for v in values) if e]
    shown = next((str(c.get("val")) for c in claims if c.get("typ") == "name" and c.get("val")), "")
    return {"signed_in": bool(name_header or claims), "email": emails[0] if emails else name_header.lower()[:254],
            "emails": emails or ([name_header.lower()[:254]] if name_header else []), "name": shown[:120]}


def effective(role, changed):
    """What a role may do: its defaults, with what admins changed (`changed`: {(role, permission): allowed})."""
    if role == ADMIN:
        return set(ALL)
    allowed = set(DEFAULTS.get(role, ()))
    for (r, perm), on in changed.items():
        if r == role and perm in LABEL and perm not in FIXED:
            (allowed.add if on else allowed.discard)(perm)
    return allowed


def person(headers):
    """The person asking and what they may do. let_in False comes with the status and the words of the refusal."""
    setting = admins_setting()
    me = identity(headers)
    out = dict(me, on=setting is not None, role=None, from_setting=False, let_in=False, allowed=[], status=None, why=None,
               store=None)
    if setting is None:
        return dict(out, let_in=True, allowed=list(ALL), why=OFF_WORDS)
    admins, _ = setting
    if not me["signed_in"]:
        return dict(out, status=401, why="No Microsoft sign-in reached RightPrice, so it cannot tell who you are. Sign in and try again.")
    if set(me["emails"]) & set(admins):
        return dict(out, role=ADMIN, from_setting=True, let_in=True, allowed=list(ALL))
    st = store.get()
    out["store"] = st.kind
    if st.kind == "files":
        return dict(out, status=503, why=FILES_WORDS)
    try:
        found, changed = st._read(lambda c: (data_users.find(c, me["emails"]), data_users.overrides(c)))
    except store.StoreUnavailable:
        return dict(out, status=503, why="Who may use RightPrice is kept in the database, which cannot be read just now. "
                                         "Try again in a minute.")
    rec = next((r for e in me["emails"] for r in found if r["email"] == e), None)
    if rec is None:
        return dict(out, status=403, why=f"You have not been given access to RightPrice yet. Ask an admin to add you: you are "
                                         f"signed in as {me['email'] or 'an account with no e-mail address'}.")
    out.update(email=rec["email"], name=rec["name"] or me["name"], role=rec["role"])
    if not rec["active"]:
        return dict(out, status=403, why="Your access to RightPrice has been switched off. Ask an admin if this is a mistake.")
    if rec["role"] not in ROLES:
        return dict(out, status=403, why=f"Your role ({rec['role']}) is not one RightPrice knows. Ask an admin to set it again.")
    return dict(out, let_in=True, allowed=sorted(effective(rec["role"], changed), key=ALL.index))


def permission_for(key, path):
    """The permission an address needs (None: none assigned)."""
    return ROUTES.get(key) or ROUTES.get(f"* {path}")


def check(headers, need):
    """Whether a request may go on to its route: None if so; else (status, words) to refuse it with."""
    if need is None:
        return 403, ("This address has no permission assigned yet, so RightPrice refuses it to everyone until one is "
                     "(rules/access.py, ROUTES).")
    if need == PUBLIC:
        return None
    p = person(headers)
    if not p["let_in"]:
        return p["status"], p["why"]
    if need == MEMBER or need in p["allowed"]:
        return None
    return 403, f"Your role ({p['role']}) may not {VERB.get(need, need)}. Ask an admin if you need to."


def me(headers):
    """/api/me: who you are signed in as, your role, and what you may do (the shell hides the rest; the server refuses it)."""
    p = person(headers)
    admin = p["let_in"] and "do:manage_users" in p["allowed"] and p["on"]
    setting = admins_setting()
    return {"permissions_on": p["on"], "signed_in": p["signed_in"], "email": p["email"], "name": p["name"], "role": p["role"],
            "from_setting": p["from_setting"], "let_in": p["let_in"], "allowed": p["allowed"], "why": p["why"],
            "setting_ignored": setting[1] if admin and setting else [], "marks_note": MARKS_NOTE}


# ------------------------------------------------------------------ the admin page
def _store_for_users():
    st = store.get()
    if st.kind == "files":
        raise Refused(503, "Users and roles are kept in the database, and RightPrice is keeping its data in files (the app "
                           "setting DATABASE_URL is not set). Add the database first; until then permissions cannot be switched on "
                           "for anyone but the admins named in " + ADMINS_ENV + ".")
    return st


def _admin(headers):
    """The admin making a change (their sign-in address), or a refusal: changes are made only with permissions on, by an
    admin. With permissions off anyone signed in could make themselves an admin, so nothing is changed then."""
    if not enforced():
        raise Refused(409, f"Permissions are off, so RightPrice cannot tell an admin from anyone else: changes here are "
                           f"refused until the app setting {ADMINS_ENV} is added (see docs/AZURE_DEPLOY.md, \"Users and roles\").")
    p = person(headers)
    if not p["let_in"] or "do:manage_users" not in p["allowed"]:
        raise Refused(403, f"Your role ({p['role'] or 'none'}) may not change who may use RightPrice.")
    return p["email"]


def users_view(headers=None):
    """Everything the admin page shows: the people, each role's permissions (and which differ from the defaults), the AI
    assistant's fixed role, and the record of changes."""
    st = _store_for_users()

    def get(c):
        return data_users.people(c), data_users.overrides(c), data_users.override_rows(c), data_users.audit(c)
    people, changed, rows, log = st._read(get)
    setting = admins_setting()
    grid = {role: {k: {"allowed": k in effective(role, changed), "default": k in DEFAULTS[role]} for k in ALL} for role in ROLES}
    assistant = set(ASSISTANT_TOOLS.values())
    return {"permissions_on": setting is not None, "why_off": None if setting else OFF_WORDS,
            "setting_admins": setting[0] if setting else [], "setting_ignored": setting[1] if setting else [],
            "roles": ROLES, "assistant": {"name": ASSISTANT, "allowed": [k for k in ALL if k in assistant], "tools": ASSISTANT_TOOLS,
                                          "note": ASSISTANT_NOTE},
            "permissions": [{"key": k, "label": label, "fixed": k in FIXED, "group": "Pages" if k.startswith("page:") else "Actions"}
                            for k, label, _ in PERMISSIONS],
            "grid": grid, "changed": rows, "people": people,
            "admins_in_list": [p["email"] for p in people if p["role"] == ADMIN and p["active"]],
            "audit": log, "marks_note": MARKS_NOTE}


def _clean_name(v):
    name = " ".join(str(v or "").split())
    if len(name) > 120:
        raise Refused(400, "A name of at most 120 characters, please.")
    return name


def _role(v):
    if v not in ROLES:
        raise Refused(400, f"The role must be one of: {', '.join(ROLES)}.")
    return v


def add_person(payload, headers):
    who = _admin(headers)
    st = _store_for_users()
    email = _address(payload.get("email"))
    if not email:
        raise Refused(400, "Type the person's e-mail address as they sign in to Microsoft, for example name@company.com.")
    name, role = _clean_name(payload.get("name")), _role(payload.get("role"))
    at = store._now()
    with st.tx(write="users") as c:
        if data_users.find(c, [email]):
            raise Refused(400, f"{email} is already in the list: change their role or switch them on there.")
        data_users.add(c, email, name, role, at, who)
        data_users.log(c, at, who, "person added", email, {"name": name, "role": role})
    return {"added": email, "role": role}


def change_person(payload, headers):
    """Change a person's role, name, or switch them off or on. The last active admin in the list stays an active admin."""
    who = _admin(headers)
    st = _store_for_users()
    email = _address(payload.get("email")) or str(payload.get("email") or "").strip().lower()
    at = store._now()
    with st.tx(write="users") as c:
        found = data_users.find(c, [email])
        if not found:
            raise Refused(404, f"{email or 'That address'} is not in the list.")
        old = found[0]
        new = {}
        if "role" in payload and payload["role"] != old["role"]:
            new["role"] = _role(payload["role"])
        if "name" in payload and _clean_name(payload["name"]) != old["name"]:
            new["name"] = _clean_name(payload["name"])
        if "active" in payload and bool(payload["active"]) != old["active"]:
            new["active"] = bool(payload["active"])
        if not new:
            raise Refused(400, "Nothing to change: that is how it is already.")
        stays_admin = new.get("role", old["role"]) == ADMIN and new.get("active", old["active"])
        if old["role"] == ADMIN and old["active"] and not stays_admin and data_users.active_admins(c) == [email]:
            raise Refused(400, f"{email} is the last admin in the list, so they stay an admin. Make someone else Admin first.")
        data_users.update(c, email, at, who, **new)
        if "role" in new:
            data_users.log(c, at, who, "role changed", email, {"from": old["role"], "to": new["role"]})
        if "name" in new:
            data_users.log(c, at, who, "name changed", email, {"from": old["name"], "to": new["name"]})
        if "active" in new:
            data_users.log(c, at, who, "switched on" if new["active"] else "switched off", email, {})
    return {"changed": email, "what": sorted(new)}


def set_permissions(payload, headers):
    """Give a role a permission, or take one away: payload {"changes": [{"role", "permission", "allowed"}]}. Admin always
    has everything, and user admin stays Admin's alone."""
    who = _admin(headers)
    st = _store_for_users()
    changes = payload.get("changes")
    if not isinstance(changes, list) or not changes:
        raise Refused(400, "No change was sent.")
    for ch in changes:
        if not isinstance(ch, dict) or ch.get("role") not in ROLES or ch.get("permission") not in LABEL or not isinstance(ch.get("allowed"), bool):
            raise Refused(400, "Each change needs a role, a permission RightPrice knows, and allowed true or false.")
        if ch["role"] == ADMIN:
            raise Refused(400, "Admin always has every permission: it cannot be changed.")
        if ch["permission"] in FIXED:
            raise Refused(400, f"\"{LABEL[ch['permission']]}\" stays with Admin alone.")
    at, done = store._now(), []
    with st.tx(write="users") as c:
        changed = data_users.overrides(c)
        for ch in changes:
            role, perm, on = ch["role"], ch["permission"], ch["allowed"]
            if (perm in effective(role, changed)) == on:
                continue
            data_users.set_override(c, role, perm, None if on == (perm in DEFAULTS[role]) else on, at, who)
            changed[(role, perm)] = on
            data_users.log(c, at, who, "permission given" if on else "permission taken away", role,
                           {"permission": perm, "label": LABEL[perm], "verb": VERB[perm], "default": perm in DEFAULTS[role]})
            done.append({"role": role, "permission": perm, "allowed": on})
    return {"changed": done}
