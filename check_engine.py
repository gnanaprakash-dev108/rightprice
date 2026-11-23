"""Checks the engine against the seven qualities in the V1 workbook.

Targets are the 'With corrections (weft + 4% shrinkage)' row of the hidden
'Earlier Qualities' sheet. Run: python check_engine.py
"""
import engine
import masters

F = ["warp_ne", "weft_ne", "warp_rate", "weft_rate", "warp_dye", "weft_dye", "epi", "ppi", "width_in", "reed_in",
     "warp_crimp", "warp_wastage", "weft_wastage", "weaving_rate", "sizing_rate", "finishing_rate",
     "piece_dye_rate", "extra_per_m", "process_wastage", "overhead", "margin"]
CASES = {  # values copied from the Earlier Qualities sheet; yarn rate = override where one was typed
    "Qlty-11AS": ([30, 40, 320, 345, 0, 0, 108, 90, 58, 67, .05, .05, .03, .15, 15, 0, 160, 0, .065, .04, .07], 156.41),
    "Qlty-1":    ([40, 40, 345, 345, 150, 150, 132, 84, 58, 67, .05, .03, .02, .45, 30, 40, 0, 0, .03, .04, .07], 181.40),
    "Ramco-1":   ([40, 40, 390, 390, 150, 150, 132, 90, 59, 68, .05, .03, .02, .32, 30, 40, 0, 0, .03, .04, .07], 188.42),
    "Ramco-2":   ([50, 50, 460, 460, 190, 190, 146, 92, 59, 67, .04, .03, .02, .45, 40, 60, 0, 0, .03, .04, .07], 209.58),
    "Qlty-2":    ([50, 50, 820, 820, 160, 160, 164, 116, 58, 67, .05, .05, .03, .45, 50, 60, 0, 0, .05, .05, .08], 353.09),
    "Qlty-3":    ([41, 60, 620, 430, 150, 150, 172, 80, 58, 67, .05, .05, .03, .32, 30, 50, 0, 0, .05, .05, .08], 240.49),
    "Qlty-4":    ([40, 40, 395, 395, 75, 75, 92, 156, 58, 66, .05, .05, .03, .40, 30, 50, 0, 12, .05, .05, .08], 248.94),
}


def main():
    ok = True
    for name, (vals, target) in CASES.items():
        inp = dict(zip(F, vals), shrinkage=0.04, k=0.00059)
        got = engine.compute(inp)["total_per_m"]
        good = abs(got - target) < 0.01
        ok &= good
        print(f"{name:10s} engine {got:8.2f}  V1 {target:8.2f}  {'OK' if good else 'MISMATCH'}")

    # Same fabric through the drop-downs: every rate comes from the rate master.
    m = masters.load()
    r = masters.cost(masters.EXAMPLE_ROW, m)
    good = abs(r["total_per_m"] - 181.40) < 0.01
    ok &= good
    print(f"Qlty-1 via drop-downs {r['total_per_m']:.2f}  V1 181.40  {'OK' if good else 'MISMATCH'}")
    print(f"  Rs/kg {r['per_kg']:.1f}, GSM {r['gsm']:.1f}, placeholders: {r['placeholders'] or 'none'}")
    for b in r["buckets"]:
        print(f"  {b['name']:22s} {b['amount']:7.2f}  {b['pct']:.1%}")

    # Template round trip
    import io
    import pandas as pd
    df = pd.read_excel(io.BytesIO(masters.make_template(m)), sheet_name="Fabrics")
    out = masters.cost_many(df, m)
    good = len(out) == 1 and abs(out["Should-cost Rs/m"].iloc[0] - 181.40) < 0.01 and out["Error"].iloc[0] == ""
    ok &= good
    print("Template round trip", "OK" if good else "MISMATCH", out[["Fabric code", "Should-cost Rs/m", "Error"]].to_dict("records"))
    bad = masters.cost_many(pd.DataFrame([dict(masters.EXAMPLE_ROW, Weave="Not a weave")]), m)
    good = "not on the list" in bad["Error"].iloc[0]
    ok &= good
    print("Bad value rejected", "OK" if good else "MISMATCH", "-", bad["Error"].iloc[0])
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
