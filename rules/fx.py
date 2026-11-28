"""Exchange rates by month (GP's decisions, 28 Nov 2026): rupees per unit of a currency, so an import purchase line (USD,
EUR ...) is shown in rupees, apart from the rupee figures. Prices > Exchange rates; kept in the database only.

The rule (RULE below, also on the page):
- one rate per currency and month, the month's: by default the RBI (FBIL) reference rate, its monthly average, entered
  with the source "RBI reference rate";
- a person may enter the rate actually paid for a month (source "rate paid"): it takes the RBI rate's place for that month,
  which is kept, marked replaced; an RBI rate entered later never replaces a rate paid;
- a later rate of the same source replaces the earlier (kept, marked replaced);
- a rate entered with no source counts as a Placeholder (rule 4): used, and said;
- nothing is seeded: a month with no rate leaves the line's rupee price blank, and says why. Rates are never made up.
Entering a rate is a rates editor's or an admin's action (do:edit_rates)."""
import datetime as dt
import re

from rules import common
import store

KIND = "fx"
RBI, PAID, PLACEHOLDER = "RBI reference rate", "rate paid", "Placeholder"
SOURCES = (RBI, PAID)
RULE = ("One rate per currency and month: the RBI (FBIL) reference rate, the month's average, by default; the rate actually "
        "paid, where it is entered, takes its place for that month (the RBI rate kept, marked replaced). A later rate of the same "
        "source replaces the earlier. A rate entered with no source counts as a Placeholder. A month with no rate leaves the "
        "rupee price blank, and says why: nothing is made up.")
NEEDS_DB = ("Exchange rates are kept in the database, and this server keeps its data in files (the app setting DATABASE_URL is "
            "not set). Import lines are shown in their own currency until it is.")


def need_db():
    st = store.get()
    if st.kind == "files":
        raise common.Refused(503, NEEDS_DB)
    return st


def _rows(c, every=False):
    sql = "SELECT id, currency, month, rate, source, note, entered_by, entered_at, removed_at, removed_by, removed_why FROM fx_rate"
    cur = c.run(sql + ("" if every else " WHERE removed_at IS NULL") + " ORDER BY currency, month, id").cur
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def kind_of(source):
    """What a source is: 'paid' (the rate actually paid), 'rbi' (the RBI reference rate, however its average is described:
    "RBI reference rate (average of 19 daily FBIL rates)"), or 'placeholder'."""
    t = str(source or "").strip().lower()
    return "paid" if t.startswith(PAID) else "rbi" if t.startswith(RBI.lower()) else "placeholder"


def _rank(r):
    """Which rate holds where several are kept for one month: a rate paid, then the RBI rate, then a placeholder; the latest."""
    return ({"paid": 3, "rbi": 2}.get(kind_of(r["source"]), 1), r["id"])


_memo = {"v": None, "val": None}


def table():
    """{(currency, 'YYYY-MM'): {rate, source, id}}: the rate in force for each month (cached until a rate changes)."""
    st = store.get()
    if st.kind == "files":
        return {}
    v = st.version(KIND)
    if _memo["v"] != v:
        with st.tx() as c:
            rows = _rows(c)
        out = {}
        for r in rows:
            k = (r["currency"], r["month"][:7])
            if k not in out or _rank(r) > _rank(out[k]):
                out[k] = r
        _memo.update(v=v, val={k: {"rate": float(r["rate"]), "source": r["source"], "id": r["id"], "note": r["note"]} for k, r in out.items()})
    return _memo["val"]


def rate_for(currency, day, tab=None):
    """(rate, words) for a currency on a day (its month's rate), or (None, why not)."""
    cur = (currency or "").upper()
    if cur == "INR":
        return 1.0, "rupees"
    if not cur:
        return None, "no currency on the line"
    if not day:
        return None, "no date on the line"
    hit = (tab if tab is not None else table()).get((cur, day[:7]))
    if hit is None:
        return None, f"no exchange rate for {cur} in {dt.date.fromisoformat(day[:7] + '-01'):%b %Y} yet (Prices > Exchange rates)"
    return hit["rate"], f"{cur} at Rs {hit['rate']:,.4g} ({hit['source']}, {dt.date.fromisoformat(day[:7] + '-01'):%b %Y})"


def rates():
    """Prices > Exchange rates: every rate in force and every one kept, and the months and currencies the purchase history's
    import lines need, with or without a rate."""
    st = need_db()
    with st.tx() as c:
        rows = _rows(c, every=True)
        need = c.all("SELECT currency, substr(doc_date, 1, 7), count(*) FROM purchase_line WHERE currency IS NOT NULL AND currency <> 'INR' "
                     "AND doc_date IS NOT NULL AND fabric_id IS NOT NULL GROUP BY currency, substr(doc_date, 1, 7) ORDER BY 1, 2")
    tab = table()
    in_force = {r["id"] for r in tab.values()}
    for r in rows:
        r["in_force"] = r["id"] in in_force
        r["month"] = r["month"][:7]
        if not r["in_force"] and not r["removed_at"]:
            r["removed_why"] = "replaced: a rate paid holds for this month" if kind_of(r["source"]) != "paid" else "replaced by a later rate paid"
    needed = [{"currency": cur, "month": m, "lines": n, "rate": (tab.get((cur, m)) or {}).get("rate"), "source": (tab.get((cur, m)) or {}).get("source")}
              for cur, m, n in need]
    return {"rule": RULE, "sources": list(SOURCES), "rates": rows, "needed": needed,
            "missing": sum(1 for x in needed if x["rate"] is None)}


