"""One fabric's costing as the screens show it: the should-cost from the engine, its warnings, and the negotiation
brief (the usual range for its type, the verdict, the opening figure and the aim)."""
import io
import math
import re
import pandas as pd
from rules import common, dashboard, rates
import masters
import rate_card
import yarn_seed


def placeholder_count(m):
    return sum(int(df["Basis"].astype(str).str.startswith("Placeholder").sum())
               for df in m.values() if "Basis" in df.columns)


def sanity(inp, res):
    """Things a typing slip usually causes. The cost is still shown; these say why it may be wrong."""
    w, out = inp["width_in"], []
    if not 30 <= w <= 130:
        out.append(f"Finished width {w:g} inch is outside 30 to 130. Widths are in inches, not centimetres.")
    for name, key in (("EPI", "epi"), ("PPI", "ppi")):
        if not 20 <= inp[key] <= 400:
            out.append(f"{name} {inp[key]:g} is outside 20 to 400.")
    if inp["reed_in"] < w:
        out.append(f"Reed space {inp['reed_in']:g} inch is narrower than the finished width {w:g} inch.")
    elif inp["reed_in"] > w * 1.35:
        out.append(f"Reed space {inp['reed_in']:g} inch is more than 35% wider than the finished width {w:g} inch.")
    for name, key in (("Warp", "warp_ne"), ("Weft", "weft_ne")):
        if not 4 <= inp[key] <= 200:
            out.append(f"{name} count works out at Ne {inp[key]:.4g}, outside 4 to 200. Check the count and the count system.")
    if not 40 <= res["gsm"] <= 600:
        out.append(f"The fabric works out at about {res['gsm']:.0f} g/m2, outside 40 to 600. Check the counts, EPI and PPI.")
    return out


def yarn_sensitivity(res):
    """Rupees per metre that the price moves for each Rs 10 per kg on the warp yarn, and on the weft yarn."""
    i = res["inputs"]
    mult = (1 + i["process_wastage"] + i["overhead"]) * (1 + i["margin"]) / (1 - i["shrinkage"]) * (1 + i.get("small_lot_pct", 0.0))
    # carry: the share of a yarn price move that reaches the fabric price. It is larger than yarn's own
    # share of the cost, because losses, overhead and margin are charged on the yarn too.
    return {"warp_per_10": res["warp_kg"] * mult * 10, "weft_per_10": res["weft_kg"] * mult * 10,
            "warp_rate": i["warp_rate"], "weft_rate": i["weft_rate"],
            "yarn_share": (res["warp_kg"] * i["warp_rate"] + res["weft_kg"] * i["weft_rate"]) * mult / res["total_per_m"] if res["total_per_m"] else 0.0}


# The quote is "in line" when it sits inside the range where three in four past purchases of the same fabric
# type landed against their should-cost (the middle half of panel 1, upper and lower quarter), never
# narrower than 5% either way and never wider than 10%. Without purchase history: 5% either way.
BAND_MIN, BAND_MAX = 5.0, 10.0


def usual_range(p25=None, p75=None):
    """The usual range either side, in per cent (lo, hi): the middle half of past prices (lower and upper quarter, in
    per cent against the figure the range is set round), never narrower than BAND_MIN either way nor wider than
    BAND_MAX. Without past prices: BAND_MIN either way. The brief sets it round should-cost by fabric type; a Fab
    group's page round the group's median price (GP's decision, 27 Nov 2026: the same rule)."""
    if p25 is None or p75 is None:
        return -BAND_MIN, BAND_MIN
    return max(-BAND_MAX, min(-BAND_MIN, p25)), min(BAND_MAX, max(BAND_MIN, p75))


# A placeholder rate stops the brief naming a target only when the costs resting on it are more than this
# share of the price; below it, a placeholder off by half moves the should-cost by under 5%.
PLACEHOLDER_SHARE_LIMIT = 0.10


# Rate items whose cost shows on more than one line of the cost table
PLACEHOLDER_LINES = {"Finishing": ("Finishing", "Finish upcharge")}


def _qty_range(label):
    """'500 to 599 m' -> (500, 599); 'Below 1,000 m' -> (0, 999.99); 'Above 6,000 m' -> (6000.01, inf)."""
    s = str(label).replace(",", "").lower()
    n = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not n:
        return None
    if s.startswith("below"):
        return (0.0, n[0] - 0.01)
    if s.startswith("above"):
        return (n[0] + 0.01, math.inf)
    if "and above" in s:
        return (n[0], math.inf)
    if " to " in s and len(n) == 2:
        return (n[0], n[1])
    return None


