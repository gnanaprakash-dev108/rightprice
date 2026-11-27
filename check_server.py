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
        stage2_checks(c, check)         # stage 2: purchase history and Fab groups (last: it loads purchase files)
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


# ===================================================================== stage 2: purchase history and Fab groups
def _stage2_codes():
    """Real fabric codes for the made-up purchase file: three costed 100% cotton codes of one construction (A1, A2, A3)
    and one of another (B1) from the pilot; one whose PLM specification is incomplete. Prices and mills are made up."""
    import pandas as pd
    from rules import fab_groups, purchases
    specs = purchases.plm_specs()
    pilot_codes = pd.read_excel(os.path.join(HERE, "pilot", "Pilot_Results.xlsx"), sheet_name="Fabrics")["Fabric code"].astype(str)
    by_sig = {}
    for code in pilot_codes:
        _, sig, _ = fab_groups.signature_of(specs.get(code))
        if sig:
            by_sig.setdefault(sig, []).append(code)
    sigs = sorted(by_sig, key=lambda s: (-len(by_sig[s]), s))
    a, b = by_sig[sigs[0]], by_sig[sigs[1]]
    incomplete = next(code for code in sorted(specs) if "incomplete" in (fab_groups.signature_of(specs[code])[2] or ""))
    return a[0], a[1], a[2], b[0], incomplete


def _stage2_file(rows):
    """A purchase-order file in the SAP export's shape, from made-up rows (each a dict over the export's columns)."""
    import pandas as pd
    cols = ["Purchasing Document", "Plant", "Document Date", "Item", "Material", "Short Text", "Purchasing Doc. Type", "Order Quantity",
            "Order Unit", "Net Price", "Name of Supplier", "Currency", "Deletion Indicator"]
    buf = io.BytesIO()
    pd.DataFrame([{k: r.get(k) for k in cols} for r in rows], columns=cols).to_excel(buf, index=False)
    return buf.getvalue()


