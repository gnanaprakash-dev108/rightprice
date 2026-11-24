"""Starting yarn rates for poly cotton and linen, so those fabrics can be costed at all.

EVERY RATE HERE IS A PLACEHOLDER: a starting guess with no data behind it. Each is marked so in
the Basis column and the app warns whenever one is used. Replace them from a yarn circular or a
supplier quote. The weaving, sizing, dyeing and finishing rates these fabrics pick up are the
ones measured on 100% cotton, which is a second reason to treat their cost as provisional.

The rows are added once (Settings row 'Blend yarn placeholders added'); deleting or editing them
afterwards is respected. masters.load() calls apply() and saves a dated backup first.
"""
import pandas as pd

FLAG = "Blend yarn placeholders added"
PH = "Placeholder: starting guess, no data"
DATE = "2026-11-24"
ROWS = [  # key, blend, count label, resultant Ne, Rs/kg
    ("Poly Cotton 65/35 30S", "Polyester Cotton", "30S", 30, 215),
    ("Poly Cotton 65/35 40S", "Polyester Cotton", "40S", 40, 235),
    ("Poly Cotton 65/35 45S", "Polyester Cotton", "45S", 45, 245),
    ("Linen 25 Lea", "Linen", "25 Lea", 8.93, 750),      # Ne = lea x 0.357
    ("Linen 40 Lea", "Linen", "40 Lea", 14.29, 900),
    ("Linen 60 Lea", "Linen", "60 Lea", 21.43, 1200),
]
# what the fabric-content step offers, and the yarn blends that belong to each
CONTENTS = {"100% cotton": ("Cotton", "Organic Cotton"), "Poly cotton": ("Polyester Cotton",), "Linen": ("Linen",)}


def content_of(blend):
    b = str(blend)
    for content, starts in CONTENTS.items():
        if any(b == s or b.startswith(s + " ") for s in starts):
            return content
    return "Other"


def apply(m):
    st = m["Settings"]
    if (st["Setting"] == FLAG).any():
        return []
    yr = m["Yarn_Rates"]
    have = set(yr["Yarn key"])
    new = [dict(zip(["Yarn key", "Blend", "Count", "Count Ne (resultant)", "Rate Rs/kg"], r), **{"Rate date": DATE, "Basis": PH})
           for r in ROWS if r[0] not in have]
    if new:
        m["Yarn_Rates"] = pd.concat([yr, pd.DataFrame(new)[yr.columns]], ignore_index=True)
    m["Settings"] = pd.concat([st, pd.DataFrame([{
        "Setting": FLAG, "Value": "Yes",
        "Note": "Poly cotton and linen yarn rates were added once as placeholders. Remove this row to add them again"}])],
        ignore_index=True)
    return [f"Yarn_Rates: {len(new)} placeholder yarns added for poly cotton and linen"]
