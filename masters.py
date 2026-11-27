"""Rate master access, drop-down resolution, upload template and bulk costing."""
import io
import os
import re

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import engine
import rate_card
import store
import yarn_seed

HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED_MASTER = os.path.join(HERE, "data", "Rate_Master.xlsx")
# On a server, set RIGHTPRICE_DATA to a folder that survives redeploys (Azure: /home/rightprice-data).
# Unset, everything stays in the project's own data folder, as on a laptop. With DATABASE_URL set, what is
# kept goes to the database instead (store.py); these paths are then only where the files were copied in from.
DATA_DIR = store.data_dir()
MASTER_PATH = os.path.join(DATA_DIR, "Rate_Master.xlsx")
LOG_PATH = os.path.join(DATA_DIR, "costing_log.csv")

ROUTES = ["Yarn Dyed", "Piece Dyed", "RFD / Bleached", "Printed"]


def load():
    """The rate master in use, as its tables, from the store (the file, or the database's latest version)."""
    s = store.get()
    data = s.read_rates()
    if data is None:
        # first start: begin from the rate master that came with the code
        if not os.path.exists(SHIPPED_MASTER):
            import build_masters
            build_masters.build()
        with open(SHIPPED_MASTER, "rb") as f:
            data = f.read()
        if s.kind != "files" or MASTER_PATH != SHIPPED_MASTER:
            s.write_rates(data, reason="Begun from the rate master that came with the code")
    m = pd.read_excel(io.BytesIO(data), sheet_name=None)
    return _add_missing_tables(m)


def _add_missing_tables(m):
    """Bring an older rate master up to date, once: the mill rate card tables, then the blend yarns.

    A server keeps its own rate master, which a new version of the code does not replace. The
    rate card tables are added to it here; every other rate, and every edit made in the app,
    stays as it is. A dated copy is kept first (a file beside it, or the earlier version in the database).
    """
    import mill_sheet
    card = rate_card.apply(m)
    log = card + yarn_seed.apply(m)       # placeholder yarns for poly cotton and linen, added once
    terms = mill_sheet.apply(m)           # per-mill sheet terms, moved from the code
    log += terms
    if log:
        import datetime as dt
        what = "rate card" if card else ("mill sheet terms" if terms else "blend yarns")
        kept = save(m, reason="Brought up to date: " + "; ".join(log), backup=f" before {what} {dt.datetime.now():%Y%m%d-%H%M}")
        print("Rate master brought up to date:", "; ".join(log), "| Backup:", kept)
    return m


def workbook(masters):
    """The rate master as the bytes of an Excel workbook."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in masters.items():
            df.to_excel(xw, sheet_name=name, index=False)
            xw.sheets[name].freeze_panes = "A2"
    return buf.getvalue()


def save(masters, reason="Rate master saved", who="", backup=None, backup_if_absent=False):
    """Save the rate master through the store. `backup` keeps a dated copy of what was there first (see
    store.FileStore.write_rates); in a database every version is kept anyway. Returns where the copy is."""
    return store.get().write_rates(workbook(masters), reason=reason, who=who, backup=backup, backup_if_absent=backup_if_absent)


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
        "Count system": list(engine.COUNT_SYSTEMS),
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


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_of(on):
    """The month a date falls in, as 'YYYY-MM': from a date, a 'YYYY-MM-DD' or a 'YYYY-MM'. ValueError otherwise."""
    if hasattr(on, "year") and hasattr(on, "month"):
        return f"{on.year:04d}-{on.month:02d}"
    s = str(on).strip()[:10]
    hit = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", s)
    if not hit or not 1 <= int(hit.group(2)) <= 12:
        raise ValueError(f"'{on}' is not a date (give YYYY-MM-DD or YYYY-MM)")
    return f"{hit.group(1)}-{hit.group(2)}"


def month_label(month):
    """'2026-09' -> 'Sep 2026'."""
    return f"{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}"


def _dated_note(month, yarns):
    """What a costing on a date says about each yarn it used: the dated rate, a typed price, or today's rate."""
    notes, seen = [], set()
    for y in yarns:
        if y["yarn"] in seen:
            continue
        seen.add(y["yarn"])
        if y.get("typed"):
            notes.append(f"{y['yarn']}: a typed price (Rs {y['rate']:g}) is used, not a dated rate")
        elif y["dated"]:
            notes.append(f"{y['yarn']}: the dated rate for {month_label(month)} is used (Rs {y['rate']:g}; today's is Rs {y['today']:g})"
                         + (": a placeholder, entered with no source" if y.get("placeholder") else ""))
        else:
            notes.append(f"No dated rate for {y['yarn']} in {month_label(month)}: today's rate used (Rs {y['today']:g})")
    return notes