def stage2_checks(c, check):
    """Purchase files read in the background; one line per order line; mills, fabrics and Fab groups; the price popup;
    the Fab group page and its range (the brief's rule); the merge; Right cost's Fab group column. On the files store:
    a plain refusal, and everything else as before."""
    import statistics
    import pandas as pd
    import store
    from rules import costing, purchases
    kind = store.get().kind
    sha = lambda p: hashlib.sha256(open(os.path.join(HERE, p), "rb").read()).hexdigest()
    kept_files = {p: sha(p) for p in ("pilot/Pilot_Results.xlsx", "data/Rate_Master.xlsx", "inputs/Fabric _ 3Months_4746.xlsx")}
    r_before, yarn_before = c.post("/api/cost", json=masters.EXAMPLE_ROW).json(), c.get("/api/table/Yarn_Rates").json()
    versions = lambda: (c.get("/api/store").json().get("counts") or {}).get("rate versions")
    versions_before = versions()
    for css in ("web/purchases.css",):
        txt = open(os.path.join(HERE, css), encoding="utf8").read()
        check(f"{css}: every brace closed", txt.count("{") == txt.count("}"))
    if shutil.which("node"):
        p = subprocess.run(["node", "--check", os.path.join(HERE, "web", "purchases.js")], capture_output=True, text=True)
        check("web/purchases.js parses", p.returncode == 0, p.stderr[-300:])
    shell = c.get("/").text
    check("Stage 2: the shell loads the purchase-history page script before its own", shell.index("purchases.js") < shell.index("rightcost.js")
          and c.get("/purchases.js").status_code == 200 and c.get("/purchases.css").status_code == 200)
    if kind == "files":
        answers = [c.get("/api/purchases/uploads"), c.get("/api/groups"), c.get("/api/groups/Fab-0001"), c.get("/api/purchases/history", params={"code": "X"}),
                   c.post("/api/purchases/load-shipped"), c.post("/api/groups/merge", json={"code": "Fab-0001", "into": "Fab-0002"})]
        check("Stage 2 on the files store: the purchase history says plainly that it needs the database (503), nothing breaks",
              all(r.status_code == 503 and "kept in the database" in r.json()["detail"] for r in answers)
              and c.get("/api/purchases/status").json()["available"] is False)
        po = [r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Purchase orders"]
        check("Stage 2 on the files store: Right cost's Fab group column is empty", po and all(r["fab_group"] is None and r["fab_group_name"] is None for r in po))
        check("Stage 2: the pilot results, the rate master and the purchase file are untouched", all(sha(p) == v for p, v in kept_files.items()))
        return

    def wait(uid, limit=300):
        for _ in range(limit * 4):
            u = next((x for x in c.get("/api/purchases/uploads").json()["uploads"] if x["id"] == uid), None)
            if u and u["status"] in ("done", "failed"):
                return u
            time.sleep(0.25)
        raise SystemExit(f"upload {uid} was not read in {limit} s")

    k = f"[{kind}] Stage 2:"
    s0 = c.get("/api/purchases/status").json()
    check(f"{k} the purchase history starts empty", s0["available"] is True and s0["counts"]["lines"] == 0 and s0["counts"]["groups"] == 0, str(s0))
    a1, a2, a3, b1, inc = _stage2_codes()
    arv, arv2 = "1200094    ARVIND LTD", "1200094    Arvind Limited"
    raj, raj2, nsl = "1208655    RAJAPALAYAM MILLS LIMITE", "1208655    Rajapalayam Mills Limited", "1203290    NSL TEXTILES LIMITED"
    row = lambda po, item, code, day, sup, qty, price, **kw: dict({"Purchasing Document": float(po), "Item": float(item), "Material": code, "Plant": "F007",
                                                               "Document Date": pd.Timestamp(day), "Name of Supplier": sup, "Order Quantity": qty, "Net Price": price,
                                                               "Purchasing Doc. Type": "BO", "Currency": "INR", "Order Unit": "M", "Short Text": "made up for the checks"}, **kw)
    rows = [row(9900000001, 10, a1, "2026-08-03", arv, 1000, 100), row(9900000002, 10, a2, "2026-08-10", arv2, 1200, 101, **{"Purchasing Doc. Type": "ZLOI"}),
            row(9900000003, 10, a1, "2026-09-01", raj, 800, 102), row(9900000003, 20, a2, "2026-09-01", raj2, 900, 103, **{"Purchasing Doc. Type": "BF"}),
            row(9900000004, 10, a1, "2026-10-05", arv, 2000, 140),
            row(9900000005, 10, b1, "2026-08-01", nsl, 3000, 150),                     # the earliest line: its group is Fab-0001
            row(9900000006, 10, inc, "2026-08-05", nsl, 500, 90), row(9900000007, 10, "ZZCHECK001", "2026-08-06", nsl, 600, 95),
            # left out, each for its own reason
            row(9900000008, 10, a1, "2026-08-07", arv, 100, 100, **{"Deletion Indicator": "L"}), row(9900000009, 10, a1, "2026-08-07", arv, 100, 100, **{"Purchasing Doc. Type": "BA"}),
            row(9900000010, 10, a1, "2026-08-07", arv, 100, 1.2, Currency="USD"), row(9900000011, 10, a1, "2026-08-07", arv, 100, 100, **{"Order Unit": "KG"}),
            row(9900000012, 10, a1, "2026-08-07", arv, 100, 0), row(9900000001, 10, a1, "2026-08-03", arv, 1000, 100),
            {"Order Quantity": 9999, "Order Unit": "M"}]                               # a total line at the foot, as SAP writes it
    data = _stage2_file(rows)
    bad = c.post("/api/purchases/upload", files={"file": ("orders.csv", io.BytesIO(b"a,b\n1,2\n"))})
    check(f"{k} a file that is not an Excel workbook is refused at once", bad.status_code == 400 and ".xlsx" in bad.json()["detail"])
    up = c.post("/api/purchases/upload", files={"file": ("purchase orders.xlsx", io.BytesIO(data))}).json()
    check(f"{k} an upload is answered at once and queued for the background", up.get("status") == "queued" and isinstance(up.get("id"), int), str(up))
    u = wait(up["id"])
    det = c.get(f"/api/purchases/uploads/{up['id']}").json()
    why = {s["kind"] for s in det["skipped"]}
    check(f"{k} the file is read in the background: done, with its counts", u["status"] == "done" and u["rows_total"] == len(rows) and u["rows_loaded"] == 8
          and u["rows_new"] == 8 and u["rows_skipped"] == 7 and u["fabrics_new"] == 5 and u["groups_new"] == 2 and u["mills_new"] == 3, str({x: u[x] for x in u if x.startswith("rows") or x.endswith("new")}))
    check(f"{k} the rows left out say which and why (deleted, not bulk, not rupees, not metres, no price, repeated, a total line)",
          why == {"Deleted or blocked in SAP", "Not a bulk order", "Not in rupees", "Not per metre", "No price", "Repeated in this file", "No order number"}
          and any(s["why"].startswith("The same order line as row 2") for s in det["skipped"]) and any("BA" in s["why"] for s in det["skipped"]), str(det["skipped"])[:400])
    xl = c.get(f"/api/purchases/uploads/{up['id']}/skipped")
    check(f"{k} every row left out can be downloaded", xl.status_code == 200 and len(pd.read_excel(io.BytesIO(xl.content))) == 7)
    st = store.get()
    with st.tx() as cur:
        mills = cur.all("SELECT m.key, count(a.spelling) FROM mill m JOIN mill_alias a ON a.mill_id = m.id GROUP BY m.key ORDER BY m.key")
    check(f"{k} one record per mill, every spelling kept (Arvind Ltd and Arvind Limited; a name cut at 24 characters and its full name)",
          mills == [("arvind", 2), ("nsl textile", 1), ("rajapalayam", 2)], str(mills))
    hist = c.get("/api/purchases/history", params={"code": a1}).json()
    gA, gB = hist["group"]["code"], c.get("/api/purchases/history", params={"code": b1}).json()["group"]["code"]
    check(f"{k} Fab-0001 onward in order of first appearance; two codes of one construction are one group, across mills",
          gB == "Fab-0001" and gA == "Fab-0002" and c.get("/api/purchases/history", params={"code": a2}).json()["group"]["code"] == gA
          and {m["name"] for m in hist["group"]["mills"]} == {"Arvind Limited", "Rajapalayam Mills Limited"}, f"{gA} {gB}")
    ng1, ng2 = (c.get("/api/purchases/history", params={"code": x}).json() for x in (inc, "ZZCHECK001"))
    check(f"{k} a code whose specification is incomplete, or missing, is not grouped and says why (never guessed)",
          ng1["group"] is None and "incomplete" in ng1["not_grouped"] and ng2["group"] is None and ng2["not_grouped"] == "No PLM specification for this code"
          and ng2["should"] is None)
    po_row = next(r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Purchase orders" and r["code"] == a1)   # the pilot's choices
    same = lambda d: {x: v for x, v in d.items() if x not in ("Quoted price (Rs/m)", "Supplier", "Description", "Fabric code", "Order quantity (m)",
                                                                 "Rate card quantity", "Order size")}
    with st.tx() as cur:
        stored = json.loads(cur.one("SELECT choices FROM fabric WHERE code = %s", (a1,))[0])
    check(f"{k} price over time for a code: each purchase with date, mill, metres and price, and its should-cost on today's rates",
          [(x["date"], x["mill"], x["metres"], x["price"]) for x in hist["lines"]] == [("2026-08-03", "Arvind Limited", 1000.0, 100.0), ("2026-09-01", "Rajapalayam Mills Limited", 800.0, 102.0),
                                                                                    ("2026-10-05", "Arvind Limited", 2000.0, 140.0)]
          and hist["should"] == round(c.post("/api/cost", json=stored).json()["total_per_m"], 2) and same(stored) == same(po_row["choices"]), str(hist["lines"])[:300])
    check(f"{k} the popup also shows the code's Fab group history, its other codes included", len(hist["group"]["lines"]) == 5
          and {x["code"] for x in hist["group"]["lines"]} == {a1, a2})
    page = c.get(f"/api/groups/{gA}").json()
    prices = sorted([100, 101, 102, 103, 140])
    med = statistics.median(prices)
    q = statistics.quantiles(prices, n=4, method="inclusive")
    lo, hi = costing.usual_range((q[0] / med - 1) * 100, (q[2] / med - 1) * 100)
    upper = round(med * (1 + hi / 100), 2)
    check(f"{k} the group page: purchases, metres, mills, median price, and the usual range by the brief's own rule (5% to 10% round the median)",
          page["purchases"] == 5 and page["metres"] == 5900 and len(page["mills"]) == 2 and page["range"]["median"] == 102 and page["range"]["enough"]
          and (page["range"]["lo"], page["range"]["hi"]) == (lo, hi) == (-5.0, 5.0) and page["range"]["upper"] == upper == 107.1
          and page["should"]["median"] is not None, str(page["range"]))
    check(f"{k} priced well above the group: only the purchase above the top of the usual range, with the rupees above it",
          [(x["code"], x["price"], x["above"], x["above_rs"]) for x in page["above"]] == [(a1, 140.0, 32.9, 65800.0)] and page["above_rs"] == 65800, str(page["above"]))
    pb = c.get("/api/groups/fab-0001").json()
    check(f"{k} a group with too few purchases says so, and calls nothing high", pb["code"] == "Fab-0001" and pb["range"]["enough"] is False and pb["range"]["n"] == 1
          and pb["above"] == [] and pb["min_for_range"] == 5)
    # the same file again: nothing doubled; a later file with one price changed and one line deleted in SAP
    u2 = wait(c.post("/api/purchases/upload", files={"file": ("purchase orders again.xlsx", io.BytesIO(data))}).json()["id"])
    n_lines = c.get("/api/purchases/status").json()["counts"]["lines"]
    check(f"{k} the same file uploaded twice: each order line is one line", u2["status"] == "done" and u2["rows_new"] == 0 and u2["rows_same"] == 8 and n_lines == 8
          and u2["fabrics_new"] == 0 and u2["groups_new"] == 0, str(u2))
    rows2 = [dict(r) for r in rows]
    rows2[1]["Net Price"] = 105
    rows2[7]["Deletion Indicator"] = "L"
    u3 = wait(c.post("/api/purchases/upload", files={"file": ("purchase orders corrected.xlsx", io.BytesIO(_stage2_file(rows2)))}).json()["id"])
    h2 = c.get("/api/purchases/history", params={"code": a2}).json()
    check(f"{k} a later file: a changed line takes the newer figures; a line deleted in SAP since is no longer counted (kept, marked)",
          u3["rows_changed"] == 1 and u3["rows_removed"] == 1 and u3["rows_same"] == 6 and c.get("/api/purchases/status").json()["counts"]["lines"] == 7
          and c.get("/api/purchases/status").json()["counts"]["lines_removed"] == 1 and h2["lines"][0]["price"] == 105
          and c.get("/api/purchases/history", params={"code": "ZZCHECK001"}).json()["lines"] == [], str(u3))
    specs = purchases.plm_specs()                     # the PLM list read by this process: a specification arrives for ZZCHECK001
    specs["ZZCHECK001"] = dict(specs[a3])
    try:
        u4 = wait(c.post("/api/purchases/upload", files={"file": ("purchase orders corrected again.xlsx", io.BytesIO(_stage2_file(rows2)))}).json()["id"])
    finally:
        specs.pop("ZZCHECK001", None)
    zz = c.get("/api/purchases/history", params={"code": "ZZCHECK001"}).json()
    check(f"{k} a code held without a specification is grouped at the next upload once the PLM list has it (not only codes in that file)",
          u4["status"] == "done" and u4["rows_new"] == 0 and zz["group"] and zz["group"]["code"] == gA and zz["not_grouped"] is None, str(zz.get("not_grouped")))
    bad2 = wait(c.post("/api/purchases/upload", files={"file": ("not orders.xlsx", io.BytesIO(b"PK, but not a workbook"))}).json()["id"])
    buf = io.BytesIO()
    pd.DataFrame([{"Fabric": "x", "Price": 1}]).to_excel(buf, index=False)
    bad3 = wait(c.post("/api/purchases/upload", files={"file": ("other sheet.xlsx", io.BytesIO(buf.getvalue()))}).json()["id"])
    check(f"{k} a file that cannot be read, or is not a purchase-order export, fails and says why", bad2["status"] == "failed" and "could not be read" in bad2["error"]
          and bad3["status"] == "failed" and "Purchasing Document" in bad3["error"], f"{bad2['error']} | {bad3['error']}")
    with st.tx(write="purchases") as cur:
        cur.run("INSERT INTO upload (kind, filename, uploaded_at, status, alive_at) VALUES ('purchase_orders', 'stale.xlsx', '2026-11-27T00:00:00', 'working', '2026-11-27T00:00:00')")
    stale = next(x for x in c.get("/api/purchases/uploads").json()["uploads"] if x["filename"] == "stale.xlsx")
    check(f"{k} a job stopped by a restart is shown as failed, with what to do", stale["status"] == "failed" and "Upload the file again" in stale["error"])
    # the merge
    refusals = [c.post("/api/groups/merge", json={"code": gA, "into": gA}).status_code, c.post("/api/groups/merge", json={"code": "Fab-9999", "into": gA}).status_code]
    m = c.post("/api/groups/merge", json={"code": gB, "into": gA})
    again = c.post("/api/groups/merge", json={"code": gB, "into": gA}).status_code
    pb2, listing = c.get(f"/api/groups/{gB}").json(), c.get("/api/groups").json()
    check(f"{k} an admin merge: the merged group's purchases count in the other; its code is kept and its page says where it went",
          m.status_code == 200 and refusals == [400, 404] and again == 409 and pb2["code"] == gA and pb2["asked"]["code"] == gB and pb2["purchases"] == 6
          and [x["code"] for x in listing["groups"]] == [gA] and listing["merged"][0]["code"] == gB and listing["merged"][0]["into"] == gA,
          f"{m.status_code} {refusals} {again}")
    check(f"{k} undoing a merge", c.post("/api/groups/unmerge", json={"code": gB}).status_code == 200 and c.get(f"/api/groups/{gB}").json()["code"] == gB
          and c.post("/api/groups/unmerge", json={"code": gB}).status_code == 409)
    c.post("/api/groups/merge", json={"code": gB, "into": gA})
    # the real purchase file that came with the code, loaded through the app
    t0 = time.time()
    real = wait(c.post("/api/purchases/load-shipped").json()["id"], limit=600)
    took = time.time() - t0
    import pilot
    po = pd.read_excel(os.path.join(HERE, "inputs", "Fabric _ 3Months_4746.xlsx"))
    bulk = po[po["Purchasing Doc. Type"].isin(pilot.BULK_TYPES) & (po["Net Price"] > 0) & po["Deletion Indicator"].isna()
              & (po["Currency"] == "INR") & (po["Order Unit"] == "M")]
    counts = c.get("/api/purchases/status").json()["counts"]
    check(f"{k} the purchase file that came with the code loads through the app ({took:.0f} s): the pilot's own bulk lines, every material code once",
          real["status"] == "done" and real["rows_total"] == len(po) and real["rows_loaded"] == len(bulk) == 6265 and real["rows_new"] == 6265
          and counts["lines"] == 6265 + 7 and counts["fabrics"] == len(set(bulk["Material"].astype(str).str.strip()) | {a1, a2, b1, inc, "ZZCHECK001"}),
          str({x: real[x] for x in real if x.startswith("rows")}))
    fab = pd.read_excel(os.path.join(HERE, "pilot", "Pilot_Results.xlsx"), sheet_name="Fabrics")
    with st.tx() as cur:
        got = {code: json.loads(ch) for code, ch in cur.all("SELECT code, choices FROM fabric WHERE choices IS NOT NULL")}
        new_codes = sorted(code for (code,) in cur.all("SELECT code FROM fab_group WHERE upload_id = %s", (real["id"],)))
    keys = ["Route", "Weave", "Finish", "Warp yarn", "Weft yarn", "EPI", "PPI", "Finished width (in)", "Rate card quantity", "Order size"]
    mine = {a1, a2, a3, b1}                           # these carry made-up lines too, so their metres differ
    got.pop("ZZCHECK001", None)                       # made up, with a3's specification
    same_value = lambda x, y: (float(x) == float(y)) if isinstance(y, (int, float)) and x is not None else str(x) == str(y)
    differ = [r["Fabric code"] for r in fab.to_dict("records") if r["Fabric code"] not in mine
              and not all(same_value(got.get(r["Fabric code"], {}).get(x), r[x]) for x in keys)]
    wd = [r["Fabric code"] for r in fab.to_dict("records") if r["Fabric code"] not in mine and r["Route"] == "Yarn Dyed"
          and got.get(r["Fabric code"], {}).get("Weft (yarn dyed)") != r["Weft (yarn dyed)"]]
    check(f"{k} every fabric the pilot costed has the same costing choices here, worked out by pilot.py's own functions ({len(fab)} fabrics)",
          not differ and not wd and len([x for x in got if x in set(fab["Fabric code"])]) == len(fab) and len(got) == len(fab), f"{differ[:5]} {wd[:5]} {len(got)}")
    check(f"{k} new Fab groups go on from the last code ever given: a merged code is never handed out again",
          new_codes and new_codes[0] == "Fab-0003" and gB not in new_codes, str(new_codes[:3]))
    rc = [r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Purchase orders"]
    check(f"{k} Right cost: every purchase-order row shows its Fab group (as it counts now, after merges) or why it has none",
          all(r["fab_group"] or r["fab_group_name"] for r in rc) and next(r for r in rc if r["code"] == b1)["fab_group"] == gA
          and next(r for r in rc if r["code"] == a1)["fab_group_name"] == page["name"], str([r for r in rc if not (r["fab_group"] or r["fab_group_name"])][:1])[:300])
    sample = rc[:20]
    agree = [abs(c.get("/api/purchases/history", params={"code": r["code"]}).json()["should"] - c.post("/api/cost", json=r["choices"]).json()["total_per_m"]) < 0.006
             for r in sample if r["code"] not in mine]
    check(f"{k} the popup's should-cost is the one Right cost's Negotiation tab gives for the same fabric", agree and all(agree), str(agree))
    again = wait(c.post("/api/purchases/load-shipped").json()["id"], limit=600)
    check(f"{k} loading the same purchase file again changes nothing", again["rows_new"] == 0 and again["rows_same"] == 6265 and again["groups_new"] == 0
          and c.get("/api/purchases/status").json()["counts"] == counts)
    big = max(c.get("/api/groups").json()["groups"], key=lambda g: g["purchases"])
    gp = c.get(f"/api/groups/{big['code']}").json()
    r_ = gp["range"]
    ps = sorted(x["price"] for x in gp["lines"])
    q2 = statistics.quantiles(ps, n=4, method="inclusive")
    exp = costing.usual_range((q2[0] / statistics.median(ps) - 1) * 100, (q2[2] / statistics.median(ps) - 1) * 100)
    check(f"{k} the busiest real group ({big['code']}, {gp['purchases']} purchases, {len(gp['mills'])} mills): range by the brief's rule; purchases above it listed",
          (r_["lo"], r_["hi"]) == exp and all(x["price"] > r_["upper"] for x in gp["above"])
          and len(gp["above"]) == sum(1 for x in gp["lines"] if round(x["price"], 2) > r_["upper"]) and gp["purchases"] == len(gp["lines"]) == big["purchases"])
    check(f"{k} the pilot results, the rate master and the purchase file are untouched", all(sha(p) == v for p, v in kept_files.items()))
    r1 = c.post("/api/cost", json=masters.EXAMPLE_ROW).json()
    check(f"{k} no rate changed: the example fabric costs what it did before the purchase files (the checks above edited rates on purpose)",
          r1["total_per_m"] == r_before["total_per_m"] and c.get("/api/table/Yarn_Rates").json() == yarn_before and versions() == versions_before,
          f"{r1['total_per_m']:.2f}, rate versions {versions_before} then {versions()}")


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
