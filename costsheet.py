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
import re
import statistics

import pandas as pd

import engine
import masters

# column, the engine input it replaces, unit, what it is
COLUMNS = [
    ("Mill", None, "", "Name of the mill (the same name on every sheet from that mill)"),
    ("Fabric code", None, "", "The mill's or your code"),
    ("Route", None, "", "Yarn Dyed, Piece Dyed, RFD / Bleached or Printed (sheet Lists)"),
    ("Weave", None, "", "One of the weaves on sheet Lists"),
    ("Warp yarn", None, "", "One of the yarns on sheet Lists"),
    ("Weft yarn", None, "", "One of the yarns on sheet Lists; blank = the warp yarn"),
    ("EPI", None, "", "Ends per inch"),
    ("PPI", None, "", "Picks per inch"),
    ("Finished width (in)", None, "", "Inches"),
    ("Finish", None, "", "One of the finishes on sheet Lists; blank = Normal"),
    ("Shade", None, "", "Light, Medium or Dark; blank = Medium"),
    ("Warp yarn Rs/kg", "warp_rate", "Rs/kg", "The mill's price of the warp yarn"),
    ("Weft yarn Rs/kg", "weft_rate", "Rs/kg", "The mill's price of the weft yarn"),
    ("Sizing Rs/kg warp", "sizing_rate", "Rs/kg", ""),
    ("Weaving Rs/pick", "weaving_rate", "Rs/pick", "Rupees (not paise) per pick per inch of cloth, per metre: 0.32, not 32"),
    ("Yarn dyeing Rs/kg", "yarn_dye", "Rs/kg", "Yarn dyed only"),
    ("Piece dyeing Rs/kg greige", "piece_dye_rate", "Rs/kg", "Piece dyed, printed or bleached only"),
    ("Finishing Rs/kg greige", "finishing_rate", "Rs/kg", "Per kg of greige, leaving out any per-metre finish upcharge (ETI, LA and the like)"),
    ("Process wastage %", "process_wastage", "%", "Losses in dyeing and finishing; 3 for 3% (a cell formatted as % also works)"),
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
          "Finishing Rs/kg greige": i["finishing_rate"], "Process wastage %": round(i["process_wastage"] * 100, 2),
          "Overhead %": round(i["overhead"] * 100, 2), "Margin %": round(i["margin"] * 100, 2), "Mill's price Rs/m": None}
    # the example's price is what its own figures give, on the choices the template carries
    ex["Mill's price Rs/m"] = round(masters.cost(_choices(ex), m)["total_per_m"], 2)
    L = masters.lists(m)
    names = {"Route": masters.ROUTES, "Weave": L["Weave"], "Yarn (warp or weft)": list(m["Yarn_Rates"]["Yarn key"]),
             "Finish": L["Finish"], "Shade": ["Light", "Medium", "Dark"]}
    width = max(len(v) for v in names.values())
    lists = pd.DataFrame({k: list(v) + [None] * (width - len(v)) for k, v in names.items()})
    return (pd.DataFrame([ex], columns=[c for c, *_ in COLUMNS]),
            pd.DataFrame([(c, u, d) for c, _, u, d in COLUMNS], columns=["Column", "Unit", "What it is"]), lists)


def _num(v):
    try:
        return None if v is None or v == "" or (isinstance(v, float) and v != v) else float(v)
    except (TypeError, ValueError):
        return None


def _figure(v):
    """A figure as typed on a sheet: 345, '345', 'Rs 345', '1,200', '7%'. (number, problem)."""
    if v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip()):
        return None, None
    if isinstance(v, (int, float)):
        return float(v), None
    t = re.sub(r"(?i)rs\.?|inr|/kg|/m|,|\s", "", str(v)).rstrip("%")
    try:
        return float(t), None
    except ValueError:
        return None, f"'{v}' is not a number"


# what a mill's figure can plausibly be (in the units of the template); outside, it is shown but not drafted
RANGE = {"warp_rate": (40, 4000), "weft_rate": (40, 4000), "sizing_rate": (0, 300), "weaving_rate": (0.02, 5),
         "yarn_dye": (0, 1000), "piece_dye_rate": (0, 1000), "finishing_rate": (0, 600),
         "process_wastage": (0, 0.4), "overhead": (0, 0.4), "margin": (0, 0.4)}
