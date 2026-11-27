"""Fab groups: the same construction in any colour, across mills (the mill is a breakdown inside a group).

A fabric code's group is decided by nine fields of its PLM specification, tidied and then matched exactly: content,
route, weave, warp count, weft count, EPI, PPI, finished width and finish. The finished width is put on the nearest whole
inch (GP, 27 Nov 2026: widths within half an inch are one group), so every code of a group is within half an inch of the
group's width, whatever order the files come in. A code whose specification is missing or incomplete is "not grouped":
nothing is guessed. Codes run Fab-0001 onward in order of first appearance; a code is never changed and never handed out
again, even after an admin merges its group into another (the merged group keeps its code and its page says where it
went). When a code's specification is corrected or completed, or the way the fields are tidied changes, the code moves
at the next upload and both group pages say so.

The group page: purchases, metres, mills, median price, usual range, should-cost, price over time by mill, and the
purchases priced well above the group. "Priced well above its group" is GP's decision of 27 Nov 2026: above the group's
usual range by the brief's own rule (costing.usual_range): the middle half of the group's past prices, kept between 5%
and 10% either side of the group's median. A range needs purchases on at least MIN_FOR_RANGE separate orders.
ZLOI order lines are left out of every figure and shown apart as outliers (GP, 27 Nov 2026)."""
import hashlib
import json
import re
import statistics
import warnings

from rules import common, costing
import data_purchases as dp
import grouping
import masters
import store

with warnings.catch_warnings():         # pilot.py turns warnings off for its own run; not for the app
    import pilot

# a usual range needs purchases on at least this many separate orders (order numbers, ZLOI left out); with fewer, the
# page says so (GP, 27 Nov 2026)
MIN_FOR_RANGE = 5
FIELDS = ("content", "route", "weave", "warp", "weft", "epi", "ppi", "width_in", "finish")
FIELD_WORDS = {"content": "content", "route": "dye method", "weave": "weave", "warp": "warp count", "weft": "weft count",
               "epi": "EPI", "ppi": "PPI", "width_in": "finished width", "finish": "finish"}
# fields that may differ between two groups an admin merges without a second warning
MERGE_FREELY = ("width_in", "finish")


# ------------------------------------------------------------------ the nine fields, tidied
def short_spec(spec):
    """A PLM row (data/plm_specs_for_po.csv) with the short field names pilot.py uses, every value text."""
    return {k.replace("article_", "").replace("cust_", ""): ("" if v is None else str(v)) for k, v in spec.items()}


def spec_sha(spec):
    return None if not spec else hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode("utf8")).hexdigest()


def tidy_content(text):
    """'98%Cotton2%Spandex' -> '98% Cotton 2% Elastane' (fibre spellings as grouping.py folds them); None if unreadable."""
    b = grouping.parse_blend(text)
    if not b or not 98 <= sum(b.values()) <= 102:
        return None
    return " ".join(f"{p:g}% {f}" for f, p in sorted(b.items(), key=lambda x: (-x[1], x[0])))


# words written before or after a count, each spelling made one; anything else is kept as written (in small letters)
COUNT_WORDS = {"ams": "Amsler", "amsler": "Amsler", "slub": "Slub", "slu": "Slub", "sl": "Slub",
               "spandex": "Spandex", "spx": "Spandex", "spdx": "Spandex", "lycra": "Spandex", "sp": "Spandex",
               "c": "combed", "cm": "combed", "cmd": "combed", "comb": "combed", "combed": "combed",
               "cc": "combed compact", "cpt": "compact", "cmpt": "compact", "compact": "compact"}
_WORDS = "|".join(sorted(COUNT_WORDS, key=len, reverse=True))
_ONE = re.compile(rf"(?:(?P<pre>{_WORDS}))?(?:ne)?(?P<num>1/\d+(?:\.\d+)?|\d+(?:\.\d+)?/[12]|2/\d+(?:\.\d+)?|\d+(?:\.\d+)?)"
                  rf"(?:s(?=$|{_WORDS}|nm$|lea$)|(?:/?s?/?ne)(?=$))?(?P<suf>{_WORDS}|nm|lea)?")


