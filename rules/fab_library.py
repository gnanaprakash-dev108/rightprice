"""The Fab library (GP's decision, 28 Nov 2026): the PLM fabric code list (about 5 lakh codes), uploaded by an admin and
read in the background, as purchase files are (a job with its progress, read again from the start after a restart),
kept in the database with every upload (who, when, its file and its counts). Every code can be found on the Fab
library page with its construction, its Fab group and its purchases.

The purchase history takes each fabric code's PLM specification from it (rules/purchases.py plm_specs), in place of
data/plm_specs_for_po.csv deployed with the code: once the library holds an upload read in full, it is the source; before
any, the deployed file, as before (so nothing changes until an admin uploads the list). A code's specification is the
one of the latest upload that holds it (uploads go in order of their number, so an older upload read again after a
restart never undoes a later one); a code missing from a later upload keeps the specification it had. Codes with a
blank EPI, PPI, width or count are stored as they are, blanks kept.

When an upload is read, every fabric code of the purchase history is grouped again on the library's specifications and
those whose specification changed are costed again at once, by the same path a purchase upload takes (stage 2:
fab_groups.regroup, then purchases.recost of the fabrics whose costing choices are stale): a corrected EPI moves a code to
its Fab group, and a code that had no specification gets one, is grouped and costed, without another purchase upload.

Accepted: a .csv (as plm_extract.py writes it: the 26 columns of COLUMNS), a .zip holding one such .csv, or an .xlsx with
those columns. Each is read as pilot.py reads data/plm_specs_for_po.csv (every value as text, the cells pandas reads as
empty left blank), so a code of the deployed file has exactly the same specification here. A file larger than MAX_BYTES
(the list itself: the .csv inside a .zip unzipped) is refused at once, with the limit named."""
import contextlib
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import socket
import threading
import time
import zipfile

import warnings

from rules import common, fab_groups
import data_fab_library as dl
import store

with warnings.catch_warnings():         # pilot.py turns warnings off for its own run; not for the app
    import pilot

KIND, STATUS = dl.KIND, dl.STATUS
# the columns of the PLM fabric list kept (plm_extract.py KEEP; check_server.py checks the two are the same)
COLUMNS = ["article_code", "article_lifecyclestage_name", "article_productgroup_name",
           "article_productsubcategory_name", "article_division_name", "article_cust_dyemethod_name",
           "article_cust_blend_name", "article_cust_weight", "article_cust_weight_uom",
           "article_cust_weavetype_name", "article_cust_developmentpurchasecost",
           "article_cust_developmentpurchasecost_currency", "article_cust_source_name",
           "article_cust_finishedwidth", "article_cust_finishedwidth_uom", "article_cust_genericname_name",
           "article_supplier_name", "article_cust_patterndetails_name", "article_cust_pattern_name",
           "article_cust_finish_name", "article_cust_rfdindigo_name", "article_cust_epi", "article_cust_ppi",
           "article_cust_yarndetails_name", "article_cust_warpcount", "article_cust_weftcount"]
CODE_COL = "article_code"
WORDS = {"lifecyclestage_name": "Lifecycle stage", "productgroup_name": "Product group", "productsubcategory_name": "Product subcategory",
         "division_name": "Division", "dyemethod_name": "Dye method", "blend_name": "Content", "weight": "Weight", "weight_uom": "Weight unit",
         "weavetype_name": "Weave", "developmentpurchasecost": "Development purchase cost", "developmentpurchasecost_currency": "Its currency",
         "source_name": "Source", "finishedwidth": "Finished width", "finishedwidth_uom": "Width unit", "genericname_name": "Generic name",
         "supplier_name": "Supplier (PLM)", "patterndetails_name": "Pattern details", "pattern_name": "Pattern", "finish_name": "Finish",
         "rfdindigo_name": "RFD / indigo", "epi": "EPI", "ppi": "PPI", "yarndetails_name": "Yarn details", "warpcount": "Warp count",
         "weftcount": "Weft count", "code": "Code"}
MAX_BYTES = 200 * 1024 * 1024       # the list itself (the real one, 418,877 codes, is 80 MB as a .csv; 3.7 MB zipped)
CHUNK = 2000                        # codes written per transaction, so pages are never held up for long
BEAT, STALE = 15, 90                # seconds between a job's signs of life; without one this long, a restart stopped it
GIVE_WAY = 0.02                     # seconds the job leaves the store free after each of its transactions
NA = {"", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None",
      "n/a", "nan", "null"}         # what pandas reads as empty (and pilot.py's fillna("") then blank): blank here too
