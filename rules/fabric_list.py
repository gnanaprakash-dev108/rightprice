"""The fabric list: every fabric costed here, added from Cost a fabric or an upload (the RightPrice template or a
mill's own price sheet), each row costed again on today's rates whenever the list is shown."""
import datetime as dt
import io
import json
import pandas as pd
from rules import alerts, common, costing, dashboard
import masters
import mill_sheet
import store


# One list holds every fabric costed here: added one at a time from Cost a fabric, or many at once
# from an upload (the RightPrice template, or a mill's own price sheet). It is kept in a small file
# beside the rate master, and each row is re-costed on today's rates whenever the list is shown.
LIST_COLS = common.LOG_COLS + ["Id", "Inputs", "Result", "Mill", "Problems", "Notes"]


def _then(res):
    return json.dumps({"total_per_m": res["total_per_m"],
                       "buckets": [{"name": b["name"], "amount": b["amount"]} for b in res["buckets"]],
                       "rates": [{"Item": u["Item"], "Choice": str(u["Choice"]),
                                  "Value": u["Value"] if isinstance(u["Value"], str) else common.clean(u["Value"]),
                                  "Unit": u["Unit"]} for u in res["rates_used"]]})


def _list_row(sel, m, mill=None, problems=(), notes=(), n=0):
    """One list row. A fabric that cannot be costed yet is kept, with the reason, and no cost."""
    now = dt.datetime.now()
    sel = {k: (v if isinstance(v, str) else common.clean(v)) for k, v in sel.items() if v not in ("", None)}
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


def list_add(sel: dict, who: str = ""):
    """Add the fabric on Cost a fabric to the list. With '_id' it takes the place of that row (its mill columns stay)."""
    sel = dict(sel)
    replace = str(sel.pop("_id", "") or "")
    m = common.get_masters()
    costing.cost_or_400(sel, m)                      # a fabric typed on screen must cost before it is listed
    log = common.read_log()
    mill, old_id = None, None
    if replace and "Id" in log.columns and (log["Id"].astype(str) == replace).any():
        old = log[log["Id"].astype(str) == replace].iloc[0]
        mill, old_id = common._loads(old.get("Mill"), None), replace
    row = _list_row(sel, m, mill=mill)
    if old_id is not None:
        store.get().replace_list_row(old_id, row, who=who)
    else:
        store.get().append_list([row], who=who)
    return {"saved": True, "id": row["Id"]}


def list_upload(filename, data, who=""):
    """Many fabrics at once: the RightPrice template, or a mill's price sheet as it comes."""
    m = common.get_masters()
    try:
        book = pd.read_excel(io.BytesIO(data), sheet_name=None)
    except Exception as e:
        raise common.Refused(400, "This file could not be read as an Excel workbook (.xlsx). Save the mill's sheet as Excel and upload that.")
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
        raise common.Refused(400, "No sheet in this file has the headings of the RightPrice template (Fabric code, Route, "
                                 "EPI, PPI) or of a mill price sheet (Fab Code, Base Price, EPI, PPI)")
    if not rows:
        raise common.Refused(400, "The sheet has the right headings but no fabric rows")
    log = common.read_log()
    have = set()
    for col, key in (("Mill", None), ("Inputs", None)):
        if col in log.columns:
            have |= {v for v in log[col].dropna().astype(str)}
    fresh = [r for r in rows if (r["Mill"] or r["Inputs"]) not in have]
    upload = f"{filename or 'sheet'} \u00b7 {dt.datetime.now():%d %b %H:%M:%S}"
    for r in fresh:
        r["Upload"] = upload            # which file a row came in with, for the pack's choice of rows
    if fresh:
        store.get().append_list(fresh, who=who)
    out = {"added": len(fresh), "already": len(rows) - len(fresh), "kind": kind, "not_costed": sum(1 for r in fresh if r["Problems"]), "alerts": []}
    if fresh:
        try:        # flagged at once: the rows of this upload that need a look before the price is accepted
            ids = {str(r["Id"]) for r in fresh}
            out["alerts"] = [a for a in alerts._alerts_all() if a["id"] in ids]
        except Exception:
            pass
    return out


_list_memo = {"key": None, "val": None}


