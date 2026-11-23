"""Rate master access, drop-down resolution, upload template and bulk costing."""
import io
import os

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_PATH = os.path.join(HERE, "data", "Rate_Master.xlsx")
LOG_PATH = os.path.join(HERE, "data", "costing_log.csv")

ROUTES = ["Yarn Dyed", "Piece Dyed", "RFD / Bleached", "Printed"]


def load():
    if not os.path.exists(MASTER_PATH):
        import build_masters
        build_masters.build()
    return upgrade(pd.read_excel(MASTER_PATH, sheet_name=None))


CARD_SHEETS = ["Print_Method", "Dobby_Upcharge", "Weft_Upcharge", "Order_Quantity"]
TOP_BEAM = ["No", "Yes"]
DISCOUNT = ["Applies", "Not applicable (split delivery or EOSS)"]


def upgrade(masters):
    """Add the mill rate card tables to a rate master that predates them.

    Only adds: new sheets, two upcharge columns on Finishing_Rates and the card's
    finishes that were not on the list. No existing rate is touched.
    """
    import build_masters as bm
    m = dict(masters)
    for name in CARD_SHEETS:
        if name not in m:
            m[name] = bm.SHEETS[name]()
    fr = m["Finishing_Rates"]
    if "Upcharge Rs per m" not in fr.columns:
        fr = fr.copy()
        fr["Upcharge Rs per m"] = 0.0
        fr["Upcharge basis"] = bm.NS
        new = bm.card_finishes()
        m["Finishing_Rates"] = pd.concat([fr, new[~new["Finish"].isin(fr["Finish"])]], ignore_index=True)
    return m


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
        "Print method": masters["Print_Method"]["Print method"].tolist(),
        "Dobby shafts": masters["Dobby_Upcharge"]["Dobby shafts"].tolist(),
        "Top beam": TOP_BEAM,
        "Weft": masters["Weft_Upcharge"]["Weft"].tolist(),
        "Order quantity": masters["Order_Quantity"]["Order quantity"].tolist(),
        "Volume discount": DISCOUNT,
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
    method = pick("Print method", L["Print method"], L["Print method"][0])
    shafts = pick("Dobby shafts", L["Dobby shafts"], L["Dobby shafts"][0])
    top_beam = pick("Top beam", L["Top beam"], "No")
    weft_mode = pick("Weft", L["Weft"], L["Weft"][0])
    quantity = pick("Order quantity", L["Order quantity"], L["Order quantity"][0])
    discount_ok = pick("Volume discount", L["Volume discount"], DISCOUNT[0]) == DISCOUNT[0]
    ups = []

    def upcharge(name, choice, rs, basis):
        note(name, choice, rs, "Rs/m", basis)
        if rs:
            ups.append({"name": name, "basis": f"{choice}, {basis}", "amount": rs})

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

    # Yarn dyeing. For a yarn-dyed fabric the weft can be costed by shade (per kg), left undyed,
    # or taken as the rate card's Rs per metre.
    wu = masters["Weft_Upcharge"].set_index("Weft").loc[weft_mode]
    weft_by_card = yd and weft_mode != L["Weft"][0]
    if weft_by_card:
        weft_shade = "Undyed"
    ydt = masters["Yarn_Dyeing"].set_index("Shade")
    for side, shade in (("warp", warp_shade), ("weft", weft_shade)):
        inp[f"{side}_dye"] = float(ydt.loc[shade, "Rs per kg yarn"])
        note(f"{side.capitalize()} yarn dyeing", shade, inp[f"{side}_dye"], "Rs/kg", ydt.loc[shade, "Basis"])
    if weft_by_card:
        upcharge("Dyed weft", weft_mode, float(wu["Rs per m"]), wu["Basis"])

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

    if group == "Dobby/Matt":
        du = masters["Dobby_Upcharge"].set_index("Dobby shafts").loc[shafts]
        col = "Rs per m with top beam" if top_beam == "Yes" else "Rs per m"
        upcharge("Dobby shafts and top beam", f"{shafts}, top beam: {top_beam}", float(du[col]), du["Basis"])

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
        pm = masters["Print_Method"].set_index("Print method").loc[method]
        by_method = route == "Printed" and method != L["Print method"][0]
        # a print method from the rate card: cloth prepared as RFD, printing added per metre
        hit = pdn[(pdn["Route"] == ("RFD / Bleached" if by_method else route)) & (pdn["Shade"] == shade)]
        if hit.empty:
            raise ValueError(f"No piece dyeing rate for {route} / {shade}")
        inp["piece_dye_rate"] = float(hit["Rs per kg greige"].iloc[0])
        note("Preparation for print" if by_method else "Piece dyeing", f"{route}, {shade}",
             inp["piece_dye_rate"], "Rs/kg greige", hit["Basis"].iloc[0])
        if by_method:
            upcharge("Printing", method, float(pm["Rs per m"]), pm["Basis"])

    # Finishing
    fr = masters["Finishing_Rates"].set_index("Finish")
    col = "Rs per kg greige (yarn dyed)" if yd else "Rs per kg greige (piece dyed / RFD / printed)"
    inp["finishing_rate"] = float(fr.loc[finish, col])
    note("Finishing", finish, inp["finishing_rate"], "Rs/kg greige", fr.loc[finish, "Basis"])
    fin_up = _num(fr.loc[finish, "Upcharge Rs per m"]) or 0.0
    if fin_up:
        upcharge("Finish upcharge", finish, fin_up, fr.loc[finish, "Upcharge basis"])

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
    oh_add = float(mt["Overhead add (points)"]) + float(sl["Overhead add (points)"])
    m_add = float(mt["Margin add (points)"])
    inp["overhead"] += oh_add / 100
    inp["margin"] += m_add / 100
    note("Mill tier", tier, f"overhead +{float(mt['Overhead add (points)']):g}, margin +{m_add:g}", "points", mt["Basis"])
    note("Order size", slab, f"overhead +{float(sl['Overhead add (points)']):g}", "points", sl["Basis"])

    # Order quantity: small-lot step (yarn dyed only on the card) and volume discount
    oq = masters["Order_Quantity"].set_index("Order quantity").loc[quantity]
    pct = float(oq["Small-lot upcharge % (yarn dyed)"]) if yd else 0.0
    disc = float(oq["Volume discount Rs per m"])
    why = ""
    if disc and not discount_ok:
        disc, why = 0.0, ", no discount: split delivery or EOSS"
    elif disc and inp["warp_ne"] == 40 and inp["weft_ne"] == 40:
        disc, why = 0.0, ", no discount: 40s quality"
    inp["small_lot_pct"], inp["volume_discount"] = pct / 100, disc
    note("Order quantity", quantity, f"small lot +{pct:g}%, discount Rs {disc:g}/m{why}", "", oq["Basis"])
    inp["upcharges"] = ups

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
    ("Print method", "Print method", False), ("Dobby shafts", "Dobby shafts", False),
    ("Top beam", "Top beam", False), ("Weft", "Weft", False), ("Order quantity", "Order quantity", False),
    ("Volume discount", "Volume discount", False),
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
        "Print method applies to printed fabrics, Dobby shafts and Top beam to dobby weaves, Weft to yarn dyed fabrics.",
        "Order quantity sets the small-lot step (yarn dyed) and the volume discount (not given on 40s x 40s).",
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
    names = [b for b in ("Yarn", "Yarn dyeing", "Sizing and weaving", "Dyeing and finishing",
                         "Losses", "Overhead", "Margin", "Mill upcharges")]
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
