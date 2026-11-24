"""RightPrice web server: the new front end (web/) and the JSON it reads.

Run: python -m uvicorn server:app --port 8000
The costing itself is unchanged: every number comes from masters.py and engine.py, and every
rate from the rate master workbook. There is no database.

The earlier Streamlit screens stay reachable under /classic (rate editing and the yarn price
intake still live there). This server starts Streamlit beside itself and passes /classic through.
"""
import asyncio
import datetime as dt
import io
import json
import math
import os
import subprocess
import sys
from contextlib import asynccontextmanager

import httpx
import pandas as pd
import websockets
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import masters
import price_import as pi
import yarn_seed

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
PILOT = os.path.join(HERE, "pilot", "Pilot_Results.xlsx")
DRAFT = os.path.join(HERE, "pilot", "Proposed_Rate_Changes.xlsx")
CLASSIC_PORT = int(os.environ.get("RIGHTPRICE_CLASSIC_PORT", "8501"))
CLASSIC = f"127.0.0.1:{CLASSIC_PORT}"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOG_COLS = ["Saved on", "Fabric code", "Description", "Supplier", "Should-cost Rs/m", "Should-cost Rs/kg",
            "Quoted Rs/m", "Gap Rs/m", "Gap %"]
# sheet -> (label, group) for the read-only table pages
TABLES = {
    "Yarn_Rates": "Yarn master", "Market_Yarn": "Market reference", "Cotton_Prices": "Cotton prices",
    "Weaving_Rates": "Weaving", "Weaving_Uplifts": "Pattern and loom uplifts", "Sizing_Rates": "Sizing",
    "Yarn_Dyeing": "Yarn dyeing", "Piece_Dyeing": "Piece dyeing and printing", "Finishing_Rates": "Finishing",
    "Class_Defaults": "Crimp, wastage, overhead, margin", "Weaves": "Weave list",
    "Content_Groups": "Content groups", "Print_Methods": "Print method",
    "Dobby_Charges": "Dobby shafts and top beam", "Weft_Options": "Weft (yarn dyed)",
    "Quantity_Terms": "Rate card quantity", "Settings": "Calculation settings", "Mill_Tier": "Mill tiers",
    "Order_Slab": "Order size slabs", "Supplier_Benchmarks": "Supplier cost ratios",
}

_classic = None
_cache = {}


@asynccontextmanager
async def lifespan(_app):
    global _classic
    if os.environ.get("RIGHTPRICE_NO_CLASSIC") != "1":
        _classic = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "app.py"),
             "--server.port", str(CLASSIC_PORT), "--server.address", "127.0.0.1", "--server.headless", "true",
             "--server.baseUrlPath", "classic", "--server.enableCORS", "false",
             "--server.enableXsrfProtection", "false", "--browser.gatherUsageStats", "false"], cwd=HERE)
    yield
    if _classic:
        _classic.terminate()


