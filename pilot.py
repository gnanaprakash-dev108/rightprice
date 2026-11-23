"""Pilot: should-cost against actual ex-mill purchase order prices.

Reads the SAP purchase order export and the sourcing platform's PLM fabric code
list extract (data/plm_specs_for_po.csv, made by plm_extract.py), keeps priced rupee-per-metre bulk orders whose material code
has specs, costs the 100% cotton wovens with the current rate master and writes
pilot/Pilot_Results.xlsx.   Run: python pilot.py
"""
import os
import re
import warnings

import pandas as pd

import masters
import paths

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
PO_FILE = paths.find("Fabric _ 3Months_4746.xlsx")
OUT = os.path.join(HERE, "pilot", "Pilot_Results.xlsx")

WEAVE_MAP = {"plain": "Plain", "plain-solid": "Plain", "2/1 twill": "Twill-2/1", "2/2 twill": "Twill-2/2",
             "3/1 twill": "Twill-3/1", "twill": "Twill-2/1", "dobby": "Dobby", "birds eye": "Dobby",
             "fancy": "Dobby", "dobby double face": "Dobby", "honeycomb": "Dobby", "oxford": "Oxford",
             "2/2 matt": "Matt 2/2", "matt": "Matt 2/2", "satin 5/1": "Satin", "satin": "Satin",
             "satin 4/1": "Satin 4/1", "hbt": "Herringbone", "3/3 hbt": "Herringbone",
             "herringbone": "Herringbone", "jacquard": "Jacquard"}
ROUTE_MAP = {"pd": "Piece Dyed", "yd": "Yarn Dyed", "print": "Printed", "rfd": "RFD / Bleached",
             "white": "RFD / Bleached"}
FINISH_MAP = {"normal soft": "F- Normal Soft", "normal": "Normal", "noraml": "Normal", "rfd": "Normal",
              "eti": "F- ETI Easy to Iron", "la": "F- LA Liquid Ammonia", "la la": "F- LA Liquid Ammonia",
              "la+eti": "F- LA + ETI", "la-eti": "F- LA + ETI", "la + eti + soft": "F- LA + ETI",
              "la+eti+soft": "F- LA + ETI", "la+eti soft": "F- LA + ETI", "la+soft": "F- LA Liquid Ammonia",
              "easy care": "F- Easy Care", "peach": "F- PEACH", "soft": "F- Soft Finish",
              "mercerized": "F- Mercerized", "mercerised": "F- Mercerized"}


def clean(v):
    return "" if pd.isna(v) else str(v).strip()


def parse_count_side(txt, yarn_by_count):
    """'40' -> Cotton 40S, '2/80' -> ply key if the yarn master has it. Else None."""
    t = txt.strip().lower().replace("'s", "").replace("s", "")
    if re.fullmatch(r"\d+", t):
        return yarn_by_count.get(("single", int(t)))
    m = re.fullmatch(r"2/(\d+)", t) or re.fullmatch(r"(\d+)/2", t)
    if m:
        return yarn_by_count.get(("ply", int(m.group(1))))
    return None


def parse_width_in(txt):
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", txt)]
    if not nums:
        return None
    w = max(n for n in nums[:2])
    if w > 100:          # centimetres
        return round(w / 2.54, 1)
    return w if 30 <= w <= 75 else None


def yarn_lookup(m):
    """Map (single|ply, count) to a plain-cotton yarn key in the yarn master."""
    out = {}
    for _, y in m["Yarn_Rates"].iterrows():
        blend, c = str(y["Blend"]), str(y["Count"]).lower()
        special = {"Cotton Amsler": "ams", "Cotton Slub": "slub"}.get(blend)
        if special and re.fullmatch(r"\d+s", c):
            out[(special, int(c[:-1]))] = y["Yarn key"]
        if blend != "Cotton":
            continue
        if re.fullmatch(r"\d+s", c):
            out[("single", int(c[:-1]))] = y["Yarn key"]
        mm = re.fullmatch(r"2/(\d+)", c) or re.fullmatch(r"(\d+)/2(?: siro)?", c)
        if mm:
            out[("ply", int(mm.group(1)))] = y["Yarn key"]
    return out


