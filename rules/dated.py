"""Dated yarn rates (stage 5): a yarn's rate for a month, so a purchase order is costed on the yarn rates of its order
month. GP's decision, 27 Nov 2026: purchase orders on the rates of their order month; quotes and Cost a fabric on
today's rates; each costing says which date's rates it used.

A dated rate comes in three ways, each kept with its source: typed on the Yarn prices page (saying what it rests on),
brought in through Bring in prices (the rows reviewed there, each given a yarn of the yarn master), or loaded from the
market history in hand (inputs/Yarn_Inteliigence_Master.xlsx, sheet Yarn_Master), only where its yarn surely is a yarn
of the yarn master. The rate master's own Yarn_Rates are never changed here. Kept in the database only (data_dated.py)."""
import datetime as dt
import math
import os
import re
import pandas as pd
from rules import common, rates
import data_dated
import masters
import paths
import price_import as pi

# The rule, as the Yarn prices page shows it. One place: the code below follows it line by line.
RULE = [
    "One rate per yarn per month. A dated rate is for its calendar month only: it is not carried into the next month. "
    "A month with no dated rate for a yarn uses today's rate (the yarn master), and the costing says so for that yarn.",
    "A dated rate says what it rests on: a market circular, a price list, a yarn quote or invoice, another document, or "
    "the market history. A rate typed with no source is a Placeholder, as in the rate master: the costing warns about "
    "it and the brief treats it as it treats any placeholder.",
    "A price given as a range (low to high) counts as its midpoint, typed or brought in.",
    "Several prices for one yarn in one month count as their average, each range as its midpoint. Each price says "
    "whether it includes GST, and prices with GST and without are never averaged together: where a month has both, only "
    "those without GST are used, and a rate with GST never takes the place of one without GST for that month.",
    "The month comes from the document's own date where the server can read it (a month named in words before a day; not "
    "a phone's or a screen's file name; when the dates found disagree or are more than a year apart, the person is asked). "
    "A row with no date of the document's, a row typed in among them included, takes the document's month or the month "
    "the person chooses. It is never taken from today's date.",
    "A rate a person enters for a yarn and a month takes the place of any earlier one for that yarn and month; the "
    "earlier one is kept, marked replaced. Loading the market history never replaces a rate a person entered, never "
    "brings back a rate a person removed, and writes nothing when nothing has changed.",
    "From the market history in hand, a price is used only where its yarn surely is a yarn of the yarn master (the same "
    "fibre and blend, count, kind and spinner), in rupees a kilo, between Rs 50 and Rs 5,000; everything else is left "
    "out, and this page says what and why.",
    "A purchase order is costed on the yarn rates of its order month; a fabric code ordered in more than one month, on "
    "the month that holds most of its metres (the earlier month when two hold the same, and the costing says so). Quotes "
    "and Cost a fabric are on today's rates. Only yarn rates are dated: every other rate (weaving, dyeing, finishing, "
    "wastage, overhead, margin) is today's, and so are the usual ranges, which come from the purchase orders as costed "
    "in the pilot.",
]
RATE_LIMITS = (50.0, 5000.0)        # rupees per kilo: outside this a figure is a slip, or not a yarn rate per kilo
FIRST_MONTH = "2019-01"             # the market history in hand starts in 2019
NEED_DB = ("Dated yarn rates are kept in the database, and this server keeps its data in files (the app setting "
           "DATABASE_URL is not set). Every costing uses today's yarn rates, and says so.")
SOURCES = {"typed": "Typed in the tool", "brought in": "Brought in", "market history": "Market history"}
# what a typed rate rests on; "none" makes it a Placeholder (rule 4)
RESTS_ON = {"circular": "Market circular", "price list": "Price list (mill or spinner)", "quote": "Yarn quote",
            "invoice": "Yarn invoice", "other": "Another document", "none": None}

