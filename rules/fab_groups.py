"""Fab groups: the same construction in any colour, across mills (the mill is a breakdown inside a group).

A fabric code's group is decided by nine fields of its PLM specification, tidied and then matched exactly: content,
route, weave, warp count, weft count, EPI, PPI, finished width and finish. Widths are matched with a tolerance (GP, 27
Nov 2026: widths within half an inch are one group): codes alike in the other eight fields whose widths are within half
an inch of each other, directly or through other codes, are one group (57 in and 145 cm; 57.4 and 57.5 in); the group's
name gives the widths it runs from and to. It depends only on the widths held, never on the order the files came in.
A code whose specification is missing or incomplete is "not grouped":
nothing is guessed. Codes run Fab-0001 onward in order of first appearance; a code is never changed and never handed out
again, even after an admin merges its group into another (the merged group keeps its code and its page says where it
went). When a code's specification is corrected or completed, or the way the fields are tidied changes, the code moves
at the next upload and both group pages say so; a group whose codes all changed together keeps its code under its new
name, and its page says it was renamed and why. Every code whose specification changed is costed again.

The group page: purchases, metres, mills, median price, usual range, should-cost, price over time by mill, and the
purchases priced well above the group. "Priced well above its group" is GP's decision of 27 Nov 2026: above the group's
usual range by the brief's own rule (costing.usual_range): the middle half of the group's past prices, kept between 5%
and 10% either side of the group's median. A range needs purchases on at least MIN_FOR_RANGE separate orders.
ZLOI order lines are left out of every figure and shown apart as outliers (GP, 27 Nov 2026)."""
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import warnings

from rules import common, costing, dated
import data_dated
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
WIDTH_TOLERANCE = 0.5               # inches: widths this close (directly or through other codes) are one group


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


def width_spans(widths):
    """{width: (from, to)}: the widths (in inches) of codes alike in the other eight fields, joined where two are within
    half an inch of each other (directly or through others). Depends only on the widths given, never on their order."""
    out, run = {}, []
    for w in sorted(set(widths)) + [None]:
        if run and (w is None or w - run[-1] > WIDTH_TOLERANCE + 1e-9):
            for x in run:
                out[x] = (run[0], run[-1])
            run = []
        if w is not None:
            run.append(w)
    return out


def _sig(f):
    return "|".join(str(f[k]).lower() if isinstance(f[k], str) else f"{f[k]:g}" for k in FIELDS)


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
         "width_in": round(width, 2) if 30 <= width <= 130 else None, "finish": tidy_finish(s.get("finish_name"))}
    missing = [FIELD_WORDS[k] for k in FIELDS if f[k] is None]
    if missing:
        return None, None, "PLM specification incomplete: " + ", ".join(missing) + " missing"
    return f, _sig(f), None             # the signature of a group of this one width; regroup() joins the widths within half an inch


def _rest(sig):
    """A signature without its width: codes alike in the other eight fields."""
    parts = sig.split("|")
    return "|".join(parts[:FIELDS.index("width_in")] + parts[FIELDS.index("width_in") + 1:])


def name_of(f):
    """The readable Fab group name: '100% Cotton · Yarn Dyed · Twill-2/1 · 40s x 40s · 136 x 90 · 57 in · Normal Soft'
    (a group of several widths: '57 to 57.48 in')."""
    to = f.get("width_to")
    width = f"{f['width_in']:g} to {to:g} in" if to is not None and to != f["width_in"] else f"{f['width_in']:g} in"
    return (f"{f['content']} · {f['route']} · {f['weave']} · {f['warp']} x {f['weft']} · {f['epi']:g} x {f['ppi']:g} · "
            f"{width} · {f['finish']}")


