"""The purchase history: purchase-order files (the SAP export, as `inputs/Fabric _ 3Months_4746.xlsx`) read in the
background, one line per order line however often a file is uploaded, every mill once with every way it is written, one
fabric per material code with its PLM specification and the costing choices pilot.py works out from it, and each fabric's
Fab group (rules/fab_groups.py). Kept in the database only; on the files store these say they need one.

What is kept from a file, as the pilot keeps it: bulk orders (pilot.BULK_TYPES), priced, in rupees, per metre, not
deleted in SAP. Every other row is left out and the upload says which and why. A line already held is one line: with the
same figures it is counted as already in; with other figures the newer ones are kept; shown deleted in a later file it is
marked removed (kept, not counted)."""
import datetime as dt
import hashlib
import io
import os
import re
import threading
import warnings

import pandas as pd

from rules import common, fab_groups, mills, rightcost
import data_purchases as dp
import grouping
import masters
import store
import yarn_seed

with warnings.catch_warnings():         # pilot.py turns warnings off for its own run; not for the app
    import pilot

KIND = dp.KIND
REQUIRED = ["Purchasing Document", "Item", "Document Date", "Material", "Order Quantity", "Order Unit", "Net Price",
            "Name of Supplier", "Purchasing Doc. Type", "Deletion Indicator", "Currency"]
SHIPPED_NAME = "Fabric _ 3Months_4746.xlsx (the purchase file that came with the code)"
STALE = 300                 # seconds without a sign of life after which a job is taken to have stopped (a restart)
MAX_BYTES = 40 * 1024 * 1024    # a purchase-order file larger than this is refused (the 4-month export is about 4 MB)
CHUNK = 1000                # order lines written per transaction, so pages are never held up for long
VENDOR_NO = re.compile(r"^\d+\s+")
need_db = fab_groups.need_db


def _now():
    return store._now()


