"""The negotiation tracker: each fabric's steps (the mill's quote, our counter, a revised quote, the agreed price),
where it stands, and what negotiation has won."""
import datetime as dt
from rules import common, mills, rightcost
import store


NEGO_KINDS = ["Mill's quote", "Our counter", "Mill's revised quote", "Agreed"]


def _negos():
    return store.get().read_negotiations()


def _nego_order(events):
    """By date; on one day the mill's (first) quote comes first and the agreed price last, whatever order they were typed in."""
    rank = {"Mill's quote": 0, "Agreed": 2}
    return sorted(events, key=lambda e: (e["date"], rank.get(e["kind"], 1), e.get("at", "")))


FAR = 2.0           # a price more than twice, or under half of, what it is compared with is flagged


def nego_summary(rec):
    """Where one fabric's negotiation stands: the mill's first and latest price, the agreed price, what was won.
    The first quote is the first step the mill quoted in (never our counter, never the agreed price). It is
    agreed only while the agreed step is the last one: a step dated after it opens the negotiation again.
    A fabric with a warning is not counted in what was won until the step is put right."""
    ev = _nego_order(rec.get("events", []))
    quotes = [e for e in ev if e["kind"] in ("Mill's quote", "Mill's revised quote")]
    last_agreed = next((e for e in reversed(ev) if e["kind"] == "Agreed"), None)
    agreed = last_agreed if ev and ev[-1]["kind"] == "Agreed" else None
    first = quotes[0]["price"] if quotes else None
    latest_q = quotes[-1]["price"] if quotes else None
    metres = rec.get("metres") or 0
    should = rec.get("should") or rec.get("row_price")          # a fabric not costed is checked against the price on its row
    counter = next((e["price"] for e in reversed(ev) if e["kind"] == "Our counter"), None)
    out = {"status": "Agreed" if agreed else ("Open" if ev else "Not tracked"), "first": first, "latest": latest_q,
           "agreed": agreed["price"] if agreed else None, "counter": counter,
           "reopened": last_agreed["price"] if last_agreed and not agreed else None,
           "steps": len(ev), "last_date": ev[-1]["date"] if ev else None}
    ref = out["agreed"] if agreed else latest_q
    out["won_per_m"] = None if first is None or ref is None else round(first - ref, 2)
    out["won"] = None if out["won_per_m"] is None or not metres else round(out["won_per_m"] * metres)
    out["above_should_per_m"] = None if ref is None or rec.get("should") is None else round(ref - rec["should"], 2)
    warn = []
    far = lambda a, b: bool(a and b) and (a > FAR * b or a < b / FAR)
    said = lambda e: f"Rs {common._inr(e['price'])} ({e['kind']}, {common._day(e['date'])})"
    if last_agreed and quotes and last_agreed["date"] < quotes[0]["date"]:
        warn.append(f"The agreed price is dated {common._day(last_agreed['date'])}, before the mill's first quote ({common._day(quotes[0]['date'])}). Check the dates.")
    first_off = bool(quotes) and far(first, should)
    if first_off:
        warn.append(f"The mill's first quote, {said(quotes[0])}, is far from {'the should-cost' if rec.get('should') else 'the price on the row'} of Rs {common._inr(should)}. "
                    "Check it is per metre and typed right: what was won is measured from it.")
    for e in ev:
        if quotes and e is quotes[0]:
            continue
        base, name = (should, "the should-cost" if rec.get("should") else "the price on the row") if first_off or first is None else (first, "the first quote")
        if far(e["price"], base):
            warn.append(f"{said(e)} is far from {name} of Rs {common._inr(base)}. Check it is per metre and typed right.")
    standing = None             # a counter above the mill's price at the time stays flagged, whatever came after
    for e in ev:
        if e["kind"] in ("Mill's quote", "Mill's revised quote"):
            standing = e["price"]
        elif e["kind"] == "Our counter" and standing is not None and e["price"] > standing:
            warn.append(f"Our counter of Rs {common._inr(e['price'])} ({common._day(e['date'])}) is above the mill's price then, Rs {common._inr(standing)}. "
                        "Check which is which, and remove and re-enter the wrong step.")
    out["warnings"] = warn
    out["no_quote"] = bool(agreed and first is None)
    out["counted"] = bool(agreed and out["won"] is not None and not warn)
    return out


def _nego_view(rec):
    return dict(rec, events=_nego_order(rec.get("events", [])), summary=nego_summary(rec))


def _list_duplicates(blocking=False):
    """Fabric-list rows that repeat an order already on the list, as Right cost and the pack decide it: {key: code it repeats}.
    blocking: only those whose negotiation must be left out of what was won, because the row they repeat has a
    negotiation of its own (the same order would be counted twice). A row agreed before a re-quote arrived keeps its gain."""
    rows = [r for r in rightcost.costs()["rows"] if r["source"] == "Fabric list"]
    out = {f"Fabric list|{r['id']}": r["duplicate_of"] for r in rows if r.get("duplicate_of")}
    if not blocking:
        return out
    tracked = {k for k, v in _negos().items() if v.get("events")}
    live = {}
    for r in rows:
        if not r.get("duplicate_of"):
            live.setdefault(r["code"], []).append(f"Fabric list|{r['id']}")
    return {k: code for k, code in out.items() if any(o in tracked for o in live.get(code, []))}