MARKET_FILE = paths.find("Yarn_Inteliigence_Master.xlsx")
MARKET_SHEET = "Yarn_Master"
# The only rows of the market history that are loaded: (category, material, blend, count, variant, spinner) -> the yarn
# key of the yarn master, and why the match is sure. Everything else is left out with the reason in LEFT_OUT.
SURE = {("linen yarn", "linen", "100% linen", "40 lea", "standard", "raymond"):
        ("Linen 40 Lea", "Raymond 100% linen, 40 lea, standard: the same fibre, blend and count as the yarn master's Linen 40 Lea"),
        ("linen yarn", "linen", "100% linen", "60 lea", "standard", "raymond"):
        ("Linen 60 Lea", "Raymond 100% linen, 60 lea, standard: the same fibre, blend and count as the yarn master's Linen 60 Lea")}
LEFT_OUT = {
    "raw cotton": "Raw cotton (Shankar-6, V-797, MCX), not yarn: it is the cotton price history on Cotton prices",
    "polyester yarn": "Polyester filament in deniers the yarn master does not have (it has Polyester 75D only; the file has 50, 70, 80, "
                      "100, 135, 150 and 300 denier)",
    "cotton yarn": "Semi-combed cotton yarn (KPR, SSM), priced with freight and, from July 2023, with GST. The yarn master's cotton "
                   "yarns do not say which kind they are (combed, combed compact or semi-combed), so the match is not sure. If they "
                   "are semi-combed these rows could be loaded: a question for GP",
    "viscose yarn": "Viscose and modal yarns: the yarn master has only Viscose 40/2, and the file's 2/40s comes two ways (ring doubled, "
                    "TFO doubled) without saying which the master's is",
    "blended yarn": "Cotton/viscose 52/48: no such yarn in the yarn master",
    "linen yarn": "Linen not matching a yarn of the master in fibre, blend, count, kind and spinner (44 lea, or another kind)",
}
PO_FILE = paths.find("Fabric _ 3Months_4746.xlsx")


def _has_gst(row):
    """Whether a dated rate in force includes GST (its basis says so, as every source writes it)."""
    return "includes GST" in str(row.get("basis") or "")


def _gst_keep(old, e):
    """RULE: a rate with GST never takes the place of one without GST for that month."""
    return _has_gst(e) and not _has_gst(old)


def _need_db():
    if not data_dated.available():
        raise common.Refused(503, NEED_DB)


def _this_month():
    return masters.month_of(dt.date.today())


def _months(first, last):
    """Every month from first to last, 'YYYY-MM'."""
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _yarns():
    """The yarn master: key -> its row (today's rate, basis, date)."""
    yr = common.get_masters()["Yarn_Rates"]
    return {str(r["Yarn key"]): r for _, r in yr.iterrows()}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _rate_ok(rate, what):
    lo, hi = RATE_LIMITS
    if rate is None or not lo <= rate <= hi:
        raise common.Refused(400, f"{what}: a yarn rate is between Rs {lo:,.0f} and Rs {hi:,.0f} a kilo; check what was typed")


def _month_ok(month, what):
    try:
        month = masters.month_of(month)
    except ValueError:
        raise common.Refused(400, f"{what}: give the month as YYYY-MM (for example 2026-09)")
    if month > _this_month():
        raise common.Refused(400, f"{what}: {masters.month_label(month)} is still to come; a dated rate is for a month that has begun")
    if month < FIRST_MONTH:
        raise common.Refused(400, f"{what}: {masters.month_label(month)} is before {masters.month_label(FIRST_MONTH)}; check the year")
    return month


def _range(low, high, rate, what):
    """RULE: a range counts as its midpoint. Returns (rate, low, high)."""
    if low is None and high is None:
        return rate, None, None
    if low is None or high is None:
        raise common.Refused(400, f"{what}: give both a low and a high, or neither")
    if high < low:
        raise common.Refused(400, f"{what}: the high price is below the low price")
    mid = round((low + high) / 2, 2)
    if rate is not None and abs(rate - mid) > 0.005:
        raise common.Refused(400, f"{what}: with a low and a high the rate is their midpoint, Rs {mid:,.2f}. Leave the rate empty, or type {mid:g}")
    return mid, low, high


