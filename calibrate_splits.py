"""The calibration draft's held-back test again, on fairer splits (stage 5). NOTHING IS APPLIED, and
pilot/Proposed_Rate_Changes.xlsx is not touched: this writes pilot/Held_Back_Splits.xlsx only.

Why: the draft holds back a third of the fabrics by a rule on the fabric code (pilot.held_back). The 1,696 costed
fabrics are only 433 constructions, and the same construction then sits on both sides (found on 27 Nov): the draft is
tested on cloth it was fitted on, so its held-back result is optimistic. Here the same draft (calibrate.draft: order
size, weaving per route and weave, printing) is worked out again on each of these splits and tested on what was held back:

  by fabric code     the draft's own split, for comparison
  by construction    a third of the constructions held back (crc32 of the construction signature, construction.py):
                     the same construction is never on both sides. Stage 2's Fab groups can take the place of the signature.
  by time            each purchase-order line on the side of its own date: a fabric code's lines of Aug and Sep 2026 are
                     one fabric in the fit (its price their weighted average), its lines of Oct and Nov another in the test
  by time, last month  the same, fitted on Aug to Oct, tested on Nov (few fabrics: a second look, not the main one)

For each: the fabrics that come within 10% with the draft and those that drop out of it, and how sure the change is
(a bootstrap that resamples whole constructions, so cloth bought under several codes counts once). Also: the fit of
today's rates by order month (every fabric), since the yarn rates are of one date (Nov 2026).
Run: python calibrate_splits.py      (about ten minutes; reads the same files as pilot.py)
"""
import os
import warnings
import zlib

import numpy as np
import pandas as pd

import calibrate
import construction
import pilot

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pilot", "Held_Back_Splits.xlsx")
NEAR = 0.03                 # a tested construction "near" a fitted one: the same yarns, route and weave, EPI and PPI within 3%
BOOT, SEED = 4000, 20261127


def signature(r):
    """The construction of a pilot fabric (every one is 100% cotton: the pilot costs no other content)."""
    return construction.signature("100% cotton", r["Route"], r["Weave"], r["Warp yarn"], r["Weft yarn"], r["EPI"], r["PPI"],
                                  r["Finished width (in)"], r["Finish"])


def held_by_construction(sig):
    return zlib.crc32(sig.encode()) % 3 == 0


def fit_row(d):
    g = d["Gap"]
    return {"Fabrics": len(d), "Median gap %": round(g.median() * 100, 1) if len(d) else None,
            "Median size of gap %": round(g.abs().median() * 100, 1) if len(d) else None,
            "Within 5%": round((g.abs() <= 0.05).mean(), 3) if len(d) else None,
            "Within 10%": round((g.abs() <= 0.10).mean(), 3) if len(d) else None,
            "Within 20%": round((g.abs() <= 0.20).mean(), 3) if len(d) else None}


def by_time(inp, lines, fit_months):
    """Each fabric code split by the date of its order lines: the fit part (its lines in fit_months) and the test part (the
    rest), each priced at the weighted average of its own lines, with its own metres and rate card quantity band."""
    out = []
    g = lines.set_index("Material")
    for _, r in inp.iterrows():
        mine = g.loc[[r["Fabric code"]]] if r["Fabric code"] in g.index else None
        if mine is None:
            continue
        for train in (True, False):
            part = mine[mine["month"].isin(fit_months) == train]
            qty, value = float(part["qty"].sum()), float(part["value"].sum())
            if qty <= 0:
                continue
            row = r.to_dict()
            row.update({"Quoted price (Rs/m)": round(value / qty, 2), "PO metres": qty, "PO lines": None,
                        "Rate card quantity": pilot.quantity_band(r["Route"], qty), "Train": train})
            out.append(row)
    return pd.DataFrame(out)


