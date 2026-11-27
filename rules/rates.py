"""Editing the rate master from the screens, the bulk costing template, and the yarn price intake."""
import datetime as dt
import os
import io
import pandas as pd
from rules import common
import masters
import price_import as pi


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
    "Mill_Sheet_Terms": "Mill sheet terms (per end, per pick)",
}


def template():
    return common.Download(masters.make_template(common.get_masters()), "Should_Cost_Upload_Template.xlsx")


def bulk(filename, data):
    m = common.get_masters()
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name="Fabrics").dropna(how="all")
    except Exception as e:
        raise common.Refused(400, f"Could not read a 'Fabrics' sheet from this file: {e}")
    missing = [c for c, _, req in masters.TEMPLATE_COLUMNS if req and c not in df.columns]
    if missing:
        raise common.Refused(400, "Required columns are missing: " + ", ".join(missing))
    out = masters.cost_many(df, m)
    inputs = [{k: common.clean(v) for k, v in r.items()} for r in df.to_dict("records")]
    return {"results": common.records(out), "inputs": inputs, "rejected": int((out["Error"] != "").sum())}


def bulk_download(payload: dict):
    buf = io.BytesIO()
    pd.DataFrame(payload["rows"], columns=payload["columns"]).to_excel(buf, index=False)
    return common.Download(buf.getvalue(), "Should_Cost_Results.xlsx")


# Every sheet a person may edit from the new screens. Cotton prices are added to, not edited in bulk.
EDITABLE = set(TABLES) - {"Cotton_Prices", "Content_Groups"}


_stash = {}       # tables read by the price intake, waiting for their columns to be chosen


def save_masters(m, reason="Rate master edited", who=""):
    """Write the rate master. The first change of each day keeps a dated copy of what was there (in a database, every
    version is kept)."""
    masters.save(m, reason=reason, who=who, backup=f" backup {dt.date.today():%Y%m%d}", backup_if_absent=True)
    common._cache.pop("#rates", None)


def save_table(sheet: str, payload: dict, who: str = ""):
    m = dict(common.get_masters())
    if sheet not in EDITABLE or sheet not in m:
        raise common.Refused(404, "This table cannot be edited here")
    old = m[sheet]
    if [str(c) for c in payload.get("columns", [])] != [str(c) for c in old.columns]:
        raise common.Refused(400, "The columns do not match the table; reload the page and try again")
    df = pd.DataFrame(payload["rows"], columns=old.columns)
    df = df[~df.apply(lambda r: all(v is None or str(v).strip() == "" for v in r), axis=1)].reset_index(drop=True)
    if df.empty:
        raise common.Refused(400, "A table cannot be saved empty")
    for col in old.columns:
        text = df[col].map(lambda v: None if v is None or str(v).strip() == "" else v)
        if sheet == "Settings" and col == "Value":      # numbers stay numbers, words stay words
            df[col] = [pd.to_numeric(v, errors="coerce") if str(v).replace(".", "", 1).isdigit() else v for v in text]
        elif pd.api.types.is_numeric_dtype(old[col]):
            num = pd.to_numeric(text, errors="coerce")
            bad = df.index[num.isna()].tolist()
            if bad:
                raise common.Refused(400, f"'{col}' needs a number in row {bad[0] + 1}")
            df[col] = num
        else:
            df[col] = text
    key = old.columns[0]
    if sheet != "Market_Yarn":
        if df[key].isna().any():
            raise common.Refused(400, f"'{key}' is blank in row {int(df.index[df[key].isna()][0]) + 1}")
        dup_on = [key] if sheet not in ("Weaving_Rates", "Weaving_Uplifts", "Sizing_Rates", "Piece_Dyeing", "Class_Defaults", "Dobby_Charges") else list(old.columns[:2])
        dup = df[df.duplicated(dup_on)]
        if len(dup):
            raise common.Refused(400, f"'{' / '.join(map(str, dup.iloc[0][dup_on]))}' appears twice")
    m[sheet] = df
    try:
        masters.lists(m)
        masters.cost(masters.EXAMPLE_ROW, m)        # the example must still cost with the edited table
    except Exception as e:
        raise common.Refused(400, f"Not saved: with this change the example fabric can no longer be costed ({e})")
    save_masters(m, reason=f"Table edited: {sheet}", who=who)
    return {"saved": True, "rows": len(df)}


