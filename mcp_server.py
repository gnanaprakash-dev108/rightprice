"""RightPrice as an MCP server, so an AI assistant (Claude Desktop, for one) can use it.

Two ways in, the same tools:
- On the web app at /mcp (streamable HTTP). Off unless the app setting RIGHTPRICE_MCP_TOKEN is set (24 characters or
  more); every request must carry "Authorization: Bearer <that token>". server.py does the token check and the mount.
- On a laptop: `python mcp_server.py` (stdio), working on that machine's own data folder.

The tools call the same functions the screens do, so an assistant sees the buyer's figures, never a second version.
One tool writes: record_tracker_step. Every refusal the tracker makes on the screen it makes here too, and the step
is marked as recorded through the assistant.
"""
import functools
import hmac
import os

import anyio
from mcp.server.mcpserver import MCPServer

TOKEN_ENV = "RIGHTPRICE_MCP_TOKEN"

mcp = MCPServer(
    "RightPrice",
    instructions=(
        "RightPrice works out what a woven fabric should cost ex-mill, in rupees per metre, and compares it with a mill's "
        "quote or a purchase-order price, to prepare a fabric buyer for negotiation with the mill. Money is in Indian rupees; "
        "quantities in metres. Verdicts: 'Push' = priced above the usual range for that fabric type; 'Fair' = inside it; "
        "'Below' = under it; 'Ask break-up' = the tool is unsure of this fabric (placeholder rates or a poorly fitted type), "
        "so do not quote a target on it; 'Check quote' = more than 30% under should-cost, probably a mistake. "
        "Never net savings against overcharges. Rates marked Placeholder have no data behind them: say so when a figure rests "
        "on them. Use find_fabrics to get a fabric's key before fabric_brief, tracker_steps or record_tracker_step. "
        "record_tracker_step changes data everyone shares: confirm the fabric, the kind of step, the price and the date with "
        "the person before calling it."))


def tool(fn):
    """Register a tool. The app's functions are ordinary blocking ones (the first Right cost answer after a restart takes
    about 20 seconds), so each runs in a worker thread and the web app stays responsive meanwhile."""
    @functools.wraps(fn)
    async def run(*args, **kwargs):
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
    return mcp.tool()(run)


def token():
    """The token the web endpoint asks for, or None when it is switched off (unset, or too short to be a secret)."""
    t = os.environ.get(TOKEN_ENV, "").strip()
    return t if len(t) >= 24 else None


def allowed(header):
    """True when the Authorization header carries the token. Constant-time, so the token cannot be guessed by timing."""
    t = token()
    got = header[7:].strip() if isinstance(header, str) and header[:7].lower() == "bearer " else ""
    return bool(t) and bool(got) and hmac.compare_digest(got.encode(), t.encode())


def _s():
    import server           # late: the tools run inside the web app, or load it once for stdio
    return server


def _fail(e):
    """A refusal from the app, as words for the assistant to pass on."""
    return {"error": str(getattr(e, "detail", None) or e)}


def _r2(v):
    return None if v is None else round(float(v), 2)


def _row(r):
    return {"key": f"{r['source']}|{r.get('id') or r['code']}", "source": r["source"], "code": r["code"], "description": r.get("description"),
            "supplier": r.get("supplier"), "route": r.get("route"), "weave": r.get("weave"), "should_cost_per_m": _r2(r.get("should")),
            "price_per_m": _r2(r.get("price")), "price_is": "paid (purchase order)" if r["source"] == "Purchase orders" else "quoted (fabric list)",
            "above_should_cost_pct": _r2(r.get("gap_pct")), "metres": r.get("metres"), "verdict": r.get("band"),
            "placeholder_rates_used": r.get("placeholders"), "repeats_order_of": r.get("duplicate_of")}


def _find(key):
    return next((r for r in _s().costs()["rows"] if f"{r['source']}|{r.get('id') or r['code']}" == key), None)


