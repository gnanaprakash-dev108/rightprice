"""Mill cost sheets: a mill's own figures for a fabric, set beside the rate master, and drafted into
rate changes that GP approves one by one.

A mill cost sheet comes in the template below: one row per fabric, with the mill's yarn, sizing,
weaving, dyeing and finishing rates, its wastage, overhead and margin, and its price. For each row:

- every figure is set beside the rate the tool used for that fabric, with that rate's basis;
- the should-cost is worked again on the mill's own figures, and set beside the mill's price, so a
  sheet whose own figures do not add up to its price shows it;
- each rate the sheets disagree with becomes a draft: the middle (median) of the mills' figures
  for that rate, with how many sheets stand behind it.

Nothing here changes a rate. apply() does, only for the drafts GP ticks, after a dated backup.
"""
import datetime as dt
import statistics

import pandas as pd

import engine
import masters

# column, the engine input it replaces, unit, what it is
COLUMNS = [
    ("Mill", None, "", "Name of the mill"),
    ("Fabric code", None, "", "The mill's or your code"),
    ("Route", None, "", "Yarn Dyed, Piece Dyed, RFD / Bleached or Printed"),
    ("Weave", None, "", "As on the weave list (Plain, Twill-2/1, Dobby, ...)"),
    ("Warp yarn", None, "", "As in the yarn master (Cotton 40S, ...)"),
    ("Weft yarn", None, "", "As in the yarn master"),
    ("EPI", None, "", "Ends per inch"),
    ("PPI", None, "", "Picks per inch"),
    ("Finished width (in)", None, "", "Inches"),
    ("Finish", None, "", "As on the finish list; blank = Normal"),
    ("Shade", None, "", "Light, Medium or Dark; blank = Medium"),
    ("Warp yarn Rs/kg", "warp_rate", "Rs/kg", "The mill's price of the warp yarn"),
    ("Weft yarn Rs/kg", "weft_rate", "Rs/kg", "The mill's price of the weft yarn"),
    ("Sizing Rs/kg warp", "sizing_rate", "Rs/kg", ""),
    ("Weaving Rs/pick", "weaving_rate", "Rs/pick", "Per pick per metre"),
    ("Yarn dyeing Rs/kg", "yarn_dye", "Rs/kg", "Yarn dyed only"),
    ("Piece dyeing Rs/kg greige", "piece_dye_rate", "Rs/kg", "Piece dyed, printed or bleached only"),
    ("Finishing Rs/kg greige", "finishing_rate", "Rs/kg", ""),
    ("Process wastage %", "process_wastage", "%", "Losses in dyeing and finishing"),
    ("Overhead %", "overhead", "%", "Mill overhead"),
    ("Margin %", "margin", "%", "Mill margin"),
    ("Mill's price Rs/m", None, "Rs/m", "The ex-mill price the sheet arrives at"),
]
FIGURES = [(c, k, u) for c, k, u, _ in COLUMNS if k]
PCT = {"process_wastage", "overhead", "margin"}


def template():
    """An empty template with one filled example row (the V1 example on the rate master's own figures)."""
    m = masters.load()
    res = masters.cost(dict(masters.EXAMPLE_ROW), m)
    i = res["inputs"]
    ex = {"Mill": "Example mill", "Fabric code": "Qlty-1", "Route": "Yarn Dyed", "Weave": "Dobby", "Warp yarn": "Cotton 40S",
          "Weft yarn": "Cotton 40S", "EPI": 132, "PPI": 84, "Finished width (in)": 58, "Finish": "Normal", "Shade": "Medium",
          "Warp yarn Rs/kg": i["warp_rate"], "Weft yarn Rs/kg": i["weft_rate"], "Sizing Rs/kg warp": i["sizing_rate"],
          "Weaving Rs/pick": i["weaving_rate"], "Yarn dyeing Rs/kg": i["warp_dye"], "Piece dyeing Rs/kg greige": None,
          "Finishing Rs/kg greige": i["finishing_rate"], "Process wastage %": i["process_wastage"] * 100,
          "Overhead %": i["overhead"] * 100, "Margin %": i["margin"] * 100, "Mill's price Rs/m": None}
    # the example's price is what its own figures give, on the choices the template carries
    ex["Mill's price Rs/m"] = round(masters.cost(_choices(ex), m)["total_per_m"], 2)
    return pd.DataFrame([ex], columns=[c for c, *_ in COLUMNS]), pd.DataFrame([(c, u, d) for c, _, u, d in COLUMNS], columns=["Column", "Unit", "What it is"])


def _num(v):
    try:
        return None if v is None or v == "" or (isinstance(v, float) and v != v) else float(v)
    except (TypeError, ValueError):
        return None


def is_cost_sheet(df):
    return {"Mill", "Route", "Weave", "EPI", "PPI", "Overhead %", "Margin %"} <= {str(c).strip() for c in df.columns}


