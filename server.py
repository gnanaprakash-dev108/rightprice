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
    "Mill_Sheet_Terms": "Mill sheet terms (per end, per pick)",
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
               f"{cat['p75']:+.1f}% against should-cost (dashboard panel 1, middle half)").replace("-", "\u2212").replace("should\u2212cost", "should-cost")
        adjusted = (lo, hi) != (cat["p25"], cat["p75"])
        band_why = fit + (f"; kept at least {BAND_MIN:.0f}% and at most {BAND_MAX:.0f}% either way, so here {lo:+.1f}% to {hi:+.1f}%".replace("-", "\u2212") if adjusted else "")

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
    if (gap / should < -0.30) if should else False:
        caveats.insert(0, f"The quote is {abs(gap / should):.0%} below should-cost. That is almost always a different cloth, a typing slip "
                          "or a price per something other than a metre; check it before treating it as a saving.")
    # where to open: as far below the top of the usual range as the quote is above it, never below the
    # should-cost. It moves with the quote, so a rupee more on the quote never jumps the advice.
    open_at = max(should, round(upper - (quote - upper), 2)) if stance == "push" else should
    implausible = gap / should < -0.30 if should else False
    for n in notes or ():
        if "small-lot upcharge" not in str(n):
            caveats.insert(0, "From the mill's sheet: " + str(n)[0].upper() + str(n)[1:] + ".")
    return {
        "quote": quote, "should": should, "gap": gap, "gap_pct": gap / should if should else 0.0,
        "stance": stance, "weak": weak, "caveats": caveats, "qty_fix": qty_fix, "qty_only": qty_only, "implausible": implausible,
        "open_at": open_at, "settle_up_to": upper, "lower": lower, "above_band": round(quote - upper, 2),
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


def _qty(v):
    """A quantity as mills type it: 5000, "3,333", "5000 mtr", "4,200 m"."""
    n = _num_or_none(v)
    if n is None and isinstance(v, str):
        hit = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*(m|mt|mtr|mtrs|mts|metre|metres|meter|meters)?\.?\s*", v.lower())
        n = float(hit.group(1).replace(",", "")) if hit and hit.group(1).strip(",") else None
    return n


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
        raise HTTPException(400, "This file could not be read as an Excel workbook (.xlsx). Save the mill's sheet as Excel and upload that.")
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
    upload = f"{file.filename or 'sheet'} \u00b7 {dt.datetime.now():%d %b %H:%M:%S}"
    for r in fresh:
        r["Upload"] = upload            # which file a row came in with, for the pack's choice of rows
    if fresh:
        _write_list(pd.concat([log, pd.DataFrame(fresh)], ignore_index=True))
    out = {"added": len(fresh), "already": len(rows) - len(fresh), "kind": kind, "not_costed": sum(1 for r in fresh if r["Problems"]), "alerts": []}
    if fresh:
        try:        # flagged at once: the rows of this upload that need a look before the price is accepted
            ids = {str(r["Id"]) for r in fresh}
            out["alerts"] = [a for a in _alerts_all() if a["id"] in ids]
        except Exception:
            pass
    return out


_list_memo = {"key": None, "val": None}
_costs_memo = {"key": None, "val": None}


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _state_key():
    """What the list and Right cost are worked out from: the fabric list, the rate master, and the purchase history.
    While none of them changes, the answer is kept (the pages ask every half minute)."""
    ins = _cache.get(PILOT + "#insights")
    return (_mtime(masters.LOG_PATH), _mtime(getattr(masters, "MASTER_PATH", "")), bool(ins and ins[1]), _mtime(PILOT))


@app.post("/api/list")
def list_view(options: dict = Body(default={})):
    """The list, newest first, each row re-costed on today's rates. options.yarn_pct = {yarn key or '*': % change}
    also costs every row with those yarn rates moved, to show what a yarn price move would do."""
    m = get_masters()
    _warm_pilot()
    moves = {k: float(v) for k, v in (options.get("yarn_pct") or {}).items() if v not in ("", None) and float(v) != 0}
    memo = None if moves else _state_key()
    if memo is not None and _list_memo["key"] == memo:
        return _list_memo["val"]
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
                "sums": mill_sheet.check_sums(mill, m) if mill else None, "problems": problems,
                "sheet_terms": None if not mill else (mill_sheet.terms_for(mill, m) or {}).get("mill"),
                "should_cost": None, "gap": None, "gap_pct": None, "placeholders": [], "simulated": None, "sim_gap": None,
                "sim_gap_pct": None, "quantity": None, "at_stake": None, "brief": None,
                "supplier": clean(r.get("Supplier")), "description": clean(r.get("Description")), "upload": clean(r.get("Upload"))}
        if mill and item["sheet_terms"] is None:
            item["notes"] = list(item["notes"]) + ["no per-end and per-pick figures for this mill in the rate master (Mill sheet terms), so those upcharges were not checked"]
        if inputs is None:                   # a costing saved before choices were kept: shown, not re-costed
            item["should_cost"], item["mill"] = clean(r.get("Should-cost Rs/m")), {"Fab Code": clean(r.get("Fabric code")), "Ex mill price": clean(r.get("Quoted Rs/m"))}
            item["problems"] = ["saved before choices were kept; it cannot be re-costed or opened"]
        elif not problems:
            try:
                res = masters.cost(inputs, m)
                item.update(should_cost=res["total_per_m"], per_kg=res["per_kg"], gsm=res["gsm"], gap=res["gap"],
                            gap_pct=res["gap_pct"], placeholders=res["placeholders"], yarn=yarn_sensitivity(res))
                qty = _qty((mill or {}).get("Total order qnty")) or _qty(inputs.get("Order quantity (m)"))
                qty = qty if qty and qty > 0 else None          # a negative or zero quantity puts nothing at stake
                item["quantity"] = qty
                item["brief"] = brief(res, m, qty, item["notes"], inputs)
                item["at_stake"] = None if item["brief"] is None else item["brief"]["at_stake"]
                if sim is not None:
                    moved = masters.cost(inputs, sim)
                    item.update(simulated=moved["total_per_m"], sim_gap=moved["gap"], sim_gap_pct=moved["gap_pct"],
                                sim_brief=brief(moved, sim, qty, item["notes"], inputs))
            except Exception as e:
                item["problems"] = [str(e)]
        out.append(item)
    val = {"columns": mill_sheet.COLUMNS, "groups": mill_sheet.GROUPS, "rows": out,
           "yarns_in_use": sorted({i["inputs"][k] for i in out if i["inputs"] for k in ("Warp yarn", "Weft yarn") if i["inputs"].get(k)})}
    if memo is not None:
        _list_memo.update(key=memo, val=val)
    return val


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
def _volume_question(r, m):
    """The card gives a volume discount from 2,000 m (not for 40s quality). Ask when the sheet gives none."""
    qty, mill, inp = r["quantity"], r["mill"], r["inputs"]
    if not qty or qty < 2000 or not r["from_mill"] or (mill_sheet._num(mill.get("Discoun>2000 mts")) or 0) > 0:
        return None
    counts = m["Yarn_Rates"].set_index("Yarn key")["Count"].astype(str).str.strip().str.lower()
    if all(counts.get(str(inp.get(f"{s} yarn") or "").strip()) == "40s" for s in ("Warp", "Weft")):
        return None             # the card: no volume discount on 40s quality
    band = next((name for lo, hi, name in mill_sheet.QUANTITY_BANDS if lo <= qty < hi), None)
    qt = m["Quantity_Terms"].set_index("Quantity band")
    disc = float(qt.loc[band, "Volume discount Rs per metre"]) if band in qt.index else 0.0
    if not disc:
        return None
    return (f"{r['code']}: {qty:,.0f} m and no volume discount on the sheet. Your own rate card gives Rs {disc:g} a metre "
            f"at {band}; why not here?")


def _questions(r, b, m):
    """What to ask the mill about one row, most useful first. b is the brief the row's figures come from."""
    q, code, own_gap = [], r["code"], r["own_gap"] if r["sums"] else None
    stance = r["stance"]
    if stance == "push":
        w = b["would_need"]
        alts = []
        if w["yarn"] and not w["yarn"]["placeholder"]:
            alts.append(f"yarn at about Rs {w['yarn']['warp']:,.0f} a kilo (we work on Rs {w['yarn']['warp_now']:,.0f})")
        if not w["weaving"]["placeholder"]:
            alts.append(f"weaving at about Rs {w['weaving']['rate']:.3f} a pick (we work on Rs {w['weaving']['now']:.3f})")
        if not w["margin"]["placeholder"]:
            alts.append(f"a margin of about {w['margin']['rate']:.1%} (we work on {w['margin']['now']:.1%})")
        if r["above_band"] < 0.02 * r["should"]:
            q.append(f"{code} is only Rs {r['above_band']:,.2f} a metre above the top of the usual range: ask for Rs {r['upper']:,.2f}.")
        else:
            q.append(f"{code} is Rs {r['gap']:,.2f} a metre above should-cost (Rs {r['should']:,.2f}), Rs {r['above_band']:,.2f} of it above "
                     f"the usual range. Which explains the whole Rs {r['gap']:,.2f}" + (": " + "; or ".join(alts) + "?" if alts else "?"))
    elif stance == "ask":
        q.append(f"Send the break-up for {code} (yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish, "
                 f"margin) before a price is named. Why: {b['weak'][0]}.")
    elif stance == "check":
        q.append(f"Confirm the quote for {code}: Rs {r['quote']:,.2f} is {abs(r['gap_pct']):.0%} below should-cost. "
                 "Is it per metre, for this construction and finish?")
    elif stance == "below":
        q.append(f"{code} is below the usual range: confirm the yarn, the construction and the finish are as specified.")
    if own_gap is not None and own_gap >= 0.01:
        q.append(f"{code}: your own sums give Rs {r['own_price']:,.2f}, not Rs {r['quote']:,.2f}. Bring the price to Rs {r['own_price']:,.2f}.")
    elif own_gap is not None and own_gap <= -0.01:
        q.append(f"{code}: hold Rs {r['quote']:,.2f} as the ceiling (the sheet's own build-up comes to Rs {r['own_price']:,.2f}, "
                 "more than the quote). Ask only for the sheet to be corrected so it shows how the quoted price is made up.")
    elif r["sums"] and own_gap is not None:
        q.append(f"Correct the sheet for {code}: {'; '.join(r['sums'])}. The ex-mill price itself agrees with the sums.")
    vq = _volume_question(r, m)
    if vq:
        q.append(vq)
    for n in r["notes"]:
        if "second yarn" in n:
            q.append(f"{code}: name the second yarn in {n.split(chr(39))[1] if chr(39) in n else 'the warp or weft'} and its rate.")
        elif "not recognised" in n:
            q.append(f"{code}: {n[0].upper() + n[1:]}. Which finish is it, and what does it add?")
    return q