@tool
def list_choices() -> dict:
    """The drop-down choices RightPrice accepts when costing a fabric (content, route, weave, finish, yarns and so on).
    Call this before cost_fabric and use the values exactly as given."""
    s = _s()
    L = s.masters.lists(s.get_masters())
    return {"choices": {k: list(v)[:400] for k, v in L.items()},
            "typed_fields": ["EPI", "PPI", "Finished width (in)", "Quoted price (Rs/m)", "Order quantity (m)", "Fabric code", "Description", "Supplier"],
            "example": {k: v for k, v in s.masters.EXAMPLE_ROW.items()}}


@tool
def cost_fabric(choices: dict) -> dict:
    """Work out the should-cost of one fabric, ex-mill, in rupees per metre and per kilo, from its construction.
    `choices` uses the field names and values of list_choices (see its example). Add "Quoted price (Rs/m)" and
    "Order quantity (m)" to get the negotiation brief as well. Nothing is saved."""
    s = _s()
    try:
        out = s.cost(dict(choices))
    except Exception as e:
        return _fail(e)
    b = out.get("brief")
    res = {"should_cost_per_m": _r2(out["total_per_m"]), "should_cost_per_kg": _r2(out["per_kg"]), "gsm": _r2(out.get("gsm")),
           "cost_groups_rs_per_m": {x["name"]: _r2(x["amount"]) for x in out.get("buckets", [])},
           "placeholder_rates_used": out.get("placeholders") or [], "warnings": out.get("warnings") or []}
    if b:
        res["brief"] = _brief(b)
    return res


def _brief(b):
    stance = "Check quote" if b["implausible"] else {"push": "Push", "fair": "Fair", "below": "Below", "ask": "Ask break-up"}[b["stance"]]
    return {"verdict": stance, "price_per_m": b["quote"], "should_cost_per_m": b["should"], "price_above_should_cost_per_m": b["gap"],
            "usual_range_per_m": [b["lower"], b["settle_up_to"]], "why_this_range": b["band"]["why"],
            "open_at_per_m": b["open_at"] if b["stance"] == "push" else None, "aim_for_per_m": b["settle_up_to"] if b["stance"] == "push" else None,
            "why_no_target": b["weak"], "caveats": b["caveats"], "quantity_m": b["quantity"],
            "rupees_above_should_cost_on_the_quantity": b["at_stake"]}


@tool
def find_fabrics(search: str = "", mill: str = "", verdict: str = "", source: str = "", limit: int = 20) -> dict:
    """Find costings in Right cost: purchase-order fabrics (price paid) and fabric-list rows (price quoted).
    search: words in the fabric code, description or supplier. mill: a mill's name, any spelling. verdict: Push, Fair,
    Below, Ask break-up, Check quote. source: "Purchase orders" or "Fabric list". Sorted by rupees above should-cost,
    largest first. Returns each fabric's key, needed by the other tools."""
    s = _s()
    d = s.costs()
    rows, words = d["rows"], [w for w in search.lower().split() if w]
    if mill:
        rows = [r for r in rows if r["mill"] == s.mill_key(mill)]
    if source:
        rows = [r for r in rows if r["source"].lower() == source.lower()]
    if verdict:
        rows = [r for r in rows if str(r.get("band") or "").lower().startswith(verdict.lower())]
    if words:
        rows = [r for r in rows if all(w in " ".join(str(r.get(k) or "") for k in ("code", "description", "supplier")).lower() for w in words)]
    rows = sorted(rows, key=lambda r: -(r.get("excess") or 0))
    n = max(1, min(int(limit or 20), 100))
    return {"found": len(rows), "shown": min(n, len(rows)), "verdicts_ready": d["ready"],
            "note": None if d["ready"] else "The purchase-order verdicts are still being worked out (about 20 seconds after a restart): ask again shortly.",
            "fabrics": [_row(r) for r in rows[:n]]}


