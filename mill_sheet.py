"""The mill's own price sheet (the 'AS Sweetan' layout): read it, cost each row, check its sums.

A mill prices a fabric as a base price for a standard construction plus upcharges:
    Price = Base Price + EPI Upch + PPI Upch + Finish Upch + Dobby Upch
            + Upcharge/Print/Mcount + Double beam
    EPI Upch = (Actual EPI - Std EPI) x rate per end,  PPI Upch likewise per pick
    Total = Price + upcharge for a small quantity - discount above 2,000 m
This module turns such a row into the choices RightPrice costs from, so the mill's price can sit
beside the should-cost, and it checks that the mill's own arithmetic adds up.

Nothing here is a costing rate. PER_END and PER_PICK are the mill rate card's figures
(docs/Mill_Rate_Card.md, section 1) and are used only to check the sheet.
"""
import math
import re

import pandas as pd

import yarn_seed

# The 41 headings, in the mill's order. The list page shows these, then RightPrice's own columns.
COLUMNS = ["Brand", "Fab Code", "YD/NYD", "Material Type", "Warp", "Weft", "EPI", "PPI", "Variety", "Weave", "F.W.",
           "Finish", "Sort", "Shaft", "Quality comment", "Sales order No", "Order Issue Date", "Status", "Arvind Ref",
           "Total order qnty", "Del Date", "Rahul's comment", "Base Price", "Std EPI", "Std PPI", "Actual EPI",
           "Actual PPI", "Diff EPI", "Diff PPI", "EPI Upch", "PPI Upch", "Finish Upch", "Dobby Upch",
           "Upcharge/Print/Mcount", "Double beam", "Price", "Upcharge for less qnty", "Discoun>2000 mts",
           "Total price with qnty disc/upcharge", "Ex mill price", "C2FO @2.84%"]
GROUPS = {"Fabric": COLUMNS[:15], "Order": COLUMNS[15:22], "Mill's price build-up": COLUMNS[22:]}
PER_END, PER_PICK, PER_PICK_ABOVE_90 = 0.60, 0.90, 1.00
C2FO = 1.0284
QUANTITY_BANDS = [(500, 600, "500 to 599 m"), (600, 700, "600 to 699 m"), (700, 800, "700 to 799 m"),
                  (800, 2000, "800 to 1,999 m"), (2000, 4000, "2,000 to 3,999 m"),
                  (4000, 6000.5, "4,000 to 6,000 m"), (6000.5, 1e12, "Above 6,000 m")]


def is_mill_sheet(df):
    return {"Fab Code", "Base Price", "EPI", "PPI"} <= {str(c).strip() for c in df.columns}


def _blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() == "" or v is pd.NaT


def _num(v):
    try:
        return None if _blank(v) else float(v)
    except (TypeError, ValueError):
        return None


def clean_row(row):
    """A sheet row as plain values JSON can hold, keyed by the 41 headings."""
    out = {}
    for c in COLUMNS:
        v = row.get(c)
        if _blank(v):
            continue
        if hasattr(v, "isoformat"):
            v = v.isoformat()[:10]
        elif hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float) and v == int(v):
            v = int(v)
        out[c] = v if isinstance(v, (int, float)) else str(v).strip()
    return out


def _yarn(text, yarns):
    """'40', '40s', '2/80', '40+2/80 (98/2)' -> (yarn key, note). The first count is the main yarn."""
    t = str(text).strip().lower()
    main, note = re.split(r"\+", t)[0], ""
    if "+" in t:
        note = f"warp or weft '{text}' is costed on its main yarn only; the second yarn is not in the should-cost"
    main = re.sub(r"\(.*?\)", "", main).strip().replace(" ", "")
    main = re.sub(r"(s|ne|'s)$", "", re.sub(r"^(cm|cpt|cw|ne)", "", main))
    main = re.sub(r"^(\d+)/1$", r"\1", main)
    ply = re.fullmatch(r"2/(\d+)", main) or re.fullmatch(r"(\d+)/2", main)
    want = f"2/{ply.group(1)}" if ply else (main + "s" if re.fullmatch(r"\d+(\.0)?", main) else None)
    if want:
        want = want.replace(".0s", "s")
        for _, y in yarns.iterrows():
            if str(y["Blend"]) == "Cotton" and str(y["Count"]).strip().lower() in (want, want.replace("2/", "") + "/2"):
                return y["Yarn key"], note
    return None, f"yarn count '{text}' is not in the yarn master"


