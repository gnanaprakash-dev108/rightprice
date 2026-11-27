"""The purchase history's tables (db/002_purchases_and_fab_groups.sql): mills and every way they are written, fabric
codes, Fab groups, uploads and purchase-order lines. Only SQL: what is decided about them is in rules/purchases.py and
rules/fab_groups.py. Every function takes the cursor of a transaction opened with store.get().tx(); none of this is
reached on the files store (the purchase history needs a database).

ZLOI order lines are kept like any other, but every figure worked out here leaves them out (GP's decision, 27 Nov
2026); `outliers` reads them apart."""
import json

import store

KIND = "purchases"          # store.KINDS: writers wait for each other, and the version moves with every change
STATUS = "purchase_status"  # a job's progress and signs of life: written without moving the version (no page needs redoing)
OUTLIER_TYPES = ("ZLOI",)   # order types kept but left out of every calculation (GP, 27 Nov 2026)
_NOT_OUTLIER = "l.doc_type NOT IN (" + ", ".join(f"'{t}'" for t in OUTLIER_TYPES) + ")"
_OUTLIER = "l.doc_type IN (" + ", ".join(f"'{t}'" for t in OUTLIER_TYPES) + ")"


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
FABRIC = "id, code, description, fab_group_id, not_grouped, signature, spec, spec_sha, choices, problems"


def _fabric(r):
    r = dict(r)
    for k, empty in (("spec", None), ("choices", None), ("problems", [])):
        if k in r:
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


def fabric_index(c):
    """Every fabric, without its specification: {code: {id, fab_group_id, signature, spec_sha, not_grouped}}."""
    return {r["code"]: r for r in _dicts(c, "SELECT id, code, fab_group_id, signature, spec_sha, not_grouped FROM fabric")}


def specs_of(c, ids):
    """{id: specification} for these fabrics (the ones the PLM list no longer has)."""
    out = {}
    for part in _chunks(sorted(set(ids))):
        out.update({i: (json.loads(s) if s else None) for i, s in c.all(f"SELECT id, spec FROM fabric WHERE id IN {store._in(len(part))}", part)})
    return out


def fabric_groups(c):
    """{fabric code: (Fab group id, why not grouped)}, for every fabric: what Right cost's column needs."""
    return {code: (g, why) for code, g, why in c.all("SELECT code, fab_group_id, not_grouped FROM fabric")}


def add_fabrics(c, rows, at):
    """rows: dicts with code, description, spec, spec_sha, fab_group_id, signature, not_grouped. Returns {code: id}."""
    _many(c, "INSERT INTO fabric (code, description, spec, spec_sha, fab_group_id, signature, not_grouped, problems, updated_at) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(r["code"], r.get("description") or "", None if r.get("spec") is None else json.dumps(r["spec"]), r.get("spec_sha"),
            r.get("fab_group_id"), r.get("signature"), r.get("not_grouped"), "[]", at) for r in rows])
    return ids_of(c, [r["code"] for r in rows])


def ids_of(c, codes):
    out = {}
    for part in _chunks(sorted(set(codes))):
        out.update(dict(c.all(f"SELECT code, id FROM fabric WHERE code IN {store._in(len(part))}", part)))
    return out


def set_fabrics(c, rows, at):
    """rows: dicts with id and any of description, spec, spec_sha, fab_group_id, signature, not_grouped, choices, problems.
    Rows that change the same columns go in one statement (a first upload changes thousands)."""
    plain, as_json = ("description", "fab_group_id", "signature", "not_grouped", "spec_sha"), ("spec", "choices", "problems")
    same = {}
    for r in rows:
        cols = tuple(k for k in plain + as_json if k in r)
        if cols:
            same.setdefault(cols, []).append([r[k] if k in plain else (None if r[k] is None else json.dumps(r[k], default=str)) for k in cols] + [at, r["id"]])
    for cols, vals in same.items():
        _many(c, f"UPDATE fabric SET {', '.join(k + ' = %s' for k in cols)}, updated_at = %s WHERE id = %s", vals)


def set_choices(c, rows, at):
    """rows: dicts with id, choices and problems: the costing choices worked out again."""
    _many(c, "UPDATE fabric SET choices = %s, problems = %s, updated_at = %s WHERE id = %s",
          [(None if r["choices"] is None else json.dumps(r["choices"], default=str), json.dumps(r["problems"]), at, r["id"]) for r in rows])


def add_regroups(c, rows, at, upload_id):
    """rows: (fabric id, from group id, to group id, why)"""
    _many(c, "INSERT INTO fabric_regroup (fabric_id, from_group_id, to_group_id, why, at, upload_id) VALUES (%s, %s, %s, %s, %s, %s)",
          [(f, a, b, why, at, upload_id) for f, a, b, why in rows])