PLM_SPECS = os.path.join(HERE, "data", "plm_specs_for_po.csv")
GROUP_WEAVE = {"Plain": "Plain", "Twill": "Twill-2/1", "Dobby/Matt": "Dobby", "Oxford": "Oxford",
               "Satin": "Satin", "Jacquard": "Jacquard", "Corduroy": "Corduroy"}
PLM_ROUTE = {"yarn dyed": "Yarn Dyed", "piece dyed": "Piece Dyed", "print": "Printed",
             "bleached": "RFD / Bleached"}


def norm(t):
    return re.sub(r"[^a-z0-9+]", "", str(t).lower())


def plm_count(txt, yarn_by_count):
    """PLM count spellings: 40, 40s, 40/1, CM40, 2/80s, 80/2, 24 Ams, 20s Slub."""
    t = str(txt).strip().lower().replace(" ", "").strip("()")
    kind = "single"
    mm = re.fullmatch(r"(?:bx)?(\d+)(?:/1)?s?(ams|amsler|slub|slu|sl)", t)
    if mm:
        return yarn_by_count.get(("ams" if mm.group(2).startswith("ams") else "slub", int(mm.group(1))))
    t = re.sub(r"^(cm|cpt|cw|ne)", "", t)
    t = re.sub(r"(s|ne|'s)$", "", t)
    t = re.sub(r"^(\d+)/1$", r"", t)
    if re.fullmatch(r"\d+", t):
        return yarn_by_count.get((kind, int(t)))
    mm = re.fullmatch(r"2/(\d+)", t) or re.fullmatch(r"(\d+)/2", t)
    if mm:
        return yarn_by_count.get(("ply", int(mm.group(1))))
    return None


