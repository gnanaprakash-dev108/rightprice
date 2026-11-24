"""Builds the mill rate card (docs/Mill_Rate_Card.md) into the rate master.

Adds the tables behind the rate card drop-downs and leaves every other rate as it is:
  * Print_Methods    print method, Rs per metre (replaces the single printing rate per kg)
  * Dobby_Charges    dobby shafts and top beam, Rs per metre
  * Weft_Options     dyed or undyed weft for yarn-dyed fabrics, and the chambray dyed weft charge
  * Quantity_Terms   small-lot upcharge and volume discount by quantity band
  * Finishing_Rates  new column 'Upcharge Rs per metre' and the card's finishes
  * Settings         how the order size slabs behave when rate card quantity terms are used
The app does this by itself when it opens a rate master that lacks the tables (a server keeps its
own copy, which new code does not replace). A dated copy of the rate master is saved first, and
running it twice changes nothing the second time.   Run by hand: python rate_card.py
"""
import pandas as pd

CARD = "Mill rate card 23 Nov 2026"
V1, NS = "V1 workbook", "Not set"
FIN_UP = "Upcharge Rs per metre"
QTY_SETTING = "Order size slabs with rate card quantity"
NO_QTY = "Not applied"


def print_methods():
    return pd.DataFrame([("No print", 0, NS), ("Rotary", 18, CARD), ("Digital", 55, CARD)],
                        columns=["Print method", "Rs per metre", "Basis"])


def dobby_charges():
    # The card's six figures are these two lists added together: top beam is Rs 10 at every shaft count.
    return pd.DataFrame([("Dobby shafts", "Up to 8", 0, CARD), ("Dobby shafts", "9 to 12", 8, CARD),
                         ("Dobby shafts", "13 and above", 10, CARD),
                         ("Top beam", "No", 0, CARD), ("Top beam", "Yes", 10, CARD)],
                        columns=["Type", "Value", "Rs per metre", "Basis"])


def weft_options():
    return pd.DataFrame([
        ("Dyed", "Yes", 0, V1, "Weft yarn dyeing at the Rs per kg rate of its shade, as in the V1 workbook"),
        ("Undyed", "No", 0, CARD, "No weft yarn dyeing"),
        ("Chambray, dyed weft", "No", 10, CARD, "Rs per metre on the price in place of the Rs per kg rate"),
    ], columns=["Weft (yarn dyed)", "Rs per kg weft dyeing applies", "Rs per metre", "Basis", "Note"])


def quantity_terms():
    rows = [(NO_QTY, 0, 0, NS, "The order size slab is used instead"),
            ("500 to 599 m", 8, 0, CARD, "Yarn dyed only; the card takes no print or piece-dyed order this small"),
            ("600 to 699 m", 7, 0, CARD, "Yarn dyed only"),
            ("700 to 799 m", 4, 0, CARD, "Yarn dyed only"),
            ("800 to 1,999 m", 0, 0, CARD, "At or above the minimum, below the first discount"),
            ("2,000 to 3,999 m", 0, 2, CARD, "No discount when warp and weft are both 40s"),
            ("4,000 to 6,000 m", 0, 3, CARD, "No discount when warp and weft are both 40s"),
            ("Above 6,000 m", 0, 4, CARD, "No discount when warp and weft are both 40s")]
    return pd.DataFrame(rows, columns=["Quantity band", "Small-lot upcharge %", "Volume discount Rs per metre",
                                       "Basis", "Note"])


# finish -> (Rs per metre, basis). A combination that the card does not price as one item is the
# sum of its parts and stays a placeholder until a mill confirms it.
def _sum(text):
    return f"Placeholder: sum of card items, {text}"


