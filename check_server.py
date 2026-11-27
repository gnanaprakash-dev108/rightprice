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
    os.environ.pop("RIGHTPRICE_ADMINS", None)       # permissions off: every check runs as before; access_checks() switches them on
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
        check("MCP: the health check answers a caller holding the token", hl["ok"] is True and hl["tools"] == len(server.mcp_server.MIRRORS) >= 10)
        rpc = lambda method, params, i=1: c.post("/mcp", headers=hd, json={"jsonrpc": "2.0", "id": i, "method": method, "params": params}).json()
        call = lambda name, **args: json.loads(rpc("tools/call", {"name": name, "arguments": args})["result"]["content"][0]["text"])
        listed_t = rpc("tools/list", {})["result"]["tools"]
        names = [t["name"] for t in listed_t]
        writers = {t["name"] for t in listed_t if not (t.get("annotations") or {}).get("readOnlyHint")}
        # since GP's decision of 27 Nov 2026 the token is an admin key with more tools: assistant_checks() checks those
        check("MCP: the ten first tools are offered among the others; the two of them that write are marked as writing, the eight others are not",
              {"list_choices", "cost_fabric", "find_fabrics", "fabric_brief", "supplier_summary", "negotiation_pack", "tracker_steps",
               "record_tracker_step", "remove_my_tracker_step", "quote_alerts"} <= set(names) == set(server.mcp_server.MIRRORS)
              and writers & {"list_choices", "cost_fabric", "find_fabrics", "fabric_brief", "supplier_summary", "negotiation_pack", "tracker_steps",
                             "record_tracker_step", "remove_my_tracker_step", "quote_alerts"} == {"record_tracker_step", "remove_my_tracker_step"}, str(writers))
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
        check("MCP: with a counter recorded the brief says not to open above it; a person's step is not removed by remove_my_tracker_step (remove_tracker_step does that, as an admin can)",
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
    from rules import rates as rates_rules
    pics = [c.post("/api/intake/file", files={"file": (n, io.BytesIO(b"\x89PNG"))}).json() for n in
            ("WhatsApp Image 2026-11-27 at 10.15.32.png", "Screenshot_2026-11-27-10-15-32.png", "IMG-20261127-WA0001.jpg")]
    month_words = rates_rules._decide(("Yarn rates Oct 2026 (sent 03.11.2026).pdf", "the file name"))
    letterhead = rates_rules._decide(("price list.pdf", "the file name"), ("Estd. dated 01-04-2019 ... rates as on 21.10.2026", "the document's text"))
    old_only = rates_rules._decide(("rates 01-04-2019.pdf", "the file name"))
    check("Bring in prices: a phone's or a screen's file name is not the document's date; a month in words wins over a sent date; dates "
          "more than a year apart, or a lone old one, are shown and the month is asked",
          all(p["date_read"] is False and p["dates_found"] == [] and "Dated" not in p["note"] for p in pics)
          and month_words["sure"] and month_words["month"] == "2026-10" and not letterhead["sure"] and letterhead["month"] == "2019-04"
          and letterhead["suggest"] == "2026-10" and len(letterhead["found"]) == 2 and not old_only["sure"], f"{month_words} {letterhead}")
    t = c.post("/api/intake/file", files={"file": ("list.csv", io.BytesIO(b"Date,Yarn,Count,Rate\n15/09/2026,Combed,60s,420\n,Combed,60s,424\n03.10.2026,Combed,60s,430\n"))}).json()
    st = c.post("/api/intake/map", json={"token": t["token"], "sheet": next(iter(t["sheets"])), "count": "Count", "low": "Rate", "yarn": "Yarn", "date": "Date"}).json()
    xl = io.BytesIO()
    pd.DataFrame({"Date": [pd.Timestamp("2026-09-15"), None], "Count": ["60s", "60s"], "Rate": [420, 424]}).to_excel(xl, index=False)
    tx = c.post("/api/intake/file", files={"file": ("list.xlsx", io.BytesIO(xl.getvalue()))}).json()
    sx = c.post("/api/intake/map", json={"token": tx["token"], "sheet": next(iter(tx["sheets"])), "count": "Count", "low": "Rate", "date": "Date"}).json()
    check("Bring in prices: a date column is read day first (15/09/2026, 03.10.2026) and as real Excel dates; a blank cell is left blank, and said",
          [r[0] for r in st["rows"]] == ["2026-09-15", None, "2026-10-03"] and st["date_read"] and "1 row has none" in st["note"]
          and [r[0] for r in sx["rows"]] == ["2026-09-15", None], str(st)[:300] + str(sx)[:200])
    check("Dated rates: a purchase order whose code is not in the purchase file says so, not that the file is missing",
          "is not in the purchase file" in dated_rules.po_rates("NOT-A-CODE", months, {"rates_of": {}})["note"])
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
    # from Bring in prices: the month of each row decided by the server from what it read of the document (its read
    # token), never today's and never a flag the page sends; GST said row by row; a rate with GST never replaces one without
    add_dated = lambda **b: c.post("/api/intake/add-dated", json=b)
    today_ = _dt.date.today().isoformat()
    flag = add_dated(rows=[[today_, "Combed", "40s", 350, 360, "", "Cotton 40S", False]], dates_read=True, date_from="the file name")
    prev = add_dated(rows=[[today_, "Combed", "40s", 350, 360, "", "Cotton 40S", False]], dates_read=True, preview=True).json()
    chk("Dated rates from Bring in prices: a row dated today with no document read is not taken as today's month, whatever the page says it read",
        flag.status_code == 400 and "choose the month" in flag.json()["detail"] and prev["need_month"][0]["row"] == 1, flag.text[:200])
    chk("Dated rates from Bring in prices: each row must say whether its price includes GST",
        "Row 1: say whether its price includes GST" in add_dated(rows=[[today_, "Combed", "40s", 350, 360, "", "Cotton 40S"]], month="2026-07").json()["detail"])
    ta = c.post("/api/intake/file", files={"file": ("circular 21.10.2026.csv", io.BytesIO(b"Count,Yarn,Rate\n40s,Combed compact,355\n"))}).json()
    sa = c.post("/api/intake/map", json={"token": ta["token"], "sheet": next(iter(ta["sheets"])), "count": "Count", "low": "Rate", "yarn": "Yarn"}).json()
    rows_a = [["2026-10-21", "Combed compact", "40s", 350, 360, "x", "Cotton 40S", False], [today_, "Combed compact", "40s", 364, None, "x", "Cotton 40S", False],
              ["2026-10-21", "Combed compact", "50s", 400, 410, "x", "", False]]
    pa = add_dated(rows=rows_a, read_token=sa["read_token"], source="circular 21.10.2026.csv", preview=True).json()
    ga = add_dated(rows=rows_a, read_token=sa["read_token"], source="circular 21.10.2026.csv").json()
    chk("Dated rates from Bring in prices: on a document dated 21.10.2026 a row typed in with today's date takes the document's month; "
        "two prices of one yarn in a month are averaged; a row given no yarn is left out",
        [x["month"] for x in pa["plan"]] == ["2026-10", "2026-10"] and pa["need_month"] == [] and "the document's month" in pa["plan"][1]["how"]
        and ga.get("rates") == [{"yarn_key": "Cotton 40S", "month": "2026-10", "rate": 359.5, "entries": 2}] and ga["left_out"] == 1, str(pa) + str(ga))
    rows_b = [r[:6] + ["Cotton 60S", False] for r in st["rows"]]
    pb = add_dated(rows=rows_b, read_token=st["read_token"], preview=True).json()
    nb = add_dated(rows=rows_b, read_token=st["read_token"])
    gb = add_dated(rows=rows_b, read_token=st["read_token"], month_undated="2026-09").json()
    chk("Dated rates from Bring in prices: a date column read day first gives each row its month; a blank date is listed for the person, "
        "who chooses its month: it is not a refusal of every row, and not today's",
        [x["month"] for x in pb["plan"]] == ["2026-09", None, "2026-10"] and [x["row"] for x in pb["need_month"]] == [2]
        and nb.status_code == 400 and "Row 2" in nb.json()["detail"]
        and sorted((x["month"], x["rate"], x["entries"]) for x in gb["rates"]) == [("2026-09", 422, 2), ("2026-10", 430, 1)], str(pb) + str(gb))
    g60 = add_dated(rows=[["2026-10-21", "Combed", "60s", 441, None, "", "Cotton 60S", True]], read_token=sa["read_token"]).json()
    t60 = add(yarn_key="Cotton 60S", month="2026-10", rate=445, gst=True)
    e60 = next(e for e in c.get("/api/dated-rates").json()["entries"] if (e["yarn_key"], e["month"]) == ("Cotton 60S", "2026-10"))
    mix = add_dated(rows=[["2026-10-21", "Combed", "50s", 400, None, "", "Cotton 50S", False], ["2026-10-21", "Combed", "50s", 420, None, "", "Cotton 50S", True]],
                    read_token=sa["read_token"]).json()
    e50 = next(e for e in c.get("/api/dated-rates").json()["entries"] if (e["yarn_key"], e["month"]) == ("Cotton 50S", "2026-10"))
    chk("Dated rates: a rate with GST never takes the place of one without GST for the month (brought in or typed); in one import, "
        "prices with GST are left out where the month has one without",
        g60["added"] == 0 and g60["kept"][0]["yarn_key"] == "Cotton 60S" and t60.status_code == 409 and e60["rate"] == 430 and "includes GST" not in e60["basis"]
        and mix["rates"][0]["rate"] == 400 and "with GST left out" in e50["basis"], str(g60) + t60.text[:200] + e50["basis"])
    g7 = add_dated(rows=[["", "Combed", "40s", 350, 360, "", "Cotton 40S", True], ["", "Combed", "40s", 364, None, "", "Cotton 40S", True]], month="2026-07").json()
    e7 = next(e for e in c.get("/api/dated-rates").json()["entries"] if (e["yarn_key"], e["month"]) == ("Cotton 40S", "2026-07"))
    chk("Dated rates from Bring in prices: a month chosen for the document is every row's month, and prices with GST say so",
        g7["rates"] == [{"yarn_key": "Cotton 40S", "month": "2026-07", "rate": 359.5, "entries": 2}] and "includes GST" in e7["basis"] and "month chosen" in e7["basis"], str(g7))
    chk("Dated rates from Bring in prices: a yarn not in the master is refused with its row number",
        "Row 1" in add_dated(rows=[["2026-08-04", "x", "40s", 350, 360, "", "Cotton 41S", False]], month="2026-08").json()["detail"])
    active = {(e["yarn_key"], e["month"]) for e in c.get("/api/dated-rates").json()["entries"]}
    n_dated = sum(1 for r in po if (r["choices"]["Warp yarn"], r["rates"]["month"]) in active or (r["choices"]["Weft yarn"], r["rates"]["month"]) in active)
    chk("Dated rates: the dashboard works out how many orders are on a dated yarn rate itself (not from Right cost's memory)",
        f"Right cost costs {n_dated} of these orders on a dated yarn rate" in c.get("/api/insights").json()["pilot_rates"], f"{n_dated}")
    pg = c.get("/api/dated-rates").json()
    s40 = next(s for s in pg["series"] if s["key"] == "Cotton 40S")
    chk("Dated rates: the page's chart holds each yarn by month from the first dated month to this one, a month without a rate left empty",
        pg["months"][0] == "2026-06" and pg["months"][-1] == pg["this_month"] and len(s40["points"]) == len(pg["months"])
        and [p and p["rate"] for p in s40["points"]][:6] == [None, 359.5, None, None, 359.5, None] and data_dated.version() is not None)
    chk("Dated rates: the store counts them", c.get("/api/store").json()["counts"]["dated yarn rates"] == len(pg["entries"]))
    for e in pg["entries"]:         # leave the store as the rest of the suite found it
        c.post("/api/dated-rates/remove", json={"id": e["id"]})
    return good


# ===================================================================== stage 3: users, roles and permissions
def front_end_calls(routes):
    """Every address each page's own code calls, read from the front-end files: {permission of the page: {"METHOD /path"}}.
    web/app.js: each earlier screen (PAGES.<id>), with the functions it uses, and the drop-down lists the screens load
    first; web/rightcost.js: Right cost (the list, fabric and supplier pages, and the rail's alert count); web/access.js:
    Users and roles. Left out on purpose: the earlier front end's own header search (setupSearch), which the shell hides."""
    app_pages = {"dashboard": "page:dashboard", "pilot": "page:pilot", "cost": "page:cost", "compare": "page:cost", "bulk": "page:list",
                 "pack": "page:pack", "yarn": "page:prices", "cotton": "page:prices", "rates": "page:prices", "ratecard": "page:prices",
                 "settings": "page:prices", "costsheets": "page:costsheets", "intake": "do:edit_rates"}
    templates = sorted({k.split(" ", 1)[1] for k in routes if " /api/" in k}, key=len, reverse=True)

    def address(literal):
        for t in templates:
            if literal == t or ("{" in t and literal == t.split("{")[0]):
                return t
        return literal

    def calls(text):
        out = set()
        for m in re.finditer(r"""["'`](/api/[A-Za-z0-9_/-]*)""", text):
            before = text[max(0, m.start() - 40):m.start()]
            rest = re.split(r"[;\n]", text[m.end():m.end() + 200], maxsplit=1)[0]      # the rest of the call, on its line
            method = re.search(r"""method:\s*["'](\w+)["']""", rest)
            if re.search(r"getJSON\(\s*$", before):
                verb = "GET"
            elif re.search(r"(postJSON|download|uaChange|uaPost|send)\(\s*$", before):
                verb = "POST"
            else:
                verb = method.group(1).upper() if method else "GET"
            out.add(f"{verb} {address(m.group(1))}")
        return out

    def blocks(src):
        """The file's top-level definitions (function, const, PAGES.<id>, the start-up function) and their text."""
        pat = re.compile(r"^(?:async\s+)?function\s+(\w+)|^const\s+(\w+)\s*=|^PAGES\.(\w+)\s*=|^\(async function (\w+)\(", re.M)
        found = [(m.start(), m.group(1) or m.group(2) or ("PAGES." + m.group(3) if m.group(3) else None) or m.group(4)) for m in pat.finditer(src)]
        out = {}
        for i, (pos, name) in enumerate(found):
            out[name] = out.get(name, "") + src[pos:found[i + 1][0] if i + 1 < len(found) else len(src)]
        return out

    def reach(name, defs, skip):
        seen, todo = set(), [name]
        while todo:
            n = todo.pop()
            if n in seen or n in skip:
                continue
            seen.add(n)
            todo += [w for w in set(re.findall(r"\b(\w+)\b", defs[n])) if w in defs and w != n]
        return set().union(*(calls(defs[n]) for n in seen))

    read = lambda name: open(os.path.join(HERE, "web", name), encoding="utf8").read()
    app = blocks(read("app.js"))
    skip = {"setupSearch", "start", "route", "PAGES"}
    boot = calls(app["start"])                                 # what every earlier screen loads first
    per = {}
    for pid, perm in app_pages.items():
        per.setdefault(perm, set()).update(reach("PAGES." + pid, app, skip) | boot)
    per.setdefault("page:rightcost", set()).update(calls(read("rightcost.js")))
    per.setdefault("page:users", set()).update(calls(read("access.js")) - {"GET /api/me"})
    dj = read("dated.js")           # stage 5: the Yarn prices card (page:prices) and Bring in prices' dated step (do:edit_rates)
    cut = dj.index("async function fromIntake")
    per.setdefault("page:prices", set()).update(calls(dj[:cut]))
    per.setdefault("do:edit_rates", set()).update(calls(dj[cut:]))
    return per


def access_checks():
    """Users, roles and page-wise permissions (rules/access.py, server.py AccessGate) on this store: every address has a
    permission, and every address is tried with and without them; the switch (the app setting RIGHTPRICE_ADMINS) and how
    it is read; who the sign-in says is asking; every role against a sample of addresses, with the exact answer of each;
    one page unticked never breaking another; the AI assistant's tools going through the same permissions; the admin
    page's changes and their record; the last-admin rule; the shell served without the database; the files store."""
    import asyncio
    import base64
    import contextlib
    import http
    import store
    from fastapi.routing import APIRoute
    from starlette.websockets import WebSocketDisconnect
    from websockets.sync.server import serve
    import data_users
    from rules import access
    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    H = lambda e: {"X-MS-CLIENT-PRINCIPAL-NAME": e}
    P = lambda claims, **extra: {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(dict({"auth_typ": "aad", "claims": claims}, **extra)).encode()).decode()}
    gp, tag = H("gp@example.com"), f"[{STORE}] "
    for k in ("RIGHTPRICE_ADMINS", "WEBSITE_SITE_NAME", "WEBSITE_AUTH_ENABLED", "RIGHTPRICE_MCP_TOKEN"):
        os.environ.pop(k, None)

    # a stand-in for the earlier (Streamlit) screens: a plain answer to plain requests, an echo on the web socket
    def echo(ws):
        for msg in ws:
            ws.send(msg)
    stand_in = serve(echo, "127.0.0.1", 0, process_request=lambda conn, req: None if req.headers.get("Upgrade", "").lower() == "websocket"
                     else conn.respond(http.HTTPStatus.OK, "classic stand-in\n"))
    threading.Thread(target=stand_in.serve_forever, daemon=True).start()
    server.CLASSIC = f"127.0.0.1:{stand_in.socket.getsockname()[1]}"

    def socket_answer(email):
        """What the earlier screens' web socket gives this person: "echo" when it opens through to them, else the close code."""
        try:
            with c.websocket_connect("/classic/_stcore/stream", headers=H(email) if email else {}) as ws:
                ws.send_text("hello")
                return "echo" if ws.receive_text() == "hello" else "?"
        except WebSocketDisconnect as e:
            return e.code

    fill_in = {"{sheet}": "Settings", "{saved_id}": "x", "{path:path}": "x"}
    bodies = {"POST /api/bulk-download": {"columns": ["a"], "rows": []}}

    def sweep(headers):
        """Every address of the app (each method), asked once, as these headers: {address: status}."""
        out = {}
        for key in server.route_keys():
            method, path = key.split(" ", 1)
            if method in ("MOUNT", "WS"):
                continue
            for a, b in fill_in.items():
                path = path.replace(a, b)
            out[key] = c.request(method, path, json=bodies.get(key, {}) if method in ("POST", "PUT") else None, headers=headers).status_code
        return out

    with TestClient(server.app, raise_server_exceptions=False) as c:
        keys = server.route_keys()
        paths = {k.split(" ", 1)[1] for k in keys}
        check(tag + "Every address the app answers has a permission assigned (a later stage adds its own to rules/access.py ROUTES)",
              keys and all(v is not None for v in keys.values()), str([k for k, v in keys.items() if v is None]))
        known = lambda v: v in (access.PUBLIC, access.SHELL, access.MEMBER) or v in access.LABEL or (
            isinstance(v, tuple) and v and all(p in access.LABEL and p.startswith("page:") for p in v))
        stale = [k for k in access.ROUTES if (k[2:] not in paths if k.startswith("* ") else k not in keys)]
        check(tag + "The table names only permissions RightPrice knows, and no address the app does not answer (\"* /path\" entries included)",
              all(known(v) for v in access.ROUTES.values()) and not stale, str(stale))
        D, pages = access.DEFAULTS, {k for k in access.ALL if k.startswith("page:")} - {"page:users"}
        check(tag + "GP's roles: Admin everything; Rates editor edits rates and applies drafts, no user admin; Buyer every page, "
                    "uploads, steps and drafts, no rate edits; Viewer read only",
              D["Admin"] == set(access.ALL) and {"do:edit_rates", "do:apply_drafts"} <= D["Rates editor"] and "do:manage_users" not in D["Rates editor"]
              and pages <= D["Buyer"] and {"do:upload", "do:record_steps", "do:draft"} <= D["Buyer"] and not {"do:edit_rates", "do:apply_drafts", "do:manage_users"} & D["Buyer"]
              and D["Viewer"] == pages and all(not p.startswith("do:") for p in D["Viewer"]))
        broken = [f"{q} unticked breaks {p} ({a})" for role in ("Rates editor", "Buyer", "Viewer") for q in pages
                  for p in sorted(D[role] - {q}) if p in access.PAGE_USES for a in access.PAGE_USES[p] if not access.opens(access.ROUTES.get(a), D[role] - {q})]
        check(tag + "Each page opens every address it reads (access.PAGE_USES), so unticking any one page, for any role, leaves every other page working",
              not broken and all(a in access.ROUTES for uses in access.PAGE_USES.values() for a in uses) and set(access.PAGE_USES) >= pages, "; ".join(broken[:5]))
        called = front_end_calls(access.ROUTES)
        is_read = lambda a: access.ROUTES.get(a) == access.MEMBER or all(str(n).startswith("page:") for n in access._needs(access.ROUTES.get(a)))
        differs = {perm: (sorted(set(access.PAGE_USES.get(perm, [])) - {a for a in got if is_read(a)}), sorted({a for a in got if is_read(a)} - set(access.PAGE_USES.get(perm, []))))
                   for perm, got in called.items() if perm.startswith("page:")}
        unknown = sorted({a for got in called.values() for a in got if a not in access.ROUTES})
        # and no address opens for a page that does not read it: its pages are exactly the pages whose lists name it
        loose = {a: (sorted(access._needs(need)), sorted(users)) for a, need in access.ROUTES.items() if need not in (access.PUBLIC, access.SHELL, access.MEMBER)
                 and is_read(a) for users in [{perm for perm, uses in access.PAGE_USES.items() if a in uses}] if users and set(access._needs(need)) != users}
        check(tag + "access.PAGE_USES is what each page's code calls (read from web/app.js, rightcost.js and access.js), both ways; every "
                    "address the screens call is in ROUTES; an address read by pages opens for exactly those pages; Bring in prices "
                    "reads nothing beyond the drop-down lists",
              all(not a and not b for a, b in differs.values()) and set(called) >= pages | {"page:users"} and not unknown
              and {a for a in called["do:edit_rates"] if is_read(a)} == {"GET /api/meta"} and not loose,
              str({k: v for k, v in differs.items() if v[0] or v[1]}) + str(unknown) + str(loose))

        # the AI assistant: each tool goes through the permission of the address it mirrors
        if server.mcp_server is not None:
            tools = {t.name: t for t in asyncio.run(server.mcp_server.mcp.list_tools())}
            mirrors = server.mcp_server.MIRRORS
            writers = {n for n, t in tools.items() if not (t.annotations and t.annotations.read_only_hint)}
            check(tag + "The AI assistant: every tool names an address of the app it mirrors, its fixed role opens each, and no tool "
                        "mirroring a page's address (to look at) writes",
                  set(tools) == set(mirrors) and all(m in keys for m in mirrors.values()) and all(access.assistant_refusal(m) is None for m in mirrors.values())
                  and not {n for n in writers if not str(access.ROUTES[mirrors[n]]).startswith("do:")} and {"record_tracker_step", "remove_my_tracker_step"} <= writers,
                  str(set(tools) ^ set(mirrors)))

        # the setting off: everything as before
        r = c.get("/api/me").json()
        off = sweep({})
        bad = {k: v for k, v in off.items() if v in (401, 500) or (v == 403 and k != "GET /api/users")}
        check(tag + f"Setting off: /api/me says permissions are off; every one of the {len(off)} addresses answers without a sign-in, "
                    "none refused for a role, none failing (Users and roles alone is not shown: it lists people's addresses)",
              r["permissions_on"] is False and "off" in r["why"] and set(r["allowed"]) == set(access.ALL) and not bad
              and off["GET /api/users"] == 403 and "Permissions are off" in c.get("/api/users", headers=H("x@example.com")).json()["detail"]
              and c.get("/rightcost.js").status_code == 200 and socket_answer(None) == "echo" and r["sign_in"] == "not on Azure", str(bad))
        refused = c.post("/api/users/add", json={"email": "x@example.com", "role": "Admin"}, headers=H("x@example.com"))
        check(tag + "Setting off: nobody can change users (anyone signed in could make themselves an admin)",
              refused.status_code == 409 and "Permissions are off" in refused.json()["detail"])

        # the setting, as people may type it
        def admins_for(raw):
            os.environ["RIGHTPRICE_ADMINS"] = raw
            return access.admins_setting()
        forms = {'"gp@example.com"': ["gp@example.com"], "GP <GP@Example.com>": ["gp@example.com"], "mailto:gp@example.com": ["gp@example.com"],
                 "gp@example.com.": ["gp@example.com"], "'gp@example.com' ; Asha Rao <asha@example.com>": ["gp@example.com", "asha@example.com"],
                 "gp@example.com b@example.com": ["gp@example.com", "b@example.com"], "live.com#GP@Example.com": ["gp@example.com"],
                 "GP<gp@example.com> Asha<asha@example.com>": ["gp@example.com", "asha@example.com"],
                 '"Gnana Prakash" <gp@example.com> b@example.com': ["gp@example.com", "b@example.com"]}
        read = {raw: admins_for(raw)[0] for raw in forms}
        check(tag + "The setting is read as people type an address: in quotes, as Name <address> (several without commas too), with "
                    "mailto:, with live.com# in front, with a full stop after it, several at once",
              read == forms, str(read))
        rejects = admins_for("gp@example, @example.com, gp@@example.com, gp at example.com, gp@example.c")
        check(tag + "What is still not an e-mail address is not taken as one", rejects[0] == [] and len(rejects[1]) == 7, str(rejects))
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            admins_for("gp at example dot com")
            no_admin = c.get("/api/meta", headers=gp)
            page = c.get("/", headers=H("someone@example.com"))
            me_text = json.dumps(c.get("/api/me", headers=H("someone@example.com")).json())
        check(tag + "A setting naming no valid address: everyone refused is told the setting names no valid e-mail address (not what it holds), and so is the log",
              no_admin.status_code in (403, 503) and "names no valid e-mail address" in no_admin.json()["detail"]
              and "names no valid e-mail address" in me_text and "gp at example" not in me_text + no_admin.text
              and "names no valid e-mail address" in log.getvalue() and "gp at example" not in log.getvalue()
              and page.status_code == (503 if STORE == "files" else 200), log.getvalue()[:200])

        os.environ["RIGHTPRICE_ADMINS"] = " GP@Example.com ; not-an-address"
        nobody = sweep({})
        check(tag + f"Setting on, no sign-in: every one of the {len(nobody)} addresses but /api/me refuses (401), the home page included; "
                    "never treated as an admin; the shell's files stay open; the web socket is closed",
              all(v == 401 for k, v in nobody.items() if access.ROUTES.get(k) != access.PUBLIC and k != "GET /rightcost")
              and nobody["GET /api/me"] == 200 and c.get("/api/me").json()["let_in"] is False and "Sign in" in c.get("/").text
              and c.get("/api/meta", headers=H("")).status_code == 401 and c.get("/rightcost.js").status_code == 200 and socket_answer(None) == 1008,
              str({k: v for k, v in nobody.items() if v != 401}))
        me = c.get("/api/me", headers=H("gp@example.com")).json()
        check(tag + "Setting on: an admin named in it is Admin, whatever the letter case; an entry that is not an address is ignored and shown to admins",
              me["permissions_on"] and me["role"] == "Admin" and me["from_setting"] and me["setting_ignored"] == ["not-an-address"]
              and c.get("/api/meta", headers=H("GP@EXAMPLE.COM")).status_code == 200)

        # who is asking: one value only
        sign = {"gp header": c.get("/api/me", headers=gp).json(),
                "stranger header, gp claims": c.get("/api/me", headers=dict(H("stranger@example.com"), **P([{"typ": "email", "val": "gp@example.com"},
                                                                                                               {"typ": "upn", "val": "gp@example.com"}]))).json(),
                "display name": c.get("/api/me", headers=P([{"typ": "name", "val": "Mallory#gp@example.com"}], name_typ="name")).json(),
                "claims only": c.get("/api/me", headers=P([{"typ": "name", "val": "GP"}, {"typ": "preferred_username", "val": "GP@Example.com"}])).json(),
                "upn only": c.get("/api/me", headers=P([{"typ": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn", "val": "gp@example.com"}])).json(),
                "hash": c.get("/api/me", headers=H("x#gp@example.com")).json()}
        check(tag + "Who is asking is the name header alone; preferred_username or upn only when it is absent; never the display name; "
                    "\"#\" counts only in live.com#",
              sign["gp header"]["role"] == "Admin" and sign["stranger header, gp claims"]["let_in"] is False
              and sign["display name"]["signed_in"] is False and sign["claims only"]["role"] == "Admin" and sign["upn only"]["role"] == "Admin"
              and sign["hash"]["let_in"] is False and sign["hash"]["email"] == "x#gp@example.com",
              str({k: (v["email"], v["role"], v["let_in"]) for k, v in sign.items()}))
        twice = [("X-MS-CLIENT-PRINCIPAL-NAME", "gp@example.com"), ("X-MS-CLIENT-PRINCIPAL-NAME", "someone@example.com")]
        check(tag + "A request carrying a sign-in header twice is refused (400), on data, the home page and /api/me alike",
              c.get("/api/meta", headers=twice).status_code == 400 and c.get("/", headers=twice).status_code == 400
              and c.get("/api/me", headers=twice).status_code == 400
              and c.get("/api/meta", headers=[("X-MS-CLIENT-PRINCIPAL", "e30="), ("X-MS-CLIENT-PRINCIPAL", "e30=")]).status_code == 400)
        odd = [base64.b64encode(json.dumps({"claims": 5}).encode()).decode(), base64.b64encode(b"[1, 2]").decode(), "%%%not base64%%%",
               base64.b64encode(json.dumps({"claims": [5, {"typ": 1, "val": "gp@example.com"}, {"typ": "preferred_username", "val": None}]}).encode()).decode()]
        answers = [(c.get("/api/me", headers={"X-MS-CLIENT-PRINCIPAL": v}).status_code, c.get("/api/meta", headers={"X-MS-CLIENT-PRINCIPAL": v}).status_code)
                   for v in odd]
        check(tag + "A sign-in principal that does not read counts as no sign-in (never a failure of the server)", answers == [(200, 401)] * len(odd), str(answers))

        # on Azure: the headers are trusted only while App Service sign-in is on
        os.environ["WEBSITE_SITE_NAME"] = "rightprice"
        untrusted = c.get("/api/meta", headers=gp)
        untrusted_page = c.get("/", headers=gp)
        seen = [c.get("/api/me", headers=gp).json()["sign_in"]]
        os.environ["WEBSITE_AUTH_ENABLED"] = "True"
        trusted_again = c.get("/api/meta", headers=gp).status_code
        seen.append(c.get("/api/me", headers=gp).json()["sign_in"])
        os.environ.pop("WEBSITE_SITE_NAME", None)
        os.environ.pop("WEBSITE_AUTH_ENABLED", None)
        check(tag + "On Azure with App Service sign-in off, no one is let in, not even an admin named in the setting, and the page says why "
                    "(with no sign-out link, which would lead nowhere); /api/me shows how the app sees sign-in",
              untrusted.status_code == 503 and "sign-in (Authentication) is off" in untrusted.json()["detail"] and untrusted_page.status_code == 503
              and "Authentication" in untrusted_page.text and "/.auth/logout" not in untrusted_page.text and trusted_again == 200
              and seen == ["off", "on"], str(seen))

        tok = "t" * 40
        os.environ["RIGHTPRICE_MCP_TOKEN"] = tok
        check(tag + "Setting on: the AI assistant still comes in by its token alone, and a sign-in does not open /mcp",
              c.get("/mcp/health", headers={"Authorization": "Bearer " + tok}).status_code == 200 and c.get("/mcp/health", headers=gp).status_code == 401)
        os.environ.pop("RIGHTPRICE_MCP_TOKEN", None)

        if STORE == "files":
            no = c.get("/api/meta", headers=H("asha@example.com"))
            page = c.get("/", headers=H("asha@example.com"))
            check("[files] Setting on, no database: anyone not named in the setting is refused, saying a database is needed (the home page too); "
                  "the admins named get in",
                  no.status_code == 503 and "DATABASE_URL" in no.json()["detail"] and page.status_code == 503 and "DATABASE_URL" in page.text
                  and "/.auth/logout" not in page.text and c.get("/api/me", headers=H("asha@example.com")).json()["why_kind"] == "setup"
                  and c.get("/api/meta", headers=gp).status_code == 200 and c.post("/api/cost", json=masters.EXAMPLE_ROW, headers=gp).status_code == 200)
            u = c.get("/api/users", headers=gp)
            check("[files] The admin page says users need the database", u.status_code == 503 and "database" in u.json()["detail"]
                  and c.post("/api/users/add", json={"email": "a@example.com", "role": "Buyer"}, headers=gp).status_code == 503)
            os.environ.pop("RIGHTPRICE_ADMINS", None)
            check("[files] Setting taken off again: open as before", c.get("/api/meta", headers=H("asha@example.com")).status_code == 200)
            stand_in.shutdown()
            print("ALL OK" if ok else "SOMETHING FAILED")
            return 0 if ok else 1

        strangers = sweep(H("stranger@example.com"))
        shell = c.get("/", headers=H("stranger@example.com"))
        why = c.get("/api/me", headers=H("stranger@example.com")).json()
        with_data = [k for k in strangers if access.ROUTES.get(k) not in (access.PUBLIC, access.SHELL)]
        check(tag + f"Setting on: a signed-in person not added is refused (403) on every one of the {len(with_data)} addresses with data; "
                    "the shell is served (it has none), and /api/me says why, with the address to add",
              all(strangers[k] == 403 for k in with_data)
              and strangers["GET /"] == 200 and "access.js?v=" in shell.text and why["let_in"] is False and "not been given access" in why["why"]
              and "stranger@example.com" in why["why"] and socket_answer("stranger@example.com") == 1008,
              str({k: v for k, v in strangers.items() if v != 403}))
        add = lambda email, role, by=gp, name="": c.post("/api/users/add", json={"email": email, "name": name, "role": role}, headers=by)
        people = {"Admin": "a2@example.com", "Rates editor": "r@example.com", "Buyer": "b@example.com", "Viewer": "v@example.com"}
        made = [add(e, role, name=role + " person").status_code for role, e in people.items()]
        check(tag + "An admin adds a person of each role", made == [200] * 4, str(made))
        check(tag + "A bad address, a person twice, an unknown role are refused; a non-admin cannot add; Name <address> is read as the address",
              add("not an address", "Buyer").status_code == 400 and add("B@Example.com", "Viewer").status_code == 400
              and add("z@example.com", "Owner").status_code == 400 and add("z@example.com", "Admin", by=H("b@example.com")).status_code == 403
              and add("z@example.com", "Admin", by=H("r@example.com")).status_code == 403 and add("Bee <b@example.com>", "Viewer").status_code == 400)
        # each role against a sample: the exact answer of the route when allowed (its own answer to this made-up input), 403 when not
        sample = [("GET", "/api/meta", None, "GET /api/meta", 200), ("GET", "/api/table/Settings", None, "GET /api/table/{sheet}", 200),
                  ("GET", "/api/negotiations", None, "GET /api/negotiations", 200), ("GET", "/api/alerts", None, "GET /api/alerts", 200),
                  ("GET", "/api/costsheet", None, "GET /api/costsheet", 200), ("GET", "/api/template", None, "GET /api/template", 200),
                  ("POST", "/api/cost", masters.EXAMPLE_ROW, "POST /api/cost", 200), ("GET", "/api/pilot", None, "GET /api/pilot", 200),
                  ("GET", "/api/dashboard", None, "GET /api/dashboard", 200), ("POST", "/api/list", {}, "POST /api/list", 200),
                  ("GET", "/api/users", None, "GET /api/users", 200), ("GET", "/classic", None, "GET /classic", 200),
                  ("PUT", "/api/table/Nope", {}, "PUT /api/table/{sheet}", 404), ("POST", "/api/cotton", {}, "POST /api/cotton", 400),
                  ("POST", "/api/costsheet/apply", {"ids": []}, "POST /api/costsheet/apply", 400), ("POST", "/api/list/remove", {"ids": []}, "POST /api/list/remove", 400),
                  ("POST", "/api/negotiations/event", {}, "POST /api/negotiations/event", 400), ("POST", "/api/alerts/seen", {"ids": []}, "POST /api/alerts/seen", 200),
                  ("POST", "/api/draft", {}, "POST /api/draft", 400), ("POST", "/api/users/change", {"email": "nobody@example.com", "role": "Buyer"}, "POST /api/users/change", 404)]

        def matrix(email, allowed):
            wrong = []
            for method, path, body, key, code in sample:
                want = code if access.opens(access.ROUTES[key], allowed) else 403
                got = c.request(method, path, json=body, headers=H(email)).status_code
                if got != want:
                    wrong.append(f"{method} {path}: {got}, not {want}")
            return wrong
        for role, email in people.items():
            wrong = matrix(email, set(access.ALL) if role == "Admin" else D[role])
            check(tag + f"{role}: on {len(sample)} addresses (reading, rates, drafts, uploads, steps, alerts, users, the earlier screens) each gives "
                        "the route's own answer where the role may, and 403 where it may not",
                  not wrong, "; ".join(wrong))
        sockets = {role: socket_answer(email) for role, email in people.items()}
        check(tag + "The earlier screens' web socket opens through to the roles that may edit rates, and is closed (1008) to the others",
              sockets == {"Admin": "echo", "Rates editor": "echo", "Buyer": 1008, "Viewer": 1008}, str(sockets))
        classic = c.get("/classic", headers=H("v@example.com"))
        nosign = c.get("/")
        check(tag + "A refused page offers to sign out only when the refusal is about the person (their role here), and to sign in when no one is signed in",
              classic.status_code == 403 and "Not open to your role" in classic.text and "/.auth/logout" in classic.text
              and nosign.status_code == 401 and "/.auth/login/aad" in nosign.text and "/.auth/logout" not in nosign.text)
        refusal = c.put("/api/table/Settings", json={}, headers=H("b@example.com")).json()["detail"]
        check(tag + "A refusal says plainly what the role may not do", refusal == "Your role (Buyer) may not edit rates. Ask an admin if you need to.", refusal)
        check(tag + "A personal Microsoft account written live.com#address is found by its address",
              c.get("/api/me", headers=H("live.com#V@example.com")).json()["role"] == "Viewer")
        row = c.get("/api/costs", headers=gp).json()["rows"][1]
        step = lambda headers, n: c.post("/api/negotiations/event", headers=headers, json={"key": f"Purchase orders|{row['code']}", "kind": "Mill's quote" if n == 0 else "Our counter",
                                                                                      "price": row["price"] - n, "date": _dt.date.today().isoformat(), "code": row["code"], "seen": n})
        by = [step(H("Live.com#B@Example.COM"), 0), step(P([{"typ": "preferred_username", "val": "B@Example.com"}]), 1)]
        check(tag + "A step is recorded as the person the permission check read (lower case, without live.com#, from the claims when "
                    "the name is absent)",
              [x.status_code for x in by] == [200, 200] and [e["by"] for e in by[1].json()["events"]] == ["b@example.com", "b@example.com"],
              str([x.text[:200] for x in by]))

        # each role's permissions changed on the admin page
        perm = lambda changes, by=gp: c.post("/api/users/permissions", json={"changes": changes}, headers=by)
        perm([{"role": "Viewer", "permission": "page:pilot", "allowed": False}, {"role": "Viewer", "permission": "do:draft", "allowed": True}])
        moved = (c.get("/api/pilot", headers=H("v@example.com")).status_code, c.get("/api/pilot", headers=H("b@example.com")).status_code,
                 c.post("/api/draft", json={}, headers=H("v@example.com")).status_code)
        grid = c.get("/api/users", headers=gp).json()["grid"]["Viewer"]
        check(tag + "Permissions changed for a role take effect at once, for that role only, and show as differing from the default",
              moved == (403, 200, 400) and grid["page:pilot"] == {"allowed": False, "default": True}
              and grid["do:draft"] == {"allowed": True, "default": False}, str(moved))
        perm([{"role": "Viewer", "permission": "page:list", "allowed": False}, {"role": "Buyer", "permission": "page:dashboard", "allowed": False},
              {"role": "Rates editor", "permission": "page:cost", "allowed": False}])
        still = {"Viewer without Bulk upload: the Dashboard's list and panels": (c.post("/api/list", json={}, headers=H("v@example.com")).status_code,
                                                                                c.get("/api/insights", headers=H("v@example.com")).status_code),
                 "Buyer without the Dashboard: Yarn prices": (c.get("/api/dashboard", headers=H("b@example.com")).status_code,
                                                             c.get("/api/table/Yarn_Rates", headers=H("b@example.com")).status_code),
                 "Rates editor without Create cost: Right cost's Negotiation tab": (c.post("/api/cost", json=masters.EXAMPLE_ROW, headers=H("r@example.com")).status_code,
                                                                                  c.get("/api/costs", headers=H("r@example.com")).status_code)}
        hidden = (c.get("/api/template", headers=H("v@example.com")).status_code, c.get("/api/insights", headers=H("b@example.com")).status_code,
                  c.post("/api/cost-sheet", json=masters.EXAMPLE_ROW, headers=H("r@example.com")).status_code)
        check(tag + "One page unticked: every other page keeps the data it reads; the page's own addresses are refused",
              all(v == (200, 200) for v in still.values()) and hidden == (403, 403, 403), f"{still} {hidden}")
        perm([{"role": "Viewer", "permission": "page:list", "allowed": True}, {"role": "Buyer", "permission": "page:dashboard", "allowed": True},
              {"role": "Rates editor", "permission": "page:cost", "allowed": True}])
        view = c.get("/api/users", headers=gp).json()
        check(tag + "The admin page says what a page's tick does not hide, and for each page what unticking it hides",
              "not a way to keep figures secret" in view["grid_note"] and all(p["unticked"] for p in view["permissions"] if p["key"] in pages)
              and set(view["assistant"]["tools"]) == set(getattr(server.mcp_server, "MIRRORS", {})))
        check(tag + "Admin's permissions, and user admin for another role, cannot be changed; only an admin changes permissions",
              perm([{"role": "Admin", "permission": "page:pilot", "allowed": False}]).status_code == 400
              and perm([{"role": "Buyer", "permission": "do:manage_users", "allowed": True}]).status_code == 400
              and perm([{"role": "Viewer", "permission": "page:nope", "allowed": True}]).status_code == 400
              and perm([{"role": "Viewer", "permission": "page:pilot", "allowed": True}], by=H("r@example.com")).status_code == 403)
        perm([{"role": "Viewer", "permission": "page:pilot", "allowed": True}, {"role": "Viewer", "permission": "do:draft", "allowed": False}])
        back = c.get("/api/users", headers=gp).json()
        check(tag + "Put back, they are the defaults again", back["changed"] == [] and back["grid"]["Viewer"]["page:pilot"]["allowed"]
              and c.get("/api/pilot", headers=H("v@example.com")).status_code == 200)

        # the AI assistant's tools go through the same check: with a permission taken from its role, the tool refuses
        if server.mcp_server is not None:
            os.environ["RIGHTPRICE_MCP_TOKEN"] = tok
            hd = {"Authorization": "Bearer " + tok, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
            call = lambda name, **args: json.loads(c.post("/mcp", headers=hd, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                                                     "params": {"name": name, "arguments": args}}).json()["result"]["content"][0]["text"])
            kept_allowed = set(access.ASSISTANT_ALLOWED)
            ex = call("list_choices")["example"]
            access.ASSISTANT_ALLOWED.discard("do:record_steps")
            access.ASSISTANT_ALLOWED.discard("page:pack")
            try:
                code = c.get("/api/costs", headers=gp).json()["rows"][0]["code"]
                stepped = call("record_tracker_step", key=f"Purchase orders|{code}", kind="Mill's quote", price_per_m=100)
                packed = call("negotiation_pack", mill="Arvind")
                alerts_ok = call("quote_alerts")
            finally:
                access.ASSISTANT_ALLOWED.clear()
                access.ASSISTANT_ALLOWED.update(kept_allowed)
            check(tag + "The AI assistant's tools go through the permission of the address each mirrors: taken from its role, the tool "
                        "refuses and nothing is done; the others still work",
                  "may not record or remove negotiation steps" in stepped.get("error", "") and "may not make a negotiation pack" in packed.get("error", "")
                  and "error" not in alerts_ok and f"Purchase orders|{code}" not in c.get("/api/negotiations", headers=gp).json()["items"]
                  and call("cost_fabric", choices=ex).get("should_cost_per_m") and "may not" not in json.dumps(call("negotiation_pack", mill="Arvind")), f"{stepped} {packed}")
            os.environ.pop("RIGHTPRICE_MCP_TOKEN", None)

        # role changed, switched off and on
        change = lambda body, by=gp: c.post("/api/users/change", json=body, headers=by)
        change({"email": "b@example.com", "role": "Viewer"})
        demoted = c.post("/api/negotiations/event", json={}, headers=H("b@example.com")).status_code
        change({"email": "B@example.com", "role": "Buyer"})
        check(tag + "A role changed takes effect at once", demoted == 403 and c.post("/api/negotiations/event", json={}, headers=H("b@example.com")).status_code == 400)
        change({"email": "v@example.com", "active": False})
        switched = c.get("/api/meta", headers=H("v@example.com"))
        offme = c.get("/api/me", headers=H("v@example.com")).json()
        change({"email": "v@example.com", "active": True})
        check(tag + "A person switched off is refused and told so; switched on again, let in",
              switched.status_code == 403 and "switched off" in switched.json()["detail"] and offme["let_in"] is False and "switched off" in offme["why"]
              and c.get("/api/meta", headers=H("v@example.com")).status_code == 200
              and change({"email": "v@example.com", "active": True}).status_code == 400 and change({"email": "nobody@example.com", "role": "Buyer"}).status_code == 404)

        # the last admin in the list
        last = [change({"email": "a2@example.com", "role": "Buyer"}).status_code, change({"email": "a2@example.com", "active": False}).status_code,
                change({"email": "a2@example.com", "role": "Viewer"}, by=H("a2@example.com")).status_code]
        words = change({"email": "a2@example.com", "role": "Buyer"}).json()["detail"]
        add("a3@example.com", "Admin", by=H("a2@example.com"))
        moved = change({"email": "a2@example.com", "role": "Rates editor"}, by=H("a3@example.com")).status_code
        check(tag + "The last admin in the list cannot be made something else or switched off, by anyone; with another admin, they can",
              last == [400, 400, 400] and "last admin" in words and moved == 200
              and change({"email": "a3@example.com", "active": False}, by=H("a3@example.com")).status_code == 400, f"{last} {moved}")
        change({"email": "a2@example.com", "role": "Admin"}, by=H("a3@example.com"))

        # the record of changes
        log = c.get("/api/users", headers=gp).json()["audit"]
        acts = [a["action"] for a in reversed(log)]
        check(tag + "Every change is in the record, with who made it and when, and only the changes that were made",
              acts == ["person added"] * 4 + ["permission taken away", "permission given"] + ["permission taken away"] * 3 + ["permission given"] * 3
              + ["permission given", "permission taken away", "role changed", "role changed", "switched off", "switched on", "person added",
                 "role changed", "role changed"]
              and all(a["who"] and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", a["at"]) for a in log)
              and log[0]["who"] == "a3@example.com" and log[0]["detail"] == {"from": "Rates editor", "to": "Admin"}
              and log[-1]["who"] == "gp@example.com" and log[-1]["subject"] == "a2@example.com", str(acts))
        check(tag + "The admin page is for admins only; the shell carries the access script",
              c.get("/api/users", headers=H("r@example.com")).status_code == 403 and "access.js?v=" in c.get("/", headers=H("b@example.com")).text)

        # an address added with no permission assigned is refused to everyone, admins included
        stray = APIRoute("/api/zz-stage3-unassigned", lambda: {"secret": 1}, methods=["GET"])
        server.app.router.routes.insert(0, stray)
        try:
            got = c.get("/api/zz-stage3-unassigned", headers=gp)
            check(tag + "An address with no permission assigned is refused to everyone while permissions are on, and the route list names it",
                  got.status_code == 403 and "no permission assigned" in got.json()["detail"] and server.route_keys()["GET /api/zz-stage3-unassigned"] is None)
        finally:
            server.app.router.routes.remove(stray)

        # a hung database: the shell still opens at once; the calls for data wait their limit, then refuse
        kept = store._store
        held, release = threading.Event(), threading.Event()

        def hold():
            with kept._lock:
                held.set()
                release.wait(20)
        wait_was, kept.WAIT = kept.WAIT, 1
        threading.Thread(target=hold, daemon=True).start()
        held.wait(5)
        try:
            t0 = time.time()
            home = c.get("/", headers=H("b@example.com"))
            quick = time.time() - t0
            busy = c.get("/api/meta", headers=H("b@example.com"))
            busy_me = c.get("/api/me", headers=H("b@example.com")).json()
        finally:
            release.set()
            kept.WAIT = wait_was
        check(tag + "A hung database: the shell page is served at once, without it; a call for data is refused with 503 saying so, never let in on a guess",
              home.status_code == 200 and quick < 0.9 and busy.status_code == 503 and "cannot be read just now" in busy.json()["detail"]
              and busy_me["why_kind"] == "database" and c.get("/api/me", headers=H("b@example.com")).json()["let_in"] is True, f"{quick:.2f} s")
        dead = store.SqlStore("postgresql://x:y@127.0.0.1:9/postgres?connect_timeout=3", folder=tempfile.mkdtemp(prefix="rightprice-dead-"))
        store._store = dead
        try:
            down = c.get("/api/meta", headers=H("b@example.com"))
            check(tag + "The database unreachable: a person is refused with 503 saying so; an admin named in the setting is let in",
                  down.status_code == 503 and "cannot be read just now" in down.json()["detail"] and c.get("/api/me", headers=gp).json()["let_in"] is True)
        finally:
            store._store = kept
            dead._drop()

        os.environ.pop("RIGHTPRICE_ADMINS", None)
        check(tag + "Setting taken off again: everything open as before, the list of people kept",
              c.get("/api/meta").status_code == 200 and c.get("/api/meta", headers=H("stranger@example.com")).status_code == 200
              and len(store.get()._read(data_users.people)) == 5 and c.get("/api/users", headers=gp).status_code == 403)
    stand_in.shutdown()
    txt = open(os.path.join(HERE, "web", "access.css"), encoding="utf8").read()
    check(tag + "web/access.css: every brace closed", txt.count("{") == txt.count("}"))
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


# ===================================================================== GP's decision of 27 Nov 2026: the AI assistant does what an Admin can
def assistant_checks():
    """The MCP token is an admin key: every change an Admin can make in the app has a tool (mcp_server.py), called here
    through /mcp with the token, as an assistant calls it. Each is set beside its web route on the same store, made by a
    signed-in admin: the same stored result, the same refusal in the same words, and the change recorded as "AI
    assistant" where the route records the admin. Without the token nothing is reachable. Runs on SQLite and PostgreSQL."""
    import base64
    import pandas as pd
    import mill_sheet
    import store
    from rules import access
    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    tag, tok, AI = f"[{STORE}, AI assistant] ", "m" * 40, "AI assistant"
    gp = {"X-MS-CLIENT-PRINCIPAL-NAME": "gp@example.com"}
    accept = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    hd = dict(accept, Authorization="Bearer " + tok)
    for k in ("WEBSITE_SITE_NAME", "WEBSITE_AUTH_ENABLED"):
        os.environ.pop(k, None)
    os.environ["RIGHTPRICE_MCP_TOKEN"] = tok
    os.environ["RIGHTPRICE_ADMINS"] = "gp@example.com"         # permissions on: the web routes record the admin by name
    ms = server.mcp_server
    if ms is None:
        check(tag + "The MCP package loads", False)
        return 1
    b64 = lambda data: base64.b64encode(data).decode()
    sql = lambda text, params=(): store.get()._read(lambda cur: cur.all(text, params))
    versions = lambda: [tuple(r) for r in sql("SELECT id, created_by, reason FROM rate_version ORDER BY id")]
    today = _dt.date.today().isoformat()

    def xlsx(df, sheet="Sheet1"):
        buf = io.BytesIO()
        df.to_excel(buf, index=False, sheet_name=sheet)
        return buf.getvalue()

    with TestClient(server.app) as c:
        def rpc(method, params, headers=hd):
            return c.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

        def call(tool_, **args):
            text = rpc("tools/call", {"name": tool_, "arguments": args}).json()["result"]["content"][0]["text"]
            try:
                return json.loads(text)
            except ValueError:
                return {"error": text}
        web = lambda method, path, **kw: c.request(method, path, headers=gp, **kw)
        upload = lambda path, name, data: c.post(path, headers=gp, files={"file": (name, io.BytesIO(data))})
        detail = lambda r: r.json().get("detail") if r.status_code != 200 else None
        same_refusal = lambda m, w: bool(m.get("error")) and m.get("error") == detail(w)
        tools = {t["name"]: t for t in rpc("tools/list", {}).json()["result"]["tools"]}
        names, mirrors = sorted(tools), ms.MIRRORS

        # without the token, nothing
        shut = [f"{n} {h}: {code}" for n in names for h, code in
                ((h, rpc("tools/call", {"name": n, "arguments": {}}, headers=dict(accept, **hh)).status_code)
                 for h, hh in (("no token", {}), ("wrong token", {"Authorization": "Bearer " + "x" * 40}), ("no Bearer", {"Authorization": tok}), ("admin's sign-in", gp)))
                if code != 401]
        os.environ.pop("RIGHTPRICE_MCP_TOKEN")
        off = rpc("tools/call", {"name": "users_and_roles", "arguments": {}}).status_code
        os.environ["RIGHTPRICE_MCP_TOKEN"] = tok
        check(tag + f"Without the token nothing is reachable: each of the {len(names)} tools called with no token, a wrong one, the token without "
                    "'Bearer', or an admin's Microsoft sign-in is refused (401), the list of tools too; with the token setting gone, /mcp is off (404)",
              not shut and rpc("tools/list", {}, headers=accept).status_code == 401 and off == 404, "; ".join(shut[:4]))

        # the tools as they are declared
        keys = server.route_keys()
        ann = {n: t.get("annotations") or {} for n, t in tools.items()}
        writes = {n for n in names if not ann[n].get("readOnlyHint")}
        exempt = lambda k: k in ms.NOT_MIRRORED or f"* {k.split(' ', 1)[1]}" in ms.NOT_MIRRORED
        missing = sorted(k for k, need in keys.items() if str(need).startswith("do:") and k not in set(mirrors.values()) and not exempt(k))
        reads_on_actions = {"intake_page", "intake_api", "intake_map_columns", "draft_message_to_mill"}     # an action's step that keeps nothing
        on_actions = {n for n in names if str(access.ROUTES[mirrors[n]]).startswith("do:")}
        rate_tools = {n for n in writes if access.ROUTES[mirrors[n]] in ("do:edit_rates", "do:apply_drafts") and ann[n].get("destructiveHint")}
        check(tag + "GP's decision: every action an Admin can take in the app (each address needing a do: permission) has a tool mirroring it, or "
                    "mcp_server.NOT_MIRRORED says why not, so a later stage's new action fails here until it has one (mcp_server.py, \"Adding a tool\")",
              not missing and set(names) == set(mirrors) and all(m in keys for m in mirrors.values()), str(missing))
        check(tag + "Every tool that changes shared data is marked writing and destructive (a client asks the person first) and says what it changes "
                    "and that the person must confirm; the tools on pages, and the steps that keep nothing, are read only; only Bring in prices' "
                    "first step is writing but not destructive (it keeps a PDF or picture as the source)",
              writes == on_actions - reads_on_actions and all(ann[n].get("destructiveHint") for n in writes - {"intake_file"})
              and not ann["intake_file"].get("destructiveHint") and all("confirm" in tools[n]["description"].lower()
                                                                       and re.search(r"THIS\s+(CHANGES|ADDS|REMOVES)", tools[n]["description"])
                                                                       or n == "intake_file" for n in writes)
              and {n for n in names if ann[n].get("openWorldHint")} == {"intake_page", "intake_api", "draft_message_to_mill"},
              str(sorted(writes ^ (on_actions - reads_on_actions))))
        check(tag + "Rule 2 holds for the assistant: each tool that changes the rate master says to change a rate only when the person explicitly "
                    "asks for that change, stating the old and the new figure first; so do the server's instructions",
              rate_tools >= {"edit_rate_table", "add_cotton_price", "intake_add_rows", "apply_cost_sheet_drafts", "add_dated_rate", "remove_dated_rate", "load_market_dated_rates", "intake_add_dated_rates"}
              and all("explicitly asked" in tools[n]["description"] and "the old figure and the new one" in tools[n]["description"] for n in rate_tools)
              and "NEVER CHANGE A RATE" in (ms.mcp.instructions or ""), str(rate_tools))
        fixed = call("change_role_permissions", changes=[{"role": AI, "permission": "do:draft", "allowed": False}])
        check(tag + "The AI assistant is a fixed role with the Admin role's permissions, kept in code: not one of the roles, and the admin page "
                    "cannot change it (refused in the same words as on the screen)",
              access.ASSISTANT_ALLOWED == access.DEFAULTS[access.ADMIN] == set(access.ALL) and AI not in access.ROLES
              and same_refusal(fixed, web("POST", "/api/users/permissions", json={"changes": [{"role": AI, "permission": "do:draft", "allowed": False}]})), str(fixed))

        # every tool refused, in words, when its address's permission is taken from the role; nothing done
        fill = {"string": "x", "integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}
        minimal = lambda schema: {p: fill.get(schema["properties"][p].get("type"), "x") for p in schema.get("required", [])}
        fingerprint = lambda: (json.dumps(c.get("/api/store", headers=gp).json(), sort_keys=True), sql("SELECT count(*) FROM audit_log"))
        kept, before, gated = set(access.ASSISTANT_ALLOWED), fingerprint(), []
        free = [n for n in names if access.ROUTES[mirrors[n]] == access.MEMBER]
        try:
            for n in names:
                if n in free:
                    continue
                access.ASSISTANT_ALLOWED.difference_update(access._needs(access.ROUTES[mirrors[n]]))
                got = call(n, **minimal(tools[n]["inputSchema"]))
                access.ASSISTANT_ALLOWED.update(kept)
                if "The AI assistant may not" not in str(got.get("error")) or "Nothing was done" not in str(got.get("error")):
                    gated.append(f"{n}: {str(got)[:100]}")
        finally:
            access.ASSISTANT_ALLOWED.clear()
            access.ASSISTANT_ALLOWED.update(kept)
        check(tag + f"Each of the {len(names) - len(free)} tools with a permission is refused in words when its address's permission is taken from the "
                    f"assistant's role, and nothing is done ({', '.join(free)}: what anyone let in reads)",
              not gated and fingerprint() == before and len(free) <= 2, "; ".join(gated[:4]))

        # reading: what the screens read
        meta, yr = web("GET", "/api/meta").json(), web("GET", "/api/table/Yarn_Rates").json()
        as_lists = lambda rows, cols: [[r[k] for k in cols] for r in rows]
        listing, mt = call("rate_table"), call("rate_table", sheet="Yarn_Rates")
        check(tag + "rate_table: every table the screens list, which can be edited, and a table's rows exactly as the screen reads them, numbered from 1",
              [t["sheet"] for t in listing["tables"]] == list(meta["tables"]) and {t["sheet"] for t in listing["tables"] if t["editable"]} == set(meta["editable"])
              and mt["columns"] == yr["columns"] and as_lists(mt["rows"], yr["columns"]) == yr["rows"] and mt["rows"][0]["row"] == 1
              and call("rate_table", sheet="Nope").get("error") == detail(web("GET", "/api/table/Nope")))
        ym, db, pw, pm = call("yarn_master"), call("dashboard"), web("GET", "/api/pilot").json(), call("pilot_results")
        cot_w, cot_m = web("GET", "/api/cotton").json(), call("cotton_prices", last=5000)
        diff = _first_difference(db["panels"], web("GET", "/api/insights").json())
        check(tag + "yarn_master, dashboard, pilot_results and cotton_prices give what the Yarn prices page, the Dashboard, Pilot results and Cotton prices read",
              ym["cotton_yarns_against_the_market"] == web("GET", "/api/dashboard").json()["yarns"] and as_lists(ym["yarns"], yr["columns"]) == yr["rows"]
              and diff is None and db["negotiation_won"] == web("GET", "/api/negotiations/summary").json()
              and pm["sheets"] == list(pw) and all(as_lists(pm["tables"][k], pw[k]["columns"]) == pw[k]["rows"] for k in pw)
              and [[p["date"], p["price"]] for p in cot_m["prices"]] == cot_w["points"] and cot_m["unit"] == cot_w["unit"], str(diff))
        tpl = web("GET", "/api/template").content
        bm, bw = call("cost_template_file", file_base64=b64(tpl), file_name="t.xlsx"), upload("/api/bulk", "t.xlsx", tpl).json()
        check(tag + "cost_template_file costs a filled template as Bulk upload does, and keeps nothing",
              as_lists(bm["rows"], bw["results"]["columns"]) == bw["results"]["rows"] and bm["rows_refused"] == bw["rejected"] == 0
              and json.dumps(c.get("/api/store", headers=gp).json(), sort_keys=True) == before[0])

        # editing a rate table
        cols = yr["columns"]
        ki, ri = cols.index("Yarn key"), cols.index("Rate Rs/kg")
        n = next(i for i, r in enumerate(yr["rows"]) if r[ki] == "Cotton 40S") + 1
        r0 = yr["rows"][n - 1][ri]
        v0 = versions()
        stale = call("edit_rate_table", sheet="Yarn_Rates", changes=[{"row": n, "column": "Rate Rs/kg", "old": r0 + 1, "new": r0 + 7}])
        v_stale = versions()
        done = call("edit_rate_table", sheet="Yarn_Rates", changes=[{"row": n, "column": "Rate Rs/kg", "old": r0, "new": r0 + 7}])
        t_ai, v_ai = web("GET", "/api/table/Yarn_Rates").json(), versions()
        web("PUT", "/api/table/Yarn_Rates", json={"columns": cols, "rows": yr["rows"]})            # back as it was, on the screen
        web("PUT", "/api/table/Yarn_Rates", json={"columns": cols, "rows": t_ai["rows"]})          # the same change, made on the screen
        t_web, v_web = web("GET", "/api/table/Yarn_Rates").json(), versions()
        check(tag + "edit_rate_table: a cell changed through the assistant (row, column, old and new figure) is stored exactly as the same change saved "
                    "on the screen; the answer lists it, old and new; each save is a new rate version, the earlier ones kept; recorded as \"AI assistant\" "
                    "where the screen records the admin",
              t_ai["rows"][n - 1][ri] == r0 + 7 and t_web == t_ai and done.get("saved") is True
              and done["changed"]["cells"] == [{"row": n, "column": "Rate Rs/kg", "old": r0, "new": r0 + 7}]
              and v_ai[:-1] == v0 and v_ai[-1][1:] == (AI, "Table edited: Yarn_Rates") and v_web[:len(v_ai)] == v_ai and v_web[-1][1:] == ("gp@example.com", "Table edited: Yarn_Rates"),
              str(done)[:300])
        check(tag + "edit_rate_table: an old figure that is not what the table holds now is refused, saying so, and nothing is saved",
              "does not hold the old figures" in stale.get("error", "") and f"{r0!r}" in stale["error"] and v_stale == v0, str(stale)[:200])
        back = call("edit_rate_table", sheet="Yarn_Rates", rows=mt["rows"])        # the whole table, rows as rate_table gave them
        check(tag + "edit_rate_table: the whole table sent back (as rate_table gave it) puts it back exactly, and says which cell changed",
              web("GET", "/api/table/Yarn_Rates").json()["rows"] == yr["rows"] and back["changed"]["cells"] == [{"row": n, "column": "Rate Rs/kg", "old": r0 + 7, "new": r0}]
              and versions()[-1][1] == AI)
        bad = [list(r) for r in yr["rows"]]
        bad[n - 1][ri] = "abc"
        twice, blank = [list(r) for r in yr["rows"]] + [list(yr["rows"][n - 1])], [list(r) for r in yr["rows"]]
        blank[n - 1][ki] = ""
        v_before = versions()
        refused = {what: (call("edit_rate_table", sheet=sheet, rows=rows), web("PUT", f"/api/table/{sheet}", json={"columns": cols, "rows": rows}))
                   for what, sheet, rows in (("a word for a number", "Yarn_Rates", bad), ("a key twice", "Yarn_Rates", twice), ("a blank key", "Yarn_Rates", blank),
                                             ("an empty table", "Yarn_Rates", []), ("a table not edited here", "Cotton_Prices", []), ("no such table", "Nope", []))}
        check(tag + "edit_rate_table refuses what the screen refuses, in the same words (a word for a number, a key twice or blank, an empty table, a table "
                    "not edited here), and nothing is saved",
              all(same_refusal(m, w) for m, w in refused.values()) and versions() == v_before,
              str({k: (m.get("error"), detail(w)) for k, (m, w) in refused.items() if not same_refusal(m, w)}))

        # a cotton price
        cot0 = len(web("GET", "/api/table/Cotton_Prices").json()["rows"])
        day = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        cm = call("add_cotton_price", date=day, price_per_candy=55555, source="check")
        web("POST", "/api/cotton", json={"date": day, "price": 55555, "source": "check"})
        cot, vv = web("GET", "/api/table/Cotton_Prices").json()["rows"], versions()
        check(tag + "add_cotton_price adds the same row as Prices > Cotton prices, says the latest price before it, recorded as \"AI assistant\"; "
                    "a bad date or price is refused in the screen's words",
              len(cot) == cot0 + 2 and cot[-1] == cot[-2] and cm["added"]["Price"] == 55555 and cm["latest_before"] is not None
              and vv[-2][1:] == (AI, f"Cotton price added: {day}, Rs 55555") and vv[-1][1] == "gp@example.com"
              and same_refusal(call("add_cotton_price", date="not a date", price_per_candy=5), web("POST", "/api/cotton", json={"date": "not a date", "price": 5}))
              and same_refusal(call("add_cotton_price", date=day, price_per_candy=-5), web("POST", "/api/cotton", json={"date": day, "price": -5})), str(cm)[:200])

        # Bring in prices: a file, its columns, the rows added
        csv = b"Count,Yarn,Rate\n40s,Combed compact,351\n50s,Combed compact,402\n60s,Combed compact,\n"
        fm, fw = call("intake_file", file_base64=b64(csv), file_name="list.csv"), upload("/api/intake/file", "list.csv", csv).json()
        sheet = next(iter(fw["sheets"]))
        mm = call("intake_map_columns", token=fm["token"], table=sheet, count_column="Count", rate_column="Rate", yarn_column="Yarn")
        mw = web("POST", "/api/intake/map", json={"token": fw["token"], "sheet": sheet, "count": "Count", "low": "Rate", "yarn": "Yarn"}).json()
        my0 = len(web("GET", "/api/table/Market_Yarn").json()["rows"])
        am = call("intake_add_rows", rows=mm["rows"], source="list.csv")
        aw = web("POST", "/api/intake/add", json={"rows": mw["rows"], "source": "list.csv"}).json()
        my, vv = web("GET", "/api/table/Market_Yarn").json()["rows"], versions()
        check(tag + "Bring in prices through the assistant reads the file, maps its columns and adds the rows exactly as the screen does (a file given "
                    "as base64 with its name); the addition recorded as \"AI assistant\"",
              {k: v["first_rows"] for k, v in fm["tables"].items()} == {k: v["rows"] for k, v in fw["sheets"].items()} and mm["rows"] == mw["rows"]
              and mm["columns"] == mw["columns"] and am["added"] == aw["added"] == 2 and len(my) == my0 + 4 and my[-4:-2] == my[-2:]
              and vv[-2][1:] == (AI, "Market yarn prices brought in: 2 rows") and vv[-1][1] == "gp@example.com", str(am))
        refused = {"no such token": (call("intake_map_columns", token="nope", table=sheet, count_column="Count", rate_column="Rate"),
                                     web("POST", "/api/intake/map", json={"token": "nope", "sheet": sheet, "count": "Count", "low": "Rate"})),
                   "no complete row": (call("intake_add_rows", rows=[[None] * 6]), web("POST", "/api/intake/add", json={"rows": [[None] * 6]})),
                   "a file of another kind": (call("intake_file", file_base64=b64(b"x"), file_name="x.exe"), upload("/api/intake/file", "x.exe", b"x")),
                   "no page address": (call("intake_page", url=""), web("POST", "/api/intake/link", json={"url": ""})),
                   "no endpoint": (call("intake_api", url=""), web("POST", "/api/intake/api", json={"url": ""}))}
        check(tag + "Bring in prices refuses what the screen refuses, in its words; a file that is not base64, or without a name, is refused in words",
              all(same_refusal(m, w) for m, w in refused.values()) and "not base64" in call("intake_file", file_base64="@@ not base64 @@", file_name="a.csv").get("error", "")
              and "file's name" in call("intake_file", file_base64=b64(csv), file_name="").get("error", "") and len(web("GET", "/api/table/Market_Yarn").json()["rows"]) == my0 + 4,
              str({k: (m.get("error"), detail(w)) for k, (m, w) in refused.items() if not same_refusal(m, w)}))

        # dated yarn rates (stage 5): typed, removed, brought in, loaded from the market history; each beside its web route
        dated = lambda: web("GET", "/api/dated-rates").json()
        bare = lambda e: {k: v for k, v in e.items() if k not in ("id", "entered_at", "entered_by", "removed_at", "removed_by", "removed_why")}
        at = lambda mo, key="Cotton 40S": next(e for e in dated()["entries"] if (e["yarn_key"], e["month"]) == (key, mo))
        first = _dt.date.today().replace(day=1)
        mon, later = (first - _dt.timedelta(days=1)).strftime("%Y-%m"), (first + _dt.timedelta(days=40)).strftime("%Y-%m")
        typed = {"yarn_key": "Cotton 40S", "month": mon, "rests_on": "quote", "rate": 352.5, "gst": False, "note": "a yarn quote"}
        dm = call("add_dated_rate", **typed)
        e_ai = at(mon)
        rd = call("remove_dated_rate", rate_id=e_ai["id"])
        gone = dated()["history"][0]
        web("POST", "/api/dated-rates", json=typed)
        e_web = at(mon)
        check(tag + "add_dated_rate and remove_dated_rate enter and take out a dated yarn rate exactly as Yarn prices does; entered and removed by "
                    "\"AI assistant\" where the screen records the admin; dated_rates reads what the page reads",
              dm.get("saved") is True and bare(e_ai) == bare(e_web) and e_ai["entered_by"] == AI and e_web["entered_by"] == "gp@example.com"
              and rd.get("removed") == 1 and gone["id"] == e_ai["id"] and gone["removed_by"] == AI
              and call("dated_rates")["in_force"] == dated()["entries"] and call("dated_rates")["rule"] == dated()["rule"], str(dm) + str(rd))
        refused = {what: (call("add_dated_rate", **args), web("POST", "/api/dated-rates", json=args)) for what, args in
                   (("a yarn not in the master", dict(typed, yarn_key="Cotton 41S")), ("a month still to come", dict(typed, month=later)),
                    ("no source said", dict(typed, rests_on="")), ("a rate outside the limits", dict(typed, rate=9)),
                    ("another document not named", dict(typed, rests_on="other", note="")), ("a price with GST over one without", dict(typed, gst=True, rate=360)))}
        refused["removed twice"] = (call("remove_dated_rate", rate_id=e_ai["id"]), web("POST", "/api/dated-rates/remove", json={"id": e_ai["id"]}))
        check(tag + "The dated rate tools refuse what Yarn prices refuses, in its words (a yarn not in the master, a month to come, no source, a rate "
                    "outside the limits, a document not named, GST over a rate without, a rate removed twice), and nothing changes",
              all(same_refusal(m, w) for m, w in refused.values()) and [bare(e) for e in dated()["entries"]] == [bare(e_web)],
              str({k: (m.get("error"), detail(w)) for k, (m, w) in refused.items() if not same_refusal(m, w)}))
        web("POST", "/api/dated-rates/remove", json={"id": e_web["id"]})
        name = f"circular 05.{mon[5:]}.{mon[:4]}.csv"
        csv_d = b"Count,Yarn,Rate\n40s,Combed compact,351\n40s,Combed compact,361\n50s,Combed compact,402\n"
        fd_m, fd_w = call("intake_file", file_base64=b64(csv_d), file_name=name), upload("/api/intake/file", name, csv_d).json()
        sh = next(iter(fd_w["sheets"]))
        md_m = call("intake_map_columns", token=fd_m["token"], table=sh, count_column="Count", rate_column="Rate", yarn_column="Yarn")
        md_w = web("POST", "/api/intake/map", json={"token": fd_w["token"], "sheet": sh, "count": "Count", "low": "Rate", "yarn": "Yarn"}).json()
        give = lambda rows: [list(r[:6]) + [k, False] for r, k in zip(rows, ["Cotton 40S", "Cotton 40S", ""])]
        pv_m = call("intake_add_dated_rates", rows=give(md_m["rows"]), read_token=md_m["read_token"], source=name, preview=True)
        pv_w = web("POST", "/api/intake/add-dated", json={"rows": give(md_w["rows"]), "read_token": md_w["read_token"], "source": name, "preview": True}).json()
        ad_m = call("intake_add_dated_rates", rows=give(md_m["rows"]), read_token=md_m["read_token"], source=name)
        b_ai = at(mon)
        web("POST", "/api/dated-rates/remove", json={"id": b_ai["id"]})
        ad_w = web("POST", "/api/intake/add-dated", json={"rows": give(md_w["rows"]), "read_token": md_w["read_token"], "source": name}).json()
        b_web = at(mon)
        check(tag + "intake_add_dated_rates brings reviewed rows in as dated yarn rates exactly as Bring in prices does: the month read from the "
                    "document, two prices averaged, a row given no yarn left out, the preview first; entered by \"AI assistant\"",
              {k: pv_m[k] for k in ("plan", "need_month", "left_out")} == {k: pv_w[k] for k in ("plan", "need_month", "left_out")} and md_m["rows"] == md_w["rows"]
              and ad_m["rates"] == ad_w["rates"] == [{"yarn_key": "Cotton 40S", "month": mon, "rate": 356, "entries": 2}] and ad_m["left_out"] == 1
              and bare(b_ai) == bare(b_web) and b_ai["entered_by"] == AI and b_web["entered_by"] == "gp@example.com", str(pv_m)[:200] + str(ad_m)[:200])
        refused = {what: (call("intake_add_dated_rates", rows=rows, read_token=md_m["read_token"]),
                          web("POST", "/api/intake/add-dated", json={"rows": rows, "read_token": md_w["read_token"]})) for what, rows in
                   (("a yarn not in the master", [list(md_m["rows"][0][:6]) + ["Cotton 41S", False]]),
                    ("GST not said", [list(md_m["rows"][0][:6]) + ["Cotton 40S"]]), ("no row given a yarn", [list(md_m["rows"][0][:6]) + ["", False]]))}
        check(tag + "intake_add_dated_rates refuses what Bring in prices refuses, in its words (a yarn not in the master, GST not said, no row given a yarn)",
              all(same_refusal(m, w) for m, w in refused.values()), str({k: (m.get("error"), detail(w)) for k, (m, w) in refused.items() if not same_refusal(m, w)}))
        web("POST", "/api/dated-rates/remove", json={"id": b_web["id"]})
        mp_m, mp_w = call("dated_market_preview"), web("GET", "/api/dated-rates/market").json()
        lm = call("load_market_dated_rates")
        loaded = [e for e in dated()["entries"] if e["source"] == "market history"]
        lw = web("POST", "/api/dated-rates/market", json={}).json()
        check(tag + "load_market_dated_rates loads what dated_market_preview (the page's preview) says it would, entered by \"AI assistant\"; the "
                    "screen's load right after finds nothing left to do",
              mp_m == mp_w and lm["added"] == mp_w["to_load"] >= 1 and len(loaded) == lm["added"] and all(e["entered_by"] == AI for e in loaded)
              and lw["added"] == 0 and lw["unchanged"] == lm["added"], str(lm) + str(lw))
        for e in dated()["entries"]:            # the later checks read Right cost on today's yarn rates
            web("POST", "/api/dated-rates/remove", json={"id": e["id"]})

        # the fabric list: a mill's sheet uploaded, a fabric added, rows removed
        base = {"Brand": "AS", "Fab Code": "AI-1", "YD/NYD": "YD", "Material Type": "100% Cotton", "Warp": 40, "Weft": 40, "EPI": 136, "PPI": 90,
                "Variety": "YDS", "Weave": "2/1 RHT", "F.W.": 145, "Finish": "Normal", "Arvind Ref": "x/1", "Total order qnty": 2255, "Base Price": 164,
                "Std EPI": 122, "Std PPI": 76, "Actual EPI": 136, "Actual PPI": 90, "Diff EPI": 14, "Diff PPI": 14, "EPI Upch": 8.4, "PPI Upch": 12.6,
                "Finish Upch": 0, "Dobby Upch": 0, "Upcharge/Print/Mcount": 0, "Double beam": 0, "Price": 185, "Upcharge for less qnty": 0,
                "Discoun>2000 mts": 0, "Total price with qnty disc/upcharge": 185, "Ex mill price": 185, "C2FO @2.84%": 190.254}
        hi = dict(base, **{"Fab Code": "AI-2", "Price": 240, "Ex mill price": 240, "Total price with qnty disc/upcharge": 240, "Total order qnty": 5000})
        sheet_x = xlsx(pd.DataFrame([base, hi], columns=mill_sheet.COLUMNS))
        live = lambda: {r["id"]: r for r in web("POST", "/api/list", json={}).json()["rows"]}
        who = lambda: {r[0]: (r[1], r[2]) for r in sql("SELECT legacy_id, added_by, removed_by FROM quote")}
        strip = lambda rows: sorted((json.dumps({k: v for k, v in r.items() if k not in ("id", "added", "upload")}, sort_keys=True) for r in rows))
        ids0 = set(live())
        um = call("upload_to_fabric_list", file_base64=b64(sheet_x), file_name="ai sheet.xlsx")
        rows_ai = [r for i, r in live().items() if i not in ids0]
        again = call("upload_to_fabric_list", file_base64=b64(sheet_x), file_name="ai sheet.xlsx")
        web("POST", "/api/list/remove", json={"ids": [r["id"] for r in rows_ai]})
        uw = upload("/api/list/upload", "ai sheet.xlsx", sheet_x).json()
        rows_web = [r for i, r in live().items() if i not in ids0]
        by = who()
        check(tag + "upload_to_fabric_list: a mill's sheet as base64 gives the same rows, costings and quote alerts as Bulk upload; a row already on the "
                    "list is not added twice; the rows recorded as added by \"AI assistant\", as the screen records the admin",
              um["added"] == uw["added"] == 2 and again["added"] == 0 and again["already_on_the_list"] == 2 and strip(rows_ai) == strip(rows_web)
              and um["read_as"] == uw["kind"] == "mill sheet" and len(um["alerts"]) == len(uw["alerts"]) >= 1
              and all(by[r["id"]] == (AI, "gp@example.com") for r in rows_ai) and all(by[r["id"]] == ("gp@example.com", None) for r in rows_web), str(um)[:300])
        check(tag + "upload_to_fabric_list refuses what the screen refuses, in its words (not Excel; no known headings)",
              same_refusal(call("upload_to_fabric_list", file_base64=b64(b"not excel"), file_name="x.xlsx"), upload("/api/list/upload", "x.xlsx", b"not excel"))
              and same_refusal(call("upload_to_fabric_list", file_base64=b64(xlsx(pd.DataFrame([{"a": 1}]))), file_name="y.xlsx"),
                               upload("/api/list/upload", "y.xlsx", xlsx(pd.DataFrame([{"a": 1}])))))
        ex = dict(masters.EXAMPLE_ROW, **{"Fabric code": "AI-3", "Supplier": "Check Mills", "Quoted price (Rs/m)": 240, "Order quantity (m)": 3000})
        fm_ = call("add_fabric_to_list", choices=ex)
        fw_ = web("POST", "/api/list/add", json=ex).json()
        rows = live()
        rp = call("add_fabric_to_list", choices=dict(ex, **{"Quoted price (Rs/m)": 230}), replaces_key=fm_["key"])
        rows2, by = live(), who()
        rp_id = rp["key"].split("|", 1)[1]
        check(tag + "add_fabric_to_list adds the same row as Cost a fabric's Add to list, and replaces a row as editing it does; recorded as \"AI assistant\"",
              strip([rows[fm_["key"].split("|", 1)[1]]]) == strip([rows[fw_["id"]]]) and rp["replaced"] == fm_["key"] and fm_["key"].split("|", 1)[1] not in rows2
              and rows2[rp_id]["inputs"]["Quoted price (Rs/m)"] == 230 and by[fm_["key"].split("|", 1)[1]] == (AI, AI) and by[rp_id] == (AI, None)
              and by[fw_["id"]] == ("gp@example.com", None), str(rp))
        bad_weave = dict(ex, Weave="Not a weave")
        check(tag + "add_fabric_to_list refuses a fabric the costing refuses, in the screen's words; a field name it does not know is refused, not kept",
              same_refusal(call("add_fabric_to_list", choices=bad_weave), web("POST", "/api/list/add", json=bad_weave))
              and "Unknown field" in call("add_fabric_to_list", choices=dict(ex, Shade="Dark")).get("error", "") and len(live()) == len(rows2))
        rm = call("remove_fabric_list_rows", keys=[rp["key"], "Fabric list|nope"])
        check(tag + "remove_fabric_list_rows removes a row as the screen does, names it, says which key was not on the list; recorded as removed by "
                    "\"AI assistant\"; no rows given is refused in the screen's words",
              rm["removed"] == 1 and rm["rows"] == [{"key": rp["key"], "code": "AI-3", "supplier": "Check Mills"}] and rm["not_on_the_list"] == ["Fabric list|nope"]
              and rp_id not in live() and who()[rp_id] == (AI, AI)
              and same_refusal(call("remove_fabric_list_rows", keys=[]), web("POST", "/api/list/remove", json={"ids": []})), str(rm))

        # mill cost sheets: upload, the drafts applied, rows removed
        cs = pd.read_excel(io.BytesIO(web("GET", "/api/costsheet/template").content), sheet_name="Cost sheet")
        cs.loc[0, "Overhead %"], cs.loc[0, "Mill"] = 6, "Mill A"
        cs2 = cs.copy()
        cs2["Mill"] = "Mill B"
        cs2.loc[0, "Overhead %"] = 8
        csx = xlsx(pd.concat([cs, cs2]), sheet="Cost sheet")
        # a row as the screen shows it, without what differs by the upload itself (its id, time, name, who); the mill's own row likewise
        cut = lambda v: [json.dumps(dict({k: x for k, x in r.items() if k not in ("id", "added", "upload", "by", "row")},
                                         row={k: x for k, x in (r.get("row") or {}).items() if not k.startswith("_")}), sort_keys=True) for r in v["rows"]]
        cum = call("upload_mill_cost_sheet", file_base64=b64(csx), file_name="cost sheets.xlsx")
        vm = web("GET", "/api/costsheet").json()
        cuw = upload("/api/costsheet/upload", "cost sheets.xlsx", csx).json()
        vw, tm = web("GET", "/api/costsheet").json(), call("mill_cost_sheets")
        check(tag + "upload_mill_cost_sheet reads the sheet as Mill cost sheets does (the same rows and drafts; sent again, it takes the place of the "
                    "mill's rows); each row records who brought it in: \"AI assistant\", or the admin on the screen",
              cum["added"] == cuw["added"] == 2 and cuw["replaced"] == 2 and cut(vm) == cut(vw) and vm["drafts"] == vw["drafts"] and vw["drafts"]
              and all(r["by"] == AI for r in vm["rows"]) and all(r["by"] == "gp@example.com" for r in vw["rows"])
              and [r["id"] for r in tm["rows"]] == [r["id"] for r in vw["rows"]] and [(d["id"], d["proposed"]) for d in tm["drafts"]] == [(d["id"], d["proposed"]) for d in vw["drafts"]],
              str(cum))
        check(tag + "upload_mill_cost_sheet refuses what the screen refuses, in its words",
              same_refusal(call("upload_mill_cost_sheet", file_base64=b64(b"nope"), file_name="c.xlsx"), upload("/api/costsheet/upload", "c.xlsx", b"nope"))
              and same_refusal(call("upload_mill_cost_sheet", file_base64=b64(xlsx(pd.DataFrame([{"a": 1}]))), file_name="c.xlsx"),
                               upload("/api/costsheet/upload", "c.xlsx", xlsx(pd.DataFrame([{"a": 1}])))))
        d = vw["drafts"][0]
        t0 = web("GET", f"/api/table/{d['table']}").json()
        ap = call("apply_cost_sheet_drafts", draft_ids=[d["id"]])
        t1, v1 = web("GET", f"/api/table/{d['table']}").json(), versions()
        web("PUT", f"/api/table/{d['table']}", json={"columns": t0["columns"], "rows": t0["rows"]})
        apw = web("POST", "/api/costsheet/apply", json={"ids": [d["id"]]}).json()
        t2, v2 = web("GET", f"/api/table/{d['table']}").json(), versions()
        check(tag + "apply_cost_sheet_drafts writes the ticked draft into the rate master exactly as the screen does (the rate and its Basis), after "
                    "keeping the rate master as it was; recorded as \"AI assistant\"",
              ap["applied"] == apw["applied"] and ap["applied"] and t1 == t2 and t1 != t0 and v1[-1][1] == AI and v1[-1][2].startswith("Mill cost sheet drafts applied")
              and v2[-1][1] == "gp@example.com", str(ap))
        check(tag + "apply_cost_sheet_drafts refuses what the screen refuses, in its words (nothing ticked; a draft no longer there)",
              same_refusal(call("apply_cost_sheet_drafts", draft_ids=[]), web("POST", "/api/costsheet/apply", json={"ids": []}))
              and same_refusal(call("apply_cost_sheet_drafts", draft_ids=["nope"]), web("POST", "/api/costsheet/apply", json={"ids": ["nope"]})))
        web("PUT", f"/api/table/{d['table']}", json={"columns": t0["columns"], "rows": t0["rows"]})
        rmm = call("remove_mill_cost_sheet_rows", ids=[vw["rows"][0]["id"]])
        left_ai = web("GET", "/api/costsheet").json()
        upload("/api/costsheet/upload", "cost sheets.xlsx", csx)
        web("POST", "/api/costsheet/remove", json={"ids": [web("GET", "/api/costsheet").json()["rows"][0]["id"]]})
        left_web = web("GET", "/api/costsheet").json()
        gone = call("remove_mill_cost_sheet_rows", upload=left_web["rows"][0]["upload"])
        check(tag + "remove_mill_cost_sheet_rows removes a row, or a whole upload, as the screen does",
              rmm["removed"] == 1 and cut(left_ai) == cut(left_web) and len(left_ai["rows"]) == 1 and gone["removed"] == 1 and web("GET", "/api/costsheet").json()["rows"] == [])

        # quote alerts seen
        al = web("GET", "/api/alerts").json()
        aid = sorted(al["ids"])[0]
        seen = lambda: {r[0]: r[1] for r in sql("SELECT quote_id, seen_by FROM alert_seen")}
        sm = call("mark_alerts_seen", keys=[f"Fabric list|{aid}"])
        after_ai, by_ai = web("GET", "/api/alerts").json(), seen()
        web("POST", "/api/alerts/seen", json={"ids": [aid], "undo": True})
        web("POST", "/api/alerts/seen", json={"ids": [aid]})
        after_web, by_web = web("GET", "/api/alerts").json(), seen()
        back = call("mark_alerts_seen", keys=[aid], bring_back=True)
        call("mark_alerts_seen", keys=[aid])
        every = call("mark_alerts_seen", bring_all_back=True)
        check(tag + "mark_alerts_seen marks an alert seen for everyone, and brings one or all back, exactly as the screens do; recorded as seen by \"AI assistant\"",
              al["count"] >= 1 and after_ai == after_web and sm["alerts_to_look_at_now"] == al["count"] - 1 and by_ai.get(aid) == AI and by_web.get(aid) == "gp@example.com"
              and back["alerts_to_look_at_now"] == al["count"] and every["marked_seen"] == 0 and web("GET", "/api/alerts").json()["count"] == al["count"], str(sm))

        # a negotiation step removed, whoever recorded it
        key3 = f"Fabric list|{fw_['id']}"
        web("POST", "/api/negotiations/event", json={"key": key3, "kind": "Mill's quote", "price": 240, "date": today, "code": "AI-3", "supplier": "Check Mills"})
        st = call("tracker_steps", key=key3)
        sid = st["steps"][0]["id"]
        rs = call("remove_tracker_step", key=key3, step_id=sid)
        ng = web("GET", "/api/negotiations").json()["items"][key3]
        check(tag + "remove_tracker_step removes a step a person recorded, as an admin can on the Negotiation tab; it is kept in the Log, removed by "
                    "\"AI assistant\"; a step already gone is refused in the screen's words",
              st["steps"][0]["by"] == "gp@example.com" and rs["removed"] is True and rs["removed_step"]["recorded_by"] == "gp@example.com" and ng["events"] == []
              and ng["removed"][-1]["removed_by"] == AI and ng["removed"][-1]["id"] == sid
              and same_refusal(call("remove_tracker_step", key=key3, step_id=sid), web("POST", "/api/negotiations/remove", json={"key": key3, "id": sid})), str(rs)[:200])
        rec = call("record_tracker_step", key=key3, kind="Mill's quote", price_per_m=240, date=today)
        steps = sql("SELECT recorded_by FROM negotiation_step WHERE negotiation_key = %s AND removed_at IS NULL", (key3,))
        check(tag + "A step recorded through the assistant is stored as recorded by \"AI assistant\"", rec.get("recorded") is True and [r[0] for r in steps] == [AI])

        # users and roles
        u0 = web("GET", "/api/users").json()
        ur = call("users_and_roles")
        check(tag + "users_and_roles shows the people, the roles, the assistant's fixed role and the change record as the admin page does",
              ur["people"] == u0["people"] and ur["change_record"] == u0["audit"][:50] and ur["assistant"]["note"] == access.ASSISTANT_NOTE
              and set(ur["roles"]) == set(access.ROLES) and ur["admins_named_in_the_setting"] == ["gp@example.com"])
        pa = call("add_person", email="Asha <asha@example.com>", role="Buyer", name="Asha")
        web("POST", "/api/users/add", json={"email": "bala@example.com", "role": "Buyer", "name": "Bala"})
        people = {p["email"]: p for p in web("GET", "/api/users").json()["people"]}
        like = lambda p: {k: v for k, v in p.items() if k not in ("email", "name", "added_at", "added_by")}
        check(tag + "add_person lets a person in as the admin page does; recorded as added by \"AI assistant\"; the person is let in with that role",
              pa.get("added") == "asha@example.com" and people["asha@example.com"]["added_by"] == AI and people["bala@example.com"]["added_by"] == "gp@example.com"
              and like(people["asha@example.com"]) == like(people["bala@example.com"])
              and c.get("/api/me", headers={"X-MS-CLIENT-PRINCIPAL-NAME": "asha@example.com"}).json()["role"] == "Buyer", str(pa))
        refused = {what: (call("add_person", **args), web("POST", "/api/users/add", json=args)) for what, args in
                   (("not an address", {"email": "asha at example", "role": "Buyer"}), ("an unknown role", {"email": "z@example.com", "role": "Owner"}),
                    ("a person twice", {"email": "ASHA@example.com", "role": "Viewer"}))}
        check(tag + "add_person refuses what the admin page refuses, in its words (not an address, an unknown role, a person twice)",
              all(same_refusal(m, w) for m, w in refused.values()), str({k: (m.get("error"), detail(w)) for k, (m, w) in refused.items() if not same_refusal(m, w)}))
        asha = {"X-MS-CLIENT-PRINCIPAL-NAME": "asha@example.com"}
        call("change_person", email="asha@example.com", role="Viewer")
        web("POST", "/api/users/change", json={"email": "bala@example.com", "role": "Viewer"})
        viewer = c.post("/api/list/remove", json={"ids": ["x"]}, headers=asha).status_code
        call("change_person", email="asha@example.com", name="Asha Rao")
        call("change_person", email="asha@example.com", active=False)
        switched = c.get("/api/meta", headers=asha)
        call("change_person", email="asha@example.com", active=True)
        log = web("GET", "/api/users").json()["audit"]
        mine = [a for a in log if a["subject"] == "asha@example.com"]
        theirs = [a for a in log if a["subject"] == "bala@example.com"]
        check(tag + "change_person changes a role, a name, switches a person off and on, at once, as the admin page does; each change recorded as made by "
                    "\"AI assistant\", with what it was and what it became",
              viewer == 403 and switched.status_code == 403 and "switched off" in switched.json()["detail"] and c.get("/api/meta", headers=asha).status_code == 200
              and [a["action"] for a in reversed(mine)] == ["person added", "role changed", "name changed", "switched off", "switched on"] and all(a["who"] == AI for a in mine)
              and next(a for a in mine if a["action"] == "role changed")["detail"] == next(a for a in theirs if a["action"] == "role changed")["detail"] == {"from": "Buyer", "to": "Viewer"}
              and all(a["who"] == "gp@example.com" for a in theirs), str([(a["action"], a["who"]) for a in mine]))
        call("add_person", email="boss@example.com", role="Admin")
        last = [(call("change_person", email="boss@example.com", role="Buyer"), web("POST", "/api/users/change", json={"email": "boss@example.com", "role": "Buyer"})),
                (call("change_person", email="boss@example.com", active=False), web("POST", "/api/users/change", json={"email": "boss@example.com", "active": False})),
                (call("change_person", email="asha@example.com", role="Viewer"), web("POST", "/api/users/change", json={"email": "asha@example.com", "role": "Viewer"})),
                (call("change_person", email="nobody@example.com", role="Viewer"), web("POST", "/api/users/change", json={"email": "nobody@example.com", "role": "Viewer"}))]
        check(tag + "The last-admin rule holds for the assistant: the last admin in the list is not made something else or switched off; nothing to change, "
                    "or a person not in the list, is refused; each in the admin page's words",
              all(same_refusal(m, w) for m, w in last) and "last admin" in last[0][0]["error"] and "last admin" in last[1][0]["error"],
              str([(m.get("error"), detail(w)) for m, w in last]))
        pm_ = call("change_role_permissions", changes=[{"role": "Viewer", "permission": "page:pilot", "allowed": False}])
        no_pilot = c.get("/api/pilot", headers=asha).status_code
        grid = web("GET", "/api/users").json()["grid"]["Viewer"]["page:pilot"]
        call("change_role_permissions", changes=[{"role": "Viewer", "permission": "page:pilot", "allowed": True}])
        refused = [(call("change_role_permissions", changes=ch), web("POST", "/api/users/permissions", json={"changes": ch})) for ch in
                   ([{"role": "Admin", "permission": "page:pilot", "allowed": False}], [{"role": "Buyer", "permission": "do:manage_users", "allowed": True}], [])]
        check(tag + "change_role_permissions changes what a role may do, at once, as the grid does, and puts it back; Admin's permissions and user admin "
                    "stay as they are, refused in the grid's words",
              pm_["changed"] == [{"role": "Viewer", "permission": "page:pilot", "allowed": False}] and no_pilot == 403 and grid == {"allowed": False, "default": True}
              and c.get("/api/pilot", headers=asha).status_code == 200 and all(same_refusal(m, w) for m, w in refused), str([(m.get("error"), detail(w)) for m, w in refused]))
        log = web("GET", "/api/users").json()["audit"]
        check(tag + "users_and_roles reads back the whole change record as the admin page shows it, the assistant's changes made by \"AI assistant\"",
              call("users_and_roles", record_limit=300)["change_record"] == log and {a["who"] for a in log} == {AI, "gp@example.com"}
              and sum(1 for a in log if a["who"] == AI) == 8)          # Asha added, her role, name, off, on; boss added; a permission off and on
        os.environ.pop("RIGHTPRICE_ADMINS")
        off = [(call("add_person", email="z@example.com", role="Buyer"), web("POST", "/api/users/add", json={"email": "z@example.com", "role": "Buyer"})),
               (call("users_and_roles"), web("GET", "/api/users"))]
        os.environ["RIGHTPRICE_ADMINS"] = "gp@example.com"
        check(tag + "With permissions off the assistant changes no one and reads no one, refused in the admin page's words",
              all(same_refusal(m, w) for m, w in off), str([(m.get("error"), detail(w)) for m, w in off]))

        # a draft to a mill, the suppliers, the list and the store: once Right cost's verdicts are worked out, as the screens read them
        for _ in range(600):
            if web("GET", "/api/costs").json().get("ready"):
                break
            time.sleep(0.5)
        drafts = [(call("draft_message_to_mill", mill="Check Mills", ask="breakup"), web("POST", "/api/draft", json={"scope": {"type": "supplier", "mill": "Check Mills"}, "ask": "breakup"})),
                  (call("draft_message_to_mill", keys=[key3], writer="GP", contact="Ravi"),
                   web("POST", "/api/draft", json={"scope": {"type": "rows", "keys": [key3]}, "writer": "GP", "contact": "Ravi"}))]
        nothing = (call("draft_message_to_mill"), web("POST", "/api/draft", json={"scope": {}}))
        check(tag + "draft_message_to_mill gives the draft the screen gives (for a mill, and for chosen fabrics), sending and keeping nothing; asked about "
                    "nothing it is refused in the screen's words",
              all(w.status_code == 200 and m == w.json() for m, w in drafts) and drafts[0][0]["source"] == "template" and same_refusal(*nothing),
              str([(str(m)[:120], w.status_code) for m, w in drafts]))
        flm = call("fabric_list", limit=1000)
        check(tag + "list_suppliers, fabric_list and store_status read what Right cost's Suppliers tab, Bulk upload and /api/store read",
              call("list_suppliers") == web("GET", "/api/suppliers").json() and [r["key"] for r in flm["rows"]] == [f"Fabric list|{r['id']}" for r in web("POST", "/api/list", json={}).json()["rows"]]
              and call("fabric_list", search="AI-2")["found"] == 1 and call("store_status") == web("GET", "/api/store").json()
              and call("store_status")["rate_master_in_use"]["by"] == "gp@example.com")
    for k in ("RIGHTPRICE_MCP_TOKEN", "RIGHTPRICE_ADMINS"):
        os.environ.pop(k, None)
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


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
    if task == "access":
        return access_checks()
    if task == "assistant":
        return assistant_checks()
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
    # stage 3: users, roles and permissions, on each store, each on a database of its own
    access_runs = [("files", None), ("sqlite", sqlite_url("access.db"))] + ([("postgres", pg.new())] if not pg.why else [])
    procs += [(f"{kind}, users and roles", _run(kind, "access", url=url)) for kind, url in access_runs]
    # GP's decision of 27 Nov 2026: the AI assistant does what an Admin can, each tool set beside its web route, on each database
    assistant_runs = [("sqlite", sqlite_url("assistant.db"))] + ([("postgres", pg.new())] if not pg.why else [])
    procs += [(f"{kind}, the AI assistant as an admin", _run(kind, "assistant", url=url)) for kind, url in assistant_runs]
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
