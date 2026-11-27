"""Who may use RightPrice, and what each person may do (stage 3 of the rebuild; GP's decisions of 27 Nov 2026).

Switched on by the app setting RIGHTPRICE_ADMINS: the sign-in addresses of the first admins, separated by commas. Without
it the app behaves as before: everyone signed in may use everything, and /api/me says permissions are off.

With it:
- a person is let in only once an admin has added them (Users and roles, under the user icon), with one of four roles.
  The admins named in the setting are always let in as Admin, whether or not they are in the list;
- every address the server answers needs a permission (ROUTES below: page:<name> to see, do:<action> to change),
  checked in one place (server.py, AccessGate) before the request reaches its route. An address with no permission
  assigned is refused to everyone, and check_server.py fails while one exists, so a later stage cannot forget one;
- a request with no sign-in is refused, never treated as an admin; a person not added is told so (403);
- on the files store (no DATABASE_URL) there is nowhere to keep the list of people: only the admins named in the setting
  get in, and everyone else is told why.

What a page's tick does, and does not do. Actions (do:) are strict: a role without one cannot do it anywhere. A page
(page:) decides whether the role can open that page; it is not a way to keep figures secret. An address that several
pages read is open to a role that has any of them (so unticking one page never breaks another), and the drop-down lists
every screen loads (/api/meta) carry the yarn master with its rates for anyone let in. PAGE_USES lists what each page
reads; the admin page says per page what unticking it hides and what still reaches the role.

The person comes from one value only: X-MS-CLIENT-PRINCIPAL-NAME, as Azure App Service's sign-in sets it, or, when it is
absent, the preferred_username or upn claim of X-MS-CLIENT-PRINCIPAL. Microsoft ("Work with user identities in
AuthN/AuthZ", read 27 Nov 2026) says requests from outside cannot set these headers, and calls the name "a human-readable
name ... such as an email address or user principal name"; it does not say which for personal or guest accounts. A
personal Microsoft account may arrive as "live.com#name@example.com": that prefix is dropped, nothing else is. People are
known by that value, lower case. On Azure (WEBSITE_SITE_NAME set) the headers are trusted only while App Service sign-in
is on (WEBSITE_AUTH_ENABLED, which App Service sets); off Azure anyone can send them, so on a laptop leave
RIGHTPRICE_ADMINS unset.

The MCP token (RIGHTPRICE_MCP_TOKEN, server.py McpGate) is its own fixed role, "AI assistant" (ASSISTANT_ALLOWED): each
of its tools names the address it mirrors (mcp_server.py) and goes through assistant_refusal() with that address's
permission before it runs. It is not changed on the admin page.

Each person's own marks (Status and Remarks in Right cost, saved searches, Library lists) stay in their browser in this
stage; moving them to the server is a separate choice for GP.
"""
import base64
import json
import os
import re
import sys

import data_users
import store
from rules.common import Refused

ADMINS_ENV = "RIGHTPRICE_ADMINS"
ADMIN, RATES, BUYER, VIEWER = "Admin", "Rates editor", "Buyer", "Viewer"
ROLES = [ADMIN, RATES, BUYER, VIEWER]
ASSISTANT = "AI assistant"

PUBLIC = "open to anyone"                   # the shell's files, and /api/me (which says who you are and what you may do)
SHELL = "the shell"                         # the shell page: refused only for what needs no database; its data is guarded
MEMBER = "anyone let in"                    # the lists for the drop-downs, where the data is kept

