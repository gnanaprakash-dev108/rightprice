"""The negotiation pack: one printable page for a mill sheet, an upload, or the rows ticked, with the questions to ask."""
import json
from rules import common, fabric_list
import mill_sheet


def _volume_question(r, m):
    """The card gives a volume discount from 2,000 m (not for 40s quality). Ask when the sheet gives none."""
    qty, mill, inp = r["quantity"], r["mill"], r["inputs"]
    if not qty or qty < 2000 or not r["from_mill"] or (mill_sheet._num(mill.get("Discoun>2000 mts")) or 0) > 0:
        return None
    counts = m["Yarn_Rates"].set_index("Yarn key")["Count"].astype(str).str.strip().str.lower()
    if all(counts.get(str(inp.get(f"{s} yarn") or "").strip()) == "40s" for s in ("Warp", "Weft")):
        return None             # the card: no volume discount on 40s quality
    band = next((name for lo, hi, name in mill_sheet.QUANTITY_BANDS if lo <= qty < hi), None)
    qt = m["Quantity_Terms"].set_index("Quantity band")
    disc = float(qt.loc[band, "Volume discount Rs per metre"]) if band in qt.index else 0.0
    if not disc:
        return None
    return (f"{r['code']}: {qty:,.0f} m and no volume discount on the sheet. Your own rate card gives Rs {disc:g} a metre "
            f"at {band}; why not here?")


def _questions(r, b, m):
    """What to ask the mill about one row, most useful first. b is the brief the row's figures come from."""
    q, code, own_gap = [], r["code"], r["own_gap"] if r["sums"] else None
    stance = r["stance"]
    if stance == "push":
        w = b["would_need"]
        alts = []
        if w["yarn"] and not w["yarn"]["placeholder"]:
            alts.append(f"yarn at about Rs {w['yarn']['warp']:,.0f} a kilo (we work on Rs {w['yarn']['warp_now']:,.0f})")
        if not w["weaving"]["placeholder"]:
            alts.append(f"weaving at about Rs {w['weaving']['rate']:.3f} a pick (we work on Rs {w['weaving']['now']:.3f})")
        if not w["margin"]["placeholder"]:
            alts.append(f"a margin of about {w['margin']['rate']:.1%} (we work on {w['margin']['now']:.1%})")
        if r["above_band"] < 0.02 * r["should"]:
            q.append(f"{code} is only Rs {r['above_band']:,.2f} a metre above the top of the usual range: ask for Rs {r['upper']:,.2f}.")
        else:
            q.append(f"{code} is Rs {r['gap']:,.2f} a metre above should-cost (Rs {r['should']:,.2f}), Rs {r['above_band']:,.2f} of it above "
                     f"the usual range. Which explains the whole Rs {r['gap']:,.2f}" + (": " + "; or ".join(alts) + "?" if alts else "?"))
    elif stance == "ask":
        q.append(f"Send the break-up for {code} (yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish, "
                 f"margin) before a price is named. Why: {b['weak'][0]}.")
    elif stance == "check":
        q.append(f"Confirm the quote for {code}: Rs {r['quote']:,.2f} is {abs(r['gap_pct']):.0%} below should-cost. "
                 "Is it per metre, for this construction and finish?")
    elif stance == "below":
        q.append(f"{code} is below the usual range: confirm the yarn, the construction and the finish are as specified.")
    if own_gap is not None and own_gap >= 0.01:
        q.append(f"{code}: your own sums give Rs {r['own_price']:,.2f}, not Rs {r['quote']:,.2f}. Bring the price to Rs {r['own_price']:,.2f}.")
    elif own_gap is not None and own_gap <= -0.01:
        q.append(f"{code}: hold Rs {r['quote']:,.2f} as the ceiling (the sheet's own build-up comes to Rs {r['own_price']:,.2f}, "
                 "more than the quote). Ask only for the sheet to be corrected so it shows how the quoted price is made up.")
    elif r["sums"] and own_gap is not None:
        q.append(f"Correct the sheet for {code}: {'; '.join(r['sums'])}. The ex-mill price itself agrees with the sums.")
    vq = _volume_question(r, m)
    if vq:
        q.append(vq)
    for n in r["notes"]:
        if "second yarn" in n:
            q.append(f"{code}: name the second yarn in {n.split(chr(39))[1] if chr(39) in n else 'the warp or weft'} and its rate.")
        elif "not recognised" in n:
            q.append(f"{code}: {n[0].upper() + n[1:]}. Which finish is it, and what does it add?")
    return q


def _ordered(r):
    q = mill_sheet._num(r["mill"].get("Total order qnty")) if r["mill"] else None
    return q if q and q > 0 else (r["quantity"] or 0)