def _count_part(t):
    """One count (no '+'), tidied; None when it does not read as a count."""
    m = _ONE.fullmatch(t)
    if not m:
        return None
    num, pre, suf = m.group("num"), m.group("pre"), m.group("suf")
    if suf in ("nm", "lea"):                                          # a metric or a lea count stays as it is
        return None if pre else f"{num} {'Nm' if suf == 'nm' else 'lea'}"
    if num.startswith("1/"):
        base = f"{float(num[2:]):g}s"
    elif num.endswith("/1"):
        base = f"{float(num[:-2]):g}s"
    elif num.endswith("/2"):
        base = f"2/{float(num[:-2]):g}s"
    elif num.startswith("2/"):
        base = f"2/{float(num[2:]):g}s"
    else:
        base = f"{float(num):g}s"
    words = [COUNT_WORDS[w] for w in (pre, suf) if w]
    return " ".join([base] + words)


def tidy_count(text):
    """A count as the PLM writes it, tidied, so that spellings of one count are one:
    - spaces, case and stray punctuation go; a slash between two letters goes (2/50 P/V = 2/50 PV);
    - a single count: 40, 40s, 40S, 40/1, 1/40, Ne 40, 40NE -> '40s'; a two-ply count: 2/80, 80/2, 2/80s, 2/80 NE -> '2/80s';
    - words before or after it, each spelling made one: Ams/Amsler; Slub/Slu/Sl; Spandex/Spx/Spdx/Sp/Lycra; combed C/CM/CMD;
      combed compact CC; compact CPT/CMPT ('40sSpx' = '40 Spandex' = '40s Spandex'; '50/1C' = '50/1 CMD' = '50s combed');
    - a metric or lea count stays as it is: '36NM' = '36s NM' = '36 Nm'; '2/90/NM' = '2/90 Nm'; '60 LEA' = '60 lea';
    - counts joined by '+' are tidied one by one ('25/1+40D' = '25s/1 + 40D').
    Anything else is kept as written, in small letters without spaces. None when missing (blank, or a single figure under
    4, which the PLM uses as a filler)."""
    t = re.sub(r"\s+", "", str(text or "")).lower().replace("'s", "s").strip(",.;:")
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
    if not t:
        return None
    t = re.sub(r"(?<=[a-z])/(?=[a-z])", "", t)                      # P/V = PV
    t = re.sub(r"(?<=\d)s(?=/\d)", "", t)                            # 25s/1 = 25/1
    t = re.sub(r"(?<=\d)/(?=[a-z])", "", t)                           # 2/90/NM = 2/90 NM
    parts = t.split("+")
    if len(parts) == 1:
        one = _count_part(t)
        if one and re.fullmatch(r"[\d.]+s", one) and float(one[:-1]) < 4:
            return None
        return one or t
    tidied = [_count_part(p) or p for p in parts]
    return " + ".join(tidied)


def tidy_finish(text):
    """'F - Normal Soft' -> 'Normal Soft'; 'F - Peach + F - RFD' -> 'Peach + RFD'. None when blank. Finishes written
    differently ('Regular', 'Normal Soft', 'Soft Finish') stay apart unless an admin merges them."""
    t = re.sub(r"(^|\+)\s*F\s*[-–]\s*", r"\1", str(text or "").strip(), flags=re.I)
    t = re.sub(r"\s*\+\s*", " + ", re.sub(r"\s+", " ", t)).strip(" +")
    return t or None


def tidy_route(text):
    t = str(text or "").strip()
    if not t:
        return None
    return pilot.PLM_ROUTE.get(t.lower(), " ".join(w.capitalize() for w in t.split()))


def tidy_weave(text):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return None if not t or t.lower() in ("not applicable", "na", "n/a", "-") else t


def width_grid(width):
    """The finished width a group is matched on: the nearest whole inch (a half goes up). 57 in and 145 cm (57.1 in)
    are one; 57 in and 58 in are two; every code of a group is within half an inch of the group's width."""
    return float(int(width + 0.5))