# ------------------------------------------------------------------ the month's figure from several prices
def month_figure(prices):
    """The rate of a month from its prices (each {low, high, gst, ...}), by RULE: each range counts as its midpoint, the
    month's figure is their average; prices with GST are used only where the month has none without.
    Returns (rate, low, high, used prices, note)."""
    plain = [p for p in prices if not p.get("gst")]
    use, note = (plain, "") if plain else (prices, "includes GST, as the source says")
    if plain and len(plain) < len(prices):
        note = f"{len(prices) - len(plain)} price{'s' if len(prices) - len(plain) > 1 else ''} with GST left out (prices without GST that month)"
    mids = [(p["low"] + p["high"]) / 2 for p in use]
    return (round(sum(mids) / len(mids), 2), min(p["low"] for p in use), max(p["high"] for p in use), use, note)


# ------------------------------------------------------------------ the purchase orders' months
def po_lines():
    """The purchase-order lines the pilot was costed from, by fabric code and month: metres and value. Read from the
    purchase file (the same lines pilot.build_inputs keeps). Stage 2 keeps the purchase history with dates in the
    database; this is where it would be read from instead."""
    if not os.path.exists(PO_FILE):
        return None

    def load():
        po = pd.read_excel(PO_FILE, usecols=["Purchasing Document", "Document Date", "Material", "Purchasing Doc. Type",
                                             "Order Quantity", "Order Unit", "Net Price", "Currency", "Deletion Indicator"])
        po = po[po["Purchasing Document"].notna()]
        b = po[po["Purchasing Doc. Type"].isin(["BO", "ZLOI", "BF"]) & (po["Net Price"] > 0) & po["Deletion Indicator"].isna()
               & (po["Currency"] == "INR") & (po["Order Unit"] == "M")].copy()
        b["Material"] = b["Material"].astype(str).str.strip()
        b["month"] = pd.to_datetime(b["Document Date"], errors="coerce").dt.strftime("%Y-%m")
        b["value"] = b["Net Price"] * b["Order Quantity"]
        b = b.dropna(subset=["month"])
        return b.groupby(["Material", "month"]).agg(qty=("Order Quantity", "sum"), value=("value", "sum")).reset_index()
    return common.cached(PO_FILE + "#lines", load)


def order_months():
    """Each purchase-order fabric code's order month: the month holding most of its metres (the earlier on a tie, said
    so), with every month it was ordered in."""
    g = po_lines()
    if g is None:
        return {}

    def load():
        out = {}
        for code, d in g.groupby("Material"):
            d = d.sort_values(["qty", "month"], ascending=[False, True])
            total = float(d["qty"].sum())
            out[str(code)] = {"month": d["month"].iloc[0], "months": sorted(d["month"].tolist()),
                              "share": float(d["qty"].iloc[0]) / total if total else 1.0,
                              "tie": len(d) > 1 and float(d["qty"].iloc[0]) == float(d["qty"].iloc[1])}
        return out
    return common.cached(PO_FILE + "#months", load)


def rates_label(rates):
    """One short text for a list column or a spreadsheet: which rates a costing is on."""
    if not rates:
        return ""
    if not rates.get("month"):
        return "Today's rates"
    return f"{rates['label']}: " + ("dated yarn rate" if rates["dated"] else "today's yarn rates (no dated rate)")


def po_rates(code, months, res):
    """What a purchase-order costing says about the rates it is on: its order month, and yarn by yarn whether a dated
    rate was used. res: the costing (with rates_of when it was costed on a month)."""
    om = months.get(str(code))
    if om is None or "rates_of" not in res:
        why = (f"{code} is not in the purchase file, so its order month is not known" if months else
               "The order month is not known (the purchase file is not on this server)")
        return {"month": None, "label": "today", "dated": False, "note": why + ": costed on today's rates."}
    ro = res["rates_of"]
    more = ""
    if om.get("tie"):
        more = (f" Ordered in {', '.join(masters.month_label(x) for x in om['months'])}, the most metres in two months alike; "
                f"costed on the earlier, {ro['label']}.")
    elif len(om["months"]) > 1:
        more = (f" Ordered in {', '.join(masters.month_label(x) for x in om['months'])}; costed on {ro['label']}, which holds "
                f"{om['share']:.0%} of the metres.")
    return {"month": ro["month"], "label": ro["label"], "dated": ro["dated"],
            "note": f"Order month {ro['label']}. " + "; ".join(ro["notes"]) + "." + more}


def today_rates():
    """What a costing on today's rates says about them (quotes, Cost a fabric)."""
    return {"month": None, "label": "today", "dated": False, "note": "On today's rates (the rate master in use): a quote is costed on today's rates."}