# every permission, in the order the admin page shows them:
# (key, what it is, what a refusal says the role may not do, for a page: what unticking it hides and what still shows)
PERMISSIONS = [
    ("page:dashboard", "Home: Dashboard", "see the Dashboard",
     "Unticked, the Dashboard (the home page) shows a notice instead. Its figures still reach the role elsewhere: the "
     "fabric list and quote alerts in Right cost and Bulk upload, the tracker in Right cost, the pilot results on Pilot "
     "results, the cotton prices and the mill rate card on the Prices pages."),
    ("page:pilot", "Home: Pilot results", "see the pilot results",
     "Unticked, Pilot results is not offered. The Dashboard still shows the pilot's summary (should-cost against the "
     "price paid by fabric type and by supplier, and the overall fit) to a role that has the Dashboard."),
    ("page:rightcost", "Right cost: the list, each fabric's page, supplier pages, the tracker's steps and quote alerts (to look at)", "see Right cost",
     "Unticked, Right cost, the fabric pages and the supplier pages are not offered. Quote alerts still show on the "
     "Dashboard; fabric-list rows in Bulk upload, Compare and the negotiation pack; purchase orders summed by fabric "
     "type and by supplier on the Dashboard."),
    ("page:cost", "Create cost and Compare (cost a fabric; download its cost sheet)", "cost a fabric",
     "Unticked, Create cost and Compare are not offered. Right cost's fabric pages still cost a fabric (with the rates it "
     "uses), and the drop-down lists every screen loads still carry the yarn rates."),
    ("page:list", "Bulk upload: the fabric list (to look at), costing a filled template, downloads", "see the fabric list",
     "Unticked, Bulk upload is not offered. The list's rows still show on the Dashboard, in Compare, in the negotiation "
     "pack and in Right cost."),
    ("page:pack", "Negotiation pack", "make a negotiation pack",
     "Unticked, the negotiation pack is not offered. Its rows still show in Right cost and Bulk upload."),
    ("page:prices", "Prices: yarn and cotton prices, rate tables, mill rate card, calculation settings (to look at)", "see the rate tables and prices",
     "Unticked, the price and rate pages are not offered. The yarn master with its rates still reaches every role let in "
     "(the drop-down lists every screen loads); the Dashboard shows the cotton price by year, the mill rate card's print "
     "and quantity terms and the order size slabs; Create cost and Right cost show every rate a costing uses."),
    ("page:costsheets", "Prices: mill cost sheets (to look at)", "see the mill cost sheets",
     "Unticked, Mill cost sheets is not offered. No other page shows the mills' sheets; a draft that was applied shows "
     "in the rate tables' Basis."),
    ("page:users", "Users and roles (this page)", "see who may use RightPrice", ""),
    ("do:edit_rates", "Edit rates: rate tables, yarn and cotton prices, Bring in prices", "edit rates", ""),
    ("do:apply_drafts", "Apply mill cost sheet drafts to the rate master", "apply mill cost sheet drafts", ""),
    ("do:upload", "Upload and change: mill sheets, Add to list, update or remove list rows, mill cost sheets", "upload or change the fabric list and mill cost sheets", ""),
    ("do:record_steps", "Record and remove negotiation steps in the tracker", "record or remove negotiation steps", ""),
    ("do:mark_seen", "Mark quote alerts seen for everyone, or bring them back", "mark quote alerts seen", ""),
    ("do:draft", "Draft messages to mills (e-mail and WhatsApp; nothing is sent)", "draft messages to mills", ""),
    ("do:manage_users", "Add people, change their role, switch them off, change what each role may do", "change who may use RightPrice", ""),
]
LABEL = {k: label for k, label, _, _ in PERMISSIONS}
VERB = {k: verb for k, _, verb, _ in PERMISSIONS}
ALL = [k for k, _, _, _ in PERMISSIONS]
FIXED = {"page:users", "do:manage_users"}           # Admin's alone; not given to another role on the admin page
_PAGES = {k for k in ALL if k.startswith("page:")} - FIXED
DEFAULTS = {                                         # GP, 27 Nov 2026
    ADMIN: set(ALL),                                 # everything, users included (always: not changed on the page)
    RATES: set(ALL) - FIXED,                         # may edit rates and apply mill cost sheet drafts; no user admin
    BUYER: _PAGES | {"do:upload", "do:record_steps", "do:mark_seen", "do:draft"},   # every page, uploads, steps, drafts
    VIEWER: set(_PAGES),                             # read only
}
GRID_NOTE = ("A page's tick decides whether this role can open that page. It is not a way to keep figures secret: an "
             "address several pages read stays open to a role that has any of them, so that unticking one page never breaks "
             "another, and the drop-down lists every screen loads carry the yarn rates for anyone let in. Each page says what "
             "unticking it hides. Actions are strict: a role without one cannot do it anywhere.")