def _ordered(r):
    q = mill_sheet._num(r["mill"].get("Total order qnty")) if r["mill"] else None
    return q if q and q > 0 else (r["quantity"] or 0)


@app.post("/api/pack")
def pack(options: dict = Body(default={})):
    """The negotiation pack for a whole mill sheet (or the rows asked for): every row with its stance, the
    money at stake, the mill's sums that are off and the questions to ask, plus the sheet's totals.
    options: ids (the rows; default every row), yarn_pct (a yarn move, as on the list).
    With a yarn move, every figure of a row, its questions included, comes from the brief on the moved costs."""
    m = get_masters()
    v = list_view({"yarn_pct": options.get("yarn_pct")} if options.get("yarn_pct") else {})
    ids = {str(i) for i in (options.get("ids") or [])}
    chosen = [r for r in v["rows"] if not ids or r["id"] in ids]
    if not chosen:
        raise HTTPException(400, "There are no rows to put in the pack")
    rows, not_costed, seen = [], [], {}
    for r in chosen:
        code = r["mill"].get("Fab Code") or (r["inputs"] or {}).get("Fabric code") or "(no code)"
        desc = r["description"] or " ".join(str(r["mill"].get(c)) for c in ("Weave", "Variety") if r["mill"].get(c))
        own_price, own_gap = mill_sheet.own_sums(r["mill"], m) if r["from_mill"] else (None, None)
        b = r.get("sim_brief") or r["brief"]
        if r["problems"] or b is None:
            k = ("sheet", json.dumps({k2: v for k2, v in r["mill"].items() if k2 != "Fab Code"}, sort_keys=True, default=str)) if r["from_mill"] else None
            if k and k in seen:
                continue                # the same uncosted order again: listed once
            if k:
                seen[k] = code
            not_costed.append({"code": code, "description": desc, "why": "; ".join(r["problems"]) or "no mill price on this row",
                               "sums": r["sums"] or [], "own_price": own_price, "own_gap": own_gap, "ordered": _ordered(r)})
            continue
        qty = r["quantity"]
        stance = "check" if b["implausible"] else b["stance"]
        row = {"id": r["id"], "code": code, "description": desc, "supplier": r["supplier"], "quantity": qty,
               "quote": b["quote"], "should": b["should"], "gap": b["gap"], "gap_pct": b["gap_pct"], "stance": stance,
               "upper": b["settle_up_to"], "open_at": b["open_at"], "above_band": b["above_band"],
               "at_stake": b["at_stake"], "weak": b["weak"], "caveats": b["caveats"],
               "sums": r["sums"] or [], "own_price": own_price, "own_gap": own_gap,
               "own_at_stake": None if own_gap is None or qty is None else round(own_gap * qty),
               "notes": r["notes"], "mill": r["mill"], "inputs": r["inputs"], "from_mill": r["from_mill"]}
        row["above_range_money"] = round(row["above_band"] * qty) if stance == "push" and qty else 0
        # the same order twice, counted once (the newest row is kept: the list runs newest first):
        # the same fabric code and quantity (a revised sheet sent again), or every column of the mill's
        # sheet the same apart from the fabric code
        keys = []
        if qty and code != "(no code)":
            keys.append(("code", code, qty))
        if r["from_mill"]:
            keys.append(("sheet", json.dumps({k: v for k, v in r["mill"].items() if k != "Fab Code"}, sort_keys=True, default=str)))
        row["duplicate_of"] = next((seen[k] for k in keys if k in seen), None)
        for k in keys:
            seen.setdefault(k, code)
        row["questions"] = [] if row["duplicate_of"] else _questions(row, b, m)
        row["has_sheet"] = bool(r["from_mill"])
        for k in ("mill", "inputs", "from_mill"):
            row.pop(k)
        rows.append(row)
    dups = [r for r in rows if r["duplicate_of"]]
    every = rows
    rows = [r for r in rows if not r["duplicate_of"]]          # totals, lead and questions count each order once
    staked = [r for r in rows if r["at_stake"] is not None]
    by = lambda st: [r for r in rows if r["stance"] == st]
    stake = lambda rs: sum(r["at_stake"] for r in rs if r["at_stake"] is not None)
    sums_rows = [r for r in rows + not_costed if r["sums"]]
    totals = {
        "rows": len(chosen), "of": len(v["rows"]), "costed": len(rows), "not_costed": len(not_costed),
        "metres": sum(r["quantity"] or 0 for r in rows),
        "ordered": sum(r["quantity"] or 0 for r in rows) + sum(r["ordered"] or 0 for r in not_costed),
        "counted_stake": stake(by("push")) + stake(by("fair")),
        "push_stake": stake(by("push")), "fair_stake": stake(by("fair")),
        "push_above_range": sum(r["above_range_money"] for r in by("push")),
        "flagged_stake": stake(by("ask")) + stake(by("check")),
        "savings": -stake(by("below")),
        "sums_off": len(sums_rows),
        "sums_money": sum(r.get("own_at_stake") or 0 for r in rows if r["sums"] and (r.get("own_at_stake") or 0) > 0),
        "count": {st: len(by(st)) for st in ("push", "ask", "check", "fair", "below")},
        "no_quantity": sum(1 for r in rows if r["quantity"] is None),
        "duplicates": len(dups), "duplicate_metres": sum(r["quantity"] or 0 for r in dups),
    }
    # lead with the money above the usual range: what the mill has to justify, not the gap to should-cost
    # a row only a few paise above its range is not one to lead with
    lead = sorted([r for r in by("push") if r["above_range_money"] > 0 and r["above_band"] >= 0.02 * r["should"]],
                  key=lambda r: -r["above_range_money"])[:3]
    suppliers = sorted({r["supplier"] for r in chosen if r["supplier"]})
    sheets = {}         # one upload each: rows of one upload share the second their ids were made in
    for r in v["rows"]:
        label = f"{r['supplier'] or 'No supplier'} \u00b7 {r['upload']}" if r.get("upload") else f"{r['supplier'] or 'No supplier'} \u00b7 added on screen or before uploads were named"
        sheets.setdefault((label, label), []).append(r["id"])
    return {"rows": every, "not_costed": not_costed, "totals": totals, "lead": [r["code"] for r in lead],
            "sheets": [{"label": k[0], "ids": i} for k, i in sheets.items()],
            "suppliers": suppliers, "added": sorted({str(r["added"])[:10] for r in chosen if r["added"]}),
            "moved": bool(v["rows"]) and any(r["simulated"] is not None for r in v["rows"]),
            "yarn_pct": options.get("yarn_pct") or None}


# ------------------------------------------------------------------ Right cost: every costing in one list
def _pilot_choices(r, patterns, contents):
    """The choices behind one purchase-order costing, so it can be opened in Cost a fabric."""
    sel = {"Fabric code": r["Fabric code"], "Description": r["Description"], "Supplier": r["Supplier"], "Content": contents[0],
           "Route": r["Route"], "Weave": r["Weave"], "Finish": r["Finish"], "Warp yarn": r["Warp yarn"], "Weft yarn": r["Weft yarn"],
           "EPI": r["EPI"], "PPI": r["PPI"], "Finished width (in)": r["Finished width (in)"], "Order size": r["Order size"],
           "Rate card quantity": r["Rate card quantity"], "Quoted price (Rs/m)": r["PO price Rs/m"], "Order quantity (m)": r["PO metres"],
           "Pattern": r["PLM pattern"] if r["PLM pattern"] in patterns else "Solid"}
    if r["Route"] == "Yarn Dyed":
        sel.update({"Warp yarn dyeing": "Medium", "Weft yarn dyeing": "Medium", "Weft (yarn dyed)": r["Weft (yarn dyed)"] or "Dyed"})
    if r["Route"] == "Piece Dyed":
        sel["Piece shade"] = "Medium"
    if r["Print method"]:
        sel["Print method"] = r["Print method"]
    return {k: v for k, v in sel.items() if v not in (None, "")}


_briefs = {"key": None, "data": None, "running": False}