NEEDS_DB = ("The Fab library is kept in the database, and this server keeps its data in files (the app setting DATABASE_URL is not "
            "set). Until it is, the PLM specifications come from the file deployed with the code (data/plm_specs_for_po.csv).")
RUNNER = f"{socket.gethostname()}:{os.getpid()}"


def _now():
    return store._now()


def need_db():
    st = store.get()
    if st.kind == "files":
        raise common.Refused(503, NEEDS_DB)
    return st


def short(k):
    return k.replace("article_", "").replace("cust_", "")


def label(k):
    return WORDS.get(short(k), short(k))


# ------------------------------------------------------------------ where the specifications come from
_src = {"v": None, "val": None}


def source():
    """The number of the latest library upload read in full, or None (the files store, or no upload yet): with one, the
    library is the source of every PLM specification."""
    st = store.get()
    if st.kind == "files":
        return None
    try:
        v = st.version(KIND)
    except store.StoreUnavailable:
        return _src["val"]
    if _src["v"] != v:
        with st.tx() as c:
            _src.update(v=v, val=dl.latest_done(c))
    return _src["val"]


def specs_for(codes):
    """{code: its 26 values as text} for these codes from the library, or None while the library is not the source."""
    if source() is None:
        return None
    with store.get().tx() as c:
        rows = dl.specs(c, codes)
    return {code: dict(zip(COLUMNS, vals)) for code, vals in rows.items()}


# ------------------------------------------------------------------ reading a list
def kind_of(filename):
    n = str(filename or "").lower()
    for ext, k in ((".csv", "csv"), (".zip", "zip"), (".xlsx", "xlsx"), (".xlsm", "xlsx")):
        if n.endswith(ext):
            return k
    raise common.Refused(400, "Upload the PLM fabric code list as a .csv (as plm_extract.py writes it), a .zip holding that one .csv, "
                              "or an .xlsx with the same columns.")


def too_big(size, name):
    """What a file over the limit is told, on the screen at once (web/library.js tooBig says the same before sending it)."""
    return (f"{name} is {size / 1048576:.1f} MB: larger than {MAX_BYTES // 1048576} MB, the most read at once. "
            "Send it as a .zip (the full list is about 4 MB zipped), or split it into parts.")


def _missing(header):
    have = {str(h or "").strip() for h in header}
    return [c for c in COLUMNS if c not in have]


def _refuse_columns(name, missing):
    raise common.Refused(400, f"{name} is not the PLM fabric code list in the shape RightPrice reads: the column{'s' if len(missing) > 1 else ''} "
                              f"{', '.join(missing[:6])}{' and ' + str(len(missing) - 6) + ' more' if len(missing) > 6 else ''} "
                              f"{'are' if len(missing) > 1 else 'is'} missing. It needs the 26 columns plm_extract.py keeps, from "
                              f"{COLUMNS[0]} to {COLUMNS[-1]}.")


def _zip_member(z, name):
    members = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/") and not os.path.basename(i.filename).startswith(".")]
    if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
        raise common.Refused(400, f"{name} should hold one .csv, the PLM fabric code list; it holds "
                                  + (", ".join(i.filename for i in members[:5]) if members else "nothing") + ".")
    return members[0]


def _cell(v):
    """An .xlsx cell as the text plm_extract.py writes for it (a number as Python writes it: 200.0, 268)."""
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ")
    return str(v)


def chunks(fmt, data, size=20000):
    """The rows of a list as dicts over COLUMNS, every value text, the cells pandas reads as empty left blank (as pilot.py
    reads data/plm_specs_for_po.csv), in lists of `size`. Yields (rows, columns ignored) once per list."""
    import pandas as pd
    if fmt in ("csv.gz", "zip"):
        with contextlib.ExitStack() as stack:
            if fmt == "csv.gz":
                f = stack.enter_context(gzip.GzipFile(fileobj=io.BytesIO(data)))
            else:
                z = stack.enter_context(zipfile.ZipFile(io.BytesIO(data)))
                f = stack.enter_context(z.open(_zip_member(z, "The file")))
            for part in pd.read_csv(f, dtype=str, chunksize=size, encoding="utf-8-sig"):
                part.columns = [str(c).strip() for c in part.columns]
                extra = [c for c in part.columns if c not in COLUMNS]
                yield part[COLUMNS].fillna("").to_dict("records"), extra
        return
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = [str(h or "").strip() for h in (next(rows, None) or ())]
        pos = {}
        for i, h_ in enumerate(header):
            pos.setdefault(h_, i)
        extra = [h_ for h_ in header if h_ and h_ not in COLUMNS]
        out = []
        for values in rows:
            if values is None or all(v is None for v in values):
                continue
            r = {}
            for k in COLUMNS:
                t = _cell(values[pos[k]]) if pos[k] < len(values) else ""
                r[k] = "" if t in NA else t
            out.append(r)
            if len(out) >= size:
                yield out, extra
                out = []
        if out:
            yield out, extra
    finally:
        wb.close()