app = FastAPI(title="RightPrice", lifespan=lifespan, docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ helpers
def cached(path, loader):
    """Reload a workbook only when the file on disk has changed (the classic screens can edit it)."""
    mtime = os.path.getmtime(path) if os.path.exists(path) else None
    hit = _cache.get(path)
    if not hit or hit[0] != mtime:
        _cache[path] = (mtime, loader())
    return _cache[path][1]


def get_masters():
    if not os.path.exists(masters.MASTER_PATH):
        masters.load()
    return cached(masters.MASTER_PATH, masters.load)


def clean(v):
    """A value JSON can carry: no NaN, no numpy or pandas types."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.isoformat()[:10]
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def records(df, limit=None):
    df = df if limit is None else df.tail(limit)
    return {"columns": [str(c) for c in df.columns],
            "rows": [[clean(v) for v in row] for row in df.itertuples(index=False, name=None)]}


def read_log():
    if os.path.exists(masters.LOG_PATH):
        return pd.read_csv(masters.LOG_PATH, dtype={"Id": str})
    return pd.DataFrame(columns=LOG_COLS)


def placeholder_count(m):
    return sum(int(df["Basis"].astype(str).str.startswith("Placeholder").sum())
               for df in m.values() if "Basis" in df.columns)


def sanity(inp, res):
    """Things a typing slip usually causes. The cost is still shown; these say why it may be wrong."""
    w, out = inp["width_in"], []
    if not 30 <= w <= 130:
        out.append(f"Finished width {w:g} inch is outside 30 to 130. Widths are in inches, not centimetres.")
    for name, key in (("EPI", "epi"), ("PPI", "ppi")):
        if not 20 <= inp[key] <= 400:
            out.append(f"{name} {inp[key]:g} is outside 20 to 400.")
    if inp["reed_in"] < w:
        out.append(f"Reed space {inp['reed_in']:g} inch is narrower than the finished width {w:g} inch.")
    elif inp["reed_in"] > w * 1.35:
        out.append(f"Reed space {inp['reed_in']:g} inch is more than 35% wider than the finished width {w:g} inch.")
    for name, key in (("Warp", "warp_ne"), ("Weft", "weft_ne")):
        if not 4 <= inp[key] <= 200:
            out.append(f"{name} count works out at Ne {inp[key]:.4g}, outside 4 to 200. Check the count and the count system.")
    if not 40 <= res["gsm"] <= 600:
        out.append(f"The fabric works out at about {res['gsm']:.0f} g/m2, outside 40 to 600. Check the counts, EPI and PPI.")
    return out


def result_json(res):
    return {
        "warnings": sanity(res["inputs"], res),
        "total_per_m": res["total_per_m"], "per_kg": res["per_kg"], "gsm": res["gsm"],
        "finished_g_per_m": res["finished_g_per_m"], "quote": res["quote"], "gap": res["gap"],
        "gap_pct": res["gap_pct"], "placeholders": res["placeholders"],
        "buckets": [{"name": b["name"], "amount": b["amount"], "pct": b["pct"],
                     "lines": [{"name": l["name"], "basis": l["basis"], "amount": l["amount"]} for l in b["lines"]]}
                    for b in res["buckets"]],
        "rates_used": [{k: (v if isinstance(v, str) else clean(v)) for k, v in u.items()} for u in res["rates_used"]],
    }


def cost_or_400(sel, m):
    try:
        return masters.cost({k: v for k, v in sel.items() if v not in ("", None)}, m)
    except Exception as e:      # a choice not on a list, a missing number: tell the user which
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ API
@app.get("/api/meta")
def meta():
    m = get_masters()
    yr = m["Yarn_Rates"]
    return {
        "lists": masters.lists(m),
        "weave_group": dict(zip(m["Weaves"]["Weave"], m["Weaves"]["Weave group"])),
        "yarns": [{"key": r["Yarn key"], "rate": clean(r["Rate Rs/kg"]), "ne": clean(r["Count Ne (resultant)"]),
                   "basis": str(r["Basis"]), "date": clean(r["Rate date"]), "blend": str(r["Blend"]),
                   "content": yarn_seed.content_of(r["Blend"])} for _, r in yr.iterrows()],
        "contents": list(yarn_seed.CONTENTS),
        "editable": sorted(EDITABLE),
        "example": masters.EXAMPLE_ROW,
        "template_columns": [{"name": c, "list": l, "required": r} for c, l, r in masters.TEMPLATE_COLUMNS],
        "tables": TABLES,
        "small_lot_bands": m["Quantity_Terms"][m["Quantity_Terms"]["Small-lot upcharge %"] > 0]["Quantity band"].tolist(),
        "placeholders": placeholder_count(m),
    }


@app.post("/api/cost")
def cost(sel: dict = Body(...)):
    return result_json(cost_or_400(sel, get_masters()))


@app.post("/api/cost-sheet")
def cost_sheet(sel: dict = Body(...)):
    res = cost_or_400(sel, get_masters())
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summ = [("Fabric code", sel.get("Fabric code")), ("Description", sel.get("Description")),
                ("Supplier", sel.get("Supplier")), ("Should-cost Rs/m", round(res["total_per_m"], 2)),
                ("Should-cost Rs/kg", round(res["per_kg"], 1)), ("Approx. GSM", round(res["gsm"], 1)),
                ("Quoted Rs/m", res["quote"]), ("Gap Rs/m", None if res["gap"] is None else round(res["gap"], 2))]
        summ += [(b["name"] + " Rs/m", round(b["amount"], 2)) for b in res["buckets"]]
        pd.DataFrame(summ, columns=["Item", "Value"]).to_excel(xw, sheet_name="Cost view", index=False)
        lines = [{"Bucket": b["name"], "Line": l["name"], "How it is worked out": l["basis"],
                  "Rs/m": round(l["amount"], 2)} for b in res["buckets"] for l in b["lines"]]
        pd.DataFrame(lines).to_excel(xw, sheet_name="Second level", index=False)
        pd.DataFrame(res["rates_used"]).astype(str).to_excel(xw, sheet_name="Rates used", index=False)
        pd.DataFrame([{"Input": k, "Value": v} for k, v in sel.items()]).astype(str).to_excel(
            xw, sheet_name="Inputs", index=False)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Should cost.xlsx"'})


@app.post("/api/save")
def save(sel: dict = Body(...)):
    res = cost_or_400(sel, get_masters())
    now = dt.datetime.now()
    row = {"Saved on": now.date().isoformat(), "Fabric code": sel.get("Fabric code"),
           "Description": sel.get("Description"), "Supplier": sel.get("Supplier"),
           "Should-cost Rs/m": round(res["total_per_m"], 2), "Should-cost Rs/kg": round(res["per_kg"], 1),
           "Quoted Rs/m": res["quote"], "Gap Rs/m": None if res["gap"] is None else round(res["gap"], 2),
           "Gap %": None if res["gap_pct"] is None else round(res["gap_pct"] * 100, 1),
           # the choices themselves, so the costing can be opened again and re-costed on today's rates
           "Id": f"{now:%Y%m%d%H%M%S%f}", "Inputs": json.dumps(sel),
           # what it cost and on which rates, so a later look can say what has moved since
           "Result": json.dumps({"total_per_m": res["total_per_m"],
                                 "buckets": [{"name": b["name"], "amount": b["amount"]} for b in res["buckets"]],
                                 "rates": [{"Item": u["Item"], "Choice": str(u["Choice"]), "Value": clean(u["Value"]) if not isinstance(u["Value"], str) else u["Value"],
                                            "Unit": u["Unit"]} for u in res["rates_used"]]})}
    os.makedirs(os.path.dirname(masters.LOG_PATH), exist_ok=True)
    pd.concat([read_log(), pd.DataFrame([row])], ignore_index=True).to_csv(masters.LOG_PATH, index=False)
    return {"saved": True, "id": row["Id"]}


@app.delete("/api/saved/{saved_id}")
def delete_saved(saved_id: str):
    log = read_log()
    if "Id" not in log.columns or not (log["Id"].astype(str) == saved_id).any():
        raise HTTPException(404, "That saved costing is no longer there")
    log[log["Id"].astype(str) != saved_id].to_csv(masters.LOG_PATH, index=False)
    return {"deleted": True}


@app.get("/api/dashboard")
def dashboard():
    m = get_masters()
    log = read_log()
    gaps = pd.to_numeric(log["Gap %"], errors="coerce").dropna()
    cot = m["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    cotton = None
    if len(cot):
        last = cot.iloc[-1]
        prev = cot[cot["Date"] <= last["Date"] - pd.Timedelta(days=30)]
        cotton = {"price": clean(last["Price"]), "date": clean(last["Date"]), "source": str(last["Source"]),
                  "change_30d": None if prev.empty else float(last["Price"]) / float(prev.iloc[-1]["Price"]) - 1,
                  "age_days": int((pd.Timestamp.today() - last["Date"]).days)}
    mk = m["Market_Yarn"]
    cc = mk[mk["Yarn"] == "Cotton combed compact"]
    yarns = []
    for _, y in m["Yarn_Rates"].iterrows():
        if str(y["Blend"]) != "Cotton":
            continue
        hit = cc[cc["Count"].astype(str).str.lower() == str(y["Count"]).lower()]
        lo, hi = (float(hit["Low Rs/kg"].iloc[0]), float(hit["High Rs/kg"].iloc[0])) if len(hit) else (None, None)
        rate = float(y["Rate Rs/kg"])
        pos = None if lo is None else ("inside" if lo <= rate <= hi else ("above" if rate > hi else "below"))
        yarns.append({"key": y["Yarn key"], "rate": rate, "date": clean(y["Rate date"]), "basis": str(y["Basis"]),
                      "market_low": lo, "market_high": hi, "position": pos})
    shown = log.iloc[::-1].reset_index(drop=True)
    items = []          # one per saved costing, newest first: its id and choices where it has them
    for _, r in shown.iterrows():
        raw = r.get("Inputs")
        try:
            inputs = json.loads(raw) if isinstance(raw, str) and raw else None
        except ValueError:
            inputs = None
        try:
            then = json.loads(r.get("Result")) if isinstance(r.get("Result"), str) and r.get("Result") else None
        except ValueError:
            then = None
        items.append({"id": None if pd.isna(r.get("Id")) else str(r.get("Id")).split(".")[0], "inputs": inputs,
                      "then": then, "saved_on": clean(r.get("Saved on"))})
    return {"saved": records(shown[[c for c in LOG_COLS if c in shown.columns]]), "saved_items": items,
            "saved_count": len(log),
            "avg_gap_pct": None if gaps.empty else float(gaps.mean()), "cotton": cotton, "yarns": yarns,
            "placeholders": placeholder_count(m), "benchmarks": records(m["Supplier_Benchmarks"])}


@app.get("/api/table/{sheet}")
def table(sheet: str):
    m = get_masters()
    if sheet not in TABLES or sheet not in m:
        raise HTTPException(404, "No such table")
    return {"label": TABLES[sheet], **records(m[sheet])}


@app.get("/api/cotton")
def cotton():
    cot = get_masters()["Cotton_Prices"].copy()
    cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
    cot = cot.dropna(subset=["Date"]).sort_values("Date")
    return {"points": [[clean(d), clean(p)] for d, p in zip(cot["Date"], cot["Price"])],
            "unit": str(cot["Unit"].iloc[-1]) if len(cot) else "", "source": str(cot["Source"].iloc[-1]) if len(cot) else ""}


@app.get("/api/pilot")
def pilot():
    if not os.path.exists(PILOT):
        raise HTTPException(404, "Pilot results are not on this server")

    def load():
        x = pd.read_excel(PILOT, sheet_name=["Funnel", "Overall", "Rate card steps", "Rate card inputs",
                                             "By route and weave", "By supplier"])
        out = {k: records(v) for k, v in x.items()}
        if os.path.exists(DRAFT):
            d = pd.read_excel(DRAFT, sheet_name=["Order size", "Weaving", "Printing", "Held-back test"])
            out.update({"Draft: " + k: records(v) for k, v in d.items()})
        return out
    return cached(PILOT, load)


@app.get("/api/template")
def template():
    return Response(masters.make_template(get_masters()), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Should_Cost_Upload_Template.xlsx"'})


@app.post("/api/bulk")
async def bulk(file: UploadFile = File(...)):
    m = get_masters()
    try:
        df = pd.read_excel(io.BytesIO(await file.read()), sheet_name="Fabrics").dropna(how="all")
    except Exception as e:
        raise HTTPException(400, f"Could not read a 'Fabrics' sheet from this file: {e}")
    missing = [c for c, _, req in masters.TEMPLATE_COLUMNS if req and c not in df.columns]
    if missing:
        raise HTTPException(400, "Required columns are missing: " + ", ".join(missing))
    out = masters.cost_many(df, m)
    inputs = [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]
    return {"results": records(out), "inputs": inputs, "rejected": int((out["Error"] != "").sum())}


@app.post("/api/bulk-download")
def bulk_download(payload: dict = Body(...)):
    buf = io.BytesIO()
    pd.DataFrame(payload["rows"], columns=payload["columns"]).to_excel(buf, index=False)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Should_Cost_Results.xlsx"'})


# ------------------------------------------------------------------ editing the rate master
# Every sheet a person may edit from the new screens. Cotton prices are added to, not edited in bulk.
EDITABLE = set(TABLES) - {"Cotton_Prices", "Content_Groups"}
_stash = {}       # tables read by the price intake, waiting for their columns to be chosen


def save_masters(m):
    """Write the rate master. The first change of each day keeps a dated copy of what was there."""
    import shutil
    backup = masters.MASTER_PATH.replace(".xlsx", f" backup {dt.date.today():%Y%m%d}.xlsx")
    if os.path.exists(masters.MASTER_PATH) and not os.path.exists(backup):
        shutil.copyfile(masters.MASTER_PATH, backup)
    masters.save(m)
    _cache.pop(masters.MASTER_PATH, None)


@app.put("/api/table/{sheet}")
def save_table(sheet: str, payload: dict = Body(...)):
    m = dict(get_masters())
    if sheet not in EDITABLE or sheet not in m:
        raise HTTPException(404, "This table cannot be edited here")
    old = m[sheet]
    if [str(c) for c in payload.get("columns", [])] != [str(c) for c in old.columns]:
        raise HTTPException(400, "The columns do not match the table; reload the page and try again")
    df = pd.DataFrame(payload["rows"], columns=old.columns)
    df = df[~df.apply(lambda r: all(v is None or str(v).strip() == "" for v in r), axis=1)].reset_index(drop=True)
    if df.empty:
        raise HTTPException(400, "A table cannot be saved empty")
    for col in old.columns:
        text = df[col].map(lambda v: None if v is None or str(v).strip() == "" else v)
        if sheet == "Settings" and col == "Value":      # numbers stay numbers, words stay words
            df[col] = [pd.to_numeric(v, errors="coerce") if str(v).replace(".", "", 1).isdigit() else v for v in text]
        elif pd.api.types.is_numeric_dtype(old[col]):
            num = pd.to_numeric(text, errors="coerce")
            bad = df.index[num.isna()].tolist()
            if bad:
                raise HTTPException(400, f"'{col}' needs a number in row {bad[0] + 1}")
            df[col] = num
        else:
            df[col] = text
    key = old.columns[0]
    if sheet != "Market_Yarn":
        if df[key].isna().any():
            raise HTTPException(400, f"'{key}' is blank in row {int(df.index[df[key].isna()][0]) + 1}")
        dup_on = [key] if sheet not in ("Weaving_Rates", "Weaving_Uplifts", "Sizing_Rates", "Piece_Dyeing", "Class_Defaults", "Dobby_Charges") else list(old.columns[:2])
        dup = df[df.duplicated(dup_on)]
        if len(dup):
            raise HTTPException(400, f"'{' / '.join(map(str, dup.iloc[0][dup_on]))}' appears twice")
    m[sheet] = df
    try:
        masters.lists(m)
        masters.cost(masters.EXAMPLE_ROW, m)        # the example must still cost with the edited table
    except Exception as e:
        raise HTTPException(400, f"Not saved: with this change the example fabric can no longer be costed ({e})")
    save_masters(m)
    return {"saved": True, "rows": len(df)}


@app.post("/api/cotton")
def add_cotton(payload: dict = Body(...)):
    m = dict(get_masters())
    cot = m["Cotton_Prices"]
    try:
        date, price = pd.Timestamp(payload["date"]).date().isoformat(), float(payload["price"])
    except Exception:
        raise HTTPException(400, "A date and a price in rupees per candy are both needed")
    if price <= 0:
        raise HTTPException(400, "The price must be above zero")
    last = cot.iloc[-1] if len(cot) else {"Variety": "Shankar-6", "Unit": "Rs per candy", "Source": ""}
    row = {"Date": date, "Variety": last["Variety"], "Price": price, "Unit": last["Unit"],
           "Source": str(payload.get("source") or "").strip() or "Typed in the tool"}
    m["Cotton_Prices"] = pd.concat([cot, pd.DataFrame([row])[cot.columns]], ignore_index=True)
    save_masters(m)
    return {"saved": True}


# ------------------------------------------------------------------ yarn price intake
def _stage(df, note=""):
    return {"kind": "rows", "note": note, **records(df[pi.STAGE_COLS])}


def _tables(named, source):
    token = f"t{len(_stash) + 1}-{dt.datetime.now():%H%M%S%f}"
    _stash[token] = ({k: v.rename(columns=str) for k, v in named.items()}, source)
    while len(_stash) > 6:
        _stash.pop(next(iter(_stash)))
    return {"kind": "tables", "token": token, "source": source,
            "sheets": {k: records(v.rename(columns=str).head(15)) for k, v in named.items()}}


def _pdf(data, source):
    rows, info = pi.read_pdf(data, source)
    if info["scanned"]:
        note = (f"This PDF is a scan ({info['pages']} pages, no readable text). Type the rates into the table "
                "while looking at the pages.")
    else:
        note = f"Read {len(rows)} price lines from {info['pages']} pages. Check them before adding."
        if info["image_pages"]:
            note += f" {info['image_pages']} pages are pictures with no readable text; their rates need typing in."
    return _stage(rows if len(rows) else pi.empty_stage(), note)


@app.post("/api/intake/file")
async def intake_file(file: UploadFile = File(...)):
    data, name = await file.read(), file.filename or "upload"
    ext = name.lower().rsplit(".", 1)[-1]
    try:
        if ext in ("xlsx", "xls", "csv"):
            return _tables(pi.read_table_file(name, data), name)
        if ext == "pdf":
            pi.keep_file(name, data)
            return _pdf(data, name)
        if ext in ("png", "jpg", "jpeg", "webp"):
            pi.keep_file(name, data)
            return _stage(pi.empty_stage(), "Pictures cannot be read here. The picture is kept as the source; type its "
                                            "rates into the table.") | {"source": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read this file: {e}")
    raise HTTPException(400, "Use an Excel, CSV, PDF or picture file")


@app.post("/api/intake/link")
def intake_link(payload: dict = Body(...)):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Give a page address")
    try:
        kind, got = pi.fetch_link(url)
        if kind == "pdf":
            return _pdf(got, url)
        tables, text = got
        if tables:
            return _tables({f"Table {i + 1} ({len(t)} rows)": t for i, t in enumerate(tables)}, url)
        rows = pi.rows_from_text(text, url)
        return _stage(rows if len(rows) else pi.empty_stage(), f"No tables on the page; {len(rows)} price-like lines found in its text.")
    except Exception as e:
        raise HTTPException(400, f"Could not read this page: {e}. Pages behind a login cannot be read.")


@app.post("/api/intake/api")
def intake_api(payload: dict = Body(...)):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Give the endpoint address")
    try:        # the key is used for this one call and is not stored
        return _tables({"Reply": pi.fetch_api(url, payload.get("header_name"), payload.get("header_value"))}, url)
    except Exception as e:
        raise HTTPException(400, f"The call failed: {e}")


@app.post("/api/intake/map")
def intake_map(payload: dict = Body(...)):
    hit = _stash.get(payload.get("token"))
    if not hit or payload.get("sheet") not in hit[0]:
        raise HTTPException(400, "That file is no longer held; upload it again")
    if not payload.get("count") or not payload.get("low"):
        raise HTTPException(400, "Choose at least the count column and the rate column")
    try:
        rows = pi.map_columns(hit[0][payload["sheet"]], payload["count"], payload["low"], payload.get("high") or None,
                              payload.get("yarn") or None, payload.get("date") or None, hit[1])
    except Exception as e:
        raise HTTPException(400, f"Those columns could not be read: {e}")
    return _stage(rows, f"{len(rows)} rows with a rate were read. Check them before adding.")


@app.post("/api/intake/add")
def intake_add(payload: dict = Body(...)):
    good = pi.clean_stage(pd.DataFrame(payload.get("rows", []), columns=pi.STAGE_COLS))
    if good.empty:
        raise HTTPException(400, "No complete rows: each row needs a count and a rate")
    if payload.get("source"):
        good["Source"] = good["Source"].fillna(payload["source"])
    m = dict(get_masters())
    m["Market_Yarn"] = pd.concat([m["Market_Yarn"], good], ignore_index=True)
    save_masters(m)
    return {"added": len(good)}



# ------------------------------------------------------------------ classic screens, passed through
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-encoding", "content-length", "host"}


@app.api_route("/classic", methods=["GET"])
@app.api_route("/classic/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def classic_http(request: Request, path: str = ""):
    url = f"http://{CLASSIC}/classic/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.request(request.method, url, params=request.query_params, headers=headers,
                                     content=await request.body())
    except httpx.HTTPError:
        return Response("The classic screens are still starting. Try again in a few seconds.", status_code=503,
                        headers={"Retry-After": "5"})
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in HOP})


@app.websocket("/classic/{path:path}")
async def classic_ws(ws: WebSocket, path: str):
    proto = ws.headers.get("sec-websocket-protocol")
    subs = [p.strip() for p in proto.split(",")] if proto else None
    query = f"?{ws.url.query}" if ws.url.query else ""
    try:
        upstream = await websockets.connect(f"ws://{CLASSIC}/classic/{path}{query}", subprotocols=subs,
                                            max_size=None, additional_headers={"Cookie": ws.headers.get("cookie", "")})
    except Exception:
        await ws.close(code=1013)
        return
    await ws.accept(subprotocol=upstream.subprotocol)

    async def up():
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                await upstream.send(msg["bytes"] if msg.get("bytes") is not None else msg["text"])
        finally:
            await upstream.close()

    async def down():
        try:
            async for msg in upstream:
                await (ws.send_bytes(msg) if isinstance(msg, bytes) else ws.send_text(msg))
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    await asyncio.gather(up(), down(), return_exceptions=True)


# ------------------------------------------------------------------ the front end
class FreshFiles(StaticFiles):
    """Static files the browser must check before reusing, so a new version shows without a hard refresh."""
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


@app.get("/")
def index():
    # the script and stylesheet addresses carry the time they were last changed: a new deploy is a new address
    html = open(os.path.join(WEB, "index.html"), encoding="utf8").read()
    for name in ("app.css", "app.js"):
        html = html.replace(f'"{name}"', f'"{name}?v={int(os.path.getmtime(os.path.join(WEB, name)))}"')
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})


app.mount("/", FreshFiles(directory=WEB), name="web")
