"""Right cost: every costing in one list, the purchase-order costings of the pilot and the fabric list, each with
its verdict on today's rates."""
import io
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
import pandas as pd
from rules import common, costing, dashboard, dated, fabric_list, mills
import data_dated
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


_briefs = {"done": (None, None), "want": None, "running": False}     # done: (key, verdicts), replaced whole
_briefs_lock = threading.Lock()
RETRY_BRIEFS = (2, 120)         # seconds before a failed working-out is tried again: the first wait, doubled up to the second


def _pilot_briefs(rows, key, start=True):
    """The negotiation brief's verdict for every purchase-order costing, on the yarn rates of its order month (stage 5,
    GP's decision of 27 Nov 2026: a dated rate where there is one, today's rate otherwise, said per yarn) and today's
    other rates. About 12 ms a fabric, so it runs in the background and is kept until what it rests on changes (key).
    None until worked out. start=False: only what is worked out already (rows being replaced are not worked out: on a
    slow machine that delayed the verdicts of the new rows by a whole working-out, the CI run of 4e1f6f0)."""
    done_key, data = _briefs["done"]
    if done_key == key:
        return data
    if start:
        with _briefs_lock:
            _briefs["want"] = (rows, key)
            if _briefs["running"]:
                return None             # the one running takes this up when it ends
            _briefs["running"] = True
        try:
            threading.Thread(target=_work_briefs, daemon=True, name="rightprice-purchase-order-verdicts").start()
        except Exception:
            with _briefs_lock:
                _briefs["running"] = False
            raise
    return None


def _work_briefs():
    """The verdicts worked out for the newest rows asked for, until they are; one that fails (the store busy or
    unreachable) is logged and tried again after a wait."""
    wait = RETRY_BRIEFS[0]
    while True:
        with _briefs_lock:
            rows, key = _briefs["want"]
            if _briefs["done"][0] == key:
                _briefs["running"] = False
                return
        try:
            _briefs["done"] = (key, _verdicts(rows))
            wait = RETRY_BRIEFS[0]
        except Exception:
            print(f"RightPrice: the verdicts of Right cost's purchase orders could not be worked out; tried again in {wait} s:\n"
                  + traceback.format_exc(limit=8), file=sys.stderr, flush=True)
            time.sleep(wait)
            wait = min(wait * 2, RETRY_BRIEFS[1])


_costed = {"hit": (None, None, {})}     # (the rate master, the dated rates, {(choices, order month): costing}) of the last one


def _verdicts(rows):
    """Every row's verdict. A row costed on the same choices in the same order month, on the same rates and dated rates,
    as at the last working-out keeps that costing (the costing is nearly all of the time: 1,696 of them took minutes on a
    slow machine, the stage 4 run of 28 Nov); its verdict is worked out again, as the usual ranges may have moved."""
    m, out = common.get_masters(), {}
    months, table = dated.order_months(), data_dated.table()
    last_m, last_table, last = _costed["hit"]
    last = last if last_m is m and last_table == table else {}
    now = {}
    for r in rows:
        om = months.get(str(r["code"]))
        try:
            on = (json.dumps(r["choices"], sort_keys=True, default=str), om["month"] if om else None)
            res = now.get(on) or last.get(on) or masters.cost(r["choices"], m, on=on[1], dated=table)
            now[on] = res
            b = costing.brief(res, m, r["metres"], (), r["choices"])
            # the figures the row shows follow this costing, worked out as the pilot works them (masters.cost_many,
            # pilot.py): on the yarn rates of the order month (stage 5) and today's other rates, so a row, its verdict
            # and the price popup always agree (stage 2)
            v = {"should": round(res["total_per_m"], 2), "per_kg": round(res["per_kg"], 1), "gsm": round(res["gsm"], 1),
                 "buckets": {x["name"]: round(x["amount"], 2) for x in res["buckets"]},
                 "placeholders": ", ".join(res["placeholders"]) or None,
                 "gap": None if res["gap"] is None else round(res["gap"], 2),
                 "gap_pct": None if res["gap_pct"] is None else round(res["gap_pct"] * 100, 1),
                 "dated": bool((res.get("rates_of") or {}).get("dated")), "rates": dated.po_rates(r["code"], months, res)}
            if b is not None:
                v.update(stance=b["stance"], implausible=b["implausible"], lo=b["band"]["lo"] * 100, hi=b["band"]["hi"] * 100,
                         weak=b["weak"])
            out[r["code"]] = v
        except Exception as e:      # a costing that no longer works on today's rates
            out[r["code"]] = {"stance": "error", "weak": [str(e)]}
    _costed["hit"] = (m, table, now)
    return out


# the words of the negotiation brief, so a row reads the same in Right cost, the list and the pack
STANCE_BAND = {"push": "Push", "fair": "Fair", "below": "Below", "ask": "Ask break-up", "error": "Not costed"}


