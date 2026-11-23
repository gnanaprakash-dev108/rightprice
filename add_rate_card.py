"""Adds the mill rate card tables to data/Rate_Master.xlsx.

Adds only: the sheets Print_Method, Dobby_Upcharge, Weft_Upcharge and
Order_Quantity, two upcharge columns on Finishing_Rates, and the card's finishes
that were not on the list. No existing rate is changed. A dated copy of the rate
master is saved first.   Run once: python add_rate_card.py
"""
import datetime as dt
import shutil

import pandas as pd

import masters


def main():
    on_disk = pd.read_excel(masters.MASTER_PATH, sheet_name=None)
    if all(s in on_disk for s in masters.CARD_SHEETS) and "Upcharge Rs per m" in on_disk["Finishing_Rates"]:
        print("The rate master already has the rate card tables; nothing done.")
        return
    backup = masters.MASTER_PATH.replace(".xlsx", f" before rate card {dt.datetime.now():%Y%m%d-%H%M}.xlsx")
    shutil.copy(masters.MASTER_PATH, backup)
    masters.save(masters.upgrade(on_disk))
    after = pd.read_excel(masters.MASTER_PATH, sheet_name=None)
    for name, df in on_disk.items():           # every rate that was there must still be there, unchanged
        now = after[name][df.columns].iloc[:len(df)]
        if not now.astype(str).equals(df.astype(str)):
            shutil.copy(backup, masters.MASTER_PATH)
            raise SystemExit(f"Sheet {name} changed on saving; the rate master was restored from the backup.")
    print("Added:", ", ".join(masters.CARD_SHEETS), "and", len(after["Finishing_Rates"]) - len(on_disk["Finishing_Rates"]),
          "finishes. Existing rates unchanged.")
    print("Backup:", backup)


if __name__ == "__main__":
    main()
