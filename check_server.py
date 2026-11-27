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
        check("The old Right cost address leads to its page in the shell, keeping any '#' part the browser carries (stage 2: /rightcost#group/Fab-0001)",
              old.status_code == 307 and old.headers["location"] == "/?from=rightcost" and 'get("from") === "rightcost"' in c.get("/rightcost.js").text)
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
    fields = lambda sig: fab_groups.signature_of(specs[by_sig[sig][0]])[0]
    a = by_sig[sigs[0]]
    b = by_sig[next(x for x in sigs[1:] if fab_groups.differences(fields(sigs[0]), fields(x)))]      # another cloth, not only another width or finish
    incomplete = next(code for code in sorted(specs) if "incomplete" in (fab_groups.signature_of(specs[code])[2] or ""))
    return a[0], a[1], a[2], b[0], incomplete


def _stage2_file(rows, saved=None):
    """A purchase-order file in the SAP export's shape, from made-up rows (each a dict over the export's columns); with
    `saved`, the workbook says it was saved then (as SAP's export does)."""
    import zipfile
    import pandas as pd
    cols = ["Purchasing Document", "Plant", "Document Date", "Item", "Material", "Short Text", "Purchasing Doc. Type", "Order Quantity",
            "Order Unit", "Net Price", "Name of Supplier", "Currency", "Deletion Indicator"]
    buf = io.BytesIO()
    pd.DataFrame([{k: r.get(k) for k in cols} for r in rows], columns=cols).to_excel(buf, index=False)
    if saved is None:
        return buf.getvalue()
    src, out = zipfile.ZipFile(io.BytesIO(buf.getvalue())), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(modified|created)[^>]*>)[^<]*(</dcterms:)", rb"\g<1>" + saved.encode() + rb"Z\g<3>", data)
            z.writestr(item, data)
    return out.getvalue()