def _text_id(v):
    """An order number or item as text: 3210021310.0 -> '3210021310', 10.0 -> '10'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()) or v is pd.NaT


def _number(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(x) else x


def _date(v):
    if _blank(v):
        return None
    try:
        d = v if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)) else pd.to_datetime(str(v), dayfirst=True)
    except (ValueError, TypeError):
        return None
    return None if pd.isna(d) else pd.Timestamp(d).date().isoformat()


# ------------------------------------------------------------------ reading a purchase-order file
def read_po_file(data, filename=""):
    """The order lines kept from a purchase-order file, the rows left out with why, the lines shown deleted, and the
    number of rows. Refused when it is not a workbook in the SAP export's shape."""
    try:
        df = pd.read_excel(io.BytesIO(data))
    except Exception as e:
        raise common.Refused(400, f"{filename or 'The file'} could not be read as an Excel workbook ({type(e).__name__}). "
                                  "Upload the purchase-order export (.xlsx) as SAP gives it.")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise common.Refused(400, f"{filename or 'This file'} is not a purchase-order export in the shape RightPrice reads: the "
                                  f"column{'s' if len(missing) > 1 else ''} {', '.join(missing)} {'are' if len(missing) > 1 else 'is'} missing. "
                                  "It needs the SAP columns Purchasing Document, Item, Document Date, Material, Short Text, Order "
                                  "Quantity, Order Unit, Net Price, Name of Supplier, Currency, Purchasing Doc. Type and Deletion Indicator.")
    kept, skipped, deleted, first = [], [], [], {}
    bulk = set(pilot.BULK_TYPES)
    for n, r in enumerate(df.to_dict("records")):
        row = n + 2                                 # the row number Excel shows (the headings are row 1)
        po, item = _text_id(r["Purchasing Document"]), _text_id(r["Item"])
        material = "" if _blank(r["Material"]) else str(r["Material"]).strip()
        rec = {"row": row, "po": po, "item": item, "material": material}

        def skip(kind, why):
            skipped.append(dict(rec, kind=kind, why=why))
        if not po or not item:
            skip("No order number", "No order number or item: a total line or an empty row")
            continue
        if (po, item) in first:
            skip("Repeated in this file", f"The same order line as row {first[(po, item)]} of this file")
            continue
        first[(po, item)] = row
        dtype = "" if _blank(r["Purchasing Doc. Type"]) else str(r["Purchasing Doc. Type"]).strip()
        flag = "" if _blank(r["Deletion Indicator"]) else str(r["Deletion Indicator"]).strip()
        cur = "" if _blank(r["Currency"]) else str(r["Currency"]).strip()
        unit = "" if _blank(r["Order Unit"]) else str(r["Order Unit"]).strip()
        price, qty, day = _number(r["Net Price"]), _number(r["Order Quantity"]), _date(r["Document Date"])
        supplier = "" if _blank(r["Name of Supplier"]) else re.sub(r"\s+", " ", str(r["Name of Supplier"])).strip()
        if flag:
            deleted.append((po, item))
            skip("Deleted or blocked in SAP", f"Deletion indicator {flag} in SAP ({'deleted' if flag == 'L' else 'blocked' if flag == 'S' else 'marked'})")
        elif dtype not in bulk:
            skip("Not a bulk order", f"Order type {dtype or '(blank)'} is not a bulk order (bulk: {', '.join(pilot.BULK_TYPES)})")
        elif cur != "INR":
            skip("Not in rupees", f"Priced in {cur or '(no currency)'}, not rupees")
        elif unit != "M":
            skip("Not per metre", f"Ordered in {unit or '(no unit)'}, not metres")
        elif price is None or price <= 0:
            skip("No price", "No net price")
        elif qty is None or qty <= 0:
            skip("No quantity", "No order quantity")
        elif not material:
            skip("No material code", "No material (fabric) code")
        elif not supplier:
            skip("No supplier", "No supplier name")
        elif day is None:
            skip("No date", "No document date")
        else:
            kept.append({"po_number": po, "item": item, "doc_date": day, "doc_type": dtype, "code": material, "supplier": supplier,
                         "qty_m": qty, "price": price, "short_text": "" if _blank(r.get("Short Text")) else str(r.get("Short Text")).strip(),
                         "row": row})
    return kept, skipped, deleted, len(df)


# ------------------------------------------------------------------ PLM specifications
_plm = {"key": None, "rows": None}


def plm_specs():
    """{material code: its row of data/plm_specs_for_po.csv, as received}, read again only when the file changes."""
    key = common._mtime(pilot.PLM_SPECS)
    if _plm["key"] != key or _plm["rows"] is None:
        rows = {}
        if key is not None:
            plm = pd.read_csv(pilot.PLM_SPECS, dtype=str).fillna("")
            code = next(c for c in plm.columns if c.replace("article_", "") == "code")
            for r in plm.drop_duplicates(code).to_dict("records"):
                rows[str(r[code]).strip()] = r
        _plm.update(key=key, rows=rows)
    return _plm["rows"]


def costing_choices(code, spec, metres, m, ctx, patterns):
    """The costing choices for one fabric, worked out from its PLM specification exactly as pilot.py does (the rate card
    quantity band and the order size from its metres on record), in the form Right cost costs purchase orders in
    (rightcost._pilot_choices). (choices, []) or (None, why not costed)."""
    if not spec:
        return None, ["No PLM specification for this code"]
    s = fab_groups.short_spec(spec)
    if s.get("productgroup_name") != "Woven":
        return None, [f"Not a woven fabric ({s.get('productgroup_name') or 'blank'} in the PLM)"]
    s["Content group"] = grouping.blend_group(s.get("blend_name"))
    row, why = pilot.fabric_inputs(code, s, ctx, metres)
    if why:
        return None, [why]
    row = dict(row, **{"PO price Rs/m": None, "Order size": pilot.order_size(m, metres)})
    return rightcost._pilot_choices(row, patterns, list(yarn_seed.CONTENTS)), []


# ------------------------------------------------------------------ the background job
_jobs = {"thread": None}
_jobs_lock = threading.Lock()
_running = set()


