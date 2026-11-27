"""Checks the engine against the seven qualities in the V1 workbook, then the mill rate card items.

Targets are the 'With corrections (weft + 4% shrinkage)' row of the hidden
'Earlier Qualities' sheet. Run: python check_engine.py
"""
import pandas as pd

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


def rate_card_checks(m):
    pdt = m["Piece_Dyeing"].set_index("Route")["Rs per kg greige"]
    PRINT_RATE_PER_KG, PREP_RATE_PER_KG = float(pdt["Printed"]), float(pdt["RFD / Bleached"])
    """The mill rate card items: each is a fixed amount on top of the price, and none is on by default."""
    ex = masters.EXAMPLE_ROW
    base = masters.cost(ex, m)["total_per_m"]
    undyed = masters.cost(dict(ex, **{"Weft (yarn dyed)": "Undyed"}), m)
    no_shade = masters.cost(dict(ex, **{"Weft yarn dyeing": "Undyed"}), m)["total_per_m"]
    ex50 = dict(ex, **{"Warp yarn": "Cotton 50S", "Weft yarn": "Cotton 50S"})
    base50 = masters.cost(ex50, m)["total_per_m"]
    small = dict(ex, **{"Order size": "Below 1,000 m"})
    pr = dict(ex, Route="Printed", Weave="Satin", **{"Warp yarn dyeing": None, "Weft yarn dyeing": None})

    def total(row, **more):
        return masters.cost(dict(row, **more), m)["total_per_m"]

    def error(row, **more):
        out = masters.cost_many(pd.DataFrame([dict(row, **more)]), m)
        return out["Error"].iloc[0]

    checks = [
        ("Dobby 9 to 12 shafts adds Rs 8", total(ex, **{"Dobby shafts": "9 to 12"}) - base, 8),
        ("Dobby 13 shafts with top beam adds Rs 20",
         total(ex, **{"Dobby shafts": "13 and above", "Top beam": "Yes"}) - base, 20),
        ("Top beam alone adds Rs 10", total(ex, **{"Top beam": "Yes"}) - base, 10),
        ("Undyed weft equals weft shade Undyed", undyed["total_per_m"], no_shade),
        ("Chambray dyed weft is undyed weft plus Rs 10",
         total(ex, **{"Weft (yarn dyed)": "Chambray, dyed weft"}) - undyed["total_per_m"], 10),
        ("Finish ETI adds Rs 4", total(ex, Finish="F- ETI Easy to Iron") - base, 4),
        ("Finish Teflon adds Rs 30", total(ex, Finish="F- Teflon") - base, 30),
        ("600 to 699 m adds 7%", total(ex, **{"Rate card quantity": "600 to 699 m"}) / base, 1.07),
        ("800 to 1,999 m changes nothing", total(ex, **{"Rate card quantity": "800 to 1,999 m"}), base),
        ("Above 6,000 m takes Rs 4 off (50s)", base50 - total(ex50, **{"Rate card quantity": "Above 6,000 m"}), 4),
        ("No volume discount for 40s quality", total(ex, **{"Rate card quantity": "Above 6,000 m"}), base),
        ("Quantity band replaces the order size slab, not both",
         total(small, **{"Rate card quantity": "700 to 799 m"}) / base, 1.04),
        ("Order size slab alone still applies", total(small) > base * 1.05, True),
        ("Digital print is Rs 37 above rotary",
         total(pr, **{"Print method": "Digital"}) - total(pr, **{"Print method": "Rotary"}), 37),
        ("Printed fabric, no method chosen, stays on the printing rate per kg",
         masters.cost(pr, m)["inputs"]["piece_dye_rate"], PRINT_RATE_PER_KG),
        ("Printed fabric, no method chosen, has no charge per metre", masters.cost(pr, m)["inputs"]["print_per_m"], 0),
        ("Rotary on a printed fabric is preparation plus Rs 18", total(pr, **{"Print method": "Rotary"}),
         engine.compute(dict(masters.cost(pr, m)["inputs"], piece_dye_rate=PREP_RATE_PER_KG, print_per_m=18,
                             labels={}))["total_per_m"]),
        ("Print over yarn dyed adds Rs 18", total(ex, **{"Print method": "Rotary"}) - base, 18),
    ]
    ok = True
    for name, got, want in checks:
        good = got is want if isinstance(want, bool) else abs(got - want) < 0.005
        ok &= good
        print(f"  {name}: {got if isinstance(got, bool) else round(got, 3)}  {'OK' if good else 'MISMATCH'}")
    refusals = [
        ("Dobby shafts on a twill", error(ex, Weave="Twill-2/1", **{"Dobby shafts": "9 to 12"}), "dobby weaves only"),
        ("Small-lot band on piece dyed",
         error(pr, Route="Piece Dyed", **{"Rate card quantity": "500 to 599 m"}), "yarn dyed"),
        ("Value not on a list", error(ex, **{"Top beam": "Maybe"}), "not on the list"),
    ]
    for name, got, want in refusals:
        good = want in got
        ok &= good
        print(f"  {name} refused: {'OK' if good else 'MISMATCH'} - {got}")
    conv = [("Nm 68 is Ne 40.16", engine.to_ne(68, "Metric count (Nm)"), 68 / 1.6934), ("Tex 14.76 is Ne 40", engine.to_ne(14.7625, "Tex"), 40),
            ("Denier 75 is Ne 70.87", engine.to_ne(75, "Denier"), 5315 / 75), ("Lea 40 is Ne 14.29", engine.to_ne(40, "Lea (linen)"), 40 * 300 / 840),
            ("Worsted 60 is Ne 40", engine.to_ne(60, "Worsted count (Nw)"), 40), ("Ne 40 is Ne 40", engine.to_ne(40, "English count (Ne)"), 40),
            ("Count typed as Ne 40 changes nothing", total(ex, **{"Warp count": 40, "Weft count": 40}), base),
            ("Count typed as Tex 14.7625 changes nothing",
             total(ex, **{"Count system": "Tex", "Warp count": 14.7625, "Weft count": 14.7625}), base),
            ("A finer typed count lowers the cost", total(ex, **{"Warp count": 50}) < base, True),
            ("Tex 14.76 (Ne 40.007) stays in the Ne 40 sizing band",
             masters.cost(dict(ex, **{"Count system": "Tex", "Warp count": 14.76}), m)["inputs"]["sizing_rate"], 30)]
    for name, got, want in conv:
        good = got is want if isinstance(want, bool) else abs(got - want) < 0.005
        ok &= good
        print(f"  {name}: {got if isinstance(got, bool) else round(got, 3)}  {'OK' if good else 'MISMATCH'}")
    lines = [l["name"] for b in undyed["buckets"] if b["name"] == engine.UPCHARGE_BUCKET for l in b["lines"]]
    good = len(lines) == 7
    ok &= good
    print(f"  Second-level lines for the rate card: {lines}  {'OK' if good else 'MISMATCH'}")
    print("Rate card items", "OK" if ok else "MISMATCH")
    return ok