def _pilot_briefs(rows, key):
    """The negotiation brief's verdict for every purchase-order costing, on today's rates. About 12 ms a
    fabric, so it runs once in the background and is kept until the rate master changes."""
    import threading

    def work():
        try:
            m, out = get_masters(), {}
            for r in rows:
                try:
                    res = masters.cost(r["choices"], m)
                    b = brief(res, m, r["metres"], (), r["choices"])
                    out[r["code"]] = None if b is None else {"stance": b["stance"], "implausible": b["implausible"],
                                                            "lo": b["band"]["lo"] * 100, "hi": b["band"]["hi"] * 100, "weak": b["weak"]}
                except Exception as e:      # a costing that no longer works on today's rates
                    out[r["code"]] = {"stance": "error", "weak": [str(e)]}
            _briefs.update(key=key, data=out)
        finally:
            _briefs["running"] = False

    if _briefs["key"] == key:
        return _briefs["data"]
    if not _briefs["running"]:
        _briefs["running"] = True
        threading.Thread(target=work, daemon=True).start()
    return None


# the words of the negotiation brief, so a row reads the same in Right cost, the list and the pack
STANCE_BAND = {"push": "Push", "fair": "Fair", "below": "Below", "ask": "Ask break-up", "error": "Not costed"}


@app.get("/api/costs")
def costs():
    """Right cost: every purchase-order fabric costed in the pilot (1,696), plus the rows of the fabric list,
    each with what the list page shows and the choices to open it in Cost a fabric. Read-only."""
    m = get_masters()
    L = masters.lists(m)
    _warm_pilot()
    ins = _cache.get(PILOT + "#insights")
    cats = {(c["route"], c["weave"]): c for c in (ins[1]["categories"] if ins and ins[1] else [])}
    memo = (_state_key(), _briefs["key"], _briefs["running"])
    if _costs_memo["key"] == memo and _costs_memo["val"]["ready"]:
        return _costs_memo["val"]
    out = []
    if os.path.exists(PILOT):
        def load():
            f = pd.read_excel(PILOT, sheet_name="Fabrics")
            f = f.astype(object).where(pd.notna(f), None)
            return f.to_dict("records")
        for r in cached(PILOT + "#fabrics", load):
            gap = r["PO above should-cost %"]
            cat = cats.get((r["Route"], r["Weave group"]))
            hi = BAND_MIN if cat is None else min(BAND_MAX, max(BAND_MIN, cat["p75"]))
            lo = -BAND_MIN if cat is None else max(-BAND_MAX, min(-BAND_MIN, cat["p25"]))
            band = None             # set below from the brief, once it has been worked out
            out.append({
                "source": "Purchase orders", "code": r["Fabric code"], "description": r["Description"],
                "supplier": re.sub(r"^\d+\s+", "", str(r["Supplier"] or "")).title(), "route": r["Route"], "weave": r["Weave"],
                "weave_group": r["Weave group"], "finish": r["Finish"], "pattern": r["PLM pattern"], "warp": r["Warp yarn"], "weft": r["Weft yarn"],
                "epi": r["EPI"], "ppi": r["PPI"], "width": r["Finished width (in)"], "gsm": r["GSM"],
                "should": r["Should-cost Rs/m"], "per_kg": r["Should-cost Rs/kg"], "price": r["PO price Rs/m"],
                "gap": r["PO minus should-cost Rs/m"], "gap_pct": gap, "metres": r["PO metres"], "po_lines": r["PO lines"],
                "excess": r["Excess Rs"], "order_size": r["Order size"], "qty_band": r["Rate card quantity"],
                "placeholders": r["Placeholder rates used"], "held_back": bool(r["Held back"]), "band": band,
                "range": [lo, hi], "buckets": {b: r.get(f"{b} Rs/m") for b in BUCKETS},
                "choices": _pilot_choices(r, L["Pattern"], list(yarn_seed.CONTENTS))})
    mtime = os.path.getmtime(masters.MASTER_PATH) if hasattr(masters, "MASTER_PATH") and os.path.exists(masters.MASTER_PATH) else None
    verdicts = _pilot_briefs([r for r in out if r["source"] == "Purchase orders"], (mtime, len(out), bool(cats))) if out else {}
    for r in out:
        v = (verdicts or {}).get(r["code"])
        if v:
            r["band"] = "Check quote" if v.get("implausible") else STANCE_BAND[v["stance"]]
            r["why_unsure"] = v["weak"]
            if "lo" in v:
                r["range"] = [v["lo"], v["hi"]]
        elif verdicts is None:
            r["band"] = "Working it out"
    listed = list_view({})["rows"]
    for i in listed:
        b, inp = i["brief"], i["inputs"] or {}
        st = None if b is None else ("Check quote" if b["implausible"] else STANCE_BAND[b["stance"]])
        out.append({
            "source": "Fabric list", "id": i["id"], "code": i["mill"].get("Fab Code") or inp.get("Fabric code") or "(no code)",
            "description": i["description"] or " ".join(str(i["mill"].get(c)) for c in ("Weave", "Variety") if i["mill"].get(c)),
            "supplier": i["supplier"] or "", "route": inp.get("Route"), "weave": inp.get("Weave"),
            "weave_group": m["Weaves"].set_index("Weave")["Weave group"].get(inp.get("Weave")) if inp.get("Weave") else None,
            "finish": inp.get("Finish"), "pattern": inp.get("Pattern"), "warp": inp.get("Warp yarn"), "weft": inp.get("Weft yarn"),
            "epi": inp.get("EPI"), "ppi": inp.get("PPI"), "width": inp.get("Finished width (in)"), "gsm": i.get("gsm"),
            "should": i["should_cost"], "per_kg": i.get("per_kg"), "price": inp.get("Quoted price (Rs/m)"),
            "gap": i["gap"], "gap_pct": None if i["gap_pct"] is None else i["gap_pct"] * 100, "metres": i["quantity"], "po_lines": None,
            "excess": i["at_stake"], "order_size": inp.get("Order size"), "qty_band": inp.get("Rate card quantity"),
            "placeholders": ", ".join(i["placeholders"]) or None, "held_back": None, "band": st or ("Not costed" if i["problems"] else "No price"),
            "range": None if b is None else [b["band"]["lo"] * 100, b["band"]["hi"] * 100], "buckets": None,
            "problems": i["problems"], "added": i["added"], "choices": inp, "why_unsure": None if b is None else b["weak"]})
    # an unsure verdict on a price above the top of its usual range is still money above should-cost:
    # it is marked "Ask break-up, above range" so it is not lost among the unsure rows
    for r in out:
        if r["band"] == "Ask break-up" and r.get("range") and r.get("gap_pct") is not None and r["gap_pct"] > r["range"][1]:
            r["band"] = "Ask break-up, above range"
    # the same order twice in the fabric list (as the negotiation pack decides it)
    seen = {}
    for r, i in zip([x for x in out if x["source"] == "Fabric list"], listed):
        keys = []
        if r["metres"] and r["code"] != "(no code)":
            keys.append(("code", r["code"], r["metres"]))
        if i["from_mill"]:
            keys.append(("sheet", json.dumps({k: v for k, v in i["mill"].items() if k != "Fab Code"}, sort_keys=True, default=str)))
        r["duplicate_of"] = next((seen[k] for k in keys if k in seen), None)
        for k in keys:
            seen.setdefault(k, r["code"])
        if r["metres"] is None:
            q = mill_sheet._num(i["mill"].get("Total order qnty")) if i["mill"] else None
            r["metres"] = q if q and q > 0 else None
    _learn_mill_names({r["supplier"] for r in out})
    for r in out:
        r["mill"] = mill_key(r["supplier"])
    val = {"rows": out, "ready": verdicts is not None, "counts": {"Purchase orders": sum(1 for r in out if r["source"] == "Purchase orders"),
                                    "Fabric list": sum(1 for r in out if r["source"] == "Fabric list")}}
    _costs_memo.update(key=(_state_key(), _briefs["key"], _briefs["running"]), val=val)
    return val


@app.post("/api/costs/download")
def costs_download(payload: dict = Body(default={})):
    """The Right cost rows asked for (codes), or all of one source, as Excel."""
    rows = [dict(r) for r in costs()["rows"]]
    src, order, extra = payload.get("source"), payload.get("keys") or [], payload.get("extra") or {}
    key = lambda r: f"{r['source']}|{r.get('id') or r['code']}"
    if order:           # the rows asked for, in the order the page shows them
        at = {key(r): r for r in rows}
        pick = [at[k] for k in order if k in at]
    else:
        pick = [r for r in rows if not src or r["source"] == src]
    for r in pick:
        e = extra.get(key(r)) or {}
        r["status"], r["remarks"] = e.get("status"), e.get("remarks")
    cols = [("source", "Source"), ("code", "Fabric code"), ("description", "Description"), ("supplier", "Supplier"), ("route", "Route"),
            ("weave", "Weave"), ("finish", "Finish"), ("warp", "Warp yarn"), ("weft", "Weft yarn"), ("epi", "EPI"), ("ppi", "PPI"),
            ("width", "Finished width (in)"), ("should", "Should-cost Rs/m"), ("price", "Price paid (purchase orders) or quoted (fabric list) Rs/m"),
            ("gap", "Above should-cost Rs/m"), ("gap_pct", "Above should-cost %"), ("metres", "Metres"),
            ("excess", "Above should-cost Rs (gap x metres; minus = below)"), ("band", "Against the usual range"),
            ("placeholders", "Placeholder rates used"), ("status", "Status"), ("remarks", "Remarks")]
    df = pd.DataFrame([{h: r.get(k) for k, h in cols} for r in pick], columns=[h for _, h in cols])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="RightCost.xlsx"'})


