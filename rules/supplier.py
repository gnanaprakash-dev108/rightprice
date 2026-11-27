"""The supplier page: one mill, for the meeting with it."""
import datetime as dt
import re
from rules import common, costing, mills, pack, rightcost, tracker
import masters


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


def suppliers():
    """Every mill bought from or quoted by, one line each (a mill written two ways is one mill)."""
    d = rightcost.costs()
    by = {}
    for r in d["rows"]:
        k = mills.mill_key(r["supplier"])
        if not k:
            continue
        by.setdefault(k, []).append(r)
    won = {mills.mill_key(b["supplier"]): b for b in tracker.negotiations_summary()["suppliers"]}
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
    first = (f"{code}: hold our counter of Rs {common._inr(c)}. The mill's Rs {common._inr(b['quote'])} is still Rs {common._inr(b['above_band'])} a metre above the top of "
             f"the usual range (Rs {common._inr(b['settle_up_to'])}): what explains the difference? Do not go above Rs {common._inr(b['settle_up_to'])}.")
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


def supplier(mill: str):
    """One mill, for the meeting with it: what was bought and what is quoted, each fabric's verdict, the money above
    the usual range, its sheets' sums that are off, where each negotiation stands, and the questions to take along."""
    key = mills.mill_key(mill)
    d = rightcost.costs()
    rows = [dict(r) for r in d["rows"] if mills.mill_key(r["supplier"]) == key]         # copies: the page changes its rows
    if not key or not rows:
        raise common.Refused(404, "No fabric bought from or quoted by that mill")
    m = common.get_masters()
    po = [r for r in rows if r["source"] == "Purchase orders"]
    fl = [r for r in rows if r["source"] == "Fabric list"]
    negos = {k: tracker.nego_summary(v) for k, v in tracker._negos().items() if v.get("events")}

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
            b = costing.brief(res, m, r["metres"], (), r["choices"])
        except Exception:
            b = None
        if b is None:
            continue
        band = "Check quote" if b["implausible"] else rightcost.STANCE_BAND[b["stance"]]
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
            p = pack.pack({"ids": [r["id"] for r in fl]})
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
                    lead = f"{r['code']}: the mill is now at Rs {common._inr(b['quote'])}" + (
                        f", up from its first quote of Rs {common._inr(first)}" if first is not None and b["quote"] > first + 0.005 else
                        f", down from its first quote of Rs {common._inr(first)}" if first is not None and b["quote"] < first - 0.005 else "") + (
                        f" (its sheet said Rs {common._inr(row['sheet_price'])})" if row.get("sheet_price") else "") + (
                        f"; our counter is Rs {common._inr(ng['counter'])}" if ng["counter"] is not None else "") + ". "
                    q_row = {"code": r["code"], "stance": "check" if b["implausible"] else b["stance"], "quote": b["quote"], "should": b["should"],
                             "gap": b["gap"], "gap_pct": b["gap_pct"], "upper": b["settle_up_to"], "above_band": b["above_band"], "sums": [],
                             "own_gap": None, "own_price": None, "quantity": row["metres"], "mill": {}, "from_mill": False, "inputs": row["choices"], "notes": []}
                    qs_ = pack._questions(q_row, b, m) if b["stance"] != "fair" else [f"{r['code']} is now inside its usual range (up to Rs {common._inr(b['settle_up_to'])}): close it" + (
                        f" at the mill's Rs {common._inr(b['quote'])}, which is at or below our counter of Rs {common._inr(ng['counter'])}." if ng["counter"] is not None and b["quote"] <= ng["counter"] + 0.005
                        else f" at or near our counter of Rs {common._inr(ng['counter'])}." if ng["counter"] is not None else ".")]
                    quoted_q += [{"code": r["code"], "text": (lead if n == 0 else "") + q} for n, q in enumerate(x.replace(f"{r['code']}: hold our", "Hold our") for x in _hold_counter(qs_, ng, b, r["code"]))]
                    if r["own_price"] is not None and b["quote"] - r["own_price"] >= 0.01:      # its own build-up is below what it now asks
                        gap_ = round(b["quote"] - r["own_price"], 2)
                        sums.append({"code": r["code"], "sums": [f"its sheet priced it at Rs {common._inr(r['quote'])}; it now asks Rs {common._inr(b['quote'])}"], "quote": b["quote"],
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
        except common.Refused:
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
    quoted_q = [{"code": q["code"], "also": list(dict.fromkeys(q["also"])), "text": q["text"] + (f" (The same holds for {', '.join(dict.fromkeys(q['also']))}.)" if q["also"] else "")} for q in merged]

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
            b = costing.brief(res, m, r["metres"], (), r["choices"])
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
            for n, q in enumerate(pack._questions(row, b, m)):
                item = {"code": r["code"], "text": f"Bought at Rs {common._inr(b['quote'])} a metre ({common._inr(r['metres'], 0)} m). " + q,
                        "above_range": r["above_range"], "also": []}
                bought_q.append(item)
                if n == 0:
                    same[(r["price"], round(r["should"], 2))] = item
        except Exception:
            continue
    for q in bought_q:
        if q["also"]:
            q["text"] += f" The same cloth at the same price was bought as {', '.join(q['also'])}; Rs {common._inr(q['above_range'], 0)} above the range on all of them."
    # fabrics that look high but that the tool is unsure of: name the largest, and ask for their break-up
    high = sorted([r for r in rows if r["band"] == "Ask break-up, above range" and not r.get("duplicate_of") and r.get("tracked") != "Agreed"],
                  key=lambda r: -(r["excess"] or 0))
    unsure_q = []
    if high:
        named = "; ".join(f"{r['code']} ({'quoted' if r['source'] == 'Fabric list' else 'bought at'} Rs {common._inr(r['price'])} against our cost of Rs {common._inr(r['should'])})" for r in high[:3])
        unsure_q.append(f"These look high, but our costing of this kind of cloth is not yet firm, so we need your break-up before we say more: {named}"
                        + (f"; and {len(high) - 3} more" if len(high) > 3 else "") + ". Please send the cost break-up (yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish, margin).")

    # the tracker: where each negotiation with this mill stands
    dups = tracker._list_duplicates(blocking=True)
    track, won, lost, agreed, open_ = [], 0, 0, 0, 0
    for k, v in tracker._negos().items():
        if not v.get("events") or mills.mill_key(v.get("supplier")) != key:
            continue
        s_ = tracker.nego_summary(v)
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
            where = f"the mill is at Rs {common._inr(t['latest'])}" if t["latest"] is not None else "the mill has not quoted"
            general.append(f"{t['code']} is still open: {where}" + (f", our counter is Rs {common._inr(t['counter'])}" if t["counter"] is not None else "") + ". Close it or agree the next step.")
    slim = lambda r: {k: r.get(k) for k in ("source", "id", "code", "description", "route", "weave_group", "should", "price", "gap", "gap_pct", "metres", "excess",
                                              "band", "range", "duplicate_of", "problems", "why_unsure", "placeholders", "above_range", "tracked", "sheet_price", "first_quote")}
    return {"key": key, "name": _mill_names(rows)[0], "names": _mill_names(rows), "ready": d["ready"],
            "bought": dict(b_side, rows=[slim(r) for r in sorted(po, key=lambda r: (-r["above_range"], -(r["excess"] or 0)))]),
            "quoted": dict(q_side, rows=[slim(r) for r in sorted(fl, key=lambda r: (r.get("tracked") == "Agreed", -r["above_range"]))], not_costed=not_costed, sheets=sheets),
            "sums": sums, "hint": hint, "today": common._day(dt.date.today().isoformat()),
            "tracker": {"fabrics": len(track), "agreed": agreed, "open": open_, "won": round(won), "lost": round(lost), "items": track},
            "questions": {"quoted": quoted_q, "bought": bought_q, "general": general}}
