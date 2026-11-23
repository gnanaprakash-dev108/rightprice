"""Brings the PLM master data's lists into the rate master without touching any rate.

Reads 'Master Data- Pending to WFX New.xlsx' (BlendsMapping, FabricDropDown) and
data/plm_value_counts.xlsx, then:
  * adds the sheet Content_Groups: every blend spelling folded into a short list of groups
  * adds any PLM weave type missing from the Weaves sheet, with its weave group
Existing rows and all rates are left as they are.   Run: python refresh_groups.py
"""
import os

import pandas as pd
from openpyxl import load_workbook

import grouping
import masters
import paths

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER_DATA = paths.find("Master Data- Pending to WFX New.xlsx")
PLM_COUNTS = os.path.join(HERE, "data", "plm_value_counts.xlsx")
PO_SPECS = os.path.join(HERE, "data", "plm_specs_for_po.csv")
COSTED_NOW = {"100% cotton"}


def main():
    m = dict(masters.load())
    wb = load_workbook(open(MASTER_DATA, "rb"), read_only=True)
    blends = {str(r[4]).strip() for n, r in enumerate(wb["BlendsMapping"].iter_rows(values_only=True)) if n and r[4]}
    rows = [r for r in wb["FabricDropDown"].iter_rows(values_only=True)]
    wcol = rows[0].index("Weave Type")
    plm_weaves = {str(r[wcol]).strip() for r in rows[1:] if r[wcol]}

    plm_blend = pd.read_excel(PLM_COUNTS, sheet_name="blend_name").dropna(subset=["Value"])
    plm_blend["Group"] = plm_blend["Value"].map(grouping.blend_group)
    po = pd.read_csv(PO_SPECS, dtype=str, usecols=["article_cust_blend_name"]).fillna("")
    po["Group"] = po["article_cust_blend_name"].map(grouping.blend_group)

    md = pd.Series([grouping.blend_group(b) for b in blends]).value_counts()
    stretch = pd.Series([grouping.blend_group(b) for b in blends if grouping.has_stretch(b)]).value_counts()
    cg = pd.DataFrame({"Blend spellings in master data": md,
                       "...of which with stretch": stretch,
                       "PLM fabric codes": plm_blend.groupby("Group")["Rows"].sum(),
                       "Fabric codes in purchase orders": po["Group"].value_counts()}).fillna(0).astype(int)
    cg = cg.sort_values("Fabric codes in purchase orders", ascending=False).rename_axis("Content group").reset_index()
    cg["Costed in this version"] = cg["Content group"].map(lambda g: "Yes" if g in COSTED_NOW else "Not yet")
    m["Content_Groups"] = cg

    wv = m["Weaves"]
    have = set(wv["Weave"])
    plm_w = pd.read_excel(PLM_COUNTS, sheet_name="weavetype_name").dropna(subset=["Value"])
    plm_weaves |= {str(v).strip() for v in plm_w["Value"]}
    add, skipped = [], []
    for w in sorted(plm_weaves - have):
        g = grouping.weave_group(w)
        (add if g else skipped).append((w, g))
    if add:
        m["Weaves"] = pd.concat([wv, pd.DataFrame(add, columns=["Weave", "Weave group"])], ignore_index=True)
    masters.save(m)
    print(cg.to_string(index=False))
    print(f"Weaves: {len(have)} before, {len(add)} added. Not woven or not recognised, left out:",
          [w for w, _ in skipped])


if __name__ == "__main__":
    main()