def _prepare(code, spec):
    """What is stored of one code: (code, its values as JSON, spec_sha, search text, its group's eight fields, its width,
    why it cannot be grouped) and what is blank in it."""
    s = fab_groups.short_spec(spec)
    fields, sig, why = fab_groups.signature_of(spec)
    try:
        _, _, width = pilot.plm_numbers(s)
    except (KeyError, AttributeError):
        width = 0
    width = round(width, 2) if 30 <= width <= 130 else None
    tidy = [fab_groups.tidy_content(s.get("blend_name")), fab_groups.tidy_route(s.get("dyemethod_name")), fab_groups.tidy_count(s.get("warpcount")),
            fab_groups.tidy_count(s.get("weftcount")), fab_groups.tidy_finish(s.get("finish_name"))]
    words = [code] + [s.get(k, "") for k in ("blend_name", "dyemethod_name", "weavetype_name", "warpcount", "weftcount", "finish_name", "pattern_name",
                                            "genericname_name", "productsubcategory_name", "productgroup_name", "division_name", "lifecyclestage_name",
                                            "supplier_name", "yarndetails_name")]
    words += [t for t in tidy if t] + [f"{s.get('epi', '').strip()} x {s.get('ppi', '').strip()}", f"{s.get('finishedwidth', '')} {s.get('finishedwidth_uom', '')}"]
    if width:
        words.append(f"{width:g} in")
    search = re.sub(r"\s+", " ", " ".join(w for w in words if w)).lower()
    blank = lambda k: not str(s.get(k, "")).strip()
    gaps = {"no_epi_ppi": blank("epi") or blank("ppi"), "no_width": blank("finishedwidth"), "no_counts": blank("warpcount") or blank("weftcount")}
    return (code, json.dumps([spec[k] for k in COLUMNS]), fab_groups.spec_sha(spec), search, fab_groups._rest(sig) if sig else None, width, why), gaps


def _what(old, new):
    """What a later upload changed in a code's specification, in words: 'EPI 132 to 142; Finish F - Normal to F - Peach'."""
    show = lambda v: v if str(v).strip() else "blank"
    out = [f"{label(k)} {show(old.get(k, ''))} to {show(new.get(k, ''))}" for k in COLUMNS if str(old.get(k, "")) != str(new.get(k, ""))]
    return "; ".join(out) or "written another way"


def _check(name, fmt, data):
    """Refused at once (before anything is kept) when it is not the list: the columns, and for a .zip, the one .csv in it
    and its size unzipped. Returns the size of the list itself."""
    if fmt == "zip":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise common.Refused(400, f"{name} could not be read as a .zip.")
        m = _zip_member(z, name)
        if m.file_size > MAX_BYTES:
            raise common.Refused(413, too_big(m.file_size, f"The list inside {name} ({m.filename})"))
        with z.open(m) as f:
            first = io.TextIOWrapper(f, encoding="utf-8-sig", newline="").readline()
        _cols(name, first)
        return m.file_size
    if fmt == "xlsx":
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise common.Refused(400, f"{name} could not be read as an Excel workbook ({type(e).__name__}).")
        try:
            header = next(wb.worksheets[0].iter_rows(values_only=True, max_row=1), None) or ()
        finally:
            wb.close()
        missing = _missing(header)
        if missing:
            _refuse_columns(name, missing)
        return len(data)
    return None


def _cols(name, first_line):
    header = next(csv.reader([first_line]), [])
    missing = _missing(header)
    if missing:
        _refuse_columns(name, missing)


