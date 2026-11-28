"""The purchase history: purchase-order files (the SAP export, as `inputs/Fabric _ 3Months_4746.xlsx`) read in the
background, one line per order line however often a file is uploaded, every mill once with every way it is written, one
fabric per material code with its PLM specification and the costing choices pilot.py works out from it, and each fabric's
Fab group (rules/fab_groups.py). Kept in the database only; on the files store these say they need one.

What is kept from a file, as the pilot keeps it: bulk orders (pilot.BULK_TYPES), priced, in rupees, per metre, not
deleted in SAP. Every other row is left out and the upload says which and why.

ZLOI order lines (GP, 27 Nov 2026) are kept, and left out of every calculation everywhere: price paid, metres, medians,
ranges, "above the range", the quantity band of a should-cost, Right cost's purchase-order rows (and so the supplier
pages, alerts, drafts and the dashboard's fit by fabric type). They are shown apart, as "Outliers (ZLOI)".

The newest file wins (GP's review, 27 Nov 2026). Which file is newer is read first from what it covers (the second
review, 27 Nov 2026): a file can have been taken no earlier than its latest document date (or the report date it carries
in a column of its own) and no later than when it was saved (else, when it carries no saved date, any time since). One
file is newer than another for certain when it can have been taken no earlier than the other was at the latest; that
decides. Only where what the two cover cannot tell (a correction of the same orders, the same file saved again), the
file saved later wins (GP's decision, 28 Nov 2026, "saved later wins"), exactly as a file certainly newer does: its
figures, its removals, the lines it leaves out of an order, its marks. A saved date counts only where it can be used:
there, and not before the file's latest document date (one before it says "not used"); a file carrying a report date
counts as taken at the end of that date (its report date stands in for its saved date). Both are a file's covers_to,
which each order line's state (state_to), each mark, each order the file has (order_seen, through its upload) and a
settled disagreement carry, so the comparison is made the same way whenever, and in whichever process, a file is read:
an older or earlier-saved file read after a newer one, or at the same moment in another server process, never brings
back or changes what the newer one decided.

Every order line keeps the evidence of the newest file that covered it: its figures, or that it was shown deleted,
blocked, no longer bulk, not in rupees, not per metre, with no price or quantity, or left out of an order the file has.
That holds before any file gave the line's figures (a mark). A newer file changes or removes a line. What is left with
no way to tell (both saved at the same moment, or either file without a saved date that can be used): where a file and
the history disagree on a line, the history's figures stand and the disagreement is listed on the file's page, for an
admin to keep them or to take the file's (settle; POST /api/purchases/disagreements, the assistant's
settle_purchase_disagreements)."""
import contextlib
import datetime as dt
import hashlib
import io
import json
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


REPORT_COLUMNS = {"report date", "export date", "exported on", "extraction date", "extracted on", "run date", "data as of",
                  "as of", "as on", "as on date"}      # a column carrying the date the report was taken (SAP's own export has none)