def signature_of(spec):
    """(fields, signature, None) for a complete specification, or (None, None, why it is not grouped)."""
    if not spec:
        return None, None, "No PLM specification for this code"
    s = short_spec(spec)
    if s.get("productgroup_name", "") != "Woven":
        return None, None, f"Not a woven fabric ({s.get('productgroup_name') or 'blank'} in the PLM)"
    epi, ppi, width = pilot.plm_numbers(s)
    f = {"content": tidy_content(s.get("blend_name")), "route": tidy_route(s.get("dyemethod_name")),
         "weave": tidy_weave(s.get("weavetype_name")), "warp": tidy_count(s.get("warpcount")), "weft": tidy_count(s.get("weftcount")),
         "epi": round(epi, 1) if epi > 20 else None, "ppi": round(ppi, 1) if ppi > 20 else None,      # pilot.py: 20 or less is missing
         "width_in": width_grid(width) if 30 <= width <= 130 else None, "finish": tidy_finish(s.get("finish_name"))}
    missing = [FIELD_WORDS[k] for k in FIELDS if f[k] is None]
    if missing:
        return None, None, "PLM specification incomplete: " + ", ".join(missing) + " missing"
    sig = "|".join(str(f[k]).lower() if isinstance(f[k], str) else f"{f[k]:g}" for k in FIELDS)
    return f, sig, None


def name_of(f):
    """The readable Fab group name: '100% Cotton · Yarn Dyed · Twill-2/1 · 40s x 40s · 136 x 90 · 57 in · Normal Soft'."""
    return (f"{f['content']} · {f['route']} · {f['weave']} · {f['warp']} x {f['weft']} · {f['epi']:g} x {f['ppi']:g} · "
            f"{f['width_in']:g} in · {f['finish']}")


def signatures(specs, codes):
    """What regroup() needs of each code the PLM list has, worked out before its transaction (so the store is held only
    for the writing): {code: {spec, sha, fields, sig, why}}."""
    out = {}
    for code in codes:
        if code in specs:
            spec = specs[code]
            fields, sig, why = signature_of(spec)
            out[code] = {"spec": spec, "sha": spec_sha(spec), "fields": fields, "sig": sig, "why": why}
    return out


def regroup(c, specs, first_seen, new_codes, at, upload_id, ready=None):
    """Every fabric's Fab group worked out again from its specification (the PLM list's, else the one kept): new codes
    are placed, and a code whose specification was corrected or completed, or whose fields are tidied another way now,
    moves; each move is recorded. A group whose signature is no longer anyone's keeps its code under the new signature of
    most of its codes. New groups get the next codes in order of first appearance (first_seen: code -> sort key).
    `ready`: signatures() worked out beforehand. Returns (new groups, moves)."""
    index = dp.fabric_index(c)
    stored = dp.specs_of(c, [f["id"] for code, f in index.items() if code not in specs and f["spec_sha"]])
    ready = ready or {}
    now = {}
    for code, f in index.items():
        if code in specs and code in ready:
            now[code] = ready[code]
            continue
        spec = specs.get(code) if code in specs else stored.get(f["id"])
        fields, sig, why = signature_of(spec)
        now[code] = {"spec": spec, "sha": spec_sha(spec), "fields": fields, "sig": sig, "why": why}
    groups = dp.groups(c)
    by_sig = {g["signature"]: i for i, g in groups.items()}
    used = {v["sig"] for v in now.values() if v["sig"]}
    target, fields_of, resign = {}, {}, {}
    holders = {}
    for code, v in now.items():
        if v["sig"]:
            fields_of.setdefault(v["sig"], v["fields"])
            holders.setdefault(v["sig"], []).append(index[code]["fab_group_id"])
    for sig in sorted(holders):
        if sig in by_sig:
            target[sig] = by_sig[sig]
            continue
        # a group whose own signature nobody has now, holding most of these codes, keeps its code under this signature
        counts = {}
        for g in holders[sig]:
            if g is not None and groups[g]["signature"] not in used and g not in resign:
                counts[g] = counts.get(g, 0) + 1
        if counts:
            g = sorted(counts, key=lambda x: (-counts[x], x))[0]
            resign[g] = sig
            target[sig] = g
    for g, sig in resign.items():
        dp.resign_group(c, g, name_of(fields_of[sig]), fields_of[sig], sig)
    fresh = sorted((sig for sig in holders if sig not in target),
                   key=lambda s: (min(first_seen.get(code, ("9999",)) for code, v in now.items() if v["sig"] == s), s))
    n = dp.last_group_number(c)
    rows = []
    for sig in fresh:
        n += 1
        rows.append((f"Fab-{n:04d}", name_of(fields_of[sig]), fields_of[sig], sig))
    target.update(dp.add_groups(c, rows, at, upload_id))
    groups = dp.groups(c) if rows or resign else groups
    changes, moves = [], []
    for code, v in now.items():
        f = index[code]
        to = target.get(v["sig"]) if v["sig"] else None
        change = {}
        if to != f["fab_group_id"]:
            change.update(fab_group_id=to)
            if code not in new_codes:
                spec_changed = v["sha"] != f["spec_sha"]
                why = (("its PLM specification is now complete" if f["fab_group_id"] is None else "its PLM specification changed")
                       if spec_changed and to is not None else
                       (f"its PLM specification changed: {v['why']}" if to is None else "the way its fields are tidied changed"))
                moves.append((f["id"], f["fab_group_id"], to, why))
        if v["sig"] != f["signature"]:
            change["signature"] = v["sig"]
        if (v["why"] or None) != f["not_grouped"]:
            change["not_grouped"] = v["why"]
        if v["sha"] != f["spec_sha"]:
            change.update(spec=v["spec"], spec_sha=v["sha"])
        if change:
            changes.append(dict(change, id=f["id"]))
    dp.set_fabrics(c, changes, at)
    dp.add_regroups(c, moves, at, upload_id)
    return len(rows), moves


