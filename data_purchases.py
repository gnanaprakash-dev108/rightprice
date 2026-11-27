"""The purchase history's tables (db/002_purchases_and_fab_groups.sql): mills and every way they are written, fabric
codes, Fab groups, uploads and purchase-order lines. Only SQL: what is decided about them is in rules/purchases.py and
rules/fab_groups.py. Every function takes the cursor of a transaction opened with store.get().tx(); none of this is
reached on the files store (the purchase history needs a database)."""
import json

import store

KIND = "purchases"          # store.KINDS: writers wait for each other, and the version moves with every change


def _many(c, sql, rows):
    """One statement for many rows (psycopg sends them together; SQLite runs them in one go)."""
    rows = [tuple(r) for r in rows]
    if rows:
        c.cur.executemany(sql if c.kind == "postgres" else sql.replace("%s", "?"), rows)


def _chunks(items, n=500):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _dicts(c, sql, params=()):
    cur = c.run(sql, params).cur
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


# ------------------------------------------------------------------ mills
def mills(c):
    """{id: {"id", "key", "name"}}"""
    return {r["id"]: r for r in _dicts(c, "SELECT id, key, name FROM mill ORDER BY id")}


def aliases(c):
    """{spelling as received: mill id}"""
    return dict(c.all("SELECT spelling, mill_id FROM mill_alias"))


def add_mill(c, key, name, at):
    c.run("INSERT INTO mill (key, name, added_at) VALUES (%s, %s, %s)", (key, name, at))
    return c.one("SELECT id FROM mill WHERE key = %s", (key,))[0]


def set_mill(c, mill_id, key, name):
    c.run("UPDATE mill SET key = %s, name = %s WHERE id = %s", (key, name, mill_id))


def add_aliases(c, rows, at):
    """rows: (spelling, mill id)"""
    _many(c, "INSERT INTO mill_alias (spelling, mill_id, added_at) VALUES (%s, %s, %s)", [(s, m, at) for s, m in rows])


# ------------------------------------------------------------------ fabrics
FABRIC = "id, code, description, fab_group_id, not_grouped, spec, choices, problems"


def _fabric(r):
    r = dict(r)
    for k, empty in (("spec", None), ("choices", None), ("problems", [])):
        r[k] = json.loads(r[k]) if r.get(k) else empty
    return r


def fabrics(c, codes=None, ids=None, group_ids=None):
    """{code: fabric} for these codes (or ids, or Fab group ids), or every fabric."""
    out = {}
    if codes is None and ids is None and group_ids is None:
        return {r["code"]: _fabric(r) for r in _dicts(c, f"SELECT {FABRIC} FROM fabric ORDER BY id")}
    col, vals = ("code", codes) if codes is not None else (("id", ids) if ids is not None else ("fab_group_id", group_ids))
    for part in _chunks(sorted(set(vals))):
        for r in _dicts(c, f"SELECT {FABRIC} FROM fabric WHERE {col} IN {store._in(len(part))} ORDER BY id", part):
            out[r["code"]] = _fabric(r)
    return out


def fabric_groups(c):
    """{fabric code: (Fab group id, why not grouped)}, for every fabric: what Right cost's column needs."""
    return {code: (g, why) for code, g, why in c.all("SELECT code, fab_group_id, not_grouped FROM fabric")}


def add_fabrics(c, rows, at):
    """rows: dicts with code, description, spec, fab_group_id, not_grouped. Returns {code: id}."""
    _many(c, "INSERT INTO fabric (code, description, spec, fab_group_id, not_grouped, problems, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
          [(r["code"], r.get("description") or "", None if r.get("spec") is None else json.dumps(r["spec"]), r.get("fab_group_id"),
            r.get("not_grouped"), "[]", at) for r in rows])
    return {code: i for code, i in ids_of(c, [r["code"] for r in rows]).items()}


def ids_of(c, codes):
    out = {}
    for part in _chunks(sorted(set(codes))):
        out.update(dict(c.all(f"SELECT code, id FROM fabric WHERE code IN {store._in(len(part))}", part)))
    return out


def set_choices(c, rows, at):
    """rows: dicts with id, choices and problems: the costing choices worked out again."""
    _many(c, "UPDATE fabric SET choices = %s, problems = %s, updated_at = %s WHERE id = %s",
          [(None if r["choices"] is None else json.dumps(r["choices"], default=str), json.dumps(r["problems"]), at, r["id"]) for r in rows])