def _weave(text, weaves):
    t = str(text).strip().lower()
    for pat, name in ((r"2\s*/\s*1", "Twill-2/1"), (r"2\s*/\s*2", "Twill-2/2"), (r"3\s*/\s*1", "Twill-3/1"),
                      (r"plain|poplin|1\s*/\s*1", "Plain"), (r"oxford", "Oxford"), (r"dobby", "Dobby"),
                      (r"satin|sateen", "Satin"), (r"herring|hbt", "Herringbone"), (r"twill", "Twill-2/1"),
                      (r"matt", "Matt 2/2")):
        if re.search(pat, t) and name in weaves:
            return name
    exact = {w.lower(): w for w in weaves}
    return exact.get(t)


def _finish(text, finishes):
    norm = lambda s: re.sub(r"[^a-z0-9+]", "", str(s).lower()).lstrip("f")
    by = {norm(f): f for f in finishes}
    by.update({"regular": "Normal", "normal": "Normal", "eti": "F- ETI Easy to Iron", "la": "F- LA Liquid Ammonia",
               "easycare": "F- Easy Care", "peach": "F- PEACH", "la+eti": "F- LA + ETI"})
    hit = by.get(norm(text))
    return hit if hit in finishes else None


def to_inputs(row, m):
    """(choices for masters.cost, problems that stop it being costed, notes). row: one sheet row as a dict."""
    L_weaves = m["Weaves"]["Weave"].tolist()
    finishes = m["Finishing_Rates"]["Finish"].tolist()
    group = m["Weaves"].set_index("Weave")["Weave group"]
    sel, problems, notes = {}, [], []
    sel["Fabric code"] = "" if _blank(row.get("Fab Code")) else str(row.get("Fab Code")).strip()
    sel["Description"] = " ".join(str(row.get(c)).strip() for c in ("Brand", "Material Type", "Variety", "Weave")
                                  if not _blank(row.get(c)))
    if not _blank(row.get("Arvind Ref")):
        sel["Supplier"] = "Arvind"

    kind = "" if _blank(row.get("YD/NYD")) else str(row.get("YD/NYD")).strip().upper()
    if kind == "YD":
        sel["Route"] = "Yarn Dyed"
    elif kind == "NYD":
        problems.append("not yarn dyed (NYD on the sheet), and the sheet does not say how it is coloured: open it in Cost a fabric and choose piece dyed, printed or bleached")
    else:
        problems.append("YD/NYD is blank")

    content = "" if _blank(row.get("Material Type")) else re.sub(r"\s+", "", str(row.get("Material Type")).lower())
    if content in ("100%cotton", "cotton"):
        sel["Content"] = list(yarn_seed.CONTENTS)[0]
    else:
        problems.append(f"material '{row.get('Material Type')}' is not covered yet (100% cotton only from a mill sheet)")

    for side in ("Warp", "Weft"):
        if _blank(row.get(side)):
            problems.append(f"{side} count is blank")
            continue
        key, note = _yarn(row.get(side), m["Yarn_Rates"])
        if key:
            sel[f"{side} yarn"] = key
            if note:
                notes.append(note)
        else:
            problems.append(note)

    for name in ("EPI", "PPI"):
        v = _num(row.get(name))
        if v and v > 0:
            sel[name] = v
        else:
            problems.append(f"{name} is blank")
    w = _num(row.get("F.W."))
    if w and w > 0:
        sel["Finished width (in)"] = round(w / 2.54, 1) if w > 100 else w      # the mill writes width in cm
    else:
        problems.append("F.W. (finished width) is blank")

    weave = None if _blank(row.get("Weave")) else _weave(row.get("Weave"), L_weaves)
    if weave:
        sel["Weave"] = weave
    else:
        problems.append(f"weave '{row.get('Weave')}' is not recognised")
    variety = "" if _blank(row.get("Variety")) else str(row.get("Variety")).upper()
    sel["Pattern"] = "Check" if variety.endswith("C") else ("Stripe" if variety.endswith("S") else "Solid")

    if _blank(row.get("Finish")):
        sel["Finish"] = "Normal"
    else:
        f = _finish(row.get("Finish"), finishes)
        sel["Finish"] = f or "Normal"
        if not f:
            notes.append(f"finish '{row.get('Finish')}' is not recognised; costed as Normal")

    if weave and group.get(weave) == "Dobby/Matt":
        shafts = _num(row.get("Shaft"))
        if shafts:
            sel["Dobby shafts"] = "Up to 8" if shafts <= 8 else ("9 to 12" if shafts <= 12 else "13 and above")
        if (_num(row.get("Double beam")) or 0) > 0:
            sel["Top beam"] = "Yes"

    qty = _num(row.get("Total order qnty"))
    if qty:
        floor = 500 if sel.get("Route") == "Yarn Dyed" else 1000
        if qty >= floor:
            sel["Rate card quantity"] = next(name for lo, hi, name in QUANTITY_BANDS if lo <= qty < hi)
            if qty < 800 and not (_num(row.get("Upcharge for less qnty")) or 0):
                # the mill's sheet charges nothing for the small lot: the should-cost must not add it either
                sel["Rate card quantity"] = "800 to 1,999 m"
                notes.append(f"the mill charges no small-lot upcharge on {qty:g} m, so the should-cost leaves it out too")
        sel["Order size"] = "Below 1,000 m" if qty < 1000 else ("1,000 to 3,000 m" if qty < 3000 else "3,000 m and above")

    price = _num(row.get("Ex mill price")) or _num(row.get("Total price with qnty disc/upcharge")) or _num(row.get("Price"))
    if price:
        sel["Quoted price (Rs/m)"] = price
    return sel, problems, notes