def paired(r, x):
    """The tested fabrics, today's gap and the draft's side by side, with their construction."""
    cur, prop = r["current"], r["d3"]
    b = cur[~cur["Train"]][["Fabric code", "Gap"]].rename(columns={"Gap": "today"})
    a = prop[~prop["Train"]][["Fabric code", "Gap"]].rename(columns={"Gap": "draft"})
    t = x[~x["Train"]][["Fabric code", "Construction"]].drop_duplicates("Fabric code")
    return b.merge(a, on="Fabric code").merge(t, on="Fabric code")


def bootstrap(p, rng):
    """The change in the share within 10% (points), and its 95% interval, resampling whole constructions."""
    g = p.assign(t=(p["today"].abs() <= 0.10).astype(int), d=(p["draft"].abs() <= 0.10).astype(int)).groupby("Construction").agg(
        n=("t", "size"), t=("t", "sum"), d=("d", "sum"))
    idx = rng.integers(0, len(g), size=(BOOT, len(g)))
    n, t, d = g["n"].values[idx].sum(1), g["t"].values[idx].sum(1), g["d"].values[idx].sum(1)
    diff = (d - t) / n * 100
    lo, hi = np.percentile(diff, [2.5, 97.5])
    return round((g["d"].sum() - g["t"].sum()) / g["n"].sum() * 100, 1), round(float(lo), 1), round(float(hi), 1)


def near_count(x):
    """Tested constructions that differ from a fitted one only in width, finish, or EPI and PPI within 3%."""
    fit = x[x["Train"]].drop_duplicates("Construction")
    test = x[~x["Train"]].drop_duplicates("Construction")
    key = ["Route", "Weave", "Warp yarn", "Weft yarn"]
    near = set()
    for _, t in test.iterrows():
        f = fit
        for k in key:
            f = f[f[k] == t[k]]
        if len(f) and ((abs(f["EPI"] - t["EPI"]) <= NEAR * f["EPI"]) & (abs(f["PPI"] - t["PPI"]) <= NEAR * f["PPI"])).any():
            near.add(t["Construction"])
    return near