# ------------------------------------------------------------------ reading the groups
NEEDS_DB = ("The purchase history (Fab groups, price over time, purchase-file uploads) is kept in the database, and this server "
            "keeps its data in files (the app setting DATABASE_URL is not set). Everything else works as before.")


def need_db():
    st = store.get()
    if st.kind == "files":
        raise common.Refused(503, NEEDS_DB)
    return st


def final(groups, gid):
    """The group a group now counts as: itself, or the one it was merged into (and so on)."""
    seen = set()
    while gid is not None and groups[gid]["merged_into"] is not None and gid not in seen:
        seen.add(gid)
        gid = groups[gid]["merged_into"]
    return gid


_memo = {}


def _kept(name, key, make):
    hit = _memo.get(name)
    if hit is None or hit[0] != key:
        _memo[name] = (key, make())
    return _memo[name][1]


def version():
    """Where the purchase history is at (it moves with every change); None on the files store."""
    st = store.get()
    return None if st.kind == "files" else st.version(dp.KIND)


def by_code():
    """For Right cost's Fab group column: {fabric code: {"code", "name"}} (the group it counts in now), or
    {"code": None, "why": ...} for a fabric not grouped. Empty on the files store (no purchase history there)."""
    st = store.get()
    if st.kind == "files":
        return {}
    key = st.version(dp.KIND)

    def make():
        with st.tx() as c:
            groups, fabs = dp.groups(c), dp.fabric_groups(c)
        out = {}
        for code, (gid, why) in fabs.items():
            g = groups.get(final(groups, gid)) if gid is not None else None
            out[code] = {"code": g["code"], "name": g["name"]} if g else {"code": None, "why": why or "Not grouped"}
        return out
    return _kept("by_code", key, make)


def price_range(lines):
    """The group's median price and usual range, by the brief's own rule (costing.usual_range) set round the median.
    lines: (price, order number), ZLOI left out. No range with purchases on fewer than MIN_FOR_RANGE separate orders."""
    prices = sorted(float(p) for p, _ in lines)
    orders = len({po for _, po in lines})
    if not prices:
        return {"median": None, "enough": False, "n": 0, "orders": 0}
    med = statistics.median(prices)
    out = {"median": round(med, 2), "n": len(prices), "orders": orders, "low": round(prices[0], 2), "high": round(prices[-1], 2),
           "enough": orders >= MIN_FOR_RANGE}
    if out["enough"]:
        q = statistics.quantiles(prices, n=4, method="inclusive")         # pandas' own quantile (linear), as panel 1 uses
        p25, p75 = (q[0] / med - 1) * 100, (q[2] / med - 1) * 100
        lo, hi = costing.usual_range(p25, p75)
        out.update(p25=p25, p75=p75, lo=lo, hi=hi, lower=round(med * (1 + lo / 100), 2), upper=round(med * (1 + hi / 100), 2),
                   q25=round(q[0], 2), q75=round(q[2], 2))
    return out


