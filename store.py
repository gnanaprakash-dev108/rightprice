"""The data layer: where RightPrice keeps what people add and change.

Chosen by the setting DATABASE_URL, once, when the app starts:
- not set:           files in the data folder (RIGHTPRICE_DATA, or the project's data/), exactly as before.
- postgresql://...   a PostgreSQL database (Azure Database for PostgreSQL on the live site).
- sqlite:///<path>   a database file (the agreed fallback, should PostgreSQL cost too much).

The same five things, whichever way:
  what               the file                       the tables (db/001_files_moved_in.sql)
  rate master        Rate_Master.xlsx               rate_version: every saved version, the whole workbook
  fabric list        costing_log.csv                quote (each row's saved costing with its rate version)
  tracker            negotiations.json              negotiation, negotiation_step
  alerts seen        alerts_seen.json               alert_seen
  mill cost sheets   cost_sheets.json               cost_sheet_row

With a database set and empty, the app copies the files in at its first start (one transaction), checks that every
file reads back from the database exactly as it reads from the file, and that every fabric on the list costs the same to
the paisa; anything different and nothing is kept. The files are only read, never changed, so removing DATABASE_URL goes
back to them as they were at the move. If they change after the move (the setting was taken off for a while), the app
will not start on the database, so neither side's changes are lost; `python store.py export <new folder>` writes what the
database holds in the files' own form.

Nothing here decides anything about fabrics or prices: that is rules/. The costing is engine.py and masters.py.

    python store.py status            which store this setting gives, and what it holds
    python store.py export <folder>   the database's contents as files, in a new empty folder
"""
import contextlib
import datetime as dt
import glob
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import threading

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED_MASTER = os.path.join(HERE, "data", "Rate_Master.xlsx")
DB_DIR = os.path.join(HERE, "db")
# the fabric list's columns when there is no list yet (what the first screens saved)
LOG_COLS = ["Saved on", "Fabric code", "Description", "Supplier", "Should-cost Rs/m", "Should-cost Rs/kg",
            "Quoted Rs/m", "Gap Rs/m", "Gap %"]
# the list file's columns and the quote table's: everything else a file had goes into `extra`
QUOTE_COLUMNS = {"Saved on": "saved_on", "Fabric code": "fabric_code", "Description": "description", "Supplier": "supplier",
                 "Should-cost Rs/m": "should_cost_per_m", "Should-cost Rs/kg": "should_cost_per_kg", "Quoted Rs/m": "quoted_per_m",
                 "Gap Rs/m": "gap_per_m", "Gap %": "gap_pct", "Id": "legacy_id", "Inputs": "choices", "Result": "costing",
                 "Mill": "sheet_row", "Problems": "problems", "Notes": "notes", "Upload": "upload"}
KINDS = ("rates", "list", "negotiations", "seen", "sheets")
FILES = {"rates": "Rate_Master.xlsx", "list": "costing_log.csv", "negotiations": "negotiations.json",
         "seen": "alerts_seen.json", "sheets": "cost_sheets.json"}


class StoreUnavailable(Exception):
    """The store cannot be used: the database cannot be reached, or the copying in did not succeed. The web layer
    answers 503 with this text."""


class Conflict(Exception):
    """Someone else changed it since the page read it (the tracker's 'seen' count)."""


def data_dir():
    return os.environ.get("RIGHTPRICE_DATA") or os.path.join(HERE, "data")


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _list_texts(rows):
    """Each cell of these rows as the list file writes it (pandas' own rendering), None for an empty cell. Kept as
    this text, a row reads back exactly as it would from the file."""
    if not rows:
        return [], []
    df = pd.DataFrame(rows)
    back = pd.read_csv(io.StringIO(df.to_csv(index=False)), dtype=str, keep_default_na=False)
    cols = [str(c) for c in df.columns]
    return cols, [{c: (v if v != "" else None) for c, v in zip(cols, r)} for r in back.itertuples(index=False, name=None)]


def _list_frame(header, texts):
    """The fabric list as the screens read it: the cells' text, read the way the list file is read."""
    if header is None:
        return pd.DataFrame(columns=LOG_COLS)
    df = pd.DataFrame([[t.get(c) for c in header] for t in texts], columns=header, dtype=object)
    return pd.read_csv(io.StringIO(df.to_csv(index=False)), dtype={"Id": str})


