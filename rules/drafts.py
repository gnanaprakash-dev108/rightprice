"""E-mail and WhatsApp drafts to a mill: the figures and points the draft may use (draft.py writes it)."""
from rules import alerts, common, mills, rightcost, supplier
import draft


# ------------------------------------------------------------------ e-mail drafts to a mill
def _draft_facts(payload):
    """The figures a draft may use: only the fabrics asked about, from one mill, with the points the supplier page
    would raise on them (so they follow the tracker). scope: {type: fabric, key} | {type: rows, keys} | {type: supplier, mill}.
    The price named to the mill is never our ceiling: it is our counter if one is recorded, else the lower of the
    brief's opening price and the mill's own build-up."""
    scope = payload.get("scope") or {}
    all_rows = rightcost.costs()["rows"]
    key_of = lambda r: f"{r['source']}|{r.get('id') or r['code']}"
    if scope.get("type") == "supplier":
        mill, want = mills.mill_key(scope.get("mill")), None
    else:
        keys = {str(k) for k in ([scope.get("key")] if scope.get("type") == "fabric" else scope.get("keys") or []) if k}
        picked = [r for r in all_rows if key_of(r) in keys]
        if not picked:
            raise common.Refused(400, "Choose the fabric or fabrics the message is about")
        if any(not r["mill"] for r in picked):
            raise common.Refused(400, "A ticked fabric has no supplier on it (" + ", ".join(r["code"] for r in picked if not r["mill"]) + "), so there is no mill to write to. Untick it, or add its supplier.")
        ticked = {r["mill"] for r in picked}
        if len(ticked) > 1:
            raise common.Refused(400, "The ticked fabrics are from more than one mill (" + "; ".join(f"{supplier._mill_names([r for r in picked if r['mill'] == k])[0]}: {', '.join(r['code'] for r in picked if r['mill'] == k)}" for k in sorted(ticked))
                            + "). A message goes to one mill: tick fabrics of one mill.")
        mill, want = ticked.pop(), {key_of(r) for r in picked}
    sp = supplier.supplier(mill)
    m = common.get_masters()
    full = {key_of(r): r for r in all_rows if r["mill"] == sp["key"]}
    own = {x["code"]: x for x in sp["sums"] if x.get("own_gap") is not None and x["own_gap"] >= 0.01}
    items, skipped, adjusted = [], [], []
    for side, src in (("quoted", "Fabric list"), ("bought", "Purchase orders")):
        for r in sp[side]["rows"]:
            k = f"{src}|{r.get('id') or r['code']}"
            if want is not None and k not in want:
                continue
            pts = [q["text"] for q in sp["questions"][side] if q["code"] == r["code"] or r["code"] in (q.get("also") or [])]
            band = r["band"]
            if not pts and band == "Ask break-up, above range" and r.get("tracked") != "Agreed" and not r.get("duplicate_of"):
                pts = ["The price looks high against our costing, but our costing of this kind of cloth is not firm: get the break-up (yarn count and rate, "
                       "wastage, weaving per pick, dyeing per kilo, finish, margin) before saying anything about price."]
            if r.get("duplicate_of") or r.get("tracked") == "Agreed" or not pts:
                if want is not None:
                    skipped.append({"code": r["code"], "why": f"it repeats the order of {r['duplicate_of']}" if r.get("duplicate_of") else "its price is already agreed"
                                    if r.get("tracked") == "Agreed" else "it is inside or below its usual range" if band in ("Fair", "Below") else "it is not costed" if band in ("Not costed", "No price")
                                    else "there is no point to raise on it"})
                continue
            upper = round(round(r["should"], 2) * (1 + r["range"][1] / 100), 2) if r.get("should") is not None and r.get("range") else None
            skip = None
            if band == "Fair" and r["code"] not in {x["code"] for x in sp["sums"]}:
                skip = "it is inside its usual range: close it on its Negotiation tab"
            elif band == "Push" and upper is not None and r["price"] - upper < alerts.ALERT_MIN_ABOVE * r["should"]:
                skip = "it is only paise above its usual range: not worth a message"
            if skip:
                if want is not None:
                    skipped.append({"code": r["code"], "why": skip})
                continue
            purpose = ("confirm_price" if band == "Check quote" else "breakup_only" if str(band).startswith("Ask break-up") else "correct_sheet" if band == "Fair"
                       else "confirm_spec" if band == "Below" else "next_order" if src == "Purchase orders" else "revise")
            counter = next((t["counter"] for t in sp["tracker"]["items"] if t["key"] == k and t["status"] != "Agreed"), None)
            built = own[r["code"]]["own_price"] if r["code"] in own and purpose == "revise" else None
            # the only prices of ours a message names: a counter already made, or the mill's own build-up when that is lower.
            # Never the top of our range, and never an opening figure dressed as "what our costing supports".
            name, counter_named = None, False
            if purpose == "revise":
                cands = [c for c in (counter, built) if c is not None and c < r["price"] - 0.005]
                name = round(min(cands), 2) if cands else None
                counter_named = name is not None and counter is not None and abs(name - counter) < 0.005
            said = {"breakup_only": "only the break-up is asked: the tool is unsure of this fabric, so no price is put to the mill",
                    "confirm_price": "the mill is asked to confirm the price, not to revise it: it is far below our costing",
                    "correct_sheet": "only a corrected sheet is asked: the price is inside its usual range",
                    "confirm_spec": "the mill is asked to confirm the specification, not the price: the price is below its usual range",
                    "next_order": "already bought: raised for the next order"}.get(purpose)
            if said:
                adjusted.append(f"{r['code']}: {said}")
            items.append({"code": r["code"], "description": r.get("description") or "", "quantity": common._inr(r["metres"], 0) if r.get("metres") else None,
                          "price": None if r.get("price") is None else round(r["price"], 2), "purpose": purpose, "already_bought": src == "Purchase orders",
                          "price_to_name": name, "our_counter": counter if counter_named else None, "mills_own_build_up": built, "points": pts})
    if want is None:        # a whole mill: the quotes in hand first, then at most three past purchases
        items = [i for i in items if i["purpose"] != "next_order"] + [i for i in items if i["purpose"] == "next_order"][:3]
    if not items:
        why = "; ".join(f"{x['code']}: {x['why']}" for x in skipped[:8])
        raise common.Refused(400, "There is nothing to ask this mill about " + (("this fabric" if len(want) == 1 else "these fabrics") if want else "right now") + (f" ({why})." if why else
                            ": every fabric is inside its usual range, already agreed, or has no point to raise."))
    ask = payload.get("ask") if payload.get("ask") in draft.ASKS else "both"
    clip = lambda v, d: (str(v or "").strip()[:60] or d)
    return {"writer": clip(payload.get("writer"), "[Your name]"), "contact": clip(payload.get("contact"), "[Name]"), "mill": sp["name"],
            "ask": ask, "wants": draft.ASKS[ask], "items": items[:12], "left_out": [i["code"] for i in items[12:]], "skipped": skipped,
            "adjusted": [a_ for a_ in adjusted if a_.split(":")[0] in {i["code"] for i in items[:12]}]}


def draft_message(payload: dict):
    """A fresh e-mail and WhatsApp draft to one mill, on the fabrics asked about. Editable, copied by the buyer, never sent."""
    facts = _draft_facts(payload)
    out = draft.write({k: v for k, v in facts.items() if k not in ("skipped", "left_out", "adjusted")})
    return dict(out, mill=facts["mill"], mill_key=mills.mill_key(facts["mill"]), fabrics=[i["code"] for i in facts["items"]], left_out=facts["left_out"], skipped=facts["skipped"],
                adjusted=facts["adjusted"], notes=list(dict.fromkeys(pt for i in facts["items"] for pt in i["points"])), key_set=draft.available())
