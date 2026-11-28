"""The Fab library's tables (db/006_fab_library.sql): the uploads of the PLM fabric code list and its codes. Only SQL:
what is decided about them is in rules/fab_library.py. Every function takes the cursor of a transaction opened with
store.get().tx(); none of this is reached on the files store (the library needs a database)."""
import json

import data_purchases as dp
import store

KIND = "library"            # store.KINDS: writers wait for each other, and the version moves with every change
STATUS = "library_status"   # a job's progress and signs of life: written without moving the version (no page needs redoing)


def _many(c, sql, rows):
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


# ------------------------------------------------------------------ uploads
UPLOAD = ("id, filename, uploaded_by, uploaded_at, status, step, started_at, finished_at, alive_at, runner, error, file_format, file_bytes, "
          "content_bytes, sha256, rows_total, codes_total, codes_new, codes_changed, codes_same, codes_older, codes_kept, rows_repeated, "
          "rows_no_code, no_epi_ppi, no_width, no_counts, summary")


def _upload(r):
    r = dict(r)
    r["summary"] = json.loads(r["summary"]) if r.get("summary") else {}
    return r


def add_upload(c, filename, who, fmt, data, file_bytes, content_bytes, sha, at):
    c.run("INSERT INTO fab_library_upload (filename, uploaded_by, uploaded_at, status, file_format, file, file_bytes, content_bytes, sha256) "
          "VALUES (%s, %s, %s, 'queued', %s, %s, %s, %s, %s)", (filename, who or "", at, fmt, data, file_bytes, content_bytes, sha))
    return c.one("SELECT max(id) FROM fab_library_upload")[0]


def uploads(c, limit=50):
    return [_upload(r) for r in _dicts(c, f"SELECT {UPLOAD} FROM fab_library_upload ORDER BY id DESC LIMIT {int(limit)}")]


def upload(c, upload_id):
    rows = _dicts(c, f"SELECT {UPLOAD} FROM fab_library_upload WHERE id = %s", (upload_id,))
    return _upload(rows[0]) if rows else None


def upload_file(c, upload_id):
    r = c.one("SELECT file FROM fab_library_upload WHERE id = %s", (upload_id,))
    return None if r is None or r[0] is None else bytes(r[0])


def set_upload(c, upload_id, **fields):
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(json.dumps(v, default=str) if k == "summary" else v)
    c.run(f"UPDATE fab_library_upload SET {', '.join(sets)} WHERE id = %s", vals + [upload_id])


def waiting(c):
    """Uploads not finished: (id, status, alive_at, runner), oldest first."""
    return c.all("SELECT id, status, alive_at, runner FROM fab_library_upload WHERE status IN ('queued', 'working') ORDER BY id")


def latest_done(c):
    """The number of the latest upload read in full, or None: once there is one, the library is the source of the
    specifications."""
    return c.one("SELECT max(id) FROM fab_library_upload WHERE status = 'done'")[0]


def any_done(c):
    return c.one("SELECT count(*) FROM fab_library_upload WHERE status = 'done'")[0] > 0


# ------------------------------------------------------------------ codes
CODE = "code, spec, spec_sha, sig_rest, width_in, not_grouped, upload_id, first_upload_id, seen_upload_id, changed_at"


def _code(r):
    r = dict(r)
    r["spec"] = json.loads(r["spec"])
    return r


def held(c, codes):
    """{code: (spec_sha, upload_id, spec as stored (JSON text), seen_upload_id)} for the codes among these that the library
    holds: its specification, the upload it is from, and the latest upload that held it."""
    out = {}
    for part in _chunks(sorted(set(codes))):
        for code, sha, uid, spec, seen_ in c.all(f"SELECT code, spec_sha, upload_id, spec, seen_upload_id FROM fab_code WHERE code IN {store._in(len(part))}", part):
            out[code] = (sha, uid, spec, seen_)
    return out