def _kick():
    """Make sure the worker of this process is reading the uploads that are waiting."""
    with _jobs_lock:
        t = _jobs["thread"]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_worker, daemon=True, name="rightprice-purchase-uploads")
            _jobs["thread"] = t
            t.start()


def _worker():
    st = store.get()
    while True:
        try:
            with st.tx() as c:
                waiting = [i for i, status, _ in dp.waiting_uploads(c) if status == "queued"]
        except store.StoreUnavailable:
            waiting = []
        if not waiting:
            with _jobs_lock:
                try:
                    with st.tx() as c:
                        again = [i for i, status, _ in dp.waiting_uploads(c) if status == "queued"]
                except store.StoreUnavailable:
                    again = []
                if not again:
                    _jobs["thread"] = None
                    return
            continue
        run(waiting[0])


def _alive(c, uid, step=None, **counts):
    fields = dict(counts, alive_at=_now())
    if step is not None:
        fields["step"] = step
    dp.set_upload(c, uid, **fields)


def run(uid):
    """Read one queued upload (claimed first, so two processes never read the same one)."""
    st = store.get()
    with st.tx(write=KIND) as c:
        claimed = c.run("UPDATE upload SET status = 'working', step = %s, started_at = %s, alive_at = %s WHERE id = %s AND status = 'queued'",
                        ("Reading the file", _now(), _now(), uid)).rowcount
    if claimed != 1:
        return
    _running.add(uid)
    try:
        _load(st, uid)
    except Exception as e:
        text = e.detail if isinstance(e, common.Refused) else f"{type(e).__name__}: {e}"
        text = st.scrub(text) if hasattr(st, "scrub") else text
        try:
            with st.tx(write=KIND) as c:
                dp.set_upload(c, uid, status="failed", error=text[:2000], step="", finished_at=_now(), alive_at=_now())
        except store.StoreUnavailable:
            pass
    finally:
        _running.discard(uid)