def pilot_rates_note():
    """Which rates the dashboard's purchase-order panels are on, beside Right cost's (for the dashboard). The count of
    orders on a dated yarn rate is worked out here from the dated rates and the order months, not read from Right cost."""
    base = ("Panels 1, 2 and 4 are your purchase orders as costed in the pilot, on today's rates (no dated yarn rate), and "
            "every usual range comes from them.")
    n = sum(o["both"] + o["one"] for o in _orders_by_month(data_dated.rows())) if data_dated.available() else 0
    return base + (f" Right cost costs {n} of these orders on a dated yarn rate of their order month, so for those its should-cost "
                   "and verdict can differ from these panels." if n else
                   " Right cost costs each order on the yarn rates of its order month where a dated rate exists; none does yet, so they agree.")


# ------------------------------------------------------------------ the Yarn prices page
def page():
    """The dated rates for the Yarn prices page: each yarn's rates by month (gaps left as gaps), every entry with its
    source, what was replaced or removed, and how many purchase orders each month would use them for."""
    _need_db()
    yarns = _yarns()
    active = data_dated.rows()
    every = data_dated.rows(include_removed=True)
    last = _this_month()
    first = min([r["month"] for r in active] + [last])
    months = _months(first, last)
    series = []
    for key in sorted({r["yarn_key"] for r in active}):
        mine = {r["month"]: r for r in active if r["yarn_key"] == key}
        y = yarns.get(key)
        series.append({"key": key, "today": None if y is None else common.clean(y["Rate Rs/kg"]),
                       "in_master": y is not None,
                       "points": [None if mo not in mine else {"month": mo, "rate": mine[mo]["rate"], "low": mine[mo]["low"],
                                                               "high": mine[mo]["high"], "source": mine[mo]["source"],
                                                               "placeholder": str(mine[mo]["basis"]).startswith("Placeholder")} for mo in months]})
    orders = _orders_by_month(active)
    return {"rule": RULE, "this_month": last, "months": months, "series": series,
            "yarns": [{"key": k, "rate": common.clean(r["Rate Rs/kg"]), "basis": str(r["Basis"]), "date": common.clean(r["Rate date"])}
                      for k, r in yarns.items()],
            "rests_on": [{"value": k, "text": v or "No source: a guess (kept as a placeholder)"} for k, v in RESTS_ON.items()],
            "entries": [_shown(r) for r in active],
            "history": [_shown(r) for r in sorted((r for r in every if r["removed_at"]), key=lambda r: r["removed_at"], reverse=True)[:40]],
            "orders": orders, "limits": RATE_LIMITS, "first_month": FIRST_MONTH,
            "market_file": os.path.basename(MARKET_FILE) if os.path.exists(MARKET_FILE) else None}


def _shown(r):
    return {k: r[k] for k in ("id", "yarn_key", "month", "rate", "low", "high", "entries", "basis", "source", "entered_by",
                              "entered_at", "removed_at", "removed_by", "removed_why")} | {"label": masters.month_label(r["month"]),
                                                                                            "note": (r["detail"] or {}).get("note"),
                                                                                            "placeholder": str(r["basis"]).startswith("Placeholder")}


def _orders_by_month(active):
    """Purchase-order fabrics by order month, and how many of them have a dated rate for both, one or none of their yarns."""
    if not os.path.exists(common.PILOT):
        return []
    months = order_months()

    def load():
        f = pd.read_excel(common.PILOT, sheet_name="Fabrics")
        return f[["Fabric code", "Warp yarn", "Weft yarn"]].astype(str).to_dict("records")
    have = {(r["yarn_key"], r["month"]) for r in active}
    by = {}
    for r in common.cached(common.PILOT + "#yarns", load):
        om = months.get(str(r["Fabric code"]))
        if om is None:
            continue
        n = sum((r[s], om["month"]) in have for s in ("Warp yarn", "Weft yarn"))
        d = by.setdefault(om["month"], {"month": om["month"], "label": masters.month_label(om["month"]), "fabrics": 0, "both": 0, "one": 0, "none": 0})
        d["fabrics"] += 1
        d["both" if n == 2 else "one" if n == 1 else "none"] += 1
    return [by[k] for k in sorted(by)]


