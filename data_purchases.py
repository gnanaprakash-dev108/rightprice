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
# a line counted in a figure: not ZLOI, and not a price held apart to check in SAP (unless an admin counted it)
_HELD = "(l.price_check IS NOT NULL AND l.price_ok_by IS NULL)"
_NOT_OUTLIER = "l.doc_type NOT IN (" + ", ".join(f"'{t}'" for t in OUTLIER_TYPES) + f") AND NOT {_HELD}"
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
FABRIC = "id, code, description, fab_group_id, not_grouped, signature, spec, spec_sha, choices, problems, choices_lists, choices_metres, choices_spec"


def fabric_of(r):
    """A fabric as fabrics(..., read=False) gave it, with its specification, choices and problems read."""
    r = dict(r)
    for k, empty in (("spec", None), ("choices", None), ("problems", [])):
        if k in r:
            r[k] = json.loads(r[k]) if r.get(k) else empty
    return r


def fabrics(c, codes=None, ids=None, group_ids=None, read=True):
    """{code: fabric} for these codes (or ids, or Fab group ids), or every fabric. read=False: the specification, choices
    and problems as stored (JSON text), for fabric_of() to read once the transaction is over (a background job reading
    many fabrics then holds the store only for the reading of the rows)."""
    out, one = {}, (fabric_of if read else dict)
    if codes is None and ids is None and group_ids is None:
        return {r["code"]: one(r) for r in _dicts(c, f"SELECT {FABRIC} FROM fabric ORDER BY id")}
    col, vals = ("code", codes) if codes is not None else (("id", ids) if ids is not None else ("fab_group_id", group_ids))
    for part in _chunks(sorted(set(vals))):
        for r in _dicts(c, f"SELECT {FABRIC} FROM fabric WHERE {col} IN {store._in(len(part))} ORDER BY id", part):
            out[r["code"]] = one(r)
    return out


def fabric_index(c, ids=None):
    """Every fabric (or these, by id), without its specification: {code: {id, fab_group_id, signature, spec_sha, not_grouped}}."""
    sql = "SELECT id, code, fab_group_id, signature, spec_sha, not_grouped FROM fabric"
    if ids is None:
        return {r["code"]: r for r in _dicts(c, sql)}
    out = {}
    for part in _chunks(sorted(set(ids))):
        out.update({r["code"]: r for r in _dicts(c, sql + f" WHERE id IN {store._in(len(part))}", part)})
    return out


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
    """rows: dicts with id, choices, problems and what they were worked out on (lists: the fingerprint of the rate master's
    lists, metres, spec: the specification's SHA-256): the costing choices worked out again."""
    _many(c, "UPDATE fabric SET choices = %s, problems = %s, choices_lists = %s, choices_metres = %s, choices_spec = %s, updated_at = %s WHERE id = %s",
          [(None if r["choices"] is None else json.dumps(r["choices"], default=str), json.dumps(r["problems"]), r.get("lists"), r.get("metres"),
            r.get("spec"), at, r["id"]) for r in rows])


def choices_basis(c, ids=None):
    """{fabric id: (lists fingerprint, metres, spec SHA-256 the choices were worked out on, the specification's SHA-256 now)}
    for these fabrics, or every one."""
    sql = "SELECT id, choices_lists, choices_metres, choices_spec, spec_sha FROM fabric"
    if ids is None:
        return {r[0]: tuple(r[1:]) for r in c.all(sql)}
    out = {}
    for part in _chunks(ids):
        out.update({r[0]: tuple(r[1:]) for r in c.all(sql + f" WHERE id IN {store._in(len(part))}", part)})
    return out


def top_suppliers(c, fabric_ids):
    """{fabric id: the supplier as written on most of its metres still counted, ZLOI left out}"""
    best = {}
    for part in _chunks(sorted(set(fabric_ids))):
        for f, sup, q in c.all(f"SELECT l.fabric_id, l.supplier, sum(l.qty_m) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER} "
                               f"AND l.fabric_id IN {store._in(len(part))} GROUP BY l.fabric_id, l.supplier", part):
            if f not in best or (q, sup) > best[f]:
                best[f] = (q, sup)
    return {f: sup for f, (q, sup) in best.items()}


