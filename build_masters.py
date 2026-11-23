"""Creates data/Rate_Master.xlsx with starting values.

Run once (python build_masters.py). It will NOT overwrite an existing rate
master unless run with --force, so rates edited in the app are safe.

Basis column meaning:
  V1 workbook  = taken from 'Should be Cost V1 23rd Nov.xlsx'
  Placeholder  = a starting guess with no data behind it; replace after
                 mill cost sheets or calibration against purchase orders
  Not set      = left at zero on purpose until there is data
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "Rate_Master.xlsx")
APP_YARN_FILE = os.path.join(HERE, "..", "ABLBL SOURCING ZIP", "data", "Yarn_Inteliigence_Master.xlsx")
if not os.path.exists(APP_YARN_FILE):          # repository layout: the file sits in inputs/
    import paths
    APP_YARN_FILE = paths.find("Yarn_Inteliigence_Master.xlsx")

V1, PH, NS = "V1 workbook", "Placeholder", "Not set"
V1_DATE = "2026-11-23"


def yarn_rates():
    rows = [  # key, blend, count label, resultant Ne, rate
        ("Cotton 12S", "Cotton", "12S", 12, 302), ("Cotton 16S", "Cotton", "16S", 16, 306),
        ("Cotton 24S", "Cotton", "24S", 24, 315), ("Cotton 30S", "Cotton", "30S", 30, 320),
        ("Cotton 30/2", "Cotton", "30/2", 15, 350), ("Cotton 32S", "Cotton", "32S", 32, 330),
        ("Cotton 40S", "Cotton", "40S", 40, 345), ("Cotton 50S", "Cotton", "50S", 50, 395),
        ("Cotton 60S", "Cotton", "60S", 60, 430), ("Cotton 60/2", "Cotton", "60/2", 30, 490),
        ("Cotton 2/100", "Cotton", "2/100", 50, 820), ("Cotton 82/2 Siro", "Cotton", "82/2 Siro", 41, 620),
        ("Cotton Amsler 20S", "Cotton Amsler", "20S", 20, 338), ("Cotton Amsler 24S", "Cotton Amsler", "24S", 24, 372),
        ("Cotton Melange Ecru 30S", "Cotton Melange Ecru", "30S", 30, 328),
        ("Cotton Melange Lt Grey 30S", "Cotton Melange Lt Grey", "30S", 30, 330),
        ("Cotton Melange Charcoal 30S", "Cotton Melange Charcoal", "30S", 30, 395),
        ("Cotton Melange Ecru 40S", "Cotton Melange Ecru", "40S", 40, 356),
        ("Cotton Melange Lt Grey 40S", "Cotton Melange Lt Grey", "40S", 40, 358),
        ("Cotton Melange Charcoal 40S", "Cotton Melange Charcoal", "40S", 40, 420),
        ("Organic Cotton 40S", "Organic Cotton", "40S", 40, 415), ("Organic Cotton 50S", "Organic Cotton", "50S", 50, 465),
        ("Viscose 40/2", "Viscose", "40/2", 20, 287), ("Polyester 75D", "Polyester", "75D", round(5315 / 75, 2), 149),
    ]
    df = pd.DataFrame(rows, columns=["Yarn key", "Blend", "Count", "Count Ne (resultant)", "Rate Rs/kg"])
    df["Rate date"] = V1_DATE
    df["Basis"] = V1
    extra = [  # added 23 Nov 2026 so more purchase-order fabrics can be costed
        ("Cotton 2/80", "Cotton", "2/80", 40, 700, "Market circular (Ichalkaranji, 21 Nov 2026)"),
        ("Cotton 20S", "Cotton", "20S", 20, 310, "Placeholder: midway between 16S and 24S"),
        ("Cotton Slub 20S", "Cotton Slub", "20S", 20, 338, "Placeholder: set equal to Amsler 20S"),
        ("Cotton Slub 24S", "Cotton Slub", "24S", 24, 372, "Placeholder: set equal to Amsler 24S"),
        ("Cotton Slub 30S", "Cotton Slub", "30S", 30, 360, "Placeholder: 30S plus Rs 40, no data"),
    ]
    ex = pd.DataFrame(extra, columns=list(df.columns[:5]) + ["Basis"])
    ex["Rate date"] = V1_DATE
    return pd.concat([df, ex[df.columns]], ignore_index=True)


def market_yarn():
    src = "Ichalkaranji yarn circular, 21 Nov 2026 (ex-GST, read from scanned pages)"
    rows = [
        ("Cotton combed compact", "30s", 307, 314), ("Cotton karded / karded compact", "32s", 295, 314),
        ("Cotton combed compact", "40s", 343, 358), ("Cotton karded compact", "40s", 330, 336),
        ("Cotton combed compact", "50s", 416, 427), ("Cotton combed compact", "60s", 440, 463),
        ("Cotton combed compact", "100s", 725, 800), ("Cotton combed compact", "2/80", 700, 700),
        ("Polyester cotton (PC)", "40s-45s", 243, 295), ("Polyester viscose (PV)", "42s-45s", 226, 282),
        ("Viscose vortex", "30s", 242, 242), ("Viscose vortex", "40s", 268, 268),
    ]
    df = pd.DataFrame(rows, columns=["Yarn", "Count", "Low Rs/kg", "High Rs/kg"])
    df.insert(0, "Date", "2026-11-21")
    df["Source"] = src
    return df


def cotton_prices():
    cols = ["Date", "Variety", "Price", "Unit", "Source"]
    try:
        d = pd.read_excel(APP_YARN_FILE, sheet_name="shankar 6 spot price ")
        d = d[d["Variety"].astype(str).str.strip() == "Shankar 6"].copy()
        d["Date"] = pd.to_datetime(d["Date"], errors="coerce", dayfirst=True)
        d = d.dropna(subset=["Date", "Price"]).sort_values("Date")
        d["Date"] = d["Date"].dt.strftime("%Y-%m-%d")
        d["Unit"] = "Rs/candy"
        d["Source"] = "Sourcing platform: Yarn_Inteliigence_Master.xlsx, Shankar-6 spot sheet"
        return d[cols].drop_duplicates(subset=["Date"]).reset_index(drop=True)
    except Exception as e:  # the tool still works without price history
        print("Cotton price history not loaded:", e)
        return pd.DataFrame(columns=cols)


def weaves():
    rows = [("Plain", "Plain"), ("Twill-2/1", "Twill"), ("Twill-2/2", "Twill"), ("Twill-3/1", "Twill"),
            ("Broken Twill", "Twill"), ("Herringbone", "Twill"), ("Herringbone 2/2", "Twill"),
            ("Dobby", "Dobby/Matt"), ("Matt 2/2", "Dobby/Matt"), ("Royal", "Dobby/Matt"), ("Crepe", "Dobby/Matt"),
            ("Oxford", "Oxford"), ("Satin", "Satin"), ("Satin 4/1", "Satin"),
            ("Jacquard", "Jacquard"), ("Corduroy", "Corduroy")]
    return pd.DataFrame(rows, columns=["Weave", "Weave group"])


def weaving_rates():
    rows = [
        ("Plain", "Yarn Dyed", 0.32, V1), ("Plain", "Piece Dyed", 0.15, V1),
        ("Plain", "RFD / Bleached", 0.15, PH), ("Plain", "Printed", 0.15, PH),
        ("Twill", "Yarn Dyed", 0.32, V1), ("Twill", "Piece Dyed", 0.18, PH),
        ("Twill", "RFD / Bleached", 0.18, PH), ("Twill", "Printed", 0.18, PH),
        ("Dobby/Matt", "Yarn Dyed", 0.45, V1), ("Dobby/Matt", "Piece Dyed", 0.28, PH),
        ("Dobby/Matt", "RFD / Bleached", 0.28, PH), ("Dobby/Matt", "Printed", 0.28, PH),
        ("Oxford", "Yarn Dyed", 0.32, PH), ("Oxford", "Piece Dyed", 0.16, PH),
        ("Oxford", "RFD / Bleached", 0.16, PH), ("Oxford", "Printed", 0.16, PH),
        ("Satin", "Yarn Dyed", 0.40, PH), ("Satin", "Piece Dyed", 0.22, PH),
        ("Satin", "RFD / Bleached", 0.22, PH), ("Satin", "Printed", 0.22, PH),
        ("Corduroy", "Yarn Dyed", 0.40, V1), ("Corduroy", "Piece Dyed", 0.30, PH),
        ("Corduroy", "RFD / Bleached", 0.30, PH), ("Corduroy", "Printed", 0.30, PH),
        ("Jacquard", "Yarn Dyed", 0.60, PH), ("Jacquard", "Piece Dyed", 0.45, PH),
        ("Jacquard", "RFD / Bleached", 0.45, PH), ("Jacquard", "Printed", 0.45, PH),
    ]
    return pd.DataFrame(rows, columns=["Weave group", "Route", "Rs per pick", "Basis"])


def weaving_uplifts():
    patterns = ["Solid", "Check", "Pin Checks", "Graph checks", "Tartan Checks", "Engineered Check", "Stripe",
                "Vertical stripes", "Engineered Striper", "Textured", "Dual tone", "Jacquard", "Print",
                "Floral", "Geometric"]
    rows = [("Pattern", p, 0.0, NS) for p in patterns]
    rows += [("Loom type", "Airjet", 0.0, NS), ("Loom type", "Rapier", 0.0, NS)]
    return pd.DataFrame(rows, columns=["Type", "Value", "Uplift % on weaving rate", "Basis"])


def sizing_rates():
    rows = [("Yarn Dyed", 40, 30, V1), ("Yarn Dyed", 60, 40, V1), ("Yarn Dyed", 999, 50, V1),
            ("Other", 40, 15, V1), ("Other", 60, 20, PH), ("Other", 999, 25, PH)]
    return pd.DataFrame(rows, columns=["Route type", "Warp count up to (Ne)", "Rs per kg warp", "Basis"])


def yarn_dyeing():
    rows = [("Undyed", 0, V1), ("Light", 130, PH), ("Medium", 150, V1), ("Dark", 190, V1),
            ("Melange top-up", 75, V1)]
    return pd.DataFrame(rows, columns=["Shade", "Rs per kg yarn", "Basis"])


def piece_dyeing():
    rows = [("Piece Dyed", "Light", 140, PH), ("Piece Dyed", "Medium", 160, V1), ("Piece Dyed", "Dark", 185, PH),
            ("RFD / Bleached", "Any", 60, PH), ("Printed", "Any", 180, PH)]
    return pd.DataFrame(rows, columns=["Route", "Shade", "Rs per kg greige", "Basis"])


def finishing_rates():
    rows = [("Normal", 40, 0, V1)]
    ph = [("F- Normal Soft", 45, 5), ("F- Soft Finish", 45, 5), ("F- Easy Care", 60, 20),
          ("F- ETI Easy to Iron", 65, 25), ("F- LA Liquid Ammonia", 90, 50), ("F- LA + ETI", 110, 70),
          ("F- LA+Easy Care", 110, 70), ("F- LAMC Liquid Ammonia Moist Cure", 120, 80), ("LAMC+HWRA", 130, 90),
          ("F- Mercerized", 60, 20), ("F- PEACH", 55, 15), ("F- Brushed-1 side", 55, 15), ("F- Aero", 60, 20),
          ("F- Wicking", 55, 15), ("F- Baby Skin Finish", 55, 15), ("F- Apricot Touch", 55, 15),
          ("Antibacterial finish + Quik Dry Finish", 65, 25), ("F- LA+MOIST CURE+Silk Protein", 130, 90)]
    rows += [(a, b, c, PH) for a, b, c in ph]
    return pd.DataFrame(rows, columns=["Finish", "Rs per kg greige (yarn dyed)",
                                       "Rs per kg greige (piece dyed / RFD / printed)", "Basis"])


def class_defaults():
    cols = ["Weave group", "Route", "Warp crimp", "Warp wastage", "Weft crimp (old method only)",
            "Weft wastage", "Process wastage", "Overhead", "Margin", "Basis"]
    rows = [
        ("Plain", "Piece Dyed", 0.05, 0.05, 0.10, 0.03, 0.065, 0.04, 0.07, V1),
        ("Plain", "Yarn Dyed", 0.05, 0.05, 0.10, 0.03, 0.05, 0.05, 0.08, V1),
        ("Twill", "Yarn Dyed", 0.05, 0.03, 0.08, 0.02, 0.03, 0.04, 0.07, V1),
        ("Dobby/Matt", "Yarn Dyed", 0.05, 0.03, 0.08, 0.02, 0.03, 0.04, 0.07, V1),
        ("Corduroy", "Yarn Dyed", 0.05, 0.05, 0.10, 0.03, 0.05, 0.05, 0.08, V1),
        ("Default", "Any", 0.05, 0.05, 0.10, 0.03, 0.05, 0.05, 0.08, PH),
    ]
    return pd.DataFrame(rows, columns=cols)


def mill_tier():
    rows = [("Tier 1 composite", 0.0, 0.0, NS), ("Tier 2", 0.0, 0.0, NS), ("Job-work", 0.0, 0.0, NS)]
    return pd.DataFrame(rows, columns=["Mill tier", "Overhead add (points)", "Margin add (points)", "Basis"])


def order_slab():
    rows = [("Above 10,000 m", 0.0, NS), ("3,000 to 10,000 m", 0.0, NS), ("Below 3,000 m", 0.0, NS)]
    return pd.DataFrame(rows, columns=["Order size", "Overhead add (points)", "Basis"])


def supplier_benchmarks():
    cols = ["Supplier", "Year", "Sales Rs cr", "Material %", "Employee %", "Power and fuel %",
            "Operating profit %", "Depreciation %", "Interest %", "Left after both %", "Source"]
    s, m = "screener.in", "MarketsMojo (check against annual report)"
    rows = [
        ("Vardhman Textiles", "2025-26", 9869, 55.2, 9.4, 9.1, 12.6, 4.7, 0.9, 7.0, f"{s}; power: {m}"),
        ("Nitin Spinners", "2025-26", 3208, 62.8, 6.5, 9.1, 14.1, 4.6, 2.2, 7.3, f"{s}; power: annual report"),
        ("Arvind", "2025-26", 9303, 48.3, 12.9, 6.8, 11.4, 3.1, 2.4, 5.9, f"{s}; power is 2024-25, {m}"),
        ("Banswara Syntex", "2025-26", 1356, 39.2, 23.7, 9.9, 9.5, 3.9, 3.2, 2.4, f"{s}; power: company presentation"),
        ("Raymond Lifestyle", "2025-26", 6888, 46.0, 13.5, 3.1, 9.8, 5.4, 3.6, 0.8, f"{s}; power: {m}"),
        ("Nahar Industrial", "2025-26", 1408, 58.0, 14.1, 10.7, 4.3, 3.6, 3.1, -2.4, f"{s}; power: {m}"),
        ("Rajapalayam Mills", "2025-26", 942, 51.5, 13.9, 5.9, 13.0, 8.0, 9.8, -4.8,
         f"{s}; power: annual report, net of own wind power"),
    ]
    return pd.DataFrame(rows, columns=cols)


def settings():
    rows = [
        ("Yarn weight constant K", 0.00059, "kg per end-metre for Ne 1, from the V1 workbook"),
        ("Finishing shrinkage", 0.04, "Share of length lost in finishing; 4% as in the V1 corrections"),
        ("Reed space factor", 1.155, "Reed space = finished width x this, when reed space is left blank"),
        ("Weft method", "Corrected", "Corrected = wastage on reed space. Old = crimp on reed space"),
    ]
    return pd.DataFrame(rows, columns=["Setting", "Value", "Note"])


SHEETS = {
    "Yarn_Rates": yarn_rates, "Market_Yarn": market_yarn, "Cotton_Prices": cotton_prices,
    "Weaves": weaves, "Weaving_Rates": weaving_rates, "Weaving_Uplifts": weaving_uplifts,
    "Sizing_Rates": sizing_rates, "Yarn_Dyeing": yarn_dyeing, "Piece_Dyeing": piece_dyeing,
    "Finishing_Rates": finishing_rates, "Class_Defaults": class_defaults, "Mill_Tier": mill_tier,
    "Order_Slab": order_slab, "Supplier_Benchmarks": supplier_benchmarks, "Settings": settings,
}


def build(force=False):
    if os.path.exists(OUT) and not force:
        print("Rate master already exists, left untouched:", OUT)
        return OUT
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        for name, fn in SHEETS.items():
            df = fn()
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 60)
            ws.freeze_panes = "A2"
    print("Created", OUT)
    return OUT


if __name__ == "__main__":
    build(force="--force" in sys.argv)