def upload(filename, data, who=""):
    """The PLM fabric code list uploaded: kept as it came (a .csv kept compressed), checked at once (its columns; its size,
    a .zip's list unzipped included) and read in the background. Answers at once with its number. `data`: the bytes, or a
    binary file to read them from (a .csv is compressed as it is read, so a large one is never held whole)."""
    st = need_db()
    name = os.path.basename(str(filename or "")) or "The file"
    fmt = kind_of(filename)
    src = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
    try:                                    # its size, when it can be told before reading: refused at once
        whole = src.seek(0, 2)
        src.seek(0)
    except (AttributeError, OSError, ValueError):
        whole = None
    if whole is not None and whole > MAX_BYTES and fmt != "zip":
        raise common.Refused(413, too_big(whole, name))
    sha, size = hashlib.sha256(), 0
    if fmt == "csv":
        out = io.BytesIO()
        first = b""
        with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=6, mtime=0) as gz:
            while True:
                part = src.read(1 << 20)
                if not part:
                    break
                size += len(part)
                if size > MAX_BYTES:
                    raise common.Refused(413, too_big(size, name).replace(" is ", " is more than ", 1))
                if len(first) < 65536:
                    first += part[:65536]
                sha.update(part)
                gz.write(part)
        if not size:
            raise common.Refused(400, "The file is empty.")
        _cols(name, first.decode("utf-8-sig", "replace").splitlines()[0] if first else "")
        stored, content, fmt_ = out.getvalue(), size, "csv.gz"
    else:
        raw = src.read(MAX_BYTES + 1)
        if not raw:
            raise common.Refused(400, "The file is empty.")
        if len(raw) > MAX_BYTES:
            raise common.Refused(413, too_big(len(raw), name))
        size = len(raw)
        sha.update(raw)
        content = _check(name, fmt, raw)
        stored, fmt_ = raw, fmt
    with st.tx(write=KIND) as c:
        uid = dl.add_upload(c, name, who, fmt_, stored, size, content, sha.hexdigest(), _now())
    _kick()
    return {"id": uid, "status": "queued", "bytes": size, "list_bytes": content}


# ------------------------------------------------------------------ the background job
_jobs = {"thread": None}
_jobs_lock = threading.Lock()
_running = set()


def _kick():
    with _jobs_lock:
        t = _jobs["thread"]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_worker, daemon=True, name="rightprice-fab-library")
            _jobs["thread"] = t
            t.start()


def _queued(st):
    try:
        with st.tx() as c:
            return [i for i, status, _, _ in dl.waiting(c) if status == "queued"]
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


@contextlib.contextmanager
def _job_tx(st, write=None):
    try:
        with st.tx(write=write) as c:
            yield c
    finally:
        time.sleep(GIVE_WAY)


def _status(uid, **fields):
    with _job_tx(store.get(), STATUS) as c:
        dl.set_upload(c, uid, **fields)