def add_codes(c, rows):
    """rows: (code, spec JSON, spec_sha, search, sig_rest, width_in, not_grouped, upload id, at)"""
    _many(c, "INSERT INTO fab_code (code, spec, spec_sha, search, sig_rest, width_in, not_grouped, upload_id, first_upload_id, seen_upload_id, changed_at) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
          [(code, spec, sha, search, rest, width, why, uid, uid, uid, at) for code, spec, sha, search, rest, width, why, uid, at in rows])


def change_codes(c, rows):
    """rows: (code, spec JSON, spec_sha, search, sig_rest, width_in, not_grouped, upload id, at): a later upload's specification."""
    _many(c, "UPDATE fab_code SET spec = %s, spec_sha = %s, search = %s, sig_rest = %s, width_in = %s, not_grouped = %s, upload_id = %s, "
             "seen_upload_id = %s, changed_at = %s WHERE code = %s",
          [(spec, sha, search, rest, width, why, uid, uid, at, code) for code, spec, sha, search, rest, width, why, uid, at in rows])


def seen(c, codes, uid):
    """These codes are in upload uid (with the specification they have, or an older one's): the latest upload that held them."""
    for part in _chunks(sorted(set(codes))):
        c.run(f"UPDATE fab_code SET seen_upload_id = %s WHERE seen_upload_id < %s AND code IN {store._in(len(part))}", [uid, uid] + part)


def add_changes(c, rows):
    """rows: (code, upload id, the old 26 values as JSON, what changed in words, at)"""
    _many(c, "INSERT INTO fab_code_change (code, upload_id, old_spec, what, at) VALUES (%s, %s, %s, %s, %s)", rows)


def changed_in(c, uid):
    """The codes upload uid changed (already recorded), so a re-read after a restart records none twice."""
    return {code for (code,) in c.all("SELECT DISTINCT code FROM fab_code_change WHERE upload_id = %s", (uid,))}


def counts_of(c, uid):
    """What upload uid did, counted from what is stored (so a re-read after a restart counts the same)."""
    one = lambda sql, p=(): c.one(sql, p)[0]
    return {"codes_new": one("SELECT count(*) FROM fab_code WHERE first_upload_id = %s", (uid,)),
            "codes_changed": one("SELECT count(DISTINCT code) FROM fab_code_change WHERE upload_id = %s", (uid,)),
            "codes_kept": one("SELECT count(*) FROM fab_code WHERE seen_upload_id < %s", (uid,)),
            "codes": one("SELECT count(*) FROM fab_code")}


def codes(c, codes_):
    """{code: row} for these codes."""
    out = {}
    for part in _chunks(sorted(set(codes_))):
        for r in _dicts(c, f"SELECT {CODE} FROM fab_code WHERE code IN {store._in(len(part))}", part):
            out[r["code"]] = _code(r)
    return out


def specs(c, codes_):
    """{code: its 26 values} for these codes (the library's), a few hundred to a statement."""
    out = {}
    for part in _chunks(sorted(set(codes_))):
        for code, spec in c.all(f"SELECT code, spec FROM fab_code WHERE code IN {store._in(len(part))}", part):
            out[code] = json.loads(spec)
    return out


def search(c, words, limit, typed=""):
    """Codes whose search text holds every word (small letters), the code typed first when it is one; at most `limit` + 1
    (so the page can say there are more)."""
    exact = []
    for t in dict.fromkeys([typed.strip(), typed.strip().upper()]):
        if t and not exact:
            exact = _dicts(c, f"SELECT {CODE} FROM fab_code WHERE code = %s", (t,))
    pats = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]
    where = " AND ".join(["search LIKE %s ESCAPE '\\'"] * len(pats)) or "1 = 1"
    rows = _dicts(c, f"SELECT {CODE} FROM fab_code WHERE {where} ORDER BY code LIMIT {int(limit) + 1}", pats)
    have = {r["code"] for r in exact}
    return [_code(r) for r in exact] + [_code(r) for r in rows if r["code"] not in have]