def _should(fabric, m):
    """A fabric's should-cost on today's rates (Rs/m), or None with why."""
    if not fabric.get("choices"):
        return None, "; ".join(fabric.get("problems") or ["not costed"])
    try:
        return round(masters.cost(dict(fabric["choices"]), m)["total_per_m"], 2), None
    except Exception as e:          # a choice no longer on today's lists
        return None, f"not costed on today's rates: {e}"


def shoulds(fabrics):
    """{fabric code: (should-cost or None, why)} on today's rates, kept while the rates and the history are unchanged."""
    st = store.get()
    key = (st.version("rates"), st.version(dp.KIND))
    if _memo.get("should", (None,))[0] != key:
        _memo["should"] = (key, {})
    kept, m = _memo["should"][1], None
    for code, f in fabrics.items():
        if code not in kept:
            m = m or common.get_masters()
            kept[code] = _should(f, m)
    return {code: kept[code] for code in fabrics}


def _members(groups, gid):
    """The group and every group merged into it (directly or through another)."""
    return [g for g in groups if final(groups, g) == gid]


def _line(r):
    return {"date": r["doc_date"], "po": r["po_number"], "item": r["item"], "code": r["fabric_code"], "mill": r["mill"],
            "mill_key": r["mill_key"], "metres": round(float(r["qty_m"]), 2), "price": round(float(r["price"]), 2), "type": r["doc_type"]}


def gather(c, gid, groups):
    """Inside a transaction: what history() needs of one group (gid: the group it counts as now)."""
    member_ids = _members(groups, gid)
    fabs = dp.fabrics(c, group_ids=member_ids)
    ids = [f["id"] for f in fabs.values()]
    return {"gid": gid, "groups": groups, "member_ids": member_ids, "fabs": fabs, "lines": dp.lines(c, ids),
            "outliers": dp.lines(c, ids, outliers=True), "moves": dp.regroups(c, member_ids)}


