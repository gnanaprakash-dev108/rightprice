"""Applies pilot/Proposed_Rate_Changes.xlsx to data/Rate_Master.xlsx.

A dated copy of the rate master is saved first, so the change can be undone by
copying that file back.   Run: python apply_proposals.py
"""
import datetime as dt
import os
import shutil

import pandas as pd

import masters

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSALS = os.path.join(HERE, "pilot", "Proposed_Rate_Changes.xlsx")
BASIS = f"Pilot calibration {dt.date.today():%d %b %Y}"
CHECKED = f"Pilot-checked {dt.date.today():%d %b %Y} (unchanged)"


def main():
    backup = masters.MASTER_PATH.replace(".xlsx", f" before calibration {dt.datetime.now():%Y%m%d-%H%M}.xlsx")
    shutil.copy(masters.MASTER_PATH, backup)
    m = dict(masters.load())
    p = pd.read_excel(PROPOSALS, sheet_name=None)
    log = []

    # order size: large orders first, so they stay the default choice
    slabs = p["Order size"].iloc[::-1]
    m["Order_Slab"] = pd.DataFrame({"Order size": slabs["Order size"].values,
                                    "Overhead add (points)": slabs["Proposed overhead add (points)"].values,
                                    "Basis": BASIS})
    for _, r in slabs.iterrows():
        log.append(f"Order size {r['Order size']}: overhead add {r['Proposed overhead add (points)']:g} points")

    wr = m["Weaving_Rates"].copy()
    for _, r in p["Weaving"].iterrows():
        hit = (wr["Weave group"] == r["Weave group"]) & (wr["Route"] == r["Route"])
        if r["Action"] == "Change":
            old = float(wr.loc[hit, "Rs per pick"].iloc[0])
            wr.loc[hit, ["Rs per pick", "Basis"]] = [float(r["Proposed Rs/pick"]), BASIS]
            log.append(f"Weaving {r['Route']} {r['Weave group']}: {old:g} -> {r['Proposed Rs/pick']:g} Rs/pick")
            if r["Route"] == "Piece Dyed":      # printed cloth is woven as greige, like piece dyed
                ph = (wr["Weave group"] == r["Weave group"]) & (wr["Route"] == "Printed")
                wr.loc[ph, ["Rs per pick", "Basis"]] = [float(r["Proposed Rs/pick"]), BASIS + ", same as piece dyed"]
                log.append(f"Weaving Printed {r['Weave group']}: set to {r['Proposed Rs/pick']:g} Rs/pick")
        elif r["Action"] == "Keep" and str(wr.loc[hit, "Basis"].iloc[0]).startswith("Placeholder"):
            wr.loc[hit, "Basis"] = CHECKED
            log.append(f"Weaving {r['Route']} {r['Weave group']}: kept, no longer a placeholder")
    m["Weaving_Rates"] = wr

    pr = p["Printing"].iloc[0]
    pdt = m["Piece_Dyeing"].copy()
    if float(pr["Proposed"]) != float(pr["Current"]):
        pdt.loc[pdt["Route"] == "Printed", ["Rs per kg greige", "Basis"]] = [float(pr["Proposed"]), BASIS]
        log.append(f"Printing: {pr['Current']:g} -> {pr['Proposed']:g} Rs/kg greige")
    m["Piece_Dyeing"] = pdt

    # mill rate card: only the rows marked Yes in the Apply column
    card = p.get("Rate card proposals")
    if card is not None and len(card):
        import calibrate
        yes = card[card["Apply"].astype(str).str.strip().str.lower() == "yes"]
        m = calibrate.apply_card(m, yes)
        for _, r in yes.iterrows():
            log.append(f"Rate card, {r['Sheet']} {r['Row']} / {r['Column']}: {r['Current']:g} -> {r['Proposed']:g}")
        log.append(f"Rate card proposals: {len(yes)} of {len(card)} rows applied")

    masters.save(m)
    print("\n".join(log))
    print("Backup:", backup)


if __name__ == "__main__":
    main()