def set_fabrics(c, rows, at):
    """rows: dicts with id and any of description, spec, fab_group_id, not_grouped, choices, problems."""
    for r in rows:
        sets, vals = [], []
        for k in ("description", "fab_group_id", "not_grouped"):
            if k in r:
                sets.append(f"{k} = %s")
                vals.append(r[k])
        for k in ("spec", "choices", "problems"):
            if k in r:
                sets.append(f"{k} = %s")
                vals.append(None if r[k] is None else json.dumps(r[k], default=str))
        if sets:
            c.run(f"UPDATE fabric SET {', '.join(sets)}, updated_at = %s WHERE id = %s", vals + [at, r["id"]])


# ------------------------------------------------------------------ Fab groups
GROUP = ("id, code, name, content, route, weave, warp, weft, epi, ppi, width_in, finish, signature, merged_into, merged_at, "
         "merged_by, created_at, upload_id")


def groups(c):
    """{id: group}, every group, merged ones included."""
    return {r["id"]: r for r in _dicts(c, f"SELECT {GROUP} FROM fab_group ORDER BY id")}


def group_ids_by_signature(c, signatures):
    out = {}
    for part in _chunks(sorted(set(signatures))):
        out.update(dict(c.all(f"SELECT signature, id FROM fab_group WHERE signature IN {store._in(len(part))}", part)))
    return out


def last_group_number(c):
    """The highest number a Fab group code has had (0 for none): codes are never handed out again."""
    return max((int(code.split("-")[1]) for (code,) in c.all("SELECT code FROM fab_group")), default=0)


def add_groups(c, rows, at, upload_id):
    """rows: (code, name, fields, signature). Returns {signature: id}."""
    _many(c, "INSERT INTO fab_group (code, name, content, route, weave, warp, weft, epi, ppi, width_in, finish, signature, created_at, upload_id) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(code, name, f["content"], f["route"], f["weave"], f["warp"], f["weft"], f["epi"], f["ppi"], f["width_in"], f["finish"], sig, at, upload_id)
           for code, name, f, sig in rows])
    return group_ids_by_signature(c, [r[3] for r in rows])


def set_merged(c, group_id, into_id, at, who):
    c.run("UPDATE fab_group SET merged_into = %s, merged_at = %s, merged_by = %s WHERE id = %s", (into_id, at, who, group_id))


# ------------------------------------------------------------------ uploads
UPLOAD = ("id, kind, filename, uploaded_by, uploaded_at, status, step, started_at, finished_at, alive_at, error, rows_total, "
          "rows_loaded, rows_new, rows_changed, rows_same, rows_removed, rows_skipped, fabrics_new, groups_new, mills_new, summary, sha256")


def add_upload(c, kind, filename, who, data, sha, at):
    c.run("INSERT INTO upload (kind, filename, uploaded_by, uploaded_at, status, file, sha256) VALUES (%s, %s, %s, %s, 'queued', %s, %s)",
          (kind, filename, who or "", at, data, sha))
    return c.one("SELECT max(id) FROM upload")[0]


def _upload(r):
    r = dict(r)
    r["summary"] = json.loads(r["summary"]) if r.get("summary") else {}
    if "skipped" in r:
        r["skipped"] = json.loads(r["skipped"]) if r.get("skipped") else []
    return r


def uploads(c, limit=50):
    return [_upload(r) for r in _dicts(c, f"SELECT {UPLOAD} FROM upload ORDER BY id DESC LIMIT {int(limit)}")]


def upload(c, upload_id, skipped=False):
    rows = _dicts(c, f"SELECT {UPLOAD}{', skipped' if skipped else ''} FROM upload WHERE id = %s", (upload_id,))
    return _upload(rows[0]) if rows else None


def upload_file(c, upload_id):
    r = c.one("SELECT file FROM upload WHERE id = %s", (upload_id,))
    return None if r is None or r[0] is None else bytes(r[0])


def set_upload(c, upload_id, **fields):
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(json.dumps(v, default=str) if k in ("skipped", "summary") else v)
    c.run(f"UPDATE upload SET {', '.join(sets)} WHERE id = %s", vals + [upload_id])


def waiting_uploads(c):
    """Uploads not finished: (id, status, alive_at), oldest first."""
    return c.all("SELECT id, status, alive_at FROM upload WHERE status IN ('queued', 'working') ORDER BY id")


# ------------------------------------------------------------------ purchase lines
LINE = "po_number, item, doc_date, doc_type, fabric_id, mill_id, supplier, qty_m, price, upload_id, removed_upload_id"