def read(df):
    """Rows of a cost sheet as dicts, blank rows dropped."""
    df = df.rename(columns=lambda c: str(c).strip())
    rows = []
    for r in df.to_dict("records"):
        if all(_num(r.get(c)) is None and not str(r.get(c) or "").strip() for c in ("Mill", "Fabric code", "EPI", "PPI")):
            continue
        rows.append({c: (None if (isinstance(r.get(c), float) and r.get(c) != r.get(c)) else r.get(c)) for c, *_ in COLUMNS})
    return rows


def _choices(r):
    sel = {"Fabric code": r.get("Fabric code"), "Route": r.get("Route"), "Weave": r.get("Weave"), "Warp yarn": r.get("Warp yarn"),
           "Weft yarn": r.get("Weft yarn") or r.get("Warp yarn"), "EPI": _num(r.get("EPI")), "PPI": _num(r.get("PPI")),
           "Finished width (in)": _num(r.get("Finished width (in)")), "Finish": r.get("Finish") or "Normal"}
    shade = r.get("Shade") or "Medium"
    if sel["Route"] == "Yarn Dyed":
        sel.update({"Warp yarn dyeing": shade, "Weft yarn dyeing": shade})
    elif sel["Route"] == "Piece Dyed":
        sel["Piece shade"] = shade
    return {k: v for k, v in sel.items() if v not in (None, "")}


def analyse(rows, m=None):
    """Each row set beside the rate master, and the drafts that follow from all of them."""
    m = m or masters.load()
    group = dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"]))
    out, drafts = [], {}
    for n, r in enumerate(rows):
        sel = _choices(r)
        item = {"n": n, "mill": r.get("Mill"), "code": r.get("Fabric code"), "row": r, "problems": [], "figures": []}
        try:
            inp, used = masters.resolve(sel, m)
        except Exception as e:
            item["problems"].append(str(e))
            out.append(item)
            continue
        res = engine.compute(dict(inp))
        basis = {u["Item"]: (str(u["Choice"]), str(u["Basis"])) for u in used}
        cd = m["Class_Defaults"]
        key_cd = (group.get(sel["Weave"]), sel["Route"])
        hit = cd[(cd["Weave group"] == key_cd[0]) & (cd["Route"] == key_cd[1])]
        cd_row = hit.iloc[0] if len(hit) else cd[cd["Weave group"] == "Default"].iloc[0]
        adds = {"overhead": inp["overhead"] - float(cd_row["Overhead"]), "margin": inp["margin"] - float(cd_row["Margin"])}
        mine = dict(inp)
        for col, key, unit in FIGURES:
            v = _num(r.get(col))
            if v is None:
                continue
            v = v / 100 if key in PCT else v
            if key == "yarn_dye":
                now, keys = inp["warp_dye"], [("warp_dye", v), ("weft_dye", v)]
            else:
                now, keys = inp[key], [(key, v)]
            if (key == "piece_dye_rate" and sel["Route"] == "Yarn Dyed") or (key == "yarn_dye" and sel["Route"] != "Yarn Dyed"):
                continue                                 # a figure the route does not use
            for k, val in keys:
                mine[k] = val + (adds.get(k, 0.0))      # the mill's overhead and margin are totals: slab and tier adds are in them
            target = _target(key, sel, inp, m, group, used, basis, key_cd, cd_row)
            fig = {"column": col, "unit": unit, "mill": v, "now": now if key not in adds else now - adds[key],
                   "basis": target["basis"] if target else "", "target": target["label"] if target else None}
            item["figures"].append(fig)
            if target and abs(fig["mill"] - fig["now"]) > (0.0005 if key in PCT else 0.005):
                d = drafts.setdefault(target["id"], dict(target, values=[], rows=[]))
                d["values"].append(v)
                d["rows"].append(f"{r.get('Mill') or ''} {r.get('Fabric code') or ''}".strip())
        for k in adds:                                   # keep the adds when the sheet gives no figure
            mine.setdefault(k, inp[k])
        own = engine.compute(mine)
        price = _num(r.get("Mill's price Rs/m"))
        item.update(should=res["total_per_m"], own=own["total_per_m"], price=price,
                    own_gap=None if price is None else price - own["total_per_m"], placeholders=[u["Item"] for u in used if str(u["Basis"]).startswith("Placeholder")])
        out.append(item)
    for d in drafts.values():
        d["proposed"] = round(statistics.median(d["values"]), 4)
        d["sheets"] = len(d["values"])
    return {"rows": out, "drafts": sorted(drafts.values(), key=lambda d: (d["table"], d["label"]))}