def quantity_check(res, sel, m, quantity, notes=()):
    """Is the order quantity inside the quantity band the cost was worked on? (None, None) when it is,
    else (the reason, the band that fits)."""
    if not quantity or sel is None:
        return None, None
    qband = str(sel.get("Rate card quantity") or rate_card.NO_QTY)
    if qband != rate_card.NO_QTY:
        field, band, options = "Rate card quantity", qband, m["Quantity_Terms"]["Quantity band"].tolist()[1:]
        yd = sel.get("Route") == "Yarn Dyed"
        small = set(m["Quantity_Terms"][m["Quantity_Terms"]["Small-lot upcharge %"] > 0]["Quantity band"])
        if not yd:
            options = [o for o in options if o not in small]
        # a mill sheet that charges nothing for a small lot is costed on 800 to 1,999 m on purpose
        if band == "800 to 1,999 m" and 500 <= quantity < 800 and any("no small-lot upcharge" in str(x) for x in notes):
            return None, None
    else:
        field = "Order size"
        band = next((str(u["Choice"]) for u in res["rates_used"] if u["Item"] == "Order size"), str(sel.get("Order size") or ""))
        options = m["Order_Slab"]["Order size"].tolist()
    r = _qty_range(band)
    if r is None or r[0] <= quantity <= r[1]:
        return None, None
    fits = next((o for o in options if (lambda q: q is not None and q[0] <= quantity <= q[1])(_qty_range(o))), None)
    where = "the quantity band (mill rate card)" if field == "Rate card quantity" else "the order size"
    why = (f"the order quantity, {quantity:,.0f} m, is outside {where} the cost is worked on ({band}, step 6), "
           "so the should-cost is for a different order size")
    return why, ({"field": field, "value": fits} if fits else None)


def _placeholder_share(res):
    """Share of the price that rests on placeholder rates, with losses, overhead and margin on them.
    None when a placeholder cannot be found in the cost lines (then it is treated as large)."""
    names = set(res["placeholders"])
    if not names:
        return 0.0
    i, total = res["inputs"], res["total_per_m"]
    mult = (1 + i["process_wastage"] + i["overhead"]) * (1 + i["margin"]) / (1 - i["shrinkage"]) * (1 + i.get("small_lot_pct", 0.0))
    found, amount = set(), 0.0
    for b in res["buckets"]:
        for l in b["lines"]:
            # a line can rest on more than one placeholder (a finish's upcharge rests on Finishing and on Finish upcharge):
            # it counts once, for all of them. (It used to go to whichever came first in Python's own order of a set,
            # which changes at each start, so a few verdicts changed at a restart. GP's decision, 27 Nov 2026.)
            owners = {n for n in names if l["name"] in PLACEHOLDER_LINES.get(n, (n,))}
            if owners:
                found |= owners
                amount += abs(l["amount"]) * (1.0 if b["name"] == "Upcharges and quantity terms" else mult)
    if found != names or not total:
        return None
    return amount / total