@app.get("/rightcost")
def rightcost_page():
    """The earlier address of Right cost: it is now a page of the shell."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/#rightcost", status_code=307)


# ------------------------------------------------------------------ mill cost sheets
import costsheet  # noqa: E402

SHEETS_PATH = os.path.join(os.path.dirname(masters.LOG_PATH), "cost_sheets.json")


def _sheets():
    try:
        with open(SHEETS_PATH, encoding="utf8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_sheets(rows):
    os.makedirs(os.path.dirname(SHEETS_PATH), exist_ok=True)
    with open(SHEETS_PATH, "w", encoding="utf8") as f:
        json.dump(rows, f, default=str)


@app.get("/api/costsheet/template")
def costsheet_template():
    rows, about, lists = costsheet.template()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        rows.to_excel(xw, sheet_name="Cost sheet", index=False)
        about.to_excel(xw, sheet_name="Columns", index=False)
        lists.to_excel(xw, sheet_name="Lists", index=False)
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="RightPrice mill cost sheet.xlsx"'})


@app.get("/api/costsheet")
def costsheet_view():
    """Every mill cost sheet row brought in, each set beside the rate master, and the drafts that follow."""
    rows = _sheets()
    a = costsheet.analyse(rows, get_masters()) if rows else {"rows": [], "drafts": []}
    for item, r in zip(a["rows"], rows):
        item["id"], item["added"], item["upload"] = r.get("_id"), r.get("_added"), r.get("_upload")
    # numbers read from the rate master arrive as numpy types: plain ones for JSON
    return Response(json.dumps(a, default=lambda o: o.item() if hasattr(o, "item") else str(o)), media_type="application/json")


@app.post("/api/costsheet/upload")
async def costsheet_upload(file: UploadFile = File(...)):
    try:
        book = pd.read_excel(io.BytesIO(await file.read()), sheet_name=None)
    except Exception:
        raise HTTPException(400, "This file is not an Excel workbook (.xlsx). Save the mill's sheet as Excel and upload it again")
    sheet = next((df for df in book.values() if costsheet.is_cost_sheet(df)), None)
    if sheet is None:
        raise HTTPException(400, "No sheet in this file has the cost sheet headings (Mill, Route, Weave, EPI, PPI, Overhead %, Margin %). "
                                 "Download the template and fill it in")
    new = [r for r in costsheet.read(sheet) if str(r.get("Mill") or "").strip() != "Example mill"]   # the template's example is not a mill
    if not new:
        raise HTTPException(400, "The sheet has the right headings but no rows (the template's example row is not counted)")
    now = dt.datetime.now()
    upload = f"{file.filename or 'sheet'}, {now:%d %b %H:%M}"
    key = lambda r: (str(r.get("Mill") or "").strip().lower(), str(r.get("Fabric code") or "").strip().lower())
    fresh = {key(r) for r in new if str(r.get("Fabric code") or "").strip()}
    rows = _sheets()
    keep = [r for r in rows if key(r) not in fresh]      # a mill's sheet sent again takes the place of its earlier rows
    for n, r in enumerate(new):
        r["_id"], r["_added"], r["_upload"] = f"{now:%Y%m%d%H%M%S%f}{n:04d}", now.date().isoformat(), upload
    _save_sheets(keep + new)
    a = costsheet.analyse(new, get_masters())
    return {"added": len(new), "replaced": len(rows) - len(keep), "not_read": sum(1 for x in a["rows"] if x["problems"])}


@app.post("/api/costsheet/remove")
def costsheet_remove(payload: dict = Body(...)):
    ids, upload = {str(i) for i in payload.get("ids") or []}, payload.get("upload")
    rows = _sheets()
    keep = [r for r in rows if str(r.get("_id")) not in ids and not (upload and r.get("_upload") == upload)]
    _save_sheets(keep)
    return {"removed": len(rows) - len(keep)}


@app.post("/api/costsheet/apply")
def costsheet_apply(payload: dict = Body(...)):
    """Write the drafts GP ticked into the rate master, after a dated copy of it. Nothing else changes."""
    chosen = {str(i) for i in payload.get("ids") or []}
    if not chosen:
        raise HTTPException(400, "Tick the drafts to apply")
    rows = _sheets()
    m = get_masters()
    drafts = costsheet.analyse(rows, m)["drafts"]
    picked = [d for d in drafts if d["id"] in chosen]
    if not picked:
        raise HTTPException(400, "Those drafts are no longer there; reload the page")
    import shutil
    m2 = {k: v.copy() for k, v in m.items()}
    try:
        log = costsheet.apply(m2, picked, chosen)
        masters.cost(dict(masters.EXAMPLE_ROW), m2)        # the rate master must still cost a fabric
    except Exception as e:
        raise HTTPException(400, f"Not applied, nothing changed: {e}")
    # the copy is taken only once the change is known to be good, and to the second, so none is overwritten
    backup = masters.MASTER_PATH.replace(".xlsx", f" before mill cost sheet {dt.datetime.now():%Y%m%d-%H%M%S}.xlsx")
    shutil.copyfile(masters.MASTER_PATH, backup)
    save_masters(m2)
    _briefs.update(key=None)
    return {"applied": log, "backup": os.path.basename(backup)}


# ------------------------------------------------------------------ negotiation tracker
NEGO_PATH = os.path.join(os.path.dirname(masters.LOG_PATH), "negotiations.json")
NEGO_KINDS = ["Mill's quote", "Our counter", "Mill's revised quote", "Agreed"]


def _negos():
    try:
        with open(NEGO_PATH, encoding="utf8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_negos(d):
    os.makedirs(os.path.dirname(NEGO_PATH), exist_ok=True)
    tmp = NEGO_PATH + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(d, f, default=str)
    os.replace(tmp, NEGO_PATH)


MILL_WORDS = {"ltd", "limited", "mills", "mill", "pvt", "private", "co", "company", "the", "p"}
_mill_alias = {}        # a name cut short in the purchase-order data -> the full name it is the start of (set in costs())


def _mill_base(name):
    words = re.sub(r"[^\w\u0900-\u0DFF ]+|_", " ", str(name or "").lower()).split()      # Indian scripts keep their vowel signs
    cut_ = lambda w: len(w) >= 3 and ("limited".startswith(w) or "private".startswith(w))
    keep = [w for w in words if w not in MILL_WORDS and not cut_(w)]
    if len(keep) > 1 and keep[-1] in ("l", "li", "lt"):          # "Raymond Luxury Cottons L": the name was cut off inside Ltd or Limited
        keep = keep[:-1]
    # Fashion and Fashions, Industrie (cut short) and Industries are one word
    return " ".join((w[:-1] if len(w) > 4 and w.endswith("s") else w) for w in (keep or words))


def mill_key(name):
    """One key for a mill however its name is written: "Arvind", "Arvind Ltd" and "ARVIND LIMITED" are one mill.
    Purchase-order names are cut at 24 characters ("Rajapalayam Mills Limite", "Nahar Industrial Enterpr"), so a cut-off
    Limited goes, and a cut-off name that is the start of exactly one fuller name is that mill."""
    k = _mill_base(name)
    return _mill_alias.get(k, k)


def _learn_mill_names(names):
    """Names cut short at 23 or 24 characters that are the start of exactly one other mill's name."""
    bases = {}
    for n in names:
        if n:
            bases.setdefault(_mill_base(n), set()).add(str(n).strip())
    _mill_alias.clear()
    for k, raw in bases.items():
        if len(k) >= 10 and any(len(r) >= 23 for r in raw):
            longer = [k2 for k2 in bases if k2 != k and k2.startswith(k)]
            if len(longer) == 1:
                _mill_alias[k] = longer[0]