# who a rate master figure is used for, in words
SCOPE = {"Yarn_Rates": "every fabric with this yarn, and the yarn master", "Weaving_Rates": "every fabric of this weave group and route",
         "Sizing_Rates": "every fabric of this route type and warp count band", "Yarn_Dyeing": "every yarn-dyed fabric of this shade",
         "Piece_Dyeing": "every fabric of this route and shade", "Finishing_Rates": "every fabric with this finish on these routes",
         "Class_Defaults": "every fabric of this weave group and route"}


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


def _match(v, options):
    """The list's own spelling of v, ignoring case and spaces; None when it is not on the list."""
    if v is None or str(v).strip() == "":
        return None
    norm = lambda x: re.sub(r"\s+", " ", str(x)).strip().lower()
    return next((o for o in options if norm(o) == norm(v)), None)


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


def _check_names(r, m):
    """Every name on a row that is not on the tool's lists (all of them, not only the first)."""
    L, problems, fixed = masters.lists(m), [], dict(r)
    for col, options in (("Route", masters.ROUTES), ("Weave", L["Weave"]), ("Warp yarn", list(m["Yarn_Rates"]["Yarn key"])),
                         ("Weft yarn", list(m["Yarn_Rates"]["Yarn key"])), ("Finish", L["Finish"]), ("Shade", ["Light", "Medium", "Dark"])):
        v = r.get(col)
        if v is None or str(v).strip() == "":
            if col in ("Route", "Weave", "Warp yarn"):
                problems.append(f"{col} is blank")
            continue
        hit = _match(v, options)
        if hit:
            fixed[col] = hit
        else:
            problems.append(f"{col.lower()} '{v}' is not on the tool's list")
    for col in ("EPI", "PPI", "Finished width (in)"):
        if not (_num(r.get(col)) or 0) > 0:
            problems.append(f"{col} is blank or not a number")
    return fixed, problems


def analyse(rows, m=None):
    """Each row set beside the rate master, and the drafts that follow from all of them.

    A draft is the median of every row that gives a figure for that rate, those that agree with the
    rate master included, so a draft does not lean away from the master and does not reverse once
    applied. A rate counts each row once (a yarn used as warp and weft is one figure)."""
    m = m or masters.load()
    group = dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"]))
    out, drafts, spelling = [], {}, {}
    for n, r in enumerate(rows):
        r, problems = _check_names(r, m)
        raw = re.sub(r"\s+", " ", str(r.get("Mill") or "")).strip()
        mill = spelling.setdefault(raw.lower(), raw) if raw else "unnamed mill"   # "Delta Mills" and "DELTA MILLS" are one mill
        item = {"n": n, "mill": mill, "code": r.get("Fabric code"), "row": r, "problems": problems, "figures": [], "notes": []}
        if not r.get("Mill"):
            item["notes"].append("no mill is named on this row")
        if problems:
            out.append(item)
            continue
        sel = _choices(r)
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
        mine, seen = dict(inp), set()
        for col, key, unit in FIGURES:
            v, bad = _figure(r.get(col))
            if bad:
                item["notes"].append(f"{col}: {bad}, so it is left out")
            if v is None:
                continue
            if (key == "piece_dye_rate" and sel["Route"] == "Yarn Dyed") or (key == "yarn_dye" and sel["Route"] != "Yarn Dyed"):
                item["notes"].append(f"{col} is not used for {sel['Route'].lower()} fabrics, so it is left out")
                continue
            if key in PCT:
                if 0 < v < 1:                            # 0.08, or 8% typed in Excel: a fraction
                    item["notes"].append(f"{col} {v:g} read as {v * 100:g}%")
                else:
                    v = v / 100
            lo, hi = RANGE[key]
            if not lo <= v <= hi:
                hint = " (it looks like paise: enter rupees per pick, e.g. 0.32)" if key == "weaving_rate" and 5 < v <= 500 else ""
                item["notes"].append(f"{col} {v * 100 if key in PCT else v:g} is outside what a mill charges{hint}; it is shown but not used")
                item["figures"].append({"column": col, "unit": unit, "mill": v, "now": None, "basis": "", "target": None, "ignored": True})
                continue
            now = inp["warp_dye"] if key == "yarn_dye" else inp[key]
            for k in (("warp_dye", "weft_dye") if key == "yarn_dye" else (key,)):
                mine[k] = v + adds.get(k, 0.0)            # the mill's overhead and margin are totals: slab and tier adds are in them
            target = _target(key, sel, inp, m, group, used, basis, key_cd, cd_row)
            fig = {"column": col, "unit": unit, "mill": v, "now": now if key not in adds else now - adds[key],
                   "basis": target["basis"] if target else "", "target": target["label"] if target else None}
            item["figures"].append(fig)
            if target and (target["id"], n) not in seen:
                seen.add((target["id"], n))
                d = drafts.setdefault(target["id"], dict(target, values=[], rows=[], mills=[]))
                d["values"].append(v)
                d["rows"].append(f"{mill} {r.get('Fabric code') or ''}".strip())
                d["mills"].append(mill)
        if any(f.get("ignored") for f in item["figures"]) or any("left out" in x for x in item["notes"]):
            item["partial"] = True                         # some of the mill's figures were not used: the rate master's stand in
        own = engine.compute(mine)
        price, _ = _figure(r.get("Mill's price Rs/m"))
        item.update(should=res["total_per_m"], own=own["total_per_m"], price=price,
                    own_gap=None if price is None else price - own["total_per_m"], placeholders=[u["Item"] for u in used if str(u["Basis"]).startswith("Placeholder")])
        out.append(item)
    kept = []
    for d in drafts.values():
        # each mill's own middle first, then the middle of the mills: a mill that sends many sheets counts once
        per_mill = {}
        for v, ml in zip(d["values"], d["mills"]):
            per_mill.setdefault(ml, []).append(v)
        d["proposed"] = round(statistics.median([statistics.median(v) for v in per_mill.values()]), 4 if d["pct"] or d["table"] == "Weaving_Rates" else 2)
        d["sheets"], d["mill_count"] = len(d["values"]), len(per_mill)
        d["scope"] = SCOPE.get(d["table"], "")
        if d["table"] == "Finishing_Rates":
            up = m["Finishing_Rates"].set_index("Finish").get("Upcharge Rs per metre")
            extra = float(up.get(d["match"]["Finish"], 0) or 0) if up is not None else 0
            if extra:
                d["scope"] += f"; the finish's Rs {extra:g} a metre upcharge stays on top, so the mill's figure must leave it out"
        if abs(d["proposed"] - d["now"]) > (0.00005 if d["pct"] else 0.0005):   # a draft that changes nothing is not shown
            kept.append(d)
    return {"rows": out, "drafts": sorted(kept, key=lambda d: (d["table"], d["label"]))}


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