def add_regroups(c, rows, at, upload_id):
    """rows: (fabric id, from group id, to group id, why)"""
    _many(c, "INSERT INTO fabric_regroup (fabric_id, from_group_id, to_group_id, why, at, upload_id) VALUES (%s, %s, %s, %s, %s, %s)",
          [(f, a, b, why, at, upload_id) for f, a, b, why in rows])


def add_group_changes(c, rows, at, upload_id=None, kind="renamed", who=""):
    """rows: (group id, old name, new name, why): a group renamed (its codes' specification corrected, or codes of other
    widths joined), merged into another, or its merge undone."""
    _many(c, "INSERT INTO fab_group_change (group_id, kind, old_name, new_name, why, at, by_whom, upload_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
          [(g, kind, a, b, why, at, who or "", upload_id) for g, a, b, why in rows])


def group_changes(c, group_ids):
    """What happened to these groups, newest first."""
    out = []
    for part in _chunks(sorted(set(group_ids))):
        out += _dicts(c, f"SELECT id, group_id, kind, old_name, new_name, why, at, by_whom FROM fab_group_change WHERE group_id IN {store._in(len(part))}", part)
    return sorted(out, key=lambda r: (r["at"], r["id"]), reverse=True)


def regroups_of(c, fabric_id):
    """One fabric's moves and specification changes, newest first."""
    return _dicts(c, "SELECT r.id, f.code, r.from_group_id, r.to_group_id, r.why, r.at FROM fabric_regroup r JOIN fabric f ON f.id = r.fabric_id "
                     "WHERE r.fabric_id = %s ORDER BY r.at DESC, r.id DESC", (fabric_id,))


def regroups(c, group_ids):
    """The moves into or out of these groups, newest first, with the fabric code."""
    out = []
    for part in _chunks(sorted(set(group_ids))):
        out += _dicts(c, "SELECT r.id, f.code, r.from_group_id, r.to_group_id, r.why, r.at FROM fabric_regroup r JOIN fabric f ON f.id = r.fabric_id "
                         f"WHERE r.from_group_id IN {store._in(len(part))} OR r.to_group_id IN {store._in(len(part))}", part + part)
    return sorted({r["id"]: r for r in out}.values(), key=lambda r: (r["at"], r["id"]), reverse=True)


# ------------------------------------------------------------------ Fab groups
GROUP = ("id, code, name, content, route, weave, warp, weft, epi, ppi, width_in, width_to, finish, signature, merged_into, merged_at, "
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
    _many(c, "INSERT INTO fab_group (code, name, content, route, weave, warp, weft, epi, ppi, width_in, width_to, finish, signature, created_at, upload_id) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(code, name, f["content"], f["route"], f["weave"], f["warp"], f["weft"], f["epi"], f["ppi"], f["width_in"], f.get("width_to"), f["finish"],
            sig, at, upload_id) for code, name, f, sig in rows])
    return group_ids_by_signature(c, [r[3] for r in rows])


def resign_group(c, group_id, name, fields, signature):
    """A group keeps its code under a new signature (its codes' fields are tidied another way now)."""
    c.run("UPDATE fab_group SET name = %s, content = %s, route = %s, weave = %s, warp = %s, weft = %s, epi = %s, ppi = %s, width_in = %s, "
          "width_to = %s, finish = %s, signature = %s WHERE id = %s",
          (name, fields["content"], fields["route"], fields["weave"], fields["warp"], fields["weft"], fields["epi"], fields["ppi"],
           fields["width_in"], fields.get("width_to"), fields["finish"], signature, group_id))


def set_merged(c, group_id, into_id, at, who):
    c.run("UPDATE fab_group SET merged_into = %s, merged_at = %s, merged_by = %s WHERE id = %s", (into_id, at, who, group_id))


