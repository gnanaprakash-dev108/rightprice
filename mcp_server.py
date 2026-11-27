"""RightPrice as an MCP server, so an AI assistant (Claude Desktop, for one) can use it.

Two ways in, the same tools:
- On the web app at /mcp (streamable HTTP). Off unless the app setting RIGHTPRICE_MCP_TOKEN is set (24 characters or
  more); every request must carry "Authorization: Bearer <that token>". server.py does the token check and the mount.
- On a laptop: `python mcp_server.py` (stdio), working on that machine's own data folder.

The tools call the same rule functions the screens' addresses call (rules/), so an assistant sees the buyer's figures,
never a second version, and every change it makes goes through the same checks and refusals as on the screen.

GP's decision, 27 Nov 2026: "if I ask something through the MCP connector it should execute everything including the
admin role". The token is an admin key: its fixed role, "AI assistant" (rules/access.py ASSISTANT_ALLOWED), holds the
Admin role's permissions. So there is a tool for every change an Admin can make in the app: rate tables, cotton prices,
Bring in prices, dated yarn rates (stage 5), uploads to the fabric list and removing its rows, mill cost sheets and their
drafts, quote alerts seen, tracker steps, drafts to mills, and users and roles. Every change is recorded as "AI assistant" where the screens record
the signed-in person (rate versions, list rows added or removed, cost sheet rows, alerts seen, tracker steps, the users'
change record). Every tool that changes shared data is marked as writing and destructive, so a client asks the person
before it runs, and its description says what it changes and that the person must confirm. A tool that changes a rate
says the rule that holds for it: only when the person explicitly asks for that change, saying the old and new figure first.

Adding a tool for a new address (a later stage's upload, merge or dated rate), in four steps:
1. The address is in rules/access.py ROUTES with its permission (check_server.py fails until it is).
2. Here, a function that calls the rule function the web route calls, with the same payload, passing who=ASSISTANT
   where the route passes the signed-in person (`_who(request)`). Decorate it @tool(mirrors="POST /api/<address>")
   and add writes=True if it changes anything. A file the person gives comes as base64 with its name: _file_bytes().
   A refusal (rules.common.Refused) comes back to the assistant as {"error": <its words>} by itself.
3. Its docstring says what it changes, for whom, and that the person must confirm first, as the others do.
4. Add a line for it in check_server.py's assistant section (assistant_checks): call it through /mcp and compare what
   it stored with what the web route stores. check_server.py fails while an address that needs an action permission
   (do:...) has no tool mirroring it, unless NOT_MIRRORED below says why.
"""
import base64
import datetime as dt
import functools
import hmac
import math
import os
import re

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

TOKEN_ENV = "RIGHTPRICE_MCP_TOKEN"
ASSISTANT = "AI assistant"          # how every change made through these tools is recorded (rules/access.py ASSISTANT)
MAX_FILE_MB = 25
# rule 2 (never change a rate unless GP asks), as every tool that changes the rate master says it
RATE_RULE = ("RULE: change a rate only when the person has explicitly asked for this change. Before calling, tell them each "
             "figure you will change, the old figure and the new one, and get their yes. Never change a rate to make a costing "
             "match a price, and never on your own initiative.")

mcp = MCPServer(
    "RightPrice", version="2",
    instructions=(
        "RightPrice works out what a woven fabric should cost ex-mill, in rupees per metre, and compares it with a mill's "
        "quote or a purchase-order price, to prepare a fabric buyer for negotiation with the mill. Money is in Indian rupees; "
        "quantities in metres. Verdicts: 'Push' = priced above the usual range for that fabric type; 'Fair' = inside it; "
        "'Below' = under it; 'Ask break-up' = the tool is unsure of this fabric (placeholder rates or a poorly fitted type), "
        "so do not quote a target on it ('Ask break-up, above range' = it also looks high: ask for the break-up); 'Check quote' = more than "
        "30% under should-cost, probably a mistake; 'Not costed' / 'No price' = nothing to judge yet. "
        "TWO KINDS OF PRICE: a fabric-list row carries the price on the mill's sheet; the negotiation tracker may hold a newer price "
        "(the mill's latest, our counter, or the agreed price). fabric_brief and supplier_summary follow the tracker and are the ones to "
        "answer from for 'where do we stand' and 'how much is at stake with this mill'. find_fabrics and negotiation_pack show the sheet's "
        "price and say, per row, what the tracker holds: never quote their rupee totals for a fabric the tracker has moved or agreed. "
        "A fabric that repeats another order (repeats_order_of) is the same order: do not count it twice. "
        "Never net savings against overcharges. Rates marked Placeholder have no data behind them: say so when a figure rests "
        "on them. Use find_fabrics to get a fabric's key before fabric_brief, tracker_steps or record_tracker_step. "
        "THIS CONNECTION HOLDS AN ADMIN'S PERMISSIONS: it can change rates, the fabric list, mill cost sheets, alerts, the tracker "
        "and who may use RightPrice, for everyone. Every tool that changes something is marked as such; before calling one, tell the "
        "person exactly what will change and get their yes. NEVER CHANGE A RATE (edit_rate_table, add_cotton_price, intake_add_rows, "
        "apply_cost_sheet_drafts, and the dated yarn rates: add_dated_rate, remove_dated_rate, load_market_dated_rates, "
        "intake_add_dated_rates) unless the person has explicitly asked for that change, and state the old and the new figure first; "
        "never change a rate to make a costing match a price. Every change is recorded as \"AI assistant\"."))


MIRRORS = {}        # each tool and the screen's address it mirrors: its permission is that address's (rules/access.py)
# the addresses that need an action permission (do:...) and have no tool of their own here, and why. check_server.py
# fails on any other such address without a tool, so a later stage's new action reaches the assistant too.
NOT_MIRRORED = {
    "POST /api/save": "the earlier name of POST /api/list/add, which add_fabric_to_list mirrors",
    "DELETE /api/saved/{saved_id}": "removes one list row, as POST /api/list/remove does (remove_fabric_list_rows)",
    "GET /classic": "the earlier screens (Streamlit) in a browser; what they change, the rate tables, edit_rate_table changes",
    "* /classic/{path:path}": "the earlier screens' own requests (Streamlit), for a browser only",
    "WS /classic/{path:path}": "the earlier screens' web socket (Streamlit), for a browser only",
}


