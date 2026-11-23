"""One streaming pass over the PLM fabric code list (a very large workbook).

Writes, into data/:
  plm_specs_for_po.csv   spec rows for material codes that appear in the purchase order file
  plm_value_counts.xlsx  how often each value occurs in the grouping columns (all rows)
Both source files are only read.   Run: python plm_extract.py
"""
import collections
import csv
import os
import time

import pandas as pd
from openpyxl import load_workbook

import paths

HERE = os.path.dirname(os.path.abspath(__file__))
PLM = paths.find("PLM FABRIC CODE LIST20261123-150404-815777.xls")  # really an .xlsx
PO_FILE = paths.find("Fabric _ 3Months_4746.xlsx")
OUT_SPECS = os.path.join(HERE, "data", "plm_specs_for_po.csv")
OUT_COUNTS = os.path.join(HERE, "data", "plm_value_counts.xlsx")

KEEP = ["article_code", "article_lifecyclestage_name", "article_productgroup_name",
        "article_productsubcategory_name", "article_division_name", "article_cust_dyemethod_name",
        "article_cust_blend_name", "article_cust_weight", "article_cust_weight_uom",
        "article_cust_weavetype_name", "article_cust_developmentpurchasecost",
        "article_cust_developmentpurchasecost_currency", "article_cust_source_name",
        "article_cust_finishedwidth", "article_cust_finishedwidth_uom", "article_cust_genericname_name",
        "article_supplier_name", "article_cust_patterndetails_name", "article_cust_pattern_name",
        "article_cust_finish_name", "article_cust_rfdindigo_name", "article_cust_epi", "article_cust_ppi",
        "article_cust_yarndetails_name", "article_cust_warpcount", "article_cust_weftcount"]
COUNT_COLS = ["article_productgroup_name", "article_cust_dyemethod_name", "article_cust_blend_name",
              "article_cust_weavetype_name", "article_cust_finish_name", "article_cust_pattern_name",
              "article_cust_patterndetails_name", "article_cust_yarndetails_name", "article_cust_warpcount",
              "article_cust_weftcount", "article_cust_source_name", "article_lifecyclestage_name",
              "article_cust_genericname_name", "article_cust_rfdindigo_name"]


def main():
    t = time.time()
    po = pd.read_excel(PO_FILE, usecols=["Material"])
    codes = set(po["Material"].dropna().astype(str).str.strip())
    print("PO material codes:", len(codes))
    wb = load_workbook(open(PLM, "rb"), read_only=True)
    ws = wb.worksheets[0]
    counters = {c: collections.Counter() for c in COUNT_COLS}
    n = kept = with_const = 0
    with open(OUT_SPECS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(KEEP)
        idx = cidx = None
        for row in ws.iter_rows(values_only=True):
            if idx is None:
                pos = {h: i for i, h in enumerate(row)}
                idx = [pos[c] for c in KEEP]
                cidx = [(c, pos[c]) for c in COUNT_COLS]
                epi_i = pos["article_cust_epi"]
                continue
            n += 1
            for c, i in cidx:
                v = row[i]
                counters[c]["" if v is None else str(v).strip()] += 1
            try:
                if float(row[epi_i] or 0) > 1:
                    with_const += 1
            except ValueError:
                pass
            code = "" if row[0] is None else str(row[0]).strip()
            if code in codes:
                kept += 1
                w.writerow(["" if row[i] is None else row[i] for i in idx])
            if n % 100000 == 0:
                print(n, "rows", round(time.time() - t), "s", flush=True)
    print("PLM rows:", n, "| rows for PO codes:", kept, "| rows with EPI above 1:", with_const)
    with pd.ExcelWriter(OUT_COUNTS, engine="openpyxl") as xw:
        for c, ctr in counters.items():
            pd.DataFrame(ctr.most_common(5000), columns=["Value", "Rows"]).to_excel(
                xw, sheet_name=c.replace("article_", "").replace("cust_", "")[:31], index=False)
    print("Saved", OUT_SPECS, "and", OUT_COUNTS, "in", round(time.time() - t), "s")


if __name__ == "__main__":
    main()
