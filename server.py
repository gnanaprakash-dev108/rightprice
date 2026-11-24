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
        return pd.read_csv(masters.LOG_PATH)
    return pd.DataFrame(columns=LOG_COLS)


def placeholder_count(m):
    return sum(int(df["Basis"].astype(str).str.startswith("Placeholder").sum())
               for df in m.values() if "Basis" in df.columns)


def result_json(res):
    return {
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
                   "basis": str(r["Basis"]), "date": clean(r["Rate date"])} for _, r in yr.iterrows()],
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
    row = {"Saved on": dt.date.today().isoformat(), "Fabric code": sel.get("Fabric code"),
           "Description": sel.get("Description"), "Supplier": sel.get("Supplier"),
           "Should-cost Rs/m": round(res["total_per_m"], 2), "Should-cost Rs/kg": round(res["per_kg"], 1),
           "Quoted Rs/m": res["quote"], "Gap Rs/m": None if res["gap"] is None else round(res["gap"], 2),
           "Gap %": None if res["gap_pct"] is None else round(res["gap_pct"] * 100, 1)}
    os.makedirs(os.path.dirname(masters.LOG_PATH), exist_ok=True)
    pd.concat([read_log(), pd.DataFrame([row])], ignore_index=True).to_csv(masters.LOG_PATH, index=False)
    return {"saved": True}


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
    return {"saved": records(log.iloc[::-1]), "saved_count": len(log),
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
@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"), headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=WEB), name="web")
