"""Checks the web server against the engine: same numbers, every page's data, bad input refused.

Run: python check_server.py     It must print ALL OK. It does not start the classic screens.
"""
import io
import os
import tempfile

os.environ["RIGHTPRICE_NO_CLASSIC"] = "1"
# Everything here runs on a copy of the rate master in a temporary folder, so the edits it tries
# never touch data/Rate_Master.xlsx.
os.environ["RIGHTPRICE_DATA"] = tempfile.mkdtemp(prefix="rightprice-check-")

from fastapi.testclient import TestClient  # noqa: E402

import masters  # noqa: E402
import server  # noqa: E402


def main():
    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    with TestClient(server.app) as c:
        meta = c.get("/api/meta").json()
        check("Lists for every drop-down", all(meta["lists"][k] for k in masters.lists(masters.load())))
        r = c.post("/api/cost", json=masters.EXAMPLE_ROW).json()
        check("Qlty-1 through the server", abs(r["total_per_m"] - 181.40) < 0.01, f"{r['total_per_m']:.2f}")
        check("Eight cost groups, lines add up to the total",
              len(r["buckets"]) == 8 and abs(sum(l["amount"] for b in r["buckets"] for l in b["lines"])
                                             - r["total_per_m"]) < 1e-6)
        up = dict(masters.EXAMPLE_ROW, **{"Dobby shafts": "9 to 12", "Top beam": "Yes"})
        check("Rate card upcharge through the server", abs(c.post("/api/cost", json=up).json()["total_per_m"] - 199.40) < 0.01)
        bad = c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, Weave="Not a weave"))
        check("Value not on a list refused", bad.status_code == 400 and "not on the list" in bad.json()["detail"])
        check("Blank choices fall back to defaults",
              abs(c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Top beam": "", "Print method": None})
                         ).json()["total_per_m"] - 181.40) < 0.01)
        for path in ["/", "/app.js", "/app.css", "/api/dashboard", "/api/cotton", "/api/pilot", "/api/template"] + \
                ["/api/table/" + s for s in meta["tables"]]:
            check(f"GET {path}", c.get(path).status_code == 200)
        check("Unknown table refused", c.get("/api/table/Nope").status_code == 404)
        man = c.get("/manifest.webmanifest")
        check("Phone home-screen files are served",
              man.status_code == 200 and man.json()["display"] == "standalone"
              and all(c.get("/" + i["src"]).status_code == 200 for i in man.json()["icons"])
              and c.get("/icons/icon-180.png").status_code == 200)
        home = c.get("/?embed=1")
        check("Page asks the browser for the current script, not a stored copy",
              "app.js?v=" in home.text and "app.css?v=" in home.text and home.headers["cache-control"] == "no-cache"
              and c.get("/app.js").headers["cache-control"] == "no-cache")
        tpl = c.get("/api/template").content
        b = c.post("/api/bulk", files={"file": ("t.xlsx", io.BytesIO(tpl))}).json()
        cols = b["results"]["columns"]
        check("Template round trip through the server",
              len(b["results"]["rows"]) == 1 and b["rejected"] == 0
              and abs(b["results"]["rows"][0][cols.index("Should-cost Rs/m")] - 181.40) < 0.01)
        check("Cost sheet download", c.post("/api/cost-sheet", json=masters.EXAMPLE_ROW).content[:2] == b"PK")
        check("No warning on the example fabric", r["warnings"] == [])
        odd = c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Finished width (in)": 5, "Reed space (in)": 4})).json()
        check("Implausible width and reed space warned about", len(odd["warnings"]) >= 2, str(len(odd["warnings"])))

        # saved costings: saved with their choices, listed newest first, deleted by id
        sid = c.post("/api/save", json=dict(masters.EXAMPLE_ROW, **{"Quoted price (Rs/m)": 200})).json()["id"]
        d = c.get("/api/dashboard").json()
        check("Saved costing listed with its choices",
              d["saved_count"] == 1 and d["saved_items"][0]["id"] == sid and d["saved_items"][0]["inputs"]["EPI"] == 132
              and "Inputs" not in d["saved"]["columns"])
        then = d["saved_items"][0]["then"]
        check("Saved costing keeps its cost and the rates it used",
              abs(then["total_per_m"] - 181.40) < 0.01 and len(then["buckets"]) == 8
              and any(u["Item"] == "Warp yarn" and u["Value"] == 345 for u in then["rates"]))
        lea = c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Count system": "Lea (linen)", "Warp count": 112, "Weft count": 112})).json()
        check("Count typed in lea through the server (112 lea = Ne 40)", abs(lea["total_per_m"] - 181.40) < 0.01, f"{lea['total_per_m']:.2f}")
        check("Saved costing deleted", c.delete(f"/api/saved/{sid}").status_code == 200
              and c.get("/api/dashboard").json()["saved_count"] == 0)
        check("Deleting it twice refused", c.delete(f"/api/saved/{sid}").status_code == 404)

        # the fabric list: a mill's price sheet uploaded as it comes
        import pandas as pd
        import mill_sheet
        base_row = {"Brand": "AS", "Fab Code": "T-1", "YD/NYD": "YD", "Material Type": "100% Cotton", "Warp": 40, "Weft": 40,
                    "EPI": 136, "PPI": 90, "Variety": "YDS", "Weave": "2/1 RHT", "F.W.": 145, "Finish": "Normal",
                    "Arvind Ref": "x/1", "Total order qnty": 2255, "Base Price": 164, "Std EPI": 122, "Std PPI": 76,
                    "Actual EPI": 136, "Actual PPI": 90, "Diff EPI": 14, "Diff PPI": 14, "EPI Upch": 8.4, "PPI Upch": 12.6,
                    "Finish Upch": 0, "Dobby Upch": 0, "Upcharge/Print/Mcount": 0, "Double beam": 0, "Price": 185,
                    "Upcharge for less qnty": 0, "Discoun>2000 mts": 0, "Total price with qnty disc/upcharge": 185,
                    "Ex mill price": 185, "C2FO @2.84%": 190.254}
        sheet_rows = [base_row, dict(base_row, **{"Fab Code": "T-2", "Price": 188}),            # the mill's sum is Rs 3 out
                      dict(base_row, **{"Fab Code": "T-3", "YD/NYD": "NYD"}),                      # not guessed
                      dict(base_row, **{"Fab Code": "T-4", "Warp": "40+2/80 (98/2)"})]
        buf = io.BytesIO()
        pd.DataFrame(sheet_rows, columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
        up = c.post("/api/list/upload", files={"file": ("mill.xlsx", io.BytesIO(buf.getvalue()))}).json()
        check("Mill sheet read as it comes", up.get("kind") == "mill sheet" and up["added"] == 4 and up["not_costed"] == 1, str(up))
        lst = c.post("/api/list", json={"yarn_pct": {"Cotton 40S": 5}}).json()
        by = {r["mill"]["Fab Code"]: r for r in lst["rows"]}
        check("Mill row costed beside the mill's price", abs(by["T-1"]["should_cost"] - 174.80) < 0.01 and abs(by["T-1"]["gap"] - 10.20) < 0.01,
              f"{by['T-1']['should_cost']:.2f}")
        check("Mill's own sums checked", by["T-1"]["sums"] == [] and len(by["T-2"]["sums"]) >= 1 and "188" in by["T-2"]["sums"][0])
        check("NYD row listed, not costed, not guessed", by["T-3"]["should_cost"] is None and "NYD" in by["T-3"]["problems"][0])
        import mill_sheet as _ms
        check("Mill sheet: poly cotton and linen rows are read", _ms.content_of_material("PC 65/35") == "Poly cotton" and _ms.content_of_material("100% Linen") == "Linen"
              and _ms.content_of_material("Poly Viscose") is None)
        pc_row = dict(base_row, **{"Fab Code": "PC-1", "Material Type": "PC 65/35"})
        pc_sel, pc_prob, pc_notes = _ms.to_inputs(pc_row, masters.load())
        check("Mill sheet: a poly cotton row is costed on the poly cotton yarn, and says it is a placeholder",
              not pc_prob and pc_sel["Warp yarn"].startswith("Poly Cotton") and any("placeholder" in n for n in pc_notes))
        unknown = dict(base_row, **{"Arvind Ref": None})
        check("Mill sheet: per-end and per-pick come from the rate master, by mill", _ms.terms_for(base_row, masters.load())["mill"] == "Arvind"
              and _ms.terms_for(unknown, masters.load()) is None)
        check("Mixed warp costed on its main yarn, and said so", by["T-4"]["should_cost"] is not None and by["T-4"]["notes"])
        check("Yarn move across the list", by["T-1"]["simulated"] > by["T-1"]["should_cost"] + 4 and by["T-3"]["simulated"] is None)
        added = c.post("/api/list/add", json=dict(masters.EXAMPLE_ROW, Content="100% cotton")).json()["id"]
        fixed = c.post("/api/list/add", json=dict(by["T-3"]["inputs"], Route="Piece Dyed", _id=by["T-3"]["id"])).json()["id"]
        lst = c.post("/api/list", json={}).json()
        t3 = next(r for r in lst["rows"] if r["id"] == fixed)
        check("Row updated in place keeps its mill columns", len(lst["rows"]) == 5 and t3["should_cost"] is not None and t3["mill"]["Base Price"] == 164)
        check("List downloads", c.post("/api/list/download", json={}).content[:2] == b"PK")
        pk = c.post("/api/pack", json={}).json()
        pr = {r["code"]: r for r in pk["rows"]}
        check("Pack: every row, costed or not, with totals", pk["totals"]["rows"] == 5 and len(pk["rows"]) + len(pk["not_costed"]) == 5
              and sum(pk["totals"]["count"].values()) == len(pk["rows"]))
        # T-2: the Price cell is Rs 3 out, but the ex-mill price is what the sums give, so nothing is overcharged
        check("Pack: a sum that is off but charges nothing extra", pr["T-2"]["sums"] and pr["T-2"]["own_price"] == 185.0
              and pr["T-2"]["own_gap"] == 0.0 and pk["totals"]["sums_off"] == 1 and pk["totals"]["sums_money"] == 0)
        over = dict(base_row, **{"Ex mill price": 188, "Total price with qnty disc/upcharge": 188, "C2FO @2.84%": round(188 * 1.0284, 3)})
        check("Pack: an ex-mill price above the mill's own sums, and what it is worth",
              mill_sheet.own_sums(over) == (185.0, 3.0))
        check("Pack: at stake as in the list and the brief", all(r["at_stake"] == round(r["gap"] * r["quantity"]) for r in pk["rows"] if r["quantity"]))
        check("Pack: different fabrics on one mill reference are not taken for duplicates", pk["totals"]["duplicates"] == 0)
        check("Pack: rows can be chosen by the upload they came in", any("mill.xlsx" in x["label"] for x in pk["sheets"]))
        check("Pack: the second yarn is a question", any("second yarn" in q for q in pr["T-4"]["questions"]))
        one = c.post("/api/pack", json={"ids": [pr["T-1"]["id"]]}).json()
        check("Pack: only the rows asked for", one["totals"]["rows"] == 1 and one["rows"][0]["code"] == "T-1")
        mv = c.post("/api/pack", json={"yarn_pct": {"Cotton 40S": 5}}).json()
        t1 = next(r for r in mv["rows"] if r["code"] == "T-1")
        check("Pack: with a yarn move the row and its figures come from the moved brief", t1["should"] == round(t1["quote"] - t1["gap"], 2)
              and all("405" not in q for q in t1["questions"]))
        check("Pack: the headline counts Push and in-line rows only",
              pk["totals"]["counted_stake"] == pk["totals"]["push_stake"] + pk["totals"]["fair_stake"])
        check("Pack: a yarn move re-costs it", next(r for r in mv["rows"] if r["code"] == "T-1")["should"] > pr["T-1"]["should"] + 4)
        gone = c.post("/api/list/remove", json={"ids": [r["id"] for r in lst["rows"]]}).json()
        check("Select all and remove", gone["removed"] == 5 and c.post("/api/list", json={}).json()["rows"] == [])
        tpl2 = c.post("/api/list/upload", files={"file": ("t.xlsx", io.BytesIO(c.get("/api/template").content))}).json()
        check("RightPrice template still accepted", tpl2.get("kind") == "RightPrice template" and tpl2["added"] == 1)
        check("A file with neither layout refused", c.post("/api/list/upload", files={"file": ("x.xlsx", io.BytesIO(buf.getvalue()[:0] or b"x"))}).status_code == 400)
        ins = c.get("/api/insights").json()
        check("Dashboard insights from own data", len(ins["pilot"]["categories"]) >= 10 and abs(sum(s["share"] for s in ins["pilot"]["split"][0]["shares"]) - 1) < 0.01
              and ins["cotton_years"][0]["year"] <= 2022 and 0.3 < ins["reference"]["yarn_share"] < 0.6)
        r2 = c.post("/api/cost", json=masters.EXAMPLE_ROW).json()
        up10 = c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Warp yarn price override": 355})).json()
        check("Rs 10 a kilo on the warp moves the price as stated", abs((up10["total_per_m"] - r2["total_per_m"]) - r2["yarn"]["warp_per_10"]) < 0.001,
              f"{r2['yarn']['warp_per_10']:.3f}")

        # editing the rate master (on the temporary copy)
        yr = c.get("/api/table/Yarn_Rates").json()
        ki, ri = yr["columns"].index("Yarn key"), yr["columns"].index("Rate Rs/kg")
        rows = [list(r) for r in yr["rows"]]
        row40 = next(r for r in rows if r[ki] == "Cotton 40S")
        row40[ri] = 355
        put = c.put("/api/table/Yarn_Rates", json={"columns": yr["columns"], "rows": rows})
        after = c.post("/api/cost", json=masters.EXAMPLE_ROW).json()["total_per_m"]
        check("Yarn rate edit saved and used", put.status_code == 200 and after > 181.41, f"{after:.2f}")
        check("Dated copy kept on the first change of the day",
              any(f.startswith("Rate_Master backup") for f in os.listdir(os.environ["RIGHTPRICE_DATA"])))
        row40[ri] = "abc"
        bad = c.put("/api/table/Yarn_Rates", json={"columns": yr["columns"], "rows": rows})
        check("Text in a number column refused", bad.status_code == 400 and "needs a number" in bad.json()["detail"])
        row40[ri] = 345
        rows.append(list(row40))
        bad = c.put("/api/table/Yarn_Rates", json={"columns": yr["columns"], "rows": rows})
        check("Duplicate yarn key refused", bad.status_code == 400 and "twice" in bad.json()["detail"])
        rows.pop()
        gone = [r for r in rows if r[ki] != "Cotton 40S"]
        bad = c.put("/api/table/Yarn_Rates", json={"columns": yr["columns"], "rows": gone})
        check("Edit that breaks the example fabric refused", bad.status_code == 400 and "can no longer be costed" in bad.json()["detail"])
        c.put("/api/table/Yarn_Rates", json={"columns": yr["columns"], "rows": rows})
        check("Rate restored, Qlty-1 back to 181.40",
              abs(c.post("/api/cost", json=masters.EXAMPLE_ROW).json()["total_per_m"] - 181.40) < 0.01)
        check("Read-only table refused", c.put("/api/table/Cotton_Prices", json={"columns": [], "rows": []}).status_code == 404)
        n0 = len(c.get("/api/cotton").json()["points"])
        ok_add = c.post("/api/cotton", json={"date": "2026-11-24", "price": 61000, "source": "check"}).status_code == 200
        check("Cotton price added", ok_add and len(c.get("/api/cotton").json()["points"]) == n0 + 1)
        check("Cotton price without a number refused", c.post("/api/cotton", json={"date": "2026-11-24", "price": ""}).status_code == 400)

        # the negotiation brief (sixth cold review)
        c.get("/api/insights")
        def br(**kw):
            return c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **kw)).json()["brief"]
        b0 = br(**{"Quoted price (Rs/m)": 192.3})
        check("Brief: a quote at the type's usual premium is Fair, not Push", b0["stance"] == "fair" and b0["band"]["hi"] > 0.05)
        check("Brief: no brief for a quote of zero", br(**{"Quoted price (Rs/m)": 0}) is None)
        lo = br(**{"Quoted price (Rs/m)": 60, "Order quantity (m)": 5000})
        check("Brief: a quote below the range is 'below', the stake is a saving", lo["stance"] == "below" and lo["at_stake"] < 0)
        st = br(**{"Quoted price (Rs/m)": 194.996, "Order quantity (m)": 5000})
        check("Brief: at stake is the printed gap times the quantity", st["at_stake"] == round(st["gap"] * 5000) and st["gap"] == round(st["gap"], 2))
        edge = br(**{"Quoted price (Rs/m)": b0["settle_up_to"]})
        over = br(**{"Quoted price (Rs/m)": round(b0["settle_up_to"] + 0.01, 2)})
        check("Brief: the top of the range is Fair, a paisa over is Push", edge["stance"] == "fair" and over["stance"] == "push" and over["above_band"] == 0.01)
        check("Negative order quantity refused", c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Quoted price (Rs/m)": 194, "Order quantity (m)": -5})).status_code == 400)
        q = br(**{"Quoted price (Rs/m)": 194, "Order quantity (m)": 500})
        check("Brief: quantity outside the band asks first and offers the band that fits",
              q["stance"] == "ask" and q["qty_fix"] == {"field": "Order size", "value": "Below 1,000 m"})
        soft = br(**{"Quoted price (Rs/m)": 200, "Finish": "F- Normal Soft"})
        check("Brief: a small placeholder is a caveat, not a block", soft["stance"] != "ask" and soft["caveats"])
        sat = br(**{"Quoted price (Rs/m)": 230, "Weave": "Satin"})
        check("Brief: a placeholder weaving rate blocks the target and is flagged", sat["stance"] == "ask" and sat["would_need"]["weaving"]["placeholder"])
        same = br(**{"Quoted price (Rs/m)": 194, "Order quantity (m)": 8000, "Rate card quantity": "4,000 to 6,000 m"})
        check("Brief: a band that would not change the cost does not stop the brief", same["stance"] != "ask")
        check("Brief: the quantity alone says 'set the quantity first'", q["qty_only"])
        z = c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Quoted price (Rs/m)": 0})).json()
        check("A quote of zero is said to be ignored", z["brief"] is None and any("ignored" in w for w in z["warnings"]))
        check("Brief: a quote far below should-cost is questioned", any("typing slip" in x for x in lo["caveats"]))
        vel = br(**{"Quoted price (Rs/m)": 230, "Weave": "Velvet"})
        check("Brief: velvet is named as velvet", any("velvet" in x for x in vel["weak"]))
        opens = [br(**{"Quoted price (Rs/m)": q})["open_at"] for q in (199.55, 203, 204, 210, 230)]
        check("Brief: the opening figure moves with the quote, without a jump, and never below should-cost",
              all(a >= b for a, b in zip(opens, opens[1:])) and abs(opens[1] - opens[2]) <= 1.01 and opens[-1] == 181.40, str(opens))
        check("Brief: a quote far below should-cost counts no saving", lo["implausible"])
        check("A yarn move over 50% refused", c.post("/api/list", json={"yarn_pct": {"*": 500}}).status_code == 400)
        nb = c.post("/api/cost", json=dict(masters.EXAMPLE_ROW, **{"Quoted price (Rs/m)": 194, "_notes": ["the second yarn is not in the should-cost"]})).json()
        check("Brief: a list row's notes are carried into it", any("second yarn" in x for x in nb["brief"]["caveats"]) and abs(nb["total_per_m"] - 181.40) < 0.01)

        # Right cost: every costing in one list
        rc = c.get("/api/costs").json()
        po = [r for r in rc["rows"] if r["source"] == "Purchase orders"]
        check("Right cost: the purchase-order costings are listed with their choices", len(po) >= 1600 and all(r["choices"].get("Route") for r in po))
        r0 = po[0]
        check("Right cost: a listed costing reopens at the same should-cost", abs(c.post("/api/cost", json=r0["choices"]).json()["total_per_m"] - r0["should"]) < 0.02)
        shell = c.get("/")
        check("The shell is the home page; the earlier screens are served inside it", "rightcost.js?v=" in shell.text and "rightcost.css?v=" in shell.text
              and c.get("/rightcost.js").status_code == 200 and "app.js?v=" in c.get("/?embed=1").text)
        old = c.get("/rightcost", follow_redirects=False)
        check("The old Right cost address leads to its page in the shell", old.status_code == 307 and old.headers["location"] == "/#rightcost")
        check("Right cost: downloads", c.post("/api/costs/download", json={"source": "Purchase orders"}).content[:2] == b"PK")
        for css in ("web/app.css", "web/rightcost.css"):
            txt = open(css, encoding="utf8").read()
            check(f"{css}: every brace closed", txt.count("{") == txt.count("}"))

        # mill cost sheets (on the temporary copy of the rate master)
        tpl = c.get("/api/costsheet/template")
        check("Cost sheet template downloads", tpl.status_code == 200 and tpl.content[:2] == b"PK")
        cs = pd.read_excel(io.BytesIO(tpl.content), sheet_name="Cost sheet")
        cs.loc[0, "Overhead %"] = 6; cs.loc[0, "Mill"] = "Mill A"
        cs2 = cs.copy(); cs2["Mill"] = "Mill B"; cs2.loc[0, "Overhead %"] = 8
        cs3 = cs.copy(); cs3["Mill"] = "Mill C"; cs3.loc[0, "Route"] = "Piece Dyed"; cs3.loc[0, "Weave"] = "Satin"; cs3.loc[0, "Yarn dyeing Rs/kg"] = None
        cs3.loc[0, "Piece dyeing Rs/kg greige"] = 175
        buf = io.BytesIO(); pd.concat([cs, cs2, cs3]).to_excel(buf, index=False)
        up = c.post("/api/costsheet/upload", files={"file": ("cs.xlsx", io.BytesIO(buf.getvalue()))}).json()
        v = c.get("/api/costsheet").json()
        d = next((x for x in v["drafts"] if x["table"] == "Class_Defaults" and x["col"] == "Overhead"), None)
        import costsheet
        plain = costsheet.analyse(costsheet.read(pd.read_excel(io.BytesIO(tpl.content), sheet_name="Cost sheet")))["rows"][0]
        check("Cost sheet: the template's own figures give its price", abs(plain["own"] - plain["price"]) < 0.01 and abs(plain["should"] - plain["price"]) < 0.01)
        check("Cost sheet: rows read, a disagreement becomes a draft", up.get("added") == 3
              and d is not None and abs(d["proposed"] - 0.07) < 1e-9 and d["sheets"] == 2)
        check("Cost sheet: nothing applied without a tick", c.post("/api/costsheet/apply", json={"ids": []}).status_code == 400
              and abs(c.post("/api/cost", json=masters.EXAMPLE_ROW).json()["total_per_m"] - 181.40) < 0.01)
        ap = c.post("/api/costsheet/apply", json={"ids": [d["id"]]}).json()
        cd = c.get("/api/table/Class_Defaults").json()
        row = next(r for r in cd["rows"] if r[0] == "Dobby/Matt" and r[1] == "Yarn Dyed")
        check("Cost sheet: an applied draft changes that rate only, with its basis and a dated backup",
              ap.get("backup", "").startswith("Rate_Master before mill cost sheet") and abs(row[cd["columns"].index("Overhead")] - 0.07) < 1e-9
              and row[cd["columns"].index("Basis")].startswith("V1 workbook; Overhead from mill cost sheet"))
        mm = masters.load()
        half = {"id": "Sizing_Rates|Yarn Dyed|40", "table": "Sizing_Rates", "match": {"Route type": "Yarn Dyed", "Warp count up to (Ne)": 40},
                "col": "Rs per kg warp", "label": "Sizing", "now": 30.0, "proposed": 16.5, "pct": False, "mills": ["X"]}
        costsheet.apply(mm, [half], {half["id"]})
        check("Cost sheet: a draft of half a rupee applies to a whole-rupee column",
              float(mm["Sizing_Rates"].set_index(["Route type", "Warp count up to (Ne)"]).loc[("Yarn Dyed", 40), "Rs per kg warp"]) == 16.5)
        frac = cs.copy().astype(object); frac.loc[0, "Mill"] = "Mill D"; frac.loc[0, "Fabric code"] = "D-1"; frac.loc[0, "Margin %"] = 0.08; frac.loc[0, "Weaving Rs/pick"] = 45
        rd = costsheet.analyse(costsheet.read(frac))["rows"][0]
        check("Cost sheet: 0.08 read as 8%, a weaving rate in paise is not used", any("read as 8%" in x for x in rd["notes"]) and any("paise" in x for x in rd["notes"]))
        again = c.post("/api/costsheet/upload", files={"file": ("cs.xlsx", io.BytesIO(buf.getvalue()))}).json()
        check("Cost sheet: a mill's sheet sent again takes the place of its rows", again.get("replaced") == 3 and len(c.get("/api/costsheet").json()["rows"]) == 3)
        newrow = next((x for x in c.get("/api/costsheet").json()["drafts"] if x["table"] == "Class_Defaults" and "new row" in x["label"]), None)
        if newrow:
            c.post("/api/costsheet/apply", json={"ids": [newrow["id"]]})
            cd2 = c.get("/api/table/Class_Defaults").json()
            nr = next(r for r in cd2["rows"] if r[0] == newrow["match"]["Weave group"] and r[1] == newrow["match"]["Route"])
        check("Cost sheet: a new row of wastage, overhead and margin stays marked Placeholder, naming what came from a mill",
              newrow is not None and str(nr[cd2["columns"].index("Basis")]).startswith("Placeholder") and "Mill C" in str(nr[cd2["columns"].index("Basis")]))
        after = c.get("/api/costsheet").json()
        check("Cost sheet: once applied, the same sheets draft nothing for that rate", not any(x["id"] == d["id"] for x in after["drafts"]))
        c.post("/api/costsheet/remove", json={"ids": [r["id"] for r in after["rows"]]})

        # negotiation tracker
        base = {"key": "Fabric list|T-9", "code": "T-9", "supplier": "Arvind", "metres": 1000, "should": 170}
        ev = lambda body: c.post("/api/negotiations/event", json=body)
        refused = [ev(dict(base, kind="Agreed", price=0)), ev(dict(base, kind="Agreed", price=180, date="2099-01-01")),
                   ev(dict(base, kind="Mill's quote", price=180, date="0206-11-20")), ev(dict(base, kind="Mill's quote", price=0.004)),
                   ev(dict(base, kind="Mill's quote", price=99999999))]
        check("Tracker: a price of zero, under Rs 1 or absurd, a date in the future or years ago are refused", all(r.status_code == 400 for r in refused))
        ev(dict(base, kind="Mill's quote", price=190, date="2026-11-20"))
        ev(dict(base, kind="Our counter", price=176, date="2026-11-21"))
        last = ev(dict(base, kind="Agreed", price=182.5, date="2026-11-22")).json()
        sm = last["summary"]
        check("Tracker: agreed price, and what was won against the first quote and should-cost",
              sm["status"] == "Agreed" and sm["agreed"] == 182.5 and sm["won_per_m"] == 7.5 and sm["won"] == 7500 and sm["above_should_per_m"] == 12.5 and sm["counted"])
        tot = c.get("/api/negotiations/summary").json()
        check("Tracker: the dashboard total", tot["agreed"] == 1 and tot["won"] == 7500 and tot["suppliers"][0]["supplier"] == "Arvind")
        agreed_id = last["events"][-1]["id"]
        c.post("/api/negotiations/remove", json={"key": base["key"], "id": agreed_id})
        rec = c.get("/api/negotiations").json()["items"][base["key"]]
        check("Tracker: removing the agreed step reopens it, and the removed step is kept for the log",
              rec["summary"]["status"] == "Open" and rec["removed"][0]["id"] == agreed_id and rec["removed"][0]["removed_at"])
        check("Tracker: removing a step twice says it is gone", c.post("/api/negotiations/remove", json={"key": base["key"], "id": agreed_id}).status_code == 404)
        # the first quote is a quote: never our counter, never the agreed price
        k2 = dict(base, key="Fabric list|T-10", code="T-10", supplier="Arvind Ltd")
        only = ev(dict(k2, kind="Agreed", price=180, date="2026-11-10")).json()["summary"]
        check("Tracker: an agreed price with no mill quote is not counted as won", only["first"] is None and only["won"] is None and only["no_quote"] and not only["counted"])
        late = ev(dict(k2, kind="Mill's quote", price=200, date="2026-11-12")).json()["summary"]
        check("Tracker: an agreed price dated before the first quote is not counted as agreed, and is flagged",
              late["status"] == "Open" and late["first"] == 200 and late["reopened"] == 180 and any("before the mill's first quote" in w for w in late["warnings"]))
        same = ev(dict(dict(base, key="Fabric list|T-12", code="T-12"), kind="Agreed", price=180, date="2026-11-15")).json()
        same = ev(dict(dict(base, key="Fabric list|T-12", code="T-12"), kind="Mill's quote", price=190, date="2026-11-15")).json()
        check("Tracker: a quote entered after the agreed price on the same day comes before it",
              same["summary"]["status"] == "Agreed" and same["summary"]["won"] == 10000 and same["events"][-1]["kind"] == "Agreed")
        for e in c.get("/api/negotiations").json()["items"][k2["key"]]["events"]:
            c.post("/api/negotiations/remove", json={"key": k2["key"], "id": e["id"]})
        ev(dict(k2, kind="Mill's quote", price=200, date="2026-11-12"))
        again = ev(dict(k2, kind="Agreed", price=210, date="2026-11-14")).json()["summary"]
        check("Tracker: agreeing above the first quote is a loss", again["status"] == "Agreed" and again["won_per_m"] == -10 and again["won"] == -10000)
        ev(dict(base, kind="Agreed", price=182.5, date="2026-11-22"))
        tot = c.get("/api/negotiations/summary").json()
        check("Tracker: a mill written two ways is one mill; a loss is netted and also shown apart",
              len(tot["suppliers"]) == 1 and tot["suppliers"][0]["fabrics"] == 3 and tot["won"] == 7500 and tot["lost"] == 10000 and tot["lost_fabrics"] == 1, str(tot))
        # a mistyped first quote must not become money won
        k3 = dict(base, key="Fabric list|T-11", code="T-11")
        typo = ev(dict(k3, kind="Mill's quote", price=2150, date="2026-11-20")).json()["summary"]
        typo2 = ev(dict(k3, kind="Agreed", price=150, date="2026-11-21")).json()["summary"]
        tot2 = c.get("/api/negotiations/summary").json()
        check("Tracker: a first quote far from should-cost is flagged as the odd figure, and left out of what was won",
              any("first quote" in w and "2,150.00" in w for w in typo["warnings"]) and not typo2["counted"] and tot2["won"] == 7500
              and [x["code"] for x in tot2["to_check"]] == ["T-11"] and not any("150.00 (Agreed" in w for w in typo2["warnings"]), str(typo2))
        over = ev(dict(dict(base, key="Fabric list|T-13", code="T-13"), kind="Mill's quote", price=185, date="2026-11-20")).json()
        over = ev(dict(dict(base, key="Fabric list|T-13", code="T-13"), kind="Our counter", price=190, date="2026-11-21")).json()["summary"]
        check("Tracker: a counter above the mill's price is queried", any("above the mill's price" in w for w in over["warnings"]))
        k13 = dict(base, key="Fabric list|T-13", code="T-13")
        stale = ev(dict(k13, kind="Agreed", price=180, date="2026-11-22", seen=1))
        check("Tracker: a page that has not seen the latest step cannot record over it", stale.status_code == 409)
        still = ev(dict(k13, kind="Agreed", price=180, date="2026-11-22", seen=2)).json()["summary"]
        check("Tracker: the counter stays flagged after a later step, and the fabric stays out of what was won",
              any("above the mill's price" in w for w in still["warnings"]) and not still["counted"])
        k14 = dict(base, key="Fabric list|T-14", code="T-14")
        ev(dict(k14, kind="Mill's revised quote", price=190, date="2026-11-20"))
        o14 = ev(dict(k14, kind="Mill's quote", price=200, date="2026-11-20")).json()["summary"]
        check("Tracker: on one day the mill's quote comes before its revised quote", o14["first"] == 200 and o14["latest"] == 190)
        half = ev(dict(k14, kind="Agreed", price=95, date="2026-11-21")).json()["summary"]
        check("Tracker: an agreed price under half the first quote is flagged and not counted", half["warnings"] and not half["counted"])
        nc = ev({"key": "Fabric list|T-15", "code": "T-15", "kind": "Mill's quote", "price": 2150, "row_price": 185, "date": "2026-11-20"}).json()["summary"]
        check("Tracker: a fabric not costed is checked against the price on its row", any("price on the row" in w for w in nc["warnings"]))
        check("Mill names: Ltd, Limited, Mills and a cut-off Limited are dropped",
              server.mill_key("Rajapalayam Mills Limite") == server.mill_key("RAJAPALAYAM MILLS LTD.") == "rajapalayam" and server.mill_key("Arvind") == server.mill_key("Arvind Limited"))
        check("Rupees in Indian grouping", server._inr(99999999) == "9,99,99,999.00" and server._inr(1234.5) == "1,234.50")
        # a list row that repeats another order: no second negotiation
        buf = io.BytesIO()
        pd.DataFrame([dict(base_row, **{"Fab Code": "D-1", "Total order qnty": 3100}), dict(base_row, **{"Fab Code": "D-2", "Total order qnty": 3100})],
                     columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
        c.post("/api/list/upload", files={"file": ("dup.xlsx", io.BytesIO(buf.getvalue()))})
        lst_rows = [r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Fabric list" and r["code"] in ("D-1", "D-2")]
        dup = next((r for r in lst_rows if r.get("duplicate_of")), None)
        r_ = ev({"key": f"Fabric list|{dup['id']}", "code": dup["code"], "kind": "Mill's quote", "price": 185}) if dup else None
        check("Tracker: a row repeating another order is sent to that order", bool(dup) and r_.status_code == 400 and dup["duplicate_of"] in r_.json()["detail"])
        c.post("/api/list/remove", json={"ids": [r["id"] for r in lst_rows]})
        # supplier page: one mill, however it is written
        buf = io.BytesIO()
        pd.DataFrame([dict(base_row, **{"Fab Code": "S-1", "Price": 240, "Ex mill price": 240, "Total price with qnty disc/upcharge": 240, "Total order qnty": 5000}),
                      dict(base_row, **{"Fab Code": "S-2", "Total order qnty": 4100})], columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
        c.post("/api/list/upload", files={"file": ("sup.xlsx", io.BytesIO(buf.getvalue()))})
        s_rows = [r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Fabric list" and r["code"] in ("S-1", "S-2")]
        mill = s_rows[0]["mill"]
        sp = c.get("/api/supplier", params={"mill": s_rows[0]["supplier"] + " Limited"}).json()
        s1 = next(r for r in sp["quoted"]["rows"] if r["code"] == "S-1")
        upper = round(round(s1["should"], 2) * (1 + s1["range"][1] / 100), 2)
        check("Supplier page: found under any spelling; money above the range is price less the top of the range, times metres",
              sp["key"] == mill and s1["band"] == "Push" and s1["above_range"] == round((240 - upper) * 5000), str(s1))
        check("Supplier page: questions on the quotes in hand, and the sheet's sums that are off",
              any(q["code"] == "S-1" and "above should-cost" in q["text"] for q in sp["questions"]["quoted"]) and any(x["code"] == "S-1" for x in sp["sums"]))
        k_s1 = {"key": f"Fabric list|{s_rows[0]['id'] if s_rows[0]['code'] == 'S-1' else s_rows[1]['id']}", "code": "S-1", "supplier": s_rows[0]["supplier"], "metres": 5000, "should": s1["should"]}
        ev(dict(k_s1, kind="Mill's quote", price=240, date="2026-11-20"))
        ev(dict(k_s1, kind="Agreed", price=230, date="2026-11-21"))
        k_s2 = {"key": f"Fabric list|{next(r['id'] for r in s_rows if r['code'] == 'S-2')}", "code": "S-2", "supplier": s_rows[0]["supplier"], "metres": 4100, "should": s1["should"]}
        ev(dict(k_s2, kind="Mill's quote", price=205, date="2026-11-20"))
        ev(dict(k_s2, kind="Our counter", price=180, date="2026-11-21"))
        sp2 = c.get("/api/supplier", params={"mill": mill}).json()
        check("Supplier page: an agreed fabric has no question left, and its gain is in the mill's tracker figures",
              not any(q["code"] == "S-1" for q in sp2["questions"]["quoted"]) and any(t["code"] == "S-1" and t["won"] == 50000 for t in sp2["tracker"]["items"]))
        check("Supplier page: an agreed fabric is closed, not money to push on",
              sp2["quoted"]["agreed"] == 1 and sp2["quoted"]["above_range"] == round((205 - upper) * 4100) and sp2["quoted"]["agreed_above_range"] == round((230 - upper) * 5000), str({k: v for k, v in sp2["quoted"].items() if k != "rows"}))
        check("Mill names: a name cut short is the fuller name; Textiles and Mills of one name stay apart",
              server._mill_base("Nahar Industrial Enterpr") != "" and server._mill_base("Sri Shyam Fashions India Pvt Ltd") == server._mill_base("Sri Shyam Fashion India")
              and server._mill_base("Ruby Textiles Pvt Ltd") != server._mill_base("The Ruby Mills Limited") and server._mill_base("\u0905\u0930\u0935\u093f\u0902\u0926") != "")
        server._learn_mill_names({"Nahar Industrial Enterpr", "Nahar Industrial Enterprises Ltd", "Arvind Ltd", "Arvind Ltd (Denim Division)"})
        check("Mill names: only a cut-off name joins the fuller one", server.mill_key("Nahar Industrial Enterpr") == server.mill_key("Nahar Industrial Enterprises Ltd")
              and server.mill_key("Arvind Ltd") != server.mill_key("Arvind Ltd (Denim Division)"))
        q2 = [q["text"] for q in sp2["questions"]["quoted"] if q["code"] == "S-2"]
        r2 = next(r for r in sp2["quoted"]["rows"] if r["code"] == "S-2")
        check("Supplier page: a fabric the mill has moved on is judged and asked about at the price it is at now, holding our counter",
              r2["price"] == 205 and r2["sheet_price"] == 185 and r2["band"] == "Push" and r2["above_range"] == round((205 - upper) * 4100)
              and q2 and "now at Rs 205.00" in q2[0] and "hold our counter of rs 180.00" in q2[0].lower() and not any("ask for Rs" in q for q in q2), str(q2))
        check("Supplier page: the mill's own build-up is set against the price it asks now",
              any(x["code"] == "S-2" and x["quote"] == 205 and x["own_gap"] == 20 for x in sp2["sums"]), str(sp2["sums"]))
        check("Supplier page: an unknown mill is refused", c.get("/api/supplier", params={"mill": "No Such Mill"}).status_code == 404)
        check("Suppliers: one line a mill", any(x["key"] == mill for x in c.get("/api/suppliers").json()["suppliers"]))
        c.post("/api/list/remove", json={"ids": [r["id"] for r in s_rows]})
        # quote alerts: flagged at once when a sheet is uploaded
        hi = dict(base_row, **{"Price": 240, "Ex mill price": 240, "Total price with qnty disc/upcharge": 240, "Total order qnty": 5000})
        buf = io.BytesIO()
        pd.DataFrame([dict(hi, **{"Fab Code": "Q-1"}), dict(hi, **{"Fab Code": "Q-2"}),                        # above range, sums off; Q-2 repeats Q-1
                      dict(base_row, **{"Fab Code": "Q-3", "Price": 70, "Ex mill price": 70, "Total price with qnty disc/upcharge": 70, "Total order qnty": 3300}),
                      dict(base_row, **{"Fab Code": "Q-4", "Total order qnty": 3700})], columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
        before = c.get("/api/alerts").json()["count"]
        upq = c.post("/api/list/upload", files={"file": ("quotes.xlsx", io.BytesIO(buf.getvalue()))}).json()
        got = {a["code"]: a["kinds"] for a in upq["alerts"]}
        dupe, first_ = ("Q-1", "Q-2") if got.get("Q-1") == ["repeat"] else ("Q-2", "Q-1")
        check("Quote alerts: the upload itself says which rows need a look, and why",
              got.get(first_) == ["above", "sums"] and got.get(dupe) == ["repeat"] and got.get("Q-3") == ["low", "sums"] and "Q-4" not in got, str(got))
        al = c.get("/api/alerts").json()
        a1 = next(r for g in al["groups"] for r in g["rows"] if r["code"] == first_)
        check("Quote alerts: counted, with the money above the range and the mill's own sums",
              al["count"] == before + 3 and a1["flags"][0]["money"] == round((240 - upper) * 5000) and a1["flags"][1]["money"] == 55 * 5000, str(a1))
        al2 = c.post("/api/alerts/seen", json={"ids": [a1["id"]]}).json()
        check("Quote alerts: marked seen it goes, for everyone, and can be brought back",
              al2["count"] == before + 2 and al2["seen"] >= 1 and c.post("/api/alerts/seen", json={"restore": True}).json()["count"] == before + 3)
        ev({"key": a1["key"], "code": first_, "kind": "Mill's quote", "price": 240, "metres": 5000})
        check("Quote alerts: a negotiation step on the fabric takes its alert away", c.get("/api/alerts").json()["count"] == before + 2)
        q_ids = [r["id"] for r in c.get("/api/costs").json()["rows"] if r["source"] == "Fabric list" and str(r["code"]).startswith("Q-")]
        c.post("/api/list/remove", json={"ids": q_ids})
        check("Quote alerts: removing the rows removes their alerts", c.get("/api/alerts").json()["count"] == before)
        for key, it in c.get("/api/negotiations").json()["items"].items():
            for e in it["events"]:
                c.post("/api/negotiations/remove", json={"key": key, "id": e["id"]})
        check("Tracker: with every step removed nothing is counted", c.get("/api/negotiations/summary").json()["fabrics"] == 0)

        # yarn price intake
        csv = b"Count,Yarn,Rate\n40s,Combed compact,351\n50s,Combed compact,402\n60s,Combed compact,\n"
        t = c.post("/api/intake/file", files={"file": ("list.csv", io.BytesIO(csv))}).json()
        check("CSV read as a table", t.get("kind") == "tables" and "Count" in next(iter(t["sheets"].values()))["columns"])
        st = c.post("/api/intake/map", json={"token": t["token"], "sheet": next(iter(t["sheets"])), "count": "Count",
                                             "low": "Rate", "yarn": "Yarn"}).json()
        check("Columns mapped, row without a rate dropped", st.get("kind") == "rows" and len(st["rows"]) == 2)
        m0 = len(c.get("/api/table/Market_Yarn").json()["rows"])
        added = c.post("/api/intake/add", json={"rows": st["rows"] + [[None] * 6], "source": "list.csv"}).json()
        check("Reviewed rows added to the market reference",
              added.get("added") == 2 and len(c.get("/api/table/Market_Yarn").json()["rows"]) == m0 + 2)
        check("Empty review refused", c.post("/api/intake/add", json={"rows": [[None] * 6]}).status_code == 400)
        check("Unknown file type refused", c.post("/api/intake/file", files={"file": ("x.exe", io.BytesIO(b"x"))}).status_code == 400)
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
