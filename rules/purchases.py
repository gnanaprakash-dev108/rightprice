"""The purchase history: purchase-order files (the SAP export, as `inputs/Fabric _ 3Months_4746.xlsx`) read in the
background, one line per order line however often a file is uploaded, every mill once with every way it is written, one
fabric per material code with its PLM specification and the costing choices pilot.py works out from it, and each fabric's
Fab group (rules/fab_groups.py). Kept in the database only; on the files store these say they need one.

What is kept from a file, as the pilot keeps it: bulk orders (pilot.BULK_TYPES), priced, in rupees, per metre, not
deleted in SAP. Every other row is left out and the upload says which and why.

ZLOI order lines (GP, 27 Nov 2026) are kept, and left out of every calculation everywhere: price paid, metres, medians,
ranges, "above the range", the quantity band of a should-cost, Right cost's purchase-order rows (and so the supplier
pages, alerts, drafts and the dashboard's fit by fabric type). They are shown apart, as "Outliers (ZLOI)".

The newest file wins (GP's review, 27 Nov 2026). Each file has a date: the date the workbook itself says it was last
saved (SAP writes it when it exports; Excel when the file is saved again), or, when the workbook does not say, its latest
document date. A line takes its figures from the newest file that has it (two files of one date: the later upload); an
older file never changes a line, never brings back one a newer file removed, and never removes one. A newer file removes
a line when it shows it deleted or blocked in SAP, no longer bulk, not in rupees, not per metre, or with no price or
quantity, or when it has the rest of the line's order but not that line. Two uploads read at once (even in two server
processes) come out the same as one after the other."""
import contextlib
import datetime as dt
import hashlib
import io
import os
import re
import socket
import threading
import time
import warnings
import zipfile
from collections import namedtuple

import pandas as pd

from rules import common, fab_groups, mills, rightcost
import data_purchases as dp
import grouping
import masters
import store
import yarn_seed

with warnings.catch_warnings():         # pilot.py turns warnings off for its own run; not for the app
    import pilot

KIND, STATUS = dp.KIND, dp.STATUS
OUTLIER_TYPES = set(dp.OUTLIER_TYPES)
REQUIRED = ["Purchasing Document", "Item", "Document Date", "Material", "Order Quantity", "Order Unit", "Net Price",
            "Name of Supplier", "Purchasing Doc. Type", "Deletion Indicator", "Currency"]
SHIPPED_NAME = "Fabric _ 3Months_4746.xlsx (the purchase file that came with the code)"
BEAT = 15                   # seconds between a running job's signs of life
STALE = 90                  # seconds without one after which a job is taken to have stopped (a restart): it is read again
CHUNK = 1000                # order lines written per transaction, so pages are never held up for long
MAX_BYTES = 40 * 1024 * 1024    # a purchase-order file larger than this is refused (the 4-month export is about 4 MB)
MAX_LISTED = 50000          # rows left out listed one by one (the counts cover them all)
VENDOR_NO = re.compile(r"^\d+\s+")
# a newer file showing a line like this removes it from what was bought
REMOVING = {"Deleted or blocked in SAP", "Not a bulk order", "Not in rupees", "Not per metre", "No price", "No quantity"}
need_db = fab_groups.need_db
Line = namedtuple("Line", "row po item date type code supplier qty price")


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
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def _number(v):
    if isinstance(v, str):
        v = v.replace(",", "").strip()
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(x) else x


def _date(v):
    """A document date as (ISO date, None), or (None, why). Dates written as text are read as year-month-day
    (2026-04-03 is 3 April); SAP's own 03.04.2026 is day.month.year; 03/04/2026 is refused, as it could be either."""
    if _blank(v):
        return None, "No document date"
    if isinstance(v, (dt.datetime, dt.date)):
        return (v.date() if isinstance(v, dt.datetime) else v).isoformat(), None
    if isinstance(v, (int, float)):                 # an Excel day number not formatted as a date
        if 20000 <= v <= 80000:
            return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat(), None
        return None, f"Document date {v:g} is not a date"
    t = str(v).strip()
    try:
        m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?", t)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), None
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t)
        if m:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(), None
        m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if a > 12 or a == b:
                return dt.date(y, b, a).isoformat(), None
            if b > 12:
                return dt.date(y, a, b).isoformat(), None
            return None, (f"Document date {t} could be {a} {dt.date(2000, b, 1):%B} or {b} {dt.date(2000, a, 1):%B}: "
                          f"write it as {y}-{b:02d}-{a:02d} (year-month-day) or as an Excel date")
    except ValueError:
        pass
    return None, f"Document date {t} could not be read"


