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
from mcp.types import ToolAnnotations

TOKEN_ENV = "RIGHTPRICE_MCP_TOKEN"

mcp = MCPServer(
    "RightPrice", version="1",
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
        "record_tracker_step changes data everyone shares: confirm the fabric, the kind of step, the price and the date with "
        "the person before calling it."))


def tool(fn=None, *, writes=False, destroys=False):
    """Register a tool. The app's functions are ordinary blocking ones (the first Right cost answer after a restart takes
    about 20 seconds), so each runs in a worker thread and the web app stays responsive meanwhile. Tools are marked
    read-only unless they write, so a client can ask the person before a writing one."""
    def register(f):
        @functools.wraps(f)
        async def run(*args, **kwargs):
            return await anyio.to_thread.run_sync(functools.partial(f, *args, **kwargs))
        return mcp.tool(annotations=ToolAnnotations(read_only_hint=not writes, destructive_hint=destroys, open_world_hint=False))(run)
    return register(fn) if fn is not None else register


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


def _track(key):
    """What the tracker holds on a fabric, in a few words an assistant cannot misread."""
    s = _s()
    rec = s._negos().get(key)
    if not rec or not rec.get("events"):
        return None
    m = s.nego_summary(rec)
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
    return next((r for r in _s().costs()["rows"] if f"{r['source']}|{r.get('id') or r['code']}" == key), None)


def _fields():
    s = _s()
    L = s.masters.lists(s.get_masters())
    typed = ["Fabric code", "Description", "Supplier", "Content", "EPI", "PPI", "Finished width (in)", "Reed space (in)", "Quoted price (Rs/m)", "Order quantity (m)"]
    fields = {name: {"choose_from": list(L[lst])[:400] if lst in L else None, "required": bool(req)} for name, lst, req in s.masters.TEMPLATE_COLUMNS}
    for t in typed:
        fields.setdefault(t, {"choose_from": None, "required": False})
    return fields


@tool
def list_choices() -> dict:
    """Every field RightPrice accepts when costing a fabric, with the values to choose from (choose_from is null for a
    field that is typed: a number or free text). Call this before cost_fabric and use field names and values exactly."""
    s = _s()
    return {"fields": _fields(), "example": {k: v for k, v in s.masters.EXAMPLE_ROW.items()},
            "note": "A field left out takes the rate master's default (for example medium shade, order size 3,000 m and above). "
                    "cost_fabric refuses a field name it does not know, so a misspelt field cannot be silently ignored."}


@tool
def cost_fabric(choices: dict) -> dict:
    """Work out the should-cost of one fabric, ex-mill, in rupees per metre and per kilo, from its construction.
    `choices` uses the field names and values of list_choices (see its example). Add "Quoted price (Rs/m)" and
    "Order quantity (m)" to get the negotiation brief as well. Nothing is saved."""
    s = _s()
    known = _fields()
    unknown = [k for k in choices if k not in known]
    if unknown:
        return {"error": f"Unknown field(s): {', '.join(map(str, unknown))}. Nothing was costed. Use the field names of list_choices: {', '.join(known)}."}
    bad = [f"{k}: {choices[k]!r}" for k, f in known.items() if k in choices and f["choose_from"] and str(choices[k]) not in map(str, f["choose_from"])]
    if bad:
        return {"error": "Not among the choices of list_choices: " + "; ".join(bad) + ". Nothing was costed."}
    import math
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
        return {"error": "These must be plain positive numbers (no units, no commas): " + "; ".join(wrong) + ". Nothing was costed."}
    try:
        out = s.cost(dict(choices))
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
        a = s.alerts()["all"].get(r.get("id"))
        if a:
            out["quote_alerts"] = {"state": a["state"], "flags": [f["text"] for f in a["flags"]],
                                   "note": "These flags are on the price of the mill's sheet" + (f" (Rs {r['price']:,.2f}); the tracker has since moved to Rs {price:,.2f}, so read them as history." if r.get("price") and abs(price - r["price"]) >= 0.005 else ".")}
    if r.get("duplicate_of"):
        twin = next((x for x in s.costs()["rows"] if x["source"] == r["source"] and x["code"] == r["duplicate_of"] and not x.get("duplicate_of")), None)
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
            "reading_the_figures": "This follows the tracker and is the tool to answer 'how much is at stake with this mill'. above_range = rupees above the top of the "
                                   "usual range on Push fabrics still to settle (the figure to push on). push_excess = rupees above should-cost on those same fabrics. "
                                   "unsure_high / unsure_high_excess = fabrics that look high but the tool is unsure of: ask for their break-up, never push a figure. "
                                   "below_saving, fair_excess, check_excess are shown apart and never netted. agreed / agreed_above_range = closed in the tracker. "
                                   "moved = open fabrics judged on a newer mill price than the sheet's. negotiations.won is ALREADY NET of negotiations.lost (lost is shown so a loss inside a gain is not hidden): "
                                   "report 'won X, after Y lost', never subtract again. sums_off compares the mill's own build-up with the price it asks now. Codes can repeat across rows: "
                                   "use find_fabrics for keys. Purchases are already paid: use them for the next order of the same cloth."}


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


