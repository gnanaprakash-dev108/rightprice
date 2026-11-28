"""Purchase lines (GP's decision, 28 Nov 2026): every stored line of the purchase files in one list (under Purchase
history), with its SAP type and order type, mode of sourcing (Domestic: rupees; Import: any other currency), quantity and
unit, price in the PO's currency per its unit, the exchange rate of its month, its price and value in rupees, its Fab group
and its construction (from the Fab library); filtered on each, paged and filtered on the server (it stays quick with a
million lines), and downloaded to Excel as filtered. Read only; the table of order types is changed on the same page
(rules/purchases.py set_order_type, a rates editor's or an admin's action)."""
import datetime as dt
import io
import json
import os
import re
import tempfile

from rules import common, fab_groups, fx, purchases
import data_purchases as dp
import store

PAGE, MAX_PAGE = 100, 500
EXCEL_MAX = 1048575                 # rows an Excel sheet holds, below its headings
FILTERS = ("order_type", "sourcing", "unit", "currency", "mill", "month", "group", "code", "counts")


def _where(f, types):
    """The SQL of the filters asked for: (where, params). Every filter is on purchase_line's own columns, so the count and
    the page are read straight from the table."""
    sql, args = ["l.fabric_id IS NOT NULL", "l.doc_date IS NOT NULL"], []
    ot = f.get("order_type")
    if ot:
        if ot not in purchases.CATEGORIES:
            raise common.Refused(400, "The order type is one of " + ", ".join(purchases.CATEGORIES) + ".")
        held = sorted(types)
        mine = sorted(t for t, c in types.items() if c == ot)
        if ot == "Other":
            sql.append("(l.doc_type IS NULL OR l.doc_type NOT IN " + store._in(len(held)) + (" OR l.doc_type IN " + store._in(len(mine)) if mine else "") + ")")
            args += held + mine
        elif mine:
            sql.append("l.doc_type IN " + store._in(len(mine)))
            args += mine
        else:
            sql.append("1 = 0")
    src = f.get("sourcing")
    if src:
        if src not in ("Domestic", "Import"):
            raise common.Refused(400, "Mode of sourcing is Domestic or Import.")
        sql.append("l.currency = 'INR'" if src == "Domestic" else "(l.currency IS NULL OR l.currency <> 'INR')")
    for k, col in (("unit", "l.unit"), ("currency", "l.currency")):
        v = str(f.get(k) or "").strip()
        if v:
            sql.append(f"{col} = %s")
            args.append(v)
    if f.get("mill"):
        sql.append("l.mill_id IN (SELECT id FROM mill WHERE key = %s OR name = %s)")
        args += [str(f["mill"]), str(f["mill"])]
    m = str(f.get("month") or "").strip()
    if m:
        if not re.fullmatch(r"\d{4}-\d{2}", m):
            raise common.Refused(400, "Give the month as YYYY-MM.")
        d = dt.date.fromisoformat(m + "-01")
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        sql.append("l.doc_date >= %s AND l.doc_date < %s")
        args += [d.isoformat(), nxt.isoformat()]
    g = str(f.get("group") or "").strip()
    if g:
        sql.append("l.fabric_id IN (SELECT f.id FROM fabric f JOIN fab_group fg ON fg.id = f.fab_group_id WHERE lower(fg.code) = %s OR fg.merged_into IN "
                   "(SELECT id FROM fab_group WHERE lower(code) = %s))")
        args += [g.lower(), g.lower()]
    code = str(f.get("code") or "").strip()
    if code:
        sql.append("l.fabric_id IN (SELECT id FROM fabric WHERE code = %s OR code = %s)")
        args += [code, code.upper()]
    cnt = f.get("counts")
    if cnt == "counts":
        sql.append("l.removed_upload_id IS NULL")
    elif cnt == "apart":
        sql.append("l.removed_upload_id IS NOT NULL")
    return " AND ".join(sql), args


COLS = ("l.id, l.po_number, l.item, l.doc_date, l.doc_type, l.qty_po, l.unit, l.price_po, l.currency, l.qty_m, l.price, l.not_counted, "
        "l.removed_upload_id, l.removed_why, l.deletion, l.fabric_id, l.mill_id")


