"""Rate master access, drop-down resolution, upload template and bulk costing."""
import io
import os

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import engine
import rate_card

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_PATH = os.path.join(HERE, "data", "Rate_Master.xlsx")
LOG_PATH = os.path.join(HERE, "data", "costing_log.csv")

ROUTES = ["Yarn Dyed", "Piece Dyed", "RFD / Bleached", "Printed"]


def load():
    if not os.path.exists(MASTER_PATH):
        import build_masters
        build_masters.build()
    return pd.read_excel(MASTER_PATH, sheet_name=None)


def save(masters):
    with pd.ExcelWriter(MASTER_PATH, engine="openpyxl") as xw:
        for name, df in masters.items():
            df.to_excel(xw, sheet_name=name, index=False)
            xw.sheets[name].freeze_panes = "A2"


def setting(masters, name, default=None):
    s = masters["Settings"]
    hit = s[s["Setting"] == name]
    return hit["Value"].iloc[0] if len(hit) else default


def lists(masters):
    """Allowed values for every drop-down, taken from the rate tables."""
    up = masters["Weaving_Uplifts"]
    dc = masters["Dobby_Charges"]
    return {
        "Route": ROUTES,
        "Weave": masters["Weaves"]["Weave"].tolist(),
        "Pattern": up[up["Type"] == "Pattern"]["Value"].tolist(),
        "Loom type": up[up["Type"] == "Loom type"]["Value"].tolist(),
        "Finish": masters["Finishing_Rates"]["Finish"].tolist(),
        "Yarn": masters["Yarn_Rates"]["Yarn key"].tolist(),
        "Yarn shade": masters["Yarn_Dyeing"]["Shade"].tolist(),
        "Piece shade": ["Light", "Medium", "Dark"],
        "Mill tier": masters["Mill_Tier"]["Mill tier"].tolist(),
        "Order size": masters["Order_Slab"]["Order size"].tolist(),
        "Print method": masters["Print_Methods"]["Print method"].tolist(),
        "Dobby shafts": dc[dc["Type"] == "Dobby shafts"]["Value"].tolist(),
        "Top beam": dc[dc["Type"] == "Top beam"]["Value"].tolist(),
        "Weft (yarn dyed)": masters["Weft_Options"]["Weft (yarn dyed)"].tolist(),
        "Rate card quantity": masters["Quantity_Terms"]["Quantity band"].tolist(),
    }


