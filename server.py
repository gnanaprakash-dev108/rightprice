"""RightPrice web server: the new front end (web/) and the JSON it reads.

Run: python -m uvicorn server:app --port 8000
The costing itself is unchanged: every number comes from masters.py and engine.py, and every
rate from the rate master workbook. There is no database.

The earlier Streamlit screens stay reachable under /classic (rate editing and the yarn price
intake still live there). This server starts Streamlit beside itself and passes /classic through.
"""
import asyncio
import datetime as dt
import io
import json
import math
import os
import re
import subprocess
import sys
from contextlib import asynccontextmanager

import httpx
import pandas as pd
import websockets
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import masters
import mill_sheet
import price_import as pi
import rate_card
import yarn_seed

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
PILOT = os.path.join(HERE, "pilot", "Pilot_Results.xlsx")
DRAFT = os.path.join(HERE, "pilot", "Proposed_Rate_Changes.xlsx")
CLASSIC_PORT = int(os.environ.get("RIGHTPRICE_CLASSIC_PORT", "8501"))
CLASSIC = f"127.0.0.1:{CLASSIC_PORT}"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOG_COLS = ["Saved on", "Fabric code", "Description", "Supplier", "Should-cost Rs/m", "Should-cost Rs/kg",
            "Quoted Rs/m", "Gap Rs/m", "Gap %"]
# sheet -> (label, group) for the read-only table pages
TABLES = {
    "Yarn_Rates": "Yarn master", "Market_Yarn": "Market reference", "Cotton_Prices": "Cotton prices",
    "Weaving_Rates": "Weaving", "Weaving_Uplifts": "Pattern and loom uplifts", "Sizing_Rates": "Sizing",
    "Yarn_Dyeing": "Yarn dyeing", "Piece_Dyeing": "Piece dyeing and printing", "Finishing_Rates": "Finishing",
    "Class_Defaults": "Crimp, wastage, overhead, margin", "Weaves": "Weave list",
    "Content_Groups": "Content groups", "Print_Methods": "Print method",
    "Dobby_Charges": "Dobby shafts and top beam", "Weft_Options": "Weft (yarn dyed)",
    "Quantity_Terms": "Rate card quantity", "Settings": "Calculation settings", "Mill_Tier": "Mill tiers",
    "Order_Slab": "Order size slabs", "Supplier_Benchmarks": "Supplier cost ratios",
}

_classic = None
_cache = {}


@asynccontextmanager
async def lifespan(_app):
    global _classic
    if os.environ.get("RIGHTPRICE_NO_CLASSIC") != "1":
        _classic = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "app.py"),
             "--server.port", str(CLASSIC_PORT), "--server.address", "127.0.0.1", "--server.headless", "true",
             "--server.baseUrlPath", "classic", "--server.enableCORS", "false",
             "--server.enableXsrfProtection", "false", "--browser.gatherUsageStats", "false"], cwd=HERE)
    yield
    if _classic:
        _classic.terminate()