def _plain(o):
    """An answer as plain JSON values: numbers from the rate master arrive as numpy types (an int64 would reach the
    assistant as text), a missing figure as NaN (not JSON)."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [_plain(v) for v in o]
    if isinstance(o, (dt.datetime, dt.date)) or type(o).__name__ == "Timestamp":
        return o.isoformat()
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def _guarded(f, *args, **kwargs):
    """Run a tool: a refusal from the rules, or a store that cannot be reached just now, comes back as its words."""
    import store
    from rules import common
    try:
        return _plain(f(*args, **kwargs))
    except common.Refused as e:
        return {"error": e.detail}
    except store.StoreUnavailable as e:
        return {"error": str(e)}


def tool(*, mirrors, writes=False, destructive=None, outside=False):
    """Register a tool. The app's functions are ordinary blocking ones (the first Right cost answer after a restart takes
    about 20 seconds), so each runs in a worker thread and the web app stays responsive meanwhile. `mirrors` names the
    address of the screens the tool does the work of ("POST /api/negotiations/event"): before it runs, the AI assistant's
    fixed role must hold that address's permission (rules/access.py assistant_refusal), so a tool cannot do more than its
    address allows. A tool that `writes` is marked so (not read-only, and destructive unless said otherwise), so a client
    asks the person before it runs; `outside` marks a tool that reaches beyond RightPrice (a web page, Claude's API)."""
    def register(f):
        MIRRORS[f.__name__] = mirrors
        f.__doc__ = (f.__doc__ or "").replace("[RATE RULE]", RATE_RULE)

        @functools.wraps(f)
        async def run(*args, **kwargs):
            from rules import access
            refused = access.assistant_refusal(mirrors)
            if refused:
                return {"error": refused}
            return await anyio.to_thread.run_sync(functools.partial(_guarded, f, *args, **kwargs))
        return mcp.tool(annotations=ToolAnnotations(read_only_hint=not writes, destructive_hint=writes if destructive is None else destructive,
                                                    open_world_hint=outside))(run)
    return register


def token():
    """The token the web endpoint asks for, or None when it is switched off (unset, or too short to be a secret)."""
    t = os.environ.get(TOKEN_ENV, "").strip()
    return t if len(t) >= 24 else None


def allowed(header):
    """True when the Authorization header carries the token. Constant-time, so the token cannot be guessed by timing."""
    t = token()
    got = header[7:].strip() if isinstance(header, str) and header[:7].lower() == "bearer " else ""
    return bool(t) and bool(got) and hmac.compare_digest(got.encode(), t.encode())


class _Rules:
    """The business rules the tools use (rules/), and the costing engine. The same functions the screens' requests call."""

    def __init__(self):
        import masters
        from rules import alerts, common, costing, mills, pack, rightcost, supplier, tracker
        from rules import costsheets, dashboard, drafts, fabric_list, rates
        self.masters, self.alerts, self.common, self.costing, self.mills = masters, alerts, common, costing, mills
        self.pack, self.rightcost, self.supplier, self.tracker = pack, rightcost, supplier, tracker
        self.costsheets, self.dashboard, self.drafts, self.fabric_list, self.rates = costsheets, dashboard, drafts, fabric_list, rates
        self.NEGO_KINDS = tracker.NEGO_KINDS


@functools.cache
def _s():
    return _Rules()         # late: the tools run inside the web app, or load the rules once for stdio


def _fail(e):
    """A refusal from the app, as words for the assistant to pass on."""
    return {"error": str(getattr(e, "detail", None) or e)}


def _r2(v):
    return None if v is None else round(float(v), 2)


def _track(key):
    """What the tracker holds on a fabric, in a few words an assistant cannot misread."""
    s = _s()
    rec = s.tracker._negos().get(key)
    if not rec or not rec.get("events"):
        return None
    m = s.tracker.nego_summary(rec)
    return {"status": m["status"], "mill_latest_per_m": m["latest"], "our_counter_per_m": m["counter"], "agreed_per_m": m["agreed"],
            "note": "agreed: closed, nothing left to push" if m["status"] == "Agreed" else "open: the price on this row may be out of date; use fabric_brief"}


def _row(r):
    key = f"{r['source']}|{r.get('id') or r['code']}"
    return {"key": key, "source": r["source"], "code": r["code"], "description": r.get("description"),
            "supplier": r.get("supplier"), "route": r.get("route"), "weave": r.get("weave"), "should_cost_per_m": _r2(r.get("should")),
            "price_per_m": _r2(r.get("price")), "price_is": "paid (purchase order)" if r["source"] == "Purchase orders" else "quoted on the mill's sheet (fabric list)",
            "above_should_cost_pct": _r2(r.get("gap_pct")), "metres": r.get("metres"), "verdict_on_that_price": r.get("band"),
            "rupees_above_should_cost": r.get("excess"), "placeholder_rates_used": r.get("placeholders"), "repeats_order_of": r.get("duplicate_of"),
            "tracker": _track(key)}


def _find(key):
    return next((r for r in _s().rightcost.costs()["rows"] if f"{r['source']}|{r.get('id') or r['code']}" == key), None)


def _fields():
    s = _s()
    L = s.masters.lists(s.common.get_masters())
    typed = ["Fabric code", "Description", "Supplier", "Content", "EPI", "PPI", "Finished width (in)", "Reed space (in)", "Quoted price (Rs/m)", "Order quantity (m)"]
    fields = {name: {"choose_from": list(L[lst])[:400] if lst in L else None, "required": bool(req)} for name, lst, req in s.masters.TEMPLATE_COLUMNS}
    for t in typed:
        fields.setdefault(t, {"choose_from": None, "required": False})
    return fields


@tool(mirrors="GET /api/meta")
def list_choices() -> dict:
    """Every field RightPrice accepts when costing a fabric, with the values to choose from (choose_from is null for a
    field that is typed: a number or free text). Call this before cost_fabric and use field names and values exactly."""
    s = _s()
    return {"fields": _fields(), "example": {k: v for k, v in s.masters.EXAMPLE_ROW.items()},
            "note": "A field left out takes the rate master's default (for example medium shade, order size 3,000 m and above). "
                    "cost_fabric refuses a field name it does not know, so a misspelt field cannot be silently ignored."}


@tool(mirrors="POST /api/cost")
def cost_fabric(choices: dict) -> dict:
    """Work out the should-cost of one fabric, ex-mill, in rupees per metre and per kilo, from its construction.
    `choices` uses the field names and values of list_choices (see its example). Add "Quoted price (Rs/m)" and
    "Order quantity (m)" to get the negotiation brief as well. Nothing is saved."""
    s = _s()
    known = _fields()
    words = _check_choices(choices)
    if words:
        return {"error": words}
    try:
        out = s.costing.cost(dict(choices))
    except Exception as e:
        return _fail(e)
    b = out.get("brief")
    res = {"should_cost_per_m": _r2(out["total_per_m"]), "should_cost_per_kg": _r2(out["per_kg"]), "gsm": _r2(out.get("gsm")),
           "cost_groups_rs_per_m": {x["name"]: _r2(x["amount"]) for x in out.get("buckets", [])},
           "placeholder_rates_used": out.get("placeholders") or [], "warnings": out.get("warnings") or [],
           "costed_on": dict(choices), "fields_left_to_default": [k for k, f in known.items() if f["choose_from"] and k not in choices]}
    if b:
        res["brief"] = _brief(b)
    return res


def _brief(b, summ=None):
    out = _brief0(b)
    if summ and summ["status"] == "Agreed":
        out["verdict"] = {"Push": "Agreed above the usual range", "Fair": "Agreed in the usual range", "Below": "Agreed below the usual range",
                          "Ask break-up": "Agreed; the tool is unsure of this fabric"}.get(out["verdict"], out["verdict"])
        out.update(open_at_per_m=None, aim_for_per_m=None, advice="Agreed in the tracker: closed. The verdict says where the agreed price sits against the usual range; there is nothing left to open or aim for.")
    elif summ and summ["status"] == "Open" and b["stance"] == "fair":
        c = summ["counter"]
        out["advice"] = ("The mill's price is now inside the usual range: close it" + (f" at the mill's Rs {b['quote']:,.2f}, which is at or below our counter of Rs {c:,.2f}." if c is not None and b["quote"] <= c + 0.005
                         else f" at or near our counter of Rs {c:,.2f}." if c is not None else "."))
    elif summ and summ["counter"] is not None and b["stance"] == "push":
        c = summ["counter"]
        out.update(open_at_per_m=None, our_counter_per_m=c, advice=f"We have countered at Rs {c:,.2f}: do not open above it." + (
            f" Aim for Rs {c:,.2f} to Rs {b['settle_up_to']:,.2f}." if c <= b["settle_up_to"] else f" That counter is above the top of the usual range (Rs {b['settle_up_to']:,.2f})."))
    return out


def _brief0(b):
    stance = "Check quote" if b["implausible"] else {"push": "Push", "fair": "Fair", "below": "Below", "ask": "Ask break-up"}[b["stance"]]
    return {"verdict": stance, "price_per_m": b["quote"], "should_cost_per_m": b["should"], "price_above_should_cost_per_m": b["gap"],
            "usual_range_per_m": [b["lower"], b["settle_up_to"]], "why_this_range": b["band"]["why"],
            "open_at_per_m": b["open_at"] if b["stance"] == "push" else None, "aim_for_per_m": b["settle_up_to"] if b["stance"] == "push" else None,
            "why_no_target": b["weak"], "caveats": b["caveats"], "quantity_m": b["quantity"],
            "rupees_above_should_cost_on_the_quantity": b["at_stake"]}


@tool(mirrors="GET /api/costs")
def find_fabrics(search: str = "", mill: str = "", verdict: str = "", source: str = "", limit: int = 20) -> dict:
    """Find costings in Right cost: purchase-order fabrics (price paid) and fabric-list rows (price quoted).
    search: words in the fabric code, description or supplier. mill: a mill's name, any spelling. verdict: Push, Fair,
    Below, Ask break-up, Check quote. source: "Purchase orders" or "Fabric list". Sorted by rupees above should-cost,
    largest first. Returns each fabric's key, needed by the other tools."""
    s = _s()
    d = s.rightcost.costs()
    rows, words = d["rows"], [w for w in search.lower().split() if w]
    if mill:
        rows = [r for r in rows if r["mill"] == s.mills.mill_key(mill)]
    if source:
        rows = [r for r in rows if r["source"].lower() == source.lower()]
    notes = []
    if mill and not rows:
        notes.append(f"No mill matches '{mill}'. Mills are matched by name whatever the spelling of Ltd or Limited, but not by a misspelt name.")
    if source and source.lower() not in ("purchase orders", "fabric list"):
        notes.append('source must be "Purchase orders" or "Fabric list".')
    if verdict:
        rows = [r for r in rows if str(r.get("band") or "").lower().startswith(verdict.lower())]
        if not any(v.lower().startswith(verdict.lower()) for v in ("Push", "Fair", "Below", "Ask break-up", "Ask break-up, above range", "Check quote", "Not costed", "No price")):
            notes.append("verdict must be one of Push, Fair, Below, Ask break-up (both kinds), Ask break-up, above range, Check quote, Not costed, No price.")
    if words:
        rows = [r for r in rows if all(w in " ".join(str(r.get(k) or "") for k in ("code", "description", "supplier")).lower() for w in words)]
    rows = sorted(rows, key=lambda r: -(r.get("excess") or 0))
    n = max(1, min(int(limit or 20), 100))
    return {"found": len(rows), "shown": min(n, len(rows)), "verdicts_ready": d["ready"],
            "note": " ".join(notes + ([] if d["ready"] else ["The purchase-order verdicts are still being worked out (about 20 seconds after a restart): ask again shortly."])) or None,
            "reading_the_figures": "price_per_m and verdict_on_that_price are the row's own price (the sheet, or the price paid). `tracker` says what has "
                                   "happened since: for a row with a tracker entry, answer from fabric_brief, not from this row. Rows with repeats_order_of are the same order as another row.",
            "fabrics": [_row(r) for r in rows[:n]]}


@tool(mirrors="GET /api/costs")
def fabric_brief(key: str) -> dict:
    """The negotiation brief for one fabric (key from find_fabrics): verdict, should-cost, usual range, where to open and
    what to aim for, why the tool is unsure if it is, the quote alerts on it, and where its negotiation stands. The brief
    is on the mill's latest price in the tracker (or the agreed price) when there is one, else the price on the row."""
    s = _s()
    r = _find(key)
    if r is None:
        return {"error": "No fabric with that key. Use find_fabrics to get the key."}
    out = {"fabric": _row(r)}
    rec = s.tracker._negos().get(key)
    summ = s.tracker.nego_summary(rec) if rec and rec.get("events") else None
    price = (summ["agreed"] if summ and summ["status"] == "Agreed" else summ["latest"] if summ else None) or r.get("price")
    if r.get("problems"):
        out["not_costed_because"] = r["problems"]
    elif price and r.get("choices"):
        try:
            m = s.common.get_masters()
            # a purchase order on the yarn rates of its order month, a quote on today's (stage 5, GP's decision)
            res = s.masters.cost(dict(r["choices"], **{"Quoted price (Rs/m)": price}), m, on=(r.get("rates") or {}).get("month"))
            b = s.costing.brief(res, m, r.get("metres"), (), r["choices"])
            out["rates_are"] = (r.get("rates") or {}).get("note") or "today's rates"
            if b:
                out["brief"] = _brief(b, summ)
                out["brief_is_on"] = "the agreed price in the tracker" if summ and summ["status"] == "Agreed" else "the mill's latest price in the tracker" if summ and summ["latest"] else "the price on the row"
        except Exception as e:
            out["brief_error"] = str(e)
    else:
        out["brief"] = None
        out["why_no_brief"] = "No price on this row and no mill price in the tracker."
    if summ:
        out["negotiation"] = _nego(rec, summ)
    if r["source"] == "Fabric list":
        a = s.alerts.alerts()["all"].get(r.get("id"))
        if a:
            out["quote_alerts"] = {"state": a["state"], "flags": [f["text"] for f in a["flags"]],
                                   "note": "These flags are on the price of the mill's sheet" + (f" (Rs {r['price']:,.2f}); the tracker has since moved to Rs {price:,.2f}, so read them as history." if r.get("price") and abs(price - r["price"]) >= 0.005 else ".")}
    if r.get("duplicate_of"):
        twin = next((x for x in s.rightcost.costs()["rows"] if x["source"] == r["source"] and x["code"] == r["duplicate_of"] and not x.get("duplicate_of")), None)
        tk = _track(f"{twin['source']}|{twin.get('id') or twin['code']}") if twin else None
        out["repeats_order_of"] = {"code": r["duplicate_of"], "key": f"{twin['source']}|{twin.get('id') or twin['code']}" if twin else None, "tracker": tk,
                                   "note": "This row is the same order as that one: answer from that fabric's brief and negotiation, and do not count this row's rupees as well."}
        if out.get("brief"):
            out["brief"].update(open_at_per_m=None, aim_for_per_m=None, advice=f"Same order as {r['duplicate_of']}" + (f", which is {tk['status'].lower()} in the tracker" + (f" at Rs {tk['agreed_per_m']:,.2f}" if tk.get("agreed_per_m") else "") if tk else "") + ": use that fabric's brief.")
    if out.get("brief") and r.get("band") and out["brief"]["verdict"] != r["band"]:
        out["fabric"]["note"] = "verdict_on_that_price is on the row's own price; the brief below is on the tracker's price and is the one to answer from."
    return out


def _nego(rec, summ):
    return {"status": summ["status"], "first_mill_quote": summ["first"], "mill_latest": summ["latest"], "our_counter": summ["counter"],
            "agreed": summ["agreed"], "won_per_m_against_first_quote": summ["won_per_m"], "won_rupees": summ["won"] if summ["counted"] else None,
            "counted_as_won": summ["counted"], "to_check": summ["warnings"],
            "steps": [{"date": e["date"], "kind": e["kind"], "price_per_m": e["price"], "note": e.get("note") or "", "by": e.get("by") or "", "id": e["id"]}
                      for e in _s().tracker._nego_order(rec.get("events", []))]}


@tool(mirrors="GET /api/supplier")
def supplier_summary(mill: str) -> dict:
    """One mill, for the meeting with it: what was bought and what is quoted with verdict counts, the rupees above the
    usual range (counted only where the tool is sure), its sheets' sums that are off, negotiations and what was won,
    and the questions to take to the meeting. mill: the mill's name in any spelling."""
    s = _s()
    try:
        d = s.supplier.supplier(mill)
    except Exception as e:
        return _fail(e)
    side = lambda x: {k: v for k, v in x.items() if k not in ("rows",)} | {"largest": [
        {"code": r["code"], "price_per_m": _r2(r["price"]), "should_cost_per_m": _r2(r["should"]), "metres": r["metres"], "verdict": r["band"],
         "rupees_above_range": r["above_range"]} for r in x["rows"][:15]]}
    return {"mill": d["name"], "also_written": d["names"][1:], "as_of": d["today"], "verdicts_ready": d["ready"],
            "bought": side(d["bought"]), "quoted": side(d["quoted"]), "sums_off": d["sums"],
            "negotiations": d["tracker"], "questions": d["questions"],
            "reading_the_figures": "This follows the tracker and is the tool to answer 'how much is at stake with this mill'. above_range = rupees above the top of the "
                                   "usual range on Push fabrics still to settle (the figure to push on). push_excess = rupees above should-cost on those same fabrics. "
                                   "unsure_high / unsure_high_excess = fabrics that look high but the tool is unsure of: ask for their break-up, never push a figure. "
                                   "below_saving, fair_excess, check_excess are shown apart and never netted. agreed / agreed_above_range = closed in the tracker. "
                                   "moved = open fabrics judged on a newer mill price than the sheet's. negotiations.won is ALREADY NET of negotiations.lost (lost is shown so a loss inside a gain is not hidden): "
                                   "report 'won X, after Y lost', never subtract again. sums_off compares the mill's own build-up with the price it asks now. Codes can repeat across rows: "
                                   "use find_fabrics for keys. Purchases are already paid: use them for the next order of the same cloth."}


@tool(mirrors="POST /api/pack")
def negotiation_pack(mill: str = "", keys: list[str] | None = None) -> dict:
    """The negotiation pack for a mill's quoted fabrics (fabric-list rows): totals, the rows to lead with, every row with
    its verdict, open and aim prices, rupees at stake, the mill's own sums done again, and the questions per row.
    Give a mill name, or the keys of fabric-list rows from find_fabrics."""
    s = _s()
    rows = [r for r in s.rightcost.costs()["rows"] if r["source"] == "Fabric list"]
    want = set(keys or [])
    ids = [r["id"] for r in rows if (f"Fabric list|{r['id']}" in want if want else (mill and r["mill"] == s.mills.mill_key(mill)))]
    if not ids:
        return {"error": "No fabric-list rows for that mill or those keys. The pack is made from quoted fabrics (the fabric list), not purchase orders."}
    try:
        p = s.pack.pack({"ids": ids})
    except Exception as e:
        return _fail(e)
    words = {"push": "Push", "fair": "Fair", "below": "Below", "ask": "Ask break-up", "check": "Check quote"}
    rows_out = []
    for r in p["rows"]:
        key = f"Fabric list|{r['id']}"
        rows_out.append({"key": key, "code": r["code"], "description": r["description"], "quantity_m": r["quantity"], "sheet_price_per_m": r["quote"],
                         "should_cost_per_m": r["should"], "verdict_on_sheet_price": words.get(r["stance"], r["stance"]), "top_of_usual_range_per_m": r["upper"],
                         "open_at_per_m": r["open_at"] if r["stance"] == "push" else None,
                         "rupees_above_should_cost": r["at_stake"], "rupees_above_range": (r["above_range_money"] if r["quantity"] else None) if r["stance"] == "push" else None,
                         "sheet_sums_off": r["sums"], "mills_own_build_up_per_m": r["own_price"], "repeats_order_of": r["duplicate_of"],
                         "why_no_target": r["weak"], "caveats": r["caveats"], "questions": r["questions"], "tracker": _track(key)})
    moved = [x["code"] for x in rows_out if x["tracker"]]
    t = p["totals"]
    return {"on": "THE PRICES OF THE MILL'S SHEET, as uploaded. " + (f"The tracker holds newer prices or agreements for: {', '.join(moved)}; for those, and for the mill's "
                  "total still at stake, use supplier_summary and fabric_brief." if moved else "No fabric here has a tracker entry yet."),
            "totals_on_sheet_prices": {"rows": t["rows"], "costed": t["costed"], "not_costed": t["not_costed"], "metres": t["metres"],
                                       "push_rows": t["count"]["push"], "rupees_above_range_on_push_rows": t["push_above_range"],
                                       "rupees_above_should_cost_on_push_and_fair_rows": t["counted_stake"],
                                       "rupees_on_rows_the_tool_is_unsure_of_not_counted": t["flagged_stake"], "rupees_below_should_cost_on_below_rows_not_netted": t["savings"],
                                       "rows_with_sums_off": t["sums_off"], "repeated_rows_counted_once": t["duplicates"]},
            "lead_with": p["lead"], "rows": rows_out, "not_costed": p["not_costed"]}


@tool(mirrors="GET /api/negotiations")
def tracker_steps(key: str) -> dict:
    """The negotiation recorded on one fabric (key from find_fabrics): each step with the mill (with its id, for
    remove_tracker_step, and who recorded it) and where it stands."""
    s = _s()
    if _find(key) is None:
        return {"error": "No fabric with that key. Use find_fabrics to get the key."}
    rec = s.tracker._negos().get(key)
    if not rec or not rec.get("events"):
        return {"status": "Not tracked", "steps": [], "kinds_you_can_record": s.NEGO_KINDS}
    return dict(_nego(rec, s.tracker.nego_summary(rec)), kinds_you_can_record=s.NEGO_KINDS)


@tool(mirrors="POST /api/negotiations/event", writes=True)
def record_tracker_step(key: str, kind: str, price_per_m: float, date: str = "", note: str = "") -> dict:
    """Record one negotiation step on a fabric. THIS CHANGES DATA EVERYONE SHARES: confirm with the person first.
    key: from find_fabrics. kind: exactly one of "Mill's quote", "Our counter", "Mill's revised quote", "Agreed".
    price_per_m: rupees per metre. date: YYYY-MM-DD (today if empty).
    Order matters: what was won is measured from the mill's FIRST quote, so record "Mill's quote" (usually the price on the
    mill's sheet) before a revised quote or an agreement; this tool refuses a revised quote or an agreement with no quote
    before it and tells you the sheet's price. It also refuses the same step twice, a counter on a fabric already agreed,
    a price outside Rs 1 to 50,000, a date in the future or over two years back, and a row that repeats another order.
    The answer's `warnings_on_this_step` are things that look wrong about what was just recorded (a price far from
    should-cost or the first quote, a counter above the mill's price): read them to the person; if the step was a mistake,
    undo it with remove_my_tracker_step."""
    s = _s()
    r = _find(key)
    if r is None:
        return {"error": "No fabric with that key. Use find_fabrics to get the key."}
    if kind not in s.NEGO_KINDS:
        return {"error": f"kind must be exactly one of: {', '.join(s.NEGO_KINDS)}. Nothing was recorded."}
    rec0 = s.tracker._negos().get(key) or {}
    ev0 = s.tracker._nego_order(rec0.get("events", []))
    before = s.tracker.nego_summary(rec0) if ev0 else None
    try:
        p = round(float(price_per_m), 2)
    except (TypeError, ValueError):
        return {"error": "price_per_m must be a number of rupees per metre. Nothing was recorded."}
    same = [e for e in ev0 if e["kind"] == kind and abs(e["price"] - p) < 0.005]
    if same:
        return {"error": f"That step is already recorded ({kind} Rs {p:,.2f}, dated {same[-1]['date']}). Nothing was recorded again."}
    quotes0 = [e for e in ev0 if e["kind"] in ("Mill's quote", "Mill's revised quote")]
    if date and quotes0 and date < quotes0[0]["date"]:
        return {"error": f"That date ({date}) is before the mill's first quote on this fabric (Rs {quotes0[0]['price']:,.2f}, dated {quotes0[0]['date']}). What is won is measured from the first "
                         "quote, so a step cannot be slipped in before it here. If the first quote itself is wrong, it is corrected on the fabric's Negotiation tab. Nothing was recorded."}
    if date and not quotes0 and kind == "Our counter":
        pass
    if kind == "Agreed" and before and before["status"] == "Agreed":
        return {"error": f"This fabric is already agreed at Rs {before['agreed']:,.2f}. If the agreement has changed, the person should correct it on the fabric's Negotiation tab "
                         "(or record the mill's new quote first if the price was reopened). Nothing was recorded."}
    if kind == "Agreed" and quotes0 and p > quotes0[-1]["price"] + 0.005:
        return {"error": f"Agreed at Rs {p:,.2f} would be above the mill's latest price of Rs {quotes0[-1]['price']:,.2f}. Check the figure with the person; if the mill has "
                         "raised its price, record that as a revised quote first. Nothing was recorded."}
    if kind in ("Mill's revised quote", "Agreed") and not any(e["kind"] in ("Mill's quote", "Mill's revised quote") for e in ev0):
        sheet = f" The price on this row is Rs {r['price']:,.2f}: if that was the mill's first quote, record it as \"Mill's quote\" with its date first." if r.get("price") else ""
        return {"error": f"No mill quote is recorded on this fabric yet, and what is won is measured from the mill's first quote.{sheet} Nothing was recorded."}
    if kind == "Our counter" and before and before["status"] == "Agreed":
        return {"error": f"This fabric is agreed at Rs {before['agreed']:,.2f}. A counter would reopen it. If the mill has reopened the price, record its new quote first. Nothing was recorded."}
    try:
        rec = s.tracker.negotiation_event({"key": key, "kind": kind, "price": p, "date": date or None,
                                   "note": (str(note or "").strip()[:440] + " (recorded through the AI assistant)").strip(), "code": r["code"],
                                   "supplier": r.get("supplier"), "description": r.get("description"), "source": r["source"],
                                   "metres": r.get("metres"), "should": r.get("should"), "row_price": r.get("price")}, who=ASSISTANT)
    except Exception as e:
        return _fail(e)
    new = [w for w in rec["summary"]["warnings"] if not before or w not in before["warnings"]]
    return {"recorded": True, "warnings_on_this_step": new, "now": _nego(rec, rec["summary"]),
            "effects": "Everyone using RightPrice sees this step." + (" An agreed price also clears the fabric's quote alert and is counted in what was won." if kind == "Agreed" else "")}


@tool(mirrors="POST /api/negotiations/remove", writes=True)
def remove_my_tracker_step(key: str, kind: str, price_per_m: float, date: str = "") -> dict:
    """Undo a step THIS ASSISTANT recorded by mistake. Give the fabric's key and the kind and price of the step (and its
    date, YYYY-MM-DD, if two match). The mill's first quote cannot be removed here while later steps rest on it. THIS
    CHANGES DATA EVERYONE SHARES: confirm with the person first. The removal is kept in the fabric's Log. A step a person
    recorded is removed with remove_tracker_step, as an admin can on the fabric's Negotiation tab."""
    s = _s()
    rec = s.tracker._negos().get(key) or {}
    mine = [e for e in rec.get("events", []) if e.get("by") == ASSISTANT and e["kind"] == kind and abs(e["price"] - float(price_per_m)) < 0.005 and (not date or e["date"] == date)]
    if not mine:
        return {"error": "No step with that kind and price recorded by the assistant on this fabric. Steps a person recorded are removed on the fabric's Negotiation tab."}
    ordered = s.tracker._nego_order(rec.get("events", []))
    quotes = [e for e in ordered if e["kind"] in ("Mill's quote", "Mill's revised quote")]
    if quotes and mine[-1]["id"] == quotes[0]["id"] and len(ordered) > 1:
        return {"error": "That is the mill's first quote, and the later steps are measured from it. Remove the later steps first (those the assistant recorded), "
                         "or have the person correct it on the fabric's Negotiation tab. Nothing was removed."}
    try:
        s.tracker.negotiation_remove({"key": key, "id": mine[-1]["id"]}, who=ASSISTANT)
    except Exception as e:
        return _fail(e)
    rec = s.tracker._negos().get(key) or {}
    return {"removed": True, "removed_step": {"kind": mine[-1]["kind"], "price_per_m": mine[-1]["price"], "date": mine[-1]["date"]}, "now": _nego(rec, s.tracker.nego_summary(rec)) if rec.get("events") else {"status": "Not tracked", "steps": []}}


@tool(mirrors="GET /api/alerts")
def quote_alerts() -> dict:
    """Newly quoted fabrics that need a look before their price is accepted: above the usual range, the mill's own sums
    off, repeating an order already on the list, or far below should-cost. Newest upload first."""
    a = _s().alerts.alerts()
    return {"count": a["count"], "by_kind": {a["kinds"][k]: n for k, n in a["by_kind"].items()},
            "rupees_quoted_above_ranges": a["above_money"], "rupees_the_mills_own_sums_are_out": a["sums_money"],
            "note": "The two rupee figures largely overlap: do not add them. ALERTS ARE ON THE PRICES OF THE MILLS' SHEETS, as uploaded: where a fabric has a `tracker` entry the "
                    "mill has moved since, so its rupees here are history; use fabric_brief for where it stands. An alert clears when marked seen, or when the price is agreed.",
            "uploads": [{"mill": g["supplier"], "upload": g["upload"],
                         "fabrics": [{"key": r["key"], "code": r["code"], "flags": [f["text"] for f in r["flags"]], "tracker": _track(r["key"])} for r in g["rows"]]} for g in a["groups"]]}


# ================================================================== what an Admin can see that the tools above do not show
def _file_bytes(file_base64, file_name):
    """A file the person gave, sent as base64 (a "data:...;base64," start is allowed) with its name; or a refusal."""
    from rules.common import Refused
    if not str(file_name or "").strip():
        raise Refused(400, "Give the file's name with its ending (.xlsx, .csv, .pdf ...): the ending says how to read it. Nothing was done.")
    text = re.sub(r"\s+", "", re.sub(r"^data:[^,]*,", "", str(file_base64 or "").strip()))
    if not text:
        raise Refused(400, "No file came with this: send the file's contents as base64, with its name. Nothing was done.")
    if len(text) > MAX_FILE_MB * 1024 * 1024 * 4 // 3 + 4:
        raise Refused(400, f"That file is larger than {MAX_FILE_MB} MB. Nothing was done.")
    try:
        return base64.b64decode(text.replace("-", "+").replace("_", "/") + "=" * (-len(text) % 4), validate=True)
    except ValueError:
        raise Refused(400, "file_base64 is not base64: send the file's bytes encoded as base64. Nothing was done.")


def _id_of(key):
    """A fabric-list row's id from its key ("Fabric list|<id>", as find_fabrics and quote_alerts give it) or the id itself."""
    k = str(key or "").strip()
    return k.split("|", 1)[1] if k.startswith("Fabric list|") else k


def _rows_as_dicts(records, first=1):
    return [dict({"row": first + n}, **dict(zip(records["columns"], r))) for n, r in enumerate(records["rows"])]


@tool(mirrors="GET /api/store")
def store_status() -> dict:
    """Where RightPrice keeps its data (files, or a database) and what it holds: how many rate versions, fabric-list rows,
    tracker steps, alerts seen and mill cost sheet rows; the rate master in use (which version, saved when and by whom);
    the copying in of the files; or, when it cannot be used, the error and the advice. Never a password."""
    import store
    return store.get().describe()


@tool(mirrors="GET /api/table/{sheet}")
def rate_table(sheet: str = "", max_rows: int = 300) -> dict:
    """The rate master's tables, as Prices > Rate tables shows them. Without `sheet`: every table, what it holds, its row
    count, and whether it can be edited (edit_rate_table). With `sheet` (a name from that list, for example "Yarn_Rates",
    "Weaving_Rates", "Class_Defaults", "Settings"): its columns and rows, numbered from 1 as edit_rate_table refers to them
    (a long table shows its last `max_rows` rows; their numbers stay those of the whole table). A Basis that starts
    "Placeholder" means the rate has no data behind it: say so when a figure rests on it."""
    s = _s()
    m = s.common.get_masters()
    if not str(sheet or "").strip():
        return {"tables": [{"sheet": k, "holds": label, "rows": len(m[k]) if k in m else 0, "editable": k in s.rates.EDITABLE}
                           for k, label in s.rates.TABLES.items()],
                "note": "Cotton prices are added one at a time (add_cotton_price); Content groups are not edited here."}
    t = s.dashboard.table(sheet)
    n = max(1, min(int(max_rows or 300), 5000))
    rows = t["rows"][-n:]
    first = len(t["rows"]) - len(rows) + 1
    return {"sheet": sheet, "holds": t["label"], "editable": sheet in s.rates.EDITABLE, "columns": t["columns"],
            "rows_in_table": len(t["rows"]), "rows_shown": f"{first} to {len(t['rows'])}" if t["rows"] else "none",
            "rows": _rows_as_dicts({"columns": t["columns"], "rows": rows}, first)}


@tool(mirrors="GET /api/dashboard")
def yarn_master() -> dict:
    """The yarn master, as Prices > Yarn prices shows it: every yarn with its rate in use (Rs per kg), its date and its
    Basis, and for each cotton yarn where that rate sits against the market reference (inside, above or below the
    market's low to high); the latest cotton price; how many rates are placeholders."""
    s = _s()
    d = s.dashboard.dashboard()
    t = s.dashboard.table("Yarn_Rates")
    return {"yarns": _rows_as_dicts(t), "cotton_yarns_against_the_market": d["yarns"], "latest_cotton_price": d["cotton"],
            "placeholder_rates": d["placeholders"],
            "note": "The market reference is the table Market_Yarn (rate_table), filled by Bring in prices. A yarn's rate is changed with edit_rate_table on Yarn_Rates."}


@tool(mirrors="GET /api/insights")
def dashboard() -> dict:
    """The Dashboard's own-data panels: what was paid against what it should cost, by fabric type and by supplier (from
    the pilot's 1,696 costed purchase-order fabrics), with how far the should-cost can be leaned on for each ('firm' or
    'weak'); where the rupee goes by route; prices paid by order size; the cotton price by year; how far a yarn price move
    carries into a fabric; and what negotiation has won so far (from the tracker)."""
    s = _s()
    return {"panels": s.dashboard.insights(), "negotiation_won": s.tracker.negotiations_summary(),
            "note": "The pilot figures are purchase orders already paid, costed on today's rates. 'weak' means the gap says more about the tool than the supplier."}


@tool(mirrors="GET /api/pilot")
def pilot_results(sheet: str = "") -> dict:
    """The pilot results (Home > Pilot results): the funnel of purchase-order fabrics costed, the overall fit, the rate
    card steps and inputs, the fit by route and weave and by supplier, and the calibration drafts (proposals only: no
    rate was changed by them). sheet: one of the names returned, to get only that one."""
    p = _s().dashboard.pilot()
    names = list(p)
    if sheet:
        if sheet not in p:
            return {"error": f"No sheet '{sheet}'. The sheets are: {', '.join(names)}."}
        p = {sheet: p[sheet]}
    return {"sheets": names, "tables": {k: _rows_as_dicts(v) for k, v in p.items()},
            "note": "Sheets starting 'Draft:' are calibration proposals, not applied. The held-back test splits by fabric code, so it is optimistic."}


@tool(mirrors="GET /api/cotton")
def cotton_prices(last: int = 60) -> dict:
    """Cotton prices held in the rate master (Shankar-6, rupees per candy), oldest to newest: the last `last` of them, how
    many there are, the unit and the latest source. A price is added with add_cotton_price."""
    c = _s().dashboard.cotton()
    n = max(1, min(int(last or 60), 5000))
    return {"prices": [{"date": d, "price": p} for d, p in c["points"][-n:]], "held": len(c["points"]),
            "first_date": c["points"][0][0] if c["points"] else None, "unit": c["unit"], "latest_source": c["source"]}


@tool(mirrors="GET /api/suppliers")
def list_suppliers() -> dict:
    """Every mill bought from or quoted by, one line each (a mill written two ways is one mill), as Right cost's
    Suppliers tab shows them: fabrics bought and quoted, Push fabrics, rupees above the usual range, negotiations open and
    agreed, and what was won. The most money above the range first. supplier_summary gives one mill in full."""
    return _s().supplier.suppliers()


@tool(mirrors="POST /api/list")
def fabric_list(search: str = "", limit: int = 50, yarn_move_pct: dict | None = None) -> dict:
    """The fabric list (Bulk upload): every fabric added from Cost a fabric or an upload, newest first, each costed again
    on today's rates: its key (for remove_fabric_list_rows, mark_alerts_seen, the tracker), code, supplier, the upload it
    came in with, the price on the mill's sheet, should-cost, the gap, the verdict, why it could not be costed, the mill's
    own sums that are off, and placeholder rates used. search: words in the code, description, supplier or upload.
    yarn_move_pct: {"*": 5} (every yarn) or {"Cotton 40S": -3}: also costs each row with those yarn rates moved, to show
    what a yarn price move would do (nothing is saved)."""
    s = _s()
    v = s.fabric_list.list_view({"yarn_pct": yarn_move_pct} if yarn_move_pct else {})
    words = [w for w in str(search or "").lower().split() if w]
    out = []
    for i in v["rows"]:
        mill = i.get("mill") or {}
        code = mill.get("Fab Code") or (i.get("inputs") or {}).get("Fabric code")
        text = " ".join(str(x or "") for x in (code, i.get("description"), i.get("supplier"), i.get("upload"))).lower()
        if words and not all(w in text for w in words):
            continue
        b = i.get("brief") or {}
        row = {"key": f"Fabric list|{i['id']}", "code": code, "supplier": i.get("supplier"), "description": i.get("description"),
               "upload": i.get("upload") or "Added on screen", "added": i.get("added"), "sheet_price_per_m": s.common._num_or_none(mill.get("Ex mill price")),
               "should_cost_per_m": _r2(i.get("should_cost")), "gap_per_m": _r2(i.get("gap")),
               "gap_pct": None if i.get("gap_pct") is None else round(i["gap_pct"] * 100, 1), "quantity_m": i.get("quantity"),
               "verdict": ("Check quote" if b.get("implausible") else {"push": "Push", "fair": "Fair", "below": "Below", "ask": "Ask break-up"}.get(b.get("stance"))) if b else None,
               "rupees_above_should_cost": i.get("at_stake"), "not_costed_because": i.get("problems") or [], "notes": i.get("notes") or [],
               "mills_sums_off": i.get("sums") or [], "placeholder_rates_used": i.get("placeholders") or []}
        if yarn_move_pct:
            row["should_cost_with_yarn_moved_per_m"] = _r2(i.get("simulated"))
        out.append(row)
    n = max(1, min(int(limit or 50), 1000))
    return {"rows_on_list": len(v["rows"]), "found": len(out), "shown": min(n, len(out)), "rows": out[:n],
            "note": "The price here is the mill's sheet's; the tracker may hold a newer one (fabric_brief)."}


@tool(mirrors="GET /api/costsheet")
def mill_cost_sheets() -> dict:
    """Mill cost sheets (Prices > Mill cost sheets): every row a mill sent with its own figures, set beside the rate
    master (the should-cost on our rates, the mill's own build-up, its price), with who brought it in; and the drafts
    that follow: for a rate, the figure the mills' sheets point to beside the rate in use. A draft changes nothing until
    apply_cost_sheet_drafts, which only an explicit request from the person may trigger."""
    a = _s().costsheets.costsheet_view()
    rows = [{"id": r.get("id"), "mill": r.get("mill"), "fabric_code": r.get("code"), "upload": r.get("upload"), "added": r.get("added"),
             "by": r.get("by"), "should_cost_per_m": _r2(r.get("should")), "mills_own_build_up_per_m": _r2(r.get("own")),
             "mills_price_per_m": _r2(r.get("price")), "price_above_own_build_up_per_m": _r2(r.get("own_gap")),
             "not_read_because": r.get("problems") or [], "notes": r.get("notes") or [], "placeholder_rates_used": r.get("placeholders") or [],
             "figures": [{"column": f["column"], "unit": f["unit"], "mills_figure": f["mill"], "rate_master_now": f["now"], "rate": f["target"],
                          "ignored": bool(f.get("ignored"))} for f in r.get("figures") or []]} for r in a["rows"]]
    drafts = [{"id": d["id"], "rate": d["label"], "table": d["table"], "column": d["col"], "now": d["now"], "proposed": d["proposed"],
               "is_a_share": bool(d["pct"]), "basis_now": d["basis"], "from_mills": sorted(set(d.get("mills") or [])), "sheets": d["sheets"],
               "scope": d.get("scope"), "rows": d.get("rows")} for d in a["drafts"]]
    return {"rows": rows, "drafts": drafts, "note": "A share (is_a_share) is a fraction: 0.08 is 8%. Each draft is the middle of the mills' figures, each mill counted once."}


@tool(mirrors="POST /api/bulk")
def cost_template_file(file_base64: str, file_name: str) -> dict:
    """Cost a filled RightPrice template (Bulk upload > cost a filled template): an .xlsx with a 'Fabrics' sheet, sent as
    base64 with its name. Every row is costed on today's rates and the results come back; NOTHING IS KEPT (to add the
    fabrics to the list, use upload_to_fabric_list)."""
    s = _s()
    out = s.rates.bulk(file_name, _file_bytes(file_base64, file_name))
    rows = _rows_as_dicts(out["results"])
    return {"rows": rows[:300], "rows_costed": len(rows), "rows_refused": out["rejected"],
            "note": "A row with an Error was not costed; the error says why." + (" Only the first 300 rows are shown." if len(rows) > 300 else "")}


@tool(mirrors="GET /api/users")
def users_and_roles(record_limit: int = 50) -> dict:
    """Users and roles (under the user icon): the people let in (address, name, role, switched on or off, who added and
    changed them), the admins named in the app setting RIGHTPRICE_ADMINS, what each role may do and what an admin changed
    from the defaults, this assistant's own fixed role, and the record of changes, newest first (who, when, what it was
    and what it became). Shown only while permissions are on (the app setting RIGHTPRICE_ADMINS) and on a database."""
    from rules import access
    v = access.users_view(assistant=True)
    label = {p["key"]: p["label"] for p in v["permissions"]}
    roles = {role: {"may": [label[k] for k, g in grid.items() if g["allowed"]],
                    "differs_from_default": [f"{label[k]}: {'given' if g['allowed'] else 'taken away'}" for k, g in grid.items() if g["allowed"] != g["default"]]}
             for role, grid in v["grid"].items()}
    n = max(1, min(int(record_limit or 50), 300))
    return {"people": v["people"], "admins_named_in_the_setting": v["setting_admins"], "setting_entries_ignored": v["setting_ignored"],
            "roles": roles, "permission_keys": [{"key": p["key"], "what": p["label"], "admin_only": p["fixed"]} for p in v["permissions"]],
            "assistant": {"name": v["assistant"]["name"], "note": v["assistant"]["note"]}, "how_ticks_work": v["grid_note"],
            "change_record": v["audit"][:n], "changes_held": len(v["audit"])}


# ================================================================== the changes an Admin can make, each as on the screen
def _same(a, b):
    """Two cell values the same, as the person reads them: numbers by value, words without the spaces around them."""
    blank = lambda v: v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""
    if blank(a) or blank(b):
        return blank(a) and blank(b)
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def _table_changes(before, after):
    """What a save changed, cell by cell (row numbers from 1); rows added or removed at the end."""
    out = []
    for n, (x, y) in enumerate(zip(before["rows"], after["rows"])):
        for col, a, b in zip(after["columns"], x, y):
            if not _same(a, b):
                out.append({"row": n + 1, "column": col, "old": a, "new": b})
    return {"cells": out, "rows_before": len(before["rows"]), "rows_after": len(after["rows"])}


@tool(mirrors="PUT /api/table/{sheet}", writes=True)
def edit_rate_table(sheet: str, changes: list[dict] | None = None, rows: list | None = None) -> dict:
    """Edit a table of the rate master and save it, as Prices > Rate tables does when a person edits a table and presses
    Save. THIS CHANGES THE RATES EVERY COSTING USES, FOR EVERYONE, from the moment it is saved; the person must confirm
    first. [RATE RULE]
    Give either `changes` or `rows`:
    - changes: the cells to change, each {"row": 12, "column": "Rate Rs/kg", "old": 345, "new": 352}, with the row number
      and the old figure as rate_table shows them now. A change whose old figure is not what the table holds now is
      refused (someone may have changed it since), and nothing is saved.
    - rows: the whole table, every row in order, each a list in rate_table's column order (or an object by column name).
      A row left out is removed; a new row is added. Use it to add or remove rows.
    The save is checked as on the screen: numbers where numbers belong, no blank or repeated key, and the example fabric
    must still cost; anything wrong and nothing is saved. The rate master as it was is kept (on a database every version
    is kept; on files a dated copy). The answer lists every cell that changed, old and new. Recorded as "AI assistant"."""
    s = _s()
    from rules.common import Refused
    m = s.common.get_masters()
    if sheet not in s.rates.EDITABLE or sheet not in m:
        s.rates.save_table(sheet, {"columns": [], "rows": []}, who=ASSISTANT)        # the screen's own refusal, in its words
    if (changes is None) == (rows is None):
        raise Refused(400, "Give either `changes` (the cells to change) or `rows` (the whole table), not both and not neither. Nothing was saved.")
    before = s.common.records(m[sheet])
    cols = before["columns"]
    if changes is not None:
        new_rows, wrong = [list(r) for r in before["rows"]], []
        if not changes:
            raise Refused(400, "No change was given. Nothing was saved.")
        for ch in changes:
            if not isinstance(ch, dict) or "row" not in ch or "column" not in ch or "new" not in ch:
                raise Refused(400, 'Each change needs "row", "column", "old" and "new". Nothing was saved.')
            try:
                n = int(ch["row"])
            except (TypeError, ValueError):
                n = 0
            if not 1 <= n <= len(new_rows):
                raise Refused(400, f"Row {ch['row']} is not in {sheet} (rows 1 to {len(new_rows)}). Nothing was saved.")
            if ch["column"] not in cols:
                raise Refused(400, f"'{ch['column']}' is not a column of {sheet}: {', '.join(cols)}. Nothing was saved.")
            i = cols.index(ch["column"])
            if "old" not in ch:
                raise Refused(400, f'Say the figure row {n}, {ch["column"]} holds now ("old"), as you told the person. Nothing was saved.')
            if not _same(new_rows[n - 1][i], ch["old"]):
                wrong.append(f"row {n}, {ch['column']}: the table holds {new_rows[n - 1][i]!r} now, not {ch['old']!r}")
            new_rows[n - 1][i] = ch["new"]
        if wrong:
            raise Refused(409, "The table does not hold the old figures given (" + "; ".join(wrong) + "). Read it again with rate_table and "
                               "tell the person the figures as they are now. Nothing was saved.")
    else:
        new_rows = []
        for r in rows:
            if isinstance(r, dict):
                new_rows.append([r.get(c) for c in cols])
            elif isinstance(r, list) and len(r) == len(cols):
                new_rows.append(list(r))
            else:
                raise Refused(400, f"Each row is a list of {len(cols)} values in this order: {', '.join(cols)} (or an object by column name). Nothing was saved.")
    out = s.rates.save_table(sheet, {"columns": cols, "rows": new_rows}, who=ASSISTANT)
    return dict(out, sheet=sheet, changed=_table_changes(before, s.common.records(s.common.get_masters()[sheet])), recorded_as=ASSISTANT,
                kept="The rate master as it was before this save is kept: put it back by saving the old figures again.")


@tool(mirrors="POST /api/cotton", writes=True)
def add_cotton_price(date: str, price_per_candy: float, source: str = "") -> dict:
    """Add one cotton price to the rate master (Shankar-6, rupees per candy), as Prices > Cotton prices does. THIS CHANGES
    THE RATE MASTER FOR EVERYONE; the person must confirm first. [RATE RULE] Tell them the date, the price, and
    the latest price held now (cotton_prices). date: YYYY-MM-DD. source: where the price is from (for example
    "CAI, 27 Nov 2026"); "Typed in the tool" when empty. Recorded as "AI assistant"."""
    s = _s()
    cot = s.common.get_masters()["Cotton_Prices"]
    was = s.common.records(cot.tail(1))
    out = s.rates.add_cotton({"date": date, "price": price_per_candy, "source": source}, who=ASSISTANT)
    now = s.common.records(s.common.get_masters()["Cotton_Prices"].tail(1))
    return dict(out, added=_rows_as_dicts(now)[0], latest_before=_rows_as_dicts(was)[0] if was["rows"] else None, recorded_as=ASSISTANT)


def _intake(out):
    """Bring in prices: what was read, and the next step."""
    if out.get("kind") == "tables":
        return {"kind": "tables", "token": out["token"], "source": out["source"],
                "tables": {k: {"columns": v["columns"], "first_rows": v["rows"]} for k, v in out["sheets"].items()},
                "next": "Choose the table and its columns with intake_map_columns (this token, the table's name, and the columns holding the "
                        "count and the rate; the high rate, yarn and date columns if there are any). Nothing has been added."}
    return dict(out, next="These rows are read but not added. Show them to the person; with their yes, add the ones to keep with intake_add_rows "
                          "(each row in this column order) to the market reference, or as dated yarn rates with intake_add_dated_rates "
                          "(each row given its yarn of the yarn master and whether its price includes GST, with this read_token). Nothing has been added.")


@tool(mirrors="POST /api/intake/file", writes=True, destructive=False)
def intake_file(file_base64: str, file_name: str) -> dict:
    """Bring in prices (Prices > Bring in prices), step 1, from a file the person gives: an Excel or CSV price list, a PDF,
    or a picture, sent as base64 with its name (the ending says how to read it). An Excel or CSV file comes back as its
    tables (first 15 rows of each) with a token for intake_map_columns; a PDF as the price lines read from it; a picture as
    an empty table (its rates are typed in). NOTHING IS ADDED TO THE RATES here: that is intake_add_rows. A PDF or picture
    is kept on the server as the source, so a rate can be traced back to it; that is all this step keeps."""
    return _intake(_s().rates.intake_file(file_name, _file_bytes(file_base64, file_name)))


@tool(mirrors="POST /api/intake/link", outside=True)
def intake_page(url: str) -> dict:
    """Bring in prices, step 1, from a public web page (its address): its tables come back with a token for
    intake_map_columns, or, with no tables, the price-like lines in its text. RightPrice fetches the page itself; a page
    behind a login cannot be read. Nothing is added to the rates here."""
    return _intake(_s().rates.intake_link({"url": url}))


@tool(mirrors="POST /api/intake/api", outside=True)
def intake_api(url: str, header_name: str = "", header_value: str = "") -> dict:
    """Bring in prices, step 1, from a JSON endpoint: its reply comes back as a table with a token for intake_map_columns.
    header_name and header_value: a key the endpoint asks for, used for this one call and not stored. A key given here
    passes through this conversation: for a secret key, the person should use the screen instead. Nothing is added here."""
    return _intake(_s().rates.intake_api({"url": url, "header_name": header_name or None, "header_value": header_value or None}))


@tool(mirrors="POST /api/intake/map")
def intake_map_columns(token: str, table: str, count_column: str, rate_column: str, high_rate_column: str = "",
                       yarn_column: str = "", date_column: str = "") -> dict:
    """Bring in prices, step 2: which columns of a table read by intake_file, intake_page or intake_api hold the count and
    the rate (Rs per kg; with a high rate column, the rate column is the low end), and the yarn and the date if the table
    has them. The rows read come back to check with the person (a row without a rate is dropped). Nothing is added here.
    token and table: as step 1 gave them."""
    return _intake(_s().rates.intake_map({"token": token, "sheet": table, "count": count_column, "low": rate_column,
                                          "high": high_rate_column or None, "yarn": yarn_column or None, "date": date_column or None}))


@tool(mirrors="POST /api/intake/add", writes=True)
def intake_add_rows(rows: list, source: str = "") -> dict:
    """Bring in prices, last step: add the checked rows to the rate master's market reference (the table Market_Yarn,
    which the Yarn prices page sets the yarn master against). THIS CHANGES THE RATE MASTER FOR EVERYONE; the person must
    confirm first. [RATE RULE] Show them the rows to be added and get their yes.
    rows: as intake_map_columns (or step 1, for a PDF) returned them, each a list in the order Date, Yarn, Count,
    Low Rs/kg, High Rs/kg, Source (or an object by those names); a row needs at least a count and a low rate. source: the
    file or page they came from, for rows without one. Recorded as "AI assistant"."""
    s = _s()
    cols = s.rates.pi.STAGE_COLS
    shaped = [[r.get(c) for c in cols] if isinstance(r, dict) else r for r in rows or []]
    return dict(s.rates.intake_add({"rows": shaped, "source": source}, who=ASSISTANT), recorded_as=ASSISTANT)


# ------------------------------------------------------------------ dated yarn rates (stage 5; a database only)
def _dated():
    from rules import dated
    return dated


@tool(mirrors="GET /api/dated-rates")
def dated_rates() -> dict:
    """Dated yarn rates (Prices > Yarn prices): a yarn's rate for a month, so a purchase order is costed on the yarn rates
    of its order month (quotes and Cost a fabric stay on today's rates). Gives the rule they follow, every rate in force
    (yarn, month, rate, low and high, what it rests on, who entered it, its id for remove_dated_rate), the ones removed
    or replaced lately, the yarn master's yarns with today's rate, and how many purchase-order fabrics each month has a
    dated rate for. Kept in the database only: on the files the answer says so."""
    p = _dated().page()
    return {"rule": p["rule"], "this_month": p["this_month"], "in_force": p["entries"], "removed_or_replaced_lately": p["history"],
            "yarns": p["yarns"], "rests_on_choices": p["rests_on"], "orders_by_month": p["orders"], "rate_limits_rs_per_kg": p["limits"],
            "first_month": p["first_month"], "market_file": p["market_file"]}


@tool(mirrors="GET /api/dated-rates/market")
def dated_market_preview() -> dict:
    """What loading the market history in hand (Yarn_Inteliigence_Master.xlsx) as dated yarn rates would do: each monthly
    rate it gives (only yarns surely in the yarn master), whether it is new, changed, unchanged, kept (a person's rate
    stays) or held (a person removed it), and every row it leaves out, with why. Changes nothing."""
    return _dated().market_preview()


@tool(mirrors="POST /api/dated-rates", writes=True)
def add_dated_rate(yarn_key: str, month: str, rests_on: str, rate: float | None = None, low: float | None = None,
                   high: float | None = None, gst: bool = False, note: str = "") -> dict:
    """Enter a dated yarn rate, as Prices > Yarn prices does: a yarn of the yarn master, a month (YYYY-MM, one that has
    begun), what it rests on ("circular", "price list", "quote", "invoice", "other" with the document named in `note`, or
    "none": then it is kept as a placeholder), whether the price includes GST, and the rate in rupees a kilo (or a low and
    a high: their midpoint). It takes the place of any earlier rate for that yarn and month (kept, marked replaced); a
    rate with GST never takes the place of one without GST. THIS CHANGES THE YARN RATES PURCHASE ORDERS OF THAT MONTH ARE
    COSTED ON, FOR EVERYONE; the person must confirm first. [RATE RULE] Recorded as entered by "AI assistant"."""
    payload = {"yarn_key": yarn_key, "month": month, "rests_on": rests_on, "rate": rate, "low": low, "high": high, "gst": gst, "note": note}
    return dict(_dated().add(payload, who=ASSISTANT), recorded_as=ASSISTANT)


@tool(mirrors="POST /api/dated-rates/remove", writes=True)
def remove_dated_rate(rate_id: int) -> dict:
    """Take one dated yarn rate out, as Prices > Yarn prices does (rate_id from dated_rates). Purchase orders of that month
    then use today's rate for that yarn, unless another rate is entered. THIS CHANGES HOW THOSE ORDERS ARE COSTED, FOR
    EVERYONE; the person must confirm the yarn, the month and the rate first. [RATE RULE] The rate is kept, marked removed
    by "AI assistant", and loading the market history does not bring it back."""
    return dict(_dated().remove({"id": rate_id}, who=ASSISTANT), recorded_as=ASSISTANT)


@tool(mirrors="POST /api/dated-rates/market", writes=True)
def load_market_dated_rates() -> dict:
    """Load the market history's monthly rates as dated yarn rates, as Prices > Yarn prices does (see dated_market_preview
    first, and show the person what it would add). Only the yarns surely in the yarn master; a rate a person entered
    stays, a rate a person removed is not brought back, and a load that changes nothing writes nothing. THIS CHANGES THE
    YARN RATES PURCHASE ORDERS ARE COSTED ON, FOR EVERYONE; the person must confirm first. [RATE RULE] Recorded as entered
    by "AI assistant"."""
    return dict(_dated().market_load(who=ASSISTANT), recorded_as=ASSISTANT)


@tool(mirrors="POST /api/intake/add-dated", writes=True)
def intake_add_dated_rates(rows: list, read_token: str = "", source: str = "", month: str = "", month_undated: str = "",
                           preview: bool = False) -> dict:
    """Bring in prices, last step, as dated yarn rates instead of the market reference (Bring in prices > Add as dated
    yarn rates). rows: the reviewed rows as intake_map_columns (or step 1) returned them, each with two more values: the
    yarn of the yarn master it is, and whether its price includes GST (true or false): [Date, Yarn, Count, Low Rs/kg,
    High Rs/kg, Source, yarn key, GST]; a row given no yarn key ("") is left out. read_token: as that step returned it;
    the month of each row comes from the dates the server itself read of the document, never from today. month: one month
    (YYYY-MM) for every row instead; month_undated: the month for rows without a date of the document's. preview: true
    only says which month each row would take and which rows need a month, and changes nothing: call it first and show
    the person. Otherwise THIS CHANGES THE YARN RATES PURCHASE ORDERS OF THOSE MONTHS ARE COSTED ON, FOR EVERYONE; the
    person must confirm first. [RATE RULE] One rate per yarn and month (a range as its midpoint, several prices averaged,
    those without GST before those with). Recorded as entered by "AI assistant"."""
    payload = {"rows": rows or [], "read_token": read_token, "source": source, "month": month or None, "month_undated": month_undated or None,
               "preview": bool(preview)}
    return dict(_dated().intake_add(payload, who=ASSISTANT), recorded_as=ASSISTANT)


@tool(mirrors="POST /api/list/upload", writes=True)
def upload_to_fabric_list(file_base64: str, file_name: str) -> dict:
    """Upload a mill's price sheet as it comes, or a filled RightPrice template, to the fabric list (Bulk upload): an .xlsx
    file sent as base64 with its name. THIS ADDS ROWS EVERYONE SEES (Right cost, the negotiation pack, quote alerts); the
    person must confirm the file and the mill first. A row already on the list is not added twice. Each row is costed on
    today's rates; the answer gives the rows added, those already there, those that could not be costed (they are kept,
    with the reason), and the quote alerts raised at once. Recorded as "AI assistant"."""
    out = _s().fabric_list.list_upload(file_name, _file_bytes(file_base64, file_name), who=ASSISTANT)
    return {"added": out["added"], "already_on_the_list": out["already"], "read_as": out["kind"], "not_costed": out["not_costed"],
            "alerts": [{"key": f"Fabric list|{a['id']}", "code": a["code"], "flags": [f["text"] for f in a["flags"]]} for a in out["alerts"]],
            "recorded_as": ASSISTANT, "next": "find_fabrics (source 'Fabric list') or fabric_list gives the rows and their keys."}


def _check_choices(choices, values=True):
    """cost_fabric's checks of the choices: a field it does not know (which the costing would silently leave out), and
    with `values`, a value not among the choices or a typed number that is not one. The words of the refusal, or None."""
    known = _fields()
    unknown = [k for k in choices if k not in known]
    if unknown:
        return f"Unknown field(s): {', '.join(map(str, unknown))}. Nothing was costed. Use the field names of list_choices: {', '.join(known)}."
    if not values:
        return None
    bad =[f"{k}: {choices[k]!r}" for k, f in known.items() if k in choices and f["choose_from"] and str(choices[k]) not in map(str, f["choose_from"])]
    if bad:
        return "Not among the choices of list_choices: " + "; ".join(bad) + ". Nothing was costed."
    wrong = []
    for k in ("EPI", "PPI", "Finished width (in)", "Reed space (in)", "Quoted price (Rs/m)", "Order quantity (m)"):
        if k in choices and choices[k] not in (None, ""):
            try:
                v = float(choices[k])
                if not math.isfinite(v) or v <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                wrong.append(f"{k}: {choices[k]!r}")
    if wrong:
        return "These must be plain positive numbers (no units, no commas): " + "; ".join(wrong) + ". Nothing was costed."
    return None


@tool(mirrors="POST /api/list/add", writes=True)
def add_fabric_to_list(choices: dict, replaces_key: str = "") -> dict:
    """Add one fabric to the fabric list, as Cost a fabric's "Add to list" does: `choices` as for cost_fabric (with
    "Fabric code", "Supplier", "Quoted price (Rs/m)" and "Order quantity (m)" for a quote). THIS ADDS A ROW EVERYONE SEES;
    the person must confirm the fabric, the mill and the price first. replaces_key: a fabric-list row's key to put this
    in its place (its mill columns stay), as editing a row on the screen does. The fabric must cost, or nothing is added
    (the costing's own refusal says why). Recorded as "AI assistant"."""
    s = _s()
    words = _check_choices(choices, values=False)        # a misspelt field would be kept on the row and never costed
    if words:
        return {"error": words.replace("Nothing was costed.", "Nothing was added.")}
    sel = dict(choices)
    old = _id_of(replaces_key) if replaces_key else ""
    log = s.common.read_log()
    had = bool(old) and "Id" in log.columns and old in set(log["Id"].astype(str))
    if old:
        sel["_id"] = old
    out = s.fabric_list.list_add(sel, who=ASSISTANT)
    return {"added": True, "key": f"Fabric list|{out['id']}", "replaced": f"Fabric list|{old}" if had else None,
            "note": None if had or not old else "No row with that key was on the list, so this was added as a new row.", "recorded_as": ASSISTANT}


@tool(mirrors="POST /api/list/remove", writes=True)
def remove_fabric_list_rows(keys: list[str]) -> dict:
    """Remove rows from the fabric list, as Bulk upload and Right cost do. THIS REMOVES ROWS FOR EVERYONE (and their quote
    alerts); the person must confirm which rows first (say each code and mill). keys: from find_fabrics, fabric_list or
    quote_alerts ("Fabric list|<id>"). A removed row is kept in the database, marked removed by "AI assistant"."""
    s = _s()
    ids = [_id_of(k) for k in keys or [] if _id_of(k)]
    log = s.common.read_log()
    on = {i: (c, sp) for i, c, sp in zip(log["Id"].astype(str), log["Fabric code"], log["Supplier"])} if "Id" in log.columns else {}
    out = s.fabric_list.list_remove({"ids": ids}, who=ASSISTANT)
    return {"removed": out["removed"], "rows": [{"key": f"Fabric list|{i}", "code": s.common.clean(on[i][0]), "supplier": s.common.clean(on[i][1])} for i in ids if i in on],
            "not_on_the_list": [f"Fabric list|{i}" for i in ids if i not in on], "recorded_as": ASSISTANT}


@tool(mirrors="POST /api/costsheet/upload", writes=True)
def upload_mill_cost_sheet(file_base64: str, file_name: str) -> dict:
    """Upload a mill cost sheet (Prices > Mill cost sheets): an .xlsx on RightPrice's cost sheet template, sent as base64
    with its name. THIS ADDS ROWS EVERYONE SEES on Mill cost sheets, and may make new drafts; it changes no rate. A mill's
    sheet sent again takes the place of that mill's earlier rows for the same fabric codes. The person must confirm the
    file first. Recorded as "AI assistant"."""
    out = _s().costsheets.costsheet_upload(file_name, _file_bytes(file_base64, file_name), who=ASSISTANT)
    return dict(out, recorded_as=ASSISTANT, next="mill_cost_sheets shows the rows and the drafts.")


@tool(mirrors="POST /api/costsheet/remove", writes=True)
def remove_mill_cost_sheet_rows(ids: list[str] | None = None, upload: str = "") -> dict:
    """Remove rows from Mill cost sheets, as its screen does: by row id (mill_cost_sheets), or every row of one upload
    (its `upload` name). THIS REMOVES THE ROWS FOR EVERYONE (they are not kept), and the drafts resting on them; it changes
    no rate. The person must confirm which rows first."""
    return _s().costsheets.costsheet_remove({"ids": ids or [], "upload": upload or None})


@tool(mirrors="POST /api/costsheet/apply", writes=True)
def apply_cost_sheet_drafts(draft_ids: list[str]) -> dict:
    """Apply drafts from Mill cost sheets to the rate master, as its screen does when the person ticks drafts and applies
    them. THIS CHANGES THE RATES EVERY COSTING USES, FOR EVERYONE; the person must confirm first. [RATE RULE] For
    each draft tell them the rate, its figure now and the proposed figure (mill_cost_sheets), and which mills it comes
    from. draft_ids: the drafts' ids. The rate master as it was is kept first. Recorded as "AI assistant"."""
    out = _s().costsheets.costsheet_apply({"ids": draft_ids or []}, who=ASSISTANT)
    return dict(out, recorded_as=ASSISTANT)


@tool(mirrors="POST /api/alerts/seen", writes=True)
def mark_alerts_seen(keys: list[str] | None = None, bring_back: bool = False, bring_all_back: bool = False) -> dict:
    """Mark quote alerts seen, or bring them back, as the Dashboard and Right cost do. THIS CHANGES WHAT EVERYONE SEES: an
    alert marked seen leaves the Dashboard, the Right cost count and Bulk upload for every user. The person must confirm
    which alerts first. keys: from quote_alerts ("Fabric list|<id>"). bring_back: true brings those back. bring_all_back:
    true brings every seen alert back. Recorded as "AI assistant"."""
    ids = [_id_of(k) for k in keys or [] if _id_of(k)]
    a = _s().alerts.alerts_seen({"ids": ids, "undo": bool(bring_back), "restore": bool(bring_all_back)}, who=ASSISTANT)
    return {"done": "all seen alerts brought back" if bring_all_back else ("brought back: " if bring_back else "marked seen: ") + (", ".join(ids) or "nothing (no keys given)"),
            "alerts_to_look_at_now": a["count"], "marked_seen": a["seen"], "cleared_by_agreement": a["agreed"], "recorded_as": ASSISTANT}


@tool(mirrors="POST /api/draft", outside=True)
def draft_message_to_mill(mill: str = "", keys: list[str] | None = None, ask: str = "both", writer: str = "", contact: str = "") -> dict:
    """Draft an e-mail and a WhatsApp message to one mill, as "Draft a message to the mill" does: on the fabrics worth
    raising with it, following the tracker (a counter already made is the price named; an agreed fabric is left out).
    NOTHING IS SENT AND NOTHING IS KEPT: give the draft to the person to read, change and send themselves. mill: a mill's
    name, for every fabric worth raising with it; or keys: fabrics of one mill (from find_fabrics). ask: "breakup" (the
    cost break-up), "price" (a revised price) or "both". writer: the buyer's name; contact: the mill's contact. With the
    Claude key set on the server the wording is written by Claude (the figures go to Anthropic's API, as on the screen);
    otherwise a fixed template is filled, and the answer says so."""
    scope = {"type": "rows", "keys": list(keys)} if keys else ({"type": "supplier", "mill": mill} if mill else {})
    return _s().drafts.draft_message({"scope": scope, "ask": ask, "writer": writer, "contact": contact})


@tool(mirrors="POST /api/negotiations/remove", writes=True)
def remove_tracker_step(key: str, step_id: str) -> dict:
    """Remove any negotiation step from a fabric, as an admin can on the fabric's Negotiation tab, whoever recorded it
    (step ids from tracker_steps). THIS CHANGES DATA EVERYONE SHARES, and what was won: removing the mill's first quote
    makes its next quote the first. The person must confirm the fabric and the step (kind, price, date, who recorded it)
    first. The step is kept in the fabric's Log, marked removed by "AI assistant"."""
    s = _s()
    rec = s.tracker._negos().get(key) or {}
    step = next((e for e in rec.get("events", []) if str(e.get("id")) == str(step_id)), None)
    s.tracker.negotiation_remove({"key": key, "id": step_id}, who=ASSISTANT)
    rec = s.tracker._negos().get(key) or {}
    return {"removed": True, "removed_step": None if step is None else {"kind": step["kind"], "price_per_m": step["price"], "date": step["date"], "recorded_by": step.get("by") or ""},
            "now": _nego(rec, s.tracker.nego_summary(rec)) if rec.get("events") else {"status": "Not tracked", "steps": []}, "recorded_as": ASSISTANT}


@tool(mirrors="POST /api/users/add", writes=True)
def add_person(email: str, role: str, name: str = "") -> dict:
    """Let a person into RightPrice (Users and roles > Add): their Microsoft sign-in address, a role (Admin, Rates editor,
    Buyer or Viewer) and their name. THIS CHANGES WHO MAY USE RIGHTPRICE AND WHAT THEY MAY DO; the person must confirm the
    address, the name and the role first (Admin can do everything, users included). Only while permissions are on (the app
    setting RIGHTPRICE_ADMINS), on a database. Recorded in the change record as made by "AI assistant"."""
    from rules import access
    return dict(access.add_person({"email": email, "name": name, "role": role}, assistant=True), recorded_as=ASSISTANT)


@tool(mirrors="POST /api/users/change", writes=True)
def change_person(email: str, role: str | None = None, name: str | None = None, active: bool | None = None) -> dict:
    """Change a person on Users and roles: their role (Admin, Rates editor, Buyer, Viewer), their name, or switch their
    access off (active false) or on again. Only what is given changes. THIS CHANGES WHAT THAT PERSON MAY DO, AT ONCE; the
    person asking must confirm first. The last admin in the list stays an admin. Recorded in the change record as made by
    "AI assistant"."""
    from rules import access
    payload = {"email": email}
    payload.update({k: v for k, v in (("role", role), ("name", name), ("active", active)) if v is not None})
    return dict(access.change_person(payload, assistant=True), recorded_as=ASSISTANT)


@tool(mirrors="POST /api/users/permissions", writes=True)
def change_role_permissions(changes: list[dict]) -> dict:
    """Give a role a permission or take one away, as the grid on Users and roles does: changes, each {"role": "Buyer",
    "permission": "page:pilot", "allowed": false} (permission keys from users_and_roles). THIS CHANGES WHAT EVERYONE IN
    THAT ROLE MAY DO, AT ONCE; the person must confirm first. Admin always has everything, and user admin stays Admin's
    alone. Recorded in the change record as made by "AI assistant"."""
    from rules import access
    return dict(access.set_permissions({"changes": changes}, assistant=True), recorded_as=ASSISTANT)


if __name__ == "__main__":
    mcp.run()           # stdio: for an assistant on the same machine as the data