def _load(st, uid):
    with st.tx() as c:
        data, up = dp.upload_file(c, uid), dp.upload(c, uid)
    kept, skipped, deleted, total = read_po_file(data or b"", up["filename"])
    with st.tx(write=KIND) as c:
        _alive(c, uid, "Matching the mills", rows_total=total, rows_skipped=len(skipped), skipped=skipped)
    at = _now()

    # mills: one each, every spelling kept
    with st.tx(write=KIND) as c:
        known, held = dp.aliases(c), dp.mills(c)
        spellings = sorted({r["supplier"] for r in kept})
        new_sp = [s for s in spellings if s not in known]
        plain = lambda s: VENDOR_NO.sub("", s).strip()
        learned = mills.mill_aliases({plain(s) for s in set(known) | set(spellings)})
        by_key = {m_["key"]: i for i, m_ in held.items()}
        # a mill first seen under a name cut short whose fuller name has now arrived: the fuller name is its key now
        for i, m_ in held.items():
            full = learned.get(m_["key"])
            if full and full not in by_key:
                dp.set_mill(c, i, full, m_["name"])
                by_key[full] = by_key.pop(m_["key"])
        mills_new, rows = 0, []
        for s in new_sp:
            k = mills.mill_key(plain(s), learned)
            if k not in by_key:
                by_key[k] = dp.add_mill(c, k, plain(s).title(), at)
                mills_new += 1
            rows.append((s, by_key[k]))
            known[s] = by_key[k]
        dp.add_aliases(c, rows, at)
        # the name shown: the fullest spelling received
        names = {}
        for s, i in known.items():
            if len(plain(s)) > len(names.get(i, "")):
                names[i] = plain(s)
        for i, m_ in dp.mills(c).items():
            if i in names and len(names[i]) > len(m_["name"]):
                dp.set_mill(c, i, m_["key"], names[i].title())
        _alive(c, uid, "Matching the fabrics and their Fab groups", mills_new=mills_new)
    mill_of = known

    # fabrics: one per material code; new ones in the order they first appear (earliest order line first)
    first = {}
    for r in sorted(kept, key=lambda r: (r["doc_date"], r["po_number"], r["item"])):
        first.setdefault(r["code"], r)
    latest_text = {}
    for r in sorted(kept, key=lambda r: (r["doc_date"], r["po_number"], r["item"])):
        if r["short_text"]:
            latest_text[r["code"]] = r["short_text"]
    specs = plm_specs()
    with st.tx(write=KIND) as c:
        held = dp.fabrics(c, codes=list(first))
        new_codes = [code for code in first if code not in held]
        # a fabric held (from this file or an earlier one) without a specification that the PLM list now has: grouped now
        nospec = dp.codes_without_spec(c)
        late = [code for code in nospec if code in specs]
        assigned, groups_new = fab_groups.assign(c, [(code, specs.get(code)) for code in new_codes + late], at, uid)
        dp.add_fabrics(c, [{"code": code, "description": latest_text.get(code, ""), "spec": specs.get(code),
                            "fab_group_id": assigned[code][0], "not_grouped": assigned[code][1]} for code in new_codes], at)
        dp.set_fabrics(c, [{"id": nospec[code], "spec": specs[code], "fab_group_id": assigned[code][0], "not_grouped": assigned[code][1]}
                           for code in late], at)
        dp.set_fabrics(c, [{"id": f["id"], "description": latest_text[code]} for code, f in held.items()
                           if latest_text.get(code) and latest_text[code] != f["description"]], at)
        fabric_id = dp.ids_of(c, list(first))
        _alive(c, uid, "Writing the order lines", fabrics_new=len(new_codes), groups_new=groups_new)

    # order lines, a chunk at a time
    n_new = n_changed = n_same = 0
    touched = {nospec[code] for code in late}         # their costing choices are worked out now too
    for i in range(0, len(kept), CHUNK):
        part = kept[i:i + CHUNK]
        with st.tx(write=KIND) as c:
            have = dp.lines_by_key(c, [(r["po_number"], r["item"]) for r in part])
            add, change = [], []
            for r in part:
                line = {"po_number": r["po_number"], "item": r["item"], "doc_date": r["doc_date"], "doc_type": r["doc_type"],
                        "fabric_id": fabric_id[r["code"]], "mill_id": mill_of[r["supplier"]], "supplier": r["supplier"],
                        "qty_m": float(r["qty_m"]), "price": float(r["price"]), "upload_id": uid}
                old = have.get((r["po_number"], r["item"]))
                touched.add(line["fabric_id"])
                if old is None:
                    add.append(line)
                elif old["removed_upload_id"] is None and all(old[k] == line[k] if not isinstance(line[k], float) else abs(float(old[k]) - line[k]) < 1e-9
                                                               for k in ("doc_date", "doc_type", "fabric_id", "mill_id", "supplier", "qty_m", "price")):
                    n_same += 1
                else:
                    change.append(dict(line, id=old["id"]))
                    touched.add(old["fabric_id"])
            dp.add_lines(c, add)
            dp.change_lines(c, change)
            n_new, n_changed = n_new + len(add), n_changed + len(change)
            _alive(c, uid, f"Writing the order lines ({min(i + CHUNK, len(kept)):,} of {len(kept):,})",
                   rows_new=n_new, rows_changed=n_changed, rows_same=n_same, rows_loaded=n_new + n_changed + n_same)
    # lines this file shows deleted in SAP
    removed = 0
    for i in range(0, len(deleted), CHUNK):
        with st.tx(write=KIND) as c:
            gone = [r for r in dp.lines_by_key(c, deleted[i:i + CHUNK]).values() if r["removed_upload_id"] is None]
            dp.remove_lines(c, [r["id"] for r in gone], uid)
            touched |= {r["fabric_id"] for r in gone}
            removed += len(gone)
            _alive(c, uid, rows_removed=removed)

    # the costing choices of every fabric whose lines changed (the rate card quantity band follows its metres)
    m = common.get_masters()
    ctx, patterns = pilot.inputs_context(m), masters.lists(m)["Pattern"]
    touched = sorted(touched)
    for i in range(0, len(touched), 500):
        with st.tx(write=KIND) as c:
            ids = touched[i:i + 500]
            fabs, met = dp.fabrics(c, ids=ids), dp.metres(c, ids)
            rows = []
            for code, f in fabs.items():
                sel, problems = costing_choices(code, f["spec"], float(met.get(f["id"]) or 0), m, ctx, patterns)
                rows.append({"id": f["id"], "choices": sel, "problems": problems})
            dp.set_choices(c, rows, _now())
            _alive(c, uid, f"Working out the costing choices ({min(i + 500, len(touched)):,} of {len(touched):,})")

    # done
    kinds, not_grouped = {}, {}
    for s in skipped:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    with st.tx(write=KIND) as c:
        fabs = dp.fabrics(c, codes=list(first))
        for f in fabs.values():
            if f["fab_group_id"] is None:
                k = re.sub(r":.*", "", f["not_grouped"] or "Not grouped")
                not_grouped[k] = not_grouped.get(k, 0) + 1
        summary = {"skipped_by_kind": sorted(kinds.items(), key=lambda x: -x[1]), "first": min((r["doc_date"] for r in kept), default=None),
                   "last": max((r["doc_date"] for r in kept), default=None), "fabrics": len(first), "mills": len(set(r["supplier"] for r in kept)),
                   "not_grouped": sorted(not_grouped.items(), key=lambda x: -x[1]),
                   "grouped": sum(1 for f in fabs.values() if f["fab_group_id"] is not None),
                   "costed": sum(1 for f in fabs.values() if f["choices"])}
        dp.set_upload(c, uid, status="done", step="", finished_at=_now(), alive_at=_now(), summary=summary)