@tool
def fabric_brief(key: str) -> dict:
    """The negotiation brief for one fabric (key from find_fabrics): verdict, should-cost, usual range, where to open and
    what to aim for, why the tool is unsure if it is, the quote alerts on it, and where its negotiation stands. The brief
    is on the mill's latest price in the tracker (or the agreed price) when there is one, else the price on the row."""
    s = _s()
    r = _find(key)
    if r is None:
        return {"error": "No fabric with that key. Use find_fabrics to get the key."}
    out = {"fabric": _row(r)}
    rec = s._negos().get(key)
    summ = s.nego_summary(rec) if rec and rec.get("events") else None
    price = (summ["agreed"] if summ and summ["status"] == "Agreed" else summ["latest"] if summ else None) or r.get("price")
    if r.get("problems"):
        out["not_costed_because"] = r["problems"]
    elif price and r.get("choices"):
        try:
            m = s.get_masters()
            res = s.masters.cost(dict(r["choices"], **{"Quoted price (Rs/m)": price}), m)
            b = s.brief(res, m, r.get("metres"), (), r["choices"])
            if b:
                out["brief"] = _brief(b)
                out["brief_is_on"] = "the agreed price in the tracker" if summ and summ["status"] == "Agreed" else "the mill's latest price in the tracker" if summ and summ["latest"] else "the price on the row"
        except Exception as e:
            out["brief_error"] = str(e)
    else:
        out["brief"] = None
        out["why_no_brief"] = "No price on this row and no mill price in the tracker."
    if summ:
        out["negotiation"] = _nego(rec, summ)
    if r["source"] == "Fabric list":
        a = s.alerts()["all"].get(r.get("id"))
        if a:
            out["quote_alerts"] = {"state": a["state"], "flags": [f["text"] for f in a["flags"]]}
    return out


def _nego(rec, summ):
    return {"status": summ["status"], "first_mill_quote": summ["first"], "mill_latest": summ["latest"], "our_counter": summ["counter"],
            "agreed": summ["agreed"], "won_per_m_against_first_quote": summ["won_per_m"], "won_rupees": summ["won"] if summ["counted"] else None,
            "counted_as_won": summ["counted"], "to_check": summ["warnings"],
            "steps": [{"date": e["date"], "kind": e["kind"], "price_per_m": e["price"], "note": e.get("note") or "", "by": e.get("by") or ""}
                      for e in _s()._nego_order(rec.get("events", []))]}


@tool
def supplier_summary(mill: str) -> dict:
    """One mill, for the meeting with it: what was bought and what is quoted with verdict counts, the rupees above the
    usual range (counted only where the tool is sure), its sheets' sums that are off, negotiations and what was won,
    and the questions to take to the meeting. mill: the mill's name in any spelling."""
    s = _s()
    try:
        d = s.supplier(mill)
    except Exception as e:
        return _fail(e)
    side = lambda x: {k: v for k, v in x.items() if k not in ("rows",)} | {"largest": [
        {"code": r["code"], "price_per_m": _r2(r["price"]), "should_cost_per_m": _r2(r["should"]), "metres": r["metres"], "verdict": r["band"],
         "rupees_above_range": r["above_range"]} for r in x["rows"][:15]]}
    return {"mill": d["name"], "also_written": d["names"][1:], "as_of": d["today"], "verdicts_ready": d["ready"],
            "bought": side(d["bought"]), "quoted": side(d["quoted"]), "sums_off": d["sums"],
            "negotiations": d["tracker"], "questions": d["questions"],
            "reading_the_figures": "above_range counts only Push fabrics. unsure_high fabrics look high but the tool is unsure: ask for their "
                                   "break-up, do not push a figure. Purchases are already paid: use them for the next order of the same cloth."}