# ------------------------------------------------------------------ uploads
UPLOAD = ("id, kind, filename, uploaded_by, uploaded_at, status, step, started_at, finished_at, alive_at, runner, error, file_date, "
          "file_date_from, covers_from, covers_to, covers_saved, report_date, report_used, saved_at, rows_total, rows_loaded, rows_new, rows_changed, rows_same, "
          "rows_removed, rows_dropped, rows_older, rows_disagree, rows_outliers, rows_skipped, fabrics_new, groups_new, mills_new, summary, sha256")


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
    """The newest uploads, and every older one with disagreements still open (never out of reach), newest first, each with
    how many of its disagreements are open."""
    opened = "(SELECT count(*) FROM line_disagreement d WHERE d.upload_id = upload.id AND d.settled_at IS NULL) AS disagree_open"
    rows = _dicts(c, f"SELECT {UPLOAD}, {opened} FROM upload ORDER BY id DESC LIMIT {int(limit)}")
    have = {r["id"] for r in rows}
    rows += [r for r in _dicts(c, f"SELECT {UPLOAD}, {opened} FROM upload WHERE id IN (SELECT upload_id FROM line_disagreement WHERE settled_at IS NULL) "
                                  "ORDER BY id DESC") if r["id"] not in have]
    return [_upload(r) for r in rows]


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


def upload_dates(c, ids):
    """{id: {id, filename, saved_at, report_date, covers_to}} for these uploads: when each was saved, for the words of
    a file the saved date decided against."""
    out = {}
    for part in _chunks(sorted(set(ids))):
        for r in _dicts(c, f"SELECT id, filename, uploaded_at, saved_at, report_date, report_used, covers_to, covers_saved FROM upload "
                           f"WHERE id IN {store._in(len(part))}", part):
            out[r["id"]] = r
    return out


def waiting_uploads(c):
    """Uploads not finished: (id, status, alive_at, runner), oldest first."""
    return c.all("SELECT id, status, alive_at, runner FROM upload WHERE status IN ('queued', 'working') ORDER BY id")


def shipped_in(c, sha):
    """Whether a file with this SHA-256 has been read in full, or is waiting or being read."""
    return c.one("SELECT count(*) FROM upload WHERE sha256 = %s AND status IN ('queued', 'working', 'done')", (sha,))[0] > 0


def shipped_loaded(c, sha):
    """Whether a file with this SHA-256 has been read in full."""
    return c.one("SELECT count(*) FROM upload WHERE sha256 = %s AND status = 'done'", (sha,))[0] > 0


# ------------------------------------------------------------------ purchase lines
LINE = ("id, po_number, item, doc_date, doc_type, fabric_id, mill_id, supplier, qty_m, price, upload_id, removed_upload_id, removed_why, "
        "state_upload_id, state_from, state_to, state_saved, price_check, price_ok_by")


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
    """rows: dicts with the line's columns (its state: state_upload_id, state_from, state_to, state_saved, included)."""
    _many(c, "INSERT INTO purchase_line (po_number, item, doc_date, doc_type, fabric_id, mill_id, supplier, qty_m, price, upload_id, "
             "state_upload_id, state_from, state_to, state_saved) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(r["po_number"], r["item"], r["doc_date"], r["doc_type"], r["fabric_id"], r["mill_id"], r["supplier"], r["qty_m"], r["price"],
            r["upload_id"], r["state_upload_id"], r["state_from"], r["state_to"], r["state_saved"]) for r in rows])


def add_marks(c, rows):
    """rows: (po, item, why, (upload id, from, to, saved)): a line a file shows deleted (blocked, no longer bulk ...) before
    any file gave its figures: kept as a mark (no figures), so an older file does not bring it back."""
    _many(c, "INSERT INTO purchase_line (po_number, item, upload_id, removed_upload_id, removed_why, state_upload_id, state_from, state_to, state_saved) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", [(po, item, s[0], s[0], why, s[0], s[1], s[2], s[3]) for po, item, why, s in rows])