def _file_date(data, kept):
    """The file's date and where it was read: the date the workbook says it was last saved (else made), or its latest
    document date."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("docProps/core.xml").decode("utf8", "replace")
        for tag, words in (("modified", "the date the workbook was saved"), ("created", "the date the workbook was made")):
            m = re.search(rf"<dcterms:{tag}[^>]*>\s*([^<\s]+)\s*</dcterms:{tag}>", xml)
            if m:
                d = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                if d.tzinfo:
                    d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
                return d.isoformat(timespec="seconds"), words
    except (KeyError, ValueError, zipfile.BadZipFile, OSError):
        pass
    last = max((l.date for l in kept), default=None)
    return (last + "T00:00:00", "its latest document date") if last else (_now(), "the time it was uploaded")


# ------------------------------------------------------------------ reading a purchase-order file
class Read:
    """What a purchase-order file holds: the lines kept (ZLOI included), the rows left out with why, the lines it shows
    as no longer bought, every order and item it has, the number of rows, the latest short text of each code, and its date."""

    def __init__(self):
        self.kept, self.skipped, self.removing, self.orders, self.total, self.texts = [], [], [], {}, 0, {}
        self.file_date = self.file_date_from = None


def read_po_file(data, filename=""):
    """Read a purchase-order file row by row (little memory, whatever its size). Refused when it is not a workbook in the
    SAP export's shape."""
    from openpyxl import load_workbook
    out = Read()
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise common.Refused(400, f"{filename or 'The file'} could not be read as an Excel workbook ({type(e).__name__}). "
                                  "Upload the purchase-order export (.xlsx) as SAP gives it.")
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = next(rows, None) or ()
        col = {}
        for i, h in enumerate(header):
            col.setdefault("" if h is None else str(h).strip(), i)
        missing = [c for c in REQUIRED if c not in col]
        if missing:
            raise common.Refused(400, f"{filename or 'This file'} is not a purchase-order export in the shape RightPrice reads: the "
                                      f"column{'s' if len(missing) > 1 else ''} {', '.join(missing)} {'are' if len(missing) > 1 else 'is'} missing. "
                                      "It needs the SAP columns Purchasing Document, Item, Document Date, Material, Short Text, Order "
                                      "Quantity, Order Unit, Net Price, Name of Supplier, Currency, Purchasing Doc. Type and Deletion Indicator.")
        bulk, first, names = set(pilot.BULK_TYPES), {}, {}
        text_col = col.get("Short Text")
        for n, values in enumerate(rows):
            if values is None or all(_blank(v) for v in values):
                continue
            row = n + 2                                 # the row number Excel shows (the headings are row 1)
            out.total += 1
            get = lambda c: values[col[c]] if col[c] < len(values) else None
            po, item = _text_id(get("Purchasing Document")), _text_id(get("Item"))
            material = "" if _blank(get("Material")) else str(get("Material")).strip()

            def skip(kind, why):
                if len(out.skipped) < MAX_LISTED:
                    out.skipped.append((row, po, item, material, kind, why))
                else:
                    out.skipped.append((None, None, None, None, kind, None))       # counted, not listed
            if not po or not item:
                skip("No order number", "No order number or item: a total line or an empty row")
                continue
            out.orders.setdefault(po, set()).add(item)
            if (po, item) in first:
                skip("Repeated in this file", f"The same order line as row {first[(po, item)]} of this file")
                continue
            first[(po, item)] = row
            text = lambda c: "" if _blank(get(c)) else str(get(c)).strip()
            dtype, flag, cur, unit = text("Purchasing Doc. Type"), text("Deletion Indicator"), text("Currency"), text("Order Unit")
            price, qty = _number(get("Net Price")), _number(get("Order Quantity"))
            supplier = text("Name of Supplier")
            day, day_why = _date(get("Document Date"))
            why = None
            if flag:
                why = ("Deleted or blocked in SAP", f"Deletion indicator {flag} in SAP ({'deleted' if flag == 'L' else 'blocked' if flag == 'S' else 'marked'})")
            elif dtype not in bulk:
                why = ("Not a bulk order", f"Order type {dtype or '(blank)'} is not a bulk order (bulk: {', '.join(pilot.BULK_TYPES)})")
            elif cur != "INR":
                why = ("Not in rupees", f"Priced in {cur or '(no currency)'}, not rupees")
            elif unit != "M":
                why = ("Not per metre", f"Ordered in {unit or '(no unit)'}, not metres")
            elif price is None or price <= 0:
                why = ("No price", "No net price")
            elif qty is None or qty <= 0:
                why = ("No quantity", "No order quantity")
            elif not material:
                why = ("No material code", "No material (fabric) code")
            elif not supplier:
                why = ("No supplier", "No supplier name")
            elif day is None:
                why = ("Date not read", day_why)
            if why:
                skip(*why)
                if why[0] in REMOVING:
                    out.removing.append((po, item, why[1]))
                continue
            supplier = names.setdefault(supplier, supplier)            # one string per spelling, not one per line
            out.kept.append(Line(row, po, item, day, dtype, names.setdefault(material, material), supplier, qty, price))
            st = "" if text_col is None or _blank(values[text_col] if text_col < len(values) else None) else str(values[text_col]).strip()
            if st:
                k = (day, po, item)
                if material not in out.texts or out.texts[material][0] <= k:
                    out.texts[material] = (k, st)
    finally:
        wb.close()
    out.file_date, out.file_date_from = _file_date(data, out.kept)
    return out


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


