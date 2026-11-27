"""Dated yarn rates (stage 5): a yarn's rate for a month, so a purchase order is costed on the yarn rates of its order
month. GP's decision, 27 Nov 2026: purchase orders on the rates of their order month; quotes and Cost a fabric on
today's rates; each costing says which date's rates it used.

A dated rate comes in three ways, each kept with its source: typed on the Yarn prices page, brought in through Bring in
prices (the rows reviewed there, each given a yarn of the yarn master), or loaded from the market history in hand
(inputs/Yarn_Inteliigence_Master.xlsx, sheet Yarn_Master), only where its yarn surely is a yarn of the yarn master.
The rate master's own Yarn_Rates are never changed here. Kept in the database only (data_dated.py)."""
import datetime as dt
import math
import os
import re
import pandas as pd
from rules import common
import data_dated
import masters
import paths

# The rule, as the Yarn prices page shows it. One place: the code below follows it line by line.
RULE = [
    "One rate per yarn per month. A dated rate is for its calendar month only: it is not carried into the next month. "
    "A month with no dated rate for a yarn uses today's rate (the yarn master), and the costing says so for that yarn.",
    "A price given as a range (low to high) counts as its midpoint.",
    "Several prices for one yarn in one month count as their average, each range as its midpoint. Prices with GST and "
    "prices without are never averaged together: where a month has both, only those without GST are used.",
    "A rate a person enters for a yarn and a month (typed here, or brought in through Bring in prices) takes the place "
    "of any earlier one for that yarn and month; the earlier one is kept, marked replaced. Loading the market history "
    "never replaces a rate a person entered.",
    "From the market history in hand, a price is used only where its yarn surely is a yarn of the yarn master (the "
    "same fibre, count and kind); everything else is left out, and this page says what and why.",
    "A purchase order is costed on the yarn rates of its order month; a fabric code ordered in more than one month, on "
    "the month that holds most of its metres. Quotes and Cost a fabric are on today's rates. Only yarn rates are "
    "dated: every other rate (weaving, dyeing, finishing, wastage, overhead, margin) is today's.",
]
RATE_LIMITS = (50.0, 5000.0)        # rupees per kilo: outside this a typed figure is a slip
FIRST_MONTH = "2019-01"             # the market history in hand starts in 2019
NEED_DB = ("Dated yarn rates are kept in the database, and this server keeps its data in files (the app setting "
           "DATABASE_URL is not set). Every costing uses today's yarn rates, and says so.")
SOURCES = {"typed": "Typed in the tool", "brought in": "Brought in", "market history": "Market history"}

MARKET_FILE = paths.find("Yarn_Inteliigence_Master.xlsx")
MARKET_SHEET = "Yarn_Master"
# The only rows of the market history that are loaded: (yarn category, count) -> yarn key of the yarn master, and why
# the match is sure. Everything else is left out with the reason in LEFT_OUT.
SURE = {("linen yarn", "40 lea"): ("Linen 40 Lea", "Raymond 100% linen, 40 lea: the same fibre and count as the yarn master's Linen 40 Lea"),
        ("linen yarn", "60 lea"): ("Linen 60 Lea", "Raymond 100% linen, 60 lea: the same fibre and count as the yarn master's Linen 60 Lea")}
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
    "linen yarn": "Linen 44 lea: no such yarn in the yarn master",
}
PO_FILE = paths.find("Fabric _ 3Months_4746.xlsx")


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
def order_months():
    """Each purchase-order fabric code's order month: the month holding most of its metres (the earlier on a tie), with
    every month it was ordered in. Read from the purchase file the pilot was costed from, the same lines it kept.
    Stage 2 keeps the purchase history with dates in the database; this is where it would be read from instead."""
    if not os.path.exists(PO_FILE):
        return {}

    def load():
        po = pd.read_excel(PO_FILE, usecols=["Purchasing Document", "Document Date", "Material", "Purchasing Doc. Type",
                                             "Order Quantity", "Order Unit", "Net Price", "Currency", "Deletion Indicator"])
        po = po[po["Purchasing Document"].notna()]
        b = po[po["Purchasing Doc. Type"].isin(["BO", "ZLOI", "BF"]) & (po["Net Price"] > 0) & po["Deletion Indicator"].isna()
               & (po["Currency"] == "INR") & (po["Order Unit"] == "M")].copy()      # the lines pilot.build_inputs keeps
        b["Material"] = b["Material"].astype(str).str.strip()
        b["month"] = pd.to_datetime(b["Document Date"], errors="coerce").dt.strftime("%Y-%m")
        b = b.dropna(subset=["month"])
        g = b.groupby(["Material", "month"])["Order Quantity"].sum().reset_index()
        out = {}
        for code, d in g.groupby("Material"):
            d = d.sort_values(["Order Quantity", "month"], ascending=[False, True])
            total = float(d["Order Quantity"].sum())
            out[str(code)] = {"month": d["month"].iloc[0], "months": sorted(d["month"].tolist()),
                              "share": float(d["Order Quantity"].iloc[0]) / total if total else 1.0}
        return out
    return common.cached(PO_FILE + "#months", load)


