"""The calibration draft's held-back test again, on fair splits (stage 5). NOTHING IS APPLIED, and
pilot/Proposed_Rate_Changes.xlsx is not touched: this writes pilot/Held_Back_Splits.xlsx only.

Why: the draft holds back a third of the fabrics by a rule on the fabric code (pilot.held_back). The 1,696 costed
fabrics are only 433 constructions, and the same construction then sits on both sides (found on 27 Nov): the draft is
tested on cloth it was fitted on, so its held-back result is optimistic. Here the same draft (calibrate.draft: order
size, weaving per route and weave, printing) is worked out again on each of these splits and tested on what was held back:

  by fabric code     the draft's own split, for comparison
  by construction    a third of the constructions held back (crc32 of the construction signature, construction.py):
                     the same construction is never on both sides. Stage 2's Fab groups can take the place of the signature.
  by time            fitted on the fabrics ordered in Aug and Sep 2026, tested on those ordered in Oct and Nov 2026
                     (a fabric code's month: the month that holds most of its metres, rules/dated.order_months)
  by time, last month  fitted on Aug to Oct, tested on Nov (few fabrics: a second look, not the main one)

Also: the fit of today's rates by order month (every fabric), since the yarn rates are of one date (Nov 2026).
Run: python calibrate_splits.py      (about five minutes; reads the same files as pilot.py)
"""
import os
import warnings
import zlib

import pandas as pd

import calibrate
import construction
import pilot

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pilot", "Held_Back_Splits.xlsx")
FIT_MONTHS = {"2026-08", "2026-09"}


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


def main():
    from rules import dated
    m0, inp, _, _ = pilot.build_inputs()
    months = dated.order_months()
    inp = inp.copy()
    inp["Construction"] = inp.apply(signature, axis=1)
    inp["Order month"] = inp["Fabric code"].astype(str).map(lambda c: (months.get(c) or {}).get("month"))
    inp["Order months"] = inp["Fabric code"].astype(str).map(lambda c: len((months.get(c) or {}).get("months") or []))
    missing = int(inp["Order month"].isna().sum())
    splits = [
        ("By fabric code (the draft's own split)", ~inp["Fabric code"].map(pilot.held_back)),
        ("By construction (never on both sides)", ~inp["Construction"].map(held_by_construction)),
        ("By time: fit Aug-Sep, test Oct-Nov", inp["Order month"].isin(FIT_MONTHS)),
        ("By time: fit Aug-Oct, test Nov", inp["Order month"].isin(FIT_MONTHS | {"2026-10"})),
    ]
    summary, proposals, cells, overlap = [], [], [], []
    current_all = None
    for name, train in splits:
        x = inp.assign(Train=train.values)
        print(f"\n== {name}: fit {int(train.sum())}, test {int((~train).sum())}", flush=True)
        r = calibrate.draft(m0, x)
        cur, prop = r["current"], r["d3"]
        current_all = cur if current_all is None else current_all
        tr = set(x.loc[x["Train"], "Construction"])
        test = x[~x["Train"]]
        shared = test["Construction"].isin(tr)
        overlap.append({"Split": name, "Fit fabrics": int(x["Train"].sum()), "Tested fabrics": len(test),
                        "Tested constructions": test["Construction"].nunique(),
                        "Tested fabrics whose construction is also in the fit": int(shared.sum()),
                        "...as a share": round(shared.mean(), 3) if len(test) else None,
                        "Constructions on both sides": len(set(test["Construction"]) & tr)})
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
        for _, p in r["props"].iterrows():
            proposals.append({"Split": name, "Rate": f"Weaving, {p['Route'].lower()} {p['Weave group'].lower()} (Rs a pick)",
                              "Fit fabrics": p["Training fabrics"], "Now": p["Current Rs/pick"], "Draft": p["Proposed Rs/pick"], "Action": p["Action"]})
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
    cur = current_all.merge(inp[["Fabric code", "Order month", "Order months"]], on="Fabric code", how="left")
    by_month = []
    for mo, d in cur.groupby("Order month"):
        by_month.append({"Order month": mo, **fit_row(d), "Metres": round(float(d["PO metres"].sum())),
                         "Ordered in more than one month": int((d["Order months"] > 1).sum())})
    readme = pd.DataFrame({"Read me": [
        "DRAFT TEST ONLY. Nothing in the rate master has been changed, and pilot/Proposed_Rate_Changes.xlsx is not touched.",
        "The same draft as calibrate.py (order size slabs added to the card's bands, weaving per route and weave group, one "
        "printing rate) is worked out on the fit fabrics of each split and tested on the fabrics held back.",
        "Gap = purchase order price above should-cost. 'Today's rates' is the tool as it stands; 'with the draft' adds the proposals.",
        "By fabric code: the draft's own split. The same construction sits on both sides of it, so it flatters the draft.",
        "By construction: a third of the constructions held back by a fixed rule on the construction signature (content, route, "
        "weave, warp, weft, EPI, PPI, finished width, finish; construction.py, to be replaced by stage 2's Fab groups). The same "
        "construction is never on both sides.",
        "By time: fitted on the earlier order months, tested on the later ones. A fabric code's month is the month holding most of "
        "its metres. A construction bought in both periods sits on both sides, as it would in use.",
        f"{len(inp)} fabrics; {missing} without an order month (they go to the test side of the time splits).",
        "Sheets: Summary, Proposals (what each split's draft would change), Tested by cell, Overlap, Today's fit by month.",
    ]})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tables = [("Read me", readme), ("Summary", pd.DataFrame(summary)), ("Proposals", pd.DataFrame(proposals)),
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
    for name, df in tables[1:]:
        print(f"\n== {name}\n" + df.to_string(index=False))
    print("Saved", OUT)


if __name__ == "__main__":
    main()