def build_inputs():
    """Purchase-order fabrics turned into tool inputs: (masters, inputs, not costed, funnel)."""
    import grouping
    m = masters.load()
    ybc = yarn_lookup(m)
    tool_weaves = set(m["Weaves"]["Weave"])
    fin_by_norm = {norm(f).lstrip("f"): f for f in m["Finishing_Rates"]["Finish"]}
    fin_by_norm.update({"regular": "Normal", "normal": "Normal", "etieasytoiron": "F- ETI Easy to Iron",
                        "liquidammoniamoistcure": "F- LAMC Liquid Ammonia Moist Cure",
                        "liquidammonia+mc": "F- LAMC Liquid Ammonia Moist Cure",
                        "liquidammonia+easycare": "F- LA+Easy Care", "la+eti+soft": "F- LA + ETI",
                        "brushed1side": "F- Brushed-1 side", "peach": "F- PEACH"})

    po = pd.read_excel(PO_FILE)
    po = po[po["Purchasing Document"].notna()]
    bulk = po[po["Purchasing Doc. Type"].isin(["BO", "ZLOI", "BF"]) & (po["Net Price"] > 0)
              & po["Deletion Indicator"].isna() & (po["Currency"] == "INR") & (po["Order Unit"] == "M")].copy()
    bulk["Material"] = bulk["Material"].astype(str).str.strip()
    bulk["value"] = bulk["Net Price"] * bulk["Order Quantity"]
    g = bulk.groupby("Material").agg(qty=("Order Quantity", "sum"), value=("value", "sum"),
                                     lines=("Item", "size"))
    g["PO price Rs/m"] = g["value"] / g["qty"]
    top = (bulk.groupby(["Material", "Name of Supplier"])["Order Quantity"].sum().reset_index()
           .sort_values("Order Quantity", ascending=False).drop_duplicates("Material")
           .set_index("Material")["Name of Supplier"])
    g["Supplier"] = top

    plm = pd.read_csv(PLM_SPECS, dtype=str).fillna("")
    plm.columns = [c.replace("article_", "").replace("cust_", "") for c in plm.columns]
    spec = plm[plm["code"].isin(g.index)].drop_duplicates("code").set_index("code")
    spec["Content group"] = spec["blend_name"].map(grouping.blend_group)

    funnel = [("Priced rupee-per-metre bulk materials", len(g)), ("...with specs in the PLM list", len(spec)),
              ("...woven", int((spec["productgroup_name"] == "Woven").sum()))]
    rows, reasons = [], []
    for code, s in spec.iterrows():
        if s["productgroup_name"] != "Woven":
            continue
        why = None
        route = PLM_ROUTE.get(s["dyemethod_name"].lower())
        wg = grouping.weave_group(s["weavetype_name"])
        weave = s["weavetype_name"] if s["weavetype_name"] in tool_weaves else GROUP_WEAVE.get(wg)
        warp, weft = plm_count(s["warpcount"], ybc), plm_count(s["weftcount"], ybc)
        try:
            epi, ppi, w = float(s["epi"] or 0), float(s["ppi"] or 0), float(s["finishedwidth"] or 0)
        except ValueError:
            epi = ppi = w = 0
        uom = s["finishedwidth_uom"].lower()
        width = w / 2.54 if uom == "cm" else (w * 39.37 if uom == "m" else w)
        if s["Content group"] != "100% cotton":
            why = "Not 100% cotton: " + s["Content group"]
        elif route is None:
            why = f"Dye method not mapped: {s['dyemethod_name'] or 'blank'}"
        elif weave is None:
            why = f"Weave not mapped: {s['weavetype_name'] or 'blank'}"
        elif epi <= 20 or ppi <= 20:
            why = "EPI or PPI missing"
        elif not 30 <= width <= 75:
            why = "Width missing or not plausible"
        elif warp is None or weft is None:
            why = f"Count not in yarn master: {s['warpcount'] or 'blank'} x {s['weftcount'] or 'blank'}"
        if why:
            reasons.append({"Fabric code": code, "Reason": why, "Content": s["blend_name"],
                            "Warp count": s["warpcount"], "Weft count": s["weftcount"],
                            "Weave": s["weavetype_name"], "Dye method": s["dyemethod_name"],
                            "PO metres": g.loc[code, "qty"], "PO price Rs/m": round(g.loc[code, "PO price Rs/m"], 2)})
            continue
        fkey = norm(s["finish_name"]).lstrip("f")
        rows.append({"Fabric code": code,
                     "Description": f"{s['blend_name']} {s['warpcount']}x{s['weftcount']} / {epi:g}x{ppi:g} {s['weavetype_name']}",
                     "Supplier": g.loc[code, "Supplier"], "Route": route, "Weave": weave,
                     "Finish": fin_by_norm.get(fkey, "Normal"), "Warp yarn": warp, "Weft yarn": weft,
                     "EPI": epi, "PPI": ppi, "Finished width (in)": round(width, 1),
                     "Quoted price (Rs/m)": round(g.loc[code, "PO price Rs/m"], 2),
                     "Finish as written": s["finish_name"], "Finish mapped": fkey in fin_by_norm,
                     "PO metres": g.loc[code, "qty"], "PO lines": g.loc[code, "lines"]})

    return m, pd.DataFrame(rows), pd.DataFrame(reasons), funnel