def _changed(a, b):
    """What changed between two sets of fields, in words: 'EPI 132 to 142; finished width 57.09 to 57.48 in'."""
    if not a or not b:
        return ""
    out = []
    for k in FIELDS:
        if str(a.get(k)).lower() != str(b.get(k)).lower():
            unit = " in" if k == "width_in" else ""
            show = lambda v: f"{v:g}" if isinstance(v, float) else str(v)
            out.append(f"{FIELD_WORDS[k]} {show(a.get(k))}{unit} to {show(b.get(k))}{unit}")
    if not out and (a.get("width_to") or a.get("width_in")) != (b.get("width_to") or b.get("width_in")):
        out.append(f"codes of other widths joined: it runs from {b['width_in']:g} to {(b.get('width_to') or b['width_in']):g} in")
    return "; ".join(out)


def _own(v):
    """A code's own fields (its own width, not the span of its group), or None when it is not grouped."""
    return {k: (v.get("own_width") if k == "width_in" else v["fields"][k]) for k in FIELDS} if v.get("fields") else None


def _widths_moved(f, v, now, new_codes):
    """Why a code whose specification did not change moved, when only the widths it is grouped with changed: a new code
    joined them (its widths now meet another group's), or codes of other widths joined or left. None otherwise."""
    if not f["signature"] or not v["sig"] or _rest(f["signature"]) != _rest(v["sig"]):
        return None
    lo, hi = v["fields"]["width_in"], v["fields"].get("width_to") or v["fields"]["width_in"]
    joined = sorted((x["own_width"], code) for code, x in now.items() if code in new_codes and x["sig"] == v["sig"])
    if joined:
        return (f"a new code joined the widths ({', '.join(f'{code} at {w:g} in' for w, code in joined[:3])}"
                f"{f' and {len(joined) - 3} more' if len(joined) > 3 else ''}): its group now runs {lo:g} to {hi:g} in")
    return f"codes of other widths joined or left: its group now runs {lo:g} to {hi:g} in"


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
    moves; each move is recorded. Widths within half an inch (directly or through others) are one group (width_spans).
    A group whose signature is no longer anyone's keeps its code under the new signature of most of its codes, and a
    group whose name changes says so (fab_group_change). New groups get the next codes in order of first appearance
    (first_seen: code -> sort key). `ready`: signatures() worked out beforehand.
    Returns {groups_new, moves, respecified (fabric ids whose specification changed: costed again), renamed}."""
    index = dp.fabric_index(c)
    stored = dp.specs_of(c, [f["id"] for code, f in index.items() if code not in specs and f["spec_sha"]])
    ready = ready or {}
    now = {}
    for code, f in index.items():
        if code in specs and code in ready:
            now[code] = dict(ready[code])
            continue
        spec = specs.get(code) if code in specs else stored.get(f["id"])
        fields, sig, why = signature_of(spec)
        now[code] = {"spec": spec, "sha": spec_sha(spec), "fields": fields, "sig": sig, "why": why}
    # the width tolerance: each code's signature is its group's (the widths it is joined with, from the lowest)
    widths = {}
    for v in now.values():
        if v["sig"]:
            widths.setdefault(_rest(v["sig"]), []).append(v["fields"]["width_in"])
    spans = {rest: width_spans(ws) for rest, ws in widths.items()}
    for v in now.values():
        if v["sig"]:
            lo, hi = spans[_rest(v["sig"])][v["fields"]["width_in"]]
            v["own_width"] = v["fields"]["width_in"]
            v["fields"] = dict(v["fields"], width_in=lo, width_to=hi)
            v["sig"] = _sig(v["fields"])
    # what changed in the specification of a code held before (its old fields, for the record)
    changed_ids = [f["id"] for code, f in index.items() if f["spec_sha"] and now[code]["sha"] != f["spec_sha"]]
    before = dp.specs_of(c, changed_ids) if changed_ids else {}
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
    renamed = []
    for g, sig in resign.items():
        renamed.append((g, groups[g]["name"], name_of(fields_of[sig]), "its codes' PLM specification changed: " + (_changed(
            {k: groups[g][k] for k in FIELDS} | {"width_to": groups[g].get("width_to")}, fields_of[sig]) or "how its fields are tidied")))
        dp.resign_group(c, g, name_of(fields_of[sig]), fields_of[sig], sig)
    for sig, g in target.items():        # a group kept under its signature whose name changes (codes of other widths joined)
        if g not in resign and groups[g]["name"] != name_of(fields_of[sig]):
            renamed.append((g, groups[g]["name"], name_of(fields_of[sig]), _changed({k: groups[g][k] for k in FIELDS} | {"width_to": groups[g].get("width_to")},
                                                                                     fields_of[sig]) or "its name is written another way now"))
            dp.resign_group(c, g, name_of(fields_of[sig]), fields_of[sig], sig)
    dp.add_group_changes(c, renamed, at, upload_id)
    fresh = sorted((sig for sig in holders if sig not in target),
                   key=lambda s: (min(first_seen.get(code, ("9999",)) for code, v in now.items() if v["sig"] == s), s))
    n = dp.last_group_number(c)
    rows = []
    for sig in fresh:
        n += 1
        rows.append((f"Fab-{n:04d}", name_of(fields_of[sig]), fields_of[sig], sig))
    target.update(dp.add_groups(c, rows, at, upload_id))
    groups = dp.groups(c) if rows or renamed else groups
    changes, moves, respecified = [], [], []
    for code, v in now.items():
        f = index[code]
        to = target.get(v["sig"]) if v["sig"] else None
        change = {}
        if to != f["fab_group_id"]:
            change.update(fab_group_id=to)
            if code not in new_codes:
                spec_changed = v["sha"] != f["spec_sha"]
                if to is None:
                    why = f"its PLM specification changed: {v['why']}"
                elif spec_changed and f["fab_group_id"] is None:
                    why = "its PLM specification is now complete"
                elif spec_changed:                   # what changed, as for a code that stays in its group
                    what = _changed(signature_of(before.get(f["id"]))[0], _own(v))
                    widths = None if what else _widths_moved(f, v, now, new_codes)
                    why = ("its PLM specification changed" + (f": {what}" if what else " (not in its Fab group's fields)") + "; costed again"
                           + (f"; {widths}" if widths else ""))
                else:
                    why = _widths_moved(f, v, now, new_codes) or "the way its fields are tidied changed"
                moves.append((f["id"], f["fab_group_id"], to, why))
        if v["sig"] != f["signature"]:
            change["signature"] = v["sig"]
        if (v["why"] or None) != f["not_grouped"]:
            change["not_grouped"] = v["why"]
        if v["sha"] != f["spec_sha"]:
            change.update(spec=v["spec"], spec_sha=v["sha"])
            if f["spec_sha"]:
                respecified.append(f["id"])
                if to == f["fab_group_id"]:          # it stays in its group: the change is recorded beside it all the same
                    what = _changed(signature_of(before.get(f["id"]))[0], _own(v))
                    moves.append((f["id"], f["fab_group_id"], to, "its PLM specification changed" + (f": {what}" if what else
                                                                                                    " (not in its Fab group's fields)") + "; costed again"))
        if change:
            changes.append(dict(change, id=f["id"]))
    dp.set_fabrics(c, changes, at)
    dp.add_regroups(c, moves, at, upload_id)
    return {"groups_new": len(rows), "moves": moves, "respecified": respecified, "renamed": renamed}


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


# ------------------------------------------------------------------ the usual range over time (GP's decision, 28 Nov 2026)
# "What we usually pay" (a Fab group's or a fabric type's usual range, its median, "priced above its group / its range")
# rests by default on the purchases of the last 12 months, ending today. The Fab group page and the price popup have a time
# slider to choose another period (a view only: every verdict elsewhere stays on the default); older purchases always stay
# on the price-over-time chart.
TODAY_ENV = "RIGHTPRICE_TODAY"      # a fixed "today" (YYYY-MM-DD), for the checks only, so their figures do not move with the date
IST = dt.timedelta(hours=5, minutes=30)


def today():
    """Today, as a day in India (document dates are days in India)."""
    fixed = os.environ.get(TODAY_ENV, "").strip()
    if fixed:
        return dt.date.fromisoformat(fixed)
    return (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + IST).date()


def _year_before(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:              # 29 February: 28 February of the year before
        return d.replace(year=d.year - 1, day=28)


def default_period(day=None):
    """The last 12 months, ending today: (from, to), ISO days, both included (29 Nov 2025 to 28 Nov 2026)."""
    d = day or today()
    return (_year_before(d) + dt.timedelta(days=1)).isoformat(), d.isoformat()


def _words(day):
    d = dt.date.fromisoformat(day)
    return f"{d.day} {d:%b %Y}"


def period(frm=None, to=None):
    """The period "what we usually pay" rests on: {from, to, default, label}. None for both: the default (the last 12
    months, ending today). A month (2026-03) is read as its first day (from) or its last (to)."""
    dfrom, dto = default_period()

    def read(v, end):
        v = str(v or "").strip()
        if not v:
            return None
        try:
            if re.fullmatch(r"\d{4}-\d{2}", v):
                d = dt.date.fromisoformat(v + "-01")
                if end:
                    d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
                return d.isoformat()
            return dt.date.fromisoformat(v[:10]).isoformat()
        except ValueError:
            raise common.Refused(400, f"{v} is not a date: give the period as YYYY-MM-DD or YYYY-MM.")
    f, t = read(frm, False) or (dfrom if not to else "0001-01-01"), read(to, True) or dto
    if f > t:
        raise common.Refused(400, f"The period runs from {f} to {t}: its start is after its end.")
    default = (f, t) == (dfrom, dto)
    label = ("the last 12 months" if default else "the period chosen") + f" ({_words(f) if f > '0001-01-01' else 'the first purchase'} to {_words(t)})"
    return {"from": f, "to": t, "default": default, "label": label}


def months_held(first, last):
    """The months the slider runs over: from the history's first month to its last, or to this month if later."""
    if not first:
        return []
    end = max(last or first, today().isoformat())[:7]
    out, y, m = [], int(first[:4]), int(first[5:7])
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def in_period(day, p):
    return day is not None and p["from"] <= day <= p["to"]