def regroups(c, group_ids):
    """The moves into or out of these groups, newest first, with the fabric code."""
    out = []
    for part in _chunks(sorted(set(group_ids))):
        out += _dicts(c, "SELECT r.id, f.code, r.from_group_id, r.to_group_id, r.why, r.at FROM fabric_regroup r JOIN fabric f ON f.id = r.fabric_id "
                         f"WHERE r.from_group_id IN {store._in(len(part))} OR r.to_group_id IN {store._in(len(part))}", part + part)
    return sorted({r["id"]: r for r in out}.values(), key=lambda r: (r["at"], r["id"]), reverse=True)


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


def resign_group(c, group_id, name, fields, signature):
    """A group keeps its code under a new signature (its codes' fields are tidied another way now)."""
    c.run("UPDATE fab_group SET name = %s, content = %s, route = %s, weave = %s, warp = %s, weft = %s, epi = %s, ppi = %s, width_in = %s, "
          "finish = %s, signature = %s WHERE id = %s",
          (name, fields["content"], fields["route"], fields["weave"], fields["warp"], fields["weft"], fields["epi"], fields["ppi"],
           fields["width_in"], fields["finish"], signature, group_id))


def set_merged(c, group_id, into_id, at, who):
    c.run("UPDATE fab_group SET merged_into = %s, merged_at = %s, merged_by = %s WHERE id = %s", (into_id, at, who, group_id))


# ------------------------------------------------------------------ uploads
UPLOAD = ("id, kind, filename, uploaded_by, uploaded_at, status, step, started_at, finished_at, alive_at, runner, error, file_date, "
          "file_date_from, rows_total, rows_loaded, rows_new, rows_changed, rows_same, rows_removed, rows_dropped, rows_older, rows_outliers, "
          "rows_skipped, fabrics_new, groups_new, mills_new, summary, sha256")


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
    """Uploads not finished: (id, status, alive_at, runner), oldest first."""
    return c.all("SELECT id, status, alive_at, runner FROM upload WHERE status IN ('queued', 'working') ORDER BY id")


def shipped_loaded(c, sha):
    """Whether a file with this SHA-256 has been read in full."""
    return c.one("SELECT count(*) FROM upload WHERE sha256 = %s AND status = 'done'", (sha,))[0] > 0


# ------------------------------------------------------------------ purchase lines
LINE = ("id, po_number, item, doc_date, doc_type, fabric_id, mill_id, supplier, qty_m, price, upload_id, removed_upload_id, removed_why, "
        "state_file_date, state_upload_id")


def lines_by_key(c, keys):
    """{(po_number, item): line} for the order lines already held among these."""
    out, want = {}, set(keys)
    for part in _chunks(sorted({k[0] for k in keys})):
        for r in _dicts(c, f"SELECT {LINE} FROM purchase_line WHERE po_number IN {store._in(len(part))}", part):
            if (r["po_number"], r["item"]) in want:
                out[(r["po_number"], r["item"])] = r
    return out


def lines_of_orders(c, pos):
    """Every line held for these purchase orders: {(po_number, item): line}."""
    out = {}
    for part in _chunks(sorted(set(pos))):
        for r in _dicts(c, f"SELECT {LINE} FROM purchase_line WHERE po_number IN {store._in(len(part))}", part):
            out[(r["po_number"], r["item"])] = r
    return out


def add_lines(c, rows):
    """rows: dicts with the line's columns (state_file_date and state_upload_id included)."""
    _many(c, "INSERT INTO purchase_line (po_number, item, doc_date, doc_type, fabric_id, mill_id, supplier, qty_m, price, upload_id, "
             "state_file_date, state_upload_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(r["po_number"], r["item"], r["doc_date"], r["doc_type"], r["fabric_id"], r["mill_id"], r["supplier"], r["qty_m"], r["price"],
            r["upload_id"], r["state_file_date"], r["state_upload_id"]) for r in rows])


def change_lines(c, rows):
    """rows: dicts with id and the line's columns: a newer file's figures, the line counted again."""
    _many(c, "UPDATE purchase_line SET doc_date = %s, doc_type = %s, fabric_id = %s, mill_id = %s, supplier = %s, qty_m = %s, price = %s, "
             "upload_id = %s, removed_upload_id = NULL, removed_why = NULL, state_file_date = %s, state_upload_id = %s WHERE id = %s",
          [(r["doc_date"], r["doc_type"], r["fabric_id"], r["mill_id"], r["supplier"], r["qty_m"], r["price"], r["upload_id"],
            r["state_file_date"], r["state_upload_id"], r["id"]) for r in rows])


def touch_lines(c, rows):
    """rows: (state_file_date, state_upload_id, id): a newer file has the same figures."""
    _many(c, "UPDATE purchase_line SET state_file_date = %s, state_upload_id = %s WHERE id = %s", rows)