class _Beat(threading.Thread):
    def __init__(self, uid):
        super().__init__(daemon=True, name=f"rightprice-library-{uid}-alive")
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
    _running.add(uid)
    try:
        with st.tx(write=STATUS) as c:
            claimed = c.run("UPDATE fab_library_upload SET status = 'working', step = %s, started_at = %s, alive_at = %s, runner = %s "
                            "WHERE id = %s AND status = 'queued'", ("Reading the list", _now(), _now(), RUNNER, uid)).rowcount
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
    t0 = time.monotonic()
    with _job_tx(st) as c:
        data, up = dl.upload_file(c, uid), dl.upload(c, uid)
        done_before = dl.changed_in(c, uid)          # a re-read after a restart records no change twice
    codes, n = set(), {"rows": 0, "repeated": 0, "no_code": 0, "older": 0, "no_epi_ppi": 0, "no_width": 0, "no_counts": 0}
    extra, last_beat, at = [], 0.0, _now()
    pending = []

    def write(batch):
        prepared = [_prepare(code, spec) for code, spec in batch]
        for _, gaps in prepared:
            for k, v in gaps.items():
                n[k] += bool(v)
        with _job_tx(st, KIND) as c:
            have = dl.held(c, [p[0][0] for p in prepared])
            add, change, notes = [], [], []
            for (row, _), (code, spec) in zip(prepared, batch):
                old = have.get(code)
                if old is None:
                    add.append(row + (uid, at))
                elif old[1] > uid or old[3] > uid:
                    n["older"] += 1                     # a later upload has it: this one's word is not used
                elif old[0] != row[2] and old[1] < uid:
                    change.append(row + (uid, at))
                    if code not in done_before:
                        notes.append((code, uid, old[2], _what(dict(zip(COLUMNS, json.loads(old[2]))), spec), at))
            dl.add_codes(c, add)
            dl.change_codes(c, change)
            dl.add_changes(c, notes)
            dl.seen(c, [p[0][0] for p in prepared], uid)
    for rows, ex in chunks(up["file_format"], data):
        extra = ex
        for r in rows:
            n["rows"] += 1
            code = str(r[CODE_COL]).strip()
            if not code:
                n["no_code"] += 1
                continue
            if code in codes:
                n["repeated"] += 1
                continue
            codes.add(code)
            pending.append((code, r))
            if len(pending) >= CHUNK:
                write(pending)
                pending = []
                if time.monotonic() - last_beat > 2:
                    last_beat = time.monotonic()
                    _status(uid, step=f"Writing the codes ({len(codes):,} so far)", rows_total=n["rows"], codes_total=len(codes), alive_at=_now())
    if pending:
        write(pending)
    data = None
    read_s = time.monotonic() - t0
    with _job_tx(st) as c:
        k = dl.counts_of(c, uid)
    same = len(codes) - k["codes_new"] - k["codes_changed"] - n["older"]
    _status(uid, step="Grouping and costing the purchase history again on the library's specifications", rows_total=n["rows"], codes_total=len(codes),
            codes_new=k["codes_new"], codes_changed=k["codes_changed"], codes_same=max(0, same), codes_older=n["older"], codes_kept=k["codes_kept"],
            rows_repeated=n["repeated"], rows_no_code=n["no_code"], no_epi_ppi=n["no_epi_ppi"], no_width=n["no_width"], no_counts=n["no_counts"])
    with _job_tx(st, KIND) as c:            # it is the source from here on: done, and the version moves
        dl.set_upload(c, uid, status="done", step="Grouping and costing the purchase history again on the library's specifications", alive_at=_now())
    t1 = time.monotonic()
    rg = regroup_history()
    summary = {"columns_ignored": extra, "regroup": rg, "seconds": {"read_and_write": round(read_s, 1), "regroup_and_cost": round(time.monotonic() - t1, 1)},
               "codes_in_library": k["codes"]}
    _status(uid, step="", finished_at=_now(), alive_at=_now(), summary=summary)


def regroup_history(wait_for_purchases=600):
    """Every fabric code of the purchase history grouped again on the specifications the purchase history takes now (the
    library's), and those whose costing choices are stale costed again: stage 2's own path (fab_groups.regroup, then
    purchases.stale and recost), as a purchase upload does it. A purchase file being read is waited for first (up to
    `wait_for_purchases` seconds), so the two never group on different specifications."""
    from rules import purchases
    import data_purchases as dp
    st = store.get()
    end = time.monotonic() + wait_for_purchases
    while time.monotonic() < end:
        with st.tx() as c:
            if not dl.purchase_working(c):
                break
        time.sleep(2)
    with st.tx() as c:
        codes = dl.purchase_codes(c)
        first = dl.first_bought(c)
    if not codes:
        return {"fabrics": 0}
    specs = purchases.plm_specs(codes)
    ready = fab_groups.signatures(specs, codes)
    t = time.monotonic()
    with _job_tx(st, dp.KIND) as c:
        before = {code: (f["fab_group_id"], f["not_grouped"]) for code, f in dp.fabric_index(c).items()}
        rg = fab_groups.regroup(c, specs, first, set(), _now(), None, ready)
        after = dp.fabric_index(c)
    grouped_now = sum(1 for code, f in after.items() if f["fab_group_id"] is not None and before.get(code, (None,))[0] is None)
    ungrouped_now = sum(1 for code, f in after.items() if f["fab_group_id"] is None and before.get(code, (None,))[0] is not None)
    regroup_s = time.monotonic() - t
    ids = purchases.stale(st)
    purchases.recost(st, ids)
    return {"fabrics": len(codes), "with_spec": sum(1 for code in codes if code in specs), "moved": sum(1 for m in rg["moves"] if m[1] != m[2]),
            "grouped_now": grouped_now, "not_grouped_now": ungrouped_now, "respecified": len(rg["respecified"]), "renamed": len(rg["renamed"]),
            "groups_new": rg["groups_new"], "costed_again": len(ids), "regroup_seconds": round(regroup_s, 1)}


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def resume():
    """Uploads left half-read by a restart are read again from the start (safe: later uploads win whatever the order),
    and uploads waiting are picked up. Run at start, and whenever the page is opened."""
    st = store.get()
    if st.kind == "files":
        return
    try:
        with st.tx() as c:
            waiting = dl.waiting(c)
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
                c.run("UPDATE fab_library_upload SET status = 'queued', runner = NULL, step = %s WHERE id = %s AND status = 'working'",
                      ("The server restarted while it was being read: it is read again from the start", i))
    if again or any(status == "queued" for _, status, _, _ in waiting):
        _kick()