def apply(m, drafts, chosen, mills=None):
    """Write the chosen drafts into the rate master held in memory. Returns what changed.

    Where a row holds one rate (a yarn, a weaving or sizing rate, a dyeing shade) its Basis becomes the
    mill cost sheet. Where a row holds several (wastage, overhead and margin; a finish's two routes) the
    Basis keeps what it said and adds which column now comes from which mills, so the others are not
    relabelled and a placeholder row keeps its warning."""
    today = f"{dt.date.today():%d %b %Y}"
    log = []
    for d in drafts:
        if d["id"] not in chosen:
            continue
        who = ", ".join(sorted(set(d.get("mills") or ["unnamed mill"])))
        t = m[d["table"]].copy()
        mask = pd.Series(True, index=t.index)
        for c, v in d["match"].items():
            mask &= t[c] == v
        if not mask.any():
            if d["table"] != "Class_Defaults":
                continue
            base = t[t["Weave group"] == "Default"].iloc[0].to_dict()
            base.update(d["match"])
            base["Basis"] = "Placeholder: copied from the Default row"
            t = pd.concat([t, pd.DataFrame([base])], ignore_index=True)
            mask = pd.Series(False, index=t.index)
            mask.iloc[-1] = True
        t[d["col"]] = t[d["col"]].astype(float)          # a whole-rupee column takes 16.5 as well
        t.loc[mask, d["col"]] = float(d["proposed"])
        if "Basis" in t.columns:
            old = str(t.loc[mask, "Basis"].iloc[0])
            if d["table"] in ("Class_Defaults", "Finishing_Rates"):
                kept = re.sub(r"; " + re.escape(d["col"]) + r" from mill cost sheet \([^)]*\), [^;]*", "", old)
                t.loc[mask, "Basis"] = f"{kept}; {d['col']} from mill cost sheet ({who}), {today}"
            else:
                t.loc[mask, "Basis"] = f"Mill cost sheet ({who}), {today}"
        if d["table"] == "Yarn_Rates" and "Rate date" in t.columns:
            t.loc[mask, "Rate date"] = dt.date.today().isoformat()
        m[d["table"]] = t
        show = (lambda v: f"{v * 100:.1f}%") if d["pct"] else (lambda v: f"Rs {v:g}")
        log.append(f"{d['label']}: {show(d['now'])} to {show(d['proposed'])}")
    return log