# every address the server answers, and the permission it needs: one, or a tuple of pages any of which opens it (an
# address several pages read). "METHOD /path" as the route is written in server.py ("* /path" for every method,
# "WS /path" for a web socket, "MOUNT /" for the static files). A later stage adds its addresses here; check_server.py
# fails while any address of the app is missing.
ROUTES = {
    "MOUNT /": PUBLIC,                       # the shell's scripts, styles and icons: no data in them
    "GET /rightcost": PUBLIC,                # a redirect to /#rightcost
    "GET /classic": PUBLIC,                  # the earlier Streamlit screens are retired (stage 4): a bookmark leads to /
    "GET /classic/{path:path}": PUBLIC,
    "GET /api/me": PUBLIC,
    "GET /": SHELL,                          # the shell, with every page in it: no data, no database
    "GET /openapi.json": MEMBER,
    "GET /api/store": MEMBER,
    "GET /api/meta": MEMBER,                 # the drop-down lists every screen loads first (the yarn master with its rates)
    "GET /api/dashboard": "page:prices",     # Yarn prices sets the master against the market from it (the Dashboard page reads /api/insights)
    "GET /api/insights": "page:dashboard",
    "GET /api/negotiations/summary": "page:dashboard",
    "GET /api/pilot": "page:pilot",
    "GET /api/costs": "page:rightcost",
    "POST /api/costs/download": "page:rightcost",
    "GET /api/negotiations": "page:rightcost",
    "GET /api/suppliers": "page:rightcost",
    "GET /api/supplier": "page:rightcost",
    "GET /api/alerts": ("page:rightcost", "page:dashboard"),         # the Dashboard shows the alerts first
    "POST /api/cost": ("page:cost", "page:rightcost"),               # Right cost's Costing and Negotiation tabs cost the fabric
    "POST /api/cost-sheet": "page:cost",
    "POST /api/list": ("page:list", "page:dashboard", "page:cost"),  # the Dashboard's panels, and Compare's choice of fabrics
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
    "GET /api/dated-rates": "page:prices",           # stage 5: dated yarn rates, on the Yarn prices page
    "GET /api/dated-rates/market": "page:prices",    # what the market history would give (only read)
    "POST /api/dated-rates": "do:edit_rates",
    "POST /api/dated-rates/remove": "do:edit_rates",
    "POST /api/dated-rates/market": "do:edit_rates",
    "POST /api/intake/add-dated": "do:edit_rates",   # Bring in prices: the reviewed rows as dated yarn rates
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

# what each page reads (the addresses with a page's permission or MEMBER's), from the screens' own code: web/pages/<page>.js
# (each page of the shell, with what it uses of web/pages/common.js and the drop-down lists every page loads first),
# web/rightcost.js (Right cost), web/access.js (this page).
# check_server.py compares this with the addresses each page's code calls, both ways, and checks that each page's
# permission opens every address on its list, so unticking another page cannot break it.
PAGE_USES = {
    "page:dashboard": ["GET /api/meta", "GET /api/insights", "POST /api/list", "GET /api/alerts", "GET /api/negotiations/summary"],
    "page:pilot": ["GET /api/meta", "GET /api/pilot"],
    "page:rightcost": ["GET /api/costs", "GET /api/negotiations", "GET /api/alerts", "POST /api/cost", "GET /api/supplier",
                       "POST /api/costs/download"],
    "page:cost": ["GET /api/meta", "POST /api/cost", "POST /api/cost-sheet", "POST /api/list"],     # Create cost and Compare
    "page:list": ["GET /api/meta", "POST /api/list", "POST /api/list/download", "GET /api/template"],
    "page:pack": ["GET /api/meta", "POST /api/pack"],
    "page:prices": ["GET /api/meta", "GET /api/table/{sheet}", "GET /api/dashboard", "GET /api/cotton",
                    "GET /api/dated-rates", "GET /api/dated-rates/market"],          # stage 5: web/dated.js on Yarn prices
    "page:costsheets": ["GET /api/meta", "GET /api/costsheet", "GET /api/costsheet/template"],
    "page:users": ["GET /api/users"],
}

# the AI assistant (the MCP token): a fixed role. Each tool names the address it mirrors (mcp_server.py) and runs only if
# this role holds that address's permission (assistant_refusal).
ASSISTANT_ALLOWED = {"page:cost", "page:rightcost", "page:pack", "do:record_steps"}
ASSISTANT_NOTE = ("The MCP token: one fixed role, what its tools do today. Each tool goes through the same permission as "
                  "the screen's address it mirrors. It records negotiation steps as \"AI assistant\" and removes only steps "
                  "it recorded itself; it cannot change rates, upload, remove rows, mark alerts seen, draft messages or change "
                  "users. It is switched on by the app setting RIGHTPRICE_MCP_TOKEN, not here.")
MARKS_NOTE = ("Each person's own marks (Status and Remarks in Right cost, saved searches, Library lists) are still kept in "
              "their own browser, as before; they are not shared and not part of these permissions.")
OFF_WORDS = ("Permissions are off: everyone signed in may use everything. They are switched on by the app setting "
             f"{ADMINS_ENV} (the first admins' sign-in addresses).")
FILES_WORDS = (f"Permissions are on (the app setting {ADMINS_ENV}), but RightPrice is keeping its data in files, which cannot "
               "hold the list of people. Until the app setting DATABASE_URL is added, only the admins named in "
               f"{ADMINS_ENV} can use it. Ask an admin.")
NO_ADMIN_WORDS = (f"Note for the admins: the app setting {ADMINS_ENV} names no valid e-mail address, so it gives nobody "
                  "admin rights. Correct it in the Azure portal (web app > Settings > Environment variables).")
UNTRUSTED_WORDS = ("App Service sign-in (Authentication) is off on this web app, so RightPrice cannot trust who is asking and "
                   f"lets nobody in while the app setting {ADMINS_ENV} is set. Turn sign-in back on (web app > Settings > "
                   f"Authentication), or remove {ADMINS_ENV} to open the site to everyone as before.")
NO_SIGN_IN_WORDS = "No Microsoft sign-in reached RightPrice, so it cannot tell who you are. Sign in and try again."
DB_DOWN_WORDS = "Who may use RightPrice is kept in the database, which cannot be read just now. Try again in a minute."
IDENTITY_HEADERS = ("x-ms-client-principal-name", "x-ms-client-principal", "x-ms-client-principal-id", "x-ms-client-principal-idp")
UPN_CLAIMS = ("upn", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn")
_LOCAL = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
EMAIL = re.compile(rf"{_LOCAL}@(?:{_LABEL}\.)+[a-z]{{2,63}}")


# ------------------------------------------------------------------ the setting, and who is asking
def valid_email(text):
    """The address, lower case, if the text is one (as an admin types it); else None."""
    s = str(text or "").strip().lower()
    return s if len(s) <= 254 and EMAIL.fullmatch(s) else None


def setting_entry(text):
    """One address as people write it: "gp@x.com" (quoted), GP <gp@x.com>, mailto:gp@x.com, gp@x.com. (a full stop),
    live.com#gp@outlook.com (how a personal Microsoft account can arrive; the sign-in's value has that dropped too)."""
    s = str(text or "").strip()
    inside = re.search(r"<([^<>]*)>", s)
    if inside:
        s = inside.group(1)
    s = s.strip().strip("\"'`").strip()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    if s.lower().startswith("live.com#"):
        s = s[len("live.com#"):]
    return s.strip().rstrip(".").strip("\"'`").strip()


def _setting_words(part):
    """The entries in one comma-separated part: each <address>, and outside the brackets each word with an @ in it (a
    word without one beside a bracketed address is the person's name). Without brackets, each word is an entry."""
    if "<" not in part:
        return part.split()
    inside = re.findall(r"<[^<>]*>", part)
    rest = re.sub(r"<[^<>]*>|\"[^\"]*\"", " ", part).split()
    return inside + [w for w in rest if "@" in w or "<" in w or ">" in w]


_logged = {}


def admins_setting():
    """None when the setting is not there (permissions off); else (the admins' addresses, entries that are not one).
    A setting with entries but no usable address is said once in the log, without its contents."""
    raw = os.environ.get(ADMINS_ENV)
    if raw is None or not raw.strip():
        return None
    good, bad = [], []
    for part in re.split(r"[,;\n]+", raw):
        if not part.strip():
            continue
        for word in _setting_words(part):
            addr = valid_email(setting_entry(word))
            if addr:
                good.append(addr)
            else:
                bad.append(word.strip())
    good = list(dict.fromkeys(good))
    if _logged.get("raw") != raw:
        _logged["raw"] = raw
        if not good:
            print(f"RightPrice: the app setting {ADMINS_ENV} names no valid e-mail address, so it gives nobody admin rights. "
                  "Correct it in the Azure portal.", file=sys.stderr)
        elif bad:
            print(f"RightPrice: the app setting {ADMINS_ENV} has {len(bad)} {'entry' if len(bad) == 1 else 'entries'} that "
                  "is not an e-mail address, ignored (an admin sees which on Users and roles).", file=sys.stderr)
    return good, bad


def enforced():
    return admins_setting() is not None


def trusted():
    """On Azure the sign-in headers mean something only while App Service sign-in is on: WEBSITE_AUTH_ENABLED, which
    App Service sets (Microsoft, "Environment variables and app settings reference"). Off Azure there is no such setting."""
    if not os.environ.get("WEBSITE_SITE_NAME"):
        return True
    return os.environ.get("WEBSITE_AUTH_ENABLED", "").strip().lower() in ("true", "1")


def duplicated(raw_headers):
    """True when a request carries one of the sign-in headers more than once (raw_headers: (name, value) pairs as sent)."""
    seen = set()
    for name, _ in raw_headers:
        n = (name.decode("latin1") if isinstance(name, bytes) else str(name)).lower()
        if n in IDENTITY_HEADERS:
            if n in seen:
                return True
            seen.add(n)
    return False


def _claims(value):
    """The claims of X-MS-CLIENT-PRINCIPAL (base64 JSON {auth_typ, claims: [{typ, val}], name_typ, role_typ}) as
    [(typ, val)]; [] for anything that does not read as that, so a malformed one counts as absent."""
    if not isinstance(value, str) or not value.strip():
        return []
    text = value.strip()
    try:
        d = json.loads(base64.b64decode(text + "=" * (-len(text) % 4)).decode("utf8"))
    except Exception:
        return []
    claims = d.get("claims") if isinstance(d, dict) else None
    if not isinstance(claims, list):
        return []
    return [(c["typ"], c["val"]) for c in claims
            if isinstance(c, dict) and isinstance(c.get("typ"), str) and isinstance(c.get("val"), str)]


def identity(headers):
    """Who the sign-in says is asking: {signed_in, email, name}. headers: a mapping with lower-case names.
    One value only: X-MS-CLIENT-PRINCIPAL-NAME; when it is absent, the preferred_username claim, then the upn claim.
    Never the display name. "live.com#" in front (a personal Microsoft account) is dropped."""
    claims = _claims(headers.get("x-ms-client-principal"))
    value = (headers.get("x-ms-client-principal-name") or "").strip()
    if not value:
        value = next((v.strip() for t, v in claims if t == "preferred_username" and v.strip()), "") \
            or next((v.strip() for t, v in claims if t in UPN_CLAIMS and v.strip()), "")
    email = value.lower()[:254]
    if email.startswith("live.com#"):
        email = email[len("live.com#"):]
    shown = next((v for t, v in claims if t == "name"), "")         # shown on screen only, never used to identify
    return {"signed_in": bool(email), "email": email, "name": shown.strip()[:120]}


def effective(role, changed):
    """What a role may do: its defaults, with what admins changed (`changed`: {(role, permission): allowed})."""
    if role == ADMIN:
        return set(ALL)
    allowed = set(DEFAULTS.get(role, ()))
    for (r, perm), on in changed.items():
        if r == role and perm in LABEL and perm not in FIXED:
            (allowed.add if on else allowed.discard)(perm)
    return allowed


def _before_database(me, setting):
    """What is decided without the database: None (go on), "admin" (named in the setting), or (status, words)."""
    admins, _ = setting
    hint = "" if admins else " " + NO_ADMIN_WORDS
    if not trusted():
        return 503, UNTRUSTED_WORDS, "setup"
    if not me["signed_in"]:
        return 401, NO_SIGN_IN_WORDS + hint, "sign_in"
    if me["email"] in admins:
        return "admin"
    if store.get().kind == "files":
        return 503, FILES_WORDS + hint, "setup"
    return None


def person(headers):
    """The person asking and what they may do. let_in False comes with the status and the words of the refusal."""
    setting = admins_setting()
    me = identity(headers)
    out = dict(me, on=setting is not None, role=None, from_setting=False, let_in=False, allowed=[], status=None, why=None,
               why_kind=None)          # sign_in | person (not added, switched off) | database (try again) | setup
    if setting is None:
        return dict(out, let_in=True, allowed=list(ALL), why=OFF_WORDS)
    hint = "" if setting[0] else " " + NO_ADMIN_WORDS
    first = _before_database(me, setting)
    if first == "admin":
        return dict(out, role=ADMIN, from_setting=True, let_in=True, allowed=list(ALL))
    if first is not None:
        return dict(out, status=first[0], why=first[1], why_kind=first[2])
    try:
        found, changed = store.get()._read(lambda c: (data_users.find(c, [me["email"]]), data_users.overrides(c)))
    except Exception:           # unreachable, busy, or a SQLite file locked by another process: never let in on a guess
        return dict(out, status=503, why=DB_DOWN_WORDS + hint, why_kind="database")
    if not found:
        return dict(out, status=403, why=f"You have not been given access to RightPrice yet. Ask an admin to add you: you are "
                                         f"signed in as {me['email']}." + hint, why_kind="person")
    rec = found[0]
    out.update(name=rec["name"] or me["name"], role=rec["role"])
    if not rec["active"]:
        return dict(out, status=403, why="Your access to RightPrice has been switched off. Ask an admin if this is a mistake." + hint,
                    why_kind="person")
    if rec["role"] not in ROLES:
        return dict(out, status=403, why=f"Your role ({rec['role']}) is not one RightPrice knows. Ask an admin to set it again.",
                    why_kind="person")
    return dict(out, let_in=True, allowed=sorted(effective(rec["role"], changed), key=ALL.index))


def permission_for(key, path):
    """The permission an address needs: one, or a tuple of pages any of which opens it (None: none assigned)."""
    return ROUTES.get(key) or ROUTES.get(f"* {path}")


def _needs(need):
    return need if isinstance(need, tuple) else (need,)


def opens(need, allowed):
    """Whether a role with these permissions may use an address that needs `need`."""
    return need == MEMBER or any(n in allowed for n in _needs(need))


def check(headers, need):
    """Whether a request may go on to its route: None if so; else (status, words) to refuse it with."""
    if need is None:
        return 403, ("This address has no permission assigned yet, so RightPrice refuses it to everyone until one is "
                     "(rules/access.py, ROUTES).")
    if need == PUBLIC:
        return None
    if need == SHELL:           # the shell carries no data: decided without the database; the page then asks /api/me
        setting = admins_setting()
        first = _before_database(identity(headers), setting) if setting is not None else None
        return first[:2] if isinstance(first, tuple) else None
    p = person(headers)
    if not p["let_in"]:
        return p["status"], p["why"]
    if opens(need, p["allowed"]):
        return None
    return 403, f"Your role ({p['role']}) may not {VERB.get(_needs(need)[0], need)}. Ask an admin if you need to."


def assistant_refusal(route):
    """The AI assistant's tools: None if its fixed role may use the address the tool mirrors; else the words."""
    need = ROUTES.get(route)
    if need is None:
        return f"This tool mirrors {route}, which has no permission assigned, so it is refused. Nothing was done."
    if opens(need, ASSISTANT_ALLOWED):
        return None
    return f"The AI assistant may not {VERB.get(_needs(need)[0], need)}. Nothing was done."


def me(headers):
    """/api/me: who you are signed in as, your role, and what you may do (the shell hides the rest; the server refuses it)."""
    p = person(headers)
    admin = p["let_in"] and "do:manage_users" in p["allowed"] and p["on"]
    setting = admins_setting()
    return {"permissions_on": p["on"], "signed_in": p["signed_in"], "email": p["email"], "name": p["name"], "role": p["role"],
            "from_setting": p["from_setting"], "let_in": p["let_in"], "allowed": p["allowed"], "why": p["why"],
            "why_kind": p["why_kind"], "sign_in": sign_in_seen(), "setting_ignored": setting[1] if admin and setting else [],
            "marks_note": MARKS_NOTE}


def sign_in_seen():
    """What the app sees of App Service sign-in: "on", "off" (then, with permissions on, nobody is let in), or "not on
    Azure" (a laptop or the checks: nothing to see)."""
    if not os.environ.get("WEBSITE_SITE_NAME"):
        return "not on Azure"
    return "on" if trusted() else "off"


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
    """Everything the admin page shows: the people, each role's permissions (and which differ from the defaults), what
    unticking each page does, the AI assistant's fixed role, and the record of changes. Only with permissions on, and
    only to an admin: with them off anyone signed in could read the people's addresses and the record."""
    if not enforced():
        raise Refused(403, f"Permissions are off, so this page is not shown: anyone signed in could read it. It opens to "
                           f"the admins once the app setting {ADMINS_ENV} is added (docs/AZURE_DEPLOY.md, \"Users and roles\").")
    p = person(headers or {})
    if not p["let_in"] or "page:users" not in p["allowed"]:
        raise Refused(403, f"Your role ({p['role'] or 'none'}) may not see who may use RightPrice.")
    st = _store_for_users()

    def get(c):
        return data_users.people(c), data_users.overrides(c), data_users.override_rows(c), data_users.audit(c)
    people, changed, rows, log = st._read(get)
    setting = admins_setting()
    grid = {role: {k: {"allowed": k in effective(role, changed), "default": k in DEFAULTS[role]} for k in ALL} for role in ROLES}
    try:                # each tool and the address it mirrors, from the tools themselves (the MCP package may be missing)
        import mcp_server
        tools = dict(mcp_server.MIRRORS)
    except Exception:
        tools = {}
    return {"permissions_on": True, "why_off": None,
            "setting_admins": setting[0] if setting else [], "setting_ignored": setting[1] if setting else [],
            "roles": ROLES, "assistant": {"name": ASSISTANT, "allowed": [k for k in ALL if k in ASSISTANT_ALLOWED], "tools": tools,
                                          "note": ASSISTANT_NOTE},
            "permissions": [{"key": k, "label": label, "fixed": k in FIXED, "group": "Pages" if k.startswith("page:") else "Actions",
                             "unticked": note} for k, label, _, note in PERMISSIONS],
            "grid_note": GRID_NOTE, "grid": grid, "changed": rows, "people": people,
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
    raw = str(payload.get("email") or "").strip()
    email = valid_email(setting_entry(raw[len("live.com#"):] if raw.lower().startswith("live.com#") else raw))
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
    email = str(payload.get("email") or "").strip().lower()
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