def _saved_at(data):
    """When the workbook says it was last saved (else made), UTC: an upper bound of when its content was taken, never
    how files are put in order on its own (a file saved again later is no newer)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("docProps/core.xml").decode("utf8", "replace")
        for tag in ("modified", "created"):
            m = re.search(rf"<dcterms:{tag}[^>]*>\s*([^<\s]+)\s*</dcterms:{tag}>", xml)
            if m:
                d = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                if d.tzinfo:
                    d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
                return d.isoformat(timespec="seconds")
    except (KeyError, ValueError, zipfile.BadZipFile, OSError):
        pass
    return None


def _stamp(v):
    """A report date cell as ISO text (with its time when it has one), or None."""
    if isinstance(v, dt.datetime):
        return v.isoformat(timespec="seconds") if v.time() != dt.time(0) else v.date().isoformat()     # a date alone: that whole day
    d, _ = _date(v)
    return d


def dating(latest, report, saved):
    """What a file covers, as the history puts files in order: {file_date, file_date_from (in words), covers_from,
    covers_to, report_date, saved_at}. covers_from: the earliest it can have been taken (its report date, else its latest
    document date); covers_to: the latest (its report date, else when it was saved; None: not known, as when it carries
    no saved date or one before its latest document date). Where what two files cover cannot tell which is newer, the
    later covers_to wins (newer(): for SAP's export, the file saved later)."""
    out = {"report_date": report, "saved_at": saved, "file_date": report or latest}
    if report:
        lo = report if "T" in report else report + "T00:00:00"
        hi = report if "T" in report else report + "T23:59:59"
        words = f"taken on {report[:10]}, the report date it carries"
    elif latest:
        lo = latest + "T00:00:00"
        hi = saved if saved and saved >= lo else None
        words = f"orders up to {latest}" + (f"; saved {saved[:16].replace('T', ' ')} UTC" if saved else "; no saved date") + (
            " (before its latest order: not used)" if saved and saved < lo else "")
    else:
        lo, hi = "0001-01-01T00:00:00", saved
        words = "no document date read" + (f"; saved {saved[:16].replace('T', ' ')} UTC" if saved else "")
    return dict(out, covers_from=lo, covers_to=hi, file_date_from=words)


def order_of(a, b):
    """From what they cover alone: +1 when file a is certainly newer than file b, -1 when certainly older, 0 when it
    cannot be told. Each is (covers_from, covers_to): a is newer only when it can have been taken no earlier than b was
    at the latest."""
    if b[1] is not None and a[0] > b[1]:
        return 1
    if a[1] is not None and b[0] > a[1]:
        return -1
    return 0


def newer(a, b):
    """Which of two files is newer, and how that was told: (+1 or -1, "covers") when what they cover says so for certain
    (order_of); else, GP's decision of 28 Nov 2026, the file saved later: (+1 or -1, "saved"), by each file's covers_to,
    which is when it was saved where that can be used (there, and not before its latest document date), or the end of a
    report date it carries (that is when it was taken); (0, None) when neither tells (saved at the same moment, or either
    without a saved date that can be used). Each is (covers_from, covers_to). A file's covers_to lies within what it
    covers, so the two ways never pull apart: a file certainly newer was saved later too, and files never go round in
    a circle, whatever order they are read in."""
    o = order_of(a, b)
    if o:
        return o, "covers"
    if a[1] is not None and b[1] is not None and a[1] != b[1]:
        return (1 if a[1] > b[1] else -1), "saved"
    return 0, None


# ------------------------------------------------------------------ reading a purchase-order file
class Read:
    """What a purchase-order file holds: the lines kept (ZLOI included), the rows left out with why, the lines it shows
    as no longer bought, every order and item it has, the number of rows, the latest short text of each code, and its date."""

    def __init__(self):
        self.kept, self.skipped, self.removing, self.orders, self.total, self.texts = [], [], [], {}, 0, {}
        self.latest = self.report = None         # its latest document date, any row; a report date it carries
        self.dating = {}


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
        report_col = next((i for h, i in col.items() if h.lower() in REPORT_COLUMNS), None)
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
            if day and (out.latest is None or day > out.latest):
                out.latest = day                        # what the file covers: every row with a date, kept or not
            if report_col is not None and report_col < len(values):
                rep = _stamp(values[report_col])
                if rep and (out.report is None or rep > out.report):
                    out.report = rep
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
    out.dating = dating(out.latest, out.report, _saved_at(data))
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


def _figures(line):
    return {k: line[k] for k in FIGURES}


def _kept_view(old):
    """What the history holds of a line, for a disagreement: its figures, or why it is not counted; and which file said so."""
    return {"upload_id": old["state_upload_id"], "removed": old["removed_why"],
            "figures": None if old["fabric_id"] is None else {k: old[k] for k in FIGURES}}


def _same(old, line):
    return old["removed_upload_id"] is None and old["fabric_id"] is not None and all(
        old[k] == line[k] if not isinstance(line[k], float) else abs(float(old[k]) - line[k]) < 1e-9 for k in FIGURES)


FIGURES = ("doc_date", "doc_type", "fabric_id", "mill_id", "supplier", "qty_m", "price")


def _newest(files):
    """The newest of these files by newer(), each ((how it compares), upload id, covers_from, covers_to, file name);
    among files that cannot be told apart, the latest covers_from, then the latest upload."""
    best = None
    for x in files:
        o = 1 if best is None else newer(x[2:4], best[2:4])[0]
        if o > 0 or (o == 0 and (x[2], x[1]) > (best[2], best[1])):
            best = x
    return best


def recost(st, fabric_ids):
    """The costing choices of these fabrics worked out again (their metres set the quantity band; their specification
    the rest), a few hundred to a transaction."""
    m = common.get_masters()
    ctx, patterns = pilot.inputs_context(m), masters.lists(m)["Pattern"]
    ids = sorted(set(fabric_ids))
    for i in range(0, len(ids), 500):
        with _job_tx(st, KIND) as c:
            part = ids[i:i + 500]
            fabs, met = dp.fabrics(c, ids=part), dp.metres(c, part)
            rows = []
            for code, f in fabs.items():
                sel, problems = costing_choices(code, f["spec"], float(met.get(f["id"]) or 0), m, ctx, patterns)
                rows.append({"id": f["id"], "choices": sel, "problems": problems})
            dp.set_choices(c, rows, _now())


def _load(st, uid):
    with _job_tx(st, KIND) as c:            # a fresh start (also after a restart): this upload's own evidence is written again
        data, up = dp.upload_file(c, uid), dp.upload(c, uid)
        dp.forget_evidence(c, uid)
    rd = read_po_file(data or b"", up["filename"])
    data = None
    name, dating_ = up["filename"], rd.dating
    kinds = {}
    for s in rd.skipped:
        kinds[s[4]] = kinds.get(s[4], 0) + 1
    _status(uid, step="Matching the mills", rows_total=rd.total, rows_skipped=len(rd.skipped),
            rows_outliers=sum(1 for l in rd.kept if l.type in OUTLIER_TYPES), **dating_,
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

    # fabrics: one per material code; then every fabric's Fab group worked out again (new codes placed, corrected ones
    # moved, a group whose codes' specification was corrected renamed), each change recorded
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
        rg = fab_groups.regroup(c, specs, first, set(new_codes), at, uid, ready)
        fabric_id = dp.ids_of(c, list(first))
    _status(uid, step="Writing the order lines", fabrics_new=len(new_codes), groups_new=rg["groups_new"])

    # order lines: each keeps the evidence of the newest file that covered it (newer from what the files cover; where that
    # cannot tell, the file saved later: GP, 28 Nov 2026)
    me = (uid, dating_["covers_from"], dating_["covers_to"])
    vs = lambda old: newer(me[1:], (old["state_from"], old["state_to"]))
    # (disagree: lines this file keeps that the history holds otherwise; listed: every disagreement, removals included)
    n = {"new": 0, "changed": 0, "same": 0, "older": 0, "disagree": 0, "listed": 0, "removed": 0, "dropped": 0}
    # decided by the saved date alone, for the upload's page: {other upload: lines} where this file's word replaced that
    # one's (this file saved later), and where that one's word stood against this file's (that one saved later)
    won, lost = {}, {}
    count = lambda d, u: d.__setitem__(u, d.get(u, 0) + 1)
    touched = {f for f, _, _, _ in rg["moves"]} | set(rg["respecified"])
    with _job_tx(st, KIND) as c:                # first, what this file has of each order: a file read at the same time sees it
        dp.add_orders_seen(c, uid, rd.orders)
    for i in range(0, len(rd.kept), CHUNK):
        part = rd.kept[i:i + CHUNK]
        with _job_tx(st, KIND) as c:
            have = dp.lines_by_key(c, [(l.po, l.item) for l in part])
            seen = dp.orders_seen(c, {l.po for l in part if (l.po, l.item) not in have}, but=uid)
            add, change, touch, against, held_out, disagree = [], [], [], [], [], []
            for l in part:
                line = {"po_number": l.po, "item": l.item, "doc_date": l.date, "doc_type": l.type, "fabric_id": fabric_id[l.code],
                        "mill_id": mill_of[l.supplier], "supplier": l.supplier, "qty_m": float(l.qty), "price": float(l.price),
                        "upload_id": uid, "state_upload_id": uid, "state_from": me[1], "state_to": me[2]}
                old = have.get((l.po, l.item))
                if old is None:
                    # never held: unless a file has the rest of its order without it (newer, or not to be told apart)
                    lacking = [(newer(me[1:], (lo, hi)), u, lo, hi, fn) for u, items, lo, hi, fn in seen.get(l.po, []) if l.item not in items]
                    newer_ = [_newest(x for x in lacking if x[0][0] < 0)] if any(x[0][0] < 0 for x in lacking) else []
                    unsure = sorted((x for x in lacking if x[0][0] == 0), key=lambda x: (x[2], x[1]))
                    if not newer_ and not unsure:
                        add.append(line)
                        touched.add(line["fabric_id"])
                        continue
                    (o, by), u, lo, hi, fn = (newer_ or unsure)[-1]
                    why = f"Not in {fn} (upload {u}), which has the rest of order {l.po}"
                    add.append(line)            # its figures kept, the line not counted: the other file's evidence stands
                    held_out.append(((l.po, l.item), why, (u, lo, hi)))
                    if newer_:
                        n["older"] += 1
                        if by == "saved":
                            count(lost, u)
                    else:
                        disagree.append((l.po, l.item, {"upload_id": u, "removed": why, "figures": None}, {"figures": _figures(line)}))
                    continue
                o, by = vs(old)
                if o > 0:
                    if _same(old, line):
                        touch.append((me, old["id"]))
                        n["same"] += 1
                    else:
                        change.append(dict(line, id=old["id"]))
                        touched |= {line["fabric_id"], old["fabric_id"]} - {None}
                        if by == "saved":
                            count(won, old["state_upload_id"])
                elif o < 0:
                    n["older"] += 1
                    if by == "saved" and not _same(old, line):
                        count(lost, old["state_upload_id"])
                elif _same(old, line):
                    n["same"] += 1
                else:
                    disagree.append((l.po, l.item, _kept_view(old), {"figures": _figures(line)}))
            dp.add_lines(c, add)
            dp.change_lines(c, change)
            dp.touch_lines(c, touch)
            if held_out:
                ids = dp.lines_by_key(c, [k for k, _, _ in held_out])
                for k, why, state in held_out:
                    dp.remove_lines(c, [(why, ids[k]["id"])], state)
            dp.add_disagreements(c, uid, disagree)
            n["new"] += len(add) - len(held_out)
            n["changed"] += len(change)
            n["disagree"] += len(disagree)
            n["listed"] += len(disagree)
        _status(uid, step=f"Writing the order lines ({min(i + CHUNK, len(rd.kept)):,} of {len(rd.kept):,})", rows_new=n["new"],
                rows_changed=n["changed"], rows_same=n["same"], rows_older=n["older"], rows_disagree=n["disagree"],
                rows_loaded=n["new"] + n["changed"] + n["same"] + n["older"] + n["disagree"], alive_at=_now())
    # lines this file shows as no longer bought (deleted, blocked, not bulk, not rupees ...): removed where it is newer,
    # and marked where no file has given them yet, so an older file does not bring them back
    for i in range(0, len(rd.removing), CHUNK):
        part = rd.removing[i:i + CHUNK]
        with _job_tx(st, KIND) as c:
            have = dp.lines_by_key(c, [(po, item) for po, item, _ in part])
            gone, touch, marks, disagree = [], [], [], []
            for po, item, why in part:
                old = have.get((po, item))
                if old is None:
                    marks.append((po, item, f"{name}: {why}", me))
                    continue
                o, by = vs(old)
                if o > 0:
                    if old["removed_upload_id"] is None:
                        gone.append((f"{name}: {why}", old["id"]))
                        touched.add(old["fabric_id"])
                        if by == "saved":
                            count(won, old["state_upload_id"])
                    else:
                        touch.append((me, old["id"]))
                elif o == 0 and old["removed_upload_id"] is None:
                    disagree.append((po, item, _kept_view(old), {"removed": f"{name}: {why}"}))
                elif o < 0 and by == "saved" and old["removed_upload_id"] is None:
                    count(lost, old["state_upload_id"])
            dp.add_marks(c, marks)
            dp.remove_lines(c, gone, me)
            dp.touch_lines(c, touch)
            dp.add_disagreements(c, uid, disagree)
            n["removed"] += len(gone)
            n["listed"] += len(disagree)
    # lines held for an order this file has, that it does not have
    pos = sorted(rd.orders)
    for i in range(0, len(pos), CHUNK):
        with _job_tx(st, KIND) as c:
            gone, touch, disagree = [], [], []
            for (po, item), old in dp.lines_of_orders(c, pos[i:i + CHUNK]).items():
                if item in rd.orders[po]:
                    continue
                (o, by), why = vs(old), f"Not in {name}, which has the rest of order {po}"
                if o > 0:
                    if old["removed_upload_id"] is None:
                        gone.append((why, old["id"]))
                        touched.add(old["fabric_id"])
                        if by == "saved":
                            count(won, old["state_upload_id"])
                    else:
                        touch.append((me, old["id"]))
                elif o == 0 and old["removed_upload_id"] is None:
                    disagree.append((po, item, _kept_view(old), {"removed": why}))
                elif o < 0 and by == "saved" and old["removed_upload_id"] is None:
                    count(lost, old["state_upload_id"])
            dp.remove_lines(c, gone, me)
            dp.touch_lines(c, touch)
            dp.add_disagreements(c, uid, disagree)
            n["dropped"] += len(gone)
            n["listed"] += len(disagree)
    _status(uid, step="Working out the costing choices", rows_removed=n["removed"], rows_dropped=n["dropped"], rows_disagree=n["disagree"],
            rows_loaded=n["new"] + n["changed"] + n["same"] + n["older"] + n["disagree"])

    # the costing choices of every fabric whose lines or specification changed (the quantity band follows its metres)
    recost(st, touched - {None})

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
                   "regrouped": sum(1 for m_ in rg["moves"] if m_[1] != m_[2]), "respecified": len(rg["respecified"]), "renamed": len(rg["renamed"]),
                   "disagreements": n["listed"], "listed": min(len(rd.skipped), MAX_LISTED)}
        # which uploads the saved date decided against, with when each was saved, for the upload's page
        others = dp.upload_dates(c, set(won) | set(lost))
        said = lambda d: [dict(others.get(u, {"id": u}), lines=k) for u, k in sorted(d.items())]
        summary.update(saved_later_than=said(won), saved_earlier_than=said(lost))
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
    with st.tx(write=KIND) as c:            # a new upload on the Purchase files page: the history's version moves
        uid = dp.add_upload(c, "purchase_orders", os.path.basename(str(filename)), who, data, hashlib.sha256(data).hexdigest(), _now())
    _kick()
    return {"id": uid, "status": "queued"}


def upload_shipped(who=""):
    """The purchase file that came with the code (inputs/Fabric _ 3Months_4746.xlsx, 1 Aug to 23 Nov 2026), read as
    any upload is: it covers its latest order (23 Nov 2026) up to when SAP saved it (05:48 UTC that day), so it never
    undoes a newer file, nor one covering the same orders saved later."""
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
    with st.tx() as c:
        rows = dp.disagreements(c, int(uid))
        fab_ids = {x["figures"]["fabric_id"] for r in rows for x in (r["kept"], r["file"]) if x.get("figures")}
        mill_ids = {x["figures"]["mill_id"] for r in rows for x in (r["kept"], r["file"]) if x.get("figures")}
        codes = {f["id"]: code for code, f in dp.fabrics(c, ids=sorted(fab_ids)).items()} if fab_ids else {}
        names = {i: m_["name"] for i, m_ in dp.mills(c).items() if i in mill_ids}
        files_ = {u["id"]: u["filename"] for u in dp.uploads(c, limit=1000)}
    words = lambda x: (dict({"code": codes.get(x["figures"]["fabric_id"]), "date": x["figures"]["doc_date"], "type": x["figures"]["doc_type"],
                             "mill": names.get(x["figures"]["mill_id"]), "metres": x["figures"]["qty_m"], "price": x["figures"]["price"]}
                            if x.get("figures") else {}, removed=x.get("removed"), upload=x.get("upload_id"), file=files_.get(x.get("upload_id"))))
    up["disagreements"] = [{"id": r["id"], "po": r["po_number"], "item": r["item"], "kept": words(r["kept"]), "file": words(r["file"]),
                            "settled_at": r["settled_at"], "settled_by": r["settled_by"], "settled_as": r["settled_as"]} for r in rows[:300]]
    up["disagree_count"] = len(rows)
    up["disagree_open"] = sum(1 for r in rows if r["settled_at"] is None)
    return up


def settle(payload, who=""):
    """A person settles what an upload and the history disagree on (which is newer could not be told, from what the two
    cover nor from when they were saved): "file" takes this file's figures, or its word that a line is no longer bought,
    for every line the history still holds as it did then (the line then carries this file's state, its saved date
    included); "kept" keeps the history's. Recorded with who and when. An admin action (do:upload_purchases,
    rules/access.py)."""
    st = need_db()
    payload = payload or {}
    try:
        uid = int(payload.get("upload_id"))
    except (TypeError, ValueError):
        raise common.Refused(400, "Say which upload's disagreements to settle (upload_id).")
    take = payload.get("take")
    if take not in ("file", "kept"):
        raise common.Refused(400, 'Say what to do with them: "file" takes this file\'s figures, "kept" keeps the history\'s.')
    touched, changed_since = set(), 0
    with st.tx(write=KIND) as c:
        up = dp.upload(c, uid)
        if up is None:
            raise common.Refused(404, "No such upload.")
        if up["status"] != "done":
            raise common.Refused(409, "The file is still being read: settle its disagreements once it is read.")
        rows = [r for r in dp.disagreements(c, uid) if r["settled_at"] is None]
        if not rows:
            raise common.Refused(400, f"Upload {uid} has nothing left to settle.")
        if take == "file":
            state = (uid, up["covers_from"], up["covers_to"])
            have = dp.lines_by_key(c, [(r["po_number"], r["item"]) for r in rows])
            change, gone = [], []
            for r in rows:
                old = have.get((r["po_number"], r["item"]))
                if old is None or old["state_upload_id"] != r["kept"]["upload_id"]:
                    changed_since += 1          # a newer file (or a person) has decided the line since: it is left as it is
                    continue
                f = r["file"]
                if f.get("figures"):
                    change.append(dict(f["figures"], id=old["id"], upload_id=uid, state_upload_id=state[0], state_from=state[1], state_to=state[2]))
                    touched |= {f["figures"]["fabric_id"], old["fabric_id"]}
                elif old["removed_upload_id"] is None:
                    gone.append((f["removed"], old["id"]))
                    touched.add(old["fabric_id"])
            dp.change_lines(c, change)
            dp.remove_lines(c, gone, state)
        dp.settle_disagreements(c, [r["id"] for r in rows], _now(), who or "", take)
    recost(st, touched - {None})
    return {"upload_id": uid, "settled": len(rows), "took": "this file's figures" if take == "file" else "the history's figures",
            "left_as_they_are": changed_since}


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
        moves = dp.regroups_of(c, fab["id"])
    grp = fab_groups.history(got) if got is not None else None
    should, why, on = fab_groups.shoulds({code: fab}, own)[code]          # on its order month's yarn rates, as in Right cost
    s = fab_groups.short_spec(fab["spec"]) if fab["spec"] else {}
    out = {"code": code, "description": fab["description"], "lines": lines, "outliers": outliers, "should": should, "should_why": why, "should_on": on,
           "metres": round(sum(x["metres"] for x in lines), 2), "orders": len({x["po"] for x in lines}),
           "spec": {k: s.get(k, "") for k in ("blend_name", "dyemethod_name", "weavetype_name", "warpcount", "weftcount", "epi", "ppi",
                                              "finishedwidth", "finishedwidth_uom", "finish_name", "pattern_name")} if s else None,
           "not_grouped": None if gid is not None else (fab["not_grouped"] or "Not grouped"), "group": None,
           "moved": [{"from": groups[m["from_group_id"]]["code"] if m["from_group_id"] else None,
                      "to": groups[m["to_group_id"]]["code"] if m["to_group_id"] else None, "why": m["why"], "at": m["at"]} for m in moves]}
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


def _held_fabrics(codes):
    """{code: (choices, problems, spec, metres)} of the codes the purchase history holds (its choices are what the price
    popup costs), kept until the history changes."""
    st = store.get()
    if st.kind == "files":
        return {}
    key = st.version(KIND)
    if _held_memo["key"] != key:
        with st.tx() as c:
            fabs = dp.fabrics(c, codes=sorted(codes))
            met = dp.metres(c, [f["id"] for f in fabs.values()])
        val = {code: (f["choices"], f["problems"], f["spec"], float(met.get(f["id"]) or 0)) for code, f in fabs.items()}
        _held_memo.update(key=key, val=val, digest=hashlib.sha256(json.dumps(val, sort_keys=True, default=str).encode()).hexdigest())
    return _held_memo["val"]


_held_memo = {"key": None, "val": None}


def _costed_on(sel):
    """The choices a costing rests on (not the code, its description, the supplier or the price)."""
    return None if sel is None else {k: v for k, v in sel.items() if k not in ("Fabric code", "Description", "Supplier", "Quoted price (Rs/m)", "Order quantity (m)",
                                                                         "Rate card quantity", "Order size")}
# the columns of a purchase-order row that follow its costing choices (when its specification changed since the pilot)
FROM_CHOICES = {"Route": "Route", "Weave": "Weave", "Finish": "Finish", "Warp yarn": "Warp yarn", "Weft yarn": "Weft yarn", "EPI": "EPI",
                "PPI": "PPI", "Finished width (in)": "Finished width (in)", "PLM pattern": "Pattern", "Print method": "Print method",
                "Weft (yarn dyed)": "Weft (yarn dyed)"}


def pilot_rows():
    """(key, rows): the pilot's purchase-order fabrics with their price paid, metres, quantity band, should-cost and gap
    worked out again from the lines bought, ZLOI left out, and costed on the choices the price popup costs: the purchase
    history's (worked out from each code's PLM specification by pilot.py's own functions), else the same worked out from
    the PLM list here. Each row keeps the pilot's columns, plus "Costing choices", "Outliers (ZLOI)" and "Worked out
    again" (why, or None when the pilot's own figures stand: the same lines and the same choices). Kept until the lines,
    the rates, the history or the PLM list change."""
    digest, by_code, _ = bought_lines()
    st = store.get()
    codes = {str(r["Fabric code"]) for r in pilot_records()}
    held = _held_fabrics(codes)
    key = (digest, st.version("rates"), common._mtime(common.PILOT), _held_memo.get("digest") if held else None, common._mtime(pilot.PLM_SPECS))
    if _rows_memo["key"] == key:
        return _rows_memo["val"]
    m = common.get_masters()
    patterns, contents = masters.lists(m)["Pattern"], list(yarn_seed.CONTENTS)
    ctx, specs = pilot.inputs_context(m), plm_specs()
    group_of = m["Weaves"].set_index("Weave")["Weave group"]
    out = []
    for r in pilot_records():
        code = str(r["Fabric code"])
        ls = by_code.get(code, [])
        regular = [x for x in ls if x[3] not in OUTLIER_TYPES]
        zl = [_outlier(code, po, item, day, sup, qty, price) for po, item, day, typ, sup, qty, price in ls if typ in OUTLIER_TYPES]
        metres = sum(x[5] for x in regular)
        value = sum(x[5] * x[6] for x in regular)
        price = round(value / metres, 2) if metres else None
        h = held.get(code)
        if h is not None and abs(h[3] - metres) < 1e-6:
            sel, problems = h[0], h[1]
        else:
            sel, problems = costing_choices(code, h[2] if h is not None else specs.get(code), metres, m, ctx, patterns)
        quoted = lambda s: None if s is None else dict(s, **({"Quoted price (Rs/m)": price} if price is not None else {}))
        pilots = rightcost._pilot_choices(dict(r, **{"PO price Rs/m": None}), patterns, contents)
        same = (not zl and len(regular) == r["PO lines"] and abs(metres - float(r["PO metres"] or 0)) < 1e-6
                and price is not None and r["PO price Rs/m"] is not None and abs(price - round(float(r["PO price Rs/m"]), 2)) < 0.005
                and _costed_on(sel) == _costed_on(pilots))
        if same:
            out.append(dict(r, **{"Costing choices": quoted(sel), "Outliers (ZLOI)": [], "Worked out again": None}))
            continue
        nr = dict(r)
        band, slab = quantity_terms(r["Route"], metres, m)
        top = {}
        for x in regular:
            top[x[4]] = top.get(x[4], 0) + x[5]
        why = [("ZLOI lines left out" if zl else "purchases since the pilot")] if (zl or len(regular) != r["PO lines"] or abs(metres - float(r["PO metres"] or 0)) >= 1e-6
                                                                                  or price is None or abs(price - round(float(r["PO price Rs/m"] or 0), 2)) >= 0.005) else []
        if _costed_on(sel) != _costed_on(pilots):
            why.append("its PLM specification changed since the pilot" if sel else "not costed now: " + "; ".join(problems or ["no costing choices"]))
        nr.update({"PO metres": metres or None, "PO price Rs/m": price, "PO lines": len(regular), "Rate card quantity": band, "Order size": slab,
                   "Supplier": max(top, key=lambda s: (top[s], s)) if top else r["Supplier"], "Outliers (ZLOI)": zl, "Costing choices": quoted(sel),
                   "Worked out again": "; ".join(why) + ("; no other purchase, so no price paid" if not regular else "")})
        if sel is None:                         # nothing to cost: the row says why, with no should-cost
            nr.update({"Should-cost Rs/m": None, "Should-cost Rs/kg": None, "PO minus should-cost Rs/m": None, "PO above should-cost %": None, "Excess Rs": None})
            out.append(nr)
            continue
        if _costed_on(sel) != _costed_on(pilots):       # the row's construction follows its choices
            nr.update({col: sel.get(k) for col, k in FROM_CHOICES.items()})
            nr["Weave group"] = group_of.get(sel.get("Weave"), r["Weave group"])
            nr.update({"Rate card quantity": sel.get("Rate card quantity"), "Order size": sel.get("Order size")})
        try:
            res = masters.cost(quoted(sel), m)
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
