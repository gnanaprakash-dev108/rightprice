"""Dated yarn rates (stage 5): the table yarn_rate_dated (db/005_dated_rates.sql), read and written through the data
layer. Only in a database: on the files store there are none, and every costing on a date uses today's yarn rates and
says so for each yarn.

What the rate of a month is, and who may enter one, is decided in rules/dated.py; this module only keeps the rows.
"""
import datetime as dt
import json
import threading

import store

COLS = ["id", "yarn_key", "valid_from", "rate", "low", "high", "entries", "basis", "source", "detail", "entered_by",
        "entered_at", "removed_at", "removed_by", "removed_why"]
_memo = {"key": None, "table": {}}
_lock = threading.Lock()


def available():
    """Whether dated rates can be kept here: a database, not the files."""
    return store.get().kind != "files"


def version():
    """What the dated rates are at (None on the files): the screens' memory keys on it."""
    s = store.get()
    return None if s.kind == "files" else s.version("dated")


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _row(r):
    d = dict(zip(COLS, r))
    d["month"] = str(d["valid_from"])[:7]
    try:
        d["detail"] = json.loads(d["detail"] or "{}")
    except ValueError:
        d["detail"] = {}
    for k in ("rate", "low", "high"):
        d[k] = None if d[k] is None else float(d[k])
    return d


def rows(include_removed=False):
    """Every dated rate, by yarn and month (the removed and replaced ones too, when asked)."""
    if not available():
        return []
    where = "" if include_removed else " WHERE removed_at IS NULL"
    with store.get().tx() as c:
        return [_row(r) for r in c.all(f"SELECT {', '.join(COLS)} FROM yarn_rate_dated{where} ORDER BY yarn_key, valid_from, id")]


def table():
    """The dated rates in force: {yarn key: {'YYYY-MM': row}}. Read again only when they have changed."""
    if not available():
        return {}
    key = version()
    with _lock:
        if _memo["key"] == key:
            return _memo["table"]
    out = {}
    for r in rows():
        out.setdefault(r["yarn_key"], {})[r["month"]] = r
    with _lock:
        _memo.update(key=key, table=out)
    return out


def add(entries, who="", keep=None):
    """Add dated rates, in one transaction. Each entry: yarn_key, month ('YYYY-MM'), rate, low, high, entries, basis,
    source, detail (a dict). An active rate for the same yarn and month is marked replaced and kept, unless keep(row)
    says it must stay (then the entry is not added). Returns (added, kept back): the rows added, and the entries not
    added because of keep."""
    added, held = [], []
    with store.get().tx(write="dated") as c:
        for e in entries:
            vf = e["month"] + "-01"
            old = [_row(r) for r in c.all(f"SELECT {', '.join(COLS)} FROM yarn_rate_dated WHERE yarn_key = %s AND valid_from = %s "
                                          "AND removed_at IS NULL ORDER BY id", (e["yarn_key"], vf))]
            if keep and any(keep(o) for o in old):
                held.append(e)
                continue
            for o in old:
                c.run("UPDATE yarn_rate_dated SET removed_at = %s, removed_by = %s, removed_why = 'replaced' WHERE id = %s",
                      (_now(), who or "", o["id"]))
            c.run("INSERT INTO yarn_rate_dated (yarn_key, valid_from, rate, low, high, entries, basis, source, detail, entered_by, entered_at) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                  (e["yarn_key"], vf, float(e["rate"]), None if e.get("low") is None else float(e["low"]),
                   None if e.get("high") is None else float(e["high"]), int(e.get("entries") or 1), e["basis"], e["source"],
                   json.dumps(e.get("detail") or {}, default=str), who or "", _now()))
            added.append(e)
    return added, held


def remove(rate_id, who=""):
    """Take one dated rate out (kept, marked removed). Returns how many were taken out (0 or 1)."""
    with store.get().tx(write="dated") as c:
        return c.run("UPDATE yarn_rate_dated SET removed_at = %s, removed_by = %s, removed_why = 'removed' "
                     "WHERE id = %s AND removed_at IS NULL", (_now(), who or "", int(rate_id))).rowcount
