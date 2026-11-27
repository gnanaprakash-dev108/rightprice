"""Right cost: every costing in one list, the purchase-order costings of the pilot and the fabric list, each with
its verdict on today's rates."""
import io
import json
import os
import re
import pandas as pd
from rules import common, costing, dashboard, fabric_list, mills
import masters
import mill_sheet
import store
import yarn_seed


_costs_memo = {"key": None, "val": None}


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
            m, out = common.get_masters(), {}
            for r in rows:
                try:
                    res = masters.cost(r["choices"], m)
                    b = costing.brief(res, m, r["metres"], (), r["choices"])
                    # stage 2: the should-cost on today's rates too, so a row and the price popup always agree
                    today = {"should": round(res["total_per_m"], 2), "per_kg": round(res["per_kg"], 1), "gsm": round(res["gsm"], 1),
                             "buckets": {x["name"]: round(x["amount"], 2) for x in res["buckets"]}}
                    out[r["code"]] = dict(today) if b is None else dict(today, stance=b["stance"], implausible=b["implausible"],
                                                                         lo=b["band"]["lo"] * 100, hi=b["band"]["hi"] * 100, weak=b["weak"])
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


def costs():
    """Right cost: every purchase-order fabric costed in the pilot (1,696), plus the rows of the fabric list,
    each with what the list page shows and the choices to open it in Cost a fabric. Read-only."""
    m = common.get_masters()
    L = masters.lists(m)
    dashboard._warm_pilot()
    ins = common._cache.get(common.PILOT + "#insights")
    cats = {(c["route"], c["weave"]): c for c in (ins[1]["categories"] if ins and ins[1] else [])}
    from rules import fab_groups, purchases     # stage 2: Fab groups; the purchase-order rows worked out again, ZLOI left out
    gkey = fab_groups.version()
    pkey, pilot_rows = purchases.pilot_rows()
    memo = (common._state_key(), _briefs["key"], _briefs["running"], gkey, pkey)
    if _costs_memo["key"] == memo and _costs_memo["val"]["ready"]:
        return _costs_memo["val"]
    out = []
    if os.path.exists(common.PILOT):
        for r in pilot_rows:
            gap = r["PO above should-cost %"]
            cat = cats.get((r["Route"], r["Weave group"]))
            hi = costing.BAND_MIN if cat is None else min(costing.BAND_MAX, max(costing.BAND_MIN, cat["p75"]))
            lo = -costing.BAND_MIN if cat is None else max(-costing.BAND_MAX, min(-costing.BAND_MIN, cat["p25"]))
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
                "range": [lo, hi], "buckets": {b: r.get(f"{b} Rs/m") for b in dashboard.BUCKETS},
                "choices": _pilot_choices(r, L["Pattern"], list(yarn_seed.CONTENTS)),
                "outliers": r["Outliers (ZLOI)"], "worked_out_again": r["Worked out again"]})
    version = store.get().version("rates")
    verdicts = _pilot_briefs([r for r in out if r["source"] == "Purchase orders"], (version, len(out), bool(cats), pkey, ins[0] if ins else None)) if out else {}
    for r in out:
        v = (verdicts or {}).get(r["code"])
        if v and "should" in v and r["should"] is not None and abs(v["should"] - r["should"]) >= 0.005:
            # a rate changed since the pilot: the row's should-cost follows today's rates, as its verdict does
            r.update(should=v["should"], per_kg=v["per_kg"], gsm=v["gsm"], buckets={b: v["buckets"].get(b) for b in dashboard.BUCKETS})
            if r["price"] is not None:
                r["gap"] = round(r["price"] - v["should"], 2)
                r["gap_pct"] = round((r["price"] / v["should"] - 1) * 100, 1)
                r["excess"] = None if not r["metres"] else r["gap"] * r["metres"]
        if r["price"] is None:
            r["band"] = "No price"          # stage 2: bought only on ZLOI lines, left out of every figure
        elif v and "stance" in v:
            r["band"] = "Check quote" if v.get("implausible") else STANCE_BAND[v["stance"]]
            r["why_unsure"] = v["weak"]
            if "lo" in v:
                r["range"] = [v["lo"], v["hi"]]
        elif verdicts is None:
            r["band"] = "Working it out"
    listed = fabric_list.list_view({})["rows"]
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
    mills._learn_mill_names({r["supplier"] for r in out})
    for r in out:
        r["mill"] = mills.mill_key(r["supplier"])
    groups = fab_groups.by_code()
    for r in out:           # stage 2: the purchase-order fabric's Fab group, from the purchase history
        if r["source"] == "Purchase orders":
            g = groups.get(str(r["code"])) or {}
            r["fab_group"], r["fab_group_name"] = g.get("code"), g.get("name") or g.get("why")
    val = {"rows": out, "ready": verdicts is not None, "counts": {"Purchase orders": sum(1 for r in out if r["source"] == "Purchase orders"),
                                    "Fabric list": sum(1 for r in out if r["source"] == "Fabric list")}}
    _costs_memo.update(key=(common._state_key(), _briefs["key"], _briefs["running"], gkey, pkey), val=val)
    return val


def costs_download(payload: dict = None):
    """The Right cost rows asked for (codes), or all of one source, as Excel."""
    payload = payload or {}
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
    cols = [("source", "Source"), ("code", "Fabric code"), ("description", "Description"), ("supplier", "Supplier"), ("fab_group", "Fab group"), ("route", "Route"),
            ("weave", "Weave"), ("finish", "Finish"), ("warp", "Warp yarn"), ("weft", "Weft yarn"), ("epi", "EPI"), ("ppi", "PPI"),
            ("width", "Finished width (in)"), ("should", "Should-cost Rs/m"), ("price", "Price paid (purchase orders) or quoted (fabric list) Rs/m"),
            ("gap", "Above should-cost Rs/m"), ("gap_pct", "Above should-cost %"), ("metres", "Metres"),
            ("excess", "Above should-cost Rs (gap x metres; minus = below)"), ("band", "Against the usual range"),
            ("placeholders", "Placeholder rates used"), ("status", "Status"), ("remarks", "Remarks")]
    df = pd.DataFrame([{h: r.get(k) for k, h in cols} for r in pick], columns=[h for _, h in cols])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return common.Download(buf.getvalue(), "RightCost.xlsx")
