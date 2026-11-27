"""RightPrice web server: the web requests layer.

Run: python -m uvicorn server:app --port 8000

Three layers since stage 1 of the rebuild (27 Nov 2026):
- the costing engine: engine.py and masters.py (every number, from the rate master's rates);
- the business rules: rules/ (briefs, the fabric list, the pack, Right cost, the tracker, supplier pages, alerts, drafts,
  the dashboard, rate edits), which read and write only through the data layer, store.py (files, or a database when the
  app setting DATABASE_URL is set);
- the web requests: this file. It reads the request, calls one rule, and turns the answer into the response: a refusal
  into its status and words, a download into a file, an unreachable database into 503. It decides nothing itself.

The front end is one shell (web/rightcost.html, its pages in web/pages/) since stage 4 (27 Nov 2026); the earlier
front end and the Streamlit screens (/classic) are retired.
"""
import asyncio
import datetime as dt
import json
import os
import sys
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import Body, FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import store
from rules import (alerts, common, costing, costsheets, dashboard, drafts, fabric_list, pack as pack_rules, rates, rightcost,
                   supplier as supplier_rules, tracker)
from rules import access

HERE = os.path.dirname(os.path.abspath(__file__))


WEB = os.path.join(HERE, "web")


@asynccontextmanager
async def lifespan(_app):
    # more worker threads than the default 40, so that requests waiting on a slow database cannot hold up the pages and files
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens = 120
    await asyncio.to_thread(store.get)      # with DATABASE_URL set: connect, add any new tables, copy the files in on the first start
    if _mcp_app is not None:
        async with mcp_server.mcp.session_manager.run():       # the MCP endpoint's own machinery, for as long as the app runs
            yield
    else:
        yield