def _should(fabric, m, om=None, table=None):
    """A fabric's should-cost (Rs/m) as Right cost costs a purchase order: on the yarn rates of its order month (om, from
    dated.month_of; today's where none is dated) and today's other rates. (should-cost or None, why, which rates)."""
    if not fabric.get("choices"):
        return None, "; ".join(fabric.get("problems") or ["not costed"]), None
    try:
        res = masters.cost(dict(fabric["choices"]), m, on=om["month"] if om else None, dated=table)
    except Exception as e:          # a choice no longer on today's lists
        return None, f"not costed on today's rates: {e}", None
    ro = res.get("rates_of") or {}
    return round(res["total_per_m"], 2), None, f"on the dated yarn rates of {ro['label']}" if ro.get("dated") else "on today's rates"


def shoulds(fabrics, lines=()):
    """{fabric code: (should-cost or None, why, which rates)}, each on the yarn rates of its order month, worked out from
    its own lines (rows of the history with fabric_code, doc_date and qty_m; ZLOI left out) as Right cost works it out.
    Kept while the rates, the dated rates and the history are unchanged."""
    st = store.get()
    key = (st.version("rates"), st.version(dp.KIND), data_dated.version())
    if _memo.get("should", (None,))[0] != key:
        _memo["should"] = (key, {})
    kept, m, table, by = _memo["should"][1], None, None, {}
    for r in lines:
        by.setdefault(r["fabric_code"], []).append((r["doc_date"], float(r["qty_m"])))
    for code, f in fabrics.items():
        if code not in kept:
            if m is None:
                m, table = common.get_masters(), data_dated.table()
            kept[code] = _should(f, m, dated.month_of(by.get(code, [])), table)
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
            "outliers": dp.lines(c, ids, outliers=True), "moves": dp.regroups(c, member_ids), "renames": dp.group_changes(c, member_ids)}