def stage2_checks(c, check):
    """Purchase files read in the background; one line per order line, the newest file's figures winning; ZLOI lines in no
    figure anywhere; mills, fabrics and Fab groups (the width rule, regrouping, ranges on separate orders); the price popup;
    the Fab group page; the merge; Right cost's purchase-order rows worked out again from what was bought. On the files
    store: a plain refusal, and everything else as before."""
    import statistics
    import pandas as pd
    import store
    import data_purchases as dp
    from rules import costing, fab_groups, purchases
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
    # the rules on their own: counts written many ways, widths, ranges on separate orders, dates
    same = lambda a, b: fab_groups.tidy_count(a) == fab_groups.tidy_count(b)
    check("Stage 2: a count written several ways is one (40sspandex/40sspx, 20spx/20sspx, 36nm/36snm, 2/50p/v / 2/50pv, 25/1+40d / 25s/1+40d, "
          "50/1c / 50/1cmd, 24 Ams / 24AMS, 2/80 / 80/2); combed and plain stay apart; finishes written differently stay apart",
          all(same(a, b) for a, b in (("40sspandex", "40sspx"), ("20spx", "20sspx"), ("36nm", "36snm"), ("2/50p/v", "2/50pv"), ("25/1+40d", "25s/1+40d"),
                                      ("50/1c", "50/1cmd"), ("24 Ams", "24AMS"), ("2/80", "80/2"), ("40", "40/1")))
          and not same("40", "cm40") and not same("36nm", "36") and fab_groups.tidy_count("1") is None
          and fab_groups.tidy_finish("F - Normal Soft") != fab_groups.tidy_finish("F - Soft Finish") and fab_groups.tidy_finish("F - Regular") != fab_groups.tidy_finish("F - Normal Soft"))
    a1, a2, a3, b1, inc = _stage2_codes()
    specs = purchases.plm_specs()
    w = lambda width, uom: fab_groups.signature_of(dict(specs[a1], article_cust_finishedwidth=width, article_cust_finishedwidth_uom=uom))[1]
    check("Stage 2: widths within half an inch are one group, on the nearest whole inch whatever the order (57 in and 145 cm join; 57 in and 58 in do not)",
          w("57", "in") == w("145", "cm") == w("57.4", "in") and w("57", "in") != w("58", "in") and w("57.5", "in") == w("58", "in"))
    rng5 = fab_groups.price_range([(100 + i, "one order") for i in range(6)])
    rng5b = fab_groups.price_range([(100 + i, f"order {i}") for i in range(5)])
    check("Stage 2: a usual range needs purchases on at least 5 separate orders, not 5 lines", rng5["enough"] is False and rng5["orders"] == 1 and rng5b["enough"] is True)
    dates = [purchases._date(x) for x in ("2026-04-03", "05.09.2026", "03/04/2026", "13/04/2026", 46000.0)]
    check("Stage 2: a date written as text is read as year-month-day; SAP's day.month.year as such; one that could be read two ways is refused with why",
          dates[0] == ("2026-04-03", None) and dates[1] == ("2026-09-05", None) and dates[2][0] is None and "could be 3 April or 4 March" in dates[2][1]
          and dates[3] == ("2026-04-13", None) and dates[4][0] == "2025-12-09", str(dates))
    if kind == "files":
        answers = [c.get("/api/purchases/uploads"), c.get("/api/groups"), c.get("/api/groups/Fab-0001"), c.get("/api/purchases/history", params={"code": "X"}),
                   c.post("/api/purchases/load-shipped"), c.post("/api/groups/merge", json={"code": "Fab-0001", "into": "Fab-0002"})]
        check("Stage 2 on the files store: the purchase history says plainly that it needs the database (503), nothing breaks",
              all(r.status_code == 503 and "kept in the database" in r.json()["detail"] for r in answers)
              and c.get("/api/purchases/status").json()["available"] is False)
    _stage2_right_cost(c, check, kind, "before any purchase file is loaded" if kind != "files" else "on the files")
    if kind == "files":
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
    arv, arv2 = "1200094    ARVIND LTD", "1200094    Arvind Limited"
    raj, raj2, nsl = "1208655    RAJAPALAYAM MILLS LIMITE", "1208655    Rajapalayam Mills Limited", "1203290    NSL TEXTILES LIMITED"
    row = lambda po, item, code, day, sup, qty, price, **kw: dict({"Purchasing Document": float(po), "Item": float(item), "Material": code, "Plant": "F007",
                                                               "Document Date": pd.Timestamp(day) if re.fullmatch(r"\d{4}-\d\d-\d\d", day) else day,
                                                               "Name of Supplier": sup, "Order Quantity": qty, "Net Price": price,
                                                               "Purchasing Doc. Type": "BO", "Currency": "INR", "Order Unit": "M", "Short Text": "made up for the checks"}, **kw)
    rows = [row(9900000001, 10, a1, "2026-08-03", arv, 1000, 100), row(9900000002, 10, a2, "2026-08-10", arv2, 1200, 550, **{"Purchasing Doc. Type": "ZLOI"}),
            row(9900000003, 10, a1, "2026-09-01", raj, 800, 102), row(9900000003, 20, a2, "2026-09-01", raj2, 900, 103, **{"Purchasing Doc. Type": "BF"}),
            row(9900000004, 10, a1, "2026-10-05", arv, 2000, 140), row(9900000013, 10, a2, "2026-10-10", arv2, 700, 101),
            row(9900000014, 10, a1, "2026-10-20", raj, 600, 104),
            row(9900000015, 10, a1, "x", arv, 500, 101, **{"Document Date": "2026-04-03"}),        # a date written as text: 3 April, the earliest line
            row(9900000005, 10, b1, "2026-08-01", nsl, 3000, 150), row(9900000016, 10, b1, "x", nsl, 1000, 151, **{"Document Date": "05.09.2026"}),
            row(9900000006, 10, inc, "2026-08-05", nsl, 500, 90), row(9900000007, 10, "ZZCHECK001", "2026-08-06", nsl, 600, 95),
            # left out, each for its own reason
            row(9900000008, 10, a1, "2026-08-07", arv, 100, 100, **{"Deletion Indicator": "L"}), row(9900000009, 10, a1, "2026-08-07", arv, 100, 100, **{"Purchasing Doc. Type": "BA"}),
            row(9900000010, 10, a1, "2026-08-07", arv, 100, 1.2, Currency="USD"), row(9900000011, 10, a1, "2026-08-07", arv, 100, 100, **{"Order Unit": "KG"}),
            row(9900000012, 10, a1, "2026-08-07", arv, 100, 0), row(9900000001, 10, a1, "2026-08-03", arv, 1000, 100),
            row(9900000017, 10, a1, "x", arv, 100, 100, **{"Document Date": "03/04/2026"}),
            {"Order Quantity": 9999, "Order Unit": "M"}]                               # a total line at the foot, as SAP writes it
    data = _stage2_file(rows, saved="2026-11-20T10:00:00")
    bad = c.post("/api/purchases/upload", files={"file": ("orders.csv", io.BytesIO(b"a,b\n1,2\n"))})
    big = c.post("/api/purchases/upload", files={"file": ("big.xlsx", io.BytesIO(b"x" * (purchases.MAX_BYTES + 1)))})
    check(f"{k} a file that is not an Excel workbook, or is larger than 40 MB, is refused at once (the large one unread)",
          bad.status_code == 400 and ".xlsx" in bad.json()["detail"] and big.status_code == 413 and "40 MB" in big.json()["detail"])
    up = c.post("/api/purchases/upload", files={"file": ("purchase orders.xlsx", io.BytesIO(data))}).json()
    check(f"{k} an upload is answered at once and queued for the background", up.get("status") == "queued" and isinstance(up.get("id"), int), str(up))
    u = wait(up["id"])
    det = c.get(f"/api/purchases/uploads/{up['id']}").json()
    why = {s["kind"] for s in det["skipped"]}
    check(f"{k} the file is read in the background: done, with its counts and its date", u["status"] == "done" and u["rows_total"] == len(rows) and u["rows_loaded"] == 12
          and u["rows_new"] == 12 and u["rows_outliers"] == 1 and u["rows_skipped"] == 8 and u["fabrics_new"] == 5 and u["groups_new"] == 2 and u["mills_new"] == 3
          and u["file_date"] == "2026-11-20T10:00:00" and u["file_date_from"] == "the date the workbook was saved",
          str({x: u[x] for x in u if x.startswith("rows") or x.endswith("new") or x.startswith("file")}))
    check(f"{k} the rows left out say which and why (deleted, not bulk, not rupees, not metres, no price, repeated, a total line, a date that reads two ways)",
          why == {"Deleted or blocked in SAP", "Not a bulk order", "Not in rupees", "Not per metre", "No price", "Repeated in this file", "No order number", "Date not read"}
          and any(s["why"].startswith("The same order line as row 2") for s in det["skipped"]) and any("could be 3 April or 4 March" in (s["why"] or "") for s in det["skipped"]),
          str(det["skipped"])[:400])
    xl = c.get(f"/api/purchases/skipped/{up['id']}")
    check(f"{k} every row left out can be downloaded", xl.status_code == 200 and len(pd.read_excel(io.BytesIO(xl.content))) == 8)
    st = store.get()
    with st.tx() as cur:
        mills = cur.all("SELECT m.key, count(a.spelling) FROM mill m JOIN mill_alias a ON a.mill_id = m.id GROUP BY m.key ORDER BY m.key")
    check(f"{k} one record per mill, every spelling kept (Arvind Ltd and Arvind Limited; a name cut at 24 characters and its full name)",
          mills == [("arvind", 2), ("nsl textile", 1), ("rajapalayam", 2)], str(mills))
    hist = c.get("/api/purchases/history", params={"code": a1}).json()
    h2 = c.get("/api/purchases/history", params={"code": a2}).json()
    gA, gB = hist["group"]["code"], c.get("/api/purchases/history", params={"code": b1}).json()["group"]["code"]
    check(f"{k} Fab-0001 onward in order of first appearance (the earliest line, a date written as text); two codes of one construction are one group, across mills",
          gA == "Fab-0001" and gB == "Fab-0002" and h2["group"]["code"] == gA and {m["name"] for m in hist["group"]["mills"]} == {"Arvind Limited", "Rajapalayam Mills Limited"}, f"{gA} {gB}")
    ng1, ng2 = (c.get("/api/purchases/history", params={"code": x}).json() for x in (inc, "ZZCHECK001"))
    check(f"{k} a code whose specification is incomplete, or missing, is not grouped and says why (never guessed)",
          ng1["group"] is None and "incomplete" in ng1["not_grouped"] and ng2["group"] is None and ng2["not_grouped"] == "No PLM specification for this code"
          and ng2["should"] is None)
    po_row = next(r for r in c.get("/api/costs").json()["rows"] if r["source"] == "Purchase orders" and r["code"] == a1)   # the pilot's choices
    loose = lambda d: {x: v for x, v in d.items() if x not in ("Quoted price (Rs/m)", "Supplier", "Description", "Fabric code", "Order quantity (m)",
                                                                  "Rate card quantity", "Order size")}
    with st.tx() as cur:
        stored = {code: json.loads(ch) for code, ch in cur.all("SELECT code, choices FROM fabric WHERE code IN (%s, %s)", (a1, a2))}
    check(f"{k} price over time for a code: each purchase with date, mill, metres and price, and its should-cost on today's rates",
          [(x["date"], x["mill"], x["metres"], x["price"]) for x in hist["lines"]] == [("2026-04-03", "Arvind Limited", 500.0, 101.0), ("2026-08-03", "Arvind Limited", 1000.0, 100.0),
                                                                                    ("2026-09-01", "Rajapalayam Mills Limited", 800.0, 102.0), ("2026-10-05", "Arvind Limited", 2000.0, 140.0),
                                                                                    ("2026-10-20", "Rajapalayam Mills Limited", 600.0, 104.0)]
          and hist["should"] == round(c.post("/api/cost", json=stored[a1]).json()["total_per_m"], 2) and loose(stored[a1]) == loose(po_row["choices"]), str(hist["lines"])[:300])
    page = c.get(f"/api/groups/{gA}").json()
    prices = sorted([101, 100, 102, 103, 140, 101, 104])
    med = statistics.median(prices)
    q = statistics.quantiles(prices, n=4, method="inclusive")
    lo, hi = costing.usual_range((q[0] / med - 1) * 100, (q[2] / med - 1) * 100)
    upper = round(med * (1 + hi / 100), 2)
    zl = [(o["code"], o["price"], o["metres"]) for o in page["outliers"]]
    check(f"{k} ZLOI lines are in no figure: not in the price paid, the metres, the median, the range or 'above the range', nor in a fabric's quantity band; "
          "they are listed apart beside the fabric and beside the mill",
          [(x["code"], x["price"]) for x in h2["lines"]] == [(a2, 103.0), (a2, 101.0)] and [(o["price"], o["metres"]) for o in h2["outliers"]] == [(550.0, 1200.0)]
          and zl == [(a2, 550.0, 1200.0)] and 550 not in [x["price"] for x in page["lines"]] and page["purchases"] == 7 and page["metres"] == 6500
          and stored[a2].get("Order quantity (m)") == 1600 and next(m for m in page["mills"] if m["key"] == "arvind")["outliers"][0]["price"] == 550
          and next(g for g in c.get("/api/groups").json()["groups"] if g["code"] == gA)["median"] == med, str(page["outliers"])[:200])
    check(f"{k} the group page: purchases, orders, metres, mills, median price, and the usual range by the brief's own rule (5% to 10% round the median) on 6 separate orders",
          page["range"]["orders"] == 6 and len(page["mills"]) == 2 and page["range"]["median"] == 102 and page["range"]["enough"]
          and (page["range"]["lo"], page["range"]["hi"]) == (lo, hi) == (-5.0, 5.0) and page["range"]["upper"] == upper == 107.1
          and page["should"]["median"] is not None, str(page["range"]))
    check(f"{k} priced well above the group: only the purchase above the top of the usual range, with the rupees above it",
          [(x["code"], x["price"], x["above"], x["above_rs"]) for x in page["above"]] == [(a1, 140.0, 32.9, 65800.0)] and page["above_rs"] == 65800, str(page["above"]))
    pb = c.get("/api/groups/fab-0002").json()
    check(f"{k} a group with purchases on too few separate orders says so, and calls nothing high", pb["code"] == "Fab-0002" and pb["range"]["enough"] is False
          and pb["range"]["orders"] == 2 and pb["above"] == [] and pb["min_for_range"] == 5 and [x["date"] for x in pb["lines"]] == ["2026-08-01", "2026-09-05"])
    # the newest file wins, whatever order the files come in
    u2 = wait(c.post("/api/purchases/upload", files={"file": ("purchase orders again.xlsx", io.BytesIO(data))}).json()["id"])
    n_lines = c.get("/api/purchases/status").json()["counts"]
    check(f"{k} the same file uploaded twice: each order line is one line", u2["status"] == "done" and u2["rows_new"] == 0 and u2["rows_same"] == 12
          and n_lines["lines"] == 11 and n_lines["outliers"] == 1 and u2["fabrics_new"] == 0 and u2["groups_new"] == 0, str(u2))
    rows2 = [dict(r) for r in rows]
    rows2[5]["Net Price"] = 121.2                       # 9900000013/10: the price 20% up
    rows2[6]["Deletion Indicator"] = "L"                # 9900000014/10: deleted in SAP
    rows2[10]["Currency"] = "USD"                       # 9900000006/10: now in dollars
    del rows2[3]                                        # 9900000003/20: dropped; the rest of its order (item 10) is still there
    newer = _stage2_file(rows2, saved="2026-11-25T09:00:00")
    u3 = wait(c.post("/api/purchases/upload", files={"file": ("purchase orders corrected.xlsx", io.BytesIO(newer))}).json()["id"])
    look = lambda: {(x["po"], x["item"]): x["price"] for code in (a1, a2, inc) for x in c.get("/api/purchases/history", params={"code": code}).json()["lines"]}
    after3, counts3 = look(), c.get("/api/purchases/status").json()["counts"]
    check(f"{k} a newer file: a changed price is taken; lines it shows deleted, or in dollars, and the line it no longer has (the rest of its order there) are removed",
          u3["rows_changed"] == 1 and u3["rows_removed"] == 2 and u3["rows_dropped"] == 1 and after3[("9900000013", "10")] == 121.2
          and ("9900000014", "10") not in after3 and ("9900000006", "10") not in after3 and ("9900000003", "20") not in after3 and counts3["lines"] == 8,
          str({x: u3[x] for x in u3 if x.startswith("rows")}))
    u4 = wait(c.post("/api/purchases/upload", files={"file": ("purchase orders, the old one again.xlsx", io.BytesIO(data))}).json()["id"])
    check(f"{k} the older file uploaded after it changes nothing: no old price back, no removed line counted again",
          u4["rows_older"] == 12 and u4["rows_changed"] == 0 and u4["rows_removed"] == 0 and look() == after3
          and c.get("/api/purchases/status").json()["counts"] == counts3, str({x: u4[x] for x in u4 if x.startswith("rows")}))
    # two uploads read at once, one of them by another server process: the newer file wins either way
    late_rows = [row(9900000020, 10, b1, "2026-11-01", nsl, 1000, 160)]
    old_f, new_f = _stage2_file(late_rows, saved="2026-11-21T00:00:00"), _stage2_file([dict(late_rows[0], **{"Net Price": 170})], saved="2026-11-26T00:00:00")
    for _ in range(200):                                # the worker of this process idle, so the other process reads one of the two
        if purchases._jobs["thread"] is None:
            break
        time.sleep(0.1)
    with st.tx(write=dp.STATUS) as cur:
        u_new = dp.add_upload(cur, "purchase_orders", "newer.xlsx", "check", new_f, "x", store._now())
        u_old = dp.add_upload(cur, "purchase_orders", "older.xlsx", "check", old_f, "y", store._now())
    env = dict(os.environ)
    other = subprocess.Popen([sys.executable, "-c", f"from rules import purchases; purchases.run({u_new})"], cwd=HERE, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    purchases.run(u_old)
    out_, err_ = other.communicate(timeout=300)
    both = [wait(u_new), wait(u_old)]
    late = {(x["po"], x["item"]): x["price"] for x in c.get("/api/purchases/history", params={"code": b1}).json()["lines"]}
    check(f"{k} two uploads read at once in two server processes: each read once, the newer file's figures kept", other.returncode == 0
          and all(x["status"] == "done" for x in both) and late.get(("9900000020", "10")) == 170, f"{err_[-300:]} {late}")
    # a restart in the middle of an upload; uploads waiting at a restart
    with st.tx(write=dp.STATUS) as cur:
        u_dead = dp.add_upload(cur, "purchase_orders", "half read.xlsx", "check", data, "z", store._now())
        cur.run("UPDATE upload SET status = 'working', runner = %s, alive_at = %s WHERE id = %s", (f"{purchases.socket.gethostname()}:999999", store._now(), u_dead))
        u_wait = dp.add_upload(cur, "purchase_orders", "waiting.xlsx", "check", data, "z", store._now())
    purchases.resume()
    again = [wait(u_dead), wait(u_wait)]
    check(f"{k} an upload a restart left half-read is read again from the start at once, and uploads left waiting are picked up",
          all(x["status"] == "done" for x in again) and c.get("/api/purchases/status").json()["counts"]["lines"] == counts3["lines"] + 1, str(again)[:300])
    bad2 = wait(c.post("/api/purchases/upload", files={"file": ("not orders.xlsx", io.BytesIO(b"PK, but not a workbook"))}).json()["id"])
    buf = io.BytesIO()
    pd.DataFrame([{"Fabric": "x", "Price": 1}]).to_excel(buf, index=False)
    bad3 = wait(c.post("/api/purchases/upload", files={"file": ("other sheet.xlsx", io.BytesIO(buf.getvalue()))}).json()["id"])
    check(f"{k} a file that cannot be read, or is not a purchase-order export, fails and says why", bad2["status"] == "failed" and "could not be read" in bad2["error"]
          and bad3["status"] == "failed" and "Purchasing Document" in bad3["error"], f"{bad2['error']} | {bad3['error']}")
    # regrouping: a specification completed, corrected and corrected back; the way the fields are tidied changed
    specs["ZZCHECK001"] = dict(specs[a3])               # the PLM list now has ZZCHECK001, as a3's construction
    specs[b1], b1_spec = dict(specs[a3]), specs[b1]     # and b1's specification corrected to it too
    try:
        wait(c.post("/api/purchases/upload", files={"file": ("purchase orders corrected again.xlsx", io.BytesIO(newer))}).json()["id"])
        zz, moved_b1 = (c.get("/api/purchases/history", params={"code": x}).json() for x in ("ZZCHECK001", b1))
        pa, pb2 = c.get(f"/api/groups/{gA}").json(), c.get(f"/api/groups/{gB}").json()
        specs[b1] = b1_spec                             # corrected back
        wait(c.post("/api/purchases/upload", files={"file": ("purchase orders corrected, again.xlsx", io.BytesIO(newer))}).json()["id"])
    finally:
        specs.pop("ZZCHECK001", None)
        specs[b1] = b1_spec
    back = c.get("/api/purchases/history", params={"code": b1}).json()
    check(f"{k} a specification completed or corrected regroups its code at the next upload, and both group pages say so",
          zz["group"]["code"] == gA and moved_b1["group"]["code"] == gA and {m["code"] for m in pa["moved_in"]} == {"ZZCHECK001", b1}
          and [m["code"] for m in pb2["moved_out"]] == [b1] and "is now complete" in next(m["why"] for m in pa["moved_in"] if m["code"] == "ZZCHECK001"),
          f"{zz.get('group')} {moved_b1.get('group')} {pa['moved_in']} {pb2['moved_out']}")
    check(f"{k} corrected back, the code returns to its group", back["group"]["code"] == gB, str(back.get("group")))
    with st.tx(write=dp.KIND) as cur:                  # as if the fields of Fab-0002 had been tidied another way when it was made
        cur.run("UPDATE fab_group SET signature = 'an older way of tidying' WHERE code = %s", (gB,))
        cur.run("UPDATE fabric SET signature = 'an older way of tidying' WHERE fab_group_id = (SELECT id FROM fab_group WHERE code = %s)", (gB,))
        n_groups = cur.one("SELECT count(*) FROM fab_group")[0]
    wait(c.post("/api/purchases/upload", files={"file": ("purchase orders corrected, once more.xlsx", io.BytesIO(newer))}).json()["id"])
    back = c.get("/api/purchases/history", params={"code": b1}).json()
    with st.tx() as cur:
        sig_b = cur.one("SELECT signature FROM fab_group WHERE code = %s", (gB,))[0]
        n_groups2 = cur.one("SELECT count(*) FROM fab_group")[0]
    check(f"{k} a change in how the fields are tidied keeps every group's code: the group takes the new signature, no new group is made",
          back["group"]["code"] == gB and sig_b == fab_groups.signature_of(b1_spec)[1] and n_groups2 == n_groups, f"{back.get('group')} {sig_b} {n_groups} {n_groups2}")
    # the merge
    refusals = [c.post("/api/groups/merge", json={"code": gA, "into": gA}).status_code, c.post("/api/groups/merge", json={"code": "Fab-9999", "into": gA}).status_code]
    before_m = c.get(f"/api/groups/{gA}").json()["purchases"] + c.get(f"/api/groups/{gB}").json()["purchases"]
    first = c.post("/api/groups/merge", json={"code": gB, "into": gA}).json()
    unmerged = c.get(f"/api/groups/{gB}").json()["code"] == gB
    m = c.post("/api/groups/merge", json={"code": gB, "into": gA, "confirm": True})
    again = c.post("/api/groups/merge", json={"code": gB, "into": gA, "confirm": True}).status_code
    pbm, listing = c.get(f"/api/groups/{gB}").json(), c.get("/api/groups").json()
    check(f"{k} an admin merge of groups that differ in more than width or finish waits for a second yes; then the merged group's purchases count in the other, its code kept",
          first.get("needs_confirm") is True and first["differences"] and unmerged and m.status_code == 200 and refusals == [400, 404] and again == 409
          and pbm["code"] == gA and pbm["asked"]["code"] == gB and pbm["purchases"] == before_m
          and [x["code"] for x in listing["groups"]] == [gA] and listing["merged"][0]["code"] == gB and listing["merged"][0]["into"] == gA, str(first)[:300])
    check(f"{k} undoing a merge", c.post("/api/groups/unmerge", json={"code": gB}).status_code == 200 and c.get(f"/api/groups/{gB}").json()["code"] == gB
          and c.post("/api/groups/unmerge", json={"code": gB}).status_code == 409)
    c.post("/api/groups/merge", json={"code": gB, "into": gA, "confirm": True})
    # the real purchase file that came with the code, loaded through the app
    counts_before = c.get("/api/purchases/status").json()["counts"]
    t0 = time.time()
    real = wait(c.post("/api/purchases/load-shipped").json()["id"], limit=600)
    took = time.time() - t0
    import pilot
    po = pd.read_excel(os.path.join(HERE, "inputs", "Fabric _ 3Months_4746.xlsx"))
    bulk = po[po["Purchasing Doc. Type"].isin(pilot.BULK_TYPES) & (po["Net Price"] > 0) & po["Deletion Indicator"].isna()
              & (po["Currency"] == "INR") & (po["Order Unit"] == "M")]
    counts = c.get("/api/purchases/status").json()["counts"]
    zloi = int((bulk["Purchasing Doc. Type"] == "ZLOI").sum())
    check(f"{k} the purchase file that came with the code loads through the app ({took:.0f} s): the pilot's own bulk lines, every material code once, "
          f"its {zloi} ZLOI lines kept apart; its date is the one SAP gave it", real["status"] == "done" and real["rows_total"] == len(po) and real["rows_loaded"] == len(bulk) == 6265
          and real["rows_new"] == 6265 and real["rows_outliers"] == zloi == 1377 and real["file_date"] == "2026-11-23T05:48:59"
          and counts["lines"] == counts_before["lines"] + 6265 - zloi and counts["outliers"] == counts_before["outliers"] + zloi
          and counts["fabrics"] == len(set(bulk["Material"].astype(str).str.strip()) | {a1, a2, b1, inc, "ZZCHECK001"}), str({x: real[x] for x in real if x.startswith(("rows", "file"))}))
    fab = pd.read_excel(os.path.join(HERE, "pilot", "Pilot_Results.xlsx"), sheet_name="Fabrics")
    with st.tx() as cur:
        got = {code: json.loads(ch) for code, ch in cur.all("SELECT code, choices FROM fabric WHERE choices IS NOT NULL")}
        new_codes = sorted(code for (code,) in cur.all("SELECT code FROM fab_group WHERE upload_id = %s", (real["id"],)))
        met = {code: q for code, q in cur.all("SELECT f.code, sum(l.qty_m) FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id WHERE l.removed_upload_id IS NULL "
                                              "AND l.doc_type <> 'ZLOI' GROUP BY f.code")}
    m_ = rules_common.get_masters()
    keys = ["Route", "Weave", "Finish", "Warp yarn", "Weft yarn", "EPI", "PPI", "Finished width (in)"]
    mine = {a1, a2, a3, b1}
    got.pop("ZZCHECK001", None)                         # made up, with a3's specification
    same_value = lambda x, y: (float(x) == float(y)) if isinstance(y, (int, float)) and x is not None else str(x) == str(y)
    differ = [r["Fabric code"] for r in fab.to_dict("records") if not all(same_value(got.get(r["Fabric code"], {}).get(x), r[x]) for x in keys)]
    wd = [r["Fabric code"] for r in fab.to_dict("records") if r["Route"] == "Yarn Dyed" and got.get(r["Fabric code"], {}).get("Weft (yarn dyed)") != r["Weft (yarn dyed)"]]
    bands = [r["Fabric code"] for r in fab.to_dict("records") if r["Fabric code"] not in mine
             and (got.get(r["Fabric code"], {}).get("Rate card quantity"), got.get(r["Fabric code"], {}).get("Order size")) != purchases.quantity_terms(r["Route"], met.get(r["Fabric code"]), m_)]
    check(f"{k} every fabric the pilot costed has the pilot's costing choices here, by pilot.py's own functions; its quantity band and order size from its metres, ZLOI left out ({len(fab)} fabrics)",
          not differ and not wd and not bands and len([x for x in got if x in set(fab["Fabric code"])]) == len(fab) and len(got) == len(fab), f"{differ[:5]} {wd[:5]} {bands[:5]} {len(got)}")
    check(f"{k} new Fab groups go on from the last code ever given: a merged code is never handed out again",
          new_codes and new_codes[0] == "Fab-0003" and gB not in new_codes, str(new_codes[:3]))
    _stage2_right_cost(c, check, kind, "after the purchase file is loaded", popup=True)
    again = wait(c.post("/api/purchases/load-shipped").json()["id"], limit=600)
    check(f"{k} loading the same purchase file again changes nothing", again["rows_new"] == 0 and again["rows_same"] == 6265 and again["groups_new"] == 0
          and c.get("/api/purchases/status").json()["counts"] == counts)
    big_g = max(c.get("/api/groups").json()["groups"], key=lambda g: g["purchases"])
    gp = c.get(f"/api/groups/{big_g['code']}").json()
    r_ = gp["range"]
    ps = sorted(x["price"] for x in gp["lines"])
    q2 = statistics.quantiles(ps, n=4, method="inclusive")
    exp = costing.usual_range((q2[0] / statistics.median(ps) - 1) * 100, (q2[2] / statistics.median(ps) - 1) * 100)
    check(f"{k} the busiest real group ({big_g['code']}, {gp['purchases']} purchases on {r_['orders']} orders, {len(gp['mills'])} mills): range by the brief's rule; purchases above it listed",
          (r_["lo"], r_["hi"]) == exp and all(x["price"] > r_["upper"] for x in gp["above"]) and all(x["type"] != "ZLOI" for x in gp["lines"])
          and len(gp["above"]) == sum(1 for x in gp["lines"] if round(x["price"], 2) > r_["upper"]) and gp["purchases"] == len(gp["lines"]) == big_g["purchases"])
    live = {g["code"] for g in c.get("/api/groups").json()["groups"]}
    with st.tx() as cur:
        groups = [g for g in dp.groups(cur).values() if g["code"] in live]
    buckets = {}
    for g in groups:
        buckets.setdefault(tuple(str(g[x]).lower() for x in fab_groups.FIELDS if x not in fab_groups.MERGE_FREELY), []).append(g)
    pair = next((b for b in buckets.values() if len(b) > 1), None)
    if pair:
        mm = c.post("/api/groups/merge", json={"code": pair[1]["code"], "into": pair[0]["code"]}).json()      # no "confirm"
        check(f"{k} two groups that differ only in width or finish merge at the first yes ({pair[1]['code']} into {pair[0]['code']})",
              mm.get("merged") == pair[1]["code"] and c.post("/api/groups/unmerge", json={"code": pair[1]["code"]}).status_code == 200, str(mm)[:200])
    check(f"{k} the pilot results, the rate master and the purchase file are untouched", all(sha(p) == v for p, v in kept_files.items()))
    r1 = c.post("/api/cost", json=masters.EXAMPLE_ROW).json()
    check(f"{k} no rate changed: the example fabric costs what it did before the purchase files (the checks above edited rates on purpose)",
          r1["total_per_m"] == r_before["total_per_m"] and c.get("/api/table/Yarn_Rates").json() == yarn_before and versions() == versions_before,
          f"{r1['total_per_m']:.2f}, rate versions {versions_before} then {versions()}")


def _stage2_right_cost(c, check, kind, when, popup=False):
    """Right cost's purchase-order rows: the price paid, metres, quantity band and should-cost worked out again from the
    lines bought with ZLOI left out (GP, 27 Nov 2026); a code bought only on ZLOI lines shows no price; the dashboard's fit
    by fabric type counts only rows with a price. With popup: the price popup gives every row's should-cost."""
    import pandas as pd
    from rules import dashboard, purchases
    for _ in range(600):
        rc = c.get("/api/costs").json()
        if rc.get("ready") and not any(r.get("band") == "Working it out" for r in rc["rows"]):
            break
        time.sleep(0.5)
    po = {r["code"]: r for r in rc["rows"] if r["source"] == "Purchase orders"}
    _, by_code, zl_all = purchases.bought_lines()
    bad, zl_only, changed = [], [], 0
    pilot_f = {str(r["Fabric code"]): r for r in pd.read_excel(os.path.join(HERE, "pilot", "Pilot_Results.xlsx"), sheet_name="Fabrics").to_dict("records")}
    for code, r in po.items():
        ls = by_code.get(code, [])
        reg = [x for x in ls if x[3] != "ZLOI"]
        metres = sum(x[5] for x in reg)
        price = round(sum(x[5] * x[6] for x in reg) / metres, 2) if metres else None
        if any(x[3] == "ZLOI" for x in ls) and not reg:
            zl_only.append(code)
        by_month = {}               # stage 5's order month: the month with most of its metres (the earlier on a tie), ZLOI left out
        for x in reg:
            by_month[x[2][:7]] = by_month.get(x[2][:7], 0) + x[5]
        month = min(by_month, key=lambda k: (-by_month[k], k)) if by_month else None
        if (r["price"] is None) != (price is None) or (price is not None and abs(r["price"] - price) >= 0.005) or abs((r["metres"] or 0) - metres) > 1e-6 \
                or len(r["outliers"]) != sum(1 for x in ls if x[3] == "ZLOI") or (r["rates"] or {}).get("month") != month:
            bad.append(code)
        changed += r["worked_out_again"] is not None
    ins = dashboard.insights()["pilot"]
    with_price = sum(1 for r in po.values() if r["price"] is not None)
    check(f"[{kind}] Stage 2, Right cost {when}: every purchase-order row's price paid, metres and order month (stage 5) are its lines' own, ZLOI left "
          f"out; a code bought only on ZLOI shows no price and its outliers ({len(zl_only)} such codes, {changed} rows worked out again)",
          len(po) == 1696 and not bad and zl_only and all(po[x]["price"] is None and po[x]["band"] == "No price" and po[x]["outliers"] for x in zl_only)
          and ins["fabrics"] == with_price and all(r["choices"].get("Quoted price (Rs/m)") == r["price"] for r in po.values() if r["price"] is not None)
          and all(po[x]["worked_out_again"] is None and po[x]["price"] == round(pilot_f[x]["PO price Rs/m"], 2) and po[x]["metres"] == pilot_f[x]["PO metres"] for x in po if not any(y[3] == "ZLOI" for y in by_code.get(x, []))
                  and abs(sum(y[5] for y in by_code.get(x, [])) - pilot_f[x]["PO metres"]) < 1e-6),
          f"{bad[:5]} {len(zl_only)} {ins['fabrics']} {with_price}")
    if popup:
        sample = [x for x in po if po[x]["worked_out_again"]] + [x for x in po if not po[x]["worked_out_again"]][:60]
        differ = []
        for code in sample:
            h = c.get("/api/purchases/history", params={"code": code}).json()
            if h.get("should") is None or abs(h["should"] - po[code]["should"]) >= 0.005 or abs(h["metres"] - (po[code]["metres"] or 0)) > 0.01:
                differ.append((code, h.get("should"), po[code]["should"], h.get("metres"), po[code]["metres"]))
        check(f"[{kind}] Stage 2: the price popup and Right cost give one should-cost for a code, from the same metres (ZLOI left out), for the {len(sample)} rows checked "
              "(every row worked out again, and others)", not differ, str(differ[:3]))
        # with a dated yarn rate in force (stage 5), both cost a code on its order month's rate, and the popup says so
        month, yarn = "2026-09", "Cotton 40S"
        hit = sorted(x for x, r in po.items() if (r["rates"] or {}).get("month") == month and yarn in (r["choices"].get("Warp yarn"), r["choices"].get("Weft yarn")))
        added = c.post("/api/dated-rates", json={"yarn_key": yarn, "month": month, "rate": 420, "rests_on": "quote", "note": "stage 2 check"})
        rc2 = _ready_costs(c, until=lambda d: any((r.get("rates") or {}).get("dated") for r in d["rows"]))
        po2 = {r["code"]: r for r in rc2["rows"] if r["source"] == "Purchase orders"}
        pops = {x: c.get("/api/purchases/history", params={"code": x}).json() for x in hit[:12]}
        for e in c.get("/api/dated-rates").json()["entries"]:          # the store left as the rest of the suite found it
            c.post("/api/dated-rates/remove", json={"id": e["id"]})
        check(f"[{kind}] Stage 2 with a dated yarn rate: the price popup costs a code on its order month's rate as Right cost does, and says so "
              f"({len(pops)} of the {len(hit)} {month} orders on {yarn} checked)",
              added.status_code == 200 and hit and all(po2[x]["rates"]["dated"] and po2[x]["should"] != po[x]["should"] for x in pops)
              and all(abs(pops[x]["should"] - po2[x]["should"]) < 0.005 and "dated yarn rates of Sep 2026" in pops[x]["should_on"] for x in pops),
              str([(x, pops[x].get("should"), po2[x]["should"], pops[x].get("should_on")) for x in list(pops)[:3]]))
        key = next(iter(sorted((x for x in zl_all if x[0] in po), key=lambda x: (x[3], x[1]))), None)
        if key:
            from rules import mills as rules_mills_
            mk = rules_mills_.mill_key(purchases.VENDOR_NO.sub("", key[5]).strip())
            sp = c.get("/api/supplier", params={"mill": mk})
            check(f"[{kind}] Stage 2: a mill's ZLOI lines are listed apart on its supplier page", sp.status_code == 200 and any(o["po"] == key[1] for o in sp.json()["outliers"]),
                  str(sp.status_code))


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
    # stage 2 (GP, 27 Nov 2026): ZLOI orders count in no figure, the order month included; a code bought only on them has none
    zloi_only = {r["code"] for r in po if r["price"] is None and r["outliers"]}
    check("Dated rates: every purchase-order costing names its order month, and with no dated rate for it says today's rates are used; "
          "the 184 codes bought only on ZLOI orders have none, and say so",
          len(po) == 1696 and all(r["rates"] and r["rates"]["month"] and not r["rates"]["dated"] and "No dated rate for" in r["rates"]["note"]
                                  for r in po if r["code"] not in zloi_only)
          and len(zloi_only) == 184 and all(r["rates"]["month"] is None and "bought only on ZLOI orders" in r["rates"]["note"]
                                            and r["outliers"] and all(o["code"] == r["code"] for o in r["outliers"]) for r in po if r["code"] in zloi_only)
          and all(r["rates"]["dated"] is False and r["rates"]["note"].startswith("On today's rates") for r in d["rows"] if r["source"] == "Fabric list"),
          str(sorted((k or "none", v) for k, v in by.items())))
    months, lines_ = dated_rules.order_months(), dated_rules.ordered_lines()
    ties = [k for k, v in months.items() if v["tie"]]
    tied = [r for r in po if r["code"] in set(ties)]
    top = lambda code: (lambda g: sorted(g[g["qty"] == g["qty"].max()]["month"]))(lines_[lines_["Material"] == code])
    check("Dated rates: a code ordered in two months with the same metres is costed on the earlier of them, and says so (ZLOI orders left out)",
          len(tied) == 11 and all("the most metres in two months alike; costed on the earlier" in r["rates"]["note"] for r in tied)
          and all(len(top(r["code"])) >= 2 and r["rates"]["month"] == top(r["code"])[0] for r in tied)
          and not set(lines_["Material"]) & zloi_only and all(r["code"] in months for r in po if r["code"] not in zloi_only), f"{len(tied)} tied")
    dl = pd.read_excel(io.BytesIO(c.post("/api/costs/download", json={"keys": [f"Purchase orders|{po[0]['code']}", f"Fabric list|{next(r['id'] for r in d['rows'] if r['source'] == 'Fabric list')}"]}).content))
    ins = c.get("/api/insights").json()
    check("Dated rates: the list and its spreadsheet say which rates each costing is on; the dashboard says its panels are on today's rates",
          all(r["rates_of"] == (f"{r['rates']['label']}: today's yarn rates (no dated rate)" if r["code"] not in zloi_only else "Today's rates") for r in po)
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
        # on the rate master in use (the checks above edited this copy's rates on purpose: a row's should-cost follows the
        # costing its verdict rests on, so a rate changed since the pilot moves it, as stage 2's checks show)
        m = rules_common.get_masters()
        t0, same = time.time(), 0
        for r in po:
            a = masters.cost(r["choices"], m)
            b = masters.cost(r["choices"], m, on=r["rates"]["month"])
            same += {k: v for k, v in b.items() if k != "rates_of"} == a and round(a["total_per_m"], 2) == r["should"]
        check(f"Dated rates: all {len(po)} purchase-order costings on their order month equal, line by line, the costing without a date and the "
              f"should-cost shown, on the rate master in use ({time.time() - t0:.0f} s)", same == len(po), f"{same} of {len(po)}")
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
        # ZLOI orders count in no month (stage 2): 1,512 codes have an order month; the 184 bought only on ZLOI have none
        and [o["fabrics"] for o in pg0["orders"]] == [197, 732, 459, 124] and all(o["none"] == o["fabrics"] for o in pg0["orders"]), str(pg0["orders"]))
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
    # (Oct 2026: with ZLOI orders in no month, stage 2, the Slub 20S codes once ordered in Sep 2026 are bought only on ZLOI or in Oct)
    slub = {r["code"] for r in po if r["rates"]["month"] == "2026-10" and "Cotton Slub 20S" in (r["choices"]["Warp yarn"], r["choices"]["Weft yarn"])}
    ph = add(yarn_key="Cotton Slub 20S", month="2026-10", rate=338, rests_on="none").json()
    d3 = _ready_costs(c, until=lambda x: any((r.get("rates") or {}).get("dated") for r in x["rows"]))
    po3 = {r["code"]: r for r in d3["rows"] if r["source"] == "Purchase orders"}
    m = rules_common.get_masters()

    def as_today(r):        # a Slub order costed without a date on the same rate master (the pilot's stored figures predate this suite's rate edits)
        res = masters.cost(r["choices"], m)
        return {"should": round(res["total_per_m"], 2), "gap": round(res["gap"], 2), "placeholders": ", ".join(res["placeholders"]) or None}
    same = [r["code"] for r in po if all(po3[r["code"]][f] == r[f] for f in ("band", "range", "why_unsure"))
            and (all(po3[r["code"]][f] == r[f] for f in ("should", "gap", "gap_pct", "excess", "placeholders")) if r["code"] not in slub else
                 (lambda t: all(po3[r["code"]][f] == t[f] for f in t) and abs(po3[r["code"]]["excess"] - t["gap"] * r["metres"]) < 0.01)(as_today(r)))]
    chk(f"Dated rates: a rate with no source is a placeholder; on Cotton Slub 20S at today's figure its {len(slub)} Oct 2026 orders say so and no "
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
    # stage 2, web/purchases.js: the price popup (opened from Right cost and from the Fab group pages), the Fab group pages,
    # and the purchase files page, each a section of the file
    pj = read("purchases.js")
    part = lambda a, b: calls(pj[pj.index("// ---------------------------------------------------------------- " + a):pj.index("// ---------------------------------------------------------------- " + b)])
    popup = part("the price popup", "#group/")
    per.setdefault("page:rightcost", set()).update(popup)
    per.setdefault("page:groups", set()).update(popup | part("#group/", "#purchase-files"))
    per.setdefault("page:purchase_files", set()).update(part("#purchase-files", "what the shell sees"))
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
            check(tag + "The AI assistant: every tool names an address of the app it mirrors, its fixed role opens each, and only the "
                        "tools mirroring tracker steps write",
                  set(tools) == set(mirrors) and all(m in keys for m in mirrors.values()) and all(access.assistant_refusal(m) is None for m in mirrors.values())
                  and writers == {n for n, m in mirrors.items() if access.ROUTES[m] == "do:record_steps"} == {"record_tracker_step", "remove_my_tracker_step"},
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