def list_view(options: dict = None):
    """The list, newest first, each row re-costed on today's rates. options.yarn_pct = {yarn key or '*': % change}
    also costs every row with those yarn rates moved, to show what a yarn price move would do."""
    options = options or {}
    m = common.get_masters()
    dashboard._warm_pilot()
    moves = {k: float(v) for k, v in (options.get("yarn_pct") or {}).items() if v not in ("", None) and float(v) != 0}
    memo = None if moves else common._state_key()
    if memo is not None and _list_memo["key"] == memo:
        return _list_memo["val"]
    if any(abs(v) > 50 for v in moves.values()):
        raise common.Refused(400, "A yarn move is limited to 50% either way")
    sim = None
    if moves:
        sim = dict(m)
        yr = m["Yarn_Rates"].copy()
        yr["Rate Rs/kg"] = [float(r) * (1 + moves.get(k, moves.get("*", 0.0)) / 100) for k, r in zip(yr["Yarn key"], yr["Rate Rs/kg"])]
        sim["Yarn_Rates"] = yr
    out = []
    log = common.read_log().iloc[::-1]
    for _, r in log.iterrows():
        inputs, problems = common._loads(r.get("Inputs"), None), common._loads(r.get("Problems"), [])
        mill = common._loads(r.get("Mill"), None)
        item = {"id": None if pd.isna(r.get("Id")) else str(r.get("Id")).split(".")[0], "added": common.clean(r.get("Saved on")),
                "inputs": inputs, "then": common._loads(r.get("Result"), None), "notes": common._loads(r.get("Notes"), []),
                "from_mill": mill is not None, "mill": mill or (mill_sheet.from_choices(inputs) if inputs else {}),
                "sums": mill_sheet.check_sums(mill, m) if mill else None, "problems": problems,
                "sheet_terms": None if not mill else (mill_sheet.terms_for(mill, m) or {}).get("mill"),
                "should_cost": None, "gap": None, "gap_pct": None, "placeholders": [], "simulated": None, "sim_gap": None,
                "sim_gap_pct": None, "quantity": None, "at_stake": None, "brief": None,
                "supplier": common.clean(r.get("Supplier")), "description": common.clean(r.get("Description")), "upload": common.clean(r.get("Upload"))}
        if mill and item["sheet_terms"] is None:
            item["notes"] = list(item["notes"]) + ["no per-end and per-pick figures for this mill in the rate master (Mill sheet terms), so those upcharges were not checked"]
        if inputs is None:                   # a costing saved before choices were kept: shown, not re-costed
            item["should_cost"], item["mill"] = common.clean(r.get("Should-cost Rs/m")), {"Fab Code": common.clean(r.get("Fabric code")), "Ex mill price": common.clean(r.get("Quoted Rs/m"))}
            item["problems"] = ["saved before choices were kept; it cannot be re-costed or opened"]
        elif not problems:
            try:
                res = masters.cost(inputs, m)
                item.update(should_cost=res["total_per_m"], per_kg=res["per_kg"], gsm=res["gsm"], gap=res["gap"],
                            gap_pct=res["gap_pct"], placeholders=res["placeholders"], yarn=costing.yarn_sensitivity(res))
                qty = common._qty((mill or {}).get("Total order qnty")) or common._qty(inputs.get("Order quantity (m)"))
                qty = qty if qty and qty > 0 else None          # a negative or zero quantity puts nothing at stake
                item["quantity"] = qty
                item["brief"] = costing.brief(res, m, qty, item["notes"], inputs)
                item["at_stake"] = None if item["brief"] is None else item["brief"]["at_stake"]
                if sim is not None:
                    moved = masters.cost(inputs, sim)
                    item.update(simulated=moved["total_per_m"], sim_gap=moved["gap"], sim_gap_pct=moved["gap_pct"],
                                sim_brief=costing.brief(moved, sim, qty, item["notes"], inputs))
            except Exception as e:
                item["problems"] = [str(e)]
        out.append(item)
    val = {"columns": mill_sheet.COLUMNS, "groups": mill_sheet.GROUPS, "rows": out,
           "yarns_in_use": sorted({i["inputs"][k] for i in out if i["inputs"] for k in ("Warp yarn", "Weft yarn") if i["inputs"].get(k)})}
    if memo is not None:
        _list_memo.update(key=memo, val=val)
    return val


def list_remove(payload: dict, who: str = ""):
    ids = {str(i) for i in payload.get("ids", [])}
    log = common.read_log()
    if "Id" not in log.columns or not ids:
        raise common.Refused(400, "Choose the rows to remove")
    return {"removed": store.get().remove_list(ids, who=who)}


def list_download(options: dict = None):
    v = list_view(options or {})
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
    return common.Download(buf.getvalue(), "RightPrice_fabric_list.xlsx")


def delete_saved(saved_id: str, who: str = ""):
    if list_remove({"ids": [saved_id]}, who=who)["removed"] == 0:
        raise common.Refused(404, "That row is no longer in the list")
    return {"deleted": True}
