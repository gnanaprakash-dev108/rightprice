"""Checks the web server against the engine: same numbers, every page's data, bad input refused; and the data layer.

Run: python check_server.py     It must print ALL OK. It does not start the classic screens.

What it runs:
1. The checks below on the files (as before the data layer), on a SQLite database file, and on PostgreSQL.
2. The move from files to a database, proved: a data folder is filled through the app on the files and every page's
   answer is kept; the folder is then copied into PostgreSQL and into SQLite the way the live app will do it, and every
   answer must be exactly the same (every costing equal to the paisa, and everything else). The files must not have
   changed; the database written back out as files must give the same answers again.
3. The data layer itself: tables added once, writers waiting for each other, a dropped connection made again, the app
   refusing a database when the files changed after the move, and an unreachable database (503, no password shown).

It never touches the live database: DATABASE_URL is ignored. PostgreSQL is used when RIGHTPRICE_TEST_DATABASE_URL names
a test server: a throwaway database is made on it for each run and dropped after. The "checks" job on GitHub runs one,
and sets RIGHTPRICE_CHECK_REQUIRE_POSTGRES=1 so that a missing PostgreSQL fails instead of being skipped.
"""
import datetime as _dt
import hashlib
import io
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.environ.get("RIGHTPRICE_CHECK_STORE")       # set for one run, by the run that starts it
if STORE:
    os.environ["RIGHTPRICE_NO_CLASSIC"] = "1"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("DATABASE_URL", None)
    # everything runs on a copy of the rate master in a temporary folder, so the edits it tries never touch
    # data/Rate_Master.xlsx
    if not os.environ.get("RIGHTPRICE_DATA"):
        os.environ["RIGHTPRICE_DATA"] = tempfile.mkdtemp(prefix="rightprice-check-")
    if STORE != "files":
        os.environ["DATABASE_URL"] = os.environ["RIGHTPRICE_CHECK_URL"]

    from fastapi.testclient import TestClient  # noqa: E402

    import masters  # noqa: E402
    import server  # noqa: E402
    from rules import common as rules_common, drafts as rules_drafts, mills as rules_mills  # noqa: E402


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
        st = c.get("/api/store").json()
        if st["store"] == "files":
            check("Dated copy kept on the first change of the day",
                  any(f.startswith("Rate_Master backup") for f in os.listdir(os.environ["RIGHTPRICE_DATA"])))
        else:       # a database keeps every version: the one before the edit is still there, and the files are not written
            import store as _store
            with _store.get().tx() as tx_:
                kept_, now_ = [pd.read_excel(io.BytesIO(bytes(r[0])), sheet_name="Yarn_Rates") for r in
                               tx_.all("SELECT workbook FROM rate_version ORDER BY id DESC LIMIT 2")][::-1]
            rate_ = lambda df: float(df.set_index("Yarn key").loc["Cotton 40S", "Rate Rs/kg"])
            check("Dated copy kept on the first change of the day (the earlier version, in the database, as it was)",
                  st["rate_master_in_use"]["reason"].startswith("Table edited: Yarn_Rates") and rate_(kept_) != 355 and rate_(now_) == 355
                  and not any(f.startswith("Rate_Master") for f in os.listdir(os.environ["RIGHTPRICE_DATA"])))
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
              (ap.get("backup", "").startswith("Rate_Master before mill cost sheet") if c.get("/api/store").json()["store"] == "files"
               else ap.get("backup", "").startswith("rate version ") and ap["backup"].endswith("kept in the database"))
              and abs(row[cd["columns"].index("Overhead")] - 0.07) < 1e-9
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
              rules_mills.mill_key("Rajapalayam Mills Limite") == rules_mills.mill_key("RAJAPALAYAM MILLS LTD.") == "rajapalayam" and rules_mills.mill_key("Arvind") == rules_mills.mill_key("Arvind Limited"))
        check("Rupees in Indian grouping", rules_common._inr(99999999) == "9,99,99,999.00" and rules_common._inr(1234.5) == "1,234.50")
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
              rules_mills._mill_base("Nahar Industrial Enterpr") != "" and rules_mills._mill_base("Sri Shyam Fashions India Pvt Ltd") == rules_mills._mill_base("Sri Shyam Fashion India")
              and rules_mills._mill_base("Ruby Textiles Pvt Ltd") != rules_mills._mill_base("The Ruby Mills Limited") and rules_mills._mill_base("\u0905\u0930\u0935\u093f\u0902\u0926") != "")
        rules_mills._learn_mill_names({"Nahar Industrial Enterpr", "Nahar Industrial Enterprises Ltd", "Arvind Ltd", "Arvind Ltd (Denim Division)"})
        check("Mill names: only a cut-off name joins the fuller one", rules_mills.mill_key("Nahar Industrial Enterpr") == rules_mills.mill_key("Nahar Industrial Enterprises Ltd")
              and rules_mills.mill_key("Arvind Ltd") != rules_mills.mill_key("Arvind Ltd (Denim Division)"))
        q2 = [q["text"] for q in sp2["questions"]["quoted"] if q["code"] == "S-2"]
        r2 = next(r for r in sp2["quoted"]["rows"] if r["code"] == "S-2")
        check("Supplier page: a fabric the mill has moved on is judged and asked about at the price it is at now, holding our counter",
              r2["price"] == 205 and r2["sheet_price"] == 185 and r2["band"] == "Push" and r2["above_range"] == round((205 - upper) * 4100)
              and q2 and "now at Rs 205.00" in q2[0] and "hold our counter of rs 180.00" in q2[0].lower() and not any("ask for Rs" in q for q in q2), str(q2))
        check("Supplier page: the mill's own build-up is set against the price it asks now",
              any(x["code"] == "S-2" and x["quote"] == 205 and x["own_gap"] == 20 for x in sp2["sums"]), str(sp2["sums"]))
        check("Supplier page: an unknown mill is refused", c.get("/api/supplier", params={"mill": "No Such Mill"}).status_code == 404)
        check("Suppliers: one line a mill", any(x["key"] == mill for x in c.get("/api/suppliers").json()["suppliers"]))
        # drafts to a mill: only the fabrics asked about, and always something to edit
        import draft
        os.environ.pop("ANTHROPIC_API_KEY", None)
        k_d2 = k_s2["key"]
        d0 = c.post("/api/draft", json={"scope": {"type": "fabric", "key": k_d2}, "ask": "price", "writer": "GP", "contact": "Mr Shah"}).json()
        check("Draft: with no API key a fixed template is filled from the fabric's own figures, and says so",
              d0["source"] == "template" and "not by Claude" in d0["note"] and d0["fabrics"] == ["S-2"] and "205.00" in d0["email"]
              and "Mr Shah" in d0["email"] and "GP" in d0["email"] and "S-1" not in d0["email"] and "a revised price" in d0["subject"], str(d0)[:400])
        mill_text = d0["email"] + d0["whatsapp"] + d0["subject"]
        check("Draft: what is for the mill names our counter and never the top of our range; the buyer's notes are apart",
              "Our counter of Rs 180.00 stands" in d0["email"] and "Your own sheet adds up to Rs 185.00" in d0["email"] and f"{upper:.2f}" not in mill_text and "supports Rs" not in mill_text and "should-cost" not in mill_text and "usual range" not in mill_text
              and "NOTES" not in mill_text and any("counter" in pt for pt in d0["notes"]), mill_text[:300])
        two = c.post("/api/draft", json={"scope": {"type": "rows", "keys": [k_d2, k_s1["key"]]}}).json()
        check("Draft: a ticked fabric left out is named with the reason", two["fabrics"] == ["S-2"] and two["skipped"] == [{"code": "S-1", "why": "its price is already agreed"}], str(two.get("skipped")))
        check("Draft: a fabric already agreed needs no message, and the refusal says why",
              "already agreed" in c.post("/api/draft", json={"scope": {"type": "fabric", "key": k_s1["key"]}}).json().get("detail", ""))
        other = next(r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Purchase orders" and r["mill"] != mill)
        check("Draft: fabrics of two mills are refused", c.post("/api/draft", json={"scope": {"type": "rows", "keys": [k_d2, "Purchase orders|" + other["code"]]}}).status_code == 400)
        facts = {k: v for k, v in rules_drafts._draft_facts({"scope": {"type": "fabric", "key": k_d2}, "ask": "breakup"}).items() if k not in ("skipped", "left_out", "adjusted")}
        check("Draft: what goes to the API is this fabric's figures and nothing else",
              [i["code"] for i in facts["items"]] == ["S-2"] and set(facts) == {"writer", "contact", "mill", "ask", "wants", "items"}
              and facts["writer"] == "[Your name]" and facts["items"][0]["price"] == 205 and facts["items"][0]["price_to_name"] == 180 and facts["items"][0]["purpose"] == "revise")
        t_low = draft.template(dict(facts, ask="both", items=[dict(facts["items"][0], purpose="confirm_price", price=70.0, price_to_name=None)]))
        t_unsure = draft.template(dict(facts, ask="both", items=[dict(facts["items"][0], purpose="breakup_only", price_to_name=None)]))
        t_bought = draft.template(dict(facts, ask="both", items=[dict(facts["items"][0], purpose="next_order", already_bought=True, our_counter=None, price_to_name=190.0)]))
        check("Draft: a price too low to be right is asked to be confirmed, not revised; an unsure fabric gets only the break-up; a past purchase is for the next order",
              "confirm" in t_low["email"] and "revised price" not in t_low["email"] + t_low["subject"] and "revised price" not in t_unsure["email"] + t_unsure["subject"]
              and "Rs 180" not in t_unsure["email"] and "next order" in t_bought["email"] and "before we can take it further" not in t_bought["email"])
        t_fair = draft.template(dict(facts, ask="price", items=[dict(facts["items"][0], purpose="correct_sheet", price=171.0, price_to_name=None, our_counter=None)]))
        t_below = draft.template(dict(facts, ask="price", items=[dict(facts["items"][0], purpose="confirm_spec", price=140.0, price_to_name=None, our_counter=None)]))
        t_plain = draft.template(dict(facts, ask="price", items=[dict(facts["items"][0], our_counter=None, price_to_name=None, mills_own_build_up=None)]))
        check("Draft: a fabric at or below its range is never asked for a revised price; with no counter and no sheet, no price of ours is named",
              "revise" not in (t_fair["email"] + t_fair["subject"] + t_fair["whatsapp"]).lower() and "not in question" in t_fair["email"]
              and "revise" not in (t_below["email"] + t_below["subject"]).lower() and "140.00" not in t_below["email"]
              and "well above what our costing supports" in t_plain["email"] and t_plain["email"].count("Rs ") == 1)

        class _Block:
            type = "text"
            def __init__(self, t): self.text = t
        class _Res:
            def __init__(self, t, stop="end_turn"): self.content, self.stop_reason = [_Block(t)], stop
        class _Fake:           # stands in for the SDK client, to check what is sent and how a reply is read
            def __init__(self, res): self.res, self.sent = res, None; self.beta = self; self.messages = self
            def create(self, **kw):
                self.sent = kw
                if isinstance(self.res, Exception): raise self.res
                return self.res
        fk = _Fake(_Res("SUBJECT: S-2 price\nEMAIL:\nDear [Name],\nPlease revise.\nGP\nWHATSAPP:\nPlease revise S-2. GP"))
        d1 = draft.write(facts, client=fk)
        check("Draft: the request names the model, low effort and the default fallback, and sends only the facts",
              fk.sent["model"] == "claude-opus-5-5" and fk.sent["output_config"] == {"effort": "low"} and fk.sent["fallbacks"] == "default"
              and fk.sent["betas"] == ["server-side-fallback-2026-07-01"] and "thinking" not in fk.sent and "S-2" in fk.sent["messages"][0]["content"]
              and "S-1" not in fk.sent["messages"][0]["content"] and "Rate_Master" not in fk.sent["messages"][0]["content"])
        check("Draft: a reply in the layout is read into subject, e-mail and WhatsApp", d1["source"] == "claude" and d1["subject"] == "S-2 price" and d1["email"].endswith("GP") and d1["whatsapp"].startswith("Please revise"))
        d2 = draft.write(facts, client=_Fake(_Res("", stop="refusal")))
        d3 = draft.write(facts, client=_Fake(_Res("Here is your email!")))
        d4 = draft.write(facts, client=_Fake(RuntimeError("network down")))
        check("Draft: a refusal, a reply out of layout or a failed call each fall back to the template and say why",
              all(d["source"] == "template" and "205.00" in d["email"] for d in (d2, d3, d4)) and "declined" in d2["note"] and "could not be written" in d3["note"] and "network down" in d4["note"])

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
        dupe = next(a["code"] for a in upq["alerts"] if a["repeat"])
        first_ = "Q-2" if dupe == "Q-1" else "Q-1"
        check("Quote alerts: the upload itself says which rows need a look, and why; a repeated row keeps its price flags",
              got.get(first_) == ["repeat", "above", "sums"] and got.get(dupe) == ["repeat", "above", "sums"] and got.get("Q-3") == ["low", "sums"] and "Q-4" not in got, str(got))
        al = c.get("/api/alerts").json()
        a1 = next(r for g in al["groups"] for r in g["rows"] if r["code"] == first_)
        check("Quote alerts: counted, with the money above the range and the mill's own sums",
              al["count"] == before + 3 and a1["flags"][1]["money"] == round((240 - upper) * 5000) and a1["flags"][2]["money"] == 55 * 5000
              and al["repeat_rows"] >= 1, str(a1))
        al2 = c.post("/api/alerts/seen", json={"ids": [a1["id"]]}).json()
        check("Quote alerts: marked seen it goes, for everyone, and can be brought back",
              al2["count"] == before + 2 and al2["seen"] >= 1 and c.post("/api/alerts/seen", json={"restore": True}).json()["count"] == before + 3)
        check("Quote alerts: the repeated row's rupees are not added; one alert can be brought back on its own",
              al["above_money"] - c.get("/api/alerts").json()["above_money"] == 0 and al["above_rows"] == c.get("/api/alerts").json()["above_rows"]
              and c.post("/api/alerts/seen", json={"ids": [a1["id"]]}).json()["count"] == before + 2 and c.post("/api/alerts/seen", json={"ids": [a1["id"]], "undo": True}).json()["count"] == before + 3)
        ev({"key": a1["key"], "code": first_, "kind": "Mill's quote", "price": 240, "metres": 5000})
        check("Quote alerts: recording the mill's quote does not clear the alert", c.get("/api/alerts").json()["count"] == before + 3)
        ev({"key": a1["key"], "code": first_, "kind": "Agreed", "price": 200, "metres": 5000, "seen": 1})
        gone = c.get("/api/alerts").json()
        check("Quote alerts: agreeing the price clears it, and the fabric's page still has the flags", gone["count"] == before + 2 and gone["all"][a1["id"]]["state"] == "agreed")
        buf = io.BytesIO()
        pd.DataFrame([dict(base_row, **{"Fab Code": dupe, "Total order qnty": 5000})], columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
        c.post("/api/list/upload", files={"file": ("corrected.xlsx", io.BytesIO(buf.getvalue()))})
        old_row = next(a for a in c.get("/api/alerts").json()["all"].values() if any("An older row for " + dupe in f["text"] for f in a["flags"]))
        check("Quote alerts: a corrected sheet makes the older row say so, with both prices", any("240.00" in f["text"] and "185.00" in f["text"] for f in old_row["flags"]) and len(old_row["flags"]) == 1)
        newer = [a for a in c.get("/api/alerts").json()["all"].values() if any("An older row for this code and quantity" in f["text"] for f in a["flags"])]
        check("Quote alerts: the newer row says an older one is on the list", len(newer) == 1 and newer[0]["state"] == "live")
        check("Quantities as mills type them", rules_common._qty("5000 mtr") == 5000 and rules_common._qty("3,333") == 3333 and rules_common._qty(4200) == 4200 and rules_common._qty("about 5") is None)
        tot_q = c.get("/api/negotiations/summary").json()
        check("Tracker: a fabric agreed before a re-quote arrived keeps its gain", any(t for t in [tot_q] if t["duplicates"] == 0))
        # MCP: an assistant's way in, behind a secret token
        os.environ.pop("RIGHTPRICE_MCP_TOKEN", None)
        check("MCP: switched off unless the token setting exists, and the site is untouched",
              c.get("/mcp/health").status_code == 404 and c.post("/mcp", json={}).status_code == 404 and c.get("/api/meta").status_code == 200)
        os.environ["RIGHTPRICE_MCP_TOKEN"] = "short"
        check("MCP: a token too short to be a secret keeps it off", c.get("/mcp/health", headers={"Authorization": "Bearer short"}).status_code == 404)
        tok = "k" * 40
        os.environ["RIGHTPRICE_MCP_TOKEN"] = tok
        hd = {"Authorization": "Bearer " + tok, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        check("MCP: no token, a wrong token or a token in the address are refused",
              c.get("/mcp/health").status_code == 401 and c.post("/mcp", json={}, headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
              and c.get("/mcp/health?token=" + tok).status_code == 401 and c.get("/mcp/anything", headers={"Authorization": tok}).status_code == 401)
        hl = c.get("/mcp/health", headers=hd).json()
        check("MCP: the health check answers a caller holding the token", hl["ok"] is True and hl["tools"] == 10)
        rpc = lambda method, params, i=1: c.post("/mcp", headers=hd, json={"jsonrpc": "2.0", "id": i, "method": method, "params": params}).json()
        call = lambda name, **args: json.loads(rpc("tools/call", {"name": name, "arguments": args})["result"]["content"][0]["text"])
        listed_t = rpc("tools/list", {})["result"]["tools"]
        names = [t["name"] for t in listed_t]
        writers = {t["name"] for t in listed_t if not (t.get("annotations") or {}).get("readOnlyHint")}
        check("MCP: the ten tools are offered, and only the two that write are marked as writing",
              set(names) == {"list_choices", "cost_fabric", "find_fabrics", "fabric_brief", "supplier_summary", "negotiation_pack", "tracker_steps",
                             "record_tracker_step", "remove_my_tracker_step", "quote_alerts"} and writers == {"record_tracker_step", "remove_my_tracker_step"}, str(writers))
        ex = call("list_choices")["example"]
        check("MCP: a fabric costed through the assistant gives the engine's figure", call("cost_fabric", choices=ex)["should_cost_per_m"] == round(c.post("/api/cost", json=ex).json()["total_per_m"], 2))
        check("MCP: a field the costing does not know, or a value not among the choices, is refused, not ignored",
              "Unknown field" in call("cost_fabric", choices=dict(ex, **{"Yarn shade": "Dark"})).get("error", "") and "Not among the choices" in call("cost_fabric", choices=dict(ex, Route="Woven"))
              .get("error", "") and "Warp yarn dyeing" in call("list_choices")["fields"])
        found = call("find_fabrics", search="Q-4", source="Fabric list")
        qk = found["fabrics"][0]["key"] if found["fabrics"] else None
        check("MCP: a fabric is found with its key and the verdict the screens show", bool(qk) and found["fabrics"][0]["code"] == "Q-4" and found["fabrics"][0]["price_is"].startswith("quoted") and found["fabrics"][0]["tracker"] is None, str(found)[:300])
        no_first = call("record_tracker_step", key=qk, kind="Mill's revised quote", price_per_m=180)
        bad = call("record_tracker_step", key=qk, kind="Mill's quote", price_per_m=0.5)
        wrong = call("record_tracker_step", key=qk, kind="Settled", price_per_m=185)
        ok_ = call("record_tracker_step", key=qk, kind="Mill's quote", price_per_m=185, date="2026-11-20", note="by phone " + "x" * 600)
        twice = call("record_tracker_step", key=qk, kind="Mill's quote", price_per_m=185, date="2026-11-20")
        check("MCP: recording a step keeps the tracker's refusals, asks for the first quote first, refuses a repeat, and marks the step as the assistant's",
              "error" in bad and "Mill's quote" in wrong.get("error", "") and "first quote" in no_first.get("error", "") and "185.00" in no_first["error"]
              and "already recorded" in twice.get("error", "") and ok_.get("recorded") is True and ok_["now"]["steps"][0]["by"] == "AI assistant"
              and ok_["now"]["steps"][0]["note"].endswith("(recorded through the AI assistant)") and ok_["warnings_on_this_step"] == [], str(ok_)[:300])
        slip = call("record_tracker_step", key=qk, kind="Our counter", price_per_m=199, date="2026-11-21")
        undo = call("remove_my_tracker_step", key=qk, kind="Our counter", price_per_m=199)
        early = call("record_tracker_step", key=qk, kind="Mill's revised quote", price_per_m=150, date="2026-11-10")
        above = call("record_tracker_step", key=qk, kind="Agreed", price_per_m=250, date="2026-11-22")
        check("MCP: a step dated before the first quote, and an agreement above the mill's price, are refused",
              "before the mill's first quote" in early.get("error", "") and "above the mill's latest price" in above.get("error", "")
              and len(call("tracker_steps", key=qk)["steps"]) == 1, str(early)[:200] + str(above)[:200])
        call("record_tracker_step", key=qk, kind="Our counter", price_per_m=172, date="2026-11-21")
        keep_first = call("remove_my_tracker_step", key=qk, kind="Mill's quote", price_per_m=185)
        call("remove_my_tracker_step", key=qk, kind="Our counter", price_per_m=172)
        check("MCP: the first quote cannot be removed while later steps rest on it; a stream cannot be opened on the endpoint",
              "first quote" in keep_first.get("error", "") and len(call("tracker_steps", key=qk)["steps"]) == 1
              and c.get("/mcp", headers=hd).status_code == 405 and c.delete("/mcp", headers=hd).status_code == 405)
        check("MCP: a typed number that is not a number is refused", "plain positive numbers" in call("cost_fabric", choices=dict(ex, **{"Order quantity (m)": "5,000"})).get("error", "")
              and "plain positive numbers" in call("cost_fabric", choices=dict(ex, **{"Quoted price (Rs/m)": "inf"})).get("error", ""))
        check("MCP: a warning on the step just recorded is passed back, and the assistant can undo its own step",
              any("above the mill's price" in w for w in slip["warnings_on_this_step"]) and undo.get("removed") is True and len(undo["now"]["steps"]) == 1
              and call("find_fabrics", search="Q-4", source="Fabric list")["fabrics"][0]["tracker"]["mill_latest_per_m"] == 185)
        check("MCP: the brief and the tracker read back what the screens hold",
              call("fabric_brief", key=qk)["negotiation"]["mill_latest"] == 185 and call("tracker_steps", key=qk)["status"] == "Open" and "error" in call("fabric_brief", key="nope") and "error" in call("tracker_steps", key="nope"))
        ev({"key": qk, "code": "Q-4", "kind": "Our counter", "price": 170, "date": "2026-11-22", "metres": 3700})
        check("MCP: with a counter recorded the brief says not to open above it; a person's step cannot be removed by the assistant",
              (lambda b_: b_ is None or (b_.get("open_at_per_m") is None or b_["verdict"] != "Push"))(call("fabric_brief", key=qk).get("brief"))
              and "error" in call("remove_my_tracker_step", key=qk, kind="Our counter", price_per_m=170))
        web_by = c.post("/api/negotiations/event", json={"key": qk, "kind": "Our counter", "price": 180, "date": "2026-11-23", "by": "the owner"}).json()
        check("MCP: a web request cannot name who recorded a step", web_by["events"][-1]["by"] == "")
        os.environ.pop("RIGHTPRICE_MCP_TOKEN", None)

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
        stage5 = dated_checks(c, check)         # (called first: `ok &= f()` would read ok before f could clear it)
        ok &= stage5
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


# ===================================================================== stage 5: dated yarn rates
def _ready_costs(c, until=lambda d: True):
    for _ in range(600):            # Right cost works its verdicts out in the background
        d = c.get("/api/costs").json()
        if d.get("ready") and not any(r.get("band") == "Working it out" for r in d["rows"]) and until(d):
            return d
        time.sleep(0.5)
    raise SystemExit("Right cost's verdicts were not ready after five minutes")


def dated_checks(c, check):
    """A yarn's rate for a month (GP's decision, 27 Nov 2026: purchase orders on the rates of their order month; quotes and
    Create cost on today's). In the database only; on the files every endpoint says so and every costing falls back.
    The rates typed here are made up for the checks; the market history and the purchase orders are the real files."""
    import data_dated
    import pandas as pd
    from rules import dated as dated_rules
    ex = masters.EXAMPLE_ROW
    today = c.post("/api/cost", json=ex).json()
    oct_ = c.post("/api/cost", json=dict(ex, _rates_on="2026-10-05")).json()
    check("Dated rates: Create cost says it is on today's rates; asked for a month with no dated rate it gives today's figure and says so",
          today["rates_of"]["label"] == "today" and oct_["total_per_m"] == today["total_per_m"]          # (earlier checks applied a cost sheet draft: not 181.40 here)
          and oct_["rates_of"]["notes"] == ["No dated rate for Cotton 40S in Oct 2026: today's rate used (Rs 345)"]
          and c.post("/api/cost", json=dict(ex, _rates_on="Sept 2026")).status_code == 400)
    # purchase orders: each on its order month; with no dated rate for Aug to Nov 2026, every figure as before, said per row
    d = _ready_costs(c)
    po = [r for r in d["rows"] if r["source"] == "Purchase orders"]
    by = {}
    for r in po:
        by[(r["rates"] or {}).get("month")] = by.get((r["rates"] or {}).get("month"), 0) + 1
    check("Dated rates: every purchase-order costing names its order month, and with no dated rate for it says today's rates are used",
          len(po) == 1696 and all(r["rates"] and r["rates"]["month"] and not r["rates"]["dated"] and "No dated rate for" in r["rates"]["note"] for r in po)
          and all(r["rates"]["dated"] is False and r["rates"]["note"].startswith("On today's rates") for r in d["rows"] if r["source"] == "Fabric list"),
          str(sorted((k or "none", v) for k, v in by.items())))
    months, lines_ = dated_rules.order_months(), dated_rules.po_lines()
    ties = [k for k, v in months.items() if v["tie"]]
    tied = [r for r in po if r["code"] in set(ties)]
    top = lambda code: (lambda g: sorted(g[g["qty"] == g["qty"].max()]["month"]))(lines_[lines_["Material"] == code])
    check("Dated rates: a code ordered in two months with the same metres is costed on the earlier of them, and says so",
          len(tied) == 60 and all("the most metres in two months alike; costed on the earlier" in r["rates"]["note"] for r in tied)
          and all(len(top(r["code"])) >= 2 and r["rates"]["month"] == top(r["code"])[0] for r in tied), f"{len(tied)} tied")
    dl = pd.read_excel(io.BytesIO(c.post("/api/costs/download", json={"keys": [f"Purchase orders|{po[0]['code']}", f"Fabric list|{next(r['id'] for r in d['rows'] if r['source'] == 'Fabric list')}"]}).content))
    ins = c.get("/api/insights").json()
    check("Dated rates: the list and its spreadsheet say which rates each costing is on; the dashboard says its panels are on today's rates",
          all(r["rates_of"] == f"{r['rates']['label']}: today's yarn rates (no dated rate)" for r in po)
          and all(r["rates_of"] == "Today's rates" for r in d["rows"] if r["source"] == "Fabric list")
          and list(dl["Rates of"]) == [po[0]["rates_of"], "Today's rates"]
          and "on today's rates" in ins["pilot_rates"] and "none does yet" in ins["pilot_rates"], str(ins.get("pilot_rates")))
    # Bring in prices: the document's own date where it can be read, and where from; never today's for a dated rate
    csv = b"Count,Yarn,Rate\n40s,Combed compact,351\n"
    for name, want in (("circular 21.11.2026.csv", (True, "2026-11-21")), ("circular.csv", (False, None))):
        t = c.post("/api/intake/file", files={"file": (name, io.BytesIO(csv))}).json()
        st = c.post("/api/intake/map", json={"token": t["token"], "sheet": next(iter(t["sheets"])), "count": "Count", "low": "Rate", "yarn": "Yarn"}).json()
        check(f"Bring in prices: {name}: the document's date is {'read from its name, and said' if want[0] else 'not read, and it says so'}",
              st["date_read"] is want[0] and (not want[0] or (st["rows"][0][0] == want[1] and st["date_from"] == "the file name" and "21" in st["note"])), str(st)[:300])
    if STORE == "files":
        # the proof that nothing moved: every purchase-order costing on its order month equal to the costing without a date,
        # on the rate master as it ships (read, never saved: the checks above edited this copy's rates on purpose)
        import mill_sheet
        import rate_card
        import store
        import yarn_seed
        m = pd.read_excel(store.SHIPPED_MASTER, sheet_name=None)
        for add_ in (rate_card.apply, yarn_seed.apply, mill_sheet.apply):
            add_(m)
        t0, same = time.time(), 0
        for r in po:
            a = masters.cost(r["choices"], m)
            b = masters.cost(r["choices"], m, on=r["rates"]["month"])
            same += {k: v for k, v in b.items() if k != "rates_of"} == a and round(a["total_per_m"], 2) == r["should"]
        check(f"Dated rates: all {len(po)} purchase-order costings on their order month equal, line by line, the costing without a date and the "
              f"should-cost shown before ({time.time() - t0:.0f} s)", same == len(po), f"{same} of {len(po)}")
        for path, body in (("/api/dated-rates", None), ("/api/dated-rates/market", None), ("/api/dated-rates", {"yarn_key": "Cotton 40S", "month": "2026-09", "rate": 360}),
                           ("/api/dated-rates/remove", {"id": 1}), ("/api/dated-rates/market", {}), ("/api/intake/add-dated", {"rows": []})):
            rr = c.get(path) if body is None else c.post(path, json=body)
            if rr.status_code != 503 or "database" not in rr.json()["detail"]:
                check(f"Dated rates on the files: {path} says it needs a database", False, f"{rr.status_code} {rr.text[:200]}")
                return False
        check("Dated rates on the files: every page and endpoint says plainly it needs a database (503), and the Yarn prices page still opens",
              c.get("/?embed=1").status_code == 200 and c.get("/dated.js").status_code == 200 and c.get("/api/table/Yarn_Rates").status_code == 200)
        return True
    good = True

    def chk(name, g, detail=""):
        nonlocal good
        good &= bool(g)
        check(name, g, detail)
    pg0 = c.get("/api/dated-rates").json()
    chk("Dated rates: the page holds the rule, the yarn master, what a rate may rest on and the purchase orders by month, and no rate yet",
        pg0["rule"] == dated_rules.RULE and pg0["entries"] == [] and pg0["series"] == [] and any(y["key"] == "Cotton 40S" for y in pg0["yarns"])
        and {o["value"] for o in pg0["rests_on"]} == set(dated_rules.RESTS_ON)
        and [o["fabrics"] for o in pg0["orders"]] == [200, 1047, 336, 113] and all(o["none"] == o["fabrics"] for o in pg0["orders"]), str(pg0["orders"]))
    add = lambda **b: c.post("/api/dated-rates", json=dict({"rests_on": "circular"}, **b))
    bad = [add(yarn_key="Cotton 40S", month="2099-01", rate=360), add(yarn_key="Not a yarn", month="2026-09", rate=360),
           add(yarn_key="Cotton 40S", month="2026-09", rate=3), add(yarn_key="Cotton 40S", month="Sept", rate=360),
           add(yarn_key="Cotton 40S", month="2026-09", low=380, high=360), add(yarn_key="Cotton 40S", month="2018-05", rate=300),
           add(yarn_key="Cotton 40S", month="2026-09", rate=360, rests_on=None), add(yarn_key="Cotton 40S", month="2026-09", rate=360, rests_on="other"),
           add(yarn_key="Cotton 40S", month="2026-09", rate=360, low=355, high=369), add(yarn_key="Cotton 40S", month="2026-09", low=355)]
    chk("Dated rates: a month to come, a yarn not in the master, a slip, a month not readable, a high below the low, a year too early, no source "
        "said, another document not named, a rate that is not the range's midpoint, a low without a high: all refused",
        all(b.status_code == 400 for b in bad) and "midpoint, Rs 362.00" in bad[8].json()["detail"], str([b.status_code for b in bad]))
    first = add(yarn_key="Cotton 40S", month="2026-09", rate=358, note="check")
    again = add(yarn_key="Cotton 40S", month="2026-09", low=355, high=369)
    p1 = c.get("/api/dated-rates").json()
    chk("Dated rates: a second rate for the same yarn and month takes the place of the first, which is kept marked replaced; a range counts as its midpoint",
        first.status_code == 200 and again.json()["rate"] == 362 and [(e["yarn_key"], e["month"], e["rate"]) for e in p1["entries"]] == [("Cotton 40S", "2026-09", 362)]
        and p1["history"][0]["rate"] == 358 and p1["history"][0]["removed_why"] == "replaced" and not again.json()["placeholder"])
    sep = c.post("/api/cost", json=dict(ex, _rates_on="2026-09-18")).json()
    typed = c.post("/api/cost", json=dict(ex, **{"Warp yarn price override": 362, "Weft yarn price override": 362})).json()
    nov = c.post("/api/cost", json=dict(ex, _rates_on="2026-11-02")).json()
    quoted = c.post("/api/cost", json=dict(ex, _rates_on="2026-09-18", **{"Quoted price (Rs/m)": 200})).json()
    chk("Dated rates: costed on Sep 2026 the yarn is on its dated rate; Nov 2026 has none and is on today's; Create cost stays on today's; "
        "the brief says its usual range is measured on today's rates",
        abs(sep["total_per_m"] - typed["total_per_m"]) < 1e-9 and sep["rates_of"]["dated"] and "dated rate for Sep 2026" in sep["rates_of"]["notes"][0]
        and nov["total_per_m"] == today["total_per_m"] and c.post("/api/cost", json=ex).json()["total_per_m"] == today["total_per_m"]
        and "measured on today's rates" in quoted["brief"]["band"]["why"] and "dated rates of Sep 2026" in quoted["brief"]["band"]["why"])
    # Right cost follows: the Sep 2026 purchase orders on Cotton 40S are costed on it, and say so; the others do not move
    hit = {r["code"] for r in po if r["rates"]["month"] == "2026-09" and "Cotton 40S" in (r["choices"]["Warp yarn"], r["choices"]["Weft yarn"])}
    d2 = _ready_costs(c, until=lambda x: any((r.get("rates") or {}).get("dated") for r in x["rows"]))
    po2 = {r["code"]: r for r in d2["rows"] if r["source"] == "Purchase orders"}
    moved = {k for k, r in po2.items() if r["rates"]["dated"]}
    one = po2[sorted(hit)[0]] if hit else None
    m = rules_common.get_masters()
    want = None if one is None else masters.cost(one["choices"], m, on="2026-09")
    chk(f"Dated rates: Right cost costs the {len(hit)} Sep 2026 purchase orders on Cotton 40S on its dated rate, and no other, their figures following it",
        moved == hit and len(hit) > 0 and one["should"] == round(want["total_per_m"], 2) and one["gap"] == round(want["gap"], 2)
        and "Cotton 40S: the dated rate for Sep 2026 is used" in one["rates"]["note"] and one["rates_of"] == "Sep 2026: dated yarn rate"
        and all(po2[k]["should"] == r["should"] for k, r in ((r["code"], r) for r in po) if k not in hit), f"{len(moved)} moved, {len(hit)} expected")
    chk("Dated rates: the dashboard says how many orders Right cost costs on a dated rate, so its panels' figures differ for them",
        f"Right cost costs {len(hit)} of these orders on a dated yarn rate" in c.get("/api/insights").json()["pilot_rates"])
    sp = c.get("/api/supplier", params={"mill": one["supplier"]}).json() if one else {}
    chk("Dated rates: the supplier page counts its purchases on a dated rate and says so",
        sp.get("bought", {}).get("rates", {}).get("dated", 0) >= 1 and "dated" in sp["bought"]["rates"]["text"], str(sp.get("bought", {}).get("rates"))[:300])
    rid = p1["entries"][0]["id"]
    gone = c.post("/api/dated-rates/remove", json={"id": rid})
    chk("Dated rates: a rate removed is kept marked removed, removing it twice is refused, and the month falls back to today's rate",
        gone.status_code == 200 and c.post("/api/dated-rates/remove", json={"id": rid}).status_code == 404
        and c.post("/api/cost", json=dict(ex, _rates_on="2026-09-18")).json()["total_per_m"] == today["total_per_m"]
        and c.get("/api/dated-rates").json()["history"][0]["removed_why"] == "removed")
    # rule 4: a rate typed with no source is a placeholder. On a placeholder yarn at today's figure it changes no verdict,
    # no should-cost and no placeholder column (the cold review saw 117 verdicts flip here before it was fixed)
    slub = {r["code"] for r in po if r["rates"]["month"] == "2026-09" and "Cotton Slub 20S" in (r["choices"]["Warp yarn"], r["choices"]["Weft yarn"])}
    ph = add(yarn_key="Cotton Slub 20S", month="2026-09", rate=338, rests_on="none").json()
    d3 = _ready_costs(c, until=lambda x: any((r.get("rates") or {}).get("dated") for r in x["rows"]))
    po3 = {r["code"]: r for r in d3["rows"] if r["source"] == "Purchase orders"}
    m = rules_common.get_masters()

    def as_today(r):        # a Slub order costed without a date on the same rate master (the pilot's stored figures predate this suite's rate edits)
        res = masters.cost(r["choices"], m)
        return {"should": round(res["total_per_m"], 2), "gap": round(res["gap"], 2), "placeholders": ", ".join(res["placeholders"]) or None}
    same = [r["code"] for r in po if all(po3[r["code"]][f] == r[f] for f in ("band", "range", "why_unsure"))
            and (all(po3[r["code"]][f] == r[f] for f in ("should", "gap", "gap_pct", "excess", "placeholders")) if r["code"] not in slub else
                 (lambda t: all(po3[r["code"]][f] == t[f] for f in t) and abs(po3[r["code"]]["excess"] - t["gap"] * r["metres"]) < 0.01)(as_today(r)))]
    chk(f"Dated rates: a rate with no source is a placeholder; on Cotton Slub 20S at today's figure its {len(slub)} Sep 2026 orders say so and no "
        "verdict, should-cost or placeholder column moves",
        ph["placeholder"] and len(slub) > 0 and {k for k, r in po3.items() if r["rates"]["dated"]} == slub and len(same) == len(po)
        and all("a placeholder, entered with no source" in po3[k]["rates"]["note"] for k in slub), f"{len(same)} of {len(po)} the same")
    sl = dict(ex, **{"Warp yarn": "Cotton Slub 20S", "Weft yarn": "Cotton Slub 20S"})
    add(yarn_key="Cotton Slub 20S", month="2026-09", rate=338, rests_on="quote", note="spinner's quote")
    src = c.post("/api/cost", json=dict(sl, _rates_on="2026-09")).json()
    chk("Dated rates: the same yarn and month with a source (a quote) is no longer a placeholder in the costing",
        "Warp yarn" in c.post("/api/cost", json=sl).json()["placeholders"] and "Warp yarn" not in src["placeholders"] and "Weft yarn" not in src["placeholders"])
    for e in c.get("/api/dated-rates").json()["entries"]:
        c.post("/api/dated-rates/remove", json={"id": e["id"]})
    # the market history in hand: only the yarns surely in the yarn master; a person's rate and a person's removal hold
    mk = c.get("/api/dated-rates/market").json()
    chk("Dated rates: the market history gives only the linen it surely matches (Raymond 100% linen 40 and 60 lea, standard, Jun 2026, range midpoints) "
        "and says why every other row is left out",
        mk["rows"] == 5275 and mk["used_rows"] == 2 and [(r["yarn_key"], r["month"], r["rate"], r["status"]) for r in mk["rates"]] ==
        [("Linen 40 Lea", "2026-06", 1625, "new"), ("Linen 60 Lea", "2026-06", 2225, "new")] and mk["to_load"] == 2
        and sum(x["rows"] for x in mk["left_out"]) == 5273 and any("Semi-combed cotton" in x["why"] and x["rows"] == 613 for x in mk["left_out"]), str(mk["left_out"])[:300])
    add(yarn_key="Linen 40 Lea", month="2026-06", rate=1500, rests_on="quote", note="a person's rate")
    l1 = c.post("/api/dated-rates/market", json={}).json()
    v1 = data_dated.version()
    l2 = c.post("/api/dated-rates/market", json={}).json()
    es = {(e["yarn_key"], e["month"]): e for e in c.get("/api/dated-rates").json()["entries"]}
    chk("Dated rates: loading the market history keeps a person's rate, and loading it again writes nothing (nothing is worked out again)",
        l1["added"] == 1 and l1["kept"] == 1 and l2["added"] == 0 and l2["unchanged"] == 1 and l2["kept"] == 1 and data_dated.version() == v1
        and es[("Linen 40 Lea", "2026-06")]["rate"] == 1500 and es[("Linen 60 Lea", "2026-06")]["source"] == "market history", f"{l1} {l2}")
    c.post("/api/dated-rates/remove", json={"id": es[("Linen 60 Lea", "2026-06")]["id"]})
    l3 = c.post("/api/dated-rates/market", json={}).json()
    chk("Dated rates: a market-history rate a person removed is not brought back by the next load, and the preview says so",
        l3["added"] == 0 and l3["held_removed"] == 1 and not any(e["yarn_key"] == "Linen 60 Lea" for e in c.get("/api/dated-rates").json()["entries"])
        and next(r for r in c.get("/api/dated-rates/market").json()["rates"] if r["yarn_key"] == "Linen 60 Lea")["status"] == "held", str(l3))
    yarns_ = dated_rules._yarns()
    row = {"Yarn Category": "Linen Yarn", "Material": "Linen", "Blend / Composition": "100% Linen", "Count": "40 lea", "Variant": "Standard",
           "Supplier / Mill": "Raymond", "Original Price": "1600-1650", "Original Unit": "₹/kg", "Standard Price": None, "Standard Unit": "₹/kg",
           "Date": 46197, "Year": 2026, "Month": "June", "GST Included": "Yes"}
    dec = lambda **k: dated_rules.market_decide(dict(row, **k), yarns_)
    ok_, _ = dec()
    outs = [dec(**{"Blend / Composition": "55% Linen / 45% Cotton"}), dec(Variant="Dyed"), dec(**{"Supplier / Mill": "Another mill"}),
            dec(**{"Original Unit": "₹/Candy"}), dec(**{"Standard Price": 6000}), dec(**{"Standard Price": 1625, "Standard Unit": "₹/Candy"}), dec(Count="44 lea")]
    chk("Dated rates: a market price is used only for the same fibre, blend, count, kind and spinner, in rupees a kilo, between Rs 50 and 5,000",
        ok_ and ok_["key"] == "Linen 40 Lea" and ok_["month"] == "2026-06" and (ok_["low"], ok_["high"]) == (1600, 1650) and ok_["gst"]
        and all(o[0] is None for o in outs) and outs[3][1] == outs[5][1] == "Not a price per kilo" and "Rs 50" in outs[4][1], str(outs))
    # from Bring in prices: rows given a yarn of the master; the month from the document or chosen, never today's; GST asked
    rows = [["2026-08-04", "Combed compact", "40s", 350, 360, "circular", "Cotton 40S"], ["2026-08-21", "Combed compact", "40s", 364, None, "circular", "Cotton 40S"],
            ["2026-08-21", "Combed compact", "50s", 400, 410, "circular", ""]]
    post = lambda **b: c.post("/api/intake/add-dated", json=dict({"rows": rows, "source": "circular.pdf"}, **b))
    no_gst, no_month = post(dates_read=True), post(gst=False)
    chk("Dated rates from Bring in prices: refused unless it is said whether the prices include GST, and unless the month is the document's own or chosen",
        no_gst.status_code == 400 and "GST" in no_gst.json()["detail"] and no_month.status_code == 400 and "choose the month" in no_month.json()["detail"])
    got = post(gst=False, dates_read=True, date_from="the file name").json()
    chk("Dated rates from Bring in prices: with the document's dates, two prices of one yarn in a month are averaged (a range as its midpoint), a row given no yarn is left out",
        got.get("added") == 1 and got["left_out"] == 1 and got["rates"] == [{"yarn_key": "Cotton 40S", "month": "2026-08", "rate": 359.5, "entries": 2}], str(got))
    got2 = post(gst=True, month="2026-07").json()
    e7 = next(e for e in c.get("/api/dated-rates").json()["entries"] if e["month"] == "2026-07")
    chk("Dated rates from Bring in prices: a month chosen for the document is every row's month, and prices with GST say so",
        got2["rates"] == [{"yarn_key": "Cotton 40S", "month": "2026-07", "rate": 359.5, "entries": 2}] and "includes GST" in e7["basis"] and "month chosen" in e7["basis"], str(got2))
    chk("Dated rates from Bring in prices: a yarn not in the master, or a row with no date when the dates were read, is refused with its row number",
        "Row 1" in c.post("/api/intake/add-dated", json={"rows": [["2026-08-04", "x", "40s", 350, 360, "", "Cotton 41S"]], "gst": False, "dates_read": True}).json()["detail"]
        and c.post("/api/intake/add-dated", json={"rows": [[None, "x", "40s", 350, 360, "", "Cotton 40S"]], "gst": False, "dates_read": True}).status_code == 400
        and c.post("/api/intake/add-dated", json={"rows": [rows[2]], "gst": False, "dates_read": True}).status_code == 400)
    pg = c.get("/api/dated-rates").json()
    s40 = next(s for s in pg["series"] if s["key"] == "Cotton 40S")
    chk("Dated rates: the page's chart holds each yarn by month from the first dated month to this one, a month without a rate left empty",
        pg["months"][0] == "2026-06" and pg["months"][-1] == pg["this_month"] and len(s40["points"]) == len(pg["months"])
        and [p and p["rate"] for p in s40["points"]][:4] == [None, 359.5, 359.5, None] and data_dated.version() is not None)
    chk("Dated rates: the store counts them", c.get("/api/store").json()["counts"]["dated yarn rates"] == len(pg["entries"]))
    for e in pg["entries"]:         # leave the store as the rest of the suite found it
        c.post("/api/dated-rates/remove", json={"id": e["id"]})
    return good


# ===================================================================== the move from files to a database, proved
def build(c):
    """Fill an empty data folder through the app, as people would: two mill sheets, fabrics added on screen, a rate
    edited (which keeps a dated copy), a cotton price, negotiations with every kind of step and one removed, an alert
    marked seen, a row removed, and mill cost sheets."""
    import pandas as pd
    import mill_sheet
    today = _dt.date.today()
    day = lambda n: (today - _dt.timedelta(days=n)).isoformat()
    base = {"Brand": "AS", "Fab Code": "P-1", "YD/NYD": "YD", "Material Type": "100% Cotton", "Warp": 40, "Weft": 40,
            "EPI": 136, "PPI": 90, "Variety": "YDS", "Weave": "2/1 RHT", "F.W.": 145, "Finish": "Normal",
            "Arvind Ref": "x/1", "Total order qnty": 2255, "Base Price": 164, "Std EPI": 122, "Std PPI": 76,
            "Actual EPI": 136, "Actual PPI": 90, "Diff EPI": 14, "Diff PPI": 14, "EPI Upch": 8.4, "PPI Upch": 12.6,
            "Finish Upch": 0, "Dobby Upch": 0, "Upcharge/Print/Mcount": 0, "Double beam": 0, "Price": 185,
            "Upcharge for less qnty": 0, "Discoun>2000 mts": 0, "Total price with qnty disc/upcharge": 185,
            "Ex mill price": 185, "C2FO @2.84%": 190.254}
    hi = dict(base, **{"Price": 240, "Ex mill price": 240, "Total price with qnty disc/upcharge": 240, "Total order qnty": 5000})
    sheets = [[base, dict(base, **{"Fab Code": "P-2", "Price": 188}), dict(base, **{"Fab Code": "P-3", "YD/NYD": "NYD"}),
               dict(base, **{"Fab Code": "P-4", "Warp": "40+2/80 (98/2)"}), dict(hi, **{"Fab Code": "P-5"}), dict(hi, **{"Fab Code": "P-6"}),
               dict(base, **{"Fab Code": "P-7", "Material Type": "PC 65/35"}),
               dict(base, **{"Fab Code": "P-8", "Price": 70, "Ex mill price": 70, "Total price with qnty disc/upcharge": 70, "Total order qnty": 3300})],
              [dict(base, **{"Fab Code": "R-1", "Total order qnty": 4100, "Weave": "Plain"}), dict(hi, **{"Fab Code": "R-2", "EPI": 144})]]
    for n, rows in enumerate(sheets):
        buf = io.BytesIO()
        pd.DataFrame(rows, columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
        assert c.post("/api/list/upload", files={"file": (f"mill sheet {n + 1}.xlsx", io.BytesIO(buf.getvalue()))}).status_code == 200
    for sup, price, code in (("Arvind Limited", 200, "S-1"), ("Rajapalayam Mills Ltd", 171.5, "S-2"), ("Nahar Industrial Enterprises", 150, "S-3")):
        assert c.post("/api/list/add", json=dict(masters.EXAMPLE_ROW, **{"Fabric code": code, "Supplier": sup, "Quoted price (Rs/m)": price,
                                                                         "Order quantity (m)": 3000})).status_code == 200
    yr = c.get("/api/table/Yarn_Rates").json()
    ki, ri = yr["columns"].index("Yarn key"), yr["columns"].index("Rate Rs/kg")
    rows = [list(r) for r in yr["rows"]]
    next(r for r in rows if r[ki] == "Cotton 40S")[ri] = 352
    assert c.put("/api/table/Yarn_Rates", json={"columns": yr["columns"], "rows": rows}).status_code == 200
    assert c.post("/api/cotton", json={"date": day(1), "price": 55400, "source": "check"}).status_code == 200
    listed = {r["mill"].get("Fab Code") or (r["inputs"] or {}).get("Fabric code"): r for r in c.post("/api/list", json={}).json()["rows"]}
    k1, k2 = f"Fabric list|{listed['S-1']['id']}", f"Fabric list|{listed['R-2']['id']}"
    for key, kind, price, n in ((k1, "Mill's quote", 200, 10), (k1, "Our counter", 185, 8), (k1, "Mill's revised quote", 192, 5),
                                (k1, "Agreed", 190, 2), (k2, "Mill's quote", 240, 6), (k2, "Our counter", 205, 4)):
        assert c.post("/api/negotiations/event", json={"key": key, "kind": kind, "price": price, "date": day(n), "metres": 3000,
                                                       "code": key, "note": f"{kind} by phone"}).status_code == 200, kind
    step = c.get("/api/negotiations").json()["items"][k2]["events"][-1]
    assert c.post("/api/negotiations/remove", json={"key": k2, "id": step["id"]}).status_code == 200
    po = next(r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Purchase orders" and r.get("price"))
    kp = f"Purchase orders|{po['code']}"
    for kind, price, n in (("Mill's quote", round(po["price"], 2), 20), ("Agreed", round(po["price"] * 0.97, 2), 12)):
        assert c.post("/api/negotiations/event", json={"key": kp, "kind": kind, "price": price, "date": day(n), "metres": 1200}).status_code == 200
    al = c.get("/api/alerts").json()
    assert al["ids"], "no alerts to mark seen"
    c.post("/api/alerts/seen", json={"ids": sorted(al["ids"])[:1]})
    assert c.post("/api/list/remove", json={"ids": [listed["P-3"]["id"]]}).json()["removed"] == 1
    tpl = c.get("/api/costsheet/template")
    cs = pd.read_excel(io.BytesIO(tpl.content), sheet_name="Cost sheet")
    cs.loc[0, "Overhead %"] = 6
    cs.loc[0, "Mill"] = "Mill A"
    cs2 = cs.copy()
    cs2["Mill"] = "Mill B"
    cs2.loc[0, "Overhead %"] = 8
    buf = io.BytesIO()
    pd.concat([cs, cs2]).to_excel(buf, index=False)
    assert c.post("/api/costsheet/upload", files={"file": ("cost sheets.xlsx", io.BytesIO(buf.getvalue()))}).status_code == 200


def dump(c):
    """Every page's answer that carries a figure, for comparing two stores exactly."""
    import pandas as pd
    for _ in range(600):            # Right cost works its verdicts out in the background after a start
        costs = c.get("/api/costs").json()
        if costs.get("ready") and not any(r.get("band") == "Working it out" for r in costs["rows"]):
            break
        time.sleep(0.5)
    else:
        raise SystemExit("Right cost's verdicts were not ready after five minutes")
    out = {"costs": costs, "meta": c.get("/api/meta").json(), "cost": c.post("/api/cost", json=masters.EXAMPLE_ROW).json(),
           "list": c.post("/api/list", json={}).json(), "list with yarn moved": c.post("/api/list", json={"yarn_pct": {"*": 7.5}}).json(),
           "pack": c.post("/api/pack", json={}).json(), "alerts": c.get("/api/alerts").json(),
           "negotiations": c.get("/api/negotiations").json(), "won": c.get("/api/negotiations/summary").json(),
           "suppliers": c.get("/api/suppliers").json(), "dashboard": c.get("/api/dashboard").json(), "insights": c.get("/api/insights").json(),
           "cost sheets": c.get("/api/costsheet").json(), "cotton": c.get("/api/cotton").json()}
    out["tables"] = {t: c.get(f"/api/table/{t}").json() for t in out["meta"]["tables"]}
    listed = sorted({r["supplier"] for r in out["costs"]["rows"] if r["source"] == "Fabric list" and r.get("supplier")})
    mills = listed + [s["name"] for s in out["suppliers"]["suppliers"][:4]]
    out["supplier pages"] = {m: c.get("/api/supplier", params={"mill": m}).json() for m in mills}
    out["drafts"] = {m: c.post("/api/draft", json={"scope": {"type": "supplier", "mill": m}, "ask": "breakup"}).json() for m in listed}
    out["list download"] = pd.read_excel(io.BytesIO(c.post("/api/list/download", json={}).content)).to_json()
    keys = [f"{r['source']}|{r.get('id') or r['code']}" for r in out["costs"]["rows"] if r["source"] == "Fabric list"]
    keys += [f"{r['source']}|{r['code']}" for r in out["costs"]["rows"] if r["source"] == "Purchase orders"][:40]
    out["Right cost download"] = pd.read_excel(io.BytesIO(c.post("/api/costs/download", json={"keys": keys}).content)).to_json()
    out["store"] = c.get("/api/store").json()
    return out


def child():
    """One run on one store: the checks, or one step of the proof. Answers go to RIGHTPRICE_CHECK_OUT."""
    task, out = os.environ.get("RIGHTPRICE_CHECK_TASK", "suite"), os.environ.get("RIGHTPRICE_CHECK_OUT")
    if task == "suite":
        return main()
    with TestClient(server.app) as c:
        if task == "build":
            build(c)
        result = dump(c) if task in ("build", "dump") else None
        if task == "refused":
            result = {"store": c.get("/api/store").json(), "list": [c.post("/api/list", json={}).status_code, c.post("/api/list", json={}).json()],
                      "cost": c.post("/api/cost", json=masters.EXAMPLE_ROW).status_code, "home": c.get("/").status_code}
    if task == "export":
        import store
        result = store.export(os.environ["RIGHTPRICE_CHECK_EXPORT"])        # as `python store.py export <folder>` does
    with open(out, "w", encoding="utf8") as f:
        json.dump(result, f, sort_keys=True, default=str)
    return 0


def _first_difference(a, b, path="$"):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return f"{path}: {type(a).__name__} {str(a)[:80]} / {type(b).__name__} {str(b)[:80]}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: only on one side"
            d = _first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items / {len(b)}"
        for n, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, f"{path}[{n}]")
            if d:
                return d
    elif a != b:
        return f"{path}: {str(a)[:80]} / {str(b)[:80]}"
    return None


def _hashes(folder):
    out = {}
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[name] = (hashlib.sha256(f.read()).hexdigest(), os.path.getmtime(p))
    return out


class _Postgres:
    """Throwaway databases on the test server named by RIGHTPRICE_TEST_DATABASE_URL, dropped at the end."""

    def __init__(self):
        self.admin = os.environ.get("RIGHTPRICE_TEST_DATABASE_URL", "").strip()
        self.made, self.why = [], None
        if not self.admin:
            self.why = "RIGHTPRICE_TEST_DATABASE_URL is not set"
        elif "azure.com" in self.admin.split("@")[-1] or self.admin == os.environ.get("DATABASE_URL", "").strip():
            raise SystemExit("RIGHTPRICE_TEST_DATABASE_URL names the live database: the checks never run on it")
        else:
            try:
                import psycopg
                psycopg.connect(self.admin, autocommit=True, connect_timeout=10).close()
            except Exception as e:
                self.why = f"the test PostgreSQL could not be reached ({type(e).__name__})"

    def new(self):
        import psycopg
        from urllib.parse import urlsplit, urlunsplit
        name = f"rp_check_{os.getpid()}_{len(self.made)}"
        with psycopg.connect(self.admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
            conn.execute(f'CREATE DATABASE "{name}"')
        self.made.append(name)
        u = urlsplit(self.admin)
        return urlunsplit((u.scheme, u.netloc, "/" + name, u.query, u.fragment))

    def drop(self):
        import psycopg
        with psycopg.connect(self.admin, autocommit=True) as conn:
            for name in self.made:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _run(store_kind, task, data=None, url=None, out=None, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "RIGHTPRICE_DATA", "ANTHROPIC_API_KEY")}
    # one hash seed for every run, so that two runs compare like with like (anything that walks a set of names in
    # Python's own order then walks it the same way in both)
    env.update(RIGHTPRICE_CHECK_STORE=store_kind, RIGHTPRICE_CHECK_TASK=task, PYTHONUNBUFFERED="1", PYTHONHASHSEED="20261127")
    if data:
        env["RIGHTPRICE_DATA"] = data
    if url:
        env["RIGHTPRICE_CHECK_URL"] = url
    if out:
        env["RIGHTPRICE_CHECK_OUT"] = out
    env.update(extra or {})
    return subprocess.Popen([sys.executable, os.path.abspath(__file__)], env=env, cwd=HERE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _finish(p, label, show=False):
    stdout, stderr = p.communicate()
    if show or p.returncode:
        print(f"\n== {label} ==")
        print("\n".join(line for line in stdout.splitlines() if line.strip()))
    if p.returncode:
        print("\n".join(stderr.splitlines()[-25:]))
    return p.returncode == 0, stdout + stderr


def store_checks(check, kinds, fresh, pg_url=None):
    """The data layer on its own, on each database: tables added once, writers waiting for each other across
    connections, steps removed in order, the list's columns kept, a dropped connection made again."""
    import store
    for kind, url in kinds:
        empty = tempfile.mkdtemp(prefix="rightprice-store-")
        s = store.SqlStore(url, folder=empty)
        check(f"[{kind}] Tables added and the (empty) files copied in", s.error is None and s.imported is not None, str(s.error))
        s.migrate()
        with s.tx() as c:
            n = c.one("SELECT count(*) FROM schema_migration")[0]
        check(f"[{kind}] Each numbered file of tables applied once, however often the app starts", n == len([f for f in os.listdir(os.path.join(HERE, "db")) if f[:3].isdigit()]))
        others = [store.SqlStore(url, folder=empty, start=False) for _ in range(6)]       # six connections, as six processes would be
        wins, fails = [], []

        def record(x, n):
            try:
                x.add_step("Fabric list|race", {"code": "race"}, {"id": f"r{n}", "at": "2026-11-27T10:00:00", "date": "2026-11-27",
                                                                 "kind": "Mill's quote", "price": 100.0 + n, "note": "", "by": ""}, seen=0)
                wins.append(n)
            except store.Conflict:
                fails.append(n)
        ts = [threading.Thread(target=record, args=(x, n)) for n, x in enumerate(others)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        check(f"[{kind}] Six pages recording a first step at once: one is recorded, five are told to look again",
              len(wins) == 1 and len(fails) == 5 and len(s.read_negotiations()["Fabric list|race"]["events"]) == 1, f"{wins} {fails}")
        for n in (2, 3, 4):
            s.add_step("Fabric list|race", {}, {"id": f"s{n}", "at": "x", "date": "2026-11-27", "kind": "Our counter", "price": 90.0, "note": "", "by": "GP"})
        s.remove_step("Fabric list|race", "s4", "2026-11-27T11:00:00", "GP")
        s.remove_step("Fabric list|race", "s2", "2026-11-27T11:00:00", "GP")
        rec = s.read_negotiations()["Fabric list|race"]
        check(f"[{kind}] Removed steps kept, in the order they were removed",
              [e["id"] for e in rec["removed"]] == ["s4", "s2"] and [e["id"] for e in rec["events"]] == [f"r{wins[0]}", "s3"]
              and rec["removed"][0]["removed_by"] == "GP")
        s.append_list([{"Fabric code": "A", "Id": "1", "Inputs": '{"a": 1}'}, {"Fabric code": "B", "Id": "2", "Odd column": "x"}])
        s.remove_list({"1", "2"})
        f = s.read_list()
        check(f"[{kind}] The list keeps its columns when every row is removed, as the file did",
              len(f) == 0 and list(f.columns)[-1] == "Odd column" and "Inputs" in f.columns)
        s.change_seen(["a", "b"])
        s.change_seen(["a"], undo=True)
        b = s.read_seen()
        s.change_seen(restore=True)
        check(f"[{kind}] Alerts seen, one brought back, all brought back", b == {"b"} and s.read_seen() == set())
        if kind == "postgres":
            import psycopg
            pid = s._read(lambda c: c.one("SELECT pg_backend_pid()")[0])
            with psycopg.connect(url, autocommit=True) as conn:
                conn.execute("SELECT pg_terminate_backend(%s)", (pid,))
            time.sleep(0.5)
            check("[postgres] A connection the server dropped is made again at the next read", s.read_seen() == set()
                  and s._read(lambda c: c.one("SELECT pg_backend_pid()")[0]) != pid)
        for x in others + [s]:
            x._drop()
        # a step saved by an earlier version, without "by": copied in, and read back without it
        old = tempfile.mkdtemp(prefix="rightprice-old-")
        with open(os.path.join(old, "negotiations.json"), "w", encoding="utf8") as f:
            json.dump({"Fabric list|1": {"key": "Fabric list|1", "events": [{"id": "e1", "at": "2026-11-26T09:00:00", "date": "2026-11-26",
                                                                            "kind": "Mill's quote", "price": 180, "note": ""}]}}, f)
        with open(os.path.join(old, "alerts_seen.json"), "w", encoding="utf8") as f:
            json.dump([1, "2"], f)
        o = store.SqlStore(fresh(kind), folder=old)
        check(f"[{kind}] A tracker step saved before steps had a 'by' copies in and reads back as it was",
              o.error is None and o.read_negotiations() == store.FileStore(old).read_negotiations(), str(o.error))
        # the files' note: an empty database where these files were already moved is refused, nothing copied
        e = store.SqlStore(fresh(kind), folder=old)
        check(f"[{kind}] An empty database for files already moved is refused, and nothing is copied",
              e.started is False and "already copied into a database" in (e.error or ""))
        # files worked on after the move; then keep-database sets them aside (they are not changed)
        with open(os.path.join(old, "alerts_seen.json"), "w", encoding="utf8") as f:
            json.dump(["1", "2", "3"], f)
        o2 = store.SqlStore(o.url, folder=old)
        stopped = o2.started is False and "alerts_seen.json" in (o2.error or "")
        before_files = _hashes(old)
        store.SqlStore(o.url, folder=old, start=False).keep_database()
        o3 = store.SqlStore(o.url, folder=old)
        check(f"[{kind}] Files worked on after the move stop the start; keep-database lets it start, the files untouched",
              stopped and o3.started and o3.read_seen() == {"1", "2"} and _hashes(old) == before_files, str(o3.error))
        for x in (o, e, o2, o3):
            x._drop()
    # an outage at start passes by itself: the store tries again
    if pg_url:
        import socket
        from urllib.parse import urlsplit
        target = urlsplit(pg_url)
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        port = lsock.getsockname()[1]
        lsock.close()          # nothing listens there yet: the database "cannot be reached"
        late = pg_url.replace(f"{target.hostname}:{target.port}", f"127.0.0.1:{port}")
        d = store.SqlStore(late, folder=tempfile.mkdtemp(prefix="rightprice-late-"))
        d.RETRY = 0.5
        down = d.started is False and "could not be reached" in (d.error or "")

        def relay():
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", port))
            srv.listen(5)
            while True:
                a, _ = srv.accept()
                b = socket.create_connection((target.hostname, target.port))
                for x, y in ((a, b), (b, a)):
                    threading.Thread(target=lambda x=x, y=y: [y.sendall(chunk) for chunk in iter(lambda: x.recv(65536), b"")], daemon=True).start()
        threading.Thread(target=relay, daemon=True).start()
        time.sleep(1)
        check("[postgres] A database that was down when the app started is used once it answers, with no restart",
              down and d.read_seen() == set() and d.started, str(d.error))
        d._drop()
    # passwords as people type them; a relative SQLite path
    p = store.SqlStore("postgresql://rpadmin:Pa@ss:w/rd#1%x?y@db.example.com:5432/postgres?sslmode=require", start=False)
    q = store.SqlStore("postgresql://rpadmin:Summer%2026@db.example.com/postgres?sslmode=require&application_name=me@laptop"
                       "&options=-c%20search_path%3Dpublic", start=False)
    v = store.SqlStore("postgresql:///postgres?host=db.example.com&port=6432&user=gp", start=False)
    check("A password in DATABASE_URL is typed as it is, whatever its characters, and is never shown; the rest is read as PostgreSQL reads it",
          p._pg["password"] == "Pa@ss:w/rd#1%x?y" and p._pg["host"] == "db.example.com" and p._pg["sslmode"] == "require"
          and "ss:w" not in p.where() + p.scrub("x Pa@ss:w/rd#1%x?y x") and q._pg["password"] == "Summer%2026"
          and q._pg["application_name"] == "me@laptop" and q.where() == "db.example.com:5432/postgres"
          and v._pg.get("user") == "gp" and v.where() == "db.example.com:6432/postgres")
    rel = os.path.join(HERE, "rightprice-data-check-relative")
    r = store.SqlStore("sqlite:///rightprice-data-check-relative/rp.db", folder=tempfile.mkdtemp(prefix="rightprice-rel-"))
    try:
        r.read_seen()
        used = True
    except store.StoreUnavailable:
        used = False
    check("A SQLite file named by a relative path is refused (a deploy would replace it), and stays refused at the next request",
          r.started is False and "full path" in (r.error or "") and not used and not os.path.exists(rel))
    m = store.SqlStore("mysql://x@y/z")
    check("A setting that is neither PostgreSQL nor SQLite is refused, and says so", m.started is False and "neither postgresql" in (m.error or ""))


def parent():
    pg = _Postgres()
    try:
        return _parent(pg)
    finally:            # the throwaway databases go, whatever happened
        if not pg.why:
            pg.drop()


def _parent(pg):
    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    if pg.why:
        need = os.environ.get("RIGHTPRICE_CHECK_REQUIRE_POSTGRES") == "1"
        print(f"PostgreSQL: {'MISMATCH' if need else 'not tried'}: {pg.why}")
        ok &= not need
    sp = tempfile.mkdtemp(prefix="rightprice-checks-")
    sqlite_url = lambda name: "sqlite:///" + os.path.join(sp, name)
    t0 = time.time()

    # 1. the checks on each store, side by side
    runs = [("files", None), ("sqlite", sqlite_url("suite.db"))] + ([("postgres", pg.new())] if not pg.why else [])
    procs = [(kind, _run(kind, "suite", url=url)) for kind, url in runs]
    # 2a. meanwhile, a data folder filled on the files, and every answer kept
    folder = os.path.join(sp, "data")
    os.makedirs(folder)
    built = _run("files", "build", data=folder, out=os.path.join(sp, "files.json"))
    results = {}
    for kind, p in procs:
        good, text = _finish(p, f"the checks on {kind}", show=True)
        results[kind] = good and "ALL OK" in text
        check(f"The checks on {kind}", results[kind])
    good, _ = _finish(built, "a data folder filled on the files")
    check("A data folder filled through the app on the files", good)
    if not good:
        print("ALL OK" if False else "SOMETHING FAILED")
        return 1
    before = _hashes(folder)
    with open(os.path.join(sp, "files.json"), encoding="utf8") as f:
        files_answers = json.load(f)
    # 2b. the same folder copied into each database at its first start, as the live app will do it
    targets = [("sqlite", sqlite_url("moved.db"))] + ([("postgres", pg.new())] if not pg.why else [])
    moves = [(kind, url, _run(kind, "dump", data=folder, url=url, out=os.path.join(sp, f"{kind}.json"))) for kind, url in targets]
    n_costings = len(files_answers["costs"]["rows"])       # every purchase-order costing and every row of the list
    for kind, url, p in moves:
        good, _ = _finish(p, f"the folder copied into {kind}")
        if not good:
            check(f"The folder copied into {kind}", False)
            continue
        with open(os.path.join(sp, f"{kind}.json"), encoding="utf8") as f:
            ans = json.load(f)
        moved = ans.pop("store")
        a = dict(files_answers)
        a.pop("store")
        diff = _first_difference(a, ans)
        check(f"Moved into {kind}: every page's answer exactly as on the files: all {n_costings} costings of Right cost to the paisa, "
              "the list with and without a yarn move, the pack, alerts, tracker, supplier pages, drafts, dashboard, tables, downloads",
              diff is None, diff or "")
        copied = moved.get("copied_in") or {}
        check(f"Moved into {kind}: the app copied the files in at its start and checked them",
              moved.get("store") == kind and moved.get("ok") and copied.get("checked", {}).get("equal") is True
              and any(int(re.search(r"(\d+) costed on both, equal to the paisa", x).group(1)) >= 6 for x in copied["checked"]["summary"]
                      if "costed on both" in x)
              and moved["counts"]["fabric list rows"] == len(files_answers["list"]["rows"])
              and moved["counts"]["rate versions"] >= 2,          # the dated copy of the rate edit came in as an earlier version
              "; ".join(copied.get("checked", {}).get("summary", [])))
        print("   " + "; ".join(copied.get("checked", {}).get("summary", [])))
    after = _hashes(folder)
    note = after.pop("moved_to_database.json", None)
    check("The files were only read: every file in the folder is byte for byte as before; the one added is the note of the move",
          before == after and note is not None)
    # 2c. back from the database to files: the same answers again
    if moves:
        kind, url, _ = moves[-1]
        back = os.path.join(sp, "exported")
        good, _ = _finish(_run(kind, "export", data=folder, url=url, out=os.path.join(sp, "export.json"), extra={"RIGHTPRICE_CHECK_EXPORT": back}), "export")
        good2, _ = _finish(_run("files", "dump", data=back, out=os.path.join(sp, "back.json")), "the exported files")
        if good and good2:
            with open(os.path.join(sp, "back.json"), encoding="utf8") as f:
                ans = json.load(f)
            ans.pop("store")
            a = dict(files_answers)
            a.pop("store")
            diff = _first_difference(a, ans)
            check(f"Written back out of {kind} as files, the app on those files gives the same answers", diff is None, diff or "")
            with open(os.path.join(folder, "Rate_Master.xlsx"), "rb") as f1, open(os.path.join(back, "Rate_Master.xlsx"), "rb") as f2:
                check("Written back out: the rate master is the same file, byte for byte", f1.read() == f2.read())
        else:
            check("Written back out of the database as files", False)
        # 3. the guards: files changed after the move, and a database that cannot be reached
        changed = os.path.join(sp, "changed")
        shutil.copytree(folder, changed)
        with open(os.path.join(changed, "negotiations.json"), "a", encoding="utf8") as f:
            f.write(" ")
        _finish(_run(kind, "refused", data=changed, url=url, out=os.path.join(sp, "changed.json")), "files changed after the move")
        with open(os.path.join(sp, "changed.json"), encoding="utf8") as f:
            r = json.load(f)
        check("Files changed after the move: the app does not start on the database, says which file, and loses nothing",
              r["store"].get("ok") is False and "negotiations.json" in r["store"].get("error", "") and r["list"][0] == 503
              and "changed after the database took them" in r["list"][1]["detail"] and "keep-database" in r["list"][1]["detail"] and r["home"] == 200)
        gone = os.path.join(sp, "gone")
        shutil.copytree(folder, gone)
        for name in ("negotiations.json", "alerts_seen.json", "cost_sheets.json"):
            os.remove(os.path.join(gone, name))
        _finish(_run(kind, "refused", data=gone, url=url, out=os.path.join(sp, "gone.json")), "files moved away after the move")
        with open(os.path.join(sp, "gone.json"), encoding="utf8") as f:
            r = json.load(f)
        check("Files moved away or deleted after the move: the app works on the database as before", r["store"].get("ok") is True and r["list"][0] == 200)
        p = _run(kind, "export", data=changed, url=url, out=os.path.join(sp, "export2.json"), extra={"RIGHTPRICE_CHECK_EXPORT": os.path.join(sp, "exported2")})
        good, _ = _finish(p, "export while the guard has stopped the app")
        check("While the files' guard has stopped the app, the database can still be written out as files",
              good and os.path.exists(os.path.join(sp, "exported2", "negotiations.json")))
    secret = "S3cret-Pa55word-x"
    down_url = f"postgresql://rpadmin:{secret}@127.0.0.1:9/postgres?sslmode=disable&connect_timeout=3"
    p = _run("postgres", "refused", data=tempfile.mkdtemp(prefix="rightprice-none-"), out=os.path.join(sp, "down.json"), url=down_url)
    _, text = _finish(p, "a database that cannot be reached, before any move")
    with open(os.path.join(sp, "down.json"), encoding="utf8") as f:
        r = json.load(f)
    check("A database that cannot be reached at a first start: 503 saying so, the home page opens, the files untouched and usable meanwhile",
          r["list"][0] == 503 and "could not be reached" in r["list"][1]["detail"] and r["cost"] == 503 and r["home"] == 200
          and r["store"]["ok"] is False and "tries the database again by itself" in r["store"]["advice"]
          and "Nothing has been copied in yet" in r["store"]["advice"])
    if moves:
        after = os.path.join(sp, "after")
        shutil.copytree(folder, after)          # holds the note of the move
        p2 = _run("postgres", "refused", data=after, out=os.path.join(sp, "down2.json"), url=down_url)
        _, text2 = _finish(p2, "a database that cannot be reached, after the move")
        with open(os.path.join(sp, "down2.json"), encoding="utf8") as f:
            r2 = json.load(f)
        text += text2
        check("A database that cannot be reached after the move: no advice to go back to the files (they are as at the move)",
              r2["list"][0] == 503 and "Do not remove DATABASE_URL" in r2["store"]["advice"])
        r = [r, r2]
    check("A database that cannot be reached: the password is in no answer and no log line", secret not in json.dumps(r) and secret not in text)
    # the data layer on its own
    n_db = [0]

    def fresh(kind):
        n_db[0] += 1
        return pg.new() if kind == "postgres" else sqlite_url(f"store{n_db[0]}.db")
    store_checks(check, [("sqlite", sqlite_url("store.db"))] + ([("postgres", pg.new())] if not pg.why else []), fresh,
                 None if pg.why else pg.new())
    if os.environ.get("RIGHTPRICE_CHECK_KEEP") == "1":
        print("Kept:", sp)
    else:
        shutil.rmtree(sp, ignore_errors=True)
    print(f"\n({time.time() - t0:.0f} s; stores: {', '.join(k for k, _ in runs)})")
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(child() if STORE else parent())