CARD_FINISHES = [
    ("F- Easy Care", 4, CARD), ("F- ETI Easy to Iron", 4, CARD), ("F- LA Liquid Ammonia", 10, CARD),
    ("F- LA + ETI", 14, _sum("LA 10 + ETI 4")), ("F- LA+Easy Care", 14, _sum("LA 10 + Easy Care 4")),
    ("F- LAMC Liquid Ammonia Moist Cure", 30, CARD), ("F- LA + MXL", 30, CARD),
    ("F- LA+MOIST CURE+Silk Protein", 35, _sum("LA + MC 30 + Silk Protein 5")),
    ("F- LA + Arvisilk", 15, _sum("LA 10 + Arvisilk 5")), ("F- LA + Silk Protein", 15, _sum("LA 10 + Silk Protein 5")),
    ("F- LA + Peach", 15, _sum("LA 10 + Peach 5")),
    ("F- Immaculate", 35, CARD), ("F- PEACH", 5, CARD), ("F- Aero", 5, CARD), ("F- Carbonium", 5, CARD),
    ("F- Diamond Peach", 5, CARD), ("F- Diamer", 5, CARD), ("F- Apricot Touch", 5, CARD),
    ("F- Emerised", 5, CARD), ("F- Cool Touch", 15, CARD), ("F- Arvisilk", 5, CARD),
    ("F- Silk Protein / Silk Touch", 5, CARD), ("F- Evershine", 9, CARD), ("F- Prepress", 32, CARD),
    ("F- Liquid Cotton", 5, CARD), ("F- Teflon", 30, CARD),
]


def apply(m):
    """Add the rate card tables to a rate master held in memory. Returns the list of changes made."""
    log = []
    first_time = "Print_Methods" not in m
    for name, make in (("Print_Methods", print_methods), ("Dobby_Charges", dobby_charges),
                       ("Weft_Options", weft_options), ("Quantity_Terms", quantity_terms)):
        if name not in m:
            m[name] = make()
            log.append(f"Added sheet {name}")

    fr = m["Finishing_Rates"].copy()
    if FIN_UP not in fr.columns:
        yd_col, other_col = fr.columns[1], fr.columns[2]
        normal = fr[fr["Finish"] == "Normal"].iloc[0]
        fr.insert(3, FIN_UP, 0.0)
        for finish, rs, basis in CARD_FINISHES:
            # Finishing per kg stays at the Normal rate; the finish itself is the card's Rs per metre.
            row = {"Finish": finish, yd_col: normal[yd_col], other_col: normal[other_col], FIN_UP: float(rs),
                   "Basis": basis}
            hit = fr["Finish"] == finish
            if hit.any():
                for col, val in row.items():
                    fr.loc[hit, col] = val
            else:
                fr = pd.concat([fr, pd.DataFrame([row])], ignore_index=True)
        m["Finishing_Rates"] = fr
        log.append(f"Finishing_Rates: column '{FIN_UP}' added; {len(CARD_FINISHES)} finishes set from the card")

    if first_time:      # the single printing rate per kg gives way to the print method per metre
        pdt = m["Piece_Dyeing"].copy()
        rfd = pdt[pdt["Route"] == "RFD / Bleached"]["Rs per kg greige"]
        hit = pdt["Route"] == "Printed"
        if hit.any() and len(rfd):
            old = float(pdt.loc[hit, "Rs per kg greige"].iloc[0])
            pdt.loc[hit, "Rs per kg greige"] = float(rfd.iloc[0])
            pdt.loc[hit, "Basis"] = "Placeholder: preparation before printing, set equal to RFD / Bleached"
            m["Piece_Dyeing"] = pdt
            log.append(f"Piece_Dyeing, Printed: Rs {old:g} per kg (printing) replaced by Rs {float(rfd.iloc[0]):g} "
                       "per kg for preparation; printing itself is now the print method, Rs per metre")

    st = m["Settings"]
    if not (st["Setting"] == QTY_SETTING).any():
        m["Settings"] = pd.concat([st, pd.DataFrame([{
            "Setting": QTY_SETTING, "Value": "Replaced",
            "Note": "Replaced = a rate card quantity band takes the place of the order size slab, so the two "
                    "are never both charged. Added = both apply; only once the slabs are re-set as what the "
                    "card leaves unexplained"}])], ignore_index=True)
        log.append(f"Settings: '{QTY_SETTING}' = Replaced")
    return log


def main():
    import os

    import masters
    before = {f for f in os.listdir(masters.DATA_DIR) if "before rate card" in f}
    masters.load()          # adds the tables if they are missing, after saving a dated backup
    new = {f for f in os.listdir(masters.DATA_DIR) if "before rate card" in f} - before
    print("Backup: " + ", ".join(new) if new else "The rate card is already in the rate master. Nothing changed.")


if __name__ == "__main__":
    main()