def add_cotton(payload: dict, who: str = ""):
    m = dict(common.get_masters())
    cot = m["Cotton_Prices"]
    try:
        date, price = pd.Timestamp(payload["date"]).date().isoformat(), float(payload["price"])
    except Exception:
        raise common.Refused(400, "A date and a price in rupees per candy are both needed")
    if price <= 0:
        raise common.Refused(400, "The price must be above zero")
    last = cot.iloc[-1] if len(cot) else {"Variety": "Shankar-6", "Unit": "Rs per candy", "Source": ""}
    row = {"Date": date, "Variety": last["Variety"], "Price": price, "Unit": last["Unit"],
           "Source": str(payload.get("source") or "").strip() or "Typed in the tool"}
    m["Cotton_Prices"] = pd.concat([cot, pd.DataFrame([row])[cot.columns]], ignore_index=True)
    save_masters(m, reason=f"Cotton price added: {date}, Rs {price:g}", who=who)
    return {"saved": True}


# What the server read from each document brought in (stage 5): read token -> the dates found in it and the month it
# decided on. "Add as dated yarn rates" trusts only these, never a flag the page sends (rules/dated.py intake_add).
_reads = {}


def _months_apart(a, b):
    return abs((int(a[:4]) * 12 + int(a[5:7])) - (int(b[:4]) * 12 + int(b[5:7])))


def _decide(*where):
    """The document's own date from (text or dates already read, what it is) pairs: a month named in words ("Oct 2026")
    before a day ("sent 03.11.2026"); a phone's or a screen's file name is not read. Sure only when every date of that
    kind falls in one month, none found is more than a year from it, and it is within a year of today; otherwise what was
    found is shown and the person is asked for the month."""
    found = []
    for got, what in where:
        if what == "the file name" and pi.PHONE_NAME.search(os.path.basename(str(got or ""))):
            continue
        for c in (got if isinstance(got, list) else pi.read_dates(got)):
            found.append(dict(c, where=what))
    if not found:
        return None
    pool = [c for c in found if c["kind"] == "month"] or found
    pick = pool[0]
    month = pick["value"][:7]
    sure = (len({c["value"][:7] for c in pool}) == 1 and all(_months_apart(c["value"], month) <= 12 for c in found)
            and _months_apart(month, dt.date.today().isoformat()) <= 12)
    return {"sure": sure, "value": pick["value"], "month": month, "from": pick["where"], "suggest": max(c["value"][:7] for c in pool),
            "found": [f"{c['text']} ({c['where']})" for c in found]}


def _stage(df, note="", decided=None, column=None):
    """Rows for the review table, and what the server read of the document's date, kept under a read token.
    column: the file's own date column (each row its date, read day first; a blank one has none). decided: the document's
    date from its name or text (_decide). With neither, or when not sure, the rows carry today's date for the market
    reference only, and a dated yarn rate needs the month chosen (stage 5: never today's)."""
    df = df.copy()
    info = {"dates": set(), "month": None, "from": None}
    if column:
        days = [pi.read_date(d) for d in df["Date"]]                # a blank cell (NaN) is no date
        df["Date"] = days
        info.update(dates={d for d in days if d}, **{"from": f"the file's column {column}"})
        blank = sum(1 for d in days if not d)
        note = (note + " " if note else "") + f"Dates read from the file's column {column}" + (
            f"; {blank} {'row has' if blank == 1 else 'rows have'} none." if blank else ".")
    elif decided and decided["sure"]:
        df["Date"] = decided["value"]
        info.update(dates={decided["value"]}, month=decided["month"], **{"from": decided["from"]})
        note = (note + " " if note else "") + f"Dated {decided['value']}, read from {decided['from']}."
    elif decided:
        note = (note + " " if note else "") + (f"Dates found: {'; '.join(decided['found'])}. Which is the date of these prices is not sure, "
                                               "so the month is asked before they are added as dated rates.")
    token = f"r{len(_reads) + 1}-{dt.datetime.now():%H%M%S%f}"
    _reads[token] = info
    while len(_reads) > 40:
        _reads.pop(next(iter(_reads)))
    read = bool(column) or bool(decided and decided["sure"])
    return {"kind": "rows", "note": note, **common.records(df[pi.STAGE_COLS]), "read_token": token,
            "date_read": read, "date_from": info["from"], "date_found": decided["value"] if decided and decided["sure"] else None,
            "dates_found": decided["found"] if decided else [], "month_suggested": (decided["month"] if decided["sure"] else decided["suggest"]) if decided else None}