def lines_by_key(c, keys):
    """{(po_number, item): line} for the order lines already held among these."""
    out, pos = {}, sorted({k[0] for k in keys})
    want = set(keys)
    for part in _chunks(pos):
        for r in _dicts(c, f"SELECT id, {LINE} FROM purchase_line WHERE po_number IN {store._in(len(part))}", part):
            if (r["po_number"], r["item"]) in want:
                out[(r["po_number"], r["item"])] = r
    return out


def add_lines(c, rows):
    """rows: dicts with the columns of LINE (removed_upload_id left empty)."""
    _many(c, "INSERT INTO purchase_line (po_number, item, doc_date, doc_type, fabric_id, mill_id, supplier, qty_m, price, upload_id) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(r["po_number"], r["item"], r["doc_date"], r["doc_type"], r["fabric_id"], r["mill_id"], r["supplier"], r["qty_m"], r["price"],
            r["upload_id"]) for r in rows])


def change_lines(c, rows):
    """rows: dicts with id and the columns of LINE: the newer figures kept, the line counted again."""
    _many(c, "UPDATE purchase_line SET doc_date = %s, doc_type = %s, fabric_id = %s, mill_id = %s, supplier = %s, qty_m = %s, price = %s, "
             "upload_id = %s, removed_upload_id = NULL WHERE id = %s",
          [(r["doc_date"], r["doc_type"], r["fabric_id"], r["mill_id"], r["supplier"], r["qty_m"], r["price"], r["upload_id"], r["id"])
           for r in rows])


def remove_lines(c, ids, upload_id):
    _many(c, "UPDATE purchase_line SET removed_upload_id = %s WHERE id = %s", [(upload_id, i) for i in ids])


def lines(c, fabric_ids):
    """The lines still counted for these fabrics, with the fabric code and the mill, oldest first."""
    out = []
    for part in _chunks(sorted(set(fabric_ids))):
        out += _dicts(c, "SELECT l.id, l.po_number, l.item, l.doc_date, l.doc_type, l.qty_m, l.price, l.supplier, l.fabric_id, "
                         "f.code AS fabric_code, l.mill_id, m.name AS mill, m.key AS mill_key "
                         "FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id JOIN mill m ON m.id = l.mill_id "
                         f"WHERE l.removed_upload_id IS NULL AND l.fabric_id IN {store._in(len(part))}", part)
    out.sort(key=lambda r: (r["doc_date"], r["po_number"], r["item"]))
    return out


def group_stats(c):
    """{Fab group id of the fabric: (lines, metres, mills, last date)} over the lines still counted."""
    out = {}
    for g, n, metres, mills_, last in c.all(
            "SELECT f.fab_group_id, count(*), sum(l.qty_m), count(DISTINCT l.mill_id), max(l.doc_date) FROM purchase_line l "
            "JOIN fabric f ON f.id = l.fabric_id WHERE l.removed_upload_id IS NULL AND f.fab_group_id IS NOT NULL GROUP BY f.fab_group_id"):
        out[g] = (n, metres, mills_, last)
    return out


def prices_by_group(c):
    """{Fab group id of the fabric: [prices]} over the lines still counted (for the median on the list of groups)."""
    out = {}
    for g, p in c.all("SELECT f.fab_group_id, l.price FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
                      "WHERE l.removed_upload_id IS NULL AND f.fab_group_id IS NOT NULL"):
        out.setdefault(g, []).append(p)
    return out


def metres(c, fabric_ids):
    """{fabric id: metres on the lines still counted}"""
    out = {}
    for part in _chunks(sorted(set(fabric_ids))):
        out.update(dict(c.all(f"SELECT fabric_id, sum(qty_m) FROM purchase_line WHERE removed_upload_id IS NULL AND fabric_id IN "
                              f"{store._in(len(part))} GROUP BY fabric_id", part)))
    return out


def counts(c):
    one = lambda sql: c.one(sql)[0]
    return {"lines": one("SELECT count(*) FROM purchase_line WHERE removed_upload_id IS NULL"),
            "lines_removed": one("SELECT count(*) FROM purchase_line WHERE removed_upload_id IS NOT NULL"),
            "fabrics": one("SELECT count(*) FROM fabric"), "fabrics_grouped": one("SELECT count(*) FROM fabric WHERE fab_group_id IS NOT NULL"),
            "groups": one("SELECT count(*) FROM fab_group WHERE merged_into IS NULL"),
            "groups_merged": one("SELECT count(*) FROM fab_group WHERE merged_into IS NOT NULL"),
            "mills": one("SELECT count(*) FROM mill"), "first": one("SELECT min(doc_date) FROM purchase_line WHERE removed_upload_id IS NULL"),
            "last": one("SELECT max(doc_date) FROM purchase_line WHERE removed_upload_id IS NULL")}