def add(payload: dict, who: str = ""):
    """A dated rate typed on the Yarn prices page: a yarn, a month, what it rests on (no source: a placeholder), whether
    it includes GST, and the rate (or a low and a high: their midpoint). It takes the place of any earlier rate for that
    yarn and month."""
    _need_db()
    payload = payload or {}
    key = str(payload.get("yarn_key") or "").strip()
    if key not in _yarns():
        raise common.Refused(400, "Choose a yarn of the yarn master")
    month = _month_ok(payload.get("month"), "Month")
    rests = str(payload.get("rests_on") or "").strip()
    if rests not in RESTS_ON:
        raise common.Refused(400, "Say what the rate rests on (a circular, a price list, a quote, an invoice, another document), "
                                  "or that it has no source: it is then kept as a placeholder")
    note = str(payload.get("note") or "").strip()[:300]
    if rests == "other" and not note:
        raise common.Refused(400, "Name the document the rate comes from in the note")
    rate, low, high = _range(_num(payload.get("low")), _num(payload.get("high")), _num(payload.get("rate")), "Rate")
    _rate_ok(rate, "Rate")
    gst = bool(payload.get("gst"))
    if RESTS_ON[rests] is None:
        basis = "Placeholder: typed in the tool with no source" + (f" ({note})" if note else "")
    else:
        basis = f"{SOURCES['typed']}: {RESTS_ON[rests]}" + (f", {note}" if note else "")
    basis += "; includes GST" if gst else ""
    _, held = data_dated.add([{"yarn_key": key, "month": month, "rate": round(rate, 2), "low": low, "high": high, "entries": 1,
                               "basis": basis, "source": "typed", "detail": {"note": note, "rests_on": rests, "gst": gst}}], who=who, keep=_gst_keep)
    if held:
        raise common.Refused(409, f"{key} already has a rate without GST for {masters.month_label(month)}, and it stays: a price with GST "
                                  "never takes the place of one without GST for the same month (the rule). Remove that rate first if it is wrong.")
    return {"saved": True, "yarn_key": key, "month": month, "rate": round(rate, 2), "placeholder": basis.startswith("Placeholder")}


def remove(payload: dict, who: str = ""):
    _need_db()
    try:
        rid = int((payload or {}).get("id"))
    except (TypeError, ValueError):
        raise common.Refused(400, "Say which dated rate to remove")
    if not data_dated.remove(rid, who=who):
        raise common.Refused(404, "No such dated rate (it may have been removed already)")
    return {"removed": 1}


# ------------------------------------------------------------------ from Bring in prices
def intake_plan(payload):
    """Which month each reviewed row would take, decided here from what the server itself read of the document (the read
    token of its review table; never a flag the page sends): a row whose date is one the server read takes that date's
    month; any other row (a row typed in, a blank cell) takes the document's month where one was read, else the month the
    person chose for rows without a date. month: one month the person chose for every row instead.
    Returns (plan, rows needing a month, groups by yarn and month, rows given no yarn)."""
    yarns = _yarns()
    reads = rates._reads.get(str(payload.get("read_token") or "")) or {"dates": set(), "month": None, "from": None}
    every = _month_ok(payload["month"], "Month") if payload.get("month") else None
    undated = _month_ok(payload["month_undated"], "Month for the rows without a date") if payload.get("month_undated") else None
    plan, need, groups, skipped = [], [], {}, 0
    for n, r in enumerate(payload.get("rows") or [], start=1):
        r = list(r) + [None] * (8 - len(r))
        date, yarn, count, low, high, src, key, gst = r[:8]
        key = str(key or "").strip()
        if not key:
            skipped += 1
            continue
        if key not in yarns:
            raise common.Refused(400, f"Row {n}: '{key}' is not a yarn of the yarn master")
        if gst not in (True, False):
            raise common.Refused(400, f"Row {n}: say whether its price includes GST")
        d = pi.read_date(date)
        if every:
            month, how = every, "month chosen for the document"
        elif d and d in reads["dates"]:
            month, how = d[:7], f"dated from {reads['from']}"
        elif reads["month"]:
            month, how = reads["month"], f"the document's month, read from {reads['from']}"
        elif undated:
            month, how = undated, "month chosen for the rows without a date"
        else:
            need.append({"row": n, "date": None if date in (None, "") else str(date),
                         "why": "no date of the document's: choose the month" if not d else f"its date {d} is not one read from the document: choose the month"})
            plan.append({"row": n, "month": None, "how": None})
            continue
        month = _month_ok(month, f"Row {n}")
        low, high = _num(low), _num(high)
        high = low if high is None else high
        if low is None:
            raise common.Refused(400, f"Row {n}: a rate is needed")
        if high < low:
            raise common.Refused(400, f"Row {n}: the high rate is below the low rate")
        _rate_ok(low, f"Row {n}")
        _rate_ok(high, f"Row {n}")
        plan.append({"row": n, "month": month, "how": how})
        groups.setdefault((key, month), []).append({"low": low, "high": high, "gst": gst, "date": d, "how": how,
                                                    "yarn": yarn, "count": count, "source": src})
    return plan, need, groups, skipped