def _resume_quietly():
    try:
        resume()
    except Exception:
        pass


def _regroup_if_left():
    """At start: when the latest upload read in full was stopped by a restart before the purchase history was grouped and
    costed again on it, that is done now."""
    try:
        st = store.get()
        if st.kind == "files":
            return
        with st.tx() as c:
            latest = dl.latest_done(c)
            up = dl.upload(c, latest) if latest else None
        if up and not (up["summary"] or {}).get("regroup"):
            rg = regroup_history()
            _status(latest, step="", finished_at=up["finished_at"] or _now(), summary=dict(up["summary"] or {}, regroup=rg,
                                                                                            regroup_note="worked out again after a restart"))
    except Exception:
        pass


def resume_at_start():
    _resume_quietly()
    threading.Thread(target=_regroup_if_left, daemon=True, name="rightprice-fab-library-regroup").start()
    later = threading.Timer(STALE + 10, _resume_quietly)
    later.daemon = True
    later.start()


# ------------------------------------------------------------------ the page
def _construction(s):
    """A code's construction in one line, as the PLM writes it."""
    num = lambda v: (f"{float(v):g}" if re.fullmatch(r"\s*\d+(\.\d+)?\s*", str(v or "")) else str(v or "").strip())
    parts = [s.get("blend_name"), s.get("dyemethod_name"), s.get("weavetype_name"),
             f"{s.get('warpcount', '').strip()} x {s.get('weftcount', '').strip()}" if (s.get("warpcount", "").strip() or s.get("weftcount", "").strip()) else "",
             f"{num(s.get('epi'))} x {num(s.get('ppi'))}" if (s.get("epi", "").strip() or s.get("ppi", "").strip()) else "",
             f"{num(s.get('finishedwidth'))} {s.get('finishedwidth_uom', '')}".strip() if s.get("finishedwidth", "").strip() else "",
             re.sub(r"^F\s*-\s*", "", str(s.get("finish_name") or "").strip())]
    return " · ".join(p.strip() for p in parts if p and str(p).strip())


def _groups_index(c):
    """The Fab groups as the library needs them: {id: group}, and {eight fields: [(lowest width, highest width, id)]} of
    the groups counted now (a merged group counts as the one it was merged into)."""
    import data_purchases as dp
    groups = dp.groups(c)
    by_rest = {}
    for gid, g in groups.items():
        if g["merged_into"] is None:
            by_rest.setdefault(fab_groups._rest(g["signature"]), []).append((g["width_in"], g["width_to"] or g["width_in"], gid))
    return groups, by_rest


def _group_of(row, bought, groups, by_rest):
    """A code's Fab group: the one it is in (a code of the purchase history), or the one its construction is (a code never
    bought: the group it would join, widths within half an inch); or why it has none."""
    if bought is not None:
        gid = bought[6]
        if gid is not None:
            g = groups[fab_groups.final(groups, gid)]
            return {"code": g["code"], "name": g["name"], "how": "in"}
        return {"code": None, "why": bought[7] or row["not_grouped"] or "Not grouped", "how": "not grouped"}
    if row["sig_rest"] is None:
        return {"code": None, "why": row["not_grouped"] or "Not grouped", "how": "not grouped"}
    w = row["width_in"]
    hits = [gid for lo, hi, gid in by_rest.get(row["sig_rest"], []) if w is not None and lo - fab_groups.WIDTH_TOLERANCE - 1e-9 <= w <= hi + fab_groups.WIDTH_TOLERANCE + 1e-9]
    if hits:
        g = groups[hits[0]]
        return {"code": g["code"], "name": g["name"], "how": "construction"}
    return {"code": None, "why": "No Fab group has this construction yet: none of its codes has been bought", "how": "none yet"}