@tool
def negotiation_pack(mill: str = "", keys: list[str] | None = None) -> dict:
    """The negotiation pack for a mill's quoted fabrics (fabric-list rows): totals, the rows to lead with, every row with
    its verdict, open and aim prices, rupees at stake, the mill's own sums done again, and the questions per row.
    Give a mill name, or the keys of fabric-list rows from find_fabrics."""
    s = _s()
    rows = [r for r in s.costs()["rows"] if r["source"] == "Fabric list"]
    want = set(keys or [])
    ids = [r["id"] for r in rows if (f"Fabric list|{r['id']}" in want if want else (mill and r["mill"] == s.mill_key(mill)))]
    if not ids:
        return {"error": "No fabric-list rows for that mill or those keys. The pack is made from quoted fabrics (the fabric list), not purchase orders."}
    try:
        p = s.pack({"ids": ids})
    except Exception as e:
        return _fail(e)
    keep = ("code", "description", "quantity", "quote", "should", "gap", "stance", "upper", "open_at", "above_band", "at_stake", "above_range_money",
            "sums", "own_price", "own_gap", "duplicate_of", "weak", "caveats", "questions")
    return {"totals": p["totals"], "lead_with": p["lead"], "rows": [{k: r.get(k) for k in keep} for r in p["rows"]], "not_costed": p["not_costed"],
            "reading_the_figures": "at_stake is the price less should-cost, times the quantity; above_range_money is the part above the top of the "
                                   "usual range, the figure the mill has to explain. Rows with stance ask or check carry no target. "
                                   "The pack is on the prices of the mill's sheet; fabric_brief follows the tracker."}


@tool
def tracker_steps(key: str) -> dict:
    """The negotiation recorded on one fabric (key from find_fabrics): each step with the mill and where it stands."""
    s = _s()
    rec = s._negos().get(key)
    if not rec or not rec.get("events"):
        return {"status": "Not tracked", "steps": [], "kinds_you_can_record": s.NEGO_KINDS}
    return dict(_nego(rec, s.nego_summary(rec)), kinds_you_can_record=s.NEGO_KINDS)


@tool
def record_tracker_step(key: str, kind: str, price_per_m: float, date: str = "", note: str = "") -> dict:
    """Record one negotiation step on a fabric. THIS CHANGES DATA EVERYONE SHARES: confirm with the person first.
    key: from find_fabrics. kind: exactly one of "Mill's quote", "Our counter", "Mill's revised quote", "Agreed".
    price_per_m: rupees per metre. date: YYYY-MM-DD (today if empty). The app refuses a price outside Rs 1 to 50,000,
    a date in the future or over two years back, a row that repeats another order, and returns warnings for a step
    that looks wrong (far from should-cost or the first quote, a counter above the mill's price): pass them on."""
    s = _s()
    r = _find(key)
    if r is None:
        return {"error": "No fabric with that key. Use find_fabrics to get the key."}
    try:
        rec = s.negotiation_event({"key": key, "kind": kind, "price": price_per_m, "date": date or None,
                                   "note": (str(note or "").strip() + " (recorded through the AI assistant)").strip(), "code": r["code"],
                                   "supplier": r.get("supplier"), "description": r.get("description"), "source": r["source"],
                                   "metres": r.get("metres"), "should": r.get("should"), "row_price": r.get("price")}, None, by="AI assistant")
    except Exception as e:
        return _fail(e)
    return {"recorded": True, "now": _nego(rec, rec["summary"])}


@tool
def quote_alerts() -> dict:
    """Newly quoted fabrics that need a look before their price is accepted: above the usual range, the mill's own sums
    off, repeating an order already on the list, or far below should-cost. Newest upload first."""
    a = _s().alerts()
    return {"count": a["count"], "by_kind": {a["kinds"][k]: n for k, n in a["by_kind"].items()},
            "rupees_quoted_above_ranges": a["above_money"], "rupees_the_mills_own_sums_are_out": a["sums_money"],
            "note": "The two rupee figures largely overlap: do not add them.",
            "uploads": [{"mill": g["supplier"], "upload": g["upload"],
                         "fabrics": [{"key": r["key"], "code": r["code"], "flags": [f["text"] for f in r["flags"]]} for r in g["rows"]]} for g in a["groups"]]}


if __name__ == "__main__":
    mcp.run()           # stdio: for an assistant on the same machine as the data