def history(got, p=None):
    """What the group page and the price popup show of one group, from gather() (outside the transaction: the
    should-costs read the rate master). ZLOI lines are in no figure; they are listed apart. The figures of "what we
    usually pay" (purchases, orders, metres, the median, the usual range, by mill, priced well above) rest on the
    purchases of the period `p` (period(): by default the last 12 months, ending today); every purchase stays on the
    chart (each line says whether it is in the period) and in the codes' table; the should-costs are each code's own,
    on its order month as Right cost costs it, whatever the period."""
    gid, groups, member_ids, fabs, every = got["gid"], got["groups"], got["member_ids"], got["fabs"], got["lines"]
    p = p or period()
    lines = [r for r in every if in_period(r["doc_date"], p)]
    g = groups[gid]
    rng = price_range([(r["price"], r["po_number"]) for r in lines])
    sh = shoulds(fabs, every)
    costed = sorted(v for v, _, _ in sh.values() if v is not None)
    by_mill, out_by_mill = {}, {}
    for r in lines:
        by_mill.setdefault(r["mill_key"], []).append(r)
    for r in got["outliers"]:
        out_by_mill.setdefault(r["mill_key"], []).append(r)
    mills_, everyone = [], {}
    for r in every:                 # every mill bought from, by metres: the chart's colours stay the same whatever the period
        e = everyone.setdefault(r["mill_key"], {"key": r["mill_key"], "name": r["mill"], "metres": 0.0})
        e["metres"] += float(r["qty_m"])
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
    for r in every:
        codes.setdefault(r["fabric_code"], []).append(r)
    zcodes = {}
    for r in got["outliers"]:
        zcodes[r["fabric_code"]] = zcodes.get(r["fabric_code"], 0) + 1
    fab_rows = []
    for code, f in fabs.items():
        rs = codes.get(code, [])
        s, why, _ = sh[code]
        fab_rows.append({"code": code, "description": f["description"], "lines": len(rs), "metres": round(sum(float(r["qty_m"]) for r in rs), 2),
                         "mills": sorted({r["mill"] for r in rs}), "last_price": round(float(rs[-1]["price"]), 2) if rs else None,
                         "last_date": rs[-1]["doc_date"] if rs else None, "should": s, "should_why": why, "outliers": zcodes.get(code, 0),
                         "in_group": groups[f["fab_group_id"]]["code"]})
    fab_rows.sort(key=lambda x: (-x["lines"], x["code"]))
    whys = sorted({why for v, why, _ in sh.values() if v is None and why})
    dated_ = sorted({on for v, _, on in sh.values() if v is not None and on != "on today's rates"})
    name = lambda i: None if i is None else groups[i]["code"]
    members = set(member_ids)
    return {"code": g["code"], "name": g["name"], "fields": {k: g[k] for k in FIELDS} | {"width_to": g.get("width_to")}, "created": g["created_at"],
            "merged_in": [{"code": groups[i]["code"], "name": groups[i]["name"], "merged_at": groups[i]["merged_at"], "merged_by": groups[i]["merged_by"]}
                          for i in member_ids if i != gid],
            "purchases": len(lines), "metres": round(total_m, 2), "orders": len({r["po_number"] for r in lines}),
            "first": every[0]["doc_date"] if every else None, "last": every[-1]["doc_date"] if every else None,
            "period": p, "purchases_all": len(every), "outside_period": len(every) - len(lines),
            "mills_all": sorted(({"key": e["key"], "name": e["name"], "metres": round(e["metres"], 2)} for e in everyone.values()), key=lambda x: (-x["metres"], x["name"])),
            "range": rng, "min_for_range": MIN_FOR_RANGE, "mills": mills_, "lines": [dict(_line(r), inside=in_period(r["doc_date"], p)) for r in every], "above": above,
            "above_rs": round(sum(a["above_rs"] for a in above), 0), "fabrics": fab_rows,
            "outliers": [_line(r) for r in got["outliers"]],
            "moved_in": [{"code": m["code"], "from": name(m["from_group_id"]), "why": m["why"], "at": m["at"]} for m in got["moves"]
                         if m["to_group_id"] in members and m["from_group_id"] not in members],
            "moved_out": [{"code": m["code"], "to": name(m["to_group_id"]), "why": m["why"], "at": m["at"]} for m in got["moves"]
                          if m["from_group_id"] in members and m["to_group_id"] not in members],
            # a code whose specification changed and stayed; the group renamed when its codes' specification changed
            "respecified": [{"code": m["code"], "why": m["why"], "at": m["at"]} for m in got["moves"]
                            if m["from_group_id"] in members and m["to_group_id"] == m["from_group_id"]],
            "renamed": [{"code": name(r["group_id"]), "from": r["old_name"], "to": r["new_name"], "why": r["why"], "at": r["at"]}
                        for r in got.get("renames", []) if r["kind"] == "renamed"],
            "merges": [{"code": name(r["group_id"]), "kind": r["kind"], "why": r["why"], "at": r["at"], "by": r["by_whom"]}
                       for r in got.get("renames", []) if r["kind"] != "renamed"],
            "mills_bought": sum(1 for x in mills_ if x["lines"]),          # mills with purchases beside ZLOI (a mill of ZLOI lines only is listed, not counted)
            "should": {"median": round(statistics.median(costed), 2) if costed else None, "low": costed[0] if costed else None,
                       "high": costed[-1] if costed else None, "costed": len(costed), "fabrics": len(fabs), "why_not": whys[:3],
                       "dated": dated_}}          # which codes' order months have a dated yarn rate (stage 5), as Right cost costs them