def _target(key, sel, inp, m, group, used, basis, key_cd, cd_row):
    """Where in the rate master a figure lives: table, row key, column, current value and basis."""
    g, route = key_cd
    if key in ("warp_rate", "weft_rate"):
        yk = sel["Warp yarn"] if key == "warp_rate" else sel["Weft yarn"]
        yr = m["Yarn_Rates"].set_index("Yarn key")
        return {"id": f"Yarn_Rates|{yk}", "table": "Yarn_Rates", "match": {"Yarn key": yk}, "col": "Rate Rs/kg",
                "label": f"Yarn {yk}", "now": float(yr.loc[yk, "Rate Rs/kg"]), "basis": str(yr.loc[yk, "Basis"]), "pct": False}
    if key == "weaving_rate":
        wr = m["Weaving_Rates"]
        hit = wr[(wr["Weave group"] == g) & (wr["Route"] == route)]
        if hit.empty:
            return None
        return {"id": f"Weaving_Rates|{g}|{route}", "table": "Weaving_Rates", "match": {"Weave group": g, "Route": route}, "col": "Rs per pick",
                "label": f"Weaving, {g}, {route}", "now": float(hit.iloc[0]["Rs per pick"]), "basis": str(hit.iloc[0]["Basis"]), "pct": False}
    if key == "sizing_rate":
        sr = m["Sizing_Rates"]
        rtype = "Yarn Dyed" if route == "Yarn Dyed" else "Other"
        hit = sr[(sr["Route type"] == rtype) & (sr["Warp count up to (Ne)"] >= inp["warp_ne"])].sort_values("Warp count up to (Ne)")
        if hit.empty:
            return None
        upto = hit.iloc[0]["Warp count up to (Ne)"]
        return {"id": f"Sizing_Rates|{rtype}|{upto}", "table": "Sizing_Rates", "match": {"Route type": rtype, "Warp count up to (Ne)": upto},
                "col": "Rs per kg warp", "label": f"Sizing, {rtype}, warp up to Ne {upto:g}", "now": float(hit.iloc[0]["Rs per kg warp"]),
                "basis": str(hit.iloc[0]["Basis"]), "pct": False}
    if key == "yarn_dye":
        shade = sel.get("Warp yarn dyeing", "Medium")
        yd = m["Yarn_Dyeing"].set_index("Shade")
        return {"id": f"Yarn_Dyeing|{shade}", "table": "Yarn_Dyeing", "match": {"Shade": shade}, "col": "Rs per kg yarn",
                "label": f"Yarn dyeing, {shade}", "now": float(yd.loc[shade, "Rs per kg yarn"]), "basis": str(yd.loc[shade, "Basis"]), "pct": False}
    if key == "piece_dye_rate":
        pdt = m["Piece_Dyeing"]
        shade = sel.get("Piece shade", "Any") if route == "Piece Dyed" else "Any"
        hit = pdt[(pdt["Route"] == route) & (pdt["Shade"] == shade)]
        if hit.empty:
            return None
        return {"id": f"Piece_Dyeing|{route}|{shade}", "table": "Piece_Dyeing", "match": {"Route": route, "Shade": shade}, "col": "Rs per kg greige",
                "label": f"Piece dyeing, {route}, {shade}", "now": float(hit.iloc[0]["Rs per kg greige"]), "basis": str(hit.iloc[0]["Basis"]), "pct": False}
    if key == "finishing_rate":
        fr = m["Finishing_Rates"]
        fin = sel.get("Finish", "Normal")
        col = fr.columns[1] if route == "Yarn Dyed" else fr.columns[2]
        hit = fr[fr["Finish"] == fin]
        if hit.empty:
            return None
        return {"id": f"Finishing_Rates|{fin}|{col}", "table": "Finishing_Rates", "match": {"Finish": fin}, "col": col,
                "label": f"Finishing, {fin} ({'yarn dyed' if route == 'Yarn Dyed' else 'other routes'})", "now": float(hit.iloc[0][col]),
                "basis": str(hit.iloc[0]["Basis"]), "pct": False}
    if key in PCT:
        col = {"process_wastage": "Process wastage", "overhead": "Overhead", "margin": "Margin"}[key]
        exists = cd_row["Weave group"] == g and cd_row["Route"] == route
        return {"id": f"Class_Defaults|{g}|{route}|{col}", "table": "Class_Defaults", "match": {"Weave group": g, "Route": route}, "col": col,
                "label": f"{col}, {g}, {route}" + ("" if exists else " (new row; today the Default row is used)"),
                "now": float(cd_row[col]), "basis": str(cd_row["Basis"]) + ("" if exists else ", Default row"), "pct": True, "new_row": not exists}
    return None


def apply(m, drafts, chosen, mills):
    """Write the chosen drafts into the rate master held in memory. Returns what changed."""
    basis = f"Mill cost sheet, {', '.join(sorted(mills))}, {dt.date.today():%d %b %Y}"
    log = []
    for d in drafts:
        if d["id"] not in chosen:
            continue
        t = m[d["table"]].copy()
        mask = pd.Series(True, index=t.index)
        for c, v in d["match"].items():
            mask &= t[c] == v
        if not mask.any():
            if d["table"] != "Class_Defaults":
                continue
            base = t[t["Weave group"] == "Default"].iloc[0].to_dict()
            base.update(d["match"])
            t = pd.concat([t, pd.DataFrame([base])], ignore_index=True)
            mask = pd.Series(False, index=t.index)
            mask.iloc[-1] = True
        t.loc[mask, d["col"]] = d["proposed"]
        if "Basis" in t.columns:
            t.loc[mask, "Basis"] = basis
        m[d["table"]] = t
        log.append(f"{d['label']}: {d['now']:g} -> {d['proposed']:g}")
    return log