def _rows(c, where, args, limit=None, offset=0, after=None):
    q = f"SELECT {COLS} FROM purchase_line l WHERE {where}"
    if after is not None:
        q += " AND l.id > %s ORDER BY l.id"
        args = list(args) + [after]
    else:
        q += " ORDER BY l.doc_date DESC, l.po_number DESC, l.item"
    if limit:
        q += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    cur = c.run(q, args).cur
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _gather(c, rows):
    """Inside a transaction: the fabrics and mills these lines name."""
    fids = sorted({r["fabric_id"] for r in rows})
    fabs = {f["id"]: f for f in dp.fabrics(c, ids=fids).values()} if fids else {}
    return fabs, {i: m["name"] for i, m in dp.mills(c).items()}


def _shape(rows, fabs, mills, types, rates, groups):
    """Each line as the page shows it (outside a transaction: the Fab library is read for the construction)."""
    from rules import fab_library
    lib = fab_library.specs_for([f["code"] for f in fabs.values()]) or {}
    out = []
    for r in rows:
        f = fabs.get(r["fabric_id"]) or {}
        cur = (r["currency"] or "").upper()
        price_po = r["price_po"] if r["price_po"] is not None else (r["price"] if cur in ("", "INR") else None)
        qty_po = r["qty_po"] if r["qty_po"] is not None else r["qty_m"]
        rate, why = fx.rate_for(cur or "INR", r["doc_date"], rates) if price_po else (None, "no price on the line")
        rs = None if rate is None or price_po is None else round(float(price_po) * rate, 4)
        g = groups.get(fab_groups.final(groups, f.get("fab_group_id"))) if f.get("fab_group_id") is not None else None
        spec = lib.get(f.get("code")) or f.get("spec")
        out.append({"po": r["po_number"], "item": r["item"], "date": r["doc_date"], "code": f.get("code"), "mill": mills.get(r["mill_id"]),
                    "sap_type": r["doc_type"] or "", "order_type": types.get(r["doc_type"] or "", "Other"), "sourcing": "Domestic" if cur in ("", "INR") else "Import",
                    "qty": None if qty_po is None else round(float(qty_po), 3), "unit": r["unit"] or "", "price": None if price_po is None else round(float(price_po), 4),
                    "currency": cur or "", "rate": None if cur in ("", "INR") else rate, "rate_why": None if rate is not None or cur in ("", "INR") else why,
                    "price_rs": rs, "value_rs": None if rs is None or qty_po is None else round(rs * float(qty_po), 2),
                    "counts": r["removed_upload_id"] is None, "why": None if r["removed_upload_id"] is None else (r["not_counted"] or (r["removed_why"] or "").split(": ", 1)[-1]),
                    "deletion": r["deletion"] or "", "group": g["code"] if g else None,
                    "construction": purchases_construction(spec)})
    return out


def purchases_construction(spec):
    if not spec:
        return ""
    from rules import fab_library
    return fab_library._construction(fab_groups.short_spec(spec))


_facets = {"key": None, "val": None}


def facets():
    """What each filter can be set to, with how many lines (over the whole history; kept until it changes)."""
    st = store.get()
    key = (st.version(dp.KIND), st.version(fx.KIND))
    if _facets["key"] != key:
        with st.tx() as c:
            one = lambda col: [(v, n) for v, n in c.all(f"SELECT {col}, count(*) FROM purchase_line l WHERE l.fabric_id IS NOT NULL AND l.doc_date IS NOT NULL "
                                                         f"GROUP BY {col} ORDER BY 2 DESC")]
            types = purchases.order_types(c)
            by_type = one("coalesce(l.doc_type, '')")
            val = {"units": one("coalesce(l.unit, '')"), "currencies": one("coalesce(l.currency, '')"),
                   "months": sorted(one("substr(l.doc_date, 1, 7)"), reverse=True),
                   "mills": [(name, n) for name, n in c.all("SELECT m.name, count(*) FROM purchase_line l JOIN mill m ON m.id = l.mill_id "
                                                             "WHERE l.fabric_id IS NOT NULL GROUP BY m.name ORDER BY 2 DESC")],
                   "sap_types": by_type}
            cats = {}
            for t, n in by_type:
                cats[types.get(t, "Other")] = cats.get(types.get(t, "Other"), 0) + n
            val["order_types"] = [(k, cats.get(k, 0)) for k in purchases.CATEGORIES]
            val["total"] = sum(n for _, n in by_type)
        _facets.update(key=key, val=val)
    return _facets["val"]


