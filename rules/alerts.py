"""Quote alerts: the rows of the fabric list that need a look before their price is accepted."""
from rules import common, fabric_list, mills, pack, tracker
import store


ALERT_KINDS = {"above": "Above its usual range", "sums": "Mill's sums off", "repeat": "Repeats an order", "low": "Far below should-cost"}


def _seen():
    return store.get().read_seen()


ALERT_MIN_ABOVE = 0.005        # a quote less than half a per cent of should-cost above its range is not worth an alert


def _alerts_all():
    """Every flagged row of the fabric list; whether seen or agreed is marked, not filtered. Worked out afresh each
    time from the list as it stands, so a corrected sheet or a changed rate changes the alerts."""
    try:
        p = pack.pack({})
    except common.Refused:
        return []
    listed = {r["id"]: r for r in fabric_list.list_view({})["rows"]}
    negos = {k: tracker.nego_summary(v) for k, v in tracker._negos().items() if v.get("events")}
    newest = {r["code"]: r for r in reversed(p["rows"]) if not r["duplicate_of"]}       # the row an older one is measured against
    seen, found = _seen(), {}
    for r in p["rows"]:
        flags = []
        qty = r["quantity"]
        on = lambda per_m: f" (Rs {common._inr(abs(per_m) * qty, 0)} on {common._inr(qty, 0)} m)" if qty else " (no quantity on the row, so no rupee total)"
        dup = r["duplicate_of"]
        if dup and dup == r["code"]:
            # an older row of the same code and quantity: the newer row carries the live price
            new_ = newest.get(dup)
            flags.append({"kind": "repeat", "money": 0, "counted": False,
                          "text": f"An older row for {dup}, at Rs {common._inr(r['quote'])}: a newer row for the same code and quantity is on the list"
                                  + (f" at Rs {common._inr(new_['quote'])}" if new_ else "") + ". If the newer one replaces it, remove this row; the alerts are on the newer row."})
        else:
            if dup:
                flags.append({"kind": "repeat", "money": 0, "counted": False,
                              "text": f"Repeats the order of {dup} ({common._inr(qty, 0) + ' m at ' if qty else ''}Rs {common._inr(r['quote'])}; the same cloth and quantity, or every column of the sheet the same): check it is not ordered twice. "
                                      "If it is a second order, the flags below apply to it as well; its rupees are not added to the totals."})
            if r["stance"] == "push" and r["above_band"] >= ALERT_MIN_ABOVE * r["should"]:
                flags.append({"kind": "above", "money": 0 if dup else r["above_range_money"], "counted": not dup and bool(qty),
                              "text": f"Quoted Rs {common._inr(r['quote'])}, Rs {common._inr(r['above_band'])} a metre above the top of its usual range (Rs {common._inr(r['upper'])}; should-cost Rs {common._inr(r['should'])})" + on(r["above_band"]) + "."})
            if r["stance"] == "check":
                flags.append({"kind": "low", "money": 0, "counted": False,
                              "text": f"Quoted Rs {common._inr(r['quote'])}, {abs(r['gap_pct']):.0%} below the should-cost of Rs {common._inr(r['should'])}: check it is per metre and for this cloth before treating it as a saving."})
            if r["sums"] and r["own_gap"] is not None and r["own_gap"] >= 0.01:
                flags.append({"kind": "sums", "money": 0 if dup else (r["own_at_stake"] or 0), "counted": not dup and bool(qty),
                              "text": f"The mill's own build-up comes to Rs {common._inr(r['own_price'])}, not the Rs {common._inr(r['quote'])} it asks: Rs {common._inr(r['own_gap'])} a metre too much" + on(r["own_gap"]) + "."})
            elif r["sums"] and r["own_gap"] is not None and r["own_gap"] <= -0.01:
                flags.append({"kind": "sums", "money": 0, "counted": False,
                              "text": f"The sheet's own build-up comes to Rs {common._inr(r['own_price'])}, Rs {common._inr(-r['own_gap'])} a metre more than the Rs {common._inr(r['quote'])} it asks. "
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
        was = (f"; that row is agreed at Rs {common._inr(ng['agreed'])} in the tracker" if ng and ng["status"] == "Agreed" else
               "; that row's alert was marked seen" if rid in seen else "")
        text = (f"An older row for this code and quantity is on the list at Rs {common._inr(r['quote'])}{was}. If this row replaces it, remove the older one; if it is a second order, say so to the mill."
                if dup == r["code"] else
                f"The same order is already on the list as {r['code']} ({common._inr(r['quantity'], 0) + ' m at ' if r['quantity'] else ''}Rs {common._inr(r['quote'])}){was}: check it is not ordered twice.")
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


def alerts():
    """The alerts still to look at, grouped by mill and the upload they came in with; and every flag, for the fabric pages."""
    every = _alerts_all()
    live = [a for a in every if not a["seen"] and not a["agreed"]]
    groups = {}
    for a in live:
        groups.setdefault((mills.mill_key(a["supplier"]), a["upload"]), []).append(a)
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


def alerts_seen(payload: dict, who: str = ""):
    """Mark alerts seen (ids), bring some back (ids with undo: true) or all back (restore: true). Shared: seen by one is seen by all."""
    ids = {str(i) for i in payload.get("ids") or []}
    store.get().change_seen(ids, undo=bool(payload.get("undo")), restore=bool(payload.get("restore")), who=who)
    return alerts()