def _inr(v, d=2):
    """Rupees with Indian grouping: 9,99,99,999.00."""
    neg, v = v < 0, abs(float(v))
    whole, frac = f"{v:.{d}f}".split(".") if d else (f"{v:.0f}", "")
    head, tail = whole[:-3], whole[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return ("−" if neg else "") + (head + "," if head else "") + tail + ("." + frac if d else "")


def _day(iso):
    try:
        return f"{dt.date.fromisoformat(str(iso)[:10]):%d %b %Y}".lstrip("0")
    except ValueError:
        return str(iso)


def _nego_order(events):
    """By date; on one day the mill's (first) quote comes first and the agreed price last, whatever order they were typed in."""
    rank = {"Mill's quote": 0, "Agreed": 2}
    return sorted(events, key=lambda e: (e["date"], rank.get(e["kind"], 1), e.get("at", "")))


FAR = 2.0           # a price more than twice, or under half of, what it is compared with is flagged


def nego_summary(rec):
    """Where one fabric's negotiation stands: the mill's first and latest price, the agreed price, what was won.
    The first quote is the first step the mill quoted in (never our counter, never the agreed price). It is
    agreed only while the agreed step is the last one: a step dated after it opens the negotiation again.
    A fabric with a warning is not counted in what was won until the step is put right."""
    ev = _nego_order(rec.get("events", []))
    quotes = [e for e in ev if e["kind"] in ("Mill's quote", "Mill's revised quote")]
    last_agreed = next((e for e in reversed(ev) if e["kind"] == "Agreed"), None)
    agreed = last_agreed if ev and ev[-1]["kind"] == "Agreed" else None
    first = quotes[0]["price"] if quotes else None
    latest_q = quotes[-1]["price"] if quotes else None
    metres = rec.get("metres") or 0
    should = rec.get("should") or rec.get("row_price")          # a fabric not costed is checked against the price on its row
    counter = next((e["price"] for e in reversed(ev) if e["kind"] == "Our counter"), None)
    out = {"status": "Agreed" if agreed else ("Open" if ev else "Not tracked"), "first": first, "latest": latest_q,
           "agreed": agreed["price"] if agreed else None, "counter": counter,
           "reopened": last_agreed["price"] if last_agreed and not agreed else None,
           "steps": len(ev), "last_date": ev[-1]["date"] if ev else None}
    ref = out["agreed"] if agreed else latest_q
    out["won_per_m"] = None if first is None or ref is None else round(first - ref, 2)
    out["won"] = None if out["won_per_m"] is None or not metres else round(out["won_per_m"] * metres)
    out["above_should_per_m"] = None if ref is None or rec.get("should") is None else round(ref - rec["should"], 2)
    warn = []
    far = lambda a, b: bool(a and b) and (a > FAR * b or a < b / FAR)
    said = lambda e: f"Rs {_inr(e['price'])} ({e['kind']}, {_day(e['date'])})"
    if last_agreed and quotes and last_agreed["date"] < quotes[0]["date"]:
        warn.append(f"The agreed price is dated {_day(last_agreed['date'])}, before the mill's first quote ({_day(quotes[0]['date'])}). Check the dates.")
    first_off = bool(quotes) and far(first, should)
    if first_off:
        warn.append(f"The mill's first quote, {said(quotes[0])}, is far from {'the should-cost' if rec.get('should') else 'the price on the row'} of Rs {_inr(should)}. "
                    "Check it is per metre and typed right: what was won is measured from it.")
    for e in ev:
        if quotes and e is quotes[0]:
            continue
        base, name = (should, "the should-cost" if rec.get("should") else "the price on the row") if first_off or first is None else (first, "the first quote")
        if far(e["price"], base):
            warn.append(f"{said(e)} is far from {name} of Rs {_inr(base)}. Check it is per metre and typed right.")
    standing = None             # a counter above the mill's price at the time stays flagged, whatever came after
    for e in ev:
        if e["kind"] in ("Mill's quote", "Mill's revised quote"):
            standing = e["price"]
        elif e["kind"] == "Our counter" and standing is not None and e["price"] > standing:
            warn.append(f"Our counter of Rs {_inr(e['price'])} ({_day(e['date'])}) is above the mill's price then, Rs {_inr(standing)}. "
                        "Check which is which, and remove and re-enter the wrong step.")
    out["warnings"] = warn
    out["no_quote"] = bool(agreed and first is None)
    out["counted"] = bool(agreed and out["won"] is not None and not warn)
    return out


def _nego_view(rec):
    return dict(rec, events=_nego_order(rec.get("events", [])), summary=nego_summary(rec))


def _list_duplicates(blocking=False):
    """Fabric-list rows that repeat an order already on the list, as Right cost and the pack decide it: {key: code it repeats}.
    blocking: only those whose negotiation must be left out of what was won, because the row they repeat has a
    negotiation of its own (the same order would be counted twice). A row agreed before a re-quote arrived keeps its gain."""
    rows = [r for r in costs()["rows"] if r["source"] == "Fabric list"]
    out = {f"Fabric list|{r['id']}": r["duplicate_of"] for r in rows if r.get("duplicate_of")}
    if not blocking:
        return out
    tracked = {k for k, v in _negos().items() if v.get("events")}
    live = {}
    for r in rows:
        if not r.get("duplicate_of"):
            live.setdefault(r["code"], []).append(f"Fabric list|{r['id']}")
    return {k: code for k, code in out.items() if any(o in tracked for o in live.get(code, []))}


@app.get("/api/negotiations")
def negotiations():
    """Every fabric's negotiation: its steps (and the steps removed, for the log) and where it stands."""
    return {"kinds": NEGO_KINDS, "items": {k: _nego_view(v) for k, v in _negos().items()}}


def _who(request):
    """The signed-in person, from Azure's sign-in header; nothing off Azure."""
    return (request.headers.get("x-ms-client-principal-name") or "")[:120] if request is not None else ""


@app.post("/api/negotiations/event")
def negotiation_event(payload: dict = Body(...), request: Request = None):
    """Record one step: the mill's quote, our counter, a revised quote, or the agreed price."""
    key, kind = str(payload.get("key") or ""), payload.get("kind")
    price = _num_or_none(payload.get("price"))
    if not key or kind not in NEGO_KINDS:
        raise HTTPException(400, "Choose the fabric and what happened")
    if price is None or price <= 0:
        raise HTTPException(400, "Type the price in rupees per metre")
    if round(price, 2) < 1 or price > 50000:
        raise HTTPException(400, "A price per metre is between Rs 1 and Rs 50,000: check what was typed")
    try:
        day_ = dt.date.fromisoformat(str(payload.get("date") or dt.date.today().isoformat()))
    except ValueError:
        raise HTTPException(400, "The date is not a date")
    if day_ > dt.date.today():
        raise HTTPException(400, "The date is in the future")
    if day_ < dt.date.today() - dt.timedelta(days=730):
        raise HTTPException(400, f"The date is {_day(day_.isoformat())}, more than two years ago: check the year")
    if key.startswith("Fabric list|") and not _negos().get(key, {}).get("events"):
        dup = _list_duplicates().get(key)           # a row with steps already (agreed before a re-quote came in) keeps its negotiation
        if dup:
            raise HTTPException(400, f"This row repeats the order of {dup}: record the negotiation on {dup}, so it is counted once")
    d = _negos()
    seen = payload.get("seen")
    if seen is not None and int(seen) != len(d.get(key, {}).get("events", [])):
        raise HTTPException(409, "Someone else has recorded or removed a step on this fabric since this page read it. "
                                 "The page now shows the steps as they are: check them, then record again if it is still right.")
    rec = d.setdefault(key, {"key": key, "events": []})
    for f in ("code", "supplier", "description", "source"):
        if payload.get(f):
            rec[f] = payload[f]
    for f in ("metres", "should", "row_price"):
        v = _num_or_none(payload.get(f))
        if v is not None:
            rec[f] = v
    rec["events"].append({"id": f"{dt.datetime.now():%Y%m%d%H%M%S%f}", "at": dt.datetime.now().isoformat(timespec="seconds"),
                          "date": day_.isoformat(), "kind": kind, "price": round(price, 2), "note": str(payload.get("note") or "")[:500],
                          "by": _who(request)})
    _save_negos(d)
    return _nego_view(rec)


@app.post("/api/negotiations/remove")
def negotiation_remove(payload: dict = Body(...), request: Request = None):
    """Take a step out. It is kept, marked removed, so the fabric's log still shows it was there."""
    key, eid = str(payload.get("key") or ""), str(payload.get("id") or "")
    d = _negos()
    gone = [e for e in d.get(key, {}).get("events", []) if e["id"] == eid]
    if not gone:
        raise HTTPException(404, "That step is no longer there: someone has already removed it")
    d[key]["events"] = [e for e in d[key]["events"] if e["id"] != eid]
    d[key].setdefault("removed", []).extend(dict(e, removed_at=dt.datetime.now().isoformat(timespec="seconds"), removed_by=_who(request)) for e in gone)
    d[key]["removed"] = d[key]["removed"][-100:]
    _save_negos(d)
    return {"removed": True}


@app.get("/api/negotiations/summary")
def negotiations_summary():
    """What negotiation has won, overall and by mill: against the first quote. A mill written two ways is one mill.
    Counted: agreed, with a mill quote and metres, no step to check, and not a row that repeats another order."""
    dups = _list_duplicates(blocking=True)
    items = [_nego_view(v) for v in _negos().values() if v.get("events")]
    by, check, total, lost, lost_n = {}, [], 0, 0, 0
    count = {"no_quantity": 0, "no_quote": 0, "duplicates": 0}
    for it in items:
        s_ = it["summary"]
        name = it.get("supplier") or "No supplier"
        b = by.setdefault(mill_key(name) or "no supplier", {"names": {}, "fabrics": 0, "agreed": 0, "open": 0, "won": 0, "lost": 0, "lost_fabrics": 0, "metres": 0.0, "not_counted": 0})
        b["names"][name] = b["names"].get(name, 0) + 1
        b["fabrics"] += 1
        b["agreed" if s_["status"] == "Agreed" else "open"] += 1
        if s_["warnings"]:
            check.append({"code": it.get("code") or it["key"], "why": s_["warnings"][0]})
        if s_["status"] != "Agreed":
            continue
        if it["key"] in dups:
            count["duplicates"] += 1
            b["not_counted"] += 1
        elif s_["counted"]:
            b["won"] += s_["won"]
            b["metres"] += it.get("metres") or 0
            total += s_["won"]
            if s_["won"] < 0:
                b["lost"] -= s_["won"]
                b["lost_fabrics"] += 1
                lost -= s_["won"]
                lost_n += 1
        else:
            b["not_counted"] += 1
            if s_["no_quote"]:
                count["no_quote"] += 1
            elif s_["won"] is None:
                count["no_quantity"] += 1
    for b in by.values():       # shown under the spelling used most, the longer one on a tie
        b["supplier"] = sorted(b.pop("names").items(), key=lambda kv: (-kv[1], -len(kv[0])))[0][0]
        b["key"] = mill_key(b["supplier"])
    agreed = sum(1 for it in items if it["summary"]["status"] == "Agreed")
    return dict(count, fabrics=len(items), agreed=agreed, open=len(items) - agreed, won=round(total), lost=round(lost), lost_fabrics=lost_n,
                to_check=check, suppliers=sorted(by.values(), key=lambda b: (-b["won"], b["supplier"])))


# ------------------------------------------------------------------ supplier page
PO_QUESTIONS = 5        # the purchases to ask about: the largest sums paid above the usual range


def _mill_names(rows):
    """One mill's spellings, the one used most first."""
    n = {}
    for r in rows:
        if r["supplier"]:
            n[r["supplier"]] = n.get(r["supplier"], 0) + 1
    names = [k for k, _ in sorted(n.items(), key=lambda kv: (-kv[1], -len(kv[0])))]
    if names and len(names[0]) >= 23 and not re.search(r"(ltd|limited)\.?$", names[0].lower()):      # cut at 24 characters in the purchase orders
        fuller = [x for x in names if len(x) > len(names[0])] or [x for x in names if re.search(r"(ltd|limited)\.?$", x.lower())]
        if fuller:
            names.remove(fuller[0])
            names.insert(0, fuller[0])
    return names


@app.get("/api/suppliers")
def suppliers():
    """Every mill bought from or quoted by, one line each (a mill written two ways is one mill)."""
    d = costs()
    by = {}
    for r in d["rows"]:
        k = mill_key(r["supplier"])
        if not k:
            continue
        by.setdefault(k, []).append(r)
    won = {mill_key(b["supplier"]): b for b in negotiations_summary()["suppliers"]}
    out = []
    for k, rows in by.items():
        po = [r for r in rows if r["source"] == "Purchase orders"]
        fl = [r for r in rows if r["source"] == "Fabric list" and not r.get("duplicate_of")]
        t = won.get(k) or {}
        out.append({"key": k, "name": _mill_names(rows)[0], "bought": len(po), "quoted": len(fl),
                    "push": sum(1 for r in rows if r["band"] == "Push" and not r.get("duplicate_of")),
                    "above_range": round(sum(_above_range(r) for r in po + fl)),
                    "open": t.get("open", 0), "agreed": t.get("agreed", 0), "won": t.get("won", 0)})
    return {"ready": d["ready"], "suppliers": sorted(out, key=lambda s: (-s["above_range"], -s["bought"] - s["quoted"], s["name"]))}


def _above_range(r):
    """Rupees above the top of the usual range on a Push row: the price less the top of the range (both to the paisa,
    as the brief prints them), times the metres."""
    if r["band"] != "Push" or not r.get("range") or not r.get("metres") or r.get("should") is None or r.get("price") is None:
        return 0.0
    upper = round(round(r["should"], 2) * (1 + r["range"][1] / 100), 2)
    return max(0.0, round(round(r["price"], 2) - upper, 2)) * r["metres"]


def _hold_counter(questions, ng, b, code):
    """A counter already made is the figure to hold: never ask for more than it."""
    c = ng.get("counter") if ng else None
    if c is None or b["stance"] != "push" or c >= b["settle_up_to"]:
        return questions
    first = (f"{code}: hold our counter of Rs {_inr(c)}. The mill's Rs {_inr(b['quote'])} is still Rs {_inr(b['above_band'])} a metre above the top of "
             f"the usual range (Rs {_inr(b['settle_up_to'])}): what explains the difference? Do not go above Rs {_inr(b['settle_up_to'])}.")
    return [first] + list(questions[1:])


def _side(rows):
    """The figures of one side of the page (bought, or quoted): verdict counts and the money, each kind apart and
    never netted. A fabric agreed in the tracker is closed: it is counted apart, not as money to push on."""
    live = [r for r in rows if not r.get("duplicate_of")]
    closed = [r for r in live if r.get("tracked") == "Agreed"]
    live = [r for r in live if r.get("tracked") != "Agreed"]
    cnt = {}
    for r in live:
        cnt[r["band"]] = cnt.get(r["band"], 0) + 1
    ex = lambda bands, sign=0: round(sum(r["excess"] or 0 for r in live if r["band"] in bands and (sign == 0 or (r["excess"] or 0) * sign > 0)))
    with_m = [r for r in live + closed if r.get("metres") and r.get("price") and r.get("should") is not None]
    return {"fabrics": len(live) + len(closed), "duplicates": len(rows) - len(live) - len(closed), "counts": cnt,
            "metres": round(sum(r["metres"] for r in with_m)),
            "value": round(sum(r["price"] * r["metres"] for r in with_m)),
            "should_value": round(sum(r["should"] * r["metres"] for r in with_m)),
            "above_range": round(sum(r["above_range"] for r in live)),
            "push_excess": ex(("Push",)), "fair_excess": ex(("Fair",)), "below_saving": -ex(("Below",)),
            "unsure_high": cnt.get("Ask break-up, above range", 0), "unsure_high_excess": ex(("Ask break-up, above range",), 1),
            "unsure_other": cnt.get("Ask break-up", 0), "check_excess": ex(("Check quote",)),
            "agreed": len(closed), "agreed_above_range": round(sum(r["above_range"] for r in closed)),
            "agreed_unsure": sum(1 for r in closed if str(r["band"]).startswith("Ask break-up")),
            "moved": sum(1 for r in live if r.get("tracked") == "Open"),
            "no_metres": sum(1 for r in live if r.get("price") and not r.get("metres"))}


@app.get("/api/supplier")
def supplier(mill: str):
    """One mill, for the meeting with it: what was bought and what is quoted, each fabric's verdict, the money above
    the usual range, its sheets' sums that are off, where each negotiation stands, and the questions to take along."""
    key = mill_key(mill)
    d = costs()
    rows = [dict(r) for r in d["rows"] if mill_key(r["supplier"]) == key]         # copies: the page changes its rows
    if not key or not rows:
        raise HTTPException(404, "No fabric bought from or quoted by that mill")
    m = get_masters()
    po = [r for r in rows if r["source"] == "Purchase orders"]
    fl = [r for r in rows if r["source"] == "Fabric list"]
    negos = {k: nego_summary(v) for k, v in _negos().items() if v.get("events")}

    # a quoted fabric with a price from the mill in the tracker is judged on that price: the agreed price, or the
    # mill's latest. Its verdict, its money above the range and its questions all follow it.
    live_q = []         # (row, brief, the sheet's own figures still apply)
    for r in fl:
        ng = negos.get(f"Fabric list|{r['id']}")
        ref = None if not ng else (ng["agreed"] if ng["status"] == "Agreed" else ng["latest"])
        if ref is None or r.get("duplicate_of") or r.get("problems") or not r.get("choices"):
            continue
        r["sheet_price"], r["tracked"], r["first_quote"] = r["price"], ng["status"], ng["first"]
        try:
            res = masters.cost(dict(r["choices"], **{"Quoted price (Rs/m)": ref}), m)
            b = brief(res, m, r["metres"], (), r["choices"])
        except Exception:
            b = None
        if b is None:
            continue
        band = "Check quote" if b["implausible"] else STANCE_BAND[b["stance"]]
        if band == "Ask break-up" and b["gap_pct"] * 100 > b["band"]["hi"] * 100:
            band = "Ask break-up, above range"
        r.update(price=b["quote"], gap=b["gap"], gap_pct=b["gap_pct"] * 100, band=band, excess=b["at_stake"],
                 range=[b["band"]["lo"] * 100, b["band"]["hi"] * 100])
        if ng["status"] != "Agreed":
            live_q.append((r, b, abs(ref - (r["sheet_price"] or ref)) < 0.005))
    for r in rows:
        r["above_range"] = 0 if r.get("duplicate_of") else round(_above_range(r))

    # the quoted side's sums and questions come from the negotiation pack of this mill's list rows
    quoted_q, sums, not_costed, sheets = [], [], [], 0
    moved = {r["id"]: (r, b, same) for r, b, same in live_q}
    if fl:
        try:
            p = pack({"ids": [r["id"] for r in fl]})
            not_costed = [{"code": n["code"], "why": n["why"]} for n in p["not_costed"]]
            sheets = sum(1 for r in p["rows"] if r.get("has_sheet"))
            for r in sorted(p["rows"], key=lambda r: -(r["above_range_money"] or 0)):
                if r["duplicate_of"]:
                    continue
                ng = negos.get(f"Fabric list|{r['id']}")
                if ng and ng["status"] == "Agreed":
                    continue            # agreed: nothing left to ask (it is in the negotiations table)
                if r["id"] in moved and not moved[r["id"]][2]:
                    # the mill has moved since its sheet: ask on the price it is at now
                    row, b, _ = moved[r["id"]]
                    first = row.get("first_quote")
                    lead = f"{r['code']}: the mill is now at Rs {_inr(b['quote'])}" + (
                        f", up from its first quote of Rs {_inr(first)}" if first is not None and b["quote"] > first + 0.005 else
                        f", down from its first quote of Rs {_inr(first)}" if first is not None and b["quote"] < first - 0.005 else "") + (
                        f" (its sheet said Rs {_inr(row['sheet_price'])})" if row.get("sheet_price") else "") + (
                        f"; our counter is Rs {_inr(ng['counter'])}" if ng["counter"] is not None else "") + ". "
                    q_row = {"code": r["code"], "stance": "check" if b["implausible"] else b["stance"], "quote": b["quote"], "should": b["should"],
                             "gap": b["gap"], "gap_pct": b["gap_pct"], "upper": b["settle_up_to"], "above_band": b["above_band"], "sums": [],
                             "own_gap": None, "own_price": None, "quantity": row["metres"], "mill": {}, "from_mill": False, "inputs": row["choices"], "notes": []}
                    qs_ = _questions(q_row, b, m) if b["stance"] != "fair" else [f"{r['code']} is now inside its usual range (up to Rs {_inr(b['settle_up_to'])}): close it" + (f" at or near our counter of Rs {_inr(ng['counter'])}." if ng["counter"] is not None else ".")]
                    quoted_q += [{"code": r["code"], "text": (lead if n == 0 else "") + q} for n, q in enumerate(x.replace(f"{r['code']}: hold our", "Hold our") for x in _hold_counter(qs_, ng, b, r["code"]))]
                    if r["own_price"] is not None and b["quote"] - r["own_price"] >= 0.01:      # its own build-up is below what it now asks
                        gap_ = round(b["quote"] - r["own_price"], 2)
                        sums.append({"code": r["code"], "sums": [f"its sheet priced it at Rs {_inr(r['quote'])}; it now asks Rs {_inr(b['quote'])}"], "quote": b["quote"],
                                     "own_price": r["own_price"], "own_gap": gap_, "own_at_stake": round(gap_ * row["metres"]) if row.get("metres") else None})
                    continue
                else:
                    quoted_q += [{"code": r["code"], "text": q} for q in (_hold_counter(r["questions"], ng, {"stance": r["stance"], "settle_up_to": r["upper"], "quote": r["quote"], "above_band": r["above_band"]}, r["code"]) if ng else r["questions"])]
                if r["sums"]:
                    sums.append({"code": r["code"], "sums": r["sums"], "quote": r["quote"], "own_price": r["own_price"],
                                 "own_gap": r["own_gap"], "own_at_stake": r["own_at_stake"]})
            for n in p["not_costed"]:
                if n["sums"]:
                    sums.append({"code": n["code"], "sums": n["sums"], "quote": None, "own_price": n["own_price"], "own_gap": n["own_gap"], "own_at_stake": None})
        except HTTPException:
            pass
    # the same cloth quoted at the same price under several codes: asked once
    merged, at = [], {}
    for q in quoted_q:
        body = q["text"].replace(q["code"], "\x00")
        if body in at:
            at[body]["also"].append(q["code"])
        else:
            at[body] = dict(q, also=[])
            merged.append(at[body])
    quoted_q = [{"code": q["code"], "text": q["text"] + (f" (The same holds for {', '.join(dict.fromkeys(q['also']))}.)" if q["also"] else "")} for q in merged]

    # the purchases to ask about: the largest sums paid above the usual range, with what would have to be true
    bought_q, same, cloth = [], {}, {}
    for r in po:
        if r["above_range"] > 0:
            cloth[(r["price"], round(r["should"], 2))] = cloth.get((r["price"], round(r["should"], 2)), 0) + r["above_range"]
    asked = set(sorted(cloth, key=lambda k: -cloth[k])[:PO_QUESTIONS])       # the same cloth at the same price under several codes is one question
    for r in sorted([r for r in po if r["above_range"] > 0], key=lambda r: (-cloth[(r["price"], round(r["should"], 2))], -r["above_range"])):
        if (r["price"], round(r["should"], 2)) not in asked:
            break
        try:
            res = masters.cost(r["choices"], m)
            b = brief(res, m, r["metres"], (), r["choices"])
            if b is None or b["stance"] != "push":
                continue
            row = {"code": r["code"], "stance": "push", "quote": b["quote"], "should": b["should"], "gap": b["gap"], "gap_pct": b["gap_pct"],
                   "upper": b["settle_up_to"], "above_band": b["above_band"], "sums": [], "own_gap": None, "own_price": None,
                   "quantity": r["metres"], "mill": {}, "from_mill": False, "inputs": r["choices"], "notes": []}
            twin = same.get((r["price"], round(r["should"], 2)))
            if twin is not None:        # the same cloth at the same price under another code: one question, the codes named
                twin["also"].append(r["code"])
                twin["above_range"] += r["above_range"]
                continue
            for n, q in enumerate(_questions(row, b, m)):
                item = {"code": r["code"], "text": f"Bought at Rs {_inr(b['quote'])} a metre ({_inr(r['metres'], 0)} m). " + q,
                        "above_range": r["above_range"], "also": []}
                bought_q.append(item)
                if n == 0:
                    same[(r["price"], round(r["should"], 2))] = item
        except Exception:
            continue
    for q in bought_q:
        if q["also"]:
            q["text"] += f" The same cloth at the same price was bought as {', '.join(q['also'])}; Rs {_inr(q['above_range'], 0)} above the range on all of them."
    # fabrics that look high but that the tool is unsure of: name the largest, and ask for their break-up
    high = sorted([r for r in rows if r["band"] == "Ask break-up, above range" and not r.get("duplicate_of") and r.get("tracked") != "Agreed"],
                  key=lambda r: -(r["excess"] or 0))
    unsure_q = []
    if high:
        named = "; ".join(f"{r['code']} ({'quoted' if r['source'] == 'Fabric list' else 'bought at'} Rs {_inr(r['price'])} against our cost of Rs {_inr(r['should'])})" for r in high[:3])
        unsure_q.append(f"These look high, but our costing of this kind of cloth is not yet firm, so we need your break-up before we say more: {named}"
                        + (f"; and {len(high) - 3} more" if len(high) > 3 else "") + ". Please send the cost break-up (yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish, margin).")

    # the tracker: where each negotiation with this mill stands
    dups = _list_duplicates(blocking=True)
    track, won, lost, agreed, open_ = [], 0, 0, 0, 0
    for k, v in _negos().items():
        if not v.get("events") or mill_key(v.get("supplier")) != key:
            continue
        s_ = nego_summary(v)
        counted = s_["counted"] and k not in dups
        track.append({"key": k, "code": v.get("code") or k, "status": s_["status"], "first": s_["first"], "latest": s_["latest"], "agreed": s_["agreed"],
                      "counter": s_["counter"], "reopened": s_["reopened"], "won_per_m": s_["won_per_m"], "won": s_["won"] if counted else None,
                      "counted": counted, "warnings": s_["warnings"], "last_date": s_["last_date"], "metres": v.get("metres")})
        agreed += s_["status"] == "Agreed"
        open_ += s_["status"] != "Agreed"
        if counted:
            won += s_["won"]
            lost -= min(0, s_["won"])
    track.sort(key=lambda t: (t["status"] == "Agreed", t["last_date"] or ""), reverse=False)

    general = list(unsure_q)
    b_side, q_side = _side(po), _side(fl)
    unsure = b_side["unsure_high"] + b_side["unsure_other"] + q_side["unsure_high"] + q_side["unsure_other"]
    hint = None
    if unsure:
        types = {}
        for r in rows:
            if str(r["band"]).startswith("Ask break-up") and not r.get("duplicate_of"):
                t = f"{(r.get('route') or '').lower()} {(r.get('weave_group') or '').lower()}".strip() or "other"
                types[t] = types.get(t, 0) + 1
        top = sorted(types.items(), key=lambda kv: -kv[1])[:3]
        general.append(f"Please fill one cost sheet for each of these kinds of cloth: {', '.join(t for t, _ in top)}{' (and the others we buy from you, if you can)' if len(types) > 3 else ''}. "
                       "It should show the yarn, wastage, weaving per pick, dyeing, finish, overhead and margin.")
        hint = (f"The tool cannot judge {unsure} of this mill's fabrics yet ({', '.join(f'{t}: {n}' for t, n in top)}{', and others' if len(types) > 3 else ''}). "
                "The cost sheet template is on Prices > Mill cost sheets; a filled sheet from the mill firms up the rates.")
    for t in track:
        if t["status"] != "Agreed":
            where = f"the mill is at Rs {_inr(t['latest'])}" if t["latest"] is not None else "the mill has not quoted"
            general.append(f"{t['code']} is still open: {where}" + (f", our counter is Rs {_inr(t['counter'])}" if t["counter"] is not None else "") + ". Close it or agree the next step.")
    slim = lambda r: {k: r.get(k) for k in ("source", "id", "code", "description", "route", "weave_group", "should", "price", "gap", "gap_pct", "metres", "excess",
                                              "band", "range", "duplicate_of", "problems", "why_unsure", "placeholders", "above_range", "tracked", "sheet_price", "first_quote")}
    return {"key": key, "name": _mill_names(rows)[0], "names": _mill_names(rows), "ready": d["ready"],
            "bought": dict(b_side, rows=[slim(r) for r in sorted(po, key=lambda r: (-r["above_range"], -(r["excess"] or 0)))]),
            "quoted": dict(q_side, rows=[slim(r) for r in sorted(fl, key=lambda r: (r.get("tracked") == "Agreed", -r["above_range"]))], not_costed=not_costed, sheets=sheets),
            "sums": sums, "hint": hint, "today": _day(dt.date.today().isoformat()),
            "tracker": {"fabrics": len(track), "agreed": agreed, "open": open_, "won": round(won), "lost": round(lost), "items": track},
            "questions": {"quoted": quoted_q, "bought": bought_q, "general": general}}


# ------------------------------------------------------------------ quote alerts
"""A mill sheet is uploaded: every row that needs a look before the price is accepted is flagged at once.
Four kinds: priced above its usual range, the mill's own sums are off, the row repeats an order already on the
list, or the quote is far below should-cost. An alert stays until someone marks it seen, the row is removed, or
its negotiation is agreed in the tracker (recording the mill's quote alone does not clear it). No e-mail or push: they show on the Dashboard, on the Right cost rail
item and on the Bulk upload screen."""
SEEN_PATH = os.path.join(os.path.dirname(masters.LOG_PATH), "alerts_seen.json")
ALERT_KINDS = {"above": "Above its usual range", "sums": "Mill's sums off", "repeat": "Repeats an order", "low": "Far below should-cost"}


def _seen():
    try:
        with open(SEEN_PATH, encoding="utf8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


ALERT_MIN_ABOVE = 0.005        # a quote less than half a per cent of should-cost above its range is not worth an alert


def _alerts_all():
    """Every flagged row of the fabric list; whether seen or agreed is marked, not filtered. Worked out afresh each
    time from the list as it stands, so a corrected sheet or a changed rate changes the alerts."""
    try:
        p = pack({})
    except HTTPException:
        return []
    listed = {r["id"]: r for r in list_view({})["rows"]}
    negos = {k: nego_summary(v) for k, v in _negos().items() if v.get("events")}
    newest = {r["code"]: r for r in reversed(p["rows"]) if not r["duplicate_of"]}       # the row an older one is measured against
    seen, found = _seen(), {}
    for r in p["rows"]:
        flags = []
        qty = r["quantity"]
        on = lambda per_m: f" (Rs {_inr(abs(per_m) * qty, 0)} on {_inr(qty, 0)} m)" if qty else " (no quantity on the row, so no rupee total)"
        dup = r["duplicate_of"]
        if dup and dup == r["code"]:
            # an older row of the same code and quantity: the newer row carries the live price
            new_ = newest.get(dup)
            flags.append({"kind": "repeat", "money": 0, "counted": False,
                          "text": f"An older row for {dup}, at Rs {_inr(r['quote'])}: a newer row for the same code and quantity is on the list"
                                  + (f" at Rs {_inr(new_['quote'])}" if new_ else "") + ". If the newer one replaces it, remove this row; the alerts are on the newer row."})
        else:
            if dup:
                flags.append({"kind": "repeat", "money": 0, "counted": False,
                              "text": f"Repeats the order of {dup} ({_inr(qty, 0) + ' m at ' if qty else ''}Rs {_inr(r['quote'])}; the same cloth and quantity, or every column of the sheet the same): check it is not ordered twice. "
                                      "If it is a second order, the flags below apply to it as well; its rupees are not added to the totals."})
            if r["stance"] == "push" and r["above_band"] >= ALERT_MIN_ABOVE * r["should"]:
                flags.append({"kind": "above", "money": 0 if dup else r["above_range_money"], "counted": not dup and bool(qty),
                              "text": f"Quoted Rs {_inr(r['quote'])}, Rs {_inr(r['above_band'])} a metre above the top of its usual range (Rs {_inr(r['upper'])}; should-cost Rs {_inr(r['should'])})" + on(r["above_band"]) + "."})
            if r["stance"] == "check":
                flags.append({"kind": "low", "money": 0, "counted": False,
                              "text": f"Quoted Rs {_inr(r['quote'])}, {abs(r['gap_pct']):.0%} below the should-cost of Rs {_inr(r['should'])}: check it is per metre and for this cloth before treating it as a saving."})
            if r["sums"] and r["own_gap"] is not None and r["own_gap"] >= 0.01:
                flags.append({"kind": "sums", "money": 0 if dup else (r["own_at_stake"] or 0), "counted": not dup and bool(qty),
                              "text": f"The mill's own build-up comes to Rs {_inr(r['own_price'])}, not the Rs {_inr(r['quote'])} it asks: Rs {_inr(r['own_gap'])} a metre too much" + on(r["own_gap"]) + "."})
            elif r["sums"] and r["own_gap"] is not None and r["own_gap"] <= -0.01:
                flags.append({"kind": "sums", "money": 0, "counted": False,
                              "text": f"The sheet's own build-up comes to Rs {_inr(r['own_price'])}, Rs {_inr(-r['own_gap'])} a metre more than the Rs {_inr(r['quote'])} it asks. "
                                      "The price asked is the lower figure: hold it, and ask for the sheet to be corrected."})
            elif r["sums"]:
                flags.append({"kind": "sums", "money": 0, "counted": False,
                              "text": "The sheet's figures do not agree with each other (the ex-mill price itself is not affected): " + "; ".join(r["sums"]) + ". Ask for the sheet to be corrected."})
        if flags:
            found[r["id"]] = (r, flags)
    # the row a repeat points at is the newer one: it carries the warning too, so a sheet just uploaded says so at once,
    # even when the older row's alert has been marked seen or its price agreed
    by_id = {r["id"]: r for r in p["rows"]}
    for rid, (r, flags) in list(found.items()):
        dup = r["duplicate_of"]
        new_ = newest.get(dup) if dup else None
        if not new_ or new_["id"] == rid:
            continue
        ng = negos.get(f"Fabric list|{rid}")
        was = (f"; that row is agreed at Rs {_inr(ng['agreed'])} in the tracker" if ng and ng["status"] == "Agreed" else
               "; that row's alert was marked seen" if rid in seen else "")
        text = (f"An older row for this code and quantity is on the list at Rs {_inr(r['quote'])}{was}. If this row replaces it, remove the older one; if it is a second order, say so to the mill."
                if dup == r["code"] else
                f"The same order is already on the list as {r['code']} ({_inr(r['quantity'], 0) + ' m at ' if r['quantity'] else ''}Rs {_inr(r['quote'])}){was}: check it is not ordered twice.")
        found.setdefault(new_["id"], (by_id[new_["id"]], []))[1].insert(0, {"kind": "repeat", "money": 0, "counted": False, "text": text})
    out = []
    for rid, (r, flags) in found.items():
        src = listed.get(rid) or {}
        ng = negos.get(f"Fabric list|{rid}")
        out.append({"id": rid, "key": f"Fabric list|{rid}", "code": r["code"], "description": r["description"], "supplier": r["supplier"] or "No supplier",
                    "upload": src.get("upload") or "Added on screen", "added": src.get("added"), "flags": flags, "kinds": list(dict.fromkeys(f["kind"] for f in flags)),
                    "money": max(f["money"] for f in flags), "no_quantity": not r["quantity"], "repeat": bool(r["duplicate_of"]),
                    "seen": rid in seen, "agreed": bool(ng and ng["status"] == "Agreed")})
    return out


@app.get("/api/alerts")
def alerts():
    """The alerts still to look at, grouped by mill and the upload they came in with; and every flag, for the fabric pages."""
    every = _alerts_all()
    live = [a for a in every if not a["seen"] and not a["agreed"]]
    groups = {}
    for a in live:
        groups.setdefault((mill_key(a["supplier"]), a["upload"]), []).append(a)
    count = {k: sum(1 for a in live if k in a["kinds"]) for k in ALERT_KINDS}
    money = lambda kind: [f for a in live for f in a["flags"] if f["kind"] == kind and f["counted"]]
    return {"count": len(live), "kinds": ALERT_KINDS, "by_kind": count,
            "above_money": round(sum(f["money"] for f in money("above"))), "above_rows": len(money("above")),
            "sums_money": round(sum(f["money"] for f in money("sums"))), "sums_rows": len(money("sums")),
            "no_quantity": sum(1 for a in live if a["no_quantity"] and not a["repeat"] and any(k in a["kinds"] for k in ("above", "sums"))),
            "repeat_rows": sum(1 for a in live if a["repeat"] and any(k in a["kinds"] for k in ("above", "sums"))),
            "groups": [{"supplier": v[0]["supplier"], "mill": k[0], "upload": k[1], "rows": sorted(v, key=lambda a: -a["money"])}
                       for k, v in sorted(groups.items(), key=lambda kv: max(a["id"] for a in kv[1]), reverse=True)],       # the newest upload first
            "ids": {a["id"]: a["kinds"] for a in live},
            "all": {a["id"]: {"flags": a["flags"], "state": "seen" if a["seen"] else "agreed" if a["agreed"] else "live"} for a in every},
            "seen": sum(1 for a in every if a["seen"] and not a["agreed"]), "agreed": sum(1 for a in every if a["agreed"])}


@app.post("/api/alerts/seen")
def alerts_seen(payload: dict = Body(...)):
    """Mark alerts seen (ids), bring some back (ids with undo: true) or all back (restore: true). Shared: seen by one is seen by all."""
    ids = {str(i) for i in payload.get("ids") or []}
    seen = set() if payload.get("restore") else (_seen() - ids if payload.get("undo") else _seen() | ids)
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    tmp = SEEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(sorted(seen), f)
    os.replace(tmp, SEEN_PATH)
    return alerts()


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
                sup.append({"supplier": re.sub(r"^\d+\s+", "", str(name)).title(), "key": mill_key(re.sub(r"^\d+\s+", "", str(name))), "fabrics": len(d), "gap": float(d[gap].median()),
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


def _page(file, assets):
    # the script and stylesheet addresses carry the time they were last changed: a new deploy is a new address
    html = open(os.path.join(WEB, file), encoding="utf8").read()
    for name in assets:
        html = html.replace(f'"{name}"', f'"{name}?v={int(os.path.getmtime(os.path.join(WEB, name)))}"')
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index(request: Request):
    """The app's shell (left rail, Right cost, the "+" popup). Every other screen is the earlier front end
    shown inside it: /?embed=1 serves that front end on its own, without its page list or header."""
    if request.query_params.get("embed") == "1":
        return _page("index.html", ("app.css", "app.js"))
    return _page("rightcost.html", ("rightcost.css", "rightcost.js"))


app.mount("/", FreshFiles(directory=WEB), name="web")
