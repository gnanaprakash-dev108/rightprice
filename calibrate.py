"""Draft rate changes from the purchase-order pilot. NOTHING IS APPLIED.

Two thirds of the costed fabrics (chosen by a fixed rule on the fabric code) are
used to work out proposals; the other third is held back to test them.
The fabrics carry the mill rate card inputs that pilot.py reads from PLM and the purchase orders.
Order of work:
  1. order-size premium, from yarn-dyed and piece-dyed fabrics. The rate card quantity bands stay
     switched on, so what is proposed is only what the card leaves unexplained: slabs to be ADDED
     to the bands, not the present slabs that take their place.
  2. weaving rate per route and weave group (the rate that closes the median gap)
  3. printing: no proposal. The print method rates are the card's; the sheet shows the charge per
     metre that the purchase prices imply, beside rotary and digital.
The rate master on disk is only read. Output: pilot/Proposed_Rate_Changes.xlsx
Run: python calibrate.py
"""
import os
import warnings

import pandas as pd

import engine
import masters
import pilot
import rate_card

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pilot", "Proposed_Rate_Changes.xlsx")

SLABS = [("Below 1,000 m", 0, 1000), ("1,000 to 3,000 m", 1000, 3000), ("3,000 m and above", 3000, 1e12)]
MIN_N = 20                      # fewer training fabrics than this: no proposal
WEAVE_BAND = (0.10, 0.70)       # Rs/pick; outside this the gap is not a weaving effect
KEEP_IF_WITHIN = 0.03           # leave a rate alone when the median gap is inside +/-3%


def slab_of(metres):
    return next(name for name, lo, hi in SLABS if lo <= metres < hi)


def evaluate(m, inp):
    """Cost every fabric with rate master m; add the rate that would close each gap."""
    wg = m["Weaves"].set_index("Weave")["Weave group"]
    rows = []
    for _, r in inp.iterrows():
        sel = r.to_dict()
        try:
            i, _ = masters.resolve(sel, m)
            res = engine.compute(i)
        except Exception:
            continue
        price = sel["Quoted price (Rs/m)"]
        mult = (1 + i["process_wastage"] + i["overhead"]) * (1 + i["margin"]) / (1 - i["shrinkage"])
        # undo the quantity terms, then the rate card rupees per metre, then the mark-up
        before_qty = (price + i.get("volume_discount_per_m", 0.0)) / (1 + i.get("small_lot_pct", 0.0))
        upcharges = before_qty - (price - res["total_per_m"]) / (1 + i.get("small_lot_pct", 0.0)) - res["marked_up"]
        delta = (before_qty - i["extra_per_m"] - upcharges) / mult - res["base"]   # Rs/m missing from the base cost
        rows.append({"Fabric code": sel["Fabric code"], "Supplier": sel["Supplier"], "Route": sel["Route"],
                     "Weave group": wg[sel["Weave"]], "Warp yarn": sel["Warp yarn"],
                     "Order size": sel["Order size"], "PO metres": sel["PO metres"],
                     "PO price": price, "Should-cost": res["total_per_m"],
                     "Gap": price / res["total_per_m"] - 1,
                     "Weaving rate": i["weaving_rate"], "Implied weaving rate": i["weaving_rate"] + delta / i["ppi"],
                     "Implied yarn dyeing": i["warp_dye"] + delta / res["greige_kg"],
                     "Implied piece dye or print": i["piece_dye_rate"] + delta / res["greige_kg"],
                     "Print method": sel.get("Print method"), "Print Rs/m": i.get("print_per_m", 0.0),
                     "Implied print Rs/m": i.get("print_per_m", 0.0)
                     + (price - res["total_per_m"]) / (1 + i.get("small_lot_pct", 0.0)),
                     "Train": not pilot.held_back(sel["Fabric code"])})
    return pd.DataFrame(rows)


def fit(d):
    g = d["Gap"]
    return {"Fabrics": len(d), "Median gap %": round(g.median() * 100, 1),
            "Within 5%": round((g.abs() <= 0.05).mean(), 3), "Within 10%": round((g.abs() <= 0.10).mean(), 3),
            "Within 20%": round((g.abs() <= 0.20).mean(), 3)}