def quantity_terms(route, metres, m):
    """The rate card quantity band and order size slab from the metres bought (ZLOI left out), as pilot.py sets them.
    With no metres the order size is not known: no slab is set, so the costing takes its own default, as Create cost does."""
    return pilot.quantity_band(route, metres or 0), (pilot.order_size(m, metres) if metres else None)


def costing_choices(code, spec, metres, m, ctx, patterns):
    """The costing choices for one fabric, worked out from its PLM specification exactly as pilot.py does (the rate card
    quantity band and the order size from its metres on record, ZLOI left out), in the form Right cost costs purchase
    orders in (rightcost._pilot_choices). (choices, []) or (None, why not costed)."""
    if not spec:
        return None, ["No PLM specification for this code"]
    s = fab_groups.short_spec(spec)
    if s.get("productgroup_name") != "Woven":
        return None, [f"Not a woven fabric ({s.get('productgroup_name') or 'blank'} in the PLM)"]
    s["Content group"] = grouping.blend_group(s.get("blend_name"))
    row, why = pilot.fabric_inputs(code, s, ctx, metres)
    if why:
        return None, [why]
    band, slab = quantity_terms(row["Route"], metres, m)
    row = dict(row, **{"PO price Rs/m": None, "PO metres": metres or None, "Rate card quantity": band, "Order size": slab})
    return rightcost._pilot_choices(row, patterns, list(yarn_seed.CONTENTS)), []


# ------------------------------------------------------------------ the background job
_jobs = {"thread": None}
_jobs_lock = threading.Lock()
_running = set()
RUNNER = f"{socket.gethostname()}:{os.getpid()}"


def _kick():
    """Make sure the worker of this process is reading the uploads that are waiting."""
    with _jobs_lock:
        t = _jobs["thread"]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_worker, daemon=True, name="rightprice-purchase-uploads")
            _jobs["thread"] = t
            t.start()


def _queued(st):
    try:
        with st.tx() as c:
            return [i for i, status, _, _ in dp.waiting_uploads(c) if status == "queued"]
    except store.StoreUnavailable:
        return []


def _worker():
    st = store.get()
    while True:
        waiting = _queued(st)
        if not waiting:
            with _jobs_lock:
                if not _queued(st):
                    _jobs["thread"] = None
                    return
            continue
        run(waiting[0])


GIVE_WAY = 0.02             # seconds a job leaves the store free after each of its transactions


@contextlib.contextmanager
def _job_tx(st, write=None):
    """A transaction of the background job, after which it gives way for a moment: the store serves one request at a
    time in each process, and a job going straight from one transaction to the next could keep pages waiting."""
    try:
        with st.tx(write=write) as c:
            yield c
    finally:
        time.sleep(GIVE_WAY)


def _status(uid, **fields):
    """A job's progress, written without moving the purchase history's version (no page needs redoing for it)."""
    with _job_tx(store.get(), STATUS) as c:
        dp.set_upload(c, uid, **fields)


class _Beat(threading.Thread):
    """A running job's sign of life every BEAT seconds, whatever step it is in."""

    def __init__(self, uid):
        super().__init__(daemon=True, name=f"rightprice-upload-{uid}-alive")
        self.uid, self.stop = uid, threading.Event()

    def run(self):
        while not self.stop.wait(BEAT):
            try:
                _status(self.uid, alive_at=_now())
            except Exception:
                pass


def run(uid):
    """Read one queued upload (claimed first, so two processes never read the same one)."""
    st = store.get()
    _running.add(uid)           # before the claim: resume() in this process never takes it for one a restart left
    try:
        with st.tx(write=STATUS) as c:
            claimed = c.run("UPDATE upload SET status = 'working', step = %s, started_at = %s, alive_at = %s, runner = %s WHERE id = %s AND status = 'queued'",
                            ("Reading the file", _now(), _now(), RUNNER, uid)).rowcount
    except Exception:
        _running.discard(uid)
        raise
    if claimed != 1:
        _running.discard(uid)
        return
    beat = _Beat(uid)
    beat.start()
    try:
        _load(st, uid)
    except Exception as e:
        text = e.detail if isinstance(e, common.Refused) else f"{type(e).__name__}: {e}"
        text = st.scrub(text) if hasattr(st, "scrub") else text
        try:
            _status(uid, status="failed", error=text[:2000], step="", finished_at=_now(), alive_at=_now())
        except store.StoreUnavailable:
            pass
    finally:
        beat.stop.set()
        _running.discard(uid)