def page(code, frm=None, to=None):
    """The Fab group page (#group/<code>), its figures on the period asked for (by default the last 12 months, ending
    today); with the months the history holds, for the page's time slider."""
    st = need_db()
    code = str(code or "").strip()
    p = period(frm, to)
    with st.tx() as c:
        first, last = dp.span(c)
        groups = dp.groups(c)
        hit = next((i for i, g in groups.items() if g["code"].lower() == code.lower()), None)
        if hit is None:
            raise common.Refused(404, f"There is no Fab group {code}.")
        now = final(groups, hit)
        got = gather(c, now, groups)
    out = history(got, p)
    out["months"] = months_held(first, last)
    if now != hit:
        out["asked"] = {"code": groups[hit]["code"], "name": groups[hit]["name"], "merged_at": groups[hit]["merged_at"],
                        "merged_by": groups[hit]["merged_by"]}
    return out


def listing():
    """Every Fab group with codes in it now, with its purchases, orders, metres and median price (ZLOI left out);
    merged ones say where they went."""
    st = need_db()
    usual = period()                # the median: what we usually pay, the last 12 months (GP, 28 Nov 2026)
    with st.tx() as c:
        groups, stats, prices, counts = dp.groups(c), dp.group_stats(c), dp.prices_by_group(c), dp.counts(c)
        recent = dp.prices_by_group_dated(c, usual["from"], usual["to"])
        fabs = dp.fabric_groups(c)
    per = {}
    blank = lambda: {"lines": 0, "metres": 0.0, "last": None, "prices": [], "recent": [], "codes": 0}
    for gid in groups:
        f = final(groups, gid)
        n, metres, _, last = stats.get(gid, (0, 0, 0, None))
        p = per.setdefault(f, blank())
        p["lines"] += n
        p["metres"] += float(metres or 0)
        p["last"] = max(filter(None, [p["last"], last]), default=None)
        p["prices"] += prices.get(gid, [])
        p["recent"] += recent.get(gid, [])
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
                     "median": round(statistics.median([x for x, _ in p["recent"]]), 2) if p["recent"] else None, "last": p["last"],
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
            "min_for_range": MIN_FOR_RANGE, "period": usual}


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
        dp.add_group_changes(c, [(ga, groups[ga]["name"], groups[ga]["name"], f"merged into {groups[gb]['code']}")], store._now(), kind="merged", who=who)
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
        into = groups[groups[hit]["merged_into"]]["code"]
        dp.set_merged(c, hit, None, None, None)
        dp.add_group_changes(c, [(hit, groups[hit]["name"], groups[hit]["name"], f"its merge into {into} undone")], store._now(), kind="unmerged", who=who)
    return {"unmerged": groups[hit]["code"], "was_in": into, "by": who or ""}