def brief(res, m, quantity=None, notes=(), sel=None):
    """What a buyer takes into the meeting for one fabric with a quote on it.

    The tool does not know the mill's break-up, so it cannot say where the quote differs. It can say
    what would have to be true for the quote to be right: the yarn rate, the weaving rate or the
    margin that, alone, would close the gap. Each is set beside the figure in the rate master.

    Every comparison is made on the figures as printed (rupees to the paisa), so what the brief says
    can be checked with the numbers on the page.
    """
    if res["quote"] is None or res["quote"] <= 0:
        return None
    i = res["inputs"]
    should, quote = round(res["total_per_m"], 2), round(res["quote"], 2)
    gap = round(quote - should, 2)
    lot = 1 + i.get("small_lot_pct", 0.0)
    before = (1 + i["process_wastage"] + i["overhead"]) / (1 - i["shrinkage"]) * lot        # mark-up before margin
    mult = before * (1 + i["margin"])
    yarn_cost = res["warp_kg"] * i["warp_rate"] + res["weft_kg"] * i["weft_rate"]
    f = 1 + gap / (yarn_cost * mult) if yarn_cost else None
    cost_before_margin = (res["total_per_m"] + i.get("volume_discount_per_m", 0.0)) / (1 + i["margin"])      # close enough: upcharges are small
    grp = dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"]))
    route = next((u["Choice"].split(", ")[1] for u in res["rates_used"] if u["Item"] == "Weaving" and ", " in str(u["Choice"])), None)
    basis = {u["Item"]: str(u["Basis"]) for u in res["rates_used"]}
    is_ph = lambda item: basis.get(item, "").startswith("Placeholder")
    weak, caveats, ph_share = [], [], None

    # placeholders: weighed by the share of the price that rests on them
    if res["placeholders"]:
        share = _placeholder_share(res)
        names = ", ".join(res["placeholders"])
        if share is None or share > PLACEHOLDER_SHARE_LIMIT:
            weak.append(f"placeholder rates are used for {names}" + ("" if share is None else f", and {share:.0%} of the price rests on them"))
        else:
            ph_share = share           # whether the advice stands is decided once the range is known, below

    # the fit of this fabric type, in the dashboard's own figures (panel 1)
    cat, typ = None, None
    ins = common._cache.get(common.PILOT + "#insights")
    if ins and ins[1]:
        weave = next((u["Choice"].split(" (")[0] for u in res["rates_used"] if u["Item"] == "Weaving"), None)
        cat = next((c for c in ins[1]["categories"] if c["route"] == route and c["weave"] == grp.get(weave)), None)
        g = str(grp.get(weave) or weave or "")
        typ = f"{(route or '').lower()} {g.lower()}".strip()
        if weave and g and g.lower() not in str(weave).lower():
            typ_named = f"{(route or '').lower()} {str(weave).lower()} (counted with {g.lower()})"
        else:
            typ_named = typ
        if cat is None:
            weak.append(f"there are too few purchases of {typ_named} fabrics to test the tool on")
        elif cat["trust"] == "weak":
            weak.append(f"on {typ} the tool is within 10% of the price paid for only {cat['within10']:.0%} of the "
                        f"{cat['fabrics']} fabrics bought, and they were paid {cat['gap']:+.1f}% against should-cost on "
                        "average (dashboard panel 1)")

    lo, hi = usual_range(None, None) if cat is None else usual_range(cat["p25"], cat["p75"])
    upper, lower = round(should * (1 + hi / 100), 2), round(should * (1 + lo / 100), 2)
    if cat is None:
        band_why = "5% either side of should-cost" + ("" if ins and ins[1] else " (there is no purchase history on this server to set it from)")
    else:
        fit = (f"half of the {cat['fabrics']} {typ} fabrics you bought were priced between {cat['p25']:+.1f}% and "
               f"{cat['p75']:+.1f}% against should-cost (dashboard panel 1, middle half)").replace("-", "\u2212").replace("should\u2212cost", "should-cost")
        adjusted = (lo, hi) != (cat["p25"], cat["p75"])
        band_why = fit + (f"; kept at least {BAND_MIN:.0f}% and at most {BAND_MAX:.0f}% either way, so here {lo:+.1f}% to {hi:+.1f}%".replace("-", "\u2212") if adjusted else "")

    ro = res.get("rates_of") or {}
    if ro.get("dated"):     # stage 5: the range is measured on today's rates; say so when this should-cost is not
        band_why += (f". The range is measured on today's rates (the purchase orders on the rates in use); this should-cost "
                     f"has its yarn on the dated rates of {ro['label']}")
    why_qty, qty_fix = quantity_check(res, sel, m, quantity, notes)
    qty_only = False
    if why_qty:
        same = False
        if qty_fix:
            try:
                alt = dict(sel, **{qty_fix["field"]: qty_fix["value"]})
                if qty_fix["field"] == "Order size":
                    alt["Rate card quantity"] = rate_card.NO_QTY
                # on the same month's rates as the costing itself (stage 5); none named: today's, as before
                same = abs(masters.cost(alt, m, on=(res.get("rates_of") or {}).get("month"))["total_per_m"] - res["total_per_m"]) < 0.005
            except Exception:
                same = False
        if not same:
            qty_only = not weak
            weak.insert(0, why_qty)
        else:
            qty_fix = None
    stance = "ask" if weak else ("push" if quote > upper else ("below" if quote < lower else "fair"))
    if ph_share is not None:
        swing = round(should * ph_share / 2, 2)            # a placeholder off by half moves the should-cost this much
        edge = min(abs(quote - upper), abs(quote - lower))
        if stance != "ask" and edge <= swing * (1 + hi / 100) + 0.005:
            caveats.append(f"A placeholder rate is used for {', '.join(res['placeholders'])}; {ph_share:.1%} of the price rests on it. "
                           f"If it were off by half the should-cost would move by up to Rs {swing:,.2f}, and this quote is only "
                           f"Rs {edge:,.2f} from the edge of the usual range, so the advice could change: ask for the mill's charge for it first.")
        else:
            caveats.append(f"A placeholder rate is used for {', '.join(res['placeholders'])}, but only {ph_share:.1%} of the price rests on it: "
                           f"even if it were off by half, the should-cost would move by up to Rs {swing:,.2f}, which would not change the advice.")
    if (gap / should < -0.30) if should else False:
        caveats.insert(0, f"The quote is {abs(gap / should):.0%} below should-cost. That is almost always a different cloth, a typing slip "
                          "or a price per something other than a metre; check it before treating it as a saving.")
    # where to open: as far below the top of the usual range as the quote is above it, never below the
    # should-cost. It moves with the quote, so a rupee more on the quote never jumps the advice.
    open_at = max(should, round(upper - (quote - upper), 2)) if stance == "push" else should
    implausible = gap / should < -0.30 if should else False
    for n in notes or ():
        if "small-lot upcharge" not in str(n):
            caveats.insert(0, "From the mill's sheet: " + str(n)[0].upper() + str(n)[1:] + ".")
    return {
        "quote": quote, "should": should, "gap": gap, "gap_pct": gap / should if should else 0.0,
        "stance": stance, "weak": weak, "caveats": caveats, "qty_fix": qty_fix, "qty_only": qty_only, "implausible": implausible,
        "open_at": open_at, "settle_up_to": upper, "lower": lower, "above_band": round(quote - upper, 2),
        "band": {"hi": hi / 100, "lo": lo / 100, "why": band_why},
        "fit": None if cat is None else {"type": typ, "fabrics": cat["fabrics"], "within10": cat["within10"], "gap": cat["gap"],
                                          "p25": cat["p25"], "p75": cat["p75"]},
        "quantity": quantity, "at_stake": None if quantity is None else round(gap * quantity, 0),
        "would_need": {
            "yarn": None if f is None else {"warp": i["warp_rate"] * f, "weft": i["weft_rate"] * f, "warp_now": i["warp_rate"],
                                             "weft_now": i["weft_rate"], "pct": (f - 1) * 100,
                                             "placeholder": is_ph("Warp yarn") or is_ph("Weft yarn")},
            "weaving": {"rate": i["weaving_rate"] + gap / mult / i["ppi"], "now": i["weaving_rate"], "placeholder": is_ph("Weaving"),
                        "per_m_before": gap / mult, "picks": i["ppi"]},
            "margin": {"rate": (quote + i.get("volume_discount_per_m", 0.0)) / cost_before_margin - 1, "now": i["margin"],
                       "placeholder": is_ph("Crimp, wastage, overhead, margin")},
        },
    }