def main():
    m0, inp, _, _ = pilot.build_inputs()
    inp = inp.copy()
    inp["Order size"] = inp["PO metres"].map(slab_of)
    current = evaluate(m0, inp)             # the tool as it stands: a quantity band replaces the slab
    slab_now = m0["Order_Slab"].set_index("Order size")["Overhead add (points)"]
    m0 = dict(m0)
    m0["Order_Slab"] = pd.DataFrame([(s[0], 0.0, "Not set") for s in SLABS],
                                    columns=["Order size", "Overhead add (points)", "Basis"])
    st = m0["Settings"].copy()              # slabs added to the rate card quantity bands, starting from zero
    st["Value"] = st["Value"].astype(object)
    st.loc[st["Setting"] == rate_card.QTY_SETTING, "Value"] = "Added"
    m0["Settings"] = st
    base = evaluate(m0, inp)
    train0 = base[base["Train"]]

    # ---- 1. order-size premium (yarn dyed and piece dyed only; printed has too few large orders)
    big = SLABS[-1][0]
    core = train0[train0["Route"].isin(["Yarn Dyed", "Piece Dyed"])]
    ref = core[core["Order size"] == big].groupby(["Route", "Weave group"])["Gap"].agg(["median", "size"])
    ref = ref[ref["size"] >= 10]["median"]
    ex = core.join(ref.rename("ref"), on=["Route", "Weave group"]).dropna(subset=["ref"])
    ex["excess"] = ex["Gap"] - ex["ref"]
    slab_rows, m1 = [], dict(m0)
    slab_tbl = m0["Order_Slab"].copy()
    for name, _, _ in SLABS:
        e = ex[ex["Order size"] == name]["excess"]
        pts = 0.0 if name == big else round(max(0.0, e.median() * 108) * 2) / 2   # gap % -> overhead points
        if pts < 1:
            pts = 0.0
        slab_tbl.loc[slab_tbl["Order size"] == name, ["Overhead add (points)", "Basis"]] = [pts, "Pilot proposal"]
        slab_rows.append({"Order size": name, "Training fabrics": len(e),
                          "Median gap above large orders %": round(e.median() * 100, 1) if len(e) else None,
                          "Current overhead add (points)": float(slab_now.get(name, 0.0)),
                          "Current slab is used": "Only where no rate card quantity band is set",
                          "Proposed overhead add (points)": pts,
                          "Proposed slab is used": "Added to the rate card quantity band"})
    m1["Order_Slab"] = slab_tbl

    # ---- 2. weaving rate per route and weave group
    d1 = evaluate(m1, inp)
    t1 = d1[d1["Train"]]
    wr = m1["Weaving_Rates"].copy()
    props = []
    for (route, grp), c in t1.groupby(["Route", "Weave group"]):
        if route == "Printed":
            continue
        now = wr[(wr["Weave group"] == grp) & (wr["Route"] == route)]
        if now.empty:
            continue
        cur, basis = float(now["Rs per pick"].iloc[0]), now["Basis"].iloc[0]
        imp = c["Implied weaving rate"]
        med, q1, q3 = imp.median(), imp.quantile(.25), imp.quantile(.75)
        gap = c["Gap"].median()
        new, note = cur, ""
        if len(c) < MIN_N:
            action = "No proposal"; note = f"Only {len(c)} training fabrics"
        elif abs(gap) <= KEEP_IF_WITHIN:
            action = "Keep"; note = "Median gap already inside 3%"
        elif not WEAVE_BAND[0] <= med <= WEAVE_BAND[1]:
            action = "No proposal"
            note = (f"Closing the gap through weaving would need Rs {med:.2f}/pick, which is not believable; "
                    "the cause is elsewhere (yarn rate, dyed share of yarn, or dyeing)")
        else:
            action = "Change"; new = round(med, 2)
        props.append({"Route": route, "Weave group": grp, "Training fabrics": len(c),
                      "Median gap % (after order-size step)": round(gap * 100, 1),
                      "Current Rs/pick": cur, "Current basis": basis,
                      "Rate that closes the gap: median": round(med, 3), "...lower quartile": round(q1, 3),
                      "...upper quartile": round(q3, 3), "Action": action, "Proposed Rs/pick": new,
                      "If weaving is right, implied yarn dyeing Rs/kg": round(c["Implied yarn dyeing"].median())
                      if route == "Yarn Dyed" else None,
                      "If weaving is right, implied piece dyeing Rs/kg": round(c["Implied piece dye or print"].median())
                      if route != "Yarn Dyed" else None, "Note": note})
        if action == "Change":
            wr.loc[(wr["Weave group"] == grp) & (wr["Route"] == route), ["Rs per pick", "Basis"]] = [new, "Pilot proposal"]
    # printed fabric is woven as greige like piece dyed: carry the piece-dyed rate across
    for grp in wr["Weave group"].unique():
        pdr = wr[(wr["Weave group"] == grp) & (wr["Route"] == "Piece Dyed")]
        if len(pdr) and pdr["Basis"].iloc[0] == "Pilot proposal":
            wr.loc[(wr["Weave group"] == grp) & (wr["Route"] == "Printed"), ["Rs per pick", "Basis"]] = \
                [float(pdr["Rs per pick"].iloc[0]), "Pilot proposal (same as piece dyed)"]
    m2 = dict(m1); m2["Weaving_Rates"] = wr
    props = pd.DataFrame(props).sort_values("Training fabrics", ascending=False)

    # ---- 3. printing: what the purchase prices imply, beside the card. No proposal.
    d2 = evaluate(m2, inp)
    pt = d2[d2["Train"] & (d2["Route"] == "Printed")]
    cardp = m2["Print_Methods"].set_index("Print method")["Rs per metre"]
    rot, dig = float(cardp.get("Rotary", 18)), float(cardp.get("Digital", 55))
    print_rows = []
    for label, c in [("All printed", pt)] + [(f"Printed {g.lower()}", c) for g, c in pt.groupby("Weave group")]:
        imp = c["Implied print Rs/m"]
        if len(c) < 8:
            continue
        print_rows.append({"Fabrics (training)": label, "Count": len(c), "Costed as": "Rotary (not in PLM)",
                           "Card rotary Rs/m": rot, "Card digital Rs/m": dig,
                           "Print charge that closes the gap, Rs/m: median": round(imp.median(), 1),
                           "...lower quartile": round(imp.quantile(.25), 1),
                           "...upper quartile": round(imp.quantile(.75), 1),
                           "Share nearer rotary than digital": round((imp < (rot + dig) / 2).mean(), 3),
                           "Share above digital by more than Rs 10": round((imp > dig + 10).mean(), 3)})
    print_row = pd.DataFrame(print_rows)
    print_row["Note"] = ("No proposal. The implied charge assumes weaving, preparation and every other rate are "
                         "right; preparation before printing is a placeholder.")
    m3 = m2

    # ---- 4. test on the held-back third
    d3 = evaluate(m3, inp)
    test_rows = []
    for label, before, after in [("All held-back fabrics", current[~current["Train"]], d3[~d3["Train"]]),
                                 ("Training fabrics (for comparison)", current[current["Train"]], d3[d3["Train"]])]:
        test_rows.append({"Set": label, "Rates": "Current", **fit(before)})
        test_rows.append({"Set": label, "Rates": "Proposed", **fit(after)})
    by_cell = []
    b, a = current[~current["Train"]], d3[~d3["Train"]]
    for key, cb in b.groupby(["Route", "Weave group"]):
        ca = a[(a["Route"] == key[0]) & (a["Weave group"] == key[1])]
        if len(cb) >= 8:
            fb, fa = fit(cb), fit(ca)
            by_cell.append({"Route": key[0], "Weave group": key[1], "Held-back fabrics": len(cb),
                            "Median gap % current": fb["Median gap %"], "Median gap % proposed": fa["Median gap %"],
                            "Within 10% current": fb["Within 10%"], "Within 10% proposed": fa["Within 10%"],
                            "Within 20% current": fb["Within 20%"], "Within 20% proposed": fa["Within 20%"]})
    by_cell = pd.DataFrame(by_cell).sort_values("Held-back fabrics", ascending=False)

    # ---- diagnostics that point away from process rates
    t3 = d3[d3["Train"]]
    yarn = t3.groupby("Warp yarn").agg(**{"Training fabrics": ("Gap", "size"),
                                         "Median gap % after proposals": ("Gap", lambda s: round(s.median() * 100, 1))})
    yr = m0["Yarn_Rates"].set_index("Yarn key")
    yarn["Master rate Rs/kg"] = yr["Rate Rs/kg"]
    yarn["Rate basis"] = yr["Basis"]
    yarn = yarn[yarn["Training fabrics"] >= 10].sort_values("Training fabrics", ascending=False).reset_index()
    sup = d3.groupby("Supplier").agg(**{"Fabrics": ("Gap", "size"), "PO metres": ("PO metres", "sum"),
                                        "Median gap % current rates": ("Gap", lambda s: 0.0)})
    sup["Median gap % current rates"] = current.groupby("Supplier")["Gap"].median().mul(100).round(1)
    sup["Median gap % proposed rates"] = d3.groupby("Supplier")["Gap"].median().mul(100).round(1)
    sup = sup[sup["Fabrics"] >= 10].sort_values("Fabrics", ascending=False).reset_index()

    readme = pd.DataFrame({"Read me": [
        "DRAFT for review. Nothing in the rate master has been changed.",
        f"Fabrics: {len(base)} 100% cotton wovens with a rupee-per-metre purchase order price and PLM specs.",
        f"Two thirds ({int(base['Train'].sum())}) were used to work out the proposals; one third "
        f"({int((~base['Train']).sum())}) was held back to test them (sheet 'Held-back test').",
        "Gap = purchase order price above should-cost. Positive means the order is dearer than should-cost.",
        "'Rate that closes the gap' assumes every other rate and the yarn master are right. It is evidence, not proof.",
        "A weaving proposal is made only with 20 or more training fabrics, a median gap outside 3%, and a result "
        f"between Rs {WEAVE_BAND[0]:.2f} and Rs {WEAVE_BAND[1]:.2f} per pick.",
        "Yarn dyeing (Rs 150/kg) and piece dyeing (Rs 160/kg) were held at the V1 workbook values.",
        "Mill rate card inputs are on, as pilot.py sets them: finishes and quantity bands from the data, weft dyed "
        "unless PLM shows otherwise, every print rotary, no dobby shaft or top beam charge.",
        "'Current' in the held-back test is the tool as it stands: a rate card quantity band takes the place of "
        "the order size slab. 'Proposed' adds the slabs on the 'Order size' sheet to the bands (Settings: "
        f"'{rate_card.QTY_SETTING}' = Added) and uses the weaving proposals.",
        "The order size slabs proposed here are only right together with that setting. apply_proposals.py sets both.",
        "Printing carries no proposal: the print method rates are the mill rate card's.",
        "Sheets: Order size, Weaving, Printing, Held-back test, Held-back by cell, By yarn, By supplier.",
    ]})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        for name, df in [("Read me", readme), ("Order size", pd.DataFrame(slab_rows)), ("Weaving", props),
                         ("Printing", print_row), ("Held-back test", pd.DataFrame(test_rows)),
                         ("Held-back by cell", by_cell), ("By yarn", yarn), ("By supplier", sup)]:
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(60)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 70)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(slab_rows).to_string(index=False))
    print(props.drop(columns=["Current basis", "Note"]).to_string(index=False))
    print(props[["Route", "Weave group", "Action", "Note"]].to_string(index=False))
    print(print_row.to_string(index=False))
    print(pd.DataFrame(test_rows).to_string(index=False))
    print(by_cell.to_string(index=False))
    print(yarn.to_string(index=False))
    print(sup.head(14).to_string(index=False))
    print("Saved", OUT)


if __name__ == "__main__":
    main()