def negotiations():
    """Every fabric's negotiation: its steps (and the steps removed, for the log) and where it stands."""
    return {"kinds": NEGO_KINDS, "items": {k: _nego_view(v) for k, v in _negos().items()}}


def negotiation_event(payload: dict, who: str = ""):
    """Record one step: the mill's quote, our counter, a revised quote, or the agreed price."""
    key, kind = str(payload.get("key") or ""), payload.get("kind")
    price = common._num_or_none(payload.get("price"))
    if not key or kind not in NEGO_KINDS:
        raise common.Refused(400, "Choose the fabric and what happened")
    if price is None or price <= 0:
        raise common.Refused(400, "Type the price in rupees per metre")
    if round(price, 2) < 1 or price > 50000:
        raise common.Refused(400, "A price per metre is between Rs 1 and Rs 50,000: check what was typed")
    try:
        day_ = dt.date.fromisoformat(str(payload.get("date") or dt.date.today().isoformat()))
    except ValueError:
        raise common.Refused(400, "The date is not a date")
    if day_ > dt.date.today():
        raise common.Refused(400, "The date is in the future")
    if day_ < dt.date.today() - dt.timedelta(days=730):
        raise common.Refused(400, f"The date is {common._day(day_.isoformat())}, more than two years ago: check the year")
    if key.startswith("Fabric list|") and not _negos().get(key, {}).get("events"):
        dup = _list_duplicates().get(key)           # a row with steps already (agreed before a re-quote came in) keeps its negotiation
        if dup:
            raise common.Refused(400, f"This row repeats the order of {dup}: record the negotiation on {dup}, so it is counted once")
    seen = payload.get("seen")
    fields = {f: payload[f] for f in ("code", "supplier", "description", "source") if payload.get(f)}
    for f in ("metres", "should", "row_price"):
        v = common._num_or_none(payload.get(f))
        if v is not None:
            fields[f] = v
    event = {"id": f"{dt.datetime.now():%Y%m%d%H%M%S%f}", "at": dt.datetime.now().isoformat(timespec="seconds"),
             "date": day_.isoformat(), "kind": kind, "price": round(price, 2), "note": str(payload.get("note") or "")[:500],
             "by": who}         # the signed-in person (the web layer reads it from Azure's sign-in), or "AI assistant"
    try:
        rec = store.get().add_step(key, fields, event, seen=seen)
    except store.Conflict:
        raise common.Refused(409, "Someone else has recorded or removed a step on this fabric since this page read it. "
                                 "The page now shows the steps as they are: check them, then record again if it is still right.")
    return _nego_view(rec)


def negotiation_remove(payload: dict, who: str = ""):
    """Take a step out. It is kept, marked removed, so the fabric's log still shows it was there."""
    key, eid = str(payload.get("key") or ""), str(payload.get("id") or "")
    if not store.get().remove_step(key, eid, dt.datetime.now().isoformat(timespec="seconds"), who):
        raise common.Refused(404, "That step is no longer there: someone has already removed it")
    return {"removed": True}


def negotiations_summary():
    """What negotiation has won, overall and by mill: against the first quote. A mill written two ways is one mill.
    Counted: agreed, with a mill quote and metres, no step to check, and not a row that repeats another order."""
    dups = _list_duplicates(blocking=True)
    items = [_nego_view(v) for v in _negos().values() if v.get("events")]
    by, check, total, lost, lost_n = {}, [], 0, 0, 0
    count = {"no_quantity": 0, "no_quote": 0, "duplicates": 0}
    for it in items:
        s_ = it["summary"]
        name = it.get("supplier") or "No supplier"
        b = by.setdefault(mills.mill_key(name) or "no supplier", {"names": {}, "fabrics": 0, "agreed": 0, "open": 0, "won": 0, "lost": 0, "lost_fabrics": 0, "metres": 0.0, "not_counted": 0})
        b["names"][name] = b["names"].get(name, 0) + 1
        b["fabrics"] += 1
        b["agreed" if s_["status"] == "Agreed" else "open"] += 1
        if s_["warnings"]:
            check.append({"code": it.get("code") or it["key"], "why": s_["warnings"][0]})
        if s_["status"] != "Agreed":
            continue
        if it["key"] in dups:
            count["duplicates"] += 1
            b["not_counted"] += 1
        elif s_["counted"]:
            b["won"] += s_["won"]
            b["metres"] += it.get("metres") or 0
            total += s_["won"]
            if s_["won"] < 0:
                b["lost"] -= s_["won"]
                b["lost_fabrics"] += 1
                lost -= s_["won"]
                lost_n += 1
        else:
            b["not_counted"] += 1
            if s_["no_quote"]:
                count["no_quote"] += 1
            elif s_["won"] is None:
                count["no_quantity"] += 1
    for b in by.values():       # shown under the spelling used most, the longer one on a tie
        b["supplier"] = sorted(b.pop("names").items(), key=lambda kv: (-kv[1], -len(kv[0])))[0][0]
        b["key"] = mills.mill_key(b["supplier"])
    agreed = sum(1 for it in items if it["summary"]["status"] == "Agreed")
    return dict(count, fabrics=len(items), agreed=agreed, open=len(items) - agreed, won=round(total), lost=round(lost), lost_fabrics=lost_n,
                to_check=check, suppliers=sorted(by.values(), key=lambda b: (-b["won"], b["supplier"])))