def _blank(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""


def _num(v):
    return None if _blank(v) else float(v)


def resolve(sel, masters):
    """Turn drop-down choices into numeric engine inputs.

    Returns (inputs, rates_used). rates_used is a list of
    {item, choice, value, unit, basis} so every number can be traced.
    Raises ValueError naming the first choice that is not on a list.
    """
    L = lists(masters)
    used = []

    def pick(field, allowed, default=None):
        v = sel.get(field)
        if _blank(v):
            if default is None:
                raise ValueError(f"'{field}' is required")
            return default
        v = str(v).strip()
        if v not in allowed:
            raise ValueError(f"'{field}' value '{v}' is not on the list")
        return v

    def note(item, choice, value, unit, basis):
        used.append({"Item": item, "Choice": choice, "Value": value, "Unit": unit, "Basis": basis})

    route = pick("Route", L["Route"])
    weave = pick("Weave", L["Weave"])
    finish = pick("Finish", L["Finish"], "Normal")
    pattern = pick("Pattern", L["Pattern"], "Solid")
    loom = pick("Loom type", L["Loom type"], L["Loom type"][0])
    tier = pick("Mill tier", L["Mill tier"], L["Mill tier"][0])
    slab = pick("Order size", L["Order size"], L["Order size"][0])
    yd = route == "Yarn Dyed"
    warp_shade = pick("Warp yarn dyeing", L["Yarn shade"], "Medium" if yd else "Undyed")
    weft_shade = pick("Weft yarn dyeing", L["Yarn shade"], "Medium" if yd else "Undyed")
    piece_shade = pick("Piece shade", L["Piece shade"], "Medium")
    # Mill rate card choices. The first value on each list is the one that charges nothing.
    printed = route == "Printed"
    method = pick("Print method", L["Print method"], "Rotary" if printed else L["Print method"][0])
    shafts = pick("Dobby shafts", L["Dobby shafts"], L["Dobby shafts"][0])
    beam = pick("Top beam", L["Top beam"], L["Top beam"][0])
    weft_opt = pick("Weft (yarn dyed)", L["Weft (yarn dyed)"], L["Weft (yarn dyed)"][0])
    qband = pick("Rate card quantity", L["Rate card quantity"], rate_card.NO_QTY)
    labels = {}

    group = masters["Weaves"].set_index("Weave")["Weave group"][weave]
    inp = {"k": float(setting(masters, "Yarn weight constant K", engine.K_DEFAULT)),
           "shrinkage": float(setting(masters, "Finishing shrinkage", 0.04)),
           "weft_method": str(setting(masters, "Weft method", "Corrected"))}
    note("Finishing shrinkage", "Setting", inp["shrinkage"], "share", "Settings")

    for f in ("EPI", "PPI", "Finished width (in)"):
        if _num(sel.get(f)) is None or _num(sel.get(f)) <= 0:
            raise ValueError(f"'{f}' must be a number above zero")
    inp["epi"], inp["ppi"] = _num(sel["EPI"]), _num(sel["PPI"])
    inp["width_in"] = _num(sel["Finished width (in)"])
    reed = _num(sel.get("Reed space (in)"))
    if reed is None:
        factor = float(setting(masters, "Reed space factor", 1.155))
        reed = inp["width_in"] * factor
        note("Reed space", f"width x {factor}", round(reed, 2), "inch", "Settings")
    inp["reed_in"] = reed

    # Yarn
    yr = masters["Yarn_Rates"].set_index("Yarn key")
    for side in ("Warp", "Weft"):
        key = pick(f"{side} yarn", L["Yarn"])
        row = yr.loc[key]
        rate = _num(sel.get(f"{side} yarn price override"))
        basis = "Typed override"
        if rate is None:
            rate, basis = float(row["Rate Rs/kg"]), f"{row['Basis']}, {row['Rate date']}"
        count = _num(sel.get(f"{side} count override (Ne)")) or float(row["Count Ne (resultant)"])
        inp[f"{side.lower()}_rate"], inp[f"{side.lower()}_ne"] = rate, count
        note(f"{side} yarn", f"{key} (Ne {count:g})", rate, "Rs/kg", basis)

    # Yarn dyeing
    ydt = masters["Yarn_Dyeing"].set_index("Shade")
    for side, shade in (("warp", warp_shade), ("weft", weft_shade)):
        inp[f"{side}_dye"] = float(ydt.loc[shade, "Rs per kg yarn"])
        note(f"{side.capitalize()} yarn dyeing", shade, inp[f"{side}_dye"], "Rs/kg", ydt.loc[shade, "Basis"])
    if yd:      # dyed or undyed weft; anything but 'Dyed' takes the Rs per kg weft dyeing away
        wo = masters["Weft_Options"].set_index("Weft (yarn dyed)").loc[weft_opt]
        if str(wo["Rs per kg weft dyeing applies"]).strip().lower() != "yes":
            inp["weft_dye"] = 0.0
            used.pop()
            labels["weft_dye"] = f"{weft_opt}: no Rs per kg weft dyeing"
            note("Weft yarn dyeing", weft_opt, 0.0, "Rs/kg", wo["Basis"])
        inp["weft_dye_per_m"] = float(wo["Rs per metre"])
        if inp["weft_dye_per_m"]:
            labels["weft_dye_per_m"] = weft_opt
            note("Weft dyeing, flat charge", weft_opt, inp["weft_dye_per_m"], "Rs/m", wo["Basis"])

    # Weaving
    wr = masters["Weaving_Rates"]
    hit = wr[(wr["Weave group"] == group) & (wr["Route"] == route)]
    if hit.empty:
        raise ValueError(f"No weaving rate for {group} / {route}")
    rate = _num(sel.get("Weaving rate override (Rs/pick)"))
    basis = "Typed override"
    if rate is None:
        up = masters["Weaving_Uplifts"].set_index(["Type", "Value"])["Uplift % on weaving rate"]
        uplift = float(up[("Pattern", pattern)]) + float(up[("Loom type", loom)])
        rate = float(hit["Rs per pick"].iloc[0]) * (1 + uplift / 100)
        basis = hit["Basis"].iloc[0] + (f", +{uplift:g}% uplift" if uplift else "")
    inp["weaving_rate"] = rate
    note("Weaving", f"{weave} ({group}), {route}, {pattern}, {loom}", rate, "Rs/pick", basis)

    # Sizing
    sz = masters["Sizing_Rates"]
    sz = sz[sz["Route type"] == ("Yarn Dyed" if yd else "Other")].sort_values("Warp count up to (Ne)")
    band = sz[sz["Warp count up to (Ne)"] >= inp["warp_ne"]].iloc[0]
    inp["sizing_rate"] = float(band["Rs per kg warp"])
    note("Sizing", f"warp up to Ne {band['Warp count up to (Ne)']:g}", inp["sizing_rate"], "Rs/kg warp", band["Basis"])

    # Piece dyeing
    inp["piece_dye_rate"] = 0.0
    if not yd:
        pdn = masters["Piece_Dyeing"]
        shade = piece_shade if route == "Piece Dyed" else "Any"
        hit = pdn[(pdn["Route"] == route) & (pdn["Shade"] == shade)]
        if hit.empty:
            raise ValueError(f"No piece dyeing rate for {route} / {shade}")
        inp["piece_dye_rate"] = float(hit["Rs per kg greige"].iloc[0])
        item = "Preparation for print" if printed else "Piece dyeing"
        labels["piece_dye_name"] = item
        note(item, f"{route}, {shade}", inp["piece_dye_rate"], "Rs/kg greige", hit["Basis"].iloc[0])

    # Print method, Rs per metre. A printed fabric must have one; a print over yarn dyed cloth may.
    if printed and method == L["Print method"][0]:
        raise ValueError("'Print method' is required for a printed fabric")
    pm = masters["Print_Methods"].set_index("Print method").loc[method]
    inp["print_per_m"] = float(pm["Rs per metre"])
    if method != L["Print method"][0]:
        labels["print_per_m"] = method
        note("Print method", method, inp["print_per_m"], "Rs/m", pm["Basis"])

    # Dobby shafts and top beam, Rs per metre
    dch = masters["Dobby_Charges"].set_index(["Type", "Value"])
    for field, choice, key in (("Dobby shafts", shafts, "dobby_shaft_per_m"), ("Top beam", beam, "top_beam_per_m")):
        if choice != L[field][0] and group != "Dobby/Matt":
            raise ValueError(f"'{field}' applies to dobby weaves only; leave it blank for {weave}")
        inp[key] = float(dch.loc[(field, choice), "Rs per metre"])
        if choice != L[field][0]:
            labels[key] = choice
            note(field, choice, inp[key], "Rs/m", dch.loc[(field, choice), "Basis"])

    # Finishing
    fr = masters["Finishing_Rates"].set_index("Finish")
    col = "Rs per kg greige (yarn dyed)" if yd else "Rs per kg greige (piece dyed / RFD / printed)"
    inp["finishing_rate"] = float(fr.loc[finish, col])
    note("Finishing", finish, inp["finishing_rate"], "Rs/kg greige", fr.loc[finish, "Basis"])
    inp["finish_upcharge_per_m"] = _num(fr.loc[finish].get(rate_card.FIN_UP)) or 0.0
    if inp["finish_upcharge_per_m"]:
        labels["finish_upcharge_per_m"] = finish
        note("Finish upcharge", finish, inp["finish_upcharge_per_m"], "Rs/m", fr.loc[finish, "Basis"])

    # Class defaults
    cd = masters["Class_Defaults"]
    hit = cd[(cd["Weave group"] == group) & (cd["Route"] == route)]
    if hit.empty:
        hit = cd[cd["Weave group"] == "Default"]
    row = hit.iloc[0]
    label = f"{row['Weave group']} / {row['Route']}"
    for key, colname in (("warp_crimp", "Warp crimp"), ("warp_wastage", "Warp wastage"),
                         ("weft_crimp", "Weft crimp (old method only)"), ("weft_wastage", "Weft wastage"),
                         ("process_wastage", "Process wastage"), ("overhead", "Overhead"), ("margin", "Margin")):
        inp[key] = float(row[colname])
    note("Crimp, wastage, overhead, margin", label,
         f"wastage {inp['process_wastage']:.1%}, overhead {inp['overhead']:.1%}, margin {inp['margin']:.1%}",
         "", row["Basis"])

    # Mill tier and order size
    mt = masters["Mill_Tier"].set_index("Mill tier").loc[tier]
    sl = masters["Order_Slab"].set_index("Order size").loc[slab]
    # Quantity: a rate card band and the order size slab price the same thing, so by default only
    # one is charged. See rate_card.QTY_SETTING.
    slab_pts = float(sl["Overhead add (points)"])
    stack = str(setting(masters, rate_card.QTY_SETTING, "Replaced")).strip().lower() == "added"
    slab_used = qband == rate_card.NO_QTY or stack
    oh_add = float(mt["Overhead add (points)"]) + (slab_pts if slab_used else 0.0)
    m_add = float(mt["Margin add (points)"])
    inp["overhead"] += oh_add / 100
    inp["margin"] += m_add / 100
    note("Mill tier", tier, f"overhead +{float(mt['Overhead add (points)']):g}, margin +{m_add:g}", "points", mt["Basis"])
    if slab_used:
        note("Order size", slab, f"overhead +{slab_pts:g}", "points", sl["Basis"])
    else:
        note("Order size", slab, "not applied: the rate card quantity band is used instead", "", "Settings")
    if qband != rate_card.NO_QTY:
        qt = masters["Quantity_Terms"].set_index("Quantity band").loc[qband]
        pct, disc = float(qt["Small-lot upcharge %"]), float(qt["Volume discount Rs per metre"])
        if pct and not yd:
            raise ValueError(f"'Rate card quantity' {qband}: the rate card has small-lot terms for yarn dyed "
                             "fabrics only. Leave it blank and use 'Order size'")
        counts = masters["Yarn_Rates"].set_index("Yarn key")["Count"].astype(str).str.strip().str.lower()
        if disc and all(counts[str(sel[f"{s} yarn"]).strip()] == "40s" for s in ("Warp", "Weft")):
            disc = 0.0      # the card: volume discount is not applicable for 40s quality
            labels["volume_discount_per_m"] = f"{qband}: no discount for 40s quality"
            note("Volume discount", qband, 0.0, "Rs/m", f"{qt['Basis']}: not applicable for 40s quality")
        inp["small_lot_pct"], inp["volume_discount_per_m"] = pct / 100, disc
        labels["small_lot_pct"] = qband if pct else f"{qband}: none"
        labels.setdefault("volume_discount_per_m", qband if disc else f"{qband}: none")
        if pct:
            note("Small-lot upcharge", qband, pct, "% of price", qt["Basis"])
        if disc:
            note("Volume discount", qband, disc, "Rs/m", qt["Basis"])
    inp["labels"] = labels

    inp["extra_per_m"] = _num(sel.get("Extra charge (Rs/m)")) or 0.0
    return inp, used


def cost(sel, masters):
    inp, used = resolve(sel, masters)
    res = engine.compute(inp)
    res["rates_used"] = used
    res["inputs"] = inp
    quote = _num(sel.get("Quoted price (Rs/m)"))
    res["quote"] = quote
    res["gap"] = None if quote is None else quote - res["total_per_m"]
    res["gap_pct"] = None if quote is None else quote / res["total_per_m"] - 1
    res["placeholders"] = [u["Item"] for u in used if str(u["Basis"]).startswith("Placeholder")]
    return res


# ---------------------------------------------------------------- upload template
TEMPLATE_COLUMNS = [  # (column, list name or None, required)
    ("Fabric code", None, True), ("Description", None, False), ("Supplier", None, False),
    ("Route", "Route", True), ("Weave", "Weave", True), ("Pattern", "Pattern", False),
    ("Finish", "Finish", False), ("Warp yarn", "Yarn", True), ("Weft yarn", "Yarn", True),
    ("Warp yarn dyeing", "Yarn shade", False), ("Weft yarn dyeing", "Yarn shade", False),
    ("Piece shade", "Piece shade", False), ("EPI", None, True), ("PPI", None, True),
    ("Finished width (in)", None, True), ("Reed space (in)", None, False),
    ("Loom type", "Loom type", False), ("Mill tier", "Mill tier", False), ("Order size", "Order size", False),
    ("Print method", "Print method", False), ("Dobby shafts", "Dobby shafts", False), ("Top beam", "Top beam", False),
    ("Weft (yarn dyed)", "Weft (yarn dyed)", False), ("Rate card quantity", "Rate card quantity", False),
    ("Quoted price (Rs/m)", None, False), ("Warp yarn price override", None, False),
    ("Weft yarn price override", None, False), ("Weaving rate override (Rs/pick)", None, False),
    ("Extra charge (Rs/m)", None, False),
]
EXAMPLE_ROW = {"Fabric code": "Qlty-1", "Description": "100% Cotton 40x40 / 132x84 Dobby YD shirting",
               "Route": "Yarn Dyed", "Weave": "Dobby", "Pattern": "Check", "Finish": "Normal",
               "Warp yarn": "Cotton 40S", "Weft yarn": "Cotton 40S", "Warp yarn dyeing": "Medium",
               "Weft yarn dyeing": "Medium", "EPI": 132, "PPI": 84, "Finished width (in)": 58,
               "Reed space (in)": 67}


def make_template(masters):
    """Excel upload template whose drop-downs match the current rate master."""
    L = lists(masters)
    wb = Workbook()
    ws = wb.active
    ws.title = "Fabrics"
    ls = wb.create_sheet("Lists")
    list_cols = {}
    for i, (name, values) in enumerate(L.items(), start=1):
        ls.cell(row=1, column=i, value=name).font = Font(bold=True)
        for r, v in enumerate(values, start=2):
            ls.cell(row=r, column=i, value=v)
        letter = get_column_letter(i)
        list_cols[name] = f"=Lists!${letter}$2:${letter}${len(values) + 1}"
        ls.column_dimensions[letter].width = 28
    req_fill = PatternFill("solid", fgColor="5B4FC7")
    opt_fill = PatternFill("solid", fgColor="A7A1E6")
    for c, (col, lst, required) in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = req_fill if required else opt_fill
        letter = get_column_letter(c)
        ws.column_dimensions[letter].width = max(14, len(col) + 2)
        if lst:
            dv = DataValidation(type="list", formula1=list_cols[lst], allow_blank=not required)
            dv.error = "Pick a value from the list"
            dv.showErrorMessage = True
            ws.add_data_validation(dv)
            dv.add(f"{letter}2:{letter}2000")
        if col in EXAMPLE_ROW:
            ws.cell(row=2, column=c, value=EXAMPLE_ROW[col])
    ws.freeze_panes = "B2"
    notes = wb.create_sheet("Read me")
    for r, t in enumerate([
        "One row per fabric. Dark purple columns are required; light purple are optional.",
        "Columns with a drop-down accept only values from the Lists sheet.",
        "Yarn dyeing shades default to Medium for yarn dyed fabrics and Undyed for the rest.",
        "Leave reed space blank to use finished width x the reed space factor in Settings.",
        "Mill rate card columns are optional. Left blank: no dobby or top beam charge, weft dyed, rotary for a "
        "printed fabric, and the order size slab for quantity.",
        "Print method is required in effect only for printed fabrics; it can also be set for a print over yarn dyed cloth.",
        "Dobby shafts and Top beam are for dobby weaves only. Weft (yarn dyed) is read only for yarn dyed fabrics.",
        "Rate card quantity, when filled, takes the place of Order size, so quantity is never charged twice. "
        "Bands below 800 m are for yarn dyed fabrics only.",
        "Row 2 is an example (Qlty-1). Overwrite or delete it.",
        "Download a fresh template after changing lists in the tool, so the drop-downs match.",
    ], start=1):
        notes.cell(row=r, column=1, value=t)
    notes.column_dimensions["A"].width = 100
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def cost_many(df, masters):
    """Cost every row of an uploaded sheet. Bad rows get an Error, not a cost."""
    out = []
    names = ["Yarn", "Yarn dyeing", "Sizing and weaving", "Dyeing and finishing", "Losses", "Overhead",
             "Margin", engine.UPCHARGE_BUCKET]
    for _, row in df.iterrows():
        sel = row.to_dict()
        rec = {"Fabric code": sel.get("Fabric code"), "Description": sel.get("Description"),
               "Supplier": sel.get("Supplier")}
        try:
            r = cost(sel, masters)
            rec["Should-cost Rs/m"] = round(r["total_per_m"], 2)
            rec["Should-cost Rs/kg"] = round(r["per_kg"], 1)
            rec["GSM"] = round(r["gsm"], 1)
            for b in r["buckets"]:
                rec[f"{b['name']} Rs/m"] = round(b["amount"], 2)
            rec["Quoted Rs/m"] = r["quote"]
            rec["Gap Rs/m"] = None if r["gap"] is None else round(r["gap"], 2)
            rec["Gap %"] = None if r["gap_pct"] is None else round(r["gap_pct"] * 100, 1)
            rec["Placeholder rates used"] = ", ".join(r["placeholders"])
            rec["Error"] = ""
        except Exception as e:
            for n in names:
                rec[f"{n} Rs/m"] = None
            rec["Error"] = str(e)
        out.append(rec)
    return pd.DataFrame(out)