# ------------------------------------------------------------------ the web requests' rules
def upload(filename, data, who=""):
    """A purchase-order file uploaded: kept as it came, and read in the background. Answers at once with its number."""
    st = need_db()
    if not data:
        raise common.Refused(400, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise common.Refused(413, f"The file is {len(data) / 1048576:.0f} MB; files up to {MAX_BYTES // 1048576} MB are read. Split it by months.")
    if not str(filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise common.Refused(400, "Upload the purchase-order export as an Excel workbook (.xlsx), as SAP gives it.")
    with st.tx(write=KIND) as c:
        uid = dp.add_upload(c, "purchase_orders", os.path.basename(str(filename)), who, data, hashlib.sha256(data).hexdigest(), _now())
    _kick()
    return {"id": uid, "status": "queued"}


def upload_shipped(who=""):
    """The purchase file that came with the code (inputs/Fabric _ 3Months_4746.xlsx, 1 Aug to 23 Nov 2026), read as
    any upload is: loading it twice gives each order line once."""
    need_db()
    if not os.path.exists(pilot.PO_FILE):
        raise common.Refused(404, "The purchase file that came with the code is not on this server.")
    with open(pilot.PO_FILE, "rb") as f:
        data = f.read()
    st = store.get()
    with st.tx(write=KIND) as c:
        uid = dp.add_upload(c, "purchase_orders", SHIPPED_NAME, who, data, hashlib.sha256(data).hexdigest(), _now())
    _kick()
    return {"id": uid, "status": "queued"}


def _tidy_stale(st):
    """Jobs that stopped without finishing (the server restarted while one was being read) are marked failed; uploads
    waiting are picked up."""
    with st.tx() as c:
        waiting = dp.waiting_uploads(c)
    now = dt.datetime.now()
    stale = [i for i, status, alive in waiting if status == "working" and i not in _running
             and (alive is None or (now - dt.datetime.fromisoformat(alive)).total_seconds() > STALE)]
    if stale:
        with st.tx(write=KIND) as c:
            for i in stale:
                dp.set_upload(c, i, status="failed", step="", finished_at=_now(),
                              error="It stopped before it finished (the server restarted while it was being read). Upload the file "
                                    "again: the order lines already read are kept once, not twice.")
    if any(status == "queued" for _, status, _ in waiting):
        _kick()


def uploads():
    """The uploads, newest first, with where each stands; and what the purchase history holds."""
    st = need_db()
    _tidy_stale(st)
    with st.tx() as c:
        ups, counts = dp.uploads(c), dp.counts(c)
    return {"uploads": ups, "counts": counts, "shipped": {"name": SHIPPED_NAME, "available": os.path.exists(pilot.PO_FILE)},
            "who_may": "Anyone signed in may upload and merge for now; stage 3 adds who may do what."}


def upload_detail(uid):
    st = need_db()
    with st.tx() as c:
        up = dp.upload(c, int(uid), skipped=True)
    if up is None:
        raise common.Refused(404, "No such upload.")
    up["skipped_count"] = len(up["skipped"])
    up["skipped"] = up["skipped"][:300]
    return up


def skipped_download(uid):
    st = need_db()
    with st.tx() as c:
        up = dp.upload(c, int(uid), skipped=True)
    if up is None:
        raise common.Refused(404, "No such upload.")
    df = pd.DataFrame([{"Row": s["row"], "Purchasing Document": s["po"], "Item": s["item"], "Material": s["material"],
                        "Left out": s["kind"], "Why": s["why"]} for s in up["skipped"]],
                      columns=["Row", "Purchasing Document", "Item", "Material", "Left out", "Why"])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return common.Download(buf.getvalue(), f"Rows left out of upload {up['id']}.xlsx")


def history(code):
    """Price over time for one fabric code: each purchase (date, mill, metres, price) and its should-cost on today's rates;
    and, since most codes were ordered once, its Fab group's purchases (every code of the same construction)."""
    st = need_db()
    code = str(code or "").strip()
    with st.tx() as c:
        fab = dp.fabrics(c, codes=[code]).get(code)
        if fab is None:
            raise common.Refused(404, f"No purchase of {code} is in the purchase history yet." + (
                "" if dp.counts(c)["lines"] else " No purchase file has been loaded: see Purchase files, under your initials."))
        lines = [fab_groups._line(r) for r in dp.lines(c, [fab["id"]])]
        groups = dp.groups(c)
        gid = fab_groups.final(groups, fab["fab_group_id"]) if fab["fab_group_id"] is not None else None
        got = fab_groups.gather(c, gid, groups) if gid is not None else None
    grp = fab_groups.history(got) if got is not None else None
    should, why = fab_groups.shoulds({code: fab})[code]
    s = fab_groups.short_spec(fab["spec"]) if fab["spec"] else {}
    out = {"code": code, "description": fab["description"], "lines": lines, "should": should, "should_why": why,
           "metres": round(sum(x["metres"] for x in lines), 2), "orders": len({x["po"] for x in lines}),
           "spec": {k: s.get(k, "") for k in ("blend_name", "dyemethod_name", "weavetype_name", "warpcount", "weftcount", "epi", "ppi",
                                              "finishedwidth", "finishedwidth_uom", "finish_name", "pattern_name")} if s else None,
           "not_grouped": None if gid is not None else (fab["not_grouped"] or "Not grouped"), "group": None}
    if grp is not None:
        g0 = groups[fab["fab_group_id"]]
        out["group"] = {k: grp[k] for k in ("code", "name", "purchases", "metres", "orders", "range", "mills", "should", "min_for_range",
                                            "first", "last")}
        out["group"]["lines"] = grp["lines"]
        out["group"]["codes"] = len(grp["fabrics"])
        out["group"]["via"] = None if g0["id"] == gid else g0["code"]          # its own group was merged into this one
    return out


def status():
    """Whether the purchase history is available here, and what it holds (for the pages to say so plainly)."""
    st = store.get()
    if st.kind == "files":
        return {"available": False, "why": fab_groups.NEEDS_DB}
    with st.tx() as c:
        return {"available": True, "counts": dp.counts(c)}
