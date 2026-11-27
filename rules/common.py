"""What every rule shares: the rate master in use (read again only when it changes), the fabric list, the
answers kept while nothing has changed, and the small conversions (numbers, dates, rupees) the rules use."""
import datetime as dt
import json
import math
import os
import re
import pandas as pd
import masters
import store


class Refused(Exception):
    """A request the rules turn down, with the words to show the person. The web layer answers with this status and
    {"detail": <words>}, as before; the MCP tools pass the words on."""

    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class Download:
    """A file to hand to the browser: its bytes and its name. The web layer turns it into the download."""
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, data, filename, media_type=XLSX):
        self.data, self.filename, self.media_type = data, filename, media_type


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # the project folder
PILOT = os.path.join(HERE, "pilot", "Pilot_Results.xlsx")


DRAFT = os.path.join(HERE, "pilot", "Proposed_Rate_Changes.xlsx")


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


LOG_COLS = store.LOG_COLS


_cache = {}


def cached(path, loader):
    """Reload a workbook only when the file on disk has changed (the classic screens can edit it)."""
    mtime = os.path.getmtime(path) if os.path.exists(path) else None
    hit = _cache.get(path)
    if not hit or hit[0] != mtime:
        _cache[path] = (mtime, loader())
    return _cache[path][1]


def get_masters():
    """The rate master in use, read again only when it has changed (the classic screens can change it too)."""
    st = store.get()
    key = st.version("rates")
    if key is None:                 # no rate master yet: the first load makes one
        masters.load()
        key = st.version("rates")
    hit = _cache.get("#rates")
    if not hit or hit[0] != key:
        _cache["#rates"] = (key, masters.load())
    return _cache["#rates"][1]


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
    return store.get().read_list()


def _num_or_none(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _qty(v):
    """A quantity as mills type it: 5000, "3,333", "5000 mtr", "4,200 m"."""
    n = _num_or_none(v)
    if n is None and isinstance(v, str):
        hit = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*(m|mt|mtr|mtrs|mts|metre|metres|meter|meters)?\.?\s*", v.lower())
        n = float(hit.group(1).replace(",", "")) if hit and hit.group(1).strip(",") else None
    return n


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) and v else default
    except ValueError:
        return default


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _state_key():
    """What the list and Right cost are worked out from: the fabric list, the rate master, and the purchase history.
    While none of them changes, the answer is kept (the pages ask every half minute)."""
    ins = _cache.get(PILOT + "#insights")
    st = store.get()
    return (st.version("list"), st.version("rates"), bool(ins and ins[1]), _mtime(PILOT))


def _inr(v, d=2):
    """Rupees with Indian grouping: 9,99,99,999.00."""
    neg, v = v < 0, abs(float(v))
    whole, frac = f"{v:.{d}f}".split(".") if d else (f"{v:.0f}", "")
    head, tail = whole[:-3], whole[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return ("−" if neg else "") + (head + "," if head else "") + tail + ("." + frac if d else "")


def _day(iso):
    try:
        return f"{dt.date.fromisoformat(str(iso)[:10]):%d %b %Y}".lstrip("0")
    except ValueError:
        return str(iso)