def _tables(named, source):
    token = f"t{len(_stash) + 1}-{dt.datetime.now():%H%M%S%f}"
    _stash[token] = ({k: v.rename(columns=str) for k, v in named.items()}, source)
    while len(_stash) > 6:
        _stash.pop(next(iter(_stash)))
    return {"kind": "tables", "token": token, "source": source,
            "sheets": {k: common.records(v.rename(columns=str).head(15)) for k, v in named.items()}}


def _pdf(data, source):
    rows, info = pi.read_pdf(data, source)
    if info["scanned"]:
        note = (f"This PDF is a scan ({info['pages']} pages, no readable text). Type the rates into the table "
                "while looking at the pages.")
    else:
        note = f"Read {len(rows)} price lines from {info['pages']} pages. Check them before adding."
        if info["image_pages"]:
            note += f" {info['image_pages']} pages are pictures with no readable text; their rates need typing in."
    return _stage(rows if len(rows) else pi.empty_stage(), note, _decide((source, "the file name"), (info.get("dates") or [], "the document's text")))


def intake_file(filename, data):
    name = filename or "upload"
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
                                            "rates into the table.", _decide((name, "the file name"))) | {"source": name}
    except common.Refused:
        raise
    except Exception as e:
        raise common.Refused(400, f"Could not read this file: {e}")
    raise common.Refused(400, "Use an Excel, CSV, PDF or picture file")


def intake_link(payload: dict):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise common.Refused(400, "Give a page address")
    try:
        kind, got = pi.fetch_link(url)
        if kind == "pdf":
            return _pdf(got, url)
        tables, text = got
        if tables:
            return _tables({f"Table {i + 1} ({len(t)} rows)": t for i, t in enumerate(tables)}, url)
        rows = pi.rows_from_text(text, url)
        return _stage(rows if len(rows) else pi.empty_stage(), f"No tables on the page; {len(rows)} price-like lines found in its text.",
                      _decide((url, "the page address"), (text[:4000], "the page's text")))
    except Exception as e:
        raise common.Refused(400, f"Could not read this page: {e}. Pages behind a login cannot be read.")


def intake_api(payload: dict):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise common.Refused(400, "Give the endpoint address")
    try:        # the key is used for this one call and is not stored
        return _tables({"Reply": pi.fetch_api(url, payload.get("header_name"), payload.get("header_value"))}, url)
    except Exception as e:
        raise common.Refused(400, f"The call failed: {e}")


def intake_map(payload: dict):
    hit = _stash.get(payload.get("token"))
    if not hit or payload.get("sheet") not in hit[0]:
        raise common.Refused(400, "That file is no longer held; upload it again")
    if not payload.get("count") or not payload.get("low"):
        raise common.Refused(400, "Choose at least the count column and the rate column")
    try:
        rows = pi.map_columns(hit[0][payload["sheet"]], payload["count"], payload["low"], payload.get("high") or None,
                              payload.get("yarn") or None, payload.get("date") or None, hit[1])
    except Exception as e:
        raise common.Refused(400, f"Those columns could not be read: {e}")
    note = f"{len(rows)} rows with a rate were read. Check them before adding."
    if payload.get("date"):         # the file's own date column
        return _stage(rows, note, column=payload["date"])
    return _stage(rows, note, _decide((hit[1], "the file name"), (payload.get("sheet"), "the sheet's name")))


def intake_add(payload: dict, who: str = ""):
    good = pi.clean_stage(pd.DataFrame(payload.get("rows", []), columns=pi.STAGE_COLS))
    if good.empty:
        raise common.Refused(400, "No complete rows: each row needs a count and a rate")
    if payload.get("source"):
        good["Source"] = good["Source"].fillna(payload["source"])
    m = dict(common.get_masters())
    m["Market_Yarn"] = pd.concat([m["Market_Yarn"], good], ignore_index=True)
    save_masters(m, reason=f"Market yarn prices brought in: {len(good)} rows", who=who)
    return {"added": len(good)}