def check_sums(row):
    """Does the mill's own arithmetic add up? Returns a list of what does not (empty = it does)."""
    n = lambda c: _num(row.get(c))
    z = lambda c: n(c) or 0.0
    off = []
    if n("Base Price") is None or n("Price") is None:
        return ["no base price or price to check"]
    for name in ("EPI", "PPI"):
        if n(f"Actual {name}") is not None and n(f"Std {name}") is not None and n(f"Diff {name}") is not None \
                and abs(n(f"Actual {name}") - n(f"Std {name}") - n(f"Diff {name}")) > 0.01:
            off.append(f"Diff {name} is {n(f'Diff {name}'):g}, but Actual - Std is {n(f'Actual {name}') - n(f'Std {name}'):g}")
        if n(name) is not None and n(f"Actual {name}") is not None and abs(n(name) - n(f"Actual {name}")) > 0.01:
            off.append(f"{name} {n(name):g} differs from Actual {name} {n(f'Actual {name}'):g}")
    if n("Diff EPI") is not None and n("EPI Upch") is not None and abs(n("Diff EPI") * PER_END - n("EPI Upch")) > 0.011:
        off.append(f"EPI Upch {n('EPI Upch'):g} is not {n('Diff EPI'):g} ends x Rs {PER_END:.2f} = {n('Diff EPI') * PER_END:.2f}")
    if n("Diff PPI") is not None and n("PPI Upch") is not None:
        ok = [n("Diff PPI") * r for r in (PER_PICK, PER_PICK_ABOVE_90)]
        if all(abs(v - n("PPI Upch")) > 0.011 for v in ok):
            off.append(f"PPI Upch {n('PPI Upch'):g} is not {n('Diff PPI'):g} picks x Rs {PER_PICK:.2f} = {ok[0]:.2f}")
    build = z("Base Price") + z("EPI Upch") + z("PPI Upch") + z("Finish Upch") + z("Dobby Upch") \
        + z("Upcharge/Print/Mcount") + z("Double beam")
    if abs(build - n("Price")) > 0.011:
        off.append(f"Price {n('Price'):g} is not base plus upcharges = {build:.2f}")
    if n("Total price with qnty disc/upcharge") is not None:
        total = n("Price") + z("Upcharge for less qnty") - z("Discoun>2000 mts")
        if abs(total - n("Total price with qnty disc/upcharge")) > 0.011:
            off.append(f"Total {n('Total price with qnty disc/upcharge'):g} is not price plus quantity terms = {total:.2f}")
    if n("Ex mill price") is not None and n("C2FO @2.84%") is not None and abs(n("Ex mill price") * C2FO - n("C2FO @2.84%")) > 0.011:
        off.append(f"C2FO {n('C2FO @2.84%'):g} is not ex-mill x {C2FO} = {n('Ex mill price') * C2FO:.2f}")
    return off