def listing(params):
    """One page of the purchase lines, filtered; with the count of every line the filters keep and what each filter can be."""
    st = fab_groups.need_db()
    p = dict(params or {})
    try:
        page = max(1, int(p.get("page") or 1))
        size = max(10, min(MAX_PAGE, int(p.get("size") or PAGE)))
    except (TypeError, ValueError):
        raise common.Refused(400, "page and size are whole numbers.")
    rates = fx.table()
    with st.tx() as c:
        types = purchases.order_types(c)
        where, args = _where(p, types)
        total = c.one(f"SELECT count(*) FROM purchase_line l WHERE {where}", args)[0]
        rows = _rows(c, where, args, limit=size, offset=(page - 1) * size)
        groups = dp.groups(c)
        fabs, mills = _gather(c, rows)
    shaped = _shape(rows, fabs, mills, types, rates, groups)
    return {"rows": shaped, "total": total, "page": page, "size": size, "pages": max(1, -(-total // size)), "filters": {k: p.get(k) for k in FILTERS if p.get(k)},
            "facets": facets(), "excel_max": EXCEL_MAX,
            "note": "Only domestic bulk orders per metre count in prices, ranges and verdicts; ZLOI is kept apart; imports are shown in rupees on "
                    "their month's exchange rate (blank, with why, where none is entered); lines per kg have their own per-kg figures."}


HEADS = [("po", "Purchasing Document"), ("item", "Item"), ("date", "Document Date"), ("code", "Fabric code"), ("mill", "Mill"), ("sap_type", "SAP type"),
         ("order_type", "Order type"), ("sourcing", "Mode of sourcing"), ("qty", "Quantity"), ("unit", "Unit"), ("price", "Price (PO currency, per unit)"),
         ("currency", "Currency"), ("rate", "Exchange rate (Rs per unit of currency)"), ("price_rs", "Price Rs (per unit)"), ("value_rs", "Value Rs"),
         ("counts", "Counts in the figures"), ("why", "Why not"), ("group", "Fab group"), ("construction", "Construction (Fab library)"), ("rate_why", "Rupees blank because")]


def download(params):
    """The lines the filters keep, as an Excel workbook (written as it is read, a few thousand lines at a time)."""
    import xlsxwriter
    st = fab_groups.need_db()
    p = dict(params or {})
    with st.tx() as c:
        types = purchases.order_types(c)
        where, args = _where(p, types)
        total = c.one(f"SELECT count(*) FROM purchase_line l WHERE {where}", args)[0]
        groups = dp.groups(c)
    if total > EXCEL_MAX:
        raise common.Refused(413, f"{total:,} lines are more than an Excel sheet holds ({EXCEL_MAX:,}): filter by month or by order type first.")
    rates = fx.table()
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        wb = xlsxwriter.Workbook(path, {"constant_memory": True})
        ws = wb.add_worksheet("Purchase lines")
        for j, (_, h) in enumerate(HEADS):
            ws.write(0, j, h)
        i, after = 1, 0
        while True:
            with st.tx() as c:
                rows = _rows(c, where, args, limit=5000, after=after)
                fabs, mills = _gather(c, rows) if rows else ({}, {})
            if not rows:
                break
            after = rows[-1]["id"]
            shaped = _shape(rows, fabs, mills, types, rates, groups)
            for r in shaped:
                for j, (k, _) in enumerate(HEADS):
                    v = r[k]
                    ws.write(i, j, ("yes" if v else "no") if k == "counts" else v)
                i += 1
        wb.close()
        with open(path, "rb") as f:
            data = f.read()
    finally:
        os.remove(path)
    return common.Download(data, "Purchase lines.xlsx")