@tool
def tracker_steps(key: str) -> dict:
    """The negotiation recorded on one fabric (key from find_fabrics): each step with the mill and where it stands."""
    s = _s()
    if _find(key) is None:
        return {"error": "No fabric with that key. Use find_fabrics to get the key."}
    rec = s._negos().get(key)
    if not rec or not rec.get("events"):
        return {"status": "Not tracked", "steps": [], "kinds_you_can_record": s.NEGO_KINDS}
    return dict(_nego(rec, s.nego_summary(rec)), kinds_you_can_record=s.NEGO_KINDS)


@tool(writes=True)
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
    rec0 = s._negos().get(key) or {}
    ev0 = s._nego_order(rec0.get("events", []))
    before = s.nego_summary(rec0) if ev0 else None
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
        rec = s.negotiation_event({"key": key, "kind": kind, "price": p, "date": date or None,
                                   "note": (str(note or "").strip()[:440] + " (recorded through the AI assistant)").strip(), "code": r["code"],
                                   "supplier": r.get("supplier"), "description": r.get("description"), "source": r["source"],
                                   "metres": r.get("metres"), "should": r.get("should"), "row_price": r.get("price")}, None, by="AI assistant")
    except Exception as e:
        return _fail(e)
    new = [w for w in rec["summary"]["warnings"] if not before or w not in before["warnings"]]
    return {"recorded": True, "warnings_on_this_step": new, "now": _nego(rec, rec["summary"]),
            "effects": "Everyone using RightPrice sees this step." + (" An agreed price also clears the fabric's quote alert and is counted in what was won." if kind == "Agreed" else "")}


@tool(writes=True, destroys=True)
def remove_my_tracker_step(key: str, kind: str, price_per_m: float, date: str = "") -> dict:
    """Undo a step THIS ASSISTANT recorded by mistake (steps recorded by a person on the screen cannot be removed here).
    Give the fabric's key and the kind and price of the step (and its date, YYYY-MM-DD, if two match). The mill's first
    quote cannot be removed while later steps rest on it. The removal is kept in the fabric's Log. Confirm with the
    person first."""
    s = _s()
    rec = s._negos().get(key) or {}
    mine = [e for e in rec.get("events", []) if e.get("by") == "AI assistant" and e["kind"] == kind and abs(e["price"] - float(price_per_m)) < 0.005 and (not date or e["date"] == date)]
    if not mine:
        return {"error": "No step with that kind and price recorded by the assistant on this fabric. Steps a person recorded are removed on the fabric's Negotiation tab."}
    ordered = s._nego_order(rec.get("events", []))
    quotes = [e for e in ordered if e["kind"] in ("Mill's quote", "Mill's revised quote")]
    if quotes and mine[-1]["id"] == quotes[0]["id"] and len(ordered) > 1:
        return {"error": "That is the mill's first quote, and the later steps are measured from it. Remove the later steps first (those the assistant recorded), "
                         "or have the person correct it on the fabric's Negotiation tab. Nothing was removed."}
    try:
        s.negotiation_remove({"key": key, "id": mine[-1]["id"]}, None)
    except Exception as e:
        return _fail(e)
    rec = s._negos().get(key) or {}
    return {"removed": True, "removed_step": {"kind": mine[-1]["kind"], "price_per_m": mine[-1]["price"], "date": mine[-1]["date"]}, "now": _nego(rec, s.nego_summary(rec)) if rec.get("events") else {"status": "Not tracked", "steps": []}}


@tool
def quote_alerts() -> dict:
    """Newly quoted fabrics that need a look before their price is accepted: above the usual range, the mill's own sums
    off, repeating an order already on the list, or far below should-cost. Newest upload first."""
    a = _s().alerts()
    return {"count": a["count"], "by_kind": {a["kinds"][k]: n for k, n in a["by_kind"].items()},
            "rupees_quoted_above_ranges": a["above_money"], "rupees_the_mills_own_sums_are_out": a["sums_money"],
            "note": "The two rupee figures largely overlap: do not add them. ALERTS ARE ON THE PRICES OF THE MILLS' SHEETS, as uploaded: where a fabric has a `tracker` entry the "
                    "mill has moved since, so its rupees here are history; use fabric_brief for where it stands. An alert clears when marked seen, or when the price is agreed.",
            "uploads": [{"mill": g["supplier"], "upload": g["upload"],
                         "fabrics": [{"key": r["key"], "code": r["code"], "flags": [f["text"] for f in r["flags"]], "tracker": _track(r["key"])} for r in g["rows"]]} for g in a["groups"]]}


if __name__ == "__main__":
    mcp.run()           # stdio: for an assistant on the same machine as the data