def dated_checks(m):
    """Stage 5: a costing on a date. Without a date nothing changes; with one, each yarn is on the dated rate of that
    month, or on today's rate where there is none, said yarn by yarn. The dated rates here are made up for the check."""
    ex = masters.EXAMPLE_ROW
    base = masters.cost(ex, m)
    none = masters.cost(ex, m, on="2026-09-18", dated={})
    table = {"Cotton 40S": {"2026-09": {"rate": 360.0, "basis": "made up for the check"}}}
    sep = masters.cost(ex, m, on="2026-09-18", dated=table)
    octo = masters.cost(ex, m, on="2026-10", dated=table)
    typed = masters.cost(dict(ex, **{"Warp yarn price override": 360, "Weft yarn price override": 360}), m)
    over = masters.cost(dict(ex, **{"Warp yarn price override": 350}), m, on="2026-09", dated=table)
    same = lambda a, b: {k: v for k, v in a.items() if k != "rates_of"} == b
    checks = [
        ("No date: the result is as before, with nothing added", "rates_of" not in base and abs(base["total_per_m"] - 181.40) < 0.01),
        ("A date with no dated rate: every figure equal to today's (the whole costing)", same(none, base)),
        ("...and it says so for the yarn", none["rates_of"]["label"] == "Sep 2026" and not none["rates_of"]["dated"]
         and none["rates_of"]["notes"] == ["No dated rate for Cotton 40S in Sep 2026: today's rate used (Rs 345)"]),
        ("A dated rate is used for its month, as a typed price of the same figure would be",
         sep["inputs"]["warp_rate"] == 360 and sep["inputs"]["weft_rate"] == 360 and abs(sep["total_per_m"] - typed["total_per_m"]) < 1e-9
         and sep["rates_of"]["dated"] and "Dated rate for Sep 2026" in next(u["Basis"] for u in sep["rates_used"] if u["Item"] == "Warp yarn")),
        ("A dated rate is not carried into the next month", same(octo, base) and "No dated rate for Cotton 40S in Oct 2026" in octo["rates_of"]["notes"][0]),
        ("A typed price is kept over a dated rate", over["inputs"]["warp_rate"] == 350 and over["inputs"]["weft_rate"] == 360
         and any("typed price" in n for n in over["rates_of"]["notes"])),
        ("Without a date the dated rates are not looked at", masters.cost(ex, m, dated=table) == base),
        ("A dated rate on a placeholder yarn, entered with no source at today's figure, changes nothing: the same figure and placeholders",
         (lambda sl: (lambda a, b: a["placeholders"] == b["placeholders"] and a["total_per_m"] == b["total_per_m"] and "Warp yarn" in b["placeholders"])(
             masters.cost(sl, m), masters.cost(sl, m, on="2026-09", dated={"Cotton Slub 20S": {"2026-09": {
                 "rate": 338.0, "basis": "Placeholder: typed in the tool with no source"}}})))(
             dict(ex, **{"Warp yarn": "Cotton Slub 20S", "Weft yarn": "Cotton Slub 20S"}))),
        ("A dated rate entered with no source is a placeholder (rule 4) even on a yarn whose today's rate is not",
         (lambda ph, ph_res: ph_res["placeholders"] == ["Warp yarn", "Weft yarn"] + base["placeholders"]
          and next(u["Basis"] for u in ph_res["rates_used"] if u["Item"] == "Warp yarn").startswith("Placeholder")
          and abs(ph_res["total_per_m"] - base["total_per_m"]) < 1e-12)(None, masters.cost(ex, m, on="2026-09", dated={"Cotton 40S": {"2026-09": {
              "rate": 345.0, "basis": "Placeholder: typed in the tool with no source"}}}))),
        ("A placeholder yarn given a dated rate with a source is no longer a placeholder for that month",
         (lambda sl: "Warp yarn" in masters.cost(sl, m)["placeholders"] and "Warp yarn" not in masters.cost(sl, m, on="2026-09", dated={
             "Cotton Slub 20S": {"2026-09": {"rate": 338.0, "basis": "Typed in the tool: Market circular"}}})["placeholders"])(
             dict(ex, **{"Warp yarn": "Cotton Slub 20S", "Weft yarn": "Cotton Slub 20S"}))),
        ("A month is read from a date, a day or a month; anything else is refused",
         masters.month_of("2026-09-18") == masters.month_of("2026-09") == "2026-09" and masters.month_of(__import__("datetime").date(2026, 9, 1)) == "2026-09"
         and all(_refused(lambda v=v: masters.month_of(v)) for v in ("Sept 2026", "2026-13", ""))),
    ]
    ok = True
    for name, good in checks:
        ok &= bool(good)
        print(f"  {name}: {'OK' if good else 'MISMATCH'}")
    print("Dated rates", "OK" if ok else "MISMATCH")
    return ok


def _refused(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


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
    ok &= rate_card_checks(m)
    ok &= dated_checks(m)
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
