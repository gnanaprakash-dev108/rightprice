"""Mill cost sheets: a mill's own figures for its fabrics, set beside the rate master, and the drafts that follow.
Nothing changes a rate until GP ticks a draft and applies it."""
import datetime as dt
import io
import pandas as pd
from rules import common, rightcost
import costsheet
import masters
import store


def _sheets():
    return store.get().read_sheets()


def _save_sheets(rows):
    store.get().write_sheets(rows)


def costsheet_template():
    rows, about, lists = costsheet.template()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        rows.to_excel(xw, sheet_name="Cost sheet", index=False)
        about.to_excel(xw, sheet_name="Columns", index=False)
        lists.to_excel(xw, sheet_name="Lists", index=False)
    return common.Download(buf.getvalue(), "RightPrice mill cost sheet.xlsx")


def costsheet_view():
    """Every mill cost sheet row brought in, each set beside the rate master, and the drafts that follow."""
    rows = _sheets()
    a = costsheet.analyse(rows, common.get_masters()) if rows else {"rows": [], "drafts": []}
    for item, r in zip(a["rows"], rows):
        item["id"], item["added"], item["upload"] = r.get("_id"), r.get("_added"), r.get("_upload")
        item["by"] = r.get("_by") or ""         # who brought it in: the signed-in person, or "AI assistant"
    return a          # numbers read from the rate master are numpy types: the web layer writes them as plain ones


@common.one_at_a_time
def costsheet_upload(filename, data, who=""):
    try:
        book = pd.read_excel(io.BytesIO(data), sheet_name=None)
    except Exception:
        raise common.Refused(400, "This file is not an Excel workbook (.xlsx). Save the mill's sheet as Excel and upload it again")
    sheet = next((df for df in book.values() if costsheet.is_cost_sheet(df)), None)
    if sheet is None:
        raise common.Refused(400, "No sheet in this file has the cost sheet headings (Mill, Route, Weave, EPI, PPI, Overhead %, Margin %). "
                                 "Download the template and fill it in")
    new = [r for r in costsheet.read(sheet) if str(r.get("Mill") or "").strip() != "Example mill"]   # the template's example is not a mill
    if not new:
        raise common.Refused(400, "The sheet has the right headings but no rows (the template's example row is not counted)")
    now = dt.datetime.now()
    upload = f"{filename or 'sheet'}, {now:%d %b %H:%M}"
    key = lambda r: (str(r.get("Mill") or "").strip().lower(), str(r.get("Fabric code") or "").strip().lower())
    fresh = {key(r) for r in new if str(r.get("Fabric code") or "").strip()}
    rows = _sheets()
    keep = [r for r in rows if key(r) not in fresh]      # a mill's sheet sent again takes the place of its earlier rows
    for n, r in enumerate(new):
        r["_id"], r["_added"], r["_upload"] = f"{now:%Y%m%d%H%M%S%f}{n:04d}", now.date().isoformat(), upload
        r["_by"] = who or ""
    _save_sheets(keep + new)
    a = costsheet.analyse(new, common.get_masters())
    return {"added": len(new), "replaced": len(rows) - len(keep), "not_read": sum(1 for x in a["rows"] if x["problems"])}


@common.one_at_a_time
def costsheet_remove(payload: dict):
    ids, upload = {str(i) for i in payload.get("ids") or []}, payload.get("upload")
    rows = _sheets()
    keep = [r for r in rows if str(r.get("_id")) not in ids and not (upload and r.get("_upload") == upload)]
    _save_sheets(keep)
    return {"removed": len(rows) - len(keep)}


@common.one_at_a_time
def costsheet_apply(payload: dict, who: str = ""):
    """Write the drafts GP ticked into the rate master, after a dated copy of it. Nothing else changes."""
    chosen = {str(i) for i in payload.get("ids") or []}
    if not chosen:
        raise common.Refused(400, "Tick the drafts to apply")
    rows = _sheets()
    m = common.get_masters()
    drafts = costsheet.analyse(rows, m)["drafts"]
    picked = [d for d in drafts if d["id"] in chosen]
    if not picked:
        raise common.Refused(400, "Those drafts are no longer there; reload the page")
    # the figures the person was shown (expect: {draft id: {now, proposed}}): a draft that moved since (more sheets came
    # in, or a rate was changed) is not applied on the strength of figures nobody saw
    expect = payload.get("expect") if isinstance(payload.get("expect"), dict) else {}
    show = lambda d, v: f"{float(v) * 100:.1f}%" if d["pct"] else f"Rs {float(v):g}"
    moved = []
    for d in picked:
        e = expect.get(d["id"])
        if e is None:
            continue
        try:
            same = abs(float(e["now"]) - d["now"]) <= 1e-6 and abs(float(e["proposed"]) - d["proposed"]) <= 1e-6
        except (KeyError, TypeError, ValueError):
            same = False
        if not same:
            moved.append(f"{d['label']} is now {show(d, d['now'])} to {show(d, d['proposed'])}" + (
                f", not {show(d, e['now'])} to {show(d, e['proposed'])}" if isinstance(e, dict) and "now" in e and "proposed" in e else ""))
    if moved:
        raise common.Refused(409, "A draft has changed since it was shown (more sheets came in, or a rate was changed): " + "; ".join(moved)
                                  + ". Look at the drafts again; nothing was applied.")
    m2 = {k: v.copy() for k, v in m.items()}
    try:
        log = costsheet.apply(m2, picked, chosen)
        masters.cost(dict(masters.EXAMPLE_ROW), m2)        # the rate master must still cost a fabric
    except Exception as e:
        raise common.Refused(400, f"Not applied, nothing changed: {e}")
    # the copy is taken only once the change is known to be good, and to the second, so none is overwritten
    store.get().keep_copy(f" backup {dt.date.today():%Y%m%d}", if_absent=True)       # the day's copy, as every rate save keeps
    kept = masters.save(m2, reason="Mill cost sheet drafts applied: " + "; ".join(map(str, log))[:500], who=who,
                        backup=f" before mill cost sheet {dt.datetime.now():%Y%m%d-%H%M%S}")
    common._cache.pop("#rates", None)
    rightcost._briefs.update(key=None)
    return {"applied": log, "backup": kept}