def history(got):
    """What the group page and the price popup show of one group, from gather() (outside the transaction: the
    should-costs read the rate master). ZLOI lines are in no figure; they are listed apart."""
    gid, groups, member_ids, fabs, lines = got["gid"], got["groups"], got["member_ids"], got["fabs"], got["lines"]
    g = groups[gid]
    rng = price_range([(r["price"], r["po_number"]) for r in lines])
    sh = shoulds(fabs)
    costed = sorted(v for v, _ in sh.values() if v is not None)
    by_mill, out_by_mill = {}, {}
    for r in lines:
        by_mill.setdefault(r["mill_key"], []).append(r)
    for r in got["outliers"]:
        out_by_mill.setdefault(r["mill_key"], []).append(r)
    mills_ = []
    total_m = sum(float(r["qty_m"]) for r in lines)
    for key in list(by_mill) + [k for k in out_by_mill if k not in by_mill]:
        rs, zs = by_mill.get(key, []), out_by_mill.get(key, [])
        ps = [float(r["price"]) for r in rs]
        med = statistics.median(ps) if ps else None
        mills_.append({"key": key, "name": (rs or zs)[0]["mill"], "lines": len(rs), "metres": round(sum(float(r["qty_m"]) for r in rs), 2),
                       "orders": len({r["po_number"] for r in rs}), "median": None if med is None else round(med, 2),
                       "low": round(min(ps), 2) if ps else None, "high": round(max(ps), 2) if ps else None,
                       "last": max(r["doc_date"] for r in rs) if rs else None,
                       "share": sum(float(r["qty_m"]) for r in rs) / total_m if total_m and rs else None,
                       "vs_group": None if not rng["median"] or med is None else (med / rng["median"] - 1) * 100,
                       "outliers": [_line(r) for r in zs]})
    mills_.sort(key=lambda x: (-x["metres"], x["name"]))
    above = []
    if rng["enough"]:
        for r in lines:
            if round(float(r["price"]), 2) > rng["upper"]:
                gap = round(float(r["price"]) - rng["upper"], 2)
                above.append(dict(_line(r), above=gap, above_rs=round(gap * float(r["qty_m"]), 0),
                                  pct=(float(r["price"]) / rng["median"] - 1) * 100))
        above.sort(key=lambda x: -x["above_rs"])
    codes = {}
    for r in lines:
        codes.setdefault(r["fabric_code"], []).append(r)
    zcodes = {}
    for r in got["outliers"]:
        zcodes[r["fabric_code"]] = zcodes.get(r["fabric_code"], 0) + 1
    fab_rows = []
    for code, f in fabs.items():
        rs = codes.get(code, [])
        s, why = sh[code]
        fab_rows.append({"code": code, "description": f["description"], "lines": len(rs), "metres": round(sum(float(r["qty_m"]) for r in rs), 2),
                         "mills": sorted({r["mill"] for r in rs}), "last_price": round(float(rs[-1]["price"]), 2) if rs else None,
                         "last_date": rs[-1]["doc_date"] if rs else None, "should": s, "should_why": why, "outliers": zcodes.get(code, 0),
                         "in_group": groups[f["fab_group_id"]]["code"]})
    fab_rows.sort(key=lambda x: (-x["lines"], x["code"]))
    whys = sorted({why for v, why in sh.values() if v is None and why})
    name = lambda i: None if i is None else groups[i]["code"]
    members = set(member_ids)
    return {"code": g["code"], "name": g["name"], "fields": {k: g[k] for k in FIELDS}, "created": g["created_at"],
            "merged_in": [{"code": groups[i]["code"], "name": groups[i]["name"], "merged_at": groups[i]["merged_at"], "merged_by": groups[i]["merged_by"]}
                          for i in member_ids if i != gid],
            "purchases": len(lines), "metres": round(total_m, 2), "orders": len({r["po_number"] for r in lines}),
            "first": lines[0]["doc_date"] if lines else None, "last": lines[-1]["doc_date"] if lines else None,
            "range": rng, "min_for_range": MIN_FOR_RANGE, "mills": mills_, "lines": [_line(r) for r in lines], "above": above,
            "above_rs": round(sum(a["above_rs"] for a in above), 0), "fabrics": fab_rows,
            "outliers": [_line(r) for r in got["outliers"]],
            "moved_in": [{"code": m["code"], "from": name(m["from_group_id"]), "why": m["why"], "at": m["at"]} for m in got["moves"]
                         if m["to_group_id"] in members and m["from_group_id"] not in members],
            "moved_out": [{"code": m["code"], "to": name(m["to_group_id"]), "why": m["why"], "at": m["at"]} for m in got["moves"]
                          if m["from_group_id"] in members and m["to_group_id"] not in members],
            "should": {"median": round(statistics.median(costed), 2) if costed else None, "low": costed[0] if costed else None,
                       "high": costed[-1] if costed else None, "costed": len(costed), "fabrics": len(fabs), "why_not": whys[:3]}}


def page(code):
    """The Fab group page (#group/<code>)."""
    st = need_db()
    code = str(code or "").strip()
    with st.tx() as c:
        groups = dp.groups(c)
        hit = next((i for i, g in groups.items() if g["code"].lower() == code.lower()), None)
        if hit is None:
            raise common.Refused(404, f"There is no Fab group {code}.")
        now = final(groups, hit)
        got = gather(c, now, groups)
    out = history(got)
    if now != hit:
        out["asked"] = {"code": groups[hit]["code"], "name": groups[hit]["name"], "merged_at": groups[hit]["merged_at"],
                        "merged_by": groups[hit]["merged_by"]}
    return out