def po_rates(code, months, res):
    """What a purchase-order costing says about the rates it is on: its order month, and yarn by yarn whether a dated
    rate was used. res: the costing (with rates_of when it was costed on a month)."""
    om = months.get(str(code))
    if om is None or "rates_of" not in res:
        return {"month": None, "label": "today", "dated": False,
                "note": "The order month is not known (the purchase file is not on this server): costed on today's rates."}
    ro = res["rates_of"]
    more = ""
    if len(om["months"]) > 1:
        more = (f" Ordered in {', '.join(masters.month_label(x) for x in om['months'])}; costed on {ro['label']}, which holds "
                f"{om['share']:.0%} of the metres.")
    return {"month": ro["month"], "label": ro["label"], "dated": ro["dated"],
            "note": f"Order month {ro['label']}. " + "; ".join(ro["notes"]) + "." + more}


def today_rates():
    """What a costing on today's rates says about them (quotes, Cost a fabric)."""
    return {"month": None, "label": "today", "dated": False, "note": "On today's rates (the rate master in use): a quote is costed on today's rates."}


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
                                                               "high": mine[mo]["high"], "source": mine[mo]["source"]} for mo in months]})
    orders = _orders_by_month(active)
    return {"rule": RULE, "this_month": last, "months": months, "series": series,
            "yarns": [{"key": k, "rate": common.clean(r["Rate Rs/kg"]), "basis": str(r["Basis"]), "date": common.clean(r["Rate date"])}
                      for k, r in yarns.items()],
            "entries": [_shown(r) for r in active],
            "history": [_shown(r) for r in sorted((r for r in every if r["removed_at"]), key=lambda r: r["removed_at"], reverse=True)[:40]],
            "orders": orders, "limits": RATE_LIMITS, "first_month": FIRST_MONTH,
            "market_file": os.path.basename(MARKET_FILE) if os.path.exists(MARKET_FILE) else None}


def _shown(r):
    return {k: r[k] for k in ("id", "yarn_key", "month", "rate", "low", "high", "entries", "basis", "source", "entered_by",
                              "entered_at", "removed_at", "removed_by", "removed_why")} | {"label": masters.month_label(r["month"]),
                                                                                            "note": (r["detail"] or {}).get("note")}


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
    """A dated rate typed on the Yarn prices page: a yarn, a month, and the rate (or a low and a high, counted as their
    midpoint). It takes the place of any earlier rate for that yarn and month."""
    _need_db()
    payload = payload or {}
    key = str(payload.get("yarn_key") or "").strip()
    if key not in _yarns():
        raise common.Refused(400, "Choose a yarn of the yarn master")
    month = _month_ok(payload.get("month"), "Month")
    low, high, rate = _num(payload.get("low")), _num(payload.get("high")), _num(payload.get("rate"))
    if rate is None and low is not None:
        high = low if high is None else high
        if high < low:
            raise common.Refused(400, "The high price is below the low price")
        rate = round((low + high) / 2, 2)           # RULE: a range counts as its midpoint
    _rate_ok(rate, "Rate")
    if low is not None and high is not None and not low <= rate <= high:
        raise common.Refused(400, "The rate is outside the low to high range typed with it")
    note = str(payload.get("note") or "").strip()[:300]
    basis = SOURCES["typed"] + (f": {note}" if note else "")
    data_dated.add([{"yarn_key": key, "month": month, "rate": round(rate, 2), "low": low, "high": high, "entries": 1,
                     "basis": basis, "source": "typed", "detail": {"note": note} if note else {}}], who=who)
    return {"saved": True, "yarn_key": key, "month": month, "rate": round(rate, 2)}


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
def intake_add(payload: dict, who: str = ""):
    """Rows reviewed on Bring in prices, each given a yarn of the yarn master, added as dated rates: by RULE, one rate per
    yarn and month (a range as its midpoint, several prices as their average). Rows given no yarn are left out."""
    _need_db()
    yarns = _yarns()
    rows = (payload or {}).get("rows") or []
    source = str((payload or {}).get("source") or "").strip()[:120]
    groups, skipped = {}, 0
    for n, r in enumerate(rows, start=1):
        r = list(r) + [None] * (7 - len(r))
        date, yarn, count, low, high, src, key = r[:7]
        key = str(key or "").strip()
        if not key:
            skipped += 1
            continue
        if key not in yarns:
            raise common.Refused(400, f"Row {n}: '{key}' is not a yarn of the yarn master")
        month = _month_ok(str(date or "")[:10], f"Row {n}")
        low, high = _num(low), _num(high)
        high = low if high is None else high
        if low is None:
            raise common.Refused(400, f"Row {n}: a rate is needed")
        if high < low:
            raise common.Refused(400, f"Row {n}: the high rate is below the low rate")
        _rate_ok(low, f"Row {n}")
        _rate_ok(high, f"Row {n}")
        groups.setdefault((key, month), []).append({"low": low, "high": high, "gst": False, "date": str(date or "")[:10],
                                                    "yarn": yarn, "count": count, "source": src or source})
    if not groups:
        raise common.Refused(400, "No row was given a yarn of the yarn master: choose the yarn for each row to add as a dated rate")
    entries = []
    for (key, month), prices in sorted(groups.items()):
        rate, low, high, used, note = month_figure(prices)
        what = source or next((p["source"] for p in prices if p["source"]), "") or "Bring in prices"
        entries.append({"yarn_key": key, "month": month, "rate": rate, "low": low, "high": high, "entries": len(used),
                        "basis": f"{SOURCES['brought in']}: {what}" + (f", {len(used)} prices averaged" if len(used) > 1 else ""),
                        "source": "brought in", "detail": {"prices": used, "file": what}})
    data_dated.add(entries, who=who)
    return {"added": len(entries), "rows": sum(len(g) for g in groups.values()), "left_out": skipped,
            "rates": [{"yarn_key": e["yarn_key"], "month": e["month"], "rate": e["rate"], "entries": e["entries"]} for e in entries]}


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