def total(c):
    return c.one("SELECT count(*) FROM fab_code")[0]


def changes_of(c, code):
    return _dicts(c, "SELECT x.id, x.upload_id, x.what, x.at, u.filename, u.uploaded_by FROM fab_code_change x "
                     "LEFT JOIN fab_library_upload u ON u.id = x.upload_id WHERE x.code = %s ORDER BY x.id DESC", (code,))


def changes_in(c, uid, limit=300):
    return _dicts(c, f"SELECT code, what, at FROM fab_code_change WHERE upload_id = %s ORDER BY id LIMIT {int(limit)}", (uid,))


def same_construction(c, rest, limit=20):
    """Codes of the library with these eight fields (any width): (count, the first few)."""
    n = c.one("SELECT count(*) FROM fab_code WHERE sig_rest = %s", (rest,))[0]
    return n, [r[0] for r in c.all(f"SELECT code FROM fab_code WHERE sig_rest = %s ORDER BY code LIMIT {int(limit)}", (rest,))]


# ------------------------------------------------------------------ the purchase history, as the library needs it
def purchase_codes(c):
    """Every fabric code in the purchase history."""
    return [r[0] for r in c.all("SELECT code FROM fabric")]


def first_bought(c):
    """{fabric code: (its first order line's date, order, item)} over the lines held, for the order of new Fab groups."""
    out = {}
    for code, day, po, item in c.all("SELECT f.code, l.doc_date, l.po_number, l.item FROM purchase_line l JOIN fabric f ON f.id = l.fabric_id "
                                     "WHERE l.doc_date IS NOT NULL"):
        k = (day, po, item)
        if code not in out or k < out[code]:
            out[code] = k
    return out


def bought(c, codes_):
    """{fabric code: (lines, metres, orders, last date, last price, fabric id, Fab group id, why not grouped, other lines)}
    for these codes in the purchase history (the lines still counted, ZLOI left out, as every figure; and the other rows of
    the purchase files stored for it, in no figure)."""
    out = {}
    for part in _chunks(sorted(set(codes_))):
        for code, fid, gid, why in c.all(f"SELECT code, id, fab_group_id, not_grouped FROM fabric WHERE code IN {store._in(len(part))}", part):
            out[code] = [0, 0.0, 0, None, None, fid, gid, why]
    ids = {v[5]: k for k, v in out.items()}
    for part in _chunks(sorted(ids)):
        rows = c.all("SELECT l.fabric_id, l.doc_date, l.po_number, l.item, l.qty_m, l.price FROM purchase_line l WHERE l.removed_upload_id IS NULL "
                     f"AND {dp._NOT_OUTLIER} AND l.fabric_id IN {store._in(len(part))} ORDER BY l.doc_date, l.po_number, l.item", part)
        orders = {}
        for fid, day, po, item, qty, price in rows:
            v = out[ids[fid]]
            v[0] += 1
            v[1] += float(qty or 0)
            orders.setdefault(fid, set()).add(po)
            v[3], v[4] = day, float(price)
        for fid, s in orders.items():
            out[ids[fid]][2] = len(s)
        # every other row of the purchase files stored for the code (GP, 28 Nov 2026), counted in no figure
        for fid, n in c.all(f"SELECT fabric_id, count(*) FROM purchase_line WHERE removed_upload_id IS NOT NULL AND fabric_id IN {store._in(len(part))} "
                            "GROUP BY fabric_id", part):
            out[ids[fid]].append(n)
    return {k: tuple(v) + ((0,) if len(v) == 8 else ()) for k, v in out.items()}


def purchase_working(c):
    """Whether a purchase file is being read now (in any process)."""
    return c.one("SELECT count(*) FROM upload WHERE status = 'working'")[0] > 0