def pack(options: dict = None):
    """The negotiation pack for a whole mill sheet (or the rows asked for): every row with its stance, the
    money at stake, the mill's sums that are off and the questions to ask, plus the sheet's totals.
    options: ids (the rows; default every row), yarn_pct (a yarn move, as on the list).
    With a yarn move, every figure of a row, its questions included, comes from the brief on the moved costs."""
    options = options or {}
    m = common.get_masters()
    v = fabric_list.list_view({"yarn_pct": options.get("yarn_pct")} if options.get("yarn_pct") else {})
    ids = {str(i) for i in (options.get("ids") or [])}
    chosen = [r for r in v["rows"] if not ids or r["id"] in ids]
    if not chosen:
        raise common.Refused(400, "There are no rows to put in the pack")
    rows, not_costed, seen = [], [], {}
    for r in chosen:
        code = r["mill"].get("Fab Code") or (r["inputs"] or {}).get("Fabric code") or "(no code)"
        desc = r["description"] or " ".join(str(r["mill"].get(c)) for c in ("Weave", "Variety") if r["mill"].get(c))
        own_price, own_gap = mill_sheet.own_sums(r["mill"], m) if r["from_mill"] else (None, None)
        b = r.get("sim_brief") or r["brief"]
        if r["problems"] or b is None:
            k = ("sheet", json.dumps({k2: v for k2, v in r["mill"].items() if k2 != "Fab Code"}, sort_keys=True, default=str)) if r["from_mill"] else None
            if k and k in seen:
                continue                # the same uncosted order again: listed once
            if k:
                seen[k] = code
            not_costed.append({"code": code, "description": desc, "why": "; ".join(r["problems"]) or "no mill price on this row",
                               "sums": r["sums"] or [], "own_price": own_price, "own_gap": own_gap, "ordered": _ordered(r)})
            continue
        qty = r["quantity"]
        stance = "check" if b["implausible"] else b["stance"]
        row = {"id": r["id"], "code": code, "description": desc, "supplier": r["supplier"], "quantity": qty,
               "quote": b["quote"], "should": b["should"], "gap": b["gap"], "gap_pct": b["gap_pct"], "stance": stance,
               "upper": b["settle_up_to"], "open_at": b["open_at"], "above_band": b["above_band"],
               "at_stake": b["at_stake"], "weak": b["weak"], "caveats": b["caveats"],
               "sums": r["sums"] or [], "own_price": own_price, "own_gap": own_gap,
               "own_at_stake": None if own_gap is None or qty is None else round(own_gap * qty),
               "notes": r["notes"], "mill": r["mill"], "inputs": r["inputs"], "from_mill": r["from_mill"]}
        row["above_range_money"] = round(row["above_band"] * qty) if stance == "push" and qty else 0
        # the same order twice, counted once (the newest row is kept: the list runs newest first):
        # the same fabric code and quantity (a revised sheet sent again), or every column of the mill's
        # sheet the same apart from the fabric code
        keys = []
        if qty and code != "(no code)":
            keys.append(("code", code, qty))
        if r["from_mill"]:
            keys.append(("sheet", json.dumps({k: v for k, v in r["mill"].items() if k != "Fab Code"}, sort_keys=True, default=str)))
        row["duplicate_of"] = next((seen[k] for k in keys if k in seen), None)
        for k in keys:
            seen.setdefault(k, code)
        row["questions"] = [] if row["duplicate_of"] else _questions(row, b, m)
        row["has_sheet"] = bool(r["from_mill"])
        for k in ("mill", "inputs", "from_mill"):
            row.pop(k)
        rows.append(row)
    dups = [r for r in rows if r["duplicate_of"]]
    every = rows
    rows = [r for r in rows if not r["duplicate_of"]]          # totals, lead and questions count each order once
    staked = [r for r in rows if r["at_stake"] is not None]
    by = lambda st: [r for r in rows if r["stance"] == st]
    stake = lambda rs: sum(r["at_stake"] for r in rs if r["at_stake"] is not None)
    sums_rows = [r for r in rows + not_costed if r["sums"]]
    totals = {
        "rows": len(chosen), "of": len(v["rows"]), "costed": len(rows), "not_costed": len(not_costed),
        "metres": sum(r["quantity"] or 0 for r in rows),
        "ordered": sum(r["quantity"] or 0 for r in rows) + sum(r["ordered"] or 0 for r in not_costed),
        "counted_stake": stake(by("push")) + stake(by("fair")),
        "push_stake": stake(by("push")), "fair_stake": stake(by("fair")),
        "push_above_range": sum(r["above_range_money"] for r in by("push")),
        "flagged_stake": stake(by("ask")) + stake(by("check")),
        "savings": -stake(by("below")),
        "sums_off": len(sums_rows),
        "sums_money": sum(r.get("own_at_stake") or 0 for r in rows if r["sums"] and (r.get("own_at_stake") or 0) > 0),
        "count": {st: len(by(st)) for st in ("push", "ask", "check", "fair", "below")},
        "no_quantity": sum(1 for r in rows if r["quantity"] is None),
        "duplicates": len(dups), "duplicate_metres": sum(r["quantity"] or 0 for r in dups),
    }
    # lead with the money above the usual range: what the mill has to justify, not the gap to should-cost
    # a row only a few paise above its range is not one to lead with
    lead = sorted([r for r in by("push") if r["above_range_money"] > 0 and r["above_band"] >= 0.02 * r["should"]],
                  key=lambda r: -r["above_range_money"])[:3]
    suppliers = sorted({r["supplier"] for r in chosen if r["supplier"]})
    sheets = {}         # one upload each: rows of one upload share the second their ids were made in
    for r in v["rows"]:
        label = f"{r['supplier'] or 'No supplier'} \u00b7 {r['upload']}" if r.get("upload") else f"{r['supplier'] or 'No supplier'} \u00b7 added on screen or before uploads were named"
        sheets.setdefault((label, label), []).append(r["id"])
    return {"rows": every, "not_costed": not_costed, "totals": totals, "lead": [r["code"] for r in lead],
            "sheets": [{"label": k[0], "ids": i} for k, i in sheets.items()],
            "suppliers": suppliers, "added": sorted({str(r["added"])[:10] for r in chosen if r["added"]}),
            "moved": bool(v["rows"]) and any(r["simulated"] is not None for r in v["rows"]),
            "yarn_pct": options.get("yarn_pct") or None}