def intake_add(payload: dict, who: str = ""):
    """Rows reviewed on Bring in prices, each given a yarn of the yarn master and saying whether its price includes GST,
    added as dated rates: by RULE, one rate per yarn and month (a range as its midpoint, several prices as their average,
    those without GST before those with). The month of each row is decided by intake_plan, never from today. preview:
    only say which month each row would take, and which rows need a month. Rows given no yarn are left out."""
    _need_db()
    payload = payload or {}
    source = str(payload.get("source") or "").strip()[:120]
    plan, need, groups, skipped = intake_plan(payload)
    if payload.get("preview"):
        return {"plan": plan, "need_month": need, "left_out": skipped}
    if need:
        raise common.Refused(400, f"{'Row' if len(need) == 1 else 'Rows'} {', '.join(str(x['row']) for x in need)}: no date of the document's, "
                                  "so choose the month for the rows without a date (nothing was added)")
    if not groups:
        raise common.Refused(400, "No row was given a yarn of the yarn master: choose the yarn for each row to add as a dated rate")
    entries = []
    for (key, month), prices in sorted(groups.items()):
        rate, low, high, used, note = month_figure(prices)
        what = source or next((p["source"] for p in prices if p["source"]), "") or "Bring in prices"
        gst = all(p["gst"] for p in used)
        entries.append({"yarn_key": key, "month": month, "rate": rate, "low": low, "high": high, "entries": len(used),
                        "basis": f"{SOURCES['brought in']}: {what}, {used[0]['how']}" + (f", {len(used)} prices averaged" if len(used) > 1 else "")
                                 + (f"; {note}" if note and not gst else "") + ("; includes GST" if gst else ""),
                        "source": "brought in", "detail": {"prices": used, "file": what, "gst": gst}})
    added, held = data_dated.add(entries, who=who, keep=_gst_keep)
    return {"added": len(added), "rows": sum(len(g) for g in groups.values()), "left_out": skipped,
            "rates": [{"yarn_key": e["yarn_key"], "month": e["month"], "rate": e["rate"], "entries": e["entries"]} for e in added],
            "kept": [{"yarn_key": e["yarn_key"], "month": e["month"], "why": "a rate without GST is in force for that month and stays"} for e in held]}


# ------------------------------------------------------------------ the market history in hand
_MON = {m.lower(): i for i, m in enumerate(masters.MONTH_NAMES, start=1)}