def _load(st, uid):
    with _job_tx(st) as c:
        data, up = dp.upload_file(c, uid), dp.upload(c, uid)
    rd = read_po_file(data or b"", up["filename"])
    data = None
    fdate, name = rd.file_date, up["filename"]
    kinds = {}
    for s in rd.skipped:
        kinds[s[4]] = kinds.get(s[4], 0) + 1
    _status(uid, step="Matching the mills", rows_total=rd.total, rows_skipped=len(rd.skipped), file_date=fdate, file_date_from=rd.file_date_from,
            rows_outliers=sum(1 for l in rd.kept if l.type in OUTLIER_TYPES),
            skipped=[{"row": s[0], "po": s[1], "item": s[2], "material": s[3], "kind": s[4], "why": s[5]} for s in rd.skipped if s[0] is not None])
    at = _now()

    # mills: one each, every spelling kept
    with _job_tx(st, KIND) as c:
        known, held = dp.aliases(c), dp.mills(c)
        spellings = sorted({l.supplier for l in rd.kept})
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
        names = {}                                  # the name shown: the fullest spelling received
        for s, i in known.items():
            if len(plain(s)) > len(names.get(i, "")):
                names[i] = plain(s)
        for i, m_ in dp.mills(c).items():
            if i in names and len(names[i]) > len(m_["name"]):
                dp.set_mill(c, i, m_["key"], names[i].title())
    _status(uid, step="Matching the fabrics and their Fab groups", mills_new=mills_new)
    mill_of = known

    # fabrics: one per material code; then every fabric's Fab group worked out again (new codes placed, corrected ones moved)
    first = {}
    for l in rd.kept:
        k = (l.date, l.po, l.item)
        if l.code not in first or k < first[l.code]:
            first[l.code] = k
    specs = plm_specs()
    with _job_tx(st) as c:                                  # the signatures are worked out before the store is held for writing
        codes = set(dp.fabric_index(c)) | set(first)
    ready = fab_groups.signatures(specs, codes)
    with _job_tx(st, KIND) as c:
        held = dp.ids_of(c, list(first))
        new_codes = [code for code in sorted(first, key=lambda x: (first[x], x)) if code not in held]
        dp.add_fabrics(c, [{"code": code, "description": rd.texts.get(code, (None, ""))[1]} for code in new_codes], at)
        old_text = dict(c.all(f"SELECT code, description FROM fabric WHERE id IN {store._in(len(held))}", list(held.values()))) if held else {}
        dp.set_fabrics(c, [{"id": held[code], "description": rd.texts[code][1]} for code in held
                           if code in rd.texts and rd.texts[code][1] != old_text.get(code)], at)
        groups_new, moves = fab_groups.regroup(c, specs, first, set(new_codes), at, uid, ready)
        fabric_id = dp.ids_of(c, list(first))
    _status(uid, step="Writing the order lines", fabrics_new=len(new_codes), groups_new=groups_new)

    # order lines, a chunk at a time: the newest file's figures win
    me = (fdate, uid)
    newer = lambda line: me > (line["state_file_date"], line["state_upload_id"])
    n = {"new": 0, "changed": 0, "same": 0, "older": 0, "removed": 0, "dropped": 0}
    touched = {f for f, _, _, _ in moves}
    figures = ("doc_date", "doc_type", "fabric_id", "mill_id", "supplier", "qty_m", "price")
    for i in range(0, len(rd.kept), CHUNK):
        part = rd.kept[i:i + CHUNK]
        with _job_tx(st, KIND) as c:
            have = dp.lines_by_key(c, [(l.po, l.item) for l in part])
            add, change, touch = [], [], []
            for l in part:
                line = {"po_number": l.po, "item": l.item, "doc_date": l.date, "doc_type": l.type, "fabric_id": fabric_id[l.code],
                        "mill_id": mill_of[l.supplier], "supplier": l.supplier, "qty_m": float(l.qty), "price": float(l.price),
                        "upload_id": uid, "state_file_date": fdate, "state_upload_id": uid}
                old = have.get((l.po, l.item))
                if old is None:
                    add.append(line)
                    touched.add(line["fabric_id"])
                elif not newer(old):
                    n["older"] += 1
                elif old["removed_upload_id"] is None and all(old[k] == line[k] if not isinstance(line[k], float) else abs(float(old[k]) - line[k]) < 1e-9
                                                               for k in figures):
                    touch.append((fdate, uid, old["id"]))
                    n["same"] += 1
                else:
                    change.append(dict(line, id=old["id"]))
                    touched |= {line["fabric_id"], old["fabric_id"]}
            dp.add_lines(c, add)
            dp.change_lines(c, change)
            dp.touch_lines(c, touch)
            n["new"], n["changed"] = n["new"] + len(add), n["changed"] + len(change)
        _status(uid, step=f"Writing the order lines ({min(i + CHUNK, len(rd.kept)):,} of {len(rd.kept):,})", rows_new=n["new"],
                rows_changed=n["changed"], rows_same=n["same"], rows_older=n["older"], rows_loaded=n["new"] + n["changed"] + n["same"] + n["older"],
                alive_at=_now())
    # lines this newer file shows as no longer bought (deleted, blocked, not bulk, not rupees ...)
    for i in range(0, len(rd.removing), CHUNK):
        part = rd.removing[i:i + CHUNK]
        with _job_tx(st, KIND) as c:
            have = dp.lines_by_key(c, [(po, item) for po, item, _ in part])
            gone, touch = [], []
            for po, item, why in part:
                old = have.get((po, item))
                if old is None or not newer(old):
                    continue
                if old["removed_upload_id"] is None:
                    gone.append((f"{name}: {why}", old["id"]))
                    touched.add(old["fabric_id"])
                else:
                    touch.append((fdate, uid, old["id"]))
            dp.remove_lines(c, gone, uid, fdate)
            dp.touch_lines(c, touch)
            n["removed"] += len(gone)
    # lines held for an order this newer file has, that it does not have
    pos = sorted(rd.orders)
    for i in range(0, len(pos), CHUNK):
        with _job_tx(st, KIND) as c:
            gone = []
            for (po, item), old in dp.lines_of_orders(c, pos[i:i + CHUNK]).items():
                if item not in rd.orders[po] and old["removed_upload_id"] is None and newer(old):
                    gone.append((f"Not in {name}, which has the rest of order {po}", old["id"]))
                    touched.add(old["fabric_id"])
            dp.remove_lines(c, gone, uid, fdate)
            n["dropped"] += len(gone)
    _status(uid, step="Working out the costing choices", rows_removed=n["removed"], rows_dropped=n["dropped"])

    # the costing choices of every fabric whose lines or specification changed (the quantity band follows its metres)
    m = common.get_masters()
    ctx, patterns = pilot.inputs_context(m), masters.lists(m)["Pattern"]
    touched = sorted(touched)
    for i in range(0, len(touched), 500):
        with _job_tx(st, KIND) as c:
            ids = touched[i:i + 500]
            fabs, met = dp.fabrics(c, ids=ids), dp.metres(c, ids)
            rows = []
            for code, f in fabs.items():
                sel, problems = costing_choices(code, f["spec"], float(met.get(f["id"]) or 0), m, ctx, patterns)
                rows.append({"id": f["id"], "choices": sel, "problems": problems})
            dp.set_choices(c, rows, _now())

    # done
    with _job_tx(st, KIND) as c:
        fabs = dp.fabric_index(c)
        not_grouped, grouped = {}, 0
        for code in first:
            f = fabs[code]
            if f["fab_group_id"] is None:
                k = re.sub(r":.*", "", f["not_grouped"] or "Not grouped")
                not_grouped[k] = not_grouped.get(k, 0) + 1
            else:
                grouped += 1
        costed = c.one(f"SELECT count(*) FROM fabric WHERE choices IS NOT NULL AND code IN {store._in(len(first))}", list(first))[0] if first else 0
        summary = {"skipped_by_kind": sorted(kinds.items(), key=lambda x: -x[1]), "first": min((l.date for l in rd.kept), default=None),
                   "last": max((l.date for l in rd.kept), default=None), "fabrics": len(first), "mills": len({l.supplier for l in rd.kept}),
                   "not_grouped": sorted(not_grouped.items(), key=lambda x: -x[1]), "grouped": grouped, "costed": costed,
                   "regrouped": len(moves), "listed": min(len(rd.skipped), MAX_LISTED)}
        dp.set_upload(c, uid, status="done", step="", finished_at=_now(), alive_at=_now(), summary=summary)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def resume():
    """Uploads left half-read by a restart are read again from the start (safe: the newest file's figures win whatever
    the order), and uploads waiting are picked up. Run at start, and whenever the uploads are listed."""
    st = store.get()
    if st.kind == "files":
        return
    try:
        with st.tx() as c:
            waiting = dp.waiting_uploads(c)
    except store.StoreUnavailable:
        return
    host, now = socket.gethostname(), dt.datetime.now()
    again = []
    for i, status, alive, runner in waiting:
        if status != "working" or i in _running:
            continue
        h, _, pid = (runner or "").rpartition(":")
        gone_here = h == host and pid.isdigit() and int(pid) != os.getpid() and not _pid_alive(int(pid))
        quiet = alive is None or (now - dt.datetime.fromisoformat(alive)).total_seconds() > STALE
        if gone_here or quiet or (h == host and pid == str(os.getpid())):
            again.append(i)
    if again:
        with st.tx(write=STATUS) as c:
            for i in again:
                c.run("UPDATE upload SET status = 'queued', runner = NULL, step = %s WHERE id = %s AND status = 'working'",
                      ("The server restarted while it was being read: it is read again from the start", i))
    if again or any(status == "queued" for _, status, _, _ in waiting):
        _kick()