app = FastAPI(title="RightPrice", lifespan=lifespan, docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ MCP: an AI assistant's way in, behind a secret token
try:
    import mcp_server
    from mcp.server.transport_security import TransportSecuritySettings
    # one JSON answer per request and no sessions kept: nothing to lose on a restart. The token is the protection,
    # so the host check meant for servers on a developer's own machine is off.
    _mcp_app = mcp_server.mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True,
                                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
except Exception as _e:        # the package missing or changed must never take the site down: MCP is simply off
    mcp_server, _mcp_app = None, None
    print(f"RightPrice: MCP is off ({type(_e).__name__}: {_e})", file=sys.stderr)


class McpGate:
    """Everything under /mcp. Switched off (404) unless the app setting RIGHTPRICE_MCP_TOKEN is set; with it, every
    request must carry "Authorization: Bearer <token>" (401 otherwise). /mcp/health tells a caller holding the token
    that the site is up and which code it runs. Nothing else on the site is touched by this."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/mcp" or path.startswith("/mcp/")):
            return await self.inner(scope, receive, send)

        async def answer(status, body, extra=()):
            data = json.dumps(body).encode()
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"), (b"content-length", str(len(data)).encode()), *extra]})
            await send({"type": "http.response.body", "body": data})

        if mcp_server is None or mcp_server.token() is None:
            return await answer(404, {"detail": "The MCP endpoint is switched off on this server."})
        auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin1")
        if not mcp_server.allowed(auth):
            return await answer(401, {"detail": "A token is needed: send the header Authorization: Bearer <token>."}, [(b"www-authenticate", b"Bearer")])
        if path != "/mcp/health" and scope.get("method") != "POST":
            # one JSON answer per POST and no sessions: there is no stream to open and nothing to delete
            return await answer(405, {"detail": "The MCP endpoint takes POST requests only."}, [(b"allow", b"POST")])
        if path == "/mcp/health":
            def rates_version():        # in a worker thread: a slow database must not hold up the web server's own loop
                try:
                    return store.get().version("rates"), None
                except store.StoreUnavailable as e:
                    return None, str(e)
            version, unavailable = await asyncio.to_thread(rates_version)
            return await answer(200, {"ok": True, "app": "RightPrice", "code": _code_version(), "store": store.get().kind,
                                      "rate_master_version": version, "store_unavailable": unavailable,
                                      "tools": len(await mcp_server.mcp.list_tools())})
        return await _mcp_app(dict(scope, path="/mcp", raw_path=b"/mcp"), receive, send)


def _code_version():
    """Which code is running: the newest change time among the app's own files (a deploy has no git folder)."""
    try:
        newest = max(os.path.getmtime(os.path.join(HERE, f)) for f in ("server.py", "engine.py", "masters.py", "mcp_server.py", "draft.py"))
        return dt.datetime.fromtimestamp(newest, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except OSError:
        return "unknown"


app.add_middleware(McpGate)


# ------------------------------------------------------------------ stage 3: who may use what, checked here for every request
def _route_for(scope):
    """The route that will answer this request, found the way the router finds it (the first full match, in order)."""
    from starlette.routing import Match
    partial = None
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route
        if match == Match.PARTIAL and partial is None:
            partial = route
    return partial


def _route_key(route, method):
    """How rules/access.py ROUTES names a route: "GET /api/costs", "WS /path" (a web socket), "MOUNT /"."""
    from starlette.routing import Mount, WebSocketRoute
    if isinstance(route, Mount):
        return f"MOUNT {route.path or '/'}"
    if isinstance(route, WebSocketRoute):
        return f"WS {route.path}"
    return f"{'GET' if method == 'HEAD' else method} {route.path}"


def route_keys():
    """Every address the app answers, as ROUTES names them, with the permission each needs (None: none assigned)."""
    from starlette.routing import Mount, WebSocketRoute
    out = {}
    for route in app.router.routes:
        methods = [None] if isinstance(route, (Mount, WebSocketRoute)) else sorted((getattr(route, "methods", None) or {"GET"}) - {"HEAD"})
        for m in methods:
            key = _route_key(route, m)
            out[key] = access.permission_for(key, getattr(route, "path", ""))
    return out


def _refusal_page(status, words):
    """What a browser is shown when RightPrice will not open for this person: plain words, in RightPrice's colours."""
    import html
    title = {400: "RightPrice cannot tell who is asking", 401: "Sign in first", 503: "RightPrice cannot let you in just now"}.get(
        status, "Not open to your role" if words.startswith("Your role") else "Your access is switched off"
        if "switched off" in words else "You have not been given access yet")
    # signing out helps only when the refusal is about who the person is (with sign-in off, /.auth/logout leads nowhere)
    link = ('<a href="/.auth/login/aad?post_login_redirect_uri=/">Sign in</a>' if status == 401
            else '<a href="/.auth/logout">Sign out, to sign in with another account</a>' if status == 403 else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>RightPrice</title><style>body{{margin:0;font:15px/1.5 Manrope,"Segoe UI",system-ui,sans-serif;background:#F6F4EE;color:#1D2521}}'
            f'main{{max-width:34rem;margin:12vh auto;padding:0 16px}}h1{{font-size:22px;color:#1B4D3E;margin:0 0 12px}}'
            f'a{{color:#1B4D3E}}.mark{{display:inline-block;width:36px;height:36px;border-radius:10px;background:#1B4D3E;margin-bottom:16px}}'
            f'@media (prefers-color-scheme: dark){{body{{background:#0F1513;color:#E8EDE9}}h1,a{{color:#F2B23E}}}}</style></head>'
            f'<body><main><div class="mark" aria-hidden="true"></div><h1>{html.escape(title)}</h1><p>{html.escape(words)}</p>'
            f'{f"<p>{link}</p>" if link else ""}</main></body></html>')


class AccessGate:
    """Every request, before it reaches its route: off unless the app setting RIGHTPRICE_ADMINS is set (then the app is
    as it was). With it on, the address's permission (rules/access.py ROUTES) is checked against the signed-in person;
    an address with none assigned is refused. /mcp is the AI assistant's way in, checked by McpGate and its token.
    A request carrying a sign-in header twice is refused (400), so this check and the routes always read the same person.
    The shell page (GET /) is decided without the database: it carries no data, and its data is guarded here."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not access.enforced():
            return await self.inner(scope, receive, send)
        path = scope.get("path", "")
        if path == "/mcp" or path.startswith("/mcp/"):
            return await self.inner(scope, receive, send)
        if access.duplicated(scope.get("headers") or []):
            refused = 400, "This request carries the sign-in twice, so RightPrice cannot tell who is asking. It is refused."
        else:
            route = _route_for(scope)
            key = _route_key(route, scope.get("method", "")) if route is not None else f"{scope.get('method', 'WS')} {path}"
            need = access.permission_for(key, getattr(route, "path", path))
            if need == access.PUBLIC:
                return await self.inner(scope, receive, send)
            headers = {}
            for k, v in scope.get("headers") or []:
                headers.setdefault(k.decode("latin1").lower(), v.decode("latin1"))
            # it may read the database: in a worker thread (the app's own pool of 120), never on the server's own loop
            refused = await anyio.to_thread.run_sync(access.check, headers, need)
        if refused is None:
            return await self.inner(scope, receive, send)
        status, words = refused
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        if path.startswith("/api/") or path == "/openapi.json":
            body, kind = json.dumps({"detail": words}).encode(), b"application/json"
        else:
            body, kind = _refusal_page(status, words).encode("utf8"), b"text/html; charset=utf-8"
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", kind), (b"cache-control", b"no-store"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(AccessGate)      # outside McpGate: it sees every request first, and lets /mcp through to it


@app.exception_handler(store.StoreUnavailable)
async def _store_unavailable(_request, e):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(e)}, status_code=503)


@app.get("/api/store")
def store_status():
    """Where the app keeps its data now (files or a database) and what it holds; never a password."""
    return store.get().describe()


@app.get("/rightcost")
def rightcost_page():
    """The earlier address of Right cost: it is now a page of the shell."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/#rightcost", status_code=307)


@app.get("/classic")
@app.get("/classic/{path:path}")
def classic_retired(path: str = ""):
    """The earlier Streamlit screens are retired (stage 4, 27 Nov 2026): a bookmark of them leads to the app."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/", status_code=307)


def _who(request):
    """The signed-in person, as the permission check reads them (rules/access.py identity: the sign-in's name, lower case,
    without live.com#, or its claims when the name is absent); nothing off Azure."""
    return access.identity(request.headers)["email"][:120] if request is not None else ""


# ------------------------------------------------------------------ quote alerts
"""A mill sheet is uploaded: every row that needs a look before the price is accepted is flagged at once.
Four kinds: priced above its usual range, the mill's own sums are off, the row repeats an order already on the
list, or the quote is far below should-cost. An alert stays until someone marks it seen, the row is removed, or
its negotiation is agreed in the tracker (recording the mill's quote alone does not clear it). No e-mail or push: they show on the Dashboard, on the Right cost rail
item and on the Bulk upload screen."""


@app.exception_handler(common.Refused)
async def _refused(_request, e):
    """A refusal from the rules: its status and its words, as {"detail": ...}."""
    return JSONResponse({"detail": e.detail}, status_code=e.status_code)


def _file(d):
    """A download from the rules, as the browser receives it."""
    return Response(d.data, media_type=d.media_type, headers={"Content-Disposition": f'attachment; filename="{d.filename}"'})


def _plain(o):
    """Numbers from the rate master arrive as numpy types: plain ones for JSON."""
    return o.item() if hasattr(o, "item") else str(o)


# ------------------------------------------------------------------ one fabric
@app.get("/api/meta")
def meta():
    return costing.meta()


@app.post("/api/cost")
def cost(sel: dict = Body(...)):
    return costing.cost(sel)


@app.post("/api/cost-sheet")
def cost_sheet(sel: dict = Body(...)):
    return _file(costing.cost_sheet(sel))


# ------------------------------------------------------------------ the fabric list
@app.post("/api/save")
@app.post("/api/list/add")
def list_add(sel: dict = Body(...), request: Request = None):
    return fabric_list.list_add(sel, who=_who(request))


@app.post("/api/list/upload")
async def list_upload(request: Request, file: UploadFile = File(...)):
    data = await file.read()
    return await asyncio.to_thread(fabric_list.list_upload, file.filename, data, _who(request))


@app.post("/api/list")
def list_view(options: dict = Body(default={})):
    return fabric_list.list_view(options)


@app.post("/api/list/remove")
def list_remove(payload: dict = Body(...), request: Request = None):
    return fabric_list.list_remove(payload, who=_who(request))


@app.post("/api/list/download")
def list_download(options: dict = Body(default={})):
    return _file(fabric_list.list_download(options))


@app.delete("/api/saved/{saved_id}")
def delete_saved(saved_id: str, request: Request = None):
    return fabric_list.delete_saved(saved_id, who=_who(request))


# ------------------------------------------------------------------ negotiation pack and Right cost
@app.post("/api/pack")
def pack(options: dict = Body(default={})):
    return pack_rules.pack(options)


@app.get("/api/costs")
def costs():
    return rightcost.costs()


@app.post("/api/costs/download")
def costs_download(payload: dict = Body(default={})):
    return _file(rightcost.costs_download(payload))


# ------------------------------------------------------------------ mill cost sheets
@app.get("/api/costsheet/template")
def costsheet_template():
    return _file(costsheets.costsheet_template())


@app.get("/api/costsheet")
def costsheet_view():
    return Response(json.dumps(costsheets.costsheet_view(), default=_plain), media_type="application/json")


@app.post("/api/costsheet/upload")
async def costsheet_upload(file: UploadFile = File(...)):
    data = await file.read()
    return await asyncio.to_thread(costsheets.costsheet_upload, file.filename, data)


@app.post("/api/costsheet/remove")
def costsheet_remove(payload: dict = Body(...)):
    return costsheets.costsheet_remove(payload)


@app.post("/api/costsheet/apply")
def costsheet_apply(payload: dict = Body(...), request: Request = None):
    return costsheets.costsheet_apply(payload, who=_who(request))


# ------------------------------------------------------------------ negotiation tracker
@app.get("/api/negotiations")
def negotiations():
    return tracker.negotiations()


@app.post("/api/negotiations/event")
def negotiation_event(payload: dict = Body(...), request: Request = None):
    return tracker.negotiation_event(payload, who=_who(request))


@app.post("/api/negotiations/remove")
def negotiation_remove(payload: dict = Body(...), request: Request = None):
    return tracker.negotiation_remove(payload, who=_who(request))


@app.get("/api/negotiations/summary")
def negotiations_summary():
    return tracker.negotiations_summary()


# ------------------------------------------------------------------ supplier page, quote alerts, drafts
@app.get("/api/suppliers")
def suppliers():
    return supplier_rules.suppliers()


@app.get("/api/supplier")
def supplier(mill: str):
    return supplier_rules.supplier(mill)


@app.get("/api/alerts")
def alerts_view():
    return alerts.alerts()


@app.post("/api/alerts/seen")
def alerts_seen(payload: dict = Body(...), request: Request = None):
    return alerts.alerts_seen(payload, who=_who(request))


@app.post("/api/draft")
def draft_message(payload: dict = Body(...)):
    return drafts.draft_message(payload)


# ------------------------------------------------------------------ dashboard, tables, pilot
@app.get("/api/dashboard")
def dashboard_view():
    return dashboard.dashboard()


@app.get("/api/insights")
def insights():
    return dashboard.insights()


@app.get("/api/table/{sheet}")
def table(sheet: str):
    return dashboard.table(sheet)


@app.get("/api/cotton")
def cotton():
    return dashboard.cotton()


@app.get("/api/pilot")
def pilot():
    return dashboard.pilot()


# ------------------------------------------------------------------ bulk costing, editing the rate master, yarn price intake
@app.get("/api/template")
def template():
    return _file(rates.template())


@app.post("/api/bulk")
async def bulk(file: UploadFile = File(...)):
    data = await file.read()
    return await asyncio.to_thread(rates.bulk, file.filename, data)


@app.post("/api/bulk-download")
def bulk_download(payload: dict = Body(...)):
    return _file(rates.bulk_download(payload))


@app.put("/api/table/{sheet}")
def save_table(sheet: str, payload: dict = Body(...), request: Request = None):
    return rates.save_table(sheet, payload, who=_who(request))


@app.post("/api/cotton")
def add_cotton(payload: dict = Body(...), request: Request = None):
    return rates.add_cotton(payload, who=_who(request))


@app.post("/api/intake/file")
async def intake_file(file: UploadFile = File(...)):
    data = await file.read()
    return await asyncio.to_thread(rates.intake_file, file.filename, data)


@app.post("/api/intake/link")
def intake_link(payload: dict = Body(...)):
    return rates.intake_link(payload)


@app.post("/api/intake/api")
def intake_api(payload: dict = Body(...)):
    return rates.intake_api(payload)


@app.post("/api/intake/map")
def intake_map(payload: dict = Body(...)):
    return rates.intake_map(payload)


@app.post("/api/intake/add")
def intake_add(payload: dict = Body(...), request: Request = None):
    return rates.intake_add(payload, who=_who(request))


# ------------------------------------------------------------------ stage 3: users, roles and permissions (rules/access.py)
@app.get("/api/me")
def me(request: Request):
    return access.me(request.headers)


@app.get("/api/users")
def users_view(request: Request):
    return access.users_view(request.headers)


@app.post("/api/users/add")
def users_add(payload: dict = Body(...), request: Request = None):
    return access.add_person(payload, request.headers)


@app.post("/api/users/change")
def users_change(payload: dict = Body(...), request: Request = None):
    return access.change_person(payload, request.headers)


@app.post("/api/users/permissions")
def users_permissions(payload: dict = Body(...), request: Request = None):
    return access.set_permissions(payload, request.headers)



# ------------------------------------------------------------------ the front end
class FreshFiles(StaticFiles):
    """Static files the browser must check before reusing, so a new version shows without a hard refresh."""
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


def _page(file, assets):
    # the script and stylesheet addresses carry the time they were last changed: a new deploy is a new address
    html = open(os.path.join(WEB, file), encoding="utf8").read()
    for name in assets:
        html = html.replace(f'"{name}"', f'"{name}?v={int(os.path.getmtime(os.path.join(WEB, name)))}"')
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    """The app: one shell (left rail, Right cost, the "+" popup) with every page in it; each page is a file in web/pages/."""
    pages = sorted("pages/" + f for f in os.listdir(os.path.join(WEB, "pages")) if f.endswith((".js", ".css")))
    return _page("rightcost.html", ("rightcost.css", "rightcost.js", "access.css", "access.js", *pages))


app.mount("/", FreshFiles(directory=WEB), name="web")

if [k for k, need in route_keys().items() if need is None]:        # check_server.py fails on this too
    print("RightPrice: addresses with no permission assigned (refused to everyone while permissions are on): "
          + ", ".join(k for k, need in route_keys().items() if need is None), file=sys.stderr)