def _market_month(cell, year, month_name):
    """The month of a market-history row: from its date (an Excel day number, a date, or text such as '10th April 2023'
    or "4th Oct'2023"); a text with only a month ('_ July', 'Sep') takes the year from the Year column when the Month
    column names the same month. The Year column is not trusted over a full date (it says 2020 on rows dated 2023).
    Returns 'YYYY-MM' or None."""
    if isinstance(cell, (pd.Timestamp, dt.datetime, dt.date)):
        return f"{cell.year:04d}-{cell.month:02d}"
    if isinstance(cell, (int, float)) and not (isinstance(cell, float) and math.isnan(cell)) and 20000 < cell < 80000:
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(cell))
        return f"{d.year:04d}-{d.month:02d}"
    text = str(cell or "")
    for hit in re.finditer(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*([A-Za-z]{3,9})\.?(?:\s+[A-Za-z]{3,9})?\s*['’]?\s*(\d{4}|\d{2})(?!\d)", text):
        mo = _MON.get(hit.group(2)[:3].lower())
        if mo:
            yr = int(hit.group(3))
            yr = yr + 2000 if yr < 100 else yr
            return f"{yr:04d}-{mo:02d}"
    words = [w[:3].lower() for w in re.findall(r"[A-Za-z]{3,9}", text)]
    named = next((_MON[w] for w in words if w in _MON), None)
    col = _MON.get(str(month_name or "")[:3].lower())
    yr = _num(year)
    if named and col == named and yr:
        return f"{int(yr):04d}-{named:02d}"
    return None


def _market_day(cell):
    """A market-history row's date as it can be read: an Excel day number as a date, else the text as written."""
    if isinstance(cell, (int, float)) and not (isinstance(cell, float) and math.isnan(cell)) and 20000 < cell < 80000:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(cell))).isoformat()
    return str(cell.date() if isinstance(cell, (pd.Timestamp, dt.datetime)) else cell)


def _per_kilo(unit):
    return str(unit or "").replace(" ", "").lower() in ("₹/kg", "rs/kg", "inr/kg", "rs./kg")


def _market_price(r):
    """(low, high) of a market-history price, in rupees a kilo, or (None, why): the standard price where its unit is a kilo,
    else the original price (a figure, or a range '1600-1650') where that unit is a kilo."""
    v = _num(r.get("Standard Price"))
    if v is not None and v > 0:
        return ((v, v), None) if _per_kilo(r.get("Standard Unit")) else (None, "Not a price per kilo")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(r.get("Original Price") or ""))]
    if not nums:
        return None, "It has no price"
    if not _per_kilo(r.get("Original Unit")):
        return None, "Not a price per kilo"
    if len(nums) == 1:
        return (nums[0], nums[0]), None
    if len(nums) == 2 and nums[0] <= nums[1]:
        return (nums[0], nums[1]), None
    return None, "Its price cannot be read"


def market_decide(r, yarns):
    """One row of the market history: (yarn key, month, price) to use, or (None, why it is left out)."""
    low_ = lambda k: re.sub(r"\s+", " ", str(r.get(k) or "").strip().lower())
    cat = low_("Yarn Category")
    sure = SURE.get((cat, low_("Material"), low_("Blend / Composition"), low_("Count"), low_("Variant"), low_("Supplier / Mill")))
    if sure is None:
        return None, LEFT_OUT.get(cat, "No yarn of the yarn master matches it surely")
    if sure[0] not in yarns:
        return None, f"{sure[0]} is no longer in the yarn master"
    price, why = _market_price(r)
    if price is None:
        return None, why
    lo, hi = RATE_LIMITS
    if not (lo <= price[0] and price[1] <= hi):
        return None, f"A price outside Rs {lo:,.0f} to Rs {hi:,.0f} a kilo: not taken as a yarn rate"
    month = _market_month(r.get("Date"), r.get("Year"), r.get("Month"))
    if month is None:
        return None, "Its date cannot be read"
    return {"key": sure[0], "month": month, "low": price[0], "high": price[1],
            "gst": str(r.get("GST Included") or "").lower().startswith("yes"), "date": _market_day(r.get("Date")),
            "supplier": str(r.get("Supplier / Mill") or ""), "count": str(r.get("Count") or ""), "variant": str(r.get("Variant") or ""),
            "price_basis": str(r.get("Price Basis") or ""), "why_sure": sure[1]}, None


def _market_read():
    """The market history, every row decided: used (by yarn key and month) or left out (with why)."""
    if not os.path.exists(MARKET_FILE):
        return None

    def load():
        df = pd.read_excel(MARKET_FILE, sheet_name=MARKET_SHEET)
        return df.iloc[:, :20].astype(object).where(pd.notna(df.iloc[:, :20]), None).to_dict("records")
    yarns = _yarns()
    use, out = {}, {}
    for r in common.cached(MARKET_FILE + "#" + MARKET_SHEET, load):
        got, why = market_decide(r, yarns)
        if why:
            out[why] = out.get(why, 0) + 1
            continue
        p = {k: v for k, v in got.items() if k not in ("key", "month")}
        use.setdefault((got["key"], got["month"]), []).append(p)
    return use, out