app = FastAPI(title="RightPrice", lifespan=lifespan, docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ helpers
def cached(path, loader):
    """Reload a workbook only when the file on disk has changed (the classic screens can edit it)."""
    mtime = os.path.getmtime(path) if os.path.exists(path) else None
    hit = _cache.get(path)
    if not hit or hit[0] != mtime:
        _cache[path] = (mtime, loader())
    return _cache[path][1]


def get_masters():
    if not os.path.exists(masters.MASTER_PATH):
        masters.load()
    return cached(masters.MASTER_PATH, masters.load)


def clean(v):
    """A value JSON can carry: no NaN, no numpy or pandas types."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.isoformat()[:10]
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def records(df, limit=None):
    df = df if limit is None else df.tail(limit)
    return {"columns": [str(c) for c in df.columns],
            "rows": [[clean(v) for v in row] for row in df.itertuples(index=False, name=None)]}


def read_log():
    if os.path.exists(masters.LOG_PATH):
        return pd.read_csv(masters.LOG_PATH, dtype={"Id": str})
    return pd.DataFrame(columns=LOG_COLS)


def placeholder_count(m):
    return sum(int(df["Basis"].astype(str).str.startswith("Placeholder").sum())
               for df in m.values() if "Basis" in df.columns)


def sanity(inp, res):
    """Things a typing slip usually causes. The cost is still shown; these say why it may be wrong."""
    w, out = inp["width_in"], []
    if not 30 <= w <= 130:
        out.append(f"Finished width {w:g} inch is outside 30 to 130. Widths are in inches, not centimetres.")
    for name, key in (("EPI", "epi"), ("PPI", "ppi")):
        if not 20 <= inp[key] <= 400:
            out.append(f"{name} {inp[key]:g} is outside 20 to 400.")
    if inp["reed_in"] < w:
        out.append(f"Reed space {inp['reed_in']:g} inch is narrower than the finished width {w:g} inch.")
    elif inp["reed_in"] > w * 1.35:
        out.append(f"Reed space {inp['reed_in']:g} inch is more than 35% wider than the finished width {w:g} inch.")
    for name, key in (("Warp", "warp_ne"), ("Weft", "weft_ne")):
        if not 4 <= inp[key] <= 200:
            out.append(f"{name} count works out at Ne {inp[key]:.4g}, outside 4 to 200. Check the count and the count system.")
    if not 40 <= res["gsm"] <= 600:
        out.append(f"The fabric works out at about {res['gsm']:.0f} g/m2, outside 40 to 600. Check the counts, EPI and PPI.")
    return out


def yarn_sensitivity(res):
    """Rupees per metre that the price moves for each Rs 10 per kg on the warp yarn, and on the weft yarn."""
    i = res["inputs"]
    mult = (1 + i["process_wastage"] + i["overhead"]) * (1 + i["margin"]) / (1 - i["shrinkage"]) * (1 + i.get("small_lot_pct", 0.0))
    # carry: the share of a yarn price move that reaches the fabric price. It is larger than yarn's own
    # share of the cost, because losses, overhead and margin are charged on the yarn too.
    return {"warp_per_10": res["warp_kg"] * mult * 10, "weft_per_10": res["weft_kg"] * mult * 10,
            "warp_rate": i["warp_rate"], "weft_rate": i["weft_rate"],
            "yarn_share": (res["warp_kg"] * i["warp_rate"] + res["weft_kg"] * i["weft_rate"]) * mult / res["total_per_m"] if res["total_per_m"] else 0.0}


# The quote is "in line" when it sits inside the range where three in four past purchases of the same fabric
# type landed against their should-cost (the middle half of panel 1, upper and lower quarter), never
# narrower than 5% either way and never wider than 10%. Without purchase history: 5% either way.
BAND_MIN, BAND_MAX = 5.0, 10.0
# A placeholder rate stops the brief naming a target only when the costs resting on it are more than this
# share of the price; below it, a placeholder off by half moves the should-cost by under 5%.
PLACEHOLDER_SHARE_LIMIT = 0.10
# Rate items whose cost shows on more than one line of the cost table
PLACEHOLDER_LINES = {"Finishing": ("Finishing", "Finish upcharge")}


def _qty_range(label):
    """'500 to 599 m' -> (500, 599); 'Below 1,000 m' -> (0, 999.99); 'Above 6,000 m' -> (6000.01, inf)."""
    s = str(label).replace(",", "").lower()
    n = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not n:
        return None
    if s.startswith("below"):
        return (0.0, n[0] - 0.01)
    if s.startswith("above"):
        return (n[0] + 0.01, math.inf)
    if "and above" in s:
        return (n[0], math.inf)
    if " to " in s and len(n) == 2:
        return (n[0], n[1])
    return None


def quantity_check(res, sel, m, quantity, notes=()):
    """Is the order quantity inside the quantity band the cost was worked on? (None, None) when it is,
    else (the reason, the band that fits)."""
    if not quantity or sel is None:
        return None, None
    qband = str(sel.get("Rate card quantity") or rate_card.NO_QTY)
    if qband != rate_card.NO_QTY:
        field, band, options = "Rate card quantity", qband, m["Quantity_Terms"]["Quantity band"].tolist()[1:]
        yd = sel.get("Route") == "Yarn Dyed"
        small = set(m["Quantity_Terms"][m["Quantity_Terms"]["Small-lot upcharge %"] > 0]["Quantity band"])
        if not yd:
            options = [o for o in options if o not in small]
        # a mill sheet that charges nothing for a small lot is costed on 800 to 1,999 m on purpose
        if band == "800 to 1,999 m" and 500 <= quantity < 800 and any("no small-lot upcharge" in str(x) for x in notes):
            return None, None
    else:
        field = "Order size"
        band = next((str(u["Choice"]) for u in res["rates_used"] if u["Item"] == "Order size"), str(sel.get("Order size") or ""))
        options = m["Order_Slab"]["Order size"].tolist()
    r = _qty_range(band)
    if r is None or r[0] <= quantity <= r[1]:
        return None, None
    fits = next((o for o in options if (lambda q: q is not None and q[0] <= quantity <= q[1])(_qty_range(o))), None)
    where = "the quantity band (mill rate card)" if field == "Rate card quantity" else "the order size"
    why = (f"the order quantity, {quantity:,.0f} m, is outside {where} the cost is worked on ({band}, step 6), "
           "so the should-cost is for a different order size")
    return why, ({"field": field, "value": fits} if fits else None)


def _placeholder_share(res):
    """Share of the price that rests on placeholder rates, with losses, overhead and margin on them.
    None when a placeholder cannot be found in the cost lines (then it is treated as large)."""
    names = set(res["placeholders"])
    if not names:
        return 0.0
    i, total = res["inputs"], res["total_per_m"]
    mult = (1 + i["process_wastage"] + i["overhead"]) * (1 + i["margin"]) / (1 - i["shrinkage"]) * (1 + i.get("small_lot_pct", 0.0))
    found, amount = set(), 0.0
    for b in res["buckets"]:
        for l in b["lines"]:
            owner = next((n for n in names if l["name"] in PLACEHOLDER_LINES.get(n, (n,))), None)
            if owner:
                found.add(owner)
                amount += abs(l["amount"]) * (1.0 if b["name"] == "Upcharges and quantity terms" else mult)
    if found != names or not total:
        return None
    return amount / total


def brief(res, m, quantity=None, notes=(), sel=None):
    """What a buyer takes into the meeting for one fabric with a quote on it.

    The tool does not know the mill's break-up, so it cannot say where the quote differs. It can say
    what would have to be true for the quote to be right: the yarn rate, the weaving rate or the
    margin that, alone, would close the gap. Each is set beside the figure in the rate master.

    Every comparison is made on the figures as printed (rupees to the paisa), so what the brief says
    can be checked with the numbers on the page.
    """
    if res["quote"] is None or res["quote"] <= 0:
        return None
    i = res["inputs"]
    should, quote = round(res["total_per_m"], 2), round(res["quote"], 2)
    gap = round(quote - should, 2)
    lot = 1 + i.get("small_lot_pct", 0.0)
    before = (1 + i["process_wastage"] + i["overhead"]) / (1 - i["shrinkage"]) * lot        # mark-up before margin
    mult = before * (1 + i["margin"])
    yarn_cost = res["warp_kg"] * i["warp_rate"] + res["weft_kg"] * i["weft_rate"]
    f = 1 + gap / (yarn_cost * mult) if yarn_cost else None
    cost_before_margin = (res["total_per_m"] + i.get("volume_discount_per_m", 0.0)) / (1 + i["margin"])      # close enough: upcharges are small
    grp = dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"]))
    route = next((u["Choice"].split(", ")[1] for u in res["rates_used"] if u["Item"] == "Weaving" and ", " in str(u["Choice"])), None)
    basis = {u["Item"]: str(u["Basis"]) for u in res["rates_used"]}
    is_ph = lambda item: basis.get(item, "").startswith("Placeholder")
    weak, caveats, ph_share = [], [], None

    # placeholders: weighed by the share of the price that rests on them
    if res["placeholders"]:
        share = _placeholder_share(res)
        names = ", ".join(res["placeholders"])
        if share is None or share > PLACEHOLDER_SHARE_LIMIT:
            weak.append(f"placeholder rates are used for {names}" + ("" if share is None else f", and {share:.0%} of the price rests on them"))
        else:
            ph_share = share           # whether the advice stands is decided once the range is known, below

    # the fit of this fabric type, in the dashboard's own figures (panel 1)
    cat, typ = None, None
    ins = _cache.get(PILOT + "#insights")
    if ins and ins[1]:
        weave = next((u["Choice"].split(" (")[0] for u in res["rates_used"] if u["Item"] == "Weaving"), None)
        cat = next((c for c in ins[1]["categories"] if c["route"] == route and c["weave"] == grp.get(weave)), None)
        g = str(grp.get(weave) or weave or "")
        typ = f"{(route or '').lower()} {g.lower()}".strip()
        if weave and g and g.lower() not in str(weave).lower():
            typ_named = f"{(route or '').lower()} {str(weave).lower()} (counted with {g.lower()})"
        else:
            typ_named = typ
        if cat is None:
            weak.append(f"there are too few purchases of {typ_named} fabrics to test the tool on")
        elif cat["trust"] == "weak":
            weak.append(f"on {typ} the tool is within 10% of the price paid for only {cat['within10']:.0%} of the "
                        f"{cat['fabrics']} fabrics bought, and they were paid {cat['gap']:+.1f}% against should-cost on "
                        "average (dashboard panel 1)")

    hi = BAND_MIN if cat is None else min(BAND_MAX, max(BAND_MIN, cat["p75"]))
    lo = -BAND_MIN if cat is None else max(-BAND_MAX, min(-BAND_MIN, cat["p25"]))
    upper, lower = round(should * (1 + hi / 100), 2), round(should * (1 + lo / 100), 2)
    if cat is None:
        band_why = "5% either side of should-cost" + ("" if ins and ins[1] else " (there is no purchase history on this server to set it from)")
    else:
        fit = (f"half of the {cat['fabrics']} {typ} fabrics you bought were priced between {cat['p25']:+.1f}% and "
               f"{cat['p75']:+.1f}% against should-cost (dashboard panel 1, middle half)")
        band_why = fit + (f"; the tool never counts more than {BAND_MAX:.0f}% above as in line" if cat["p75"] > BAND_MAX else
                          f"; the tool always allows {BAND_MIN:.0f}% either way" if cat["p75"] < BAND_MIN or cat["p25"] > -BAND_MIN else "")

    why_qty, qty_fix = quantity_check(res, sel, m, quantity, notes)
    qty_only = False
    if why_qty:
        same = False
        if qty_fix:
            try:
                alt = dict(sel, **{qty_fix["field"]: qty_fix["value"]})
                if qty_fix["field"] == "Order size":
                    alt["Rate card quantity"] = rate_card.NO_QTY
                same = abs(masters.cost(alt, m)["total_per_m"] - res["total_per_m"]) < 0.005
            except Exception:
                same = False
        if not same:
            qty_only = not weak
            weak.insert(0, why_qty)
        else:
            qty_fix = None
    stance = "ask" if weak else ("push" if quote > upper else ("below" if quote < lower else "fair"))
    if ph_share is not None:
        swing = round(should * ph_share / 2, 2)            # a placeholder off by half moves the should-cost this much
        edge = min(abs(quote - upper), abs(quote - lower))
        if stance != "ask" and edge <= swing * (1 + hi / 100) + 0.005:
            caveats.append(f"A placeholder rate is used for {', '.join(res['placeholders'])}; {ph_share:.1%} of the price rests on it. "
                           f"If it were off by half the should-cost would move by up to Rs {swing:,.2f}, and this quote is only "
                           f"Rs {edge:,.2f} from the edge of the usual range, so the advice could change: ask for the mill's charge for it first.")
        else:
            caveats.append(f"A placeholder rate is used for {', '.join(res['placeholders'])}, but only {ph_share:.1%} of the price rests on it: "
                           f"even if it were off by half, the should-cost would move by up to Rs {swing:,.2f}, which would not change the advice.")
    if gap / should < -0.30 if should else False:
        caveats.insert(0, f"The quote is {abs(gap / should):.0%} below should-cost. That is almost always a different cloth, a typing slip "
                          "or a price per something other than a metre; check it before treating it as a saving.")
    near = stance == "push" and quote - upper <= 0.02 * should
    for n in notes or ():
        if "small-lot upcharge" not in str(n):
            caveats.insert(0, "From the mill's sheet: " + str(n)[0].upper() + str(n)[1:] + ".")
    return {
        "quote": quote, "should": should, "gap": gap, "gap_pct": gap / should if should else 0.0,
        "stance": stance, "weak": weak, "caveats": caveats, "qty_fix": qty_fix, "qty_only": qty_only, "near_edge": near,
        "open_at": should, "settle_up_to": upper, "lower": lower, "above_band": round(quote - upper, 2),
        "band": {"hi": hi / 100, "lo": lo / 100, "why": band_why},
        "fit": None if cat is None else {"type": typ, "fabrics": cat["fabrics"], "within10": cat["within10"], "gap": cat["gap"],
                                          "p25": cat["p25"], "p75": cat["p75"]},
        "quantity": quantity, "at_stake": None if quantity is None else round(gap * quantity, 0),
        "would_need": {
            "yarn": None if f is None else {"warp": i["warp_rate"] * f, "weft": i["weft_rate"] * f, "warp_now": i["warp_rate"],
                                             "weft_now": i["weft_rate"], "pct": (f - 1) * 100,
                                             "placeholder": is_ph("Warp yarn") or is_ph("Weft yarn")},
            "weaving": {"rate": i["weaving_rate"] + gap / mult / i["ppi"], "now": i["weaving_rate"], "placeholder": is_ph("Weaving"),
                        "per_m_before": gap / mult, "picks": i["ppi"]},
            "margin": {"rate": (quote + i.get("volume_discount_per_m", 0.0)) / cost_before_margin - 1, "now": i["margin"],
                       "placeholder": is_ph("Crimp, wastage, overhead, margin")},
        },
    }


def result_json(res, quantity=None, notes=(), sel=None):
    return {
        "brief": brief(res, get_masters(), quantity, notes, sel),
        "warnings": sanity(res["inputs"], res),
        "yarn": yarn_sensitivity(res),
        "total_per_m": res["total_per_m"], "per_kg": res["per_kg"], "gsm": res["gsm"],
        "finished_g_per_m": res["finished_g_per_m"], "quote": res["quote"], "gap": res["gap"],
        "gap_pct": res["gap_pct"], "placeholders": res["placeholders"],
        "buckets": [{"name": b["name"], "amount": b["amount"], "pct": b["pct"],
                     "lines": [{"name": l["name"], "basis": l["basis"], "amount": l["amount"]} for l in b["lines"]]}
                    for b in res["buckets"]],
        "rates_used": [{k: (v if isinstance(v, str) else clean(v)) for k, v in u.items()} for u in res["rates_used"]],
    }


def cost_or_400(sel, m):
    try:
        return masters.cost({k: v for k, v in sel.items() if v not in ("", None)}, m)
    except Exception as e:      # a choice not on a list, a missing number: tell the user which
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ API
@app.get("/api/meta")
def meta():
    m = get_masters()
    yr = m["Yarn_Rates"]
    return {
        "lists": masters.lists(m),
        "weave_group": dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"])),
        "yarns": [{"key": r["Yarn key"], "rate": clean(r["Rate Rs/kg"]), "ne": clean(r["Count Ne (resultant)"]),
                   "basis": str(r["Basis"]), "date": clean(r["Rate date"]), "blend": str(r["Blend"]),
                   "content": yarn_seed.content_of(r["Blend"])} for _, r in yr.iterrows()],
        "contents": list(yarn_seed.CONTENTS),
        "editable": sorted(EDITABLE),
        "example": masters.EXAMPLE_ROW,
        "template_columns": [{"name": c, "list": l, "required": r} for c, l, r in masters.TEMPLATE_COLUMNS],
        "tables": TABLES,
        "small_lot_bands": m["Quantity_Terms"][m["Quantity_Terms"]["Small-lot upcharge %"] > 0]["Quantity band"].tolist(),
        "placeholders": placeholder_count(m),
    }


def _warm_pilot():
    if PILOT + "#insights" not in _cache and os.path.exists(PILOT):
        try:
            insights()
        except Exception:
            pass


def _quantity_or_400(v):
    q = _num_or_none(v)
    if q is not None and q < 0:
        raise HTTPException(400, "Order quantity cannot be negative")
    return q or None


@app.post("/api/cost")
def cost(sel: dict = Body(...)):
    """One fabric costed. '_notes' (optional) are the remarks of the list row it was opened from, carried
    into the negotiation brief; they are not choices and do not change the cost."""
    _warm_pilot()
    sel = dict(sel)
    notes = sel.pop("_notes", None) or []
    qty = _quantity_or_400(sel.get("Order quantity (m)"))
    m = get_masters()
    out = result_json(cost_or_400(sel, m), qty, notes=notes, sel=sel)
    q = _num_or_none(sel.get("Quoted price (Rs/m)"))
    if q is not None and q <= 0:
        out["warnings"].append(f"A quote of Rs {q:g} is not a price, so it is ignored: no negotiation brief is given.")
    return out


@app.post("/api/cost-sheet")
def cost_sheet(sel: dict = Body(...)):
    res = cost_or_400(sel, get_masters())
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summ = [("Fabric code", sel.get("Fabric code")), ("Description", sel.get("Description")),
                ("Supplier", sel.get("Supplier")), ("Should-cost Rs/m", round(res["total_per_m"], 2)),
                ("Should-cost Rs/kg", round(res["per_kg"], 1)), ("Approx. GSM", round(res["gsm"], 1)),
                ("Quoted Rs/m", res["quote"]), ("Gap Rs/m", None if res["gap"] is None else round(res["gap"], 2))]
        summ += [(b["name"] + " Rs/m", round(b["amount"], 2)) for b in res["buckets"]]
        pd.DataFrame(summ, columns=["Item", "Value"]).to_excel(xw, sheet_name="Cost view", index=False)
        lines = [{"Bucket": b["name"], "Line": l["name"], "How it is worked out": l["basis"],
                  "Rs/m": round(l["amount"], 2)} for b in res["buckets"] for l in b["lines"]]
        pd.DataFrame(lines).to_excel(xw, sheet_name="Second level", index=False)
        pd.DataFrame(res["rates_used"]).astype(str).to_excel(xw, sheet_name="Rates used", index=False)
        pd.DataFrame([{"Input": k, "Value": v} for k, v in sel.items()]).astype(str).to_excel(
            xw, sheet_name="Inputs", index=False)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Should cost.xlsx"'})


# ------------------------------------------------------------------ the fabric list
# One list holds every fabric costed here: added one at a time from Cost a fabric, or many at once
# from an upload (the RightPrice template, or a mill's own price sheet). It is kept in a small file
# beside the rate master, and each row is re-costed on today's rates whenever the list is shown.
LIST_COLS = LOG_COLS + ["Id", "Inputs", "Result", "Mill", "Problems", "Notes"]


def _then(res):
    return json.dumps({"total_per_m": res["total_per_m"],
                       "buckets": [{"name": b["name"], "amount": b["amount"]} for b in res["buckets"]],
                       "rates": [{"Item": u["Item"], "Choice": str(u["Choice"]),
                                  "Value": u["Value"] if isinstance(u["Value"], str) else clean(u["Value"]),
                                  "Unit": u["Unit"]} for u in res["rates_used"]]})


def _list_row(sel, m, mill=None, problems=(), notes=(), n=0):
    """One list row. A fabric that cannot be costed yet is kept, with the reason, and no cost."""
    now = dt.datetime.now()
    sel = {k: (v if isinstance(v, str) else clean(v)) for k, v in sel.items() if v not in ("", None)}
    problems, res = list(problems), None
    if not problems:
        try:
            res = masters.cost(sel, m)
        except Exception as e:
            problems.append(str(e))
    return {"Saved on": now.date().isoformat(), "Fabric code": sel.get("Fabric code"), "Description": sel.get("Description"),
            "Supplier": sel.get("Supplier"),
            "Should-cost Rs/m": None if res is None else round(res["total_per_m"], 2),
            "Should-cost Rs/kg": None if res is None else round(res["per_kg"], 1),
            "Quoted Rs/m": sel.get("Quoted price (Rs/m)"),
            "Gap Rs/m": None if res is None or res["gap"] is None else round(res["gap"], 2),
            "Gap %": None if res is None or res["gap_pct"] is None else round(res["gap_pct"] * 100, 1),
            "Id": f"{now:%Y%m%d%H%M%S%f}{n:04d}", "Inputs": json.dumps(sel), "Result": None if res is None else _then(res),
            "Mill": json.dumps(mill) if mill else None, "Problems": json.dumps(problems) if problems else None,
            "Notes": json.dumps(list(notes)) if notes else None}


def _num_or_none(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _write_list(df):
    os.makedirs(os.path.dirname(masters.LOG_PATH), exist_ok=True)
    df.to_csv(masters.LOG_PATH, index=False)


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) and v else default
    except ValueError:
        return default


@app.post("/api/save")
@app.post("/api/list/add")
def list_add(sel: dict = Body(...)):
    """Add the fabric on Cost a fabric to the list. With '_id' it takes the place of that row (its mill columns stay)."""
    sel = dict(sel)
    replace = str(sel.pop("_id", "") or "")
    m = get_masters()
    cost_or_400(sel, m)                      # a fabric typed on screen must cost before it is listed
    log = read_log()
    mill = None
    if replace and "Id" in log.columns and (log["Id"].astype(str) == replace).any():
        old = log[log["Id"].astype(str) == replace].iloc[0]
        mill = _loads(old.get("Mill"), None)
        log = log[log["Id"].astype(str) != replace]
    row = _list_row(sel, m, mill=mill)
    _write_list(pd.concat([log, pd.DataFrame([row])], ignore_index=True))
    return {"saved": True, "id": row["Id"]}


@app.post("/api/list/upload")
async def list_upload(file: UploadFile = File(...)):
    """Many fabrics at once: the RightPrice template, or a mill's price sheet as it comes."""
    m = get_masters()
    data = await file.read()
    try:
        book = pd.read_excel(io.BytesIO(data), sheet_name=None)
    except Exception as e:
        raise HTTPException(400, f"Could not read this file as an Excel workbook: {e}")
    rows, kind = [], None
    for name, df in book.items():
        df = df.rename(columns=lambda c: str(c).strip()).dropna(how="all")
        if mill_sheet.is_mill_sheet(df):
            kind = "mill sheet"
            for n, (_, r) in enumerate(df.iterrows()):
                r = r.to_dict()
                if all(mill_sheet._blank(r.get(c)) for c in ("Fab Code", "EPI", "PPI", "Warp")):
                    continue
                sel, problems, notes = mill_sheet.to_inputs(r, m)
                rows.append(_list_row(sel, m, mill=mill_sheet.clean_row(r), problems=problems, notes=notes, n=n))
            break
        if {"Fabric code", "Route", "EPI", "PPI"} <= set(df.columns):
            kind = "RightPrice template"
            for n, (_, r) in enumerate(df.iterrows()):
                rows.append(_list_row({k: v for k, v in r.to_dict().items() if not mill_sheet._blank(v)}, m, n=n))
            break
    if kind is None:
        raise HTTPException(400, "No sheet in this file has the headings of the RightPrice template (Fabric code, Route, "
                                 "EPI, PPI) or of a mill price sheet (Fab Code, Base Price, EPI, PPI)")
    if not rows:
        raise HTTPException(400, "The sheet has the right headings but no fabric rows")
    log = read_log()
    have = set()
    for col, key in (("Mill", None), ("Inputs", None)):
        if col in log.columns:
            have |= {v for v in log[col].dropna().astype(str)}
    fresh = [r for r in rows if (r["Mill"] or r["Inputs"]) not in have]
    if fresh:
        _write_list(pd.concat([log, pd.DataFrame(fresh)], ignore_index=True))
    return {"added": len(fresh), "already": len(rows) - len(fresh), "kind": kind, "not_costed": sum(1 for r in fresh if r["Problems"])}


@app.post("/api/list")
def list_view(options: dict = Body(default={})):
    """The list, newest first, each row re-costed on today's rates. options.yarn_pct = {yarn key or '*': % change}
    also costs every row with those yarn rates moved, to show what a yarn price move would do."""
    m = get_masters()
    _warm_pilot()
    moves = {k: float(v) for k, v in (options.get("yarn_pct") or {}).items() if v not in ("", None) and float(v) != 0}
    if any(abs(v) > 50 for v in moves.values()):
        raise HTTPException(400, "A yarn move is limited to 50% either way")
    sim = None
    if moves:
        sim = dict(m)
        yr = m["Yarn_Rates"].copy()
        yr["Rate Rs/kg"] = [float(r) * (1 + moves.get(k, moves.get("*", 0.0)) / 100) for k, r in zip(yr["Yarn key"], yr["Rate Rs/kg"])]
        sim["Yarn_Rates"] = yr
    out = []
    log = read_log().iloc[::-1]
    for _, r in log.iterrows():
        inputs, problems = _loads(r.get("Inputs"), None), _loads(r.get("Problems"), [])
        mill = _loads(r.get("Mill"), None)
        item = {"id": None if pd.isna(r.get("Id")) else str(r.get("Id")).split(".")[0], "added": clean(r.get("Saved on")),
                "inputs": inputs, "then": _loads(r.get("Result"), None), "notes": _loads(r.get("Notes"), []),
                "from_mill": mill is not None, "mill": mill or (mill_sheet.from_choices(inputs) if inputs else {}),
                "sums": mill_sheet.check_sums(mill) if mill else None, "problems": problems,
                "should_cost": None, "gap": None, "gap_pct": None, "placeholders": [], "simulated": None, "sim_gap": None,
                "sim_gap_pct": None, "quantity": None, "at_stake": None, "brief": None,
                "supplier": clean(r.get("Supplier")), "description": clean(r.get("Description"))}
        if inputs is None:                   # a costing saved before choices were kept: shown, not re-costed
            item["should_cost"], item["mill"] = clean(r.get("Should-cost Rs/m")), {"Fab Code": clean(r.get("Fabric code")), "Ex mill price": clean(r.get("Quoted Rs/m"))}
            item["problems"] = ["saved before choices were kept; it cannot be re-costed or opened"]
        elif not problems:
            try:
                res = masters.cost(inputs, m)
                item.update(should_cost=res["total_per_m"], per_kg=res["per_kg"], gsm=res["gsm"], gap=res["gap"],
                            gap_pct=res["gap_pct"], placeholders=res["placeholders"], yarn=yarn_sensitivity(res))
                qty = _num_or_none((mill or {}).get("Total order qnty")) or _num_or_none(inputs.get("Order quantity (m)"))
                qty = qty if qty and qty > 0 else None          # a negative or zero quantity puts nothing at stake
                item["quantity"] = qty
                item["brief"] = brief(res, m, qty, item["notes"], inputs)
                item["at_stake"] = None if item["brief"] is None else item["brief"]["at_stake"]
                if sim is not None:
                    moved = masters.cost(inputs, sim)
                    item.update(simulated=moved["total_per_m"], sim_gap=moved["gap"], sim_gap_pct=moved["gap_pct"])
            except Exception as e:
                item["problems"] = [str(e)]
        out.append(item)
    return {"columns": mill_sheet.COLUMNS, "groups": mill_sheet.GROUPS, "rows": out,
            "yarns_in_use": sorted({i["inputs"][k] for i in out if i["inputs"] for k in ("Warp yarn", "Weft yarn") if i["inputs"].get(k)})}


@app.post("/api/list/remove")
def list_remove(payload: dict = Body(...)):
    ids = {str(i) for i in payload.get("ids", [])}
    log = read_log()
    if "Id" not in log.columns or not ids:
        raise HTTPException(400, "Choose the rows to remove")
    keep = log[~log["Id"].astype(str).isin(ids)]
    _write_list(keep)
    return {"removed": len(log) - len(keep)}


# ------------------------------------------------------------------ negotiation pack
def _stance_for(b, gap_pct):
    """The stance of a row once its gap has moved (a yarn move): the same range, the new gap."""
    if b["stance"] == "ask":
        return "ask"
    return "push" if gap_pct > b["band"]["hi"] + 1e-9 else ("below" if gap_pct < b["band"]["lo"] - 1e-9 else "fair")


def _questions(r, b, stance, own_gap):
    """What to ask the mill about one row, most useful first."""
    q = []
    code = r["mill"].get("Fab Code") or "this fabric"
    if own_gap is not None and abs(own_gap) >= 0.01:
        q.append(f"Your own sums for {code} give Rs {r['own_price']:,.2f}, not Rs {r['quote']:,.2f}: "
                 + ("which is right?" if own_gap > 0 else "confirm the lower figure stands."))
    elif r["sums"] and own_gap is not None:
        q.append(f"Correct the sheet for {code}: {'; '.join(r['sums'])}. The ex-mill price itself agrees with the sums.")
    if stance == "push":
        w = b["would_need"]
        alts = []
        if w["yarn"] and not w["yarn"]["placeholder"]:
            alts.append(f"yarn at about Rs {w['yarn']['warp']:,.0f} a kilo (master Rs {w['yarn']['warp_now']:,.0f})")
        if not w["weaving"]["placeholder"]:
            alts.append(f"weaving at about Rs {w['weaving']['rate']:.3f} a pick (master Rs {w['weaving']['now']:.3f})")
        if not w["margin"]["placeholder"]:
            alts.append(f"a margin of about {w['margin']['rate']:.1%} (master {w['margin']['now']:.1%})")
        q.append(f"{code} is Rs {r['above_band']:,.2f} a metre above the top of the usual range (Rs {r['upper']:,.2f}). "
                 "Show where it comes from" + (": " + "; or ".join(alts) + "?" if alts else "."))
    elif stance == "ask":
        q.append(f"Send the break-up for {code} (yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish, "
                 f"margin) before a price is named. Why: {b['weak'][0]}.")
    elif stance == "below":
        q.append(f"{code} is below the usual range: confirm the yarn, the construction and the finish are as specified.")
    for n in r["notes"]:
        if "second yarn" in n:
            q.append(f"{code}: name the second yarn in {n.split(chr(39))[1] if chr(39) in n else 'the warp or weft'} and its rate.")
        elif "not recognised" in n:
            q.append(f"{code}: {n[0].upper() + n[1:]}. Which finish is it, and what does it add?")
    return q


@app.post("/api/pack")
def pack(options: dict = Body(default={})):
    """The negotiation pack for a whole mill sheet (or the rows asked for): every row with its stance, the
    money at stake, the mill's sums that are off and the questions to ask, plus the sheet's totals.
    options: ids (the rows; default every row), yarn_pct (a yarn move, as on the list)."""
    v = list_view({"yarn_pct": options.get("yarn_pct")} if options.get("yarn_pct") else {})
    ids = {str(i) for i in (options.get("ids") or [])}
    chosen = [r for r in v["rows"] if not ids or r["id"] in ids]
    if not chosen:
        raise HTTPException(400, "There are no rows to put in the pack")
    rows, not_costed = [], []
    for r in chosen:
        code = r["mill"].get("Fab Code") or (r["inputs"] or {}).get("Fabric code") or "(no code)"
        desc = r["description"] or " ".join(str(r["mill"].get(c)) for c in ("Weave", "Variety") if r["mill"].get(c))
        own_price, own_gap = mill_sheet.own_sums(r["mill"]) if r["from_mill"] else (None, None)
        b = r["brief"]
        if r["problems"] or b is None:
            not_costed.append({"code": code, "description": desc, "why": "; ".join(r["problems"]) or "no mill price on this row",
                               "sums": r["sums"] or [], "own_price": own_price, "own_gap": own_gap})
            continue
        moved = r["simulated"] is not None
        should = round(r["simulated"], 2) if moved else b["should"]
        gap = round(b["quote"] - should, 2)
        gap_pct = gap / should if should else 0.0
        stance = _stance_for(b, gap_pct) if moved else b["stance"]
        upper = round(should * (1 + b["band"]["hi"]), 2)
        qty = r["quantity"]
        row = {"id": r["id"], "code": code, "description": desc, "supplier": r["supplier"], "quantity": qty,
               "quote": b["quote"], "should": should, "gap": gap, "gap_pct": gap_pct, "stance": stance,
               "upper": upper, "above_band": round(b["quote"] - upper, 2),
               "at_stake": None if qty is None else round(gap * qty), "weak": b["weak"], "caveats": b["caveats"],
               "sums": r["sums"] or [], "own_price": own_price, "own_gap": own_gap,
               "own_at_stake": None if own_gap is None or qty is None else round(own_gap * qty),
               "notes": r["notes"], "mill": r["mill"]}
        row["questions"] = _questions(row, b, stance, own_gap if row["sums"] else None)
        rows.append(row)
    staked = [r for r in rows if r["at_stake"] is not None]
    by = lambda st: [r for r in rows if r["stance"] == st]
    sums_rows = [r for r in rows + not_costed if r["sums"]]
    totals = {
        "rows": len(chosen), "costed": len(rows), "not_costed": len(not_costed),
        "metres": sum(r["quantity"] or 0 for r in rows),
        "at_mill_price": round(sum(r["quote"] * r["quantity"] for r in staked)),
        "at_should_cost": round(sum(r["should"] * r["quantity"] for r in staked)),
        "push_stake": sum(r["at_stake"] for r in by("push") if r["at_stake"] is not None),
        "push_above_range": round(sum(r["above_band"] * r["quantity"] for r in by("push") if r["quantity"])),
        "ask_stake": sum(r["at_stake"] for r in by("ask") if r["at_stake"] is not None and r["at_stake"] > 0),
        "savings": -sum(r["at_stake"] for r in by("below") if r["at_stake"] is not None),
        "sums_off": len(sums_rows),
        "sums_money": sum(r.get("own_at_stake") or 0 for r in rows if r["sums"] and (r.get("own_at_stake") or 0) > 0),
        "count": {st: len(by(st)) for st in ("push", "ask", "fair", "below")},
        "no_quantity": sum(1 for r in rows if r["quantity"] is None),
    }
    lead = sorted([r for r in by("push") if r["at_stake"]], key=lambda r: -r["at_stake"])[:3]
    suppliers = sorted({r["supplier"] for r in chosen if r["supplier"]})
    sheets = {}         # the list's rows by supplier and the day they were added: one uploaded sheet each, as a rule
    for r in v["rows"]:
        key = f"{r['supplier'] or 'No supplier'} \u00b7 added {str(r['added'] or '')[:10]}"
        sheets.setdefault(key, []).append(r["id"])
    return {"rows": rows, "not_costed": not_costed, "totals": totals, "lead": [r["code"] for r in lead],
            "sheets": [{"label": k, "ids": i} for k, i in sheets.items()],
            "suppliers": suppliers, "added": sorted({str(r["added"])[:10] for r in chosen if r["added"]}),
            "moved": v["rows"] and any(r["simulated"] is not None for r in v["rows"]),
            "yarn_pct": options.get("yarn_pct") or None}


@app.post("/api/list/download")
def list_download(options: dict = Body(default={})):
    v = list_view(options)
    rows = []
    for i in v["rows"]:
        row = {c: i["mill"].get(c) for c in v["columns"]}
        row.update({"Should-cost Rs/m": None if i["should_cost"] is None else round(i["should_cost"], 2),
                    "Mill price above should-cost Rs/m": None if i["gap"] is None else round(i["gap"], 2),
                    "Mill price above should-cost %": None if i["gap_pct"] is None else round(i["gap_pct"] * 100, 1),
                    "Should-cost with yarn moved Rs/m": None if i["simulated"] is None else round(i["simulated"], 2),
                    "Mill's sums": "" if i["sums"] is None else ("add up" if not i["sums"] else "; ".join(i["sums"])),
                    "Not costed because": "; ".join(i["problems"]), "Notes": "; ".join(i["notes"]),
                    "Placeholder rates used": ", ".join(i["placeholders"]), "Added on": i["added"]})
        rows.append(row)
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="RightPrice_fabric_list.xlsx"'})


@app.delete("/api/saved/{saved_id}")
def delete_saved(saved_id: str):
    if list_remove({"ids": [saved_id]})["removed"] == 0:
        raise HTTPException(404, "That row is no longer in the list")
    return {"deleted": True}


@app.get("/api/dashboard")
def dashboard():
    m = get_masters()
    log = read_log()
    gaps = pd.to_numeric(log["Gap %"], errors="coerce").dropna()
    cot = m["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    cotton = None
    if len(cot):
        last = cot.iloc[-1]
        prev = cot[cot["Date"] <= last["Date"] - pd.Timedelta(days=30)]
        cotton = {"price": clean(last["Price"]), "date": clean(last["Date"]), "source": str(last["Source"]),
                  "change_30d": None if prev.empty else float(last["Price"]) / float(prev.iloc[-1]["Price"]) - 1,
                  "age_days": int((pd.Timestamp.today() - last["Date"]).days)}
    mk = m["Market_Yarn"]
    cc = mk[mk["Yarn"] == "Cotton combed compact"]
    yarns = []
    for _, y in m["Yarn_Rates"].iterrows():
        if str(y["Blend"]) != "Cotton":
            continue
        hit = cc[cc["Count"].astype(str).str.lower() == str(y["Count"]).lower()]
        lo, hi = (float(hit["Low Rs/kg"].iloc[0]), float(hit["High Rs/kg"].iloc[0])) if len(hit) else (None, None)
        rate = float(y["Rate Rs/kg"])
        pos = None if lo is None else ("inside" if lo <= rate <= hi else ("above" if rate > hi else "below"))
        yarns.append({"key": y["Yarn key"], "rate": rate, "date": clean(y["Rate date"]), "basis": str(y["Basis"]),
                      "market_low": lo, "market_high": hi, "position": pos})
    shown = log.iloc[::-1].reset_index(drop=True)
    items = []          # one per saved costing, newest first: its id and choices where it has them
    for _, r in shown.iterrows():
        raw = r.get("Inputs")
        try:
            inputs = json.loads(raw) if isinstance(raw, str) and raw else None
        except ValueError:
            inputs = None
        try:
            then = json.loads(r.get("Result")) if isinstance(r.get("Result"), str) and r.get("Result") else None
        except ValueError:
            then = None
        items.append({"id": None if pd.isna(r.get("Id")) else str(r.get("Id")).split(".")[0], "inputs": inputs,
                      "then": then, "saved_on": clean(r.get("Saved on"))})
    return {"saved": records(shown[[c for c in LOG_COLS if c in shown.columns]]), "saved_items": items,
            "saved_count": len(log),
            "avg_gap_pct": None if gaps.empty else float(gaps.mean()), "cotton": cotton, "yarns": yarns,
            "placeholders": placeholder_count(m), "benchmarks": records(m["Supplier_Benchmarks"])}


# ------------------------------------------------------------------ dashboard insights
def trust(within10, median_gap):
    """How far the should-cost can be leaned on for a group of fabrics, from how it fits the prices paid.
    'firm': at least half land within 10% and the middle gap is small. Otherwise 'weak': the gap says
    more about the tool than about the supplier, and no colour should call it a good or bad deal."""
    return "firm" if within10 >= 0.5 and abs(median_gap) <= 6 else "weak"


BUCKETS = ["Yarn", "Yarn dyeing", "Sizing and weaving", "Dyeing and finishing", "Losses", "Overhead", "Margin",
           "Upcharges and quantity terms"]


@app.get("/api/insights")
def insights():
    """The dashboard's own-data panels: what was paid and what it should cost by fabric type, where the
    rupee goes by route, the cotton price by year, and how far a yarn price move carries into a fabric."""
    m = get_masters()

    def from_pilot():
        if not os.path.exists(PILOT):
            return None
        f = pd.read_excel(PILOT, sheet_name="Fabrics")
        gap = "PO above should-cost %"
        cats = []
        for (route, grp), d in f.groupby(["Route", "Weave group"]):
            if len(d) >= 20:
                # averages over the metres bought, so paid, should-cost and the gap between them agree
                metres = d["PO metres"].sum()
                paid, should = (d["PO price Rs/m"] * d["PO metres"]).sum() / metres, (d["Should-cost Rs/m"] * d["PO metres"]).sum() / metres
                within = float((d[gap].abs() <= 10).mean())
                cats.append({"route": route, "weave": grp, "fabrics": len(d), "metres": float(metres), "paid": float(paid),
                             "should": float(should), "gap": float((paid / should - 1) * 100), "within10": within,
                             "median_gap": float(d[gap].median()), "trust": trust(within, float(d[gap].median())),
                             "p25": float(d[gap].quantile(0.25)), "p75": float(d[gap].quantile(0.75))})
        cats.sort(key=lambda c: -c["fabrics"])
        split = []
        for route, d in f.groupby("Route"):
            if len(d) >= 50:
                total = d["Should-cost Rs/m"].sum()
                split.append({"route": route, "fabrics": len(d), "median_cost": float(d["Should-cost Rs/m"].median()),
                              "shares": [{"name": b, "share": float(d[f"{b} Rs/m"].sum() / total)} for b in BUCKETS if f"{b} Rs/m" in d]})
        split.sort(key=lambda c: -c["fabrics"])
        sup = []
        for name, d in f.groupby("Supplier"):
            if len(d) >= 15:
                within = float((d[gap].abs() <= 10).mean())
                mix = d.groupby(["Route", "Weave group"]).size().sort_values(ascending=False)
                sup.append({"supplier": re.sub(r"^\d+\s+", "", str(name)).title(), "fabrics": len(d), "gap": float(d[gap].median()),
                            "within10": within, "trust": trust(within, float(d[gap].median())),
                            "mostly": f"{mix.index[0][0]} {mix.index[0][1].lower()}", "mostly_share": float(mix.iloc[0] / len(d))})
        sup.sort(key=lambda c: -c["fabrics"])
        qty = []
        for label, lo, hi in (("Below 1,000 m", 0, 1000), ("1,000 to 3,000 m", 1000, 3000), ("3,000 m and above", 3000, 1e12)):
            d = f[(f["PO metres"] >= lo) & (f["PO metres"] < hi)]
            qty.append({"band": label, "fabrics": len(d), "paid": float(d["PO price Rs/m"].median()) if len(d) else None})
        return {"categories": cats, "split": split, "suppliers": sup, "quantity": qty, "fabrics": len(f),
                "median_gap": float(f[gap].median()), "within10": float((f[gap].abs() <= 10).mean())}

    p = cached(PILOT + "#insights", from_pilot) if os.path.exists(PILOT) else None
    cot = m["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    years = [{"year": int(y), "average": float(d["Price"].mean()), "low": float(d["Price"].min()), "high": float(d["Price"].max()),
              "to": clean(d["Date"].max())} for y, d in cot.groupby(cot["Date"].dt.year)]
    ref = masters.cost(masters.EXAMPLE_ROW, m)
    ys = yarn_sensitivity(ref)
    slab = m["Order_Slab"].set_index("Order size")["Overhead add (points)"].to_dict()
    card = {"print": m["Print_Methods"].set_index("Print method")["Rs per metre"].to_dict(),
            "quantity": records(m["Quantity_Terms"][["Quantity band", "Small-lot upcharge %", "Volume discount Rs per metre"]])}
    return {"pilot": p, "cotton_years": years, "cotton_unit": str(cot["Unit"].iloc[-1]) if len(cot) else "",
            "reference": {"name": masters.EXAMPLE_ROW["Description"], "total": ref["total_per_m"], **ys},
            "order_slab": {k: clean(v) for k, v in slab.items()}, "card": card,
            "placeholders": placeholder_count(m), "benchmarks": records(m["Supplier_Benchmarks"])}


@app.get("/api/table/{sheet}")
def table(sheet: str):
    m = get_masters()
    if sheet not in TABLES or sheet not in m:
        raise HTTPException(404, "No such table")
    return {"label": TABLES[sheet], **records(m[sheet])}


@app.get("/api/cotton")
def cotton():
    cot = get_masters()["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    return {"points": [[clean(d), clean(p)] for d, p in zip(cot["Date"], cot["Price"])],
            "unit": str(cot["Unit"].iloc[-1]) if len(cot) else "", "source": str(cot["Source"].iloc[-1]) if len(cot) else ""}


@app.get("/api/pilot")
def pilot():
    if not os.path.exists(PILOT):
        raise HTTPException(404, "Pilot results are not on this server")

    def load():
        x = pd.read_excel(PILOT, sheet_name=["Funnel", "Overall", "Rate card steps", "Rate card inputs",
                                             "By route and weave", "By supplier"])
        out = {k: records(v) for k, v in x.items()}
        if os.path.exists(DRAFT):
            d = pd.read_excel(DRAFT, sheet_name=["Order size", "Weaving", "Printing", "Held-back test"])
            out.update({"Draft: " + k: records(v) for k, v in d.items()})
        return out
    return cached(PILOT, load)


@app.get("/api/template")
def template():
    return Response(masters.make_template(get_masters()), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Should_Cost_Upload_Template.xlsx"'})


@app.post("/api/bulk")
async def bulk(file: UploadFile = File(...)):
    m = get_masters()
    try:
        df = pd.read_excel(io.BytesIO(await file.read()), sheet_name="Fabrics").dropna(how="all")
    except Exception as e:
        raise HTTPException(400, f"Could not read a 'Fabrics' sheet from this file: {e}")
    missing = [c for c, _, req in masters.TEMPLATE_COLUMNS if req and c not in df.columns]
    if missing:
        raise HTTPException(400, "Required columns are missing: " + ", ".join(missing))
    out = masters.cost_many(df, m)
    inputs = [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]
    return {"results": records(out), "inputs": inputs, "rejected": int((out["Error"] != "").sum())}


@app.post("/api/bulk-download")
def bulk_download(payload: dict = Body(...)):
    buf = io.BytesIO()
    pd.DataFrame(payload["rows"], columns=payload["columns"]).to_excel(buf, index=False)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Should_Cost_Results.xlsx"'})


# ------------------------------------------------------------------ editing the rate master
# Every sheet a person may edit from the new screens. Cotton prices are added to, not edited in bulk.
EDITABLE = set(TABLES) - {"Cotton_Prices", "Content_Groups"}
_stash = {}       # tables read by the price intake, waiting for their columns to be chosen


def save_masters(m):
    """Write the rate master. The first change of each day keeps a dated copy of what was there."""
    import shutil
    backup = masters.MASTER_PATH.replace(".xlsx", f" backup {dt.date.today():%Y%m%d}.xlsx")
    if os.path.exists(masters.MASTER_PATH) and not os.path.exists(backup):
        shutil.copyfile(masters.MASTER_PATH, backup)
    masters.save(m)
    _cache.pop(masters.MASTER_PATH, None)


@app.put("/api/table/{sheet}")
def save_table(sheet: str, payload: dict = Body(...)):
    m = dict(get_masters())
    if sheet not in EDITABLE or sheet not in m:
        raise HTTPException(404, "This table cannot be edited here")
    old = m[sheet]
    if [str(c) for c in payload.get("columns", [])] != [str(c) for c in old.columns]:
        raise HTTPException(400, "The columns do not match the table; reload the page and try again")
    df = pd.DataFrame(payload["rows"], columns=old.columns)
    df = df[~df.apply(lambda r: all(v is None or str(v).strip() == "" for v in r), axis=1)].reset_index(drop=True)
    if df.empty:
        raise HTTPException(400, "A table cannot be saved empty")
    for col in old.columns:
        text = df[col].map(lambda v: None if v is None or str(v).strip() == "" else v)
        if sheet == "Settings" and col == "Value":      # numbers stay numbers, words stay words
            df[col] = [pd.to_numeric(v, errors="coerce") if str(v).replace(".", "", 1).isdigit() else v for v in text]
        elif pd.api.types.is_numeric_dtype(old[col]):
            num = pd.to_numeric(text, errors="coerce")
            bad = df.index[num.isna()].tolist()
            if bad:
                raise HTTPException(400, f"'{col}' needs a number in row {bad[0] + 1}")
            df[col] = num
        else:
            df[col] = text
    key = old.columns[0]
    if sheet != "Market_Yarn":
        if df[key].isna().any():
            raise HTTPException(400, f"'{key}' is blank in row {int(df.index[df[key].isna()][0]) + 1}")
        dup_on = [key] if sheet not in ("Weaving_Rates", "Weaving_Uplifts", "Sizing_Rates", "Piece_Dyeing", "Class_Defaults", "Dobby_Charges") else list(old.columns[:2])
        dup = df[df.duplicated(dup_on)]
        if len(dup):
            raise HTTPException(400, f"'{' / '.join(map(str, dup.iloc[0][dup_on]))}' appears twice")
    m[sheet] = df
    try:
        masters.lists(m)
        masters.cost(masters.EXAMPLE_ROW, m)        # the example must still cost with the edited table
    except Exception as e:
        raise HTTPException(400, f"Not saved: with this change the example fabric can no longer be costed ({e})")
    save_masters(m)
    return {"saved": True, "rows": len(df)}


@app.post("/api/cotton")
def add_cotton(payload: dict = Body(...)):
    m = dict(get_masters())
    cot = m["Cotton_Prices"]
    try:
        date, price = pd.Timestamp(payload["date"]).date().isoformat(), float(payload["price"])
    except Exception:
        raise HTTPException(400, "A date and a price in rupees per candy are both needed")
    if price <= 0:
        raise HTTPException(400, "The price must be above zero")
    last = cot.iloc[-1] if len(cot) else {"Variety": "Shankar-6", "Unit": "Rs per candy", "Source": ""}
    row = {"Date": date, "Variety": last["Variety"], "Price": price, "Unit": last["Unit"],
           "Source": str(payload.get("source") or "").strip() or "Typed in the tool"}
    m["Cotton_Prices"] = pd.concat([cot, pd.DataFrame([row])[cot.columns]], ignore_index=True)
    save_masters(m)
    return {"saved": True}


# ------------------------------------------------------------------ yarn price intake
def _stage(df, note=""):
    return {"kind": "rows", "note": note, **records(df[pi.STAGE_COLS])}


def _tables(named, source):
    token = f"t{len(_stash) + 1}-{dt.datetime.now():%H%M%S%f}"
    _stash[token] = ({k: v.rename(columns=str) for k, v in named.items()}, source)
    while len(_stash) > 6:
        _stash.pop(next(iter(_stash)))
    return {"kind": "tables", "token": token, "source": source,
            "sheets": {k: records(v.rename(columns=str).head(15)) for k, v in named.items()}}


def _pdf(data, source):
    rows, info = pi.read_pdf(data, source)
    if info["scanned"]:
        note = (f"This PDF is a scan ({info['pages']} pages, no readable text). Type the rates into the table "
                "while looking at the pages.")
    else:
        note = f"Read {len(rows)} price lines from {info['pages']} pages. Check them before adding."
        if info["image_pages"]:
            note += f" {info['image_pages']} pages are pictures with no readable text; their rates need typing in."
    return _stage(rows if len(rows) else pi.empty_stage(), note)


@app.post("/api/intake/file")
async def intake_file(file: UploadFile = File(...)):
    data, name = await file.read(), file.filename or "upload"
    ext = name.lower().rsplit(".", 1)[-1]
    try:
        if ext in ("xlsx", "xls", "csv"):
            return _tables(pi.read_table_file(name, data), name)
        if ext == "pdf":
            pi.keep_file(name, data)
            return _pdf(data, name)
        if ext in ("png", "jpg", "jpeg", "webp"):
            pi.keep_file(name, data)
            return _stage(pi.empty_stage(), "Pictures cannot be read here. The picture is kept as the source; type its "
                                            "rates into the table.") | {"source": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read this file: {e}")
    raise HTTPException(400, "Use an Excel, CSV, PDF or picture file")


@app.post("/api/intake/link")
def intake_link(payload: dict = Body(...)):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Give a page address")
    try:
        kind, got = pi.fetch_link(url)
        if kind == "pdf":
            return _pdf(got, url)
        tables, text = got
        if tables:
            return _tables({f"Table {i + 1} ({len(t)} rows)": t for i, t in enumerate(tables)}, url)
        rows = pi.rows_from_text(text, url)
        return _stage(rows if len(rows) else pi.empty_stage(), f"No tables on the page; {len(rows)} price-like lines found in its text.")
    except Exception as e:
        raise HTTPException(400, f"Could not read this page: {e}. Pages behind a login cannot be read.")


@app.post("/api/intake/api")
def intake_api(payload: dict = Body(...)):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Give the endpoint address")
    try:        # the key is used for this one call and is not stored
        return _tables({"Reply": pi.fetch_api(url, payload.get("header_name"), payload.get("header_value"))}, url)
    except Exception as e:
        raise HTTPException(400, f"The call failed: {e}")


@app.post("/api/intake/map")
def intake_map(payload: dict = Body(...)):
    hit = _stash.get(payload.get("token"))
    if not hit or payload.get("sheet") not in hit[0]:
        raise HTTPException(400, "That file is no longer held; upload it again")
    if not payload.get("count") or not payload.get("low"):
        raise HTTPException(400, "Choose at least the count column and the rate column")
    try:
        rows = pi.map_columns(hit[0][payload["sheet"]], payload["count"], payload["low"], payload.get("high") or None,
                              payload.get("yarn") or None, payload.get("date") or None, hit[1])
    except Exception as e:
        raise HTTPException(400, f"Those columns could not be read: {e}")
    return _stage(rows, f"{len(rows)} rows with a rate were read. Check them before adding.")


@app.post("/api/intake/add")
def intake_add(payload: dict = Body(...)):
    good = pi.clean_stage(pd.DataFrame(payload.get("rows", []), columns=pi.STAGE_COLS))
    if good.empty:
        raise HTTPException(400, "No complete rows: each row needs a count and a rate")
    if payload.get("source"):
        good["Source"] = good["Source"].fillna(payload["source"])
    m = dict(get_masters())
    m["Market_Yarn"] = pd.concat([m["Market_Yarn"], good], ignore_index=True)
    save_masters(m)
    return {"added": len(good)}



# ------------------------------------------------------------------ classic screens, passed through
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-encoding", "content-length", "host"}


@app.api_route("/classic", methods=["GET"])
@app.api_route("/classic/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def classic_http(request: Request, path: str = ""):
    url = f"http://{CLASSIC}/classic/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.request(request.method, url, params=request.query_params, headers=headers,
                                     content=await request.body())
    except httpx.HTTPError:
        return Response("The classic screens are still starting. Try again in a few seconds.", status_code=503,
                        headers={"Retry-After": "5"})
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in HOP})


@app.websocket("/classic/{path:path}")
async def classic_ws(ws: WebSocket, path: str):
    proto = ws.headers.get("sec-websocket-protocol")
    subs = [p.strip() for p in proto.split(",")] if proto else None
    query = f"?{ws.url.query}" if ws.url.query else ""
    try:
        upstream = await websockets.connect(f"ws://{CLASSIC}/classic/{path}{query}", subprotocols=subs,
                                            max_size=None, additional_headers={"Cookie": ws.headers.get("cookie", "")})
    except Exception:
        await ws.close(code=1013)
        return
    await ws.accept(subprotocol=upstream.subprotocol)

    async def up():
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                await upstream.send(msg["bytes"] if msg.get("bytes") is not None else msg["text"])
        finally:
            await upstream.close()

    async def down():
        try:
            async for msg in upstream:
                await (ws.send_bytes(msg) if isinstance(msg, bytes) else ws.send_text(msg))
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    await asyncio.gather(up(), down(), return_exceptions=True)


# ------------------------------------------------------------------ the front end
class FreshFiles(StaticFiles):
    """Static files the browser must check before reusing, so a new version shows without a hard refresh."""
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


@app.get("/")
def index():
    # the script and stylesheet addresses carry the time they were last changed: a new deploy is a new address
    html = open(os.path.join(WEB, "index.html"), encoding="utf8").read()
    for name in ("app.css", "app.js"):
        html = html.replace(f'"{name}"', f'"{name}?v={int(os.path.getmtime(os.path.join(WEB, name)))}"')
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})


app.mount("/", FreshFiles(directory=WEB), name="web")