def result_json(res, quantity=None, notes=(), sel=None):
    return {
        "brief": brief(res, common.get_masters(), quantity, notes, sel),
        "warnings": sanity(res["inputs"], res),
        "yarn": yarn_sensitivity(res),
        "total_per_m": res["total_per_m"], "per_kg": res["per_kg"], "gsm": res["gsm"],
        "finished_g_per_m": res["finished_g_per_m"], "quote": res["quote"], "gap": res["gap"],
        "gap_pct": res["gap_pct"], "placeholders": res["placeholders"],
        "buckets": [{"name": b["name"], "amount": b["amount"], "pct": b["pct"],
                     "lines": [{"name": l["name"], "basis": l["basis"], "amount": l["amount"]} for l in b["lines"]]}
                    for b in res["buckets"]],
        "rates_used": [{k: (v if isinstance(v, str) else common.clean(v)) for k, v in u.items()} for u in res["rates_used"]],
    }


def cost_or_400(sel, m, on=None):
    try:
        return masters.cost({k: v for k, v in sel.items() if v not in ("", None)}, m, on=on)
    except Exception as e:      # a choice not on a list, a missing number: tell the user which
        raise common.Refused(400, str(e))


# ------------------------------------------------------------------ API
def meta():
    m = common.get_masters()
    yr = m["Yarn_Rates"]
    return {
        "lists": masters.lists(m),
        "weave_group": dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"])),
        "yarns": [{"key": r["Yarn key"], "rate": common.clean(r["Rate Rs/kg"]), "ne": common.clean(r["Count Ne (resultant)"]),
                   "basis": str(r["Basis"]), "date": common.clean(r["Rate date"]), "blend": str(r["Blend"]),
                   "content": yarn_seed.content_of(r["Blend"])} for _, r in yr.iterrows()],
        "contents": list(yarn_seed.CONTENTS),
        "editable": sorted(rates.EDITABLE),
        "example": masters.EXAMPLE_ROW,
        "template_columns": [{"name": c, "list": l, "required": r} for c, l, r in masters.TEMPLATE_COLUMNS],
        "tables": rates.TABLES,
        "small_lot_bands": m["Quantity_Terms"][m["Quantity_Terms"]["Small-lot upcharge %"] > 0]["Quantity band"].tolist(),
        "placeholders": placeholder_count(m),
    }