def _market_entries(use):
    entries = []
    for (key, month), prices in sorted(use.items()):
        rate, low, high, used, note = month_figure(prices)
        p = used[0]
        rng = f"Rs {low:,.0f} to {high:,.0f}" if low != high else f"Rs {low:,.0f}"
        basis = (f"{SOURCES['market history']} ({os.path.basename(MARKET_FILE)}): {p['supplier']} {p['count']}, {len(used)} "
                 f"price{'s' if len(used) > 1 else ''} in {masters.month_label(month)}, {rng}" + (", midpoint" if low != high and len(used) == 1 else ", averaged" if len(used) > 1 else "")
                 + (f"; {p['price_basis'].lower()}" if p["price_basis"] else "") + (f"; {note}" if note else ""))
        entries.append({"yarn_key": key, "month": month, "rate": rate, "low": low, "high": high, "entries": len(used), "basis": basis,
                        "source": "market history", "detail": {"prices": used, "file": os.path.basename(MARKET_FILE), "why_sure": p["why_sure"]}})
    return entries


def _market_plan():
    """Each monthly rate the market history gives, and what loading it would do: new, changed, unchanged (nothing to
    write), kept (a person entered a rate for that yarn and month) or held (a person removed the rate for it)."""
    got = _market_read()
    if got is None:
        raise common.Refused(404, "The market history file (Yarn_Inteliigence_Master.xlsx) is not on this server")
    use, out = got
    every = data_dated.rows(include_removed=True)
    active = {(r["yarn_key"], r["month"]): r for r in every if not r["removed_at"]}
    removed = {(r["yarn_key"], r["month"]) for r in every if r["removed_why"] == "removed"}
    plan = []
    for e in _market_entries(use):
        k, now = (e["yarn_key"], e["month"]), active.get((e["yarn_key"], e["month"]))
        if now is not None and now["source"] != "market history":
            status = "kept"
        elif now is None and k in removed:
            status = "held"
        elif now is not None and all(now[f] == e[f] for f in ("rate", "low", "high", "entries", "basis")):
            status = "unchanged"
        else:
            status = "changed" if now is not None else "new"
        plan.append((e, status))
    return plan, use, out


STATUS = {"new": "", "changed": "the market history changed: will be replaced", "unchanged": "loaded already: nothing to do",
          "kept": "a person's rate is kept", "held": "removed by a person: not loaded again"}


def market_preview():
    """What loading the market history would add, and everything it leaves out, with why."""
    _need_db()
    plan, use, out = _market_plan()
    return {"file": os.path.basename(MARKET_FILE), "sheet": MARKET_SHEET,
            "rows": sum(len(v) for v in use.values()) + sum(out.values()), "used_rows": sum(len(v) for v in use.values()),
            "to_load": sum(1 for _, s in plan if s in ("new", "changed")),
            "rates": [{"yarn_key": e["yarn_key"], "month": e["month"], "label": masters.month_label(e["month"]), "rate": e["rate"],
                       "low": e["low"], "high": e["high"], "entries": e["entries"], "basis": e["basis"], "status": s, "status_text": STATUS[s]}
                      for e, s in plan],
            "left_out": [{"why": k, "rows": v} for k, v in sorted(out.items(), key=lambda kv: -kv[1])]}


def market_load(who: str = ""):
    """Load the market history's monthly rates (only the yarns surely matched). A rate a person entered stays, a rate a
    person removed is not brought back, and a load that changes nothing writes nothing (so nothing is worked out again)."""
    _need_db()
    plan, _, _ = _market_plan()
    write = [e for e, s in plan if s in ("new", "changed")]
    count = lambda st: sum(1 for _, s in plan if s == st)
    added, held = data_dated.add(write, who=who or "market history", keep=lambda old, e: old["source"] != "market history" or _gst_keep(old, e)) if write else ([], [])
    return {"added": len(added), "kept": count("kept") + len(held), "held_removed": count("held"), "unchanged": count("unchanged"),
            "kept_rates": [{"yarn_key": e["yarn_key"], "month": e["month"]} for e, s in plan if s == "kept"] +
                          [{"yarn_key": e["yarn_key"], "month": e["month"]} for e in held]}