def costs():
    """Right cost: every purchase-order fabric of the pilot (1,696), costed on the rates in use (the order month's dated yarn
    rate where there is one) and worked out again at every rate edit or applied cost-sheet draft (GP, 28 Nov 2026), plus the rows of the fabric list,
    each with what the list page shows and the choices to open it in Cost a fabric. Read-only."""
    m = common.get_masters()
    L = masters.lists(m)
    dashboard._warm_pilot()
    ins = common._cache.get(common.PILOT + "#insights")
    cats = {(c["route"], c["weave"]): c for c in (ins[1]["categories"] if ins and ins[1] else [])}
    from rules import fab_groups, purchases     # stage 2: Fab groups; the purchase-order rows worked out again, ZLOI left out
    gkey = fab_groups.version()
    pkey, pilot_rows = purchases.pilot_rows()
    dv = data_dated.version()           # stage 5: the purchase orders' verdicts follow the dated yarn rates too
    memo = (common._state_key(), dv, _briefs["done"][0], _briefs["running"], gkey, pkey, purchases.rows_failing())
    hit = _costs_memo["val"]
    # kept while nothing it rests on changes; one not ready yet too, while its rows are as up to date as they were (a page
    # asking every half second while the verdicts are worked out otherwise works it all out each time, and on a slow
    # machine leaves the background work little time: the CI run of 4e1f6f0)
    if _costs_memo["key"] == memo and (hit["ready"] or hit["updating"] == (not purchases.rows_up_to_date(pkey))):
        return hit
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
                # the choices the price popup costs too (stage 2): the purchase history's, from the code's PLM specification
                "choices": r["Costing choices"] if "Costing choices" in r else _pilot_choices(r, L["Pattern"], list(yarn_seed.CONTENTS)),
                "outliers": r["Outliers (ZLOI)"], "worked_out_again": r["Worked out again"]})
    version = store.get().version("rates")
    po_rows = [r for r in out if r["source"] == "Purchase orders"]
    # the verdicts rest on each row's choices and metres (and the rates): rows served while new ones are worked out
    # (purchases.pilot_rows) with the same choices need no second round
    basis = hashlib.sha256(json.dumps([(r["code"], r["choices"], r["metres"]) for r in po_rows], sort_keys=True, default=str).encode()).hexdigest()
    # rows being replaced (worked out again in the background) get no verdicts worked out of their own, unless their pass
    # keeps failing: those of the new rows follow at once
    start = purchases.rows_up_to_date(pkey) or purchases.rows_failing()
    verdicts = _pilot_briefs(po_rows, (version, dv, len(out), bool(cats), basis, ins[0] if ins else None), start) if out else {}
    for r in out:
        v = (verdicts or {}).get(r["code"])
        r["rates"] = None           # the rates the costing is on: the order month's (worked out with the verdict)
        r["why_unsure"] = None      # set with the verdict (none on a row with no price: there is nothing to judge)
        if v and "should" in v:
            r["rates"] = v["rates"]
            if r["should"] is not None and (v["dated"] or abs(v["should"] - r["should"]) >= 0.005):
                # the figures follow the costing the verdict rests on: a dated yarn rate of the order month (stage 5), or a
                # rate changed since the pilot (stage 2); the placeholder column too (a dated rate with no source is one)
                r.update(should=v["should"], per_kg=v["per_kg"], gsm=v["gsm"], buckets={b: v["buckets"].get(b) for b in dashboard.BUCKETS},
                         placeholders=v["placeholders"])
                if r["price"] is not None:
                    gap = v["gap"] if v["gap"] is not None else round(r["price"] - v["should"], 2)
                    r.update(gap=gap, gap_pct=v["gap_pct"] if v["gap_pct"] is not None else round((r["price"] / v["should"] - 1) * 100, 1),
                             excess=None if not r["metres"] else gap * r["metres"])
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
            "problems": i["problems"], "added": i["added"], "choices": inp, "why_unsure": None if b is None else b["weak"],
            "rates": dated.today_rates()})
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
    for r in out:           # stage 5: which rates each costing is on, in a few words, for the list and the spreadsheet
        r["rates_of"] = "Working it out" if r["band"] == "Working it out" else dated.rates_label(r.get("rates"))
    mills._learn_mill_names({r["supplier"] for r in out})
    for r in out:
        r["mill"] = mills.mill_key(r["supplier"])
        for o in r.get("outliers") or []:  # each ZLOI line's own mill (the Suppliers tab names those, not the row's supplier)
            o["mill_key"] = mills.mill_key(o["mill"])
    groups = fab_groups.by_code()
    for r in out:           # stage 2: the purchase-order fabric's Fab group, from the purchase history
        if r["source"] == "Purchase orders":
            g = groups.get(str(r["code"])) or {}
            r["fab_group"], r["fab_group_name"] = g.get("code"), g.get("name") or g.get("why")
    fresh = purchases.rows_up_to_date(pkey)     # the purchase-order rows are worked out again in the background after a change
    val = {"rows": out, "ready": verdicts is not None and fresh, "updating": not fresh, "counts": {"Purchase orders": sum(1 for r in out if r["source"] == "Purchase orders"),
                                    "Fabric list": sum(1 for r in out if r["source"] == "Fabric list")}}
    _costs_memo.update(key=memo, val=val)         # the key as it was before: anything that moved meanwhile is worked out again
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
            ("placeholders", "Placeholder rates used"), ("rates_of", "Rates of"), ("status", "Status"), ("remarks", "Remarks")]
    df = pd.DataFrame([{h: r.get(k) for k, h in cols} for r in pick], columns=[h for _, h in cols])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return common.Download(buf.getvalue(), "RightCost.xlsx")