def listing():
    """Every Fab group with codes in it now, with its purchases, orders, metres and median price (ZLOI left out);
    merged ones say where they went."""
    st = need_db()
    with st.tx() as c:
        groups, stats, prices, counts = dp.groups(c), dp.group_stats(c), dp.prices_by_group(c), dp.counts(c)
        fabs = dp.fabric_groups(c)
    per = {}
    blank = lambda: {"lines": 0, "metres": 0.0, "last": None, "prices": [], "codes": 0}
    for gid in groups:
        f = final(groups, gid)
        n, metres, _, last = stats.get(gid, (0, 0, 0, None))
        p = per.setdefault(f, blank())
        p["lines"] += n
        p["metres"] += float(metres or 0)
        p["last"] = max(filter(None, [p["last"], last]), default=None)
        p["prices"] += prices.get(gid, [])
    for _, (gid, _) in fabs.items():
        if gid is not None:
            per.setdefault(final(groups, gid), blank())["codes"] += 1
    rows = []
    for gid, g in groups.items():
        p = per.get(gid, blank())
        if g["merged_into"] is not None or not p["codes"]:
            continue
        rows.append({"code": g["code"], "name": g["name"], "codes": p["codes"], "purchases": p["lines"], "metres": round(p["metres"], 2),
                     "orders": len({po for _, po in p["prices"]}),
                     "median": round(statistics.median([x for x, _ in p["prices"]]), 2) if p["prices"] else None, "last": p["last"],
                     "route": g["route"], "weave": g["weave"], "content": g["content"]})
    merged = [{"code": g["code"], "name": g["name"], "into": groups[final(groups, gid)]["code"], "merged_at": g["merged_at"],
               "merged_by": g["merged_by"]} for gid, g in groups.items() if g["merged_into"] is not None]
    why = {}
    for _, (gid, w) in fabs.items():
        if gid is None:
            k = re.sub(r":.*", "", w or "Not grouped")
            why[k] = why.get(k, 0) + 1
    counts["groups"] = len(rows)
    return {"groups": rows, "merged": merged, "counts": counts, "not_grouped": sorted(why.items(), key=lambda x: -x[1]),
            "min_for_range": MIN_FOR_RANGE}


def differences(a, b):
    """The fields two groups differ in, beyond width and finish (which an admin may merge freely)."""
    return [{"field": FIELD_WORDS[k], "a": a[k], "b": b[k]} for k in FIELDS if k not in MERGE_FREELY and str(a[k]).lower() != str(b[k]).lower()]


def merge(payload, who=""):
    """An admin merges one group into another: its fabrics count in the other from now on; its code is kept (its page
    says where it went) and is never handed out again. When the two differ in more than width or finish, nothing is
    merged until the person confirms (payload "confirm": true). An admin action: do:merge_groups (rules/access.py)."""
    st = need_db()
    a, b = str(payload.get("code") or "").strip(), str(payload.get("into") or "").strip()
    if not a or not b:
        raise common.Refused(400, "Give the Fab group to merge and the one to merge it into.")
    with st.tx(write=dp.KIND) as c:
        groups = dp.groups(c)
        by = {g["code"].lower(): i for i, g in groups.items()}
        if a.lower() not in by or b.lower() not in by:
            raise common.Refused(404, f"There is no Fab group {a if a.lower() not in by else b}.")
        ga, gb = by[a.lower()], final(groups, by[b.lower()])
        if groups[ga]["merged_into"] is not None:
            raise common.Refused(409, f"{groups[ga]['code']} is already merged into {groups[final(groups, ga)]['code']}.")
        if ga == gb:
            raise common.Refused(400, f"{groups[ga]['code']} and {b} are the same group.")
        diff = differences(groups[ga], groups[gb])
        if diff and payload.get("confirm") is not True:
            return {"needs_confirm": True, "differences": diff, "code": groups[ga]["code"], "into": groups[gb]["code"],
                    "detail": f"{groups[ga]['code']} and {groups[gb]['code']} differ in more than width or finish: "
                              + "; ".join(f"{d['field']} {d['a']} against {d['b']}" for d in diff)
                              + ". Merge them only if they are really one cloth."}
        dp.set_merged(c, ga, gb, store._now(), who or "")
    return {"merged": groups[ga]["code"], "into": groups[gb]["code"], "differences": diff, "page": page(groups[gb]["code"])}


def unmerge(payload, who=""):
    """Undo a merge: the group counts on its own again."""
    st = need_db()
    a = str(payload.get("code") or "").strip()
    with st.tx(write=dp.KIND) as c:
        groups = dp.groups(c)
        hit = next((i for i, g in groups.items() if g["code"].lower() == a.lower()), None)
        if hit is None:
            raise common.Refused(404, f"There is no Fab group {a}.")
        if groups[hit]["merged_into"] is None:
            raise common.Refused(409, f"{groups[hit]['code']} is not merged into another group.")
        dp.set_merged(c, hit, None, None, None)
    return {"unmerged": groups[hit]["code"]}