def own_sums(row):
    """The ex-mill price the mill's own sheet gives when its sums are done again: base price, plus the
    differences in ends and picks at the card's rates, plus the other upcharges, plus or minus the
    quantity terms. (price by the sums, rupees per metre the stated ex-mill price is above it), or
    (None, None) when the row has no base price or ex-mill price."""
    n = lambda c: _num(row.get(c))
    z = lambda c: n(c) or 0.0
    stated = n("Ex mill price") if n("Ex mill price") is not None else n("Total price with qnty disc/upcharge")
    if n("Base Price") is None or stated is None:
        return None, None
    d_epi = n("Diff EPI") if n("Diff EPI") is not None else (z("Actual EPI") - z("Std EPI") if n("Std EPI") is not None else None)
    d_ppi = n("Diff PPI") if n("Diff PPI") is not None else (z("Actual PPI") - z("Std PPI") if n("Std PPI") is not None else None)
    epi_u = z("EPI Upch") if d_epi is None else d_epi * PER_END
    if d_ppi is None:
        ppi_u = z("PPI Upch")
    else:       # the card charges Rs 1.00 a pick above 90 picks; take whichever rate the sheet is nearer to
        ppi_u = min((d_ppi * r for r in (PER_PICK, PER_PICK_ABOVE_90)), key=lambda v: abs(v - z("PPI Upch")))
    price = z("Base Price") + epi_u + ppi_u + z("Finish Upch") + z("Dobby Upch") + z("Upcharge/Print/Mcount") + z("Double beam")
    price += z("Upcharge for less qnty") - z("Discoun>2000 mts")
    price = round(price, 2)
    return price, round(stated - price, 2)


def from_choices(sel):
    """A fabric costed on screen, shown under the mill's headings as far as the choices go."""
    route = sel.get("Route")
    w = _num(sel.get("Finished width (in)"))
    out = {"Fab Code": sel.get("Fabric code"), "YD/NYD": "YD" if route == "Yarn Dyed" else ("NYD" if route else None),
           "Material Type": sel.get("Content"), "Warp": sel.get("Warp yarn"), "Weft": sel.get("Weft yarn"),
           "EPI": sel.get("EPI"), "PPI": sel.get("PPI"), "Variety": route, "Weave": sel.get("Weave"),
           "F.W.": round(w * 2.54) if w else None, "Finish": sel.get("Finish"),
           "Ex mill price": sel.get("Quoted price (Rs/m)")}
    return {k: v for k, v in out.items() if not _blank(v)}