def _card(row, bought, groups, by_rest):
    s = fab_groups.short_spec(dict(zip(COLUMNS, row["spec"])))
    b = bought
    return {"code": row["code"], "construction": _construction(s), "product": " · ".join(x for x in (s.get("productgroup_name"), s.get("productsubcategory_name")) if x),
            "group": _group_of(row, b, groups, by_rest), "not_grouped": row["not_grouped"],
            "bought": None if b is None else {"lines": b[0], "metres": round(b[1], 2), "orders": b[2], "last": b[3], "last_price": None if b[4] is None else round(b[4], 2)},
            "upload_id": row["upload_id"]}


def status():
    """What the library holds, its uploads (newest first), where the specifications come from, and the limit."""
    st = store.get()
    if st.kind == "files":
        return {"available": False, "why": NEEDS_DB, "max_bytes": MAX_BYTES, "uploads": [], "codes": 0, "source": "the file deployed with the code"}
    resume()
    with st.tx() as c:
        ups, total, latest = dl.uploads(c), dl.total(c), dl.latest_done(c)
    return {"available": True, "codes": total, "uploads": ups, "latest": latest, "max_bytes": MAX_BYTES,
            "source": f"the Fab library (upload #{latest})" if latest else "the file deployed with the code (data/plm_specs_for_po.csv, 19,669 codes): no list uploaded yet",
            "who_may": "Uploading is an admin action (Admin and Rates editor: do:upload_fab_library, rules/access.py)."}


def search(q, limit=50):
    """Codes of the library matching every word typed (the code, or any part of its construction: 'twill 40s', '136 x 90'),
    each with its construction, its Fab group and its purchases."""
    st = need_db()
    limit = max(1, min(int(limit or 50), 200))
    text = str(q or "").strip()
    words = [w for w in re.split(r"\s+", text.lower()) if w][:8]
    with st.tx() as c:
        rows = dl.search(c, words, limit, typed=text) if words else []
        total = dl.total(c)
        b = dl.bought(c, [r["code"] for r in rows[:limit + 1]])
        groups, by_rest = _groups_index(c)
    more = len(rows) > limit
    return {"q": text, "codes": total, "results": [_card(r, b.get(r["code"]), groups, by_rest) for r in rows[:limit]], "more": more, "limit": limit}


def code_page(code):
    """One code of the library: its 26 values, its construction, its Fab group, its purchases, which upload gave its
    specification, and every change a later upload made to it."""
    st = need_db()
    code = str(code or "").strip()
    with st.tx() as c:
        rows = dl.codes(c, [code]) or dl.codes(c, [code.upper()])
        if not rows:
            n = dl.total(c)
            raise common.Refused(404, f"{code} is not in the Fab library." + ("" if n else " No PLM fabric code list has been uploaded yet."))
        row = next(iter(rows.values()))
        b = dl.bought(c, [row["code"]]).get(row["code"])
        groups, by_rest = _groups_index(c)
        changes = dl.changes_of(c, row["code"])
        ups = {u["id"]: u for u in dl.uploads(c, limit=1000)}
        latest = dl.latest_done(c)
        same = dl.same_construction(c, row["sig_rest"]) if row["sig_rest"] else (0, [])
    out = _card(row, b, groups, by_rest)
    word = lambda uid: None if uid not in ups else {"id": uid, "filename": ups[uid]["filename"], "at": ups[uid]["uploaded_at"], "by": ups[uid]["uploaded_by"]}
    spec = dict(zip(COLUMNS, row["spec"]))
    out.update(values=[{"column": k, "label": label(k), "value": spec[k]} for k in COLUMNS], spec_from=word(row["upload_id"]), first_in=word(row["first_upload_id"]),
               last_in=word(row["seen_upload_id"]), in_latest=row["seen_upload_id"] == latest, latest=latest,
               changes=[{"upload": x["upload_id"], "filename": x["filename"], "by": x["uploaded_by"], "at": x["at"], "what": x["what"]} for x in changes],
               same_construction={"codes": same[0], "first": same[1]})
    return out


def upload_detail(uid):
    st = need_db()
    with st.tx() as c:
        up = dl.upload(c, int(uid))
        if up is None:
            raise common.Refused(404, "No such upload of the Fab library.")
        up["changes"] = dl.changes_in(c, int(uid))
    return up