def _market_price(standard, original):
    """(low, high) of a market-history price: the standard price, or the original written as a range ('1600-1650')."""
    v = _num(standard)
    if v is not None and v > 0:
        return v, v
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(original or ""))]
    if len(nums) == 1:
        return nums[0], nums[0]
    if len(nums) == 2 and nums[0] <= nums[1]:
        return nums[0], nums[1]
    return None


def _market_read():
    """The market history, every row decided: loaded (with its yarn key and month) or left out (with why)."""
    if not os.path.exists(MARKET_FILE):
        return None

    def load():
        df = pd.read_excel(MARKET_FILE, sheet_name=MARKET_SHEET)
        return df.iloc[:, :20].astype(object).where(pd.notna(df.iloc[:, :20]), None).to_dict("records")
    yarns = _yarns()
    use, out = {}, {}
    for r in common.cached(MARKET_FILE + "#" + MARKET_SHEET, load):
        cat, count = str(r.get("Yarn Category") or "").strip().lower(), str(r.get("Count") or "").strip().lower()
        sure = SURE.get((cat, count))
        why = None
        if sure is None:
            why = LEFT_OUT.get(cat, "No yarn of the yarn master matches it surely")
        elif sure[0] not in yarns:
            why = f"{sure[0]} is no longer in the yarn master"
        elif str(r.get("Standard Unit") or r.get("Original Unit") or "").replace(" ", "") not in ("₹/kg", "Rs/kg"):
            why = "Not a price per kilo"
        month = None if why else _market_month(r.get("Date"), r.get("Year"), r.get("Month"))
        price = None if why or month is None else _market_price(r.get("Standard Price"), r.get("Original Price"))
        if why is None and month is None:
            why = "Its date cannot be read"
        elif why is None and price is None:
            why = "It has no price"
        if why:
            out[why] = out.get(why, 0) + 1
            continue
        use.setdefault((sure[0], month), []).append({
            "low": price[0], "high": price[1], "gst": str(r.get("GST Included") or "").lower().startswith("yes"),
            "date": _market_day(r.get("Date")), "supplier": str(r.get("Supplier / Mill") or ""), "count": str(r.get("Count") or ""),
            "variant": str(r.get("Variant") or ""), "price_basis": str(r.get("Price Basis") or ""), "why_sure": sure[1]})
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


def market_preview():
    """What loading the market history would add, and everything it leaves out, with why."""
    _need_db()
    got = _market_read()
    if got is None:
        raise common.Refused(404, "The market history file (Yarn_Inteliigence_Master.xlsx) is not on this server")
    use, out = got
    entries = _market_entries(use)
    have = {(r["yarn_key"], r["month"]): r for r in data_dated.rows()}
    return {"file": os.path.basename(MARKET_FILE), "sheet": MARKET_SHEET,
            "rows": sum(len(v) for v in use.values()) + sum(out.values()), "used_rows": sum(len(v) for v in use.values()),
            "rates": [{"yarn_key": e["yarn_key"], "month": e["month"], "label": masters.month_label(e["month"]), "rate": e["rate"],
                       "low": e["low"], "high": e["high"], "entries": e["entries"], "basis": e["basis"],
                       "held": (e["yarn_key"], e["month"]) in have and have[(e["yarn_key"], e["month"])]["source"] != "market history"}
                      for e in entries],
            "left_out": [{"why": k, "rows": v} for k, v in sorted(out.items(), key=lambda kv: -kv[1])]}


def market_load(who: str = ""):
    """Load the market history's monthly rates (only the yarns surely matched). A rate a person entered for the same yarn
    and month stays; an earlier load's rate is replaced, so loading twice changes nothing."""
    _need_db()
    got = _market_read()
    if got is None:
        raise common.Refused(404, "The market history file (Yarn_Inteliigence_Master.xlsx) is not on this server")
    entries = _market_entries(got[0])
    added, held = data_dated.add(entries, who=who or "market history", keep=lambda old: old["source"] != "market history")
    return {"added": len(added), "kept": len(held),
            "kept_rates": [{"yarn_key": e["yarn_key"], "month": e["month"]} for e in held]}