def change_lines(c, rows):
    """rows: dicts with id and the line's columns: a newer file's figures, the line counted again."""
    _many(c, "UPDATE purchase_line SET doc_date = %s, doc_type = %s, fabric_id = %s, mill_id = %s, supplier = %s, qty_m = %s, price = %s, "
             "upload_id = %s, removed_upload_id = NULL, removed_why = NULL, state_upload_id = %s, state_from = %s, state_to = %s, state_saved = %s, "
             "price_check = NULL, price_ok_by = NULL, price_ok_at = NULL WHERE id = %s",      # new figures: their price judged afresh
          [(r["doc_date"], r["doc_type"], r["fabric_id"], r["mill_id"], r["supplier"], r["qty_m"], r["price"], r["upload_id"],
            r["state_upload_id"], r["state_from"], r["state_to"], r["state_saved"], r["id"]) for r in rows])


def touch_lines(c, rows):
    """rows: ((upload id, from, to, saved), id): a newer file says the same (the same figures, or removed too): it is the
    evidence now."""
    _many(c, "UPDATE purchase_line SET state_upload_id = %s, state_from = %s, state_to = %s, state_saved = %s WHERE id = %s",
          [(s[0], s[1], s[2], s[3], i) for s, i in rows])


def remove_lines(c, rows, state):
    """rows: (why, id): a newer file says the line is no longer a priced bulk order in rupees per metre, or leaves it out of
    an order it has. state: (upload id, from, to, saved) of that file."""
    _many(c, "UPDATE purchase_line SET removed_upload_id = %s, removed_why = %s, state_upload_id = %s, state_from = %s, state_to = %s, "
             "state_saved = %s WHERE id = %s", [(state[0], why, state[0], state[1], state[2], state[3], i) for why, i in rows])


def forget_evidence(c, upload_id):
    """An upload's disagreements not settled: written again when it is read again."""
    c.run("DELETE FROM line_disagreement WHERE upload_id = %s AND settled_at IS NULL", (upload_id,))


def add_disagreements(c, upload_id, rows):
    """rows: (po, item, kept, file): this file and the history disagree, and which is newer cannot be told."""
    _many(c, "INSERT INTO line_disagreement (upload_id, po_number, item, kept, file) VALUES (%s, %s, %s, %s, %s)",
          [(upload_id, po, item, json.dumps(k, default=str), json.dumps(f, default=str)) for po, item, k, f in rows])


def disagreements(c, upload_id, limit=None):
    rows = _dicts(c, "SELECT id, po_number, item, kept, file, settled_at, settled_by, settled_as FROM line_disagreement WHERE upload_id = %s ORDER BY id"
                     + (f" LIMIT {int(limit)}" if limit else ""), (upload_id,))
    for r in rows:
        r["kept"], r["file"] = json.loads(r["kept"]), json.loads(r["file"])
    return rows


def settle_disagreements(c, ids, at, who, take):
    _many(c, "UPDATE line_disagreement SET settled_at = %s, settled_by = %s, settled_as = %s WHERE id = %s", [(at, who, take, i) for i in ids])


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
                     f"CASE WHEN l.removed_upload_id IS NULL AND NOT {_HELD} THEN 0 ELSE 1 END FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
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
            "lines_removed": one("SELECT count(*) FROM purchase_line WHERE removed_upload_id IS NOT NULL AND fabric_id IS NOT NULL"),
            "marks": one("SELECT count(*) FROM purchase_line WHERE fabric_id IS NULL"),
            "price_checks": one(f"SELECT count(*) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_HELD}"),
            "disagreements": one("SELECT count(*) FROM line_disagreement WHERE settled_at IS NULL"),
            "fabrics": one("SELECT count(*) FROM fabric"), "fabrics_grouped": one("SELECT count(*) FROM fabric WHERE fab_group_id IS NOT NULL"),
            "groups": one("SELECT count(*) FROM fab_group g WHERE g.merged_into IS NULL AND EXISTS (SELECT 1 FROM fabric f WHERE f.fab_group_id = g.id)"),
            "groups_merged": one("SELECT count(*) FROM fab_group WHERE merged_into IS NOT NULL"),
            "mills": one("SELECT count(*) FROM mill"),
            "first": one(f"SELECT min(l.doc_date) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER}"),
            "last": one(f"SELECT max(l.doc_date) FROM purchase_line l WHERE l.removed_upload_id IS NULL AND {_NOT_OUTLIER}")}