def resolve(sel, masters, on=None, dated=None):
    """Turn drop-down choices into numeric engine inputs.

    Returns (inputs, rates_used). rates_used is a list of
    {item, choice, value, unit, basis} so every number can be traced.
    Raises ValueError naming the first choice that is not on a list.

    on: a date (stage 5). Without it nothing changes: every rate is the rate master's, today's. With it, each yarn rate
    is the dated rate of that month (dated: {yarn key: {'YYYY-MM': {'rate', 'basis'}}}, read from the store when not
    given), and where there is none, today's rate, said per yarn in inputs['rates_of'] (cost() moves it to the result).
    Only yarn rates are dated; every other rate is today's.
    """
    L = lists(masters)
    used = []
    month = None if on is None else month_of(on)
    if month is not None and dated is None:
        import data_dated
        dated = data_dated.table()
    dated_yarns = []

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
    method = pick("Print method", L["Print method"], L["Print method"][0])
    card_print = method != L["Print method"][0]
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
    system = pick("Count system", L["Count system"], L["Count system"][0])
    for side in ("Warp", "Weft"):
        key = pick(f"{side} yarn", L["Yarn"])
        row = yr.loc[key]
        rate = _num(sel.get(f"{side} yarn price override"))
        basis = "Typed override"
        if rate is None:
            rate, basis = float(row["Rate Rs/kg"]), f"{row['Basis']}, {row['Rate date']}"
            if month is not None:           # a costing on a date: the dated rate of that month, where there is one
                hit = (dated.get(key) or {}).get(month)
                if hit is not None:
                    # rule 4: a dated rate with no data behind it stays a Placeholder, so the brief, the list's placeholder
                    # column and every verdict treat it as today's placeholder was treated
                    rate = float(hit["rate"])
                    basis = (f"Placeholder: dated rate for {month_label(month)} with no source ({hit['basis']})"
                             if str(hit["basis"]).startswith("Placeholder") else f"Dated rate for {month_label(month)}: {hit['basis']}")
                dated_yarns.append({"side": side, "yarn": key, "dated": hit is not None, "rate": rate, "today": float(row["Rate Rs/kg"]),
                                    "placeholder": basis.startswith("Placeholder")})
        elif month is not None:
            dated_yarns.append({"side": side, "yarn": key, "dated": False, "typed": True, "rate": rate})
        count = _num(sel.get(f"{side} count override (Ne)")) or float(row["Count Ne (resultant)"])
        typed = _num(sel.get(f"{side} count"))      # a count typed in the chosen system takes the place of the yarn's own
        label = f"{key} (Ne {count:g})"
        if typed is not None:
            if typed <= 0:
                raise ValueError(f"'{side} count' must be a number above zero")
            count = engine.to_ne(typed, system)
            label = f"{key}, count typed as {typed:g} {system} = Ne {count:.2f}"
        inp[f"{side.lower()}_rate"], inp[f"{side.lower()}_ne"] = rate, count
        note(f"{side} yarn", label, rate, "Rs/kg", basis)

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
    # a count converted from tex or denier may land a hair over a band's limit (Ne 40.007): it belongs to that band
    fits = sz[sz["Warp count up to (Ne)"] >= inp["warp_ne"] - 0.05]
    if fits.empty:
        raise ValueError(f"Warp count Ne {inp['warp_ne']:.4g} is finer than any band in the sizing table")
    band = fits.iloc[0]
    inp["sizing_rate"] = float(band["Rs per kg warp"])
    note("Sizing", f"warp up to Ne {band['Warp count up to (Ne)']:g}", inp["sizing_rate"], "Rs/kg warp", band["Basis"])

    # Piece dyeing
    inp["piece_dye_rate"] = 0.0
    if not yd:
        pdn = masters["Piece_Dyeing"]
        shade = piece_shade if route == "Piece Dyed" else "Any"
        # A print costed by rate card method carries preparation only; the method adds the printing.
        look = "RFD / Bleached" if printed and card_print else route
        hit = pdn[(pdn["Route"] == look) & (pdn["Shade"] == shade)]
        if hit.empty:
            raise ValueError(f"No piece dyeing rate for {route} / {shade}")
        inp["piece_dye_rate"] = float(hit["Rs per kg greige"].iloc[0])
        item = ("Preparation for print" if card_print else "Printing") if printed else "Piece dyeing"
        labels["piece_dye_name"] = item
        note(item, f"{look}, {shade}", inp["piece_dye_rate"], "Rs/kg greige", hit["Basis"].iloc[0])

    # Print method, Rs per metre, only when one is chosen. Without it a printed fabric stays on the
    # printing rate per kg above. It can also be set for a print over yarn dyed cloth.
    pm = masters["Print_Methods"].set_index("Print method").loc[method]
    inp["print_per_m"] = float(pm["Rs per metre"])
    if card_print:
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
    if month is not None:
        used_dated = any(y["dated"] for y in dated_yarns)
        inp["rates_of"] = {"month": month, "label": month_label(month), "dated": used_dated, "yarns": dated_yarns,
                           "notes": _dated_note(month, dated_yarns),
                           "text": (f"Yarn on the dated rates of {month_label(month)} where there is one" if used_dated else
                                    f"The rates of {month_label(month)} were asked for: there is no dated rate for its yarn in that month, "
                                    "so today's yarn rates are used") + "; every other rate is today's"}
    return inp, used


def cost(sel, masters, on=None, dated=None):
    """One fabric costed. on: a date, to cost the yarn on the dated rates of its month (see resolve); the result then
    says in 'rates_of' which month's rates it used, yarn by yarn. Without on, today's rates, exactly as before."""
    inp, used = resolve(sel, masters, on=on, dated=dated)
    rates_of = inp.pop("rates_of", None)
    res = engine.compute(inp)
    if rates_of is not None:
        res["rates_of"] = rates_of
    res["rates_used"] = used
    res["inputs"] = inp
    quote = _num(sel.get("Quoted price (Rs/m)"))
    quote = quote if quote and quote > 0 else None      # a quote of zero or less is no quote
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
    ("Count system", "Count system", False), ("Warp count", None, False), ("Weft count", None, False),
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
        "Warp count and Weft count are optional. Blank: the count of the yarn chosen. Filled: that count, in the "
        "Count system chosen (English Ne when blank), is used for the weight; the yarn's rate per kg is unchanged.",
        "Mill rate card columns are optional. Left blank: no dobby or top beam charge, weft dyed, the printing "
        "rate per kg for a printed fabric, and the order size slab for quantity.",
        "Print method Rotary or Digital replaces the printing rate per kg with the rate card's charge per metre; "
        "it can also be set for a print over yarn dyed cloth.",
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