def _resume_quietly():
    try:
        resume()
    except Exception:           # the database not reachable yet: the next listing of the uploads tries again
        pass


def resume_at_start():
    """At start: pick up what a restart left, and look again once a job elsewhere would have shown it is alive."""
    _resume_quietly()
    later = threading.Timer(STALE + 10, _resume_quietly)
    later.daemon = True
    later.start()


# ------------------------------------------------------------------ the web requests' rules
def upload(filename, data, who=""):
    """A purchase-order file uploaded: kept as it came, and read in the background. Answers at once with its number."""
    st = need_db()
    if not data:
        raise common.Refused(400, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise common.Refused(413, f"The file is larger than {MAX_BYTES // 1048576} MB, the most read at once. Export a shorter period, or split it by months.")
    if not str(filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise common.Refused(400, "Upload the purchase-order export as an Excel workbook (.xlsx), as SAP gives it.")
    with st.tx(write=STATUS) as c:
        uid = dp.add_upload(c, "purchase_orders", os.path.basename(str(filename)), who, data, hashlib.sha256(data).hexdigest(), _now())
    _kick()
    return {"id": uid, "status": "queued"}


def upload_shipped(who=""):
    """The purchase file that came with the code (inputs/Fabric _ 3Months_4746.xlsx, 1 Aug to 23 Nov 2026), read as
    any upload is: its date is the date SAP exported it, so it never undoes a newer file."""
    need_db()
    if not os.path.exists(pilot.PO_FILE):
        raise common.Refused(404, "The purchase file that came with the code is not on this server.")
    with open(pilot.PO_FILE, "rb") as f:
        data = f.read()
    st = store.get()
    with st.tx(write=STATUS) as c:
        uid = dp.add_upload(c, "purchase_orders", SHIPPED_NAME, who, data, hashlib.sha256(data).hexdigest(), _now())
    _kick()
    return {"id": uid, "status": "queued"}


def uploads():
    """The uploads, newest first, with where each stands; and what the purchase history holds."""
    st = need_db()
    resume()
    with st.tx() as c:
        ups, counts = dp.uploads(c), dp.counts(c)
    return {"uploads": ups, "counts": counts, "shipped": {"name": SHIPPED_NAME, "available": os.path.exists(pilot.PO_FILE)},
            "who_may": "Uploading and merging are admin actions (rules/access.py: do:upload_purchases, do:merge_groups)."}


def upload_detail(uid):
    st = need_db()
    with st.tx() as c:
        up = dp.upload(c, int(uid), skipped=True)
    if up is None:
        raise common.Refused(404, "No such upload.")
    up["skipped_count"] = up["rows_skipped"] if up["rows_skipped"] is not None else len(up["skipped"])
    up["skipped_listed"] = len(up["skipped"])
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
    """Price over time for one fabric code: each purchase (date, mill, metres, price) and its should-cost as Right cost
    has it (on the yarn rates of its order month, today's where none is dated); and, since most codes were ordered once,
    its Fab group's purchases (every code of the same construction). ZLOI lines are in none of it: they are listed
    apart, as outliers."""
    st = need_db()
    code = str(code or "").strip()
    with st.tx() as c:
        fab = dp.fabrics(c, codes=[code]).get(code)
        if fab is None:
            raise common.Refused(404, f"No purchase of {code} is in the purchase history yet." + (
                "" if dp.counts(c)["lines"] else " No purchase file has been loaded: see Purchase files, under your initials."))
        own = dp.lines(c, [fab["id"]])
        lines = [fab_groups._line(r) for r in own]
        outliers = [fab_groups._line(r) for r in dp.lines(c, [fab["id"]], outliers=True)]
        groups = dp.groups(c)
        gid = fab_groups.final(groups, fab["fab_group_id"]) if fab["fab_group_id"] is not None else None
        got = fab_groups.gather(c, gid, groups) if gid is not None else None
        moves = [m for m in dp.regroups(c, [fab["fab_group_id"]] if fab["fab_group_id"] else []) if m["code"] == code]
    grp = fab_groups.history(got) if got is not None else None
    should, why, on = fab_groups.shoulds({code: fab}, own)[code]          # on its order month's yarn rates, as in Right cost
    s = fab_groups.short_spec(fab["spec"]) if fab["spec"] else {}
    out = {"code": code, "description": fab["description"], "lines": lines, "outliers": outliers, "should": should, "should_why": why, "should_on": on,
           "metres": round(sum(x["metres"] for x in lines), 2), "orders": len({x["po"] for x in lines}),
           "spec": {k: s.get(k, "") for k in ("blend_name", "dyemethod_name", "weavetype_name", "warpcount", "weftcount", "epi", "ppi",
                                              "finishedwidth", "finishedwidth_uom", "finish_name", "pattern_name")} if s else None,
           "not_grouped": None if gid is not None else (fab["not_grouped"] or "Not grouped"), "group": None,
           "moved": [{"from": groups[m["from_group_id"]]["code"] if m["from_group_id"] else None, "why": m["why"], "at": m["at"]} for m in moves]}
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


# ------------------------------------------------------------------ Right cost's purchase-order rows, ZLOI left out
# Right cost lists the 1,696 fabrics the pilot costed (pilot/Pilot_Results.xlsx, never changed or re-run). Their price
# paid, metres, quantity band, should-cost and verdict are worked out again from the order lines bought, ZLOI left out
# (GP, 27 Nov 2026): from the purchase history; until the purchase file that came with the code has been loaded into
# it, that file is read the same way as well (the history's lines win). A fabric whose lines are the pilot's own (no ZLOI,
# nothing bought since) keeps the pilot's figures exactly.
_lines_memo = {"key": None, "val": None}
_shipped_memo = {"key": None, "val": None}
_rows_memo = {"key": None, "val": None}


def _shipped():
    """The purchase file that came with the code, read as an upload is: (its SHA-256, its kept lines)."""
    key = common._mtime(pilot.PO_FILE)
    if _shipped_memo["key"] != key:
        val = (None, [])
        if key is not None:
            with open(pilot.PO_FILE, "rb") as f:
                data = f.read()
            val = (hashlib.sha256(data).hexdigest(), read_po_file(data, os.path.basename(pilot.PO_FILE)).kept)
        _shipped_memo.update(key=key, val=val)
    return _shipped_memo["val"]


def pilot_records():
    """The pilot's purchase-order fabrics, as pilot/Pilot_Results.xlsx (sheet Fabrics) holds them."""
    def load():
        f = pd.read_excel(common.PILOT, sheet_name="Fabrics")
        f = f.astype(object).where(pd.notna(f), None)
        return f.to_dict("records")
    return common.cached(common.PILOT + "#fabrics", load) if os.path.exists(common.PILOT) else []


def bought_lines():
    """(key, {code: [(po, item, date, type, supplier, qty, price)]} for the pilot's codes, [ZLOI lines of every code as
    (code, po, item, date, type, supplier, qty, price)]): the order lines counted as bought, ZLOI included and flagged
    by their type. The key changes when they do."""
    st = store.get()
    dbv = st.version(KIND) if st.kind != "files" else None
    key = (dbv, common._mtime(pilot.PO_FILE), common._mtime(common.PILOT))
    if _lines_memo["key"] == key:
        return _lines_memo["val"]
    codes = {str(r["Fabric code"]) for r in pilot_records()}
    held, zl, loaded, any_lines = [], [], False, False
    sha, base = _shipped() if os.path.exists(pilot.PO_FILE) else (None, [])
    if st.kind != "files":
        with st.tx() as c:
            any_lines = c.one("SELECT count(*) FROM purchase_line")[0] > 0
            if any_lines:
                loaded = sha is not None and dp.shipped_loaded(c, sha)
                held = dp.lines_for_codes(c, codes)
                zl = dp.outlier_lines(c)
                base_keys = {(l.po, l.item) for l in base} if not loaded else set()
                over = dp.lines_by_key(c, list(base_keys)) if base_keys else {}
    lines, outl = {}, {}
    if not loaded:                      # the file that came with the code, under whatever the history holds
        for l in base:
            if any_lines and (l.po, l.item) in over:
                continue
            if l.code in codes:
                lines[(l.po, l.item)] = (l.code, l.po, l.item, l.date, l.type, l.supplier, float(l.qty), float(l.price))
            if l.type in OUTLIER_TYPES:
                outl[(l.po, l.item)] = (l.code, l.po, l.item, l.date, l.type, l.supplier, float(l.qty), float(l.price))
    for code, po, item, day, typ, sup, qty, price, removed in held:
        if not removed:
            lines[(po, item)] = (code, po, item, day, typ, sup, float(qty), float(price))
    for code, po, item, day, typ, sup, qty, price in zl:
        outl[(po, item)] = (code, po, item, day, typ, sup, float(qty), float(price))
    by_code = {}
    for code, po, item, day, typ, sup, qty, price in sorted(lines.values(), key=lambda x: (x[3], x[1], x[2])):
        by_code.setdefault(code, []).append((po, item, day, typ, sup, qty, price))
    val = (hashlib.sha256(repr(sorted(lines.values())).encode()).hexdigest(), by_code, sorted(outl.values(), key=lambda x: (x[3], x[1], x[2])))
    _lines_memo.update(key=key, val=val)
    return val


def _outlier(code, po, item, day, sup, qty, price):
    return {"code": code, "date": day, "po": po, "item": item, "mill": VENDOR_NO.sub("", sup).strip().title(), "metres": round(qty, 2), "price": round(price, 2)}


def pilot_rows():
    """(key, rows): the pilot's purchase-order fabrics with their price paid, metres, quantity band, should-cost and gap
    worked out again from the lines bought, ZLOI left out. Each row keeps the pilot's columns, plus "Outliers (ZLOI)"
    and "Worked out again" (why, or None when the pilot's own figures stand). Kept until the lines or the rates change."""
    digest, by_code, _ = bought_lines()
    st = store.get()
    key = (digest, st.version("rates"), common._mtime(common.PILOT))
    if _rows_memo["key"] == key:
        return _rows_memo["val"]
    m = common.get_masters()
    patterns = masters.lists(m)["Pattern"]
    out = []
    for r in pilot_records():
        code = str(r["Fabric code"])
        ls = by_code.get(code, [])
        regular = [x for x in ls if x[3] not in OUTLIER_TYPES]
        zl = [_outlier(code, po, item, day, sup, qty, price) for po, item, day, typ, sup, qty, price in ls if typ in OUTLIER_TYPES]
        metres = sum(x[5] for x in regular)
        value = sum(x[5] * x[6] for x in regular)
        price = round(value / metres, 2) if metres else None
        same = (not zl and len(regular) == r["PO lines"] and abs(metres - float(r["PO metres"] or 0)) < 1e-6
                and price is not None and r["PO price Rs/m"] is not None and abs(price - round(float(r["PO price Rs/m"]), 2)) < 0.005)
        if same:
            out.append(dict(r, **{"Outliers (ZLOI)": [], "Worked out again": None}))
            continue
        nr = dict(r)
        band, slab = quantity_terms(r["Route"], metres, m)
        top = {}
        for x in regular:
            top[x[4]] = top.get(x[4], 0) + x[5]
        nr.update({"PO metres": metres or None, "PO price Rs/m": price, "PO lines": len(regular), "Rate card quantity": band, "Order size": slab,
                   "Supplier": max(top, key=lambda s: (top[s], s)) if top else r["Supplier"], "Outliers (ZLOI)": zl,
                   "Worked out again": ("ZLOI lines left out" if zl else "purchases since the pilot") + ("; no other purchase, so no price paid" if not regular else "")})
        try:
            res = masters.cost(rightcost._pilot_choices(nr, patterns, list(yarn_seed.CONTENTS)), m)
        except Exception as e:                  # a choice no longer on today's lists
            nr["Worked out again"] += f"; not costed on today's rates: {e}"
            out.append(nr)
            continue
        nr.update({"Should-cost Rs/m": round(res["total_per_m"], 2), "Should-cost Rs/kg": round(res["per_kg"], 1), "GSM": round(res["gsm"], 1),
                   "Placeholder rates used": ", ".join(res["placeholders"]) or None})
        for b in res["buckets"]:
            nr[f"{b['name']} Rs/m"] = round(b["amount"], 2)
        gap = None if price is None else round(price - res["total_per_m"], 2)
        nr.update({"PO minus should-cost Rs/m": gap, "PO above should-cost %": None if gap is None else round((price / res["total_per_m"] - 1) * 100, 1),
                   "Excess Rs": None if gap is None else gap * metres})
        out.append(nr)
    val = (key, out)
    _rows_memo.update(key=key, val=val)
    return val


def outliers_for_mill(key):
    """The ZLOI lines of one mill (mills.mill_key, as Right cost learned the names), newest first."""
    _, _, zl = bought_lines()
    return [_outlier(code, po, item, day, sup, qty, price) for code, po, item, day, typ, sup, qty, price in reversed(zl)
            if mills.mill_key(VENDOR_NO.sub("", sup).strip()) == key]