# ------------------------------------------------------------------ prices held apart to check in SAP
def counted_prices(c, fabric_ids):
    """{fabric id: [(line id, price, counted by an admin)]}: the lines that count (or would, but for the price check) of
    these fabrics: not removed, not ZLOI, not held apart (an admin's counted ones included)."""
    out = {}
    for part in _chunks(sorted(set(fabric_ids))):
        for i, f, p, ok in c.all("SELECT l.id, l.fabric_id, l.price, l.price_ok_by FROM purchase_line l WHERE l.removed_upload_id IS NULL "
                                 f"AND l.doc_type NOT IN ({', '.join(repr(t) for t in OUTLIER_TYPES)}) AND NOT {_HELD} "
                                 f"AND l.fabric_id IN {store._in(len(part))}", part):
            out.setdefault(f, []).append((i, float(p), ok is not None))
    return out


def group_prices(c, group_ids):
    """{Fab group id: [(fabric id, price)]}: the prices counted for every fabric code of these groups, read in a few
    statements (a price check over a whole file never runs a statement per code: on a slow machine those kept every page
    waiting, the CI run of 4e1f6f0)."""
    out = {}
    for part in _chunks(sorted(set(group_ids) - {None})):
        for g, f, p in c.all(f"SELECT f.fab_group_id, l.fabric_id, l.price FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
                             f"WHERE f.fab_group_id IN {store._in(len(part))} AND l.removed_upload_id IS NULL AND {_NOT_OUTLIER}", part):
            out.setdefault(g, []).append((f, float(p)))
    return out


def hold_prices(c, rows):
    """rows: (why, line id): held apart to check in SAP."""
    _many(c, "UPDATE purchase_line SET price_check = %s, price_ok_by = NULL, price_ok_at = NULL WHERE id = %s", rows)


def count_price(c, line_id, who, at, count=True):
    """An admin counts a price held apart (count), or holds it apart again."""
    c.run("UPDATE purchase_line SET price_ok_by = %s, price_ok_at = %s WHERE id = %s AND price_check IS NOT NULL",
          ((who or "an admin") if count else None, at if count else None, line_id))


def held_lines(c, fabric_ids=None, line_ids=None):
    """The lines held apart as prices to check in SAP (an admin's counted ones included, marked so), with code and mill."""
    sql = ("SELECT l.id, f.code AS fabric_code, l.fabric_id, l.po_number, l.item, l.doc_date, l.doc_type, l.supplier, l.qty_m, l.price, "
           "l.price_check, l.price_ok_by, l.price_ok_at, m.name AS mill, m.key AS mill_key FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
           "JOIN mill m ON m.id = l.mill_id WHERE l.removed_upload_id IS NULL AND l.price_check IS NOT NULL")
    if fabric_ids is None and line_ids is None:
        return _dicts(c, sql + " ORDER BY l.doc_date, l.po_number, l.item")
    out, col, vals = [], ("l.fabric_id" if fabric_ids is not None else "l.id"), (fabric_ids if fabric_ids is not None else line_ids)
    for part in _chunks(sorted(set(vals))):
        out += _dicts(c, sql + f" AND {col} IN {store._in(len(part))}", part)
    return sorted(out, key=lambda r: (r["doc_date"] or "", r["po_number"], r["item"]))