def main():
    m, inp, rej, funnel = build_inputs()
    slabs = m["Order_Slab"]["Order size"].tolist()     # order size from the PO quantity, where slabs match
    by_metres = {"Below 1,000 m": (0, 1000), "1,000 to 3,000 m": (1000, 3000), "3,000 m and above": (3000, 1e12)}
    if set(by_metres) <= set(slabs):
        inp["Order size"] = inp["PO metres"].map(
            lambda q: next(k for k, (lo, hi) in by_metres.items() if lo <= q < hi))
    funnel.append(("...100% cotton", int((~rej["Reason"].str.startswith("Not 100% cotton")).sum()) + len(inp)))
    funnel.append(("...with every field readable (costed)", len(inp)))

    res = masters.cost_many(inp, m)
    extra = ["Route", "Weave", "Finish", "Finish as written", "Finish mapped", "Warp yarn", "Weft yarn", "EPI",
             "PPI", "Finished width (in)", "PO metres", "PO lines"]
    res = pd.concat([res, inp[extra]], axis=1).rename(columns={"Quoted Rs/m": "PO price Rs/m",
                                                                "Gap Rs/m": "PO minus should-cost Rs/m",
                                                                "Gap %": "PO above should-cost %"})
    ok = res[res["Error"] == ""].copy()
    ok["Weave group"] = ok["Weave"].map(m["Weaves"].set_index("Weave")["Weave group"])
    ok["Excess Rs"] = ok["PO minus should-cost Rs/m"] * ok["PO metres"]

    def summarise(df, by):
        return df.groupby(by).agg(Fabrics=("Fabric code", "size"), Metres=("PO metres", "sum"),
                                  **{"Median PO Rs/m": ("PO price Rs/m", "median"),
                                     "Median should-cost Rs/m": ("Should-cost Rs/m", "median"),
                                     "Median gap %": ("PO above should-cost %", "median"),
                                     "Within 5%": ("PO above should-cost %", lambda s: (s.abs() <= 5).mean()),
                                     "Within 10%": ("PO above should-cost %", lambda s: (s.abs() <= 10).mean())}
                                  ).round(3).sort_values("Fabrics", ascending=False).reset_index()

    overall = pd.DataFrame([{"Fabrics costed": len(ok), "Median gap %": ok["PO above should-cost %"].median(),
                             "Within 5%": (ok["PO above should-cost %"].abs() <= 5).mean(),
                             "Within 10%": (ok["PO above should-cost %"].abs() <= 10).mean(),
                             "Within 20%": (ok["PO above should-cost %"].abs() <= 20).mean(),
                             "PO above should-cost (share)": (ok["PO above should-cost %"] > 0).mean()}]).round(3)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        pd.DataFrame(funnel, columns=["Step", "Fabrics"]).to_excel(xw, sheet_name="Funnel", index=False)
        overall.to_excel(xw, sheet_name="Overall", index=False)
        summarise(ok, ["Route", "Weave group"]).to_excel(xw, sheet_name="By route and weave", index=False)
        summarise(ok, "Supplier").to_excel(xw, sheet_name="By supplier", index=False)
        ok.sort_values("PO above should-cost %", ascending=False).to_excel(xw, sheet_name="Fabrics", index=False)
        res[res["Error"] != ""].to_excel(xw, sheet_name="Costing errors", index=False)
        rej.to_excel(xw, sheet_name="Not costed", index=False)
        if len(rej):
            rej["Reason"].str.replace(r":.*", "", regex=True).value_counts().rename_axis("Reason")\
                .reset_index(name="Fabrics").to_excel(xw, sheet_name="Not costed summary", index=False)
    print(pd.DataFrame(funnel, columns=["Step", "Fabrics"]).to_string(index=False))
    print(overall.to_string(index=False))
    print(summarise(ok, ["Route", "Weave group"]).to_string(index=False))
    print(summarise(ok, "Supplier").head(15).to_string(index=False))
    if len(rej):
        print(rej["Reason"].str.replace(r":.*", "", regex=True).value_counts().to_string())
        cr = rej[rej["Reason"].str.startswith("Count")]
        miss = pd.concat([cr["Warp count"], cr["Weft count"]]).str.lower().str.replace(" ", "")
        print("Counts in fabrics that could not be costed:", miss.value_counts().head(30).to_dict())
        print("Unmapped dye methods:", rej[rej["Reason"].str.startswith("Dye")]["Dye method"].value_counts().to_dict())
    print(ok["PO above should-cost %"].describe().round(1).to_string())
    print("Finish not mapped:", int((~ok["Finish mapped"]).sum()), ok[~ok["Finish mapped"]]["Finish as written"].value_counts().head(12).to_dict())
    print("Saved", OUT)


if __name__ == "__main__":
    main()