def add(payload, who=""):
    """A rate entered: {currency, month (YYYY-MM), rate (rupees per unit), source ("RBI reference rate" | "rate paid"; none:
    Placeholder), note}. It takes the place of the rate of the same source for that month (kept, marked replaced); a rate
    paid holds over the RBI rate whatever the order they come in. An action of a rates editor or an admin (do:edit_rates)."""
    st = need_db()
    p = payload or {}
    cur = str(p.get("currency") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", cur) or cur == "INR":
        raise common.Refused(400, "Give the currency as its three-letter code (USD, EUR ...), not INR.")
    m = str(p.get("month") or "").strip()[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", m):
        raise common.Refused(400, "Give the month as YYYY-MM.")
    try:
        month = dt.date.fromisoformat(m + "-01")
    except ValueError:
        raise common.Refused(400, f"{m} is not a month.")
    if month > dt.date.today().replace(day=1):
        raise common.Refused(400, f"{m} is still to come: a rate is for a month that has begun.")
    try:
        rate = float(p.get("rate"))
    except (TypeError, ValueError):
        raise common.Refused(400, "Give the rate as a number of rupees per unit of the currency.")
    if not 0.01 <= rate <= 100000:
        raise common.Refused(400, f"Rs {rate:g} per {cur} cannot be right: give rupees per unit of the currency.")
    source = re.sub(r"\s+", " ", str(p.get("source") or "").strip())[:200]
    if source.lower() in ("rbi", "fbil"):
        source = RBI
    elif not source:
        source = PLACEHOLDER
    elif kind_of(source) == "placeholder":
        raise common.Refused(400, f'The source is "{RBI}" (its average may be said in brackets) or "{PAID}" (leave it empty and the rate counts as a Placeholder).')
    note = str(p.get("note") or "").strip()[:300]
    now = store._now()
    with st.tx(write=KIND) as c:
        same = [r for r in _rows(c) if r["currency"] == cur and r["month"][:7] == m and kind_of(r["source"]) == kind_of(source)]
        for r in same:
            c.run("UPDATE fx_rate SET removed_at = %s, removed_by = %s, removed_why = %s WHERE id = %s", (now, who or "", "replaced", r["id"]))
        c.run("INSERT INTO fx_rate (currency, month, rate, source, note, entered_by, entered_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
              (cur, m + "-01", rate, source, note, who or "", now))
        new_id = c.one("SELECT max(id) FROM fx_rate")[0]
    held = table().get((cur, m))
    return {"id": new_id, "currency": cur, "month": m, "rate": rate, "source": source, "replaced": len(same), "in_force": bool(held and held["id"] == new_id),
            "said": None if held and held["id"] == new_id else "kept, but the rate paid holds for this month"}


def import_file(filename, data, who=""):
    """A table of rates brought in as it is (.csv or .xlsx), one rate per row: month (YYYY-MM), currency, rate (or rate_inr:
    rupees per unit), and its source (a "source" column, else RBI's reference rate, described by a "days" or "method" column:
    "RBI reference rate (average of 19 daily FBIL rates)"), and a note (a "note" column, else the "source_url"). Every row is
    checked first; nothing is entered unless every row reads. Each is entered as on the page (add): it takes the place of the
    month's rate of the same kind, and a rate paid holds over the RBI rate."""
    import io
    import pandas as pd
    need_db()
    name = str(filename or "").lower()
    try:
        df = (pd.read_csv(io.BytesIO(data), dtype=str) if name.endswith(".csv") else pd.read_excel(io.BytesIO(data), dtype=str)
              if name.endswith((".xlsx", ".xls")) else None)
    except Exception as e:
        raise common.Refused(400, f"{filename} could not be read as a table ({type(e).__name__}).")
    if df is None:
        raise common.Refused(400, "Bring in the rates as a .csv or an .xlsx table: month, currency, rate (rupees per unit), source.")
    df = df.fillna("")
    df.columns = [str(x).strip().lower() for x in df.columns]
    rate_col = next((x for x in ("rate_inr", "rate", "rs per unit", "inr") if x in df.columns), None)
    missing = [x for x, ok in (("month", "month" in df.columns), ("currency", "currency" in df.columns), ("rate", rate_col)) if not ok]
    if missing:
        raise common.Refused(400, f"{filename} needs the columns month, currency and rate (or rate_inr); missing: {', '.join(missing)}.")
    rows, bad = [], []
    for i, r in enumerate(df.to_dict("records"), start=2):
        src = str(r.get("source", "")).strip()
        if not src:
            days, method = str(r.get("days", "")).strip(), str(r.get("method", "")).strip()
            src = f"{RBI} (average of {days} daily FBIL rates)" if days.isdigit() else f"{RBI} ({method})" if method else RBI
        payload = {"currency": r.get("currency"), "month": r.get("month"), "rate": r.get(rate_col), "source": src,
                   "note": str(r.get("note", "")).strip() or str(r.get("source_url", "")).strip()}
        try:
            float(payload["rate"])
            if not re.fullmatch(r"\d{4}-\d{2}", str(payload["month"]).strip()[:7]) or not re.fullmatch(r"[A-Za-z]{3}", str(payload["currency"]).strip()):
                raise ValueError
        except (TypeError, ValueError):
            bad.append(i)
        rows.append(payload)
    if bad:
        raise common.Refused(400, f"Rows {', '.join(map(str, bad[:10]))} of {filename} do not read as a month (YYYY-MM), a currency and a rate. Nothing was entered.")
    if not rows:
        raise common.Refused(400, f"{filename} has no rate in it.")
    done = [add(p_, who=who) for p_ in rows]
    return {"entered": len(done), "in_force": sum(1 for d in done if d["in_force"]), "replaced": sum(d["replaced"] for d in done),
            "currencies": sorted({d["currency"] for d in done}), "months": sorted({d["month"] for d in done}), "rows": done}