# ===================================================================== the files, as before
class FileStore:
    """Today's files in the data folder. Every read and write is the one the app made before the data layer."""
    kind = "files"

    def __init__(self, folder=None):
        self.folder = folder or data_dir()
        self.paths = {k: os.path.join(self.folder, f) for k, f in FILES.items()}
        self._lock = threading.RLock()

    def describe(self):
        return {"store": "files", "folder": self.folder,
                "files": {FILES[k]: os.path.exists(p) for k, p in self.paths.items()}}

    def version(self, what):
        return _mtime(self.paths[what])

    # ------------------------------------------------ rate master
    def read_rates(self):
        try:
            with open(self.paths["rates"], "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def write_rates(self, data, reason="", who="", backup=None, backup_if_absent=False):
        """Write the workbook. `backup` names the dated copy kept first (' backup 20261127'); with backup_if_absent the
        copy is made only if that name is not there yet (the first change of the day). Returns the copy's file name."""
        path, kept = self.paths["rates"], None
        with self._lock:
            if backup and os.path.exists(path):
                copy = path.replace(".xlsx", f"{backup}.xlsx")
                if not (backup_if_absent and os.path.exists(copy)):
                    shutil.copyfile(path, copy)
                    kept = os.path.basename(copy)
            _write_atomic(path, data)
        return kept

    # ------------------------------------------------ fabric list
    def read_list(self):
        if os.path.exists(self.paths["list"]):
            return pd.read_csv(self.paths["list"], dtype={"Id": str})
        return pd.DataFrame(columns=LOG_COLS)

    def _write_list(self, df):
        os.makedirs(self.folder, exist_ok=True)
        df.to_csv(self.paths["list"], index=False)

    def append_list(self, rows, who=""):
        with self._lock:
            self._write_list(pd.concat([self.read_list(), pd.DataFrame(rows)], ignore_index=True))

    def remove_list(self, ids, who=""):
        with self._lock:
            log = self.read_list()
            keep = log[~log["Id"].astype(str).isin(ids)] if "Id" in log.columns else log
            self._write_list(keep)
            return len(log) - len(keep)

    def replace_list_row(self, old_id, row, who=""):
        with self._lock:
            log = self.read_list()
            if "Id" in log.columns:
                log = log[log["Id"].astype(str) != old_id]
            self._write_list(pd.concat([log, pd.DataFrame([row])], ignore_index=True))

    # ------------------------------------------------ negotiation tracker
    def read_negotiations(self):
        try:
            with open(self.paths["negotiations"], encoding="utf8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_negos(self, d):
        _write_atomic(self.paths["negotiations"], json.dumps(d, default=str).encode("utf8"))

    def add_step(self, key, fields, event, seen=None):
        """Record one step. `seen` is how many steps the page saw: if that is no longer so, Conflict and nothing changes."""
        with self._lock:
            d = self.read_negotiations()
            if seen is not None and int(seen) != len(d.get(key, {}).get("events", [])):
                raise Conflict()
            rec = d.setdefault(key, {"key": key, "events": []})
            rec.update(fields)
            rec["events"].append(event)
            self._save_negos(d)
            return rec

    def remove_step(self, key, step_id, removed_at, removed_by):
        """Take a step out, kept marked removed (the last 100 per fabric). Returns how many were taken out."""
        with self._lock:
            d = self.read_negotiations()
            gone = [e for e in d.get(key, {}).get("events", []) if e["id"] == step_id]
            if not gone:
                return 0
            d[key]["events"] = [e for e in d[key]["events"] if e["id"] != step_id]
            d[key].setdefault("removed", []).extend(dict(e, removed_at=removed_at, removed_by=removed_by) for e in gone)
            d[key]["removed"] = d[key]["removed"][-100:]
            self._save_negos(d)
            return len(gone)

    # ------------------------------------------------ alerts seen
    def read_seen(self):
        try:
            with open(self.paths["seen"], encoding="utf8") as f:
                return set(json.load(f))
        except (OSError, ValueError):
            return set()

    def change_seen(self, ids=(), undo=False, restore=False, who=""):
        """Mark ids seen; with undo bring them back; with restore bring every one back."""
        with self._lock:
            ids = {str(i) for i in ids}
            seen = set() if restore else (self.read_seen() - ids if undo else self.read_seen() | ids)
            _write_atomic(self.paths["seen"], json.dumps(sorted(seen)).encode("utf8"))

    # ------------------------------------------------ mill cost sheets
    def read_sheets(self):
        try:
            with open(self.paths["sheets"], encoding="utf8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def write_sheets(self, rows):
        with self._lock:
            os.makedirs(self.folder, exist_ok=True)
            with open(self.paths["sheets"], "w", encoding="utf8") as f:
                json.dump(rows, f, default=str)


# ===================================================================== a database: PostgreSQL or SQLite
class _Cursor:
    """One SQL text for both: written with %s, turned into ? for SQLite."""

    def __init__(self, cur, kind):
        self.cur, self.kind = cur, kind

    def run(self, sql, params=()):
        self.cur.execute(sql if self.kind == "postgres" else sql.replace("%s", "?"), tuple(params))
        return self

    def all(self, sql, params=()):
        return self.run(sql, params).cur.fetchall()

    def one(self, sql, params=()):
        return self.run(sql, params).cur.fetchone()

    @property
    def rowcount(self):
        return self.cur.rowcount


def _in(n):
    return "(" + ", ".join(["%s"] * n) + ")"


class SqlStore:
    """PostgreSQL or SQLite. One connection per process, used by one request at a time; a broken connection is made
    again at the next use."""
    LOCK_KEY = 727274190        # PostgreSQL advisory lock: one writer of a kind at a time, across the app's processes

    def __init__(self, url, folder=None, start=True):
        self.url, self.folder = url, folder or data_dir()
        if url.startswith(("postgresql://", "postgres://")):
            self.kind = "postgres"
        elif url.startswith("sqlite:///"):
            self.kind, self.path = "sqlite", url[len("sqlite:///"):]
        else:
            raise StoreUnavailable("DATABASE_URL is neither postgresql://... nor sqlite:///<path>")
        self._lock, self._conn, self.error, self.imported = threading.RLock(), None, None, None
        if start:
            try:
                self.migrate()
                self.imported = self.copy_files_in()
                self._files_unchanged()
            except StoreUnavailable as e:
                self.error = str(e)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
            if self.error:
                self.error = self.scrub(self.error)     # never the password, whatever the error says
            if self.error:
                print(f"RightPrice: the database is not in use: {self.error}", file=sys.stderr)

    # ------------------------------------------------ connection and transactions
    def where(self):
        """Where the database is (host and database), never the user or the password."""
        if self.kind == "sqlite":
            return self.path
        rest = self.url.split("://", 1)[1]
        return rest.rsplit("@", 1)[-1].split("?", 1)[0] or "PostgreSQL"

    def scrub(self, text):
        """An error's words with the password, and the whole setting, taken out."""
        text = str(text).replace(self.url, "<DATABASE_URL>")
        if self.kind == "postgres":
            auth = self.url.split("://", 1)[1].rsplit("@", 1)
            if len(auth) == 2 and ":" in auth[0]:
                secret = auth[0].split(":", 1)[1]
                for s in {secret, secret.replace("%40", "@")} - {""}:
                    text = text.replace(s, "***")
        return text

    def _connect(self):
        if self._conn is not None:
            return self._conn
        try:
            if self.kind == "postgres":
                import psycopg
                self._conn = psycopg.connect(self.url, connect_timeout=15)
            else:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
                self._conn.execute("PRAGMA foreign_keys = ON")
        except Exception as e:
            self._conn = None
            first = str(e).splitlines()[0] if str(e) else ""
            raise StoreUnavailable(self.scrub(f"The database at {self.where()} could not be reached ({type(e).__name__}: {first})"))
        return self._conn

    def _drop(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _broken(self, e):
        if self.kind == "postgres":
            import psycopg
            return isinstance(e, (psycopg.OperationalError, psycopg.InterfaceError))
        return False

    @contextlib.contextmanager
    def tx(self, write=None):
        """A transaction. write names the kind being changed: writers of a kind wait for each other, across processes."""
        if self.error:
            raise StoreUnavailable(self.error)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                if self.kind == "sqlite":
                    cur.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                elif write:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (self.LOCK_KEY + KINDS.index(write) if write in KINDS else self.LOCK_KEY,))
                yield _Cursor(cur, self.kind)
                if write and write in KINDS:
                    cur.execute("UPDATE store_state SET version = version + 1 WHERE kind = " + ("%s" if self.kind == "postgres" else "?"), (write,))
                conn.commit()
            except BaseException as e:
                try:
                    conn.rollback()
                except Exception:
                    self._drop()
                if self._broken(e):
                    self._drop()
                    raise StoreUnavailable(f"The database at {self.where()} stopped answering ({type(e).__name__}); try again") from e
                raise

    def _read(self, fn):
        """A read, tried once more on a fresh connection if the first one had gone stale."""
        try:
            with self.tx() as c:
                return fn(c)
        except StoreUnavailable:
            if self.error:
                raise
            with self.tx() as c:
                return fn(c)

    # ------------------------------------------------ the tables
    def _sql_file(self, path):
        words = {"postgres": {"@ID@": "bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", "@BLOB@": "bytea", "@REAL@": "double precision"},
                 "sqlite": {"@ID@": "INTEGER PRIMARY KEY AUTOINCREMENT", "@BLOB@": "BLOB", "@REAL@": "REAL"}}[self.kind]
        text = open(path, encoding="utf8").read()
        for k, v in words.items():
            text = text.replace(k, v)
        text = "\n".join(line.split("--", 1)[0] for line in text.splitlines())   # no comments: no ';' inside one
        return [s.strip() for s in text.split(";") if s.strip()]

    def migrate(self):
        """Apply the numbered files in db/ not yet applied, each once, in order, each in its own transaction."""
        files = sorted(glob.glob(os.path.join(DB_DIR, "[0-9][0-9][0-9]_*.sql")))
        with self.tx(write="migrate") as c:
            c.run("CREATE TABLE IF NOT EXISTS schema_migration (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        for path in files:
            name = os.path.basename(path)
            with self.tx(write="migrate") as c:
                if c.one("SELECT name FROM schema_migration WHERE name = %s", (name,)):
                    continue
                for stmt in self._sql_file(path):
                    c.run(stmt)
                c.run("INSERT INTO schema_migration (name, applied_at) VALUES (%s, %s)", (name, _now()))

    def version(self, what):
        return self._read(lambda c: c.one("SELECT version FROM store_state WHERE kind = %s", (what,))[0])

    def describe(self):
        def get(c):
            counts = {"rate versions": c.one("SELECT count(*) FROM rate_version")[0],
                      "fabric list rows": c.one("SELECT count(*) FROM quote WHERE removed_at IS NULL")[0],
                      "fabric list rows removed (kept)": c.one("SELECT count(*) FROM quote WHERE removed_at IS NOT NULL")[0],
                      "fabrics in the tracker": c.one("SELECT count(*) FROM negotiation")[0],
                      "tracker steps": c.one("SELECT count(*) FROM negotiation_step WHERE removed_at IS NULL")[0],
                      "alerts seen": c.one("SELECT count(*) FROM alert_seen")[0],
                      "mill cost sheet rows": c.one("SELECT count(*) FROM cost_sheet_row")[0]}
            run = c.one("SELECT started_at, finished_at, folder, files, checked FROM import_run ORDER BY id DESC LIMIT 1")
            rate = c.one("SELECT id, created_at, created_by, reason FROM rate_version ORDER BY id DESC LIMIT 1")
            migs = [r[0] for r in c.all("SELECT name FROM schema_migration ORDER BY name")]
            return counts, run, rate, migs
        out = {"store": self.kind, "where": self.where()}
        if self.error:
            return dict(out, ok=False, error=self.error,
                        to_go_back="Remove the app setting DATABASE_URL and restart: the app returns to the files, which were not changed.")
        counts, run, rate, migs = self._read(get)
        out.update(ok=True, counts=counts, tables_from=migs,
                   rate_master_in_use=None if not rate else {"version": rate[0], "saved": rate[1], "by": rate[2], "reason": rate[3]})
        if run:
            out["copied_in"] = {"started": run[0], "finished": run[1], "folder": run[2],
                                "files": json.loads(run[3]), "checked": json.loads(run[4])}
        return out

    # ------------------------------------------------ rate master
    def _rates(self, c):
        r = c.one("SELECT workbook FROM rate_version ORDER BY id DESC LIMIT 1")
        return None if r is None else bytes(r[0])

    def read_rates(self):
        return self._read(self._rates)

    def _insert_rates(self, c, data, reason, who="", at=None):
        c.run("INSERT INTO rate_version (created_at, created_by, reason, workbook, sha256) VALUES (%s, %s, %s, %s, %s)",
              (at or _now(), who or "", reason or "Saved", data, _sha(data)))

    def write_rates(self, data, reason="", who="", backup=None, backup_if_absent=False):
        """A new version. The one before is kept as it was: that is the dated copy, named in what comes back."""
        with self.tx(write="rates") as c:
            prev = c.one("SELECT id FROM rate_version ORDER BY id DESC LIMIT 1")
            self._insert_rates(c, data, reason, who)
        return f"rate version {prev[0]}, kept in the database" if backup and prev else None

    # ------------------------------------------------ fabric list
    SQL_COLS = list(QUOTE_COLUMNS.values())

    def _header(self, c):
        r = c.one("SELECT value FROM store_meta WHERE key = 'list_columns'")
        return None if r is None else json.loads(r[0])

    def _list(self, c):
        header = self._header(c)
        texts = []
        for row in c.all(f"SELECT {', '.join(self.SQL_COLS)}, extra FROM quote WHERE removed_at IS NULL ORDER BY id"):
            t = {col: v for col, v in zip(QUOTE_COLUMNS, row[:-1])}
            t.update(json.loads(row[-1] or "{}"))
            texts.append(t)
        return header, texts

    def read_list(self):
        return _list_frame(*self._read(self._list))

    def _append(self, c, rows, who, at=None, rate_version=True):
        cols, texts = _list_texts(rows)
        header = self._header(c)
        new = list(header if header is not None else LOG_COLS)
        new += [k for k in cols if k not in new]
        if new != header:
            c.run("DELETE FROM store_meta WHERE key = 'list_columns'")
            c.run("INSERT INTO store_meta (key, value) VALUES ('list_columns', %s)", (json.dumps(new),))
        rv = c.one("SELECT max(id) FROM rate_version")[0] if rate_version else None
        for t in texts:
            extra = {k: v for k, v in t.items() if k not in QUOTE_COLUMNS}
            c.run(f"INSERT INTO quote ({', '.join(self.SQL_COLS)}, extra, rate_version_id, added_at, added_by) "
                  f"VALUES ({', '.join(['%s'] * (len(self.SQL_COLS) + 4))})",
                  [t.get(k) for k in QUOTE_COLUMNS] + [json.dumps(extra), rv, at or _now(), who or ""])

    def append_list(self, rows, who=""):
        with self.tx(write="list") as c:
            self._append(c, rows, who)

    def _remove(self, c, ids, who):
        ids = sorted({str(i) for i in ids})
        if not ids:
            return 0
        return c.run(f"UPDATE quote SET removed_at = %s, removed_by = %s WHERE removed_at IS NULL AND legacy_id IN {_in(len(ids))}",
                     [_now(), who or ""] + ids).rowcount

    def remove_list(self, ids, who=""):
        with self.tx(write="list") as c:
            return self._remove(c, ids, who)

    def replace_list_row(self, old_id, row, who=""):
        with self.tx(write="list") as c:
            self._remove(c, [old_id], who)
            self._append(c, [row], who)

    # ------------------------------------------------ negotiation tracker
    STEP = ["step_id", "at", "step_date", "kind", "price", "note", "recorded_by"]
    STEP_KEYS = ["id", "at", "date", "kind", "price", "note", "by"]

    def _step(self, row):
        e = dict(zip(self.STEP_KEYS, row[:7]))
        e.update(json.loads(row[7] or "{}"))
        return e

    def _negos(self, c, only=None):
        recs = {}
        where = "" if only is None else " WHERE key = %s"
        for key, fields in c.all("SELECT key, fields FROM negotiation" + where + " ORDER BY id", () if only is None else (only,)):
            recs[key] = dict({"key": key, "events": []}, **json.loads(fields or "{}"))
        where = "" if only is None else " AND negotiation_key = %s"
        cols = ", ".join(self.STEP) + ", extra, negotiation_key"
        for row in c.all(f"SELECT {cols} FROM negotiation_step WHERE removed_at IS NULL{where} ORDER BY id", () if only is None else (only,)):
            recs[row[-1]]["events"].append(self._step(row))
        removed = {}
        for row in c.all(f"SELECT {cols}, removed_at, removed_by FROM negotiation_step WHERE removed_at IS NOT NULL{where} "
                         "ORDER BY removed_seq, id", () if only is None else (only,)):
            removed.setdefault(row[8], []).append(dict(self._step(row), removed_at=row[9], removed_by=row[10]))
        for key, gone in removed.items():
            recs[key]["removed"] = gone[-100:]
        return recs

    def read_negotiations(self):
        return self._read(self._negos)

    def _insert_step(self, c, key, e, removed=None):
        extra = {k: v for k, v in e.items() if k not in self.STEP_KEYS and k not in ("removed_at", "removed_by")}
        price = e.get("price")
        vals = [str(e.get("id")), e.get("at"), e.get("date"), e.get("kind"), None if price is None else float(price),
                e.get("note"), e.get("by"), json.dumps(extra, default=str), key]
        cols = ", ".join(self.STEP) + ", extra, negotiation_key"
        if removed is None:
            c.run(f"INSERT INTO negotiation_step ({cols}) VALUES ({', '.join(['%s'] * 9)})", vals)
        else:
            c.run(f"INSERT INTO negotiation_step ({cols}, removed_at, removed_by, removed_seq) VALUES ({', '.join(['%s'] * 12)})",
                  vals + [e.get("removed_at"), e.get("removed_by"), removed])

    def add_step(self, key, fields, event, seen=None):
        with self.tx(write="negotiations") as c:
            n = c.one("SELECT count(*) FROM negotiation_step WHERE negotiation_key = %s AND removed_at IS NULL", (key,))[0]
            if seen is not None and int(seen) != n:
                raise Conflict()
            row = c.one("SELECT fields FROM negotiation WHERE key = %s", (key,))
            if row is None:
                c.run("INSERT INTO negotiation (key, fields) VALUES (%s, %s)", (key, json.dumps(fields, default=str)))
            elif fields:
                c.run("UPDATE negotiation SET fields = %s WHERE key = %s", (json.dumps(dict(json.loads(row[0] or "{}"), **fields), default=str), key))
            self._insert_step(c, key, event)
            return self._negos(c, only=key)[key]

    def remove_step(self, key, step_id, removed_at, removed_by):
        with self.tx(write="negotiations") as c:
            ids = [r[0] for r in c.all("SELECT id FROM negotiation_step WHERE negotiation_key = %s AND step_id = %s AND removed_at IS NULL "
                                       "ORDER BY id", (key, str(step_id)))]
            seq = c.one("SELECT coalesce(max(removed_seq), 0) FROM negotiation_step")[0]
            for n, i in enumerate(ids):
                c.run("UPDATE negotiation_step SET removed_at = %s, removed_by = %s, removed_seq = %s WHERE id = %s",
                      (removed_at, removed_by, seq + n + 1, i))
            return len(ids)

    # ------------------------------------------------ alerts seen
    def read_seen(self):
        return self._read(lambda c: {r[0] for r in c.all("SELECT quote_id FROM alert_seen")})

    def change_seen(self, ids=(), undo=False, restore=False, who=""):
        ids = sorted({str(i) for i in ids})
        with self.tx(write="seen") as c:
            if restore:
                c.run("DELETE FROM alert_seen")
            elif undo:
                if ids:
                    c.run(f"DELETE FROM alert_seen WHERE quote_id IN {_in(len(ids))}", ids)
            else:
                for i in ids:
                    c.run("INSERT INTO alert_seen (quote_id, seen_at, seen_by) VALUES (%s, %s, %s) ON CONFLICT (quote_id) DO NOTHING",
                          (i, _now(), who or ""))

    # ------------------------------------------------ mill cost sheets
    def read_sheets(self):
        return self._read(lambda c: [json.loads(r[0]) for r in c.all("SELECT row FROM cost_sheet_row ORDER BY id")])

    def _put_sheets(self, c, rows):
        c.run("DELETE FROM cost_sheet_row")
        for r in rows:
            c.run("INSERT INTO cost_sheet_row (row) VALUES (%s)", (json.dumps(r, default=str),))

    def write_sheets(self, rows):
        with self.tx(write="sheets") as c:
            self._put_sheets(c, rows)

    # ------------------------------------------------ copying the files in, once
    def _source_files(self):
        """The data files as they are now: name -> (bytes, sha256). Only read."""
        out = {}
        for k, name in FILES.items():
            p = os.path.join(self.folder, name)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    data = f.read()
                out[name] = (data, _sha(data))
        return out

    def _empty(self, c):
        return (c.one("SELECT count(*) FROM rate_version")[0] == 0 and c.one("SELECT count(*) FROM import_run")[0] == 0
                and c.one("SELECT count(*) FROM quote")[0] == 0 and c.one("SELECT count(*) FROM negotiation")[0] == 0)

    def copy_files_in(self):
        """With the database empty: every data file in, in one transaction, then checked. Returns what was done, or None
        when the database already holds the data."""
        started = _now()
        with self.tx(write="import") as c:
            if not self._empty(c):
                return None
            src = self._source_files()
            fs = FileStore(self.folder)
            files = []
            # the rate master: the dated copies beside it first, oldest first, as earlier versions; then the one in use
            copies = sorted((p for p in glob.glob(os.path.join(self.folder, "Rate_Master*.xlsx"))
                             if os.path.basename(p) != FILES["rates"]), key=lambda p: (os.path.getmtime(p), p))
            for p in copies:
                with open(p, "rb") as f:
                    data = f.read()
                at = dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")
                self._insert_rates(c, data, f"Copied in from {os.path.basename(p)} (a dated copy kept before a change)", at=at)
                files.append({"name": os.path.basename(p), "bytes": len(data), "sha256": _sha(data), "as": "an earlier rate version"})
            if FILES["rates"] in src:
                data, sha = src[FILES["rates"]]
                self._insert_rates(c, data, f"Copied in from {FILES['rates']}")
                files.append({"name": FILES["rates"], "bytes": len(data), "sha256": sha, "as": "the rate master in use"})
            else:       # a first start with no rate master yet: begin from the one that came with the code, as the files did
                with open(SHIPPED_MASTER, "rb") as f:
                    data = f.read()
                self._insert_rates(c, data, "Begun from the rate master that came with the code")
                files.append({"name": "data/Rate_Master.xlsx (with the code)", "bytes": len(data), "sha256": _sha(data), "as": "the rate master in use"})
            if FILES["list"] in src:
                raw = pd.read_csv(io.BytesIO(src[FILES["list"]][0]), dtype=str, keep_default_na=False)
                header = [str(h) for h in raw.columns]
                c.run("INSERT INTO store_meta (key, value) VALUES ('list_columns', %s)", (json.dumps(header),))
                texts = [{h: (v if v != "" else None) for h, v in zip(header, r)} for r in raw.itertuples(index=False, name=None)]
                for t in texts:     # inserted as the cells' text, as the file holds it
                    extra = {k: v for k, v in t.items() if k not in QUOTE_COLUMNS}
                    c.run(f"INSERT INTO quote ({', '.join(self.SQL_COLS)}, extra, added_at, added_by) VALUES ({', '.join(['%s'] * (len(self.SQL_COLS) + 3))})",
                          [t.get(k) for k in QUOTE_COLUMNS] + [json.dumps(extra), started, "copied in from costing_log.csv"])
            negos = fs.read_negotiations()
            seq = 0
            for key, rec in negos.items():
                fields = {k: v for k, v in rec.items() if k not in ("key", "events", "removed")}
                c.run("INSERT INTO negotiation (key, fields) VALUES (%s, %s)", (key, json.dumps(fields, default=str)))
                for e in rec.get("events", []):
                    self._insert_step(c, key, e)
                for e in rec.get("removed", []):
                    seq += 1
                    self._insert_step(c, key, e, removed=seq)
            for i in sorted(fs.read_seen()):
                c.run("INSERT INTO alert_seen (quote_id, seen_at, seen_by) VALUES (%s, %s, %s)", (str(i), started, "copied in from alerts_seen.json"))
            self._put_sheets(c, fs.read_sheets())
            for name in (FILES["list"], FILES["negotiations"], FILES["seen"], FILES["sheets"]):
                if name in src:
                    files.append({"name": name, "bytes": len(src[name][0]), "sha256": src[name][1]})
            checked = self._check_copy(c, fs, src)
            if self._source_files() != src:
                raise StoreUnavailable("The files changed while they were being copied in; nothing was kept. Restart the app to try again.")
            c.run("INSERT INTO import_run (started_at, finished_at, folder, files, checked) VALUES (%s, %s, %s, %s, %s)",
                  (started, _now(), self.folder, json.dumps(files), json.dumps(checked)))
            for k in KINDS:
                c.run("UPDATE store_state SET version = version + 1 WHERE kind = %s", (k,))
        print(f"RightPrice: the data files in {self.folder} were copied into the database at {self.where()} and checked: "
              + "; ".join(checked["summary"]), file=sys.stderr)
        return {"files": files, "checked": checked}

    def _check_copy(self, c, fs, src):
        """Inside the copying-in transaction: each file read back from the database exactly as from the file, and every
        fabric on the list costed the same to the paisa on both. Anything different and the transaction is undone."""
        import masters      # late: masters reads the rate master through this module

        def fail(what):
            raise StoreUnavailable(f"Copying the files in was stopped and nothing was kept: {what}. "
                                   "The app stays off the database; the files were not changed.")
        summary = []
        rates_file = src[FILES["rates"]][0] if FILES["rates"] in src else open(SHIPPED_MASTER, "rb").read()
        if self._rates(c) != rates_file:
            fail("the rate master read back differently")
        m = pd.read_excel(io.BytesIO(self._rates(c)), sheet_name=None)
        m_file = pd.read_excel(io.BytesIO(rates_file), sheet_name=None)
        if list(m) != list(m_file) or any(not m[k].equals(m_file[k]) for k in m):
            fail("a rate master table read back differently")
        summary.append(f"rate master: {len(m)} tables, the same")
        a, b = fs.read_list(), _list_frame(*self._list(c))
        try:
            pd.testing.assert_frame_equal(a, b, check_dtype=True)
        except AssertionError as e:
            fail(f"the fabric list read back differently ({str(e).splitlines()[0]})")
        costed = 0
        for raw in a.get("Inputs", pd.Series(dtype=object)).dropna():
            try:
                sel = json.loads(raw)
            except ValueError:
                continue
            try:
                x = masters.cost(sel, m_file)["total_per_m"]
            except Exception as e:
                x = f"not costed: {e}"
            try:
                y = masters.cost(sel, m)["total_per_m"]
            except Exception as e:
                y = f"not costed: {e}"
            if x != y:
                fail(f"a fabric on the list ({sel.get('Fabric code')}) costs {x} from the file and {y} from the database")
            costed += 1
        summary.append(f"fabric list: {len(a)} rows, the same; {costed} costings, equal to the paisa (exactly equal)")
        if self._negos(c) != fs.read_negotiations():
            fail("the negotiation tracker read back differently")
        summary.append(f"tracker: {len(fs.read_negotiations())} fabrics, the same")
        if {r[0] for r in c.all("SELECT quote_id FROM alert_seen")} != fs.read_seen():
            fail("the alerts marked seen read back differently")
        summary.append(f"alerts seen: {len(fs.read_seen())}, the same")
        if [json.loads(r[0]) for r in c.all("SELECT row FROM cost_sheet_row ORDER BY id")] != fs.read_sheets():
            fail("the mill cost sheets read back differently")
        summary.append(f"mill cost sheets: {len(fs.read_sheets())} rows, the same")
        return {"summary": summary, "equal": True}

    def _files_unchanged(self):
        """The data files must be as they were when copied in. If they changed since (the setting was taken off for a
        while and work was done on the files), the app stays off the database so neither side's changes are lost."""
        def get(c):
            r = c.one("SELECT finished_at, files FROM import_run ORDER BY id DESC LIMIT 1")
            return r
        r = self._read(get)
        if r is None:
            return
        then = {f["name"]: f["sha256"] for f in json.loads(r[1]) if f.get("as") != "an earlier rate version" and "(with the code)" not in f["name"]}
        now = {name: sha for name, (_, sha) in self._source_files().items()}
        changed = sorted(n for n in set(then) | set(now) if then.get(n) != now.get(n))
        if changed:
            raise StoreUnavailable(
                f"The data files changed after they were copied into the database on {r[0]} ({', '.join(changed)}). "
                "So that neither the database's changes nor the files' are lost, the app does not start on the database. "
                "Remove DATABASE_URL to keep working on the files, and ask for the two to be brought together.")


# ===================================================================== which one, chosen once by the setting
_store = None
_store_lock = threading.Lock()


def get():
    """The store this process uses: the database when DATABASE_URL is set, the files otherwise."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                url = os.environ.get("DATABASE_URL", "").strip()
                _store = SqlStore(url) if url else FileStore()
    return _store


def reset():
    """Forget the store chosen (the checks use this after changing the setting)."""
    global _store
    if isinstance(_store, SqlStore):
        _store._drop()
    _store = None


def export(folder, s=None):
    """What the store holds, written as the files the app reads without a database, into a new empty folder."""
    s = s or get()
    if os.path.isdir(folder) and os.listdir(folder):
        raise SystemExit(f"{folder} is not empty: give a new folder, so nothing is overwritten")
    os.makedirs(folder, exist_ok=True)
    fs = FileStore(folder)
    rates = s.read_rates()
    if rates is not None:
        _write_atomic(fs.paths["rates"], rates)
    frame = s.read_list()
    if len(frame) or len(frame.columns) != len(LOG_COLS) or list(frame.columns) != LOG_COLS:
        fs._write_list(frame)
    d = s.read_negotiations()
    if d:
        fs._save_negos(d)
    seen = s.read_seen()
    if seen:
        fs.change_seen(seen)
    sheets = s.read_sheets()
    if sheets:
        fs.write_sheets(sheets)
    return sorted(os.listdir(folder))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["export"] and len(args) == 2:
        print("Written:", ", ".join(export(args[1])))
    elif args[:1] in (["status"], []):
        print(json.dumps(get().describe(), indent=1, default=str))
    else:
        raise SystemExit(__doc__)