def _quantity_or_400(v):
    q = common._num_or_none(v)
    if q is not None and q < 0:
        raise common.Refused(400, "Order quantity cannot be negative")
    return q or None


def cost(sel: dict):
    """One fabric costed. '_notes' (optional) are the remarks of the list row it was opened from, carried
    into the negotiation brief; they are not choices and do not change the cost.
    '_rates_on' (optional, stage 5): a purchase order's month, sent by a purchase-order page, to cost the yarn on the
    dated rates of that month. Without it, today's rates (Cost a fabric and quotes, GP's decision of 27 Nov 2026).
    Either way the answer says which rates it is on ('rates_of')."""
    dashboard._warm_pilot()
    sel = dict(sel)
    notes = sel.pop("_notes", None) or []
    on = sel.pop("_rates_on", None) or None
    if on is not None:
        try:
            masters.month_of(on)
        except ValueError as e:
            raise common.Refused(400, str(e))
    qty = _quantity_or_400(sel.get("Order quantity (m)"))
    m = common.get_masters()
    res = cost_or_400(sel, m, on=on)
    out = result_json(res, qty, notes=notes, sel=sel)
    out["rates_of"] = res.get("rates_of") or {"month": None, "label": "today", "dated": False, "notes": [],
                                               "text": "Today's rates: the rate master in use"}
    q = common._num_or_none(sel.get("Quoted price (Rs/m)"))
    if q is not None and q <= 0:
        out["warnings"].append(f"A quote of Rs {q:g} is not a price, so it is ignored: no negotiation brief is given.")
    return out


def cost_sheet(sel: dict):
    res = cost_or_400(sel, common.get_masters())
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summ = [("Fabric code", sel.get("Fabric code")), ("Description", sel.get("Description")),
                ("Supplier", sel.get("Supplier")), ("Should-cost Rs/m", round(res["total_per_m"], 2)),
                ("Should-cost Rs/kg", round(res["per_kg"], 1)), ("Approx. GSM", round(res["gsm"], 1)),
                ("Quoted Rs/m", res["quote"]), ("Gap Rs/m", None if res["gap"] is None else round(res["gap"], 2))]
        summ += [(b["name"] + " Rs/m", round(b["amount"], 2)) for b in res["buckets"]]
        pd.DataFrame(summ, columns=["Item", "Value"]).to_excel(xw, sheet_name="Cost view", index=False)
        lines = [{"Bucket": b["name"], "Line": l["name"], "How it is worked out": l["basis"],
                  "Rs/m": round(l["amount"], 2)} for b in res["buckets"] for l in b["lines"]]
        pd.DataFrame(lines).to_excel(xw, sheet_name="Second level", index=False)
        pd.DataFrame(res["rates_used"]).astype(str).to_excel(xw, sheet_name="Rates used", index=False)
        pd.DataFrame([{"Input": k, "Value": v} for k, v in sel.items()]).astype(str).to_excel(
            xw, sheet_name="Inputs", index=False)
    return common.Download(buf.getvalue(), "Should cost.xlsx")
