"""The dashboard and its insights, the rate tables shown read-only, cotton prices and the pilot results."""
import json
import os
import re
import pandas as pd
from rules import common, costing, mills, rates
import masters


def _warm_pilot():
    """The fit by fabric type (panel 1), which the brief's usual ranges come from, worked out if it is not yet, or if
    what it rests on has changed (stage 2: the purchase-order rows are worked out again from what was bought)."""
    if os.path.exists(common.PILOT):
        try:
            _pilot_insights()
        except Exception:
            pass


def dashboard():
    m = common.get_masters()
    log = common.read_log()
    gaps = pd.to_numeric(log["Gap %"], errors="coerce").dropna()
    cot = m["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    cotton = None
    if len(cot):
        last = cot.iloc[-1]
        prev = cot[cot["Date"] <= last["Date"] - pd.Timedelta(days=30)]
        cotton = {"price": common.clean(last["Price"]), "date": common.clean(last["Date"]), "source": str(last["Source"]),
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
        yarns.append({"key": y["Yarn key"], "rate": rate, "date": common.clean(y["Rate date"]), "basis": str(y["Basis"]),
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
                      "then": then, "saved_on": common.clean(r.get("Saved on"))})
    return {"saved": common.records(shown[[c for c in common.LOG_COLS if c in shown.columns]]), "saved_items": items,
            "saved_count": len(log),
            "avg_gap_pct": None if gaps.empty else float(gaps.mean()), "cotton": cotton, "yarns": yarns,
            "placeholders": costing.placeholder_count(m), "benchmarks": common.records(m["Supplier_Benchmarks"])}


# ------------------------------------------------------------------ dashboard insights
def trust(within10, median_gap):
    """How far the should-cost can be leaned on for a group of fabrics, from how it fits the prices paid.
    'firm': at least half land within 10% and the middle gap is small. Otherwise 'weak': the gap says
    more about the tool than about the supplier, and no colour should call it a good or bad deal."""
    return "firm" if within10 >= 0.5 and abs(median_gap) <= 6 else "weak"


BUCKETS = ["Yarn", "Yarn dyeing", "Sizing and weaving", "Dyeing and finishing", "Losses", "Overhead", "Margin",
           "Upcharges and quantity terms"]


def _pilot_insights():
    """The pilot's own panels (fit by fabric type, cost split by route, suppliers, order size), on the purchase-order
    rows as Right cost has them: worked out again from what was bought, ZLOI left out (GP, 27 Nov 2026), the pilot
    workbook itself never changed. Kept until those rows change; the brief's usual ranges come from it."""
    from rules import purchases
    key, all_rows = purchases.pilot_rows()
    hit = common._cache.get(common.PILOT + "#insights")
    if hit and hit[0] == key:
        return hit[1]
    rows = [r for r in all_rows if r["PO price Rs/m"] is not None and r["Should-cost Rs/m"] is not None]

    def from_pilot():
        if not rows:
            return None
        f = pd.DataFrame(rows)
        gap = "PO above should-cost %"
        for col in ["PO metres", "PO price Rs/m", "Should-cost Rs/m", gap] + [f"{b} Rs/m" for b in BUCKETS]:
            if col in f:
                f[col] = pd.to_numeric(f[col], errors="coerce")
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
                sup.append({"supplier": re.sub(r"^\d+\s+", "", str(name)).title(), "key": mills.mill_key(re.sub(r"^\d+\s+", "", str(name))), "fabrics": len(d), "gap": float(d[gap].median()),
                            "within10": within, "trust": trust(within, float(d[gap].median())),
                            "mostly": f"{mix.index[0][0]} {mix.index[0][1].lower()}", "mostly_share": float(mix.iloc[0] / len(d))})
        sup.sort(key=lambda c: -c["fabrics"])
        qty = []
        for label, lo, hi in (("Below 1,000 m", 0, 1000), ("1,000 to 3,000 m", 1000, 3000), ("3,000 m and above", 3000, 1e12)):
            d = f[(f["PO metres"] >= lo) & (f["PO metres"] < hi)]
            qty.append({"band": label, "fabrics": len(d), "paid": float(d["PO price Rs/m"].median()) if len(d) else None})
        return {"categories": cats, "split": split, "suppliers": sup, "quantity": qty, "fabrics": len(f),
                "median_gap": float(f[gap].median()), "within10": float((f[gap].abs() <= 10).mean())}

    p = from_pilot()
    common._cache[common.PILOT + "#insights"] = (key, p)
    return p


def insights():
    """The dashboard's own-data panels: what was paid and what it should cost by fabric type, where the
    rupee goes by route, the cotton price by year, and how far a yarn price move carries into a fabric."""
    m = common.get_masters()
    p = _pilot_insights() if os.path.exists(common.PILOT) else None
    cot = m["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    years = [{"year": int(y), "average": float(d["Price"].mean()), "low": float(d["Price"].min()), "high": float(d["Price"].max()),
              "to": common.clean(d["Date"].max())} for y, d in cot.groupby(cot["Date"].dt.year)]
    ref = masters.cost(masters.EXAMPLE_ROW, m)
    ys = costing.yarn_sensitivity(ref)
    slab = m["Order_Slab"].set_index("Order size")["Overhead add (points)"].to_dict()
    card = {"print": m["Print_Methods"].set_index("Print method")["Rs per metre"].to_dict(),
            "quantity": common.records(m["Quantity_Terms"][["Quantity band", "Small-lot upcharge %", "Volume discount Rs per metre"]])}
    return {"pilot": p, "cotton_years": years, "cotton_unit": str(cot["Unit"].iloc[-1]) if len(cot) else "",
            "reference": {"name": masters.EXAMPLE_ROW["Description"], "total": ref["total_per_m"], **ys},
            "order_slab": {k: common.clean(v) for k, v in slab.items()}, "card": card,
            "placeholders": costing.placeholder_count(m), "benchmarks": common.records(m["Supplier_Benchmarks"])}


def table(sheet: str):
    m = common.get_masters()
    if sheet not in rates.TABLES or sheet not in m:
        raise common.Refused(404, "No such table")
    return {"label": rates.TABLES[sheet], **common.records(m[sheet])}


def cotton():
    cot = common.get_masters()["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    return {"points": [[common.clean(d), common.clean(p)] for d, p in zip(cot["Date"], cot["Price"])],
            "unit": str(cot["Unit"].iloc[-1]) if len(cot) else "", "source": str(cot["Source"].iloc[-1]) if len(cot) else ""}


def pilot():
    if not os.path.exists(common.PILOT):
        raise common.Refused(404, "Pilot results are not on this server")

    def load():
        x = pd.read_excel(common.PILOT, sheet_name=["Funnel", "Overall", "Rate card steps", "Rate card inputs",
                                             "By route and weave", "By supplier"])
        out = {k: common.records(v) for k, v in x.items()}
        if os.path.exists(common.DRAFT):
            d = pd.read_excel(common.DRAFT, sheet_name=["Order size", "Weaving", "Printing", "Held-back test"])
            out.update({"Draft: " + k: common.records(v) for k, v in d.items()})
        return out
    return common.cached(common.PILOT, load)