def main():
    from rules import dated
    m0, inp, _, _ = pilot.build_inputs()
    months, lines = dated.order_months(), dated.po_lines()
    inp = inp.copy()
    inp["Construction"] = inp.apply(signature, axis=1)
    inp["Order month"] = inp["Fabric code"].astype(str).map(lambda c: (months.get(c) or {}).get("month"))
    lines = lines[lines["Material"].isin(set(inp["Fabric code"].astype(str)))]
    inp["Fabric code"] = inp["Fabric code"].astype(str)
    # what the first version of this test did: a code's whole price on the side of its order month (a leak across the split)
    early = {"2026-08", "2026-09"}
    lm = lines.assign(fit=lines["month"].isin(early))
    side = inp.set_index("Fabric code")["Order month"].isin(early)
    leak_fit = lm[lm["Material"].map(side) & ~lm["fit"]]
    leak_test = lm[~lm["Material"].map(side) & lm["fit"]]
    leak = {"fit codes with Oct-Nov lines": leak_fit["Material"].nunique(), "fit codes": int(side.sum()),
            "share of fit metres from Oct-Nov": round(float(leak_fit["qty"].sum() / lm[lm["Material"].map(side)]["qty"].sum()), 3),
            "tested codes with Aug-Sep lines": leak_test["Material"].nunique(), "tested codes": int((~side).sum())}
    print("leak in the first version:", leak, flush=True)
    splits = [
        ("By fabric code (the draft's own split)", inp.assign(Train=~inp["Fabric code"].map(pilot.held_back))),
        ("By construction (never on both sides)", inp.assign(Train=~inp["Construction"].map(held_by_construction))),
        ("By time: fit Aug-Sep, test Oct-Nov (lines by date)", by_time(inp, lines, early)),
        ("By time: fit Aug-Oct, test Nov (lines by date)", by_time(inp, lines, early | {"2026-10"})),
    ]
    rng = np.random.default_rng(SEED)
    summary, proposals, cells, overlap, sure = [], [], [], [], []
    current_all = None
    for name, x in splits:
        train = x["Train"]
        print(f"\n== {name}: fit {int(train.sum())}, test {int((~train).sum())}", flush=True)
        r = calibrate.draft(m0, x)
        cur, prop = r["current"], r["d3"]
        current_all = cur if current_all is None else current_all
        tr = set(x.loc[x["Train"], "Construction"])
        test = x[~x["Train"]]
        shared = test["Construction"].isin(tr)
        near = near_count(x)
        overlap.append({"Split": name, "Fit fabrics": int(x["Train"].sum()), "Tested fabrics": len(test),
                        "Tested constructions": test["Construction"].nunique(),
                        "Tested fabrics whose construction is also in the fit": int(shared.sum()),
                        "...as a share": round(shared.mean(), 3) if len(test) else None,
                        "Constructions on both sides": len(set(test["Construction"]) & tr),
                        "Tested constructions near a fitted one (same yarns, route, weave; EPI, PPI within 3%)": len(near - tr) if tr else 0})
        p = paired(r, x)
        gain = int(((p["draft"].abs() <= 0.10) & (p["today"].abs() > 0.10)).sum())
        loss = int(((p["today"].abs() <= 0.10) & (p["draft"].abs() > 0.10)).sum())
        change, lo, hi = bootstrap(p, rng)
        unseen = p[~p["Construction"].isin(near | tr)]
        cu, lou, hiu = bootstrap(unseen, rng) if len(unseen) else (None, None, None)
        sure.append({"Split": name, "Tested fabrics": len(p), "Came within 10% with the draft": gain, "Dropped out of 10% with the draft": loss,
                     "Net": gain - loss, "Within 10%: change (points)": change, "95% interval, resampling constructions": f"{lo:+.1f} to {hi:+.1f}",
                     "Without tested constructions near or equal to a fitted one: fabrics": len(unseen),
                     "...change (points)": cu, "...95% interval": None if cu is None else f"{lou:+.1f} to {hiu:+.1f}"})
        print(sure[-1], flush=True)
        for label, b, a in (("Tested (held back)", cur[~cur["Train"]], prop[~prop["Train"]]), ("Fit (for comparison)", cur[cur["Train"]], prop[prop["Train"]])):
            fb, fa = fit_row(b), fit_row(a)
            summary.append({"Split": name, "Set": label, "Fabrics": fb["Fabrics"],
                            **{f"{k}, today's rates": v for k, v in fb.items() if k != "Fabrics"},
                            **{f"{k}, with the draft": v for k, v in fa.items() if k != "Fabrics"},
                            "Within 10%: change (points)": None if fb["Within 10%"] is None else round((fa["Within 10%"] - fb["Within 10%"]) * 100, 1),
                            "Median size of gap: change (points)": None if fb["Median size of gap %"] is None else round(fa["Median size of gap %"] - fb["Median size of gap %"], 1)})
        for s in r["slab_rows"]:
            proposals.append({"Split": name, "Rate": f"Order size {s['Order size']} (overhead points added to the card's band)",
                              "Fit fabrics": s["Training fabrics"], "Now": s["Current overhead add (points)"], "Draft": s["Proposed overhead add (points)"], "Action": ""})
        for _, pr_ in r["props"].iterrows():
            proposals.append({"Split": name, "Rate": f"Weaving, {pr_['Route'].lower()} {pr_['Weave group'].lower()} (Rs a pick)",
                              "Fit fabrics": pr_["Training fabrics"], "Now": pr_["Current Rs/pick"], "Draft": pr_["Proposed Rs/pick"], "Action": pr_["Action"]})
        pr = r["print_row"].iloc[0]
        proposals.append({"Split": name, "Rate": "Printing (Rs a kilo greige)", "Fit fabrics": pr["Training fabrics"], "Now": pr["Current"],
                          "Draft": pr["Proposed"], "Action": "Change" if pr["Proposed"] != pr["Current"] else (pr["Note"] or "Keep")})
        b, a = cur[~cur["Train"]], prop[~prop["Train"]]
        for key, cb in b.groupby(["Route", "Weave group"]):
            ca = a[(a["Route"] == key[0]) & (a["Weave group"] == key[1])]
            if len(cb) >= 8:
                fb, fa = fit_row(cb), fit_row(ca)
                cells.append({"Split": name, "Route": key[0], "Weave group": key[1], "Tested fabrics": len(cb),
                              "Median gap % today": fb["Median gap %"], "Median gap % draft": fa["Median gap %"],
                              "Within 10% today": fb["Within 10%"], "Within 10% draft": fa["Within 10%"],
                              "Within 10%: change (points)": round((fa["Within 10%"] - fb["Within 10%"]) * 100, 1),
                              "Within 20% today": fb["Within 20%"], "Within 20% draft": fa["Within 20%"]})
    # today's rates, fabric by order month: the yarn rates are of one date, so this is where dating them would show
    cur = current_all.merge(inp[["Fabric code", "Order month"]], on="Fabric code", how="left")
    multi = {c for c, v in months.items() if len(v["months"]) > 1}
    by_month = []
    for mo, d in cur.groupby("Order month"):
        by_month.append({"Order month": mo, **fit_row(d), "Metres": round(float(d["PO metres"].sum())),
                         "Ordered in more than one month": int(d["Fabric code"].isin(multi).sum())})
    readme = pd.DataFrame({"Read me": [
        "DRAFT TEST ONLY. Nothing in the rate master has been changed, and pilot/Proposed_Rate_Changes.xlsx is not touched.",
        "The same draft as calibrate.py (order size slabs added to the card's bands, weaving per route and weave group, one "
        "printing rate) is worked out on the fit fabrics of each split and tested on the fabrics held back.",
        "Gap = purchase order price above should-cost. 'Today's rates' is the tool as it stands; 'with the draft' adds the proposals.",
        "By fabric code: the draft's own split. The same construction sits on both sides of it, so it flatters the draft.",
        "By construction: a third of the constructions held back by a fixed rule on the construction signature (content, route, "
        "weave, warp, weft, EPI, PPI, finished width, finish; construction.py, to be replaced by stage 2's Fab groups). The same "
        "construction is never on both sides; but some tested constructions differ from a fitted one only in width, finish, or "
        "EPI and PPI within 3% (sheet 'Overlap'), so 'cloth it has not seen' holds with that caveat.",
        "By time: each order line on the side of its own date. A code bought in both periods is a fit fabric (its earlier lines) "
        "and a tested fabric (its later lines), each priced at its own lines' weighted average, as it would be in use.",
        f"The first version of this test put a code's whole price on the side of its order month: {leak['fit codes with Oct-Nov lines']} of "
        f"{leak['fit codes']} fit codes then carried Oct-Nov lines ({leak['share of fit metres from Oct-Nov']:.0%} of fit metres) and "
        f"{leak['tested codes with Aug-Sep lines']} of {leak['tested codes']} tested codes carried Aug-Sep lines. This version does not.",
        f"How sure: sheet 'How sure'. The share within 10% is compared fabric by fabric (which came within 10%, which dropped out), and "
        f"a bootstrap of {BOOT} draws resamples whole tested constructions to give a 95% interval for the change.",
        "Sheets: Summary, How sure, Proposals (what each split's draft would change), Tested by cell, Overlap, Today's fit by month.",
    ]})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tables = [("Read me", readme), ("Summary", pd.DataFrame(summary)), ("How sure", pd.DataFrame(sure)), ("Proposals", pd.DataFrame(proposals)),
              ("Tested by cell", pd.DataFrame(cells)), ("Overlap", pd.DataFrame(overlap)), ("Today's fit by month", pd.DataFrame(by_month))]
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        for name, df in tables:
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(80)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 70)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print("\nleak in the first version:", leak)
    for name, df in tables[1:]:
        print(f"\n== {name}\n" + df.to_string(index=False))
    print("Saved", OUT)


if __name__ == "__main__":
    main()