def remove_lines(c, rows, upload_id, file_date):
    """rows: (why, id): a newer file says the line is no longer a priced bulk order in rupees per metre."""
    _many(c, "UPDATE purchase_line SET removed_upload_id = %s, removed_why = %s, state_file_date = %s, state_upload_id = %s WHERE id = %s",
          [(upload_id, why, file_date, upload_id, i) for why, i in rows])


def lines(c, fabric_ids, outliers=False):
    """The lines still counted for these fabrics (outliers=True: their ZLOI lines instead), with the fabric code and the
    mill, oldest first."""
    out = []
    for part in _chunks(sorted(set(fabric_ids))):
        out += _dicts(c, "SELECT l.id, l.po_number, l.item, l.doc_date, l.doc_type, l.qty_m, l.price, l.supplier, l.fabric_id, "
                         "f.code AS fabric_code, l.mill_id, m.name AS mill, m.key AS mill_key "
                         "FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id JOIN mill m ON m.id = l.mill_id "
                         f"WHERE l.removed_upload_id IS NULL AND {_OUTLIER if outliers else _NOT_OUTLIER} AND l.fabric_id IN {store._in(len(part))}", part)
    out.sort(key=lambda r: (r["doc_date"], r["po_number"], r["item"]))
    return out


def lines_for_codes(c, codes):
    """Every line held for these fabric codes, removed and ZLOI ones included (Right cost's purchase-order rows are
    worked out from them): (code, po, item, date, type, supplier, qty, price, removed)."""
    out = []
    for part in _chunks(sorted(set(codes))):
        out += c.all("SELECT f.code, l.po_number, l.item, l.doc_date, l.doc_type, l.supplier, l.qty_m, l.price, "
                     "CASE WHEN l.removed_upload_id IS NULL THEN 0 ELSE 1 END FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
                     f"WHERE f.code IN {store._in(len(part))}", part)
    return out


def outlier_lines(c):
    """Every ZLOI line still counted as bought: (code, po, item, date, type, supplier, qty, price)."""
    return c.all("SELECT f.code, l.po_number, l.item, l.doc_date, l.doc_type, l.supplier, l.qty_m, l.price FROM purchase_line l "
                 f"JOIN fabric f ON f.id = l.fabric_id WHERE l.removed_upload_id IS NULL AND {_OUTLIER} ORDER BY l.doc_date, l.po_number, l.item")


def group_stats(c):
    """{Fab group id of the fabric: (lines, metres, orders, last date)} over the lines still counted, ZLOI left out."""
    out = {}
    for g, n, metres, orders, last in c.all(
            "SELECT f.fab_group_id, count(*), sum(l.qty_m), count(DISTINCT l.po_number), max(l.doc_date) FROM purchase_line l "
            f"JOIN fabric f ON f.id = l.fabric_id WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER} AND f.fab_group_id IS NOT NULL "
            "GROUP BY f.fab_group_id"):
        out[g] = (n, metres, orders, last)
    return out


def prices_by_group(c):
    """{Fab group id of the fabric: [(price, order number)]} over the lines still counted, ZLOI left out."""
    out = {}
    for g, p, po in c.all("SELECT f.fab_group_id, l.price, l.po_number FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
                          f"WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER} AND f.fab_group_id IS NOT NULL"):
        out.setdefault(g, []).append((p, po))
    return out


def metres(c, fabric_ids):
    """{fabric id: metres on the lines still counted, ZLOI left out}"""
    out = {}
    for part in _chunks(sorted(set(fabric_ids))):
        out.update(dict(c.all(f"SELECT l.fabric_id, sum(l.qty_m) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER} "
                              f"AND l.fabric_id IN {store._in(len(part))} GROUP BY l.fabric_id", part)))
    return out


def counts(c):
    one = lambda sql: c.one(sql)[0]
    return {"lines": one(f"SELECT count(*) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER}"),
            "outliers": one(f"SELECT count(*) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_OUTLIER}"),
            "lines_removed": one("SELECT count(*) FROM purchase_line WHERE removed_upload_id IS NOT NULL"),
            "fabrics": one("SELECT count(*) FROM fabric"), "fabrics_grouped": one("SELECT count(*) FROM fabric WHERE fab_group_id IS NOT NULL"),
            "groups": one("SELECT count(*) FROM fab_group g WHERE g.merged_into IS NULL AND EXISTS (SELECT 1 FROM fabric f WHERE f.fab_group_id = g.id)"),
            "groups_merged": one("SELECT count(*) FROM fab_group WHERE merged_into IS NOT NULL"),
            "mills": one("SELECT count(*) FROM mill"),
            "first": one(f"SELECT min(l.doc_date) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER}"),
            "last": one(f"SELECT max(l.doc_date) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER}")}
