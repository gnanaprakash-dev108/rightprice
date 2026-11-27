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
    python store.py keep-database     after the files were worked on while DATABASE_URL was off: keep the database
                                      and set the files aside (they are not changed)
"""
import contextlib
import datetime as dt
import glob
import hashlib
import io
import json
import os
import shutil
import re
import sqlite3
import sys
import threading
import time

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
KINDS += ("users",)         # stage 3: the people let in and what each role may do (db/003_users_and_roles.sql, data_users.py)
KINDS += ("purchases",)     # stage 2: the purchase history and Fab groups (db/002_purchases_and_fab_groups.sql), on a database only
MOVED_NOTE = "moved_to_database.json"      # left beside the files once they are copied into a database (they stay as they were)
FILES = {"rates": "Rate_Master.xlsx", "list": "costing_log.csv", "negotiations": "negotiations.json",
         "seen": "alerts_seen.json", "sheets": "cost_sheets.json"}


class StoreUnavailable(Exception):
    """The store cannot be used: the database cannot be reached, or the copying in did not succeed. The web layer
    answers 503 with this text."""


class Refusal(StoreUnavailable):
    """The app will not use the database as things stand (the copying in did not check out, the files changed after the
    move, an empty database where one was expected, a setting that cannot be read). The words say why and what to do."""


class Busy(StoreUnavailable):
    """Waited too long for another request or another writer; nothing is wrong with the database."""


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
        out = {"store": "files", "ok": True, "folder": self.folder, "files": {FILES[k]: os.path.exists(p) for k, p in self.paths.items()}}
        try:
            with open(os.path.join(self.folder, MOVED_NOTE), encoding="utf8") as f:
                moved = json.load(f)
            out["note"] = (f"These files were copied into a database on {moved.get('when')} ({moved.get('where')}). "
                           "Anything changed there since then is not in these files.")
        except (OSError, ValueError):
            pass
        return out

    def version(self, what):
        return _mtime(self.paths[what]) if what in self.paths else None     # the purchase history has no file

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

    def keep_copy(self, backup, if_absent=False):
        """A dated copy of the rate master as it is now, beside it (' backup 20261127'). Returns its file name."""
        path = self.paths["rates"]
        with self._lock:
            copy = path.replace(".xlsx", f"{backup}.xlsx")
            if os.path.exists(path) and not (if_absent and os.path.exists(copy)):
                shutil.copyfile(path, copy)
                return os.path.basename(copy)
        return None

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
    again at the next use. If the database cannot be reached when the app starts, it is tried again every RETRY seconds,
    so an outage passes by itself."""
    LOCK_KEY = 727274190        # PostgreSQL advisory locks: this one for adding tables and copying in, +1 ... +5 for each kind
    RETRY, RETRY_REFUSED = 15, 300      # seconds between tries to start: while unreachable; after a refusal
    WAIT = 20                   # seconds a request waits for another one using the database before it is told to try again

    def __init__(self, url, folder=None, start=True):
        self.url, self.folder = url, folder or data_dir()
        self._lock, self._conn, self.imported, self._secret = threading.RLock(), None, None, ""
        self.error, self.refused, self._tried, self._starter, self._unreadable = None, False, time.monotonic(), None, False
        self.kind, self.path, self._pg = "postgres" if url.startswith(("postgresql://", "postgres://")) else "sqlite", None, {}
        self.started = not start
        try:
            self._parse(url)
        except Refusal as e:
            self.started, self.error, self.refused, self._unreadable = False, str(e), True, True
            print(f"RightPrice: the database is not in use: {self.error}", file=sys.stderr)
            return
        if start:
            self._start()

    def _parse(self, url):
        """Read the setting: postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require, the password typed as it is
        (any characters, not percent-encoded). Everything after the password is read by PostgreSQL's own library."""
        if self.kind == "sqlite":
            if not url.startswith("sqlite:///"):
                raise Refusal("DATABASE_URL is neither postgresql://... nor sqlite:///<full path to a file>")
            self.path = url[len("sqlite:///"):]
            if not os.path.isabs(self.path):
                raise Refusal("DATABASE_URL names a SQLite file by a relative path; give the full path, with four slashes: "
                              "sqlite:////home/rightprice-data/rightprice.db (a relative one would sit in the code folder, "
                              "which a deploy replaces)")
            return
        from urllib.parse import quote
        from psycopg.conninfo import conninfo_to_dict
        scheme, rest = url.split("://", 1)
        host = r"(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._\-]+)(:\d+)?"
        cut = next((i for i, ch in enumerate(rest) if ch == "@" and re.fullmatch(rf"{host}(,{host})*", re.split(r"[/?]", rest[i + 1:], 1)[0])), None)
        userinfo, hostpart = (rest[:cut], rest[cut + 1:]) if cut is not None else ("", rest)
        user, colon, pw = userinfo.partition(":")
        self._secret = pw
        login = (quote(user, safe="") + (":" + quote(pw, safe="") if colon else "") + "@") if userinfo else ""
        try:
            self._pg = conninfo_to_dict(f"{scheme}://{login}{hostpart}")
        except Exception:
            raise Refusal("DATABASE_URL could not be read. It should be postgresql://rpadmin:PASSWORD@rightprice-db."
                          "postgres.database.azure.com:5432/postgres?sslmode=require, with the password typed as it is") from None

    def _start(self):
        """Add any new tables, copy the files in on the first start, and check the files are as they were then."""
        self._tried, self._starter = time.monotonic(), threading.get_ident()
        error, refused = None, False
        try:
            self.migrate()
            self.imported = self.copy_files_in()
            self._files_unchanged()
        except Refusal as e:
            error, refused = str(e), True
        except StoreUnavailable as e:
            error = str(e)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            self._starter = None
        self.error, self.refused, self.started = (self.scrub(error) if error else None), refused, error is None
        if error:
            print(f"RightPrice: the database is not in use yet: {self.error}", file=sys.stderr)

    # ------------------------------------------------ connection and transactions
    def where(self):
        """Where the database is (host and database), never the user or the password."""
        if self.kind == "sqlite":
            return self.path or "a SQLite file"
        return f"{self._pg.get('host', 'localhost')}:{self._pg.get('port', 5432)}/{self._pg.get('dbname', '')}" if self._pg else "PostgreSQL"

    def scrub(self, text):
        """An error's words with the password, and the whole setting, taken out."""
        text = str(text).replace(self.url, "<DATABASE_URL>")
        from urllib.parse import quote
        for s in sorted({self._secret, quote(self._secret, safe=""), self._pg.get("password", "")} - {""}, key=len, reverse=True):
            text = text.replace(s, "***")
        return text

    def _connect(self):
        if self._conn is not None:
            return self._conn
        try:
            if self.kind == "postgres":
                import psycopg
                # keepalives and a user timeout: a connection a network device has dropped without a word is noticed
                # in about a minute, not the quarter of an hour the operating system would wait
                params = dict(connect_timeout=15, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
                              tcp_user_timeout=30000, application_name="rightprice")
                params.update(self._pg)
                # timeouts first; any options in the setting come after them (and win only where they name the same one)
                params["options"] = ("-c statement_timeout=120000 -c lock_timeout=30000 " + self._pg.get("options", "")).strip()
                self._conn = psycopg.connect(**params)
            else:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
                self._conn.execute("PRAGMA foreign_keys = ON")
        except Exception as e:
            self._conn = None
            first = str(e).splitlines()[0] if str(e) else ""
            raise StoreUnavailable(self.scrub(f"The database at {self.where()} could not be reached ({type(e).__name__}: {first}). "
                                              f"The app tries again by itself; nothing is lost."))
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
            from psycopg import errors
            if isinstance(e, (errors.LockNotAvailable, errors.QueryCanceled)):
                return False            # waited too long for another writer: the connection is fine
            return isinstance(e, (psycopg.OperationalError, psycopg.InterfaceError))
        return False

    def _ready(self):
        """Not started yet (unreachable, or refused): try to start again once its wait is over; else say why not."""
        if self.started or self._starter == threading.get_ident():
            return
        due = lambda: not self._unreadable and time.monotonic() - self._tried >= (self.RETRY_REFUSED if self.refused else self.RETRY)
        if due() and self._lock.acquire(timeout=self.WAIT):
            try:
                if not self.started and due():          # another request may have tried while this one waited
                    self._start()
            finally:
                self._lock.release()
        if not self.started:
            raise (Refusal if self.refused else StoreUnavailable)(
                self.error or "The database is being made ready (tables added, or the files copied in): try again in a moment")

    @contextlib.contextmanager
    def tx(self, write=None):
        """A transaction. write names the kind being changed: writers of a kind wait for each other, across processes.
        A read sees one moment of the database throughout."""
        self._ready()
        if not self._lock.acquire(timeout=self.WAIT):
            raise Busy("The database is busy with another request; try again in a moment")
        try:
            conn = self._connect()
            try:
                cur = conn.cursor()
                if self.kind == "sqlite":
                    cur.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                elif write:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (self.LOCK_KEY + 1 + KINDS.index(write) if write in KINDS else self.LOCK_KEY,))
                else:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                yield _Cursor(cur, self.kind)
                if write and write in KINDS:
                    cur.execute("UPDATE store_state SET version = version + 1 WHERE kind = " + ("%s" if self.kind == "postgres" else "?"), (write,))
                conn.commit()
            except BaseException as e:
                try:
                    conn.rollback()
                except Exception:
                    self._drop()
                if self.kind == "postgres" and not self._broken(e):
                    from psycopg import errors
                    if isinstance(e, (errors.LockNotAvailable, errors.QueryCanceled)):
                        raise Busy("The database is busy with another change; try again in a moment") from e
                if self._broken(e):
                    self._drop()
                    raise StoreUnavailable(self.scrub(f"The database at {self.where()} stopped answering ({type(e).__name__}: "
                                                      f"{str(e).splitlines()[0] if str(e) else ''}); try again")) from e
                raise
        finally:
            self._lock.release()

    def _read(self, fn):
        """A read, tried once more on a fresh connection if the first one had gone stale."""
        try:
            with self.tx() as c:
                return fn(c)
        except (Refusal, Busy):
            raise                       # a refusal stands, and a wait is not made twice
        except StoreUnavailable:
            if not self.started:
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
        if not self.started:
            try:
                self._ready()
            except StoreUnavailable:
                pass
        if not self.started:
            return dict(out, ok=False, error=self.error, advice=self._advice())
        counts, run, rate, migs = self._read(get)
        out.update(ok=True, counts=counts, tables_from=migs,
                   rate_master_in_use=None if not rate else {"version": rate[0], "saved": rate[1], "by": rate[2], "reason": rate[3]})
        if run:
            out["copied_in"] = {"started": run[0], "finished": run[1], "folder": run[2],
                                "files": json.loads(run[3]), "checked": json.loads(run[4])}
        return out

    def _advice(self):
        if not self.refused:
            if self._moved() is None:
                return ("The app tries the database again by itself every few seconds. Nothing has been copied in yet and the "
                        "files are unchanged. If this lasts, look at the database in the Azure portal (is it running?), or remove "
                        "DATABASE_URL and restart to go on working on the files meanwhile.")
            return ("The app tries the database again by itself every few seconds; nothing is lost. If this lasts, look at the "
                    "database in the Azure portal (is it running?). Do not remove DATABASE_URL for this: the files are as they "
                    "were when they were copied in, and work done on them would later have to be brought together by hand.")
        if self._moved() is None:
            return ("Nothing was copied in and the files were not changed. To go on working meanwhile, remove the app setting "
                    "DATABASE_URL and restart: the app returns to the files.")
        return "See the error: it says what to do."

    def _moved(self):
        """The note left in the data folder when its files were copied into a database, or None."""
        try:
            with open(os.path.join(self.folder, MOVED_NOTE), encoding="utf8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------ rate master
    def _rates(self, c):
        r = c.one("SELECT workbook FROM rate_version ORDER BY id DESC LIMIT 1")
        return None if r is None else bytes(r[0])

    def read_rates(self):
        return self._read(self._rates)

    def _insert_rates(self, c, data, reason, who="", at=None):
        c.run("INSERT INTO rate_version (created_at, created_by, reason, workbook, sha256) VALUES (%s, %s, %s, %s, %s)",
              (at or _now(), who or "", reason or "Saved", data, _sha(data)))

    def keep_copy(self, backup, if_absent=False):
        """A dated copy of the rate master as it is: in a database every version is kept anyway."""
        return None

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
        extra = json.loads(row[7] or "{}")
        for k in extra.pop("_absent", []):         # a step saved by an earlier version without this field
            e.pop(k, None)
        e.update(extra)
        return e

    def _negos(self, c, only=None):
        recs = {}
        where = "" if only is None else " WHERE key = %s"
        for key, fields in c.all("SELECT key, fields FROM negotiation" + where + " ORDER BY id", () if only is None else (only,)):
            recs[key] = dict({"key": key, "events": []}, **json.loads(fields or "{}"))
        where = "" if only is None else " AND negotiation_key = %s"
        cols = ", ".join(self.STEP) + ", extra, negotiation_key"
        for row in c.all(f"SELECT {cols} FROM negotiation_step WHERE removed_at IS NULL{where} ORDER BY id", () if only is None else (only,)):
            if row[-1] in recs:
                recs[row[-1]]["events"].append(self._step(row))
        removed = {}
        for row in c.all(f"SELECT {cols}, removed_at, removed_by FROM negotiation_step WHERE removed_at IS NOT NULL{where} "
                         "ORDER BY removed_seq, id", () if only is None else (only,)):
            removed.setdefault(row[8], []).append(dict(self._step(row), removed_at=row[9], removed_by=row[10]))
        for key, gone in removed.items():
            if key in recs:
                recs[key]["removed"] = gone[-100:]
        return recs

    def read_negotiations(self):
        return self._read(self._negos)

    def _insert_step(self, c, key, e, removed=None):
        extra = {k: v for k, v in e.items() if k not in self.STEP_KEYS and k not in ("removed_at", "removed_by")}
        absent = [k for k in self.STEP_KEYS if k not in e]
        if absent:
            extra["_absent"] = absent
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
            moved = self._moved()
            if moved is not None:
                raise Refusal(f"The files in {self.folder} were already copied into a database on {moved.get('when')} "
                              f"({moved.get('where')}), but the database the setting names now ({self.where()}) is empty. "
                              "Check that DATABASE_URL names the same database. Nothing was copied, so no work is lost. "
                              f"To copy these files into this empty database on purpose, delete {MOVED_NOTE} from that folder and restart.")
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
            for i in sorted({str(i) for i in fs.read_seen()}):
                c.run("INSERT INTO alert_seen (quote_id, seen_at, seen_by) VALUES (%s, %s, %s)", (str(i), started, "copied in from alerts_seen.json"))
            self._put_sheets(c, fs.read_sheets())
            for name in (FILES["list"], FILES["negotiations"], FILES["seen"], FILES["sheets"]):
                if name in src:
                    files.append({"name": name, "bytes": len(src[name][0]), "sha256": src[name][1]})
            checked = self._check_copy(c, fs, src)
            if self._source_files() != src:
                raise StoreUnavailable("The files changed while they were being copied in; nothing was kept. The app tries again by itself.")
            c.run("INSERT INTO import_run (started_at, finished_at, folder, files, checked) VALUES (%s, %s, %s, %s, %s)",
                  (started, _now(), self.folder, json.dumps(files), json.dumps(checked)))
            for k in KINDS:
                c.run("UPDATE store_state SET version = version + 1 WHERE kind = %s", (k,))
        try:        # a note beside the files (they themselves stay as they were): which database they went into
            _write_atomic(os.path.join(self.folder, MOVED_NOTE), json.dumps(
                {"when": started, "where": self.where(), "kind": self.kind, "files": files}, indent=1).encode("utf8"))
        except OSError as e:
            print(f"RightPrice: the note {MOVED_NOTE} could not be written ({e})", file=sys.stderr)
        print(f"RightPrice: the data files in {self.folder} were copied into the database at {self.where()} and checked: "
              + "; ".join(checked["summary"]), file=sys.stderr)
        return {"files": files, "checked": checked}

    def _check_copy(self, c, fs, src):
        """Inside the copying-in transaction: each file read back from the database exactly as the app reads the file,
        and every fabric on the list costed on both, as the app costs it. Anything different and nothing is kept."""
        import masters      # late: masters reads the rate master through this module
        import mill_sheet
        import rate_card
        import yarn_seed

        def fail(what):
            raise Refusal(f"Copying the files in was stopped and nothing was kept: {what}. The files were not changed. "
                          "To go on working meanwhile, remove the app setting DATABASE_URL and restart: the app returns to the files.")

        def as_used(data):          # the tables as the app uses them: read, and brought up to date as masters.load() does
            m = pd.read_excel(io.BytesIO(data), sheet_name=None)
            m = {k: v.copy() for k, v in m.items()}
            rate_card.apply(m)
            yarn_seed.apply(m)
            mill_sheet.apply(m)
            return m
        summary = []
        rates_file = src[FILES["rates"]][0] if FILES["rates"] in src else open(SHIPPED_MASTER, "rb").read()
        if self._rates(c) != rates_file:
            fail("the rate master read back differently")
        summary.append("rate master: the same workbook, byte for byte")
        m_db, m_file = as_used(self._rates(c)), as_used(rates_file)
        a, b = fs.read_list(), _list_frame(*self._list(c))
        try:
            pd.testing.assert_frame_equal(a, b, check_dtype=True)
        except AssertionError as e:
            fail(f"the fabric list read back differently ({str(e).splitlines()[0]})")
        costed, not_costed = 0, 0
        for raw in b.get("Inputs", pd.Series(dtype=object)).dropna():
            try:
                sel = json.loads(raw)
            except ValueError:
                continue
            got = []
            for m in (m_file, m_db):
                try:
                    got.append(masters.cost(dict(sel), m)["total_per_m"])
                except Exception as e:
                    got.append(f"not costed: {e}")
            if got[0] != got[1]:
                fail(f"a fabric on the list ({sel.get('Fabric code')}) costs {got[0]} from the file and {got[1]} from the database")
            costed, not_costed = (costed + 1, not_costed) if isinstance(got[0], float) else (costed, not_costed + 1)
        summary.append(f"fabric list: {len(a)} rows, the same; {costed} costed on both, equal to the paisa"
                       + (f"; {not_costed} not costed on either, for the same reason" if not_costed else ""))
        if self._negos(c) != fs.read_negotiations():
            fail("the negotiation tracker read back differently")
        summary.append(f"tracker: {len(fs.read_negotiations())} fabrics, the same")
        if {r[0] for r in c.all("SELECT quote_id FROM alert_seen")} != {str(i) for i in fs.read_seen()}:
            fail("the alerts marked seen read back differently")
        summary.append(f"alerts seen: {len(fs.read_seen())}, the same")
        if [json.loads(r[0]) for r in c.all("SELECT row FROM cost_sheet_row ORDER BY id")] != fs.read_sheets():
            fail("the mill cost sheets read back differently")
        summary.append(f"mill cost sheets: {len(fs.read_sheets())} rows, the same")
        return {"summary": summary, "equal": True}

    def _baseline(self, c):
        """The files as the database last took them: at the copying in, or when keep_database() was run."""
        kept = c.one("SELECT value FROM store_meta WHERE key = 'files_baseline'")
        r = c.one("SELECT finished_at, files FROM import_run ORDER BY id DESC LIMIT 1")
        if r is None:
            return None, None
        when, ok = r[0], {}
        for f in json.loads(r[1]):
            if f.get("as") != "an earlier rate version":
                ok.setdefault(f["name"], set()).add(f["sha256"])
        if kept:            # keep-database: these hashes too (the files as they were when it was run)
            b = json.loads(kept[0])
            when = b["when"]
            for name, shas in b["files"].items():
                ok.setdefault(name, set()).update(shas if isinstance(shas, list) else [shas])
        return when, ok

    def _files_unchanged(self):
        """After the move the database is the one to work on. If the files have been worked on since (the setting was
        taken off for a while), the app does not start on the database, so neither side's work is lost.
        Not counted as work: a file deleted or moved away, and a rate master that is just the one shipped with the code."""
        when, then = self._read(self._baseline)
        if then is None:
            return
        shipped = {_sha(open(SHIPPED_MASTER, "rb").read())}
        now = {name: sha for name, (_, sha) in self._source_files().items()}
        shipped |= {sha for k, v in then.items() if "(with the code)" in k for sha in v}
        changed = sorted(n for n, sha in now.items() if sha not in then.get(n, set()) and not (n == FILES["rates"] and sha in shipped))
        if changed:
            raise Refusal(
                f"The data files in {self.folder} changed after the database took them on {when} ({', '.join(changed)}): "
                "someone worked on the files while DATABASE_URL was off. So that neither side's work is lost, the app does not "
                "start on the database. Either remove DATABASE_URL and keep working on the files, or keep the database and set "
                "these files aside: run `python store.py keep-database` (Azure: web app > SSH) and restart.")

    def keep_database(self):
        """The database is the one to keep: the files as they are now are taken as seen, and no longer stop the start."""
        now = {name: sha for name, (_, sha) in self._source_files().items()}
        with self.tx(write="import") as c:
            kept = c.one("SELECT value FROM store_meta WHERE key = 'files_baseline'")
            files = {k: (v if isinstance(v, list) else [v]) for k, v in (json.loads(kept[0])["files"] if kept else {}).items()}
            for name, sha in now.items():
                files.setdefault(name, [])
                if sha not in files[name]:
                    files[name].append(sha)
            c.run("DELETE FROM store_meta WHERE key = 'files_baseline'")
            c.run("INSERT INTO store_meta (key, value) VALUES ('files_baseline', %s)", (json.dumps({"when": _now(), "files": files}),))
        return now


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


def store_folder():
    return data_dir()


def _database():
    """The database the setting names, opened only to read or to set the files aside: no tables added, nothing copied in,
    and the files' guard not applied (these are the ways out when it has stopped the app)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is not set: there is no database to work on")
    return SqlStore(url, start=False)


def export(folder, s=None):
    """What the store holds, written as the files the app reads without a database, into a new empty folder."""
    if s is None:
        s = _database() if os.environ.get("DATABASE_URL", "").strip() else FileStore()
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
    elif args == ["keep-database"]:
        kept = _database().keep_database()
        print(f"The database is the one to keep. The files in {store_folder()} as they are now no longer stop the app "
              "starting on it:", ", ".join(kept) or "(none)")
    elif args[:1] in (["status"], []):
        print(json.dumps(get().describe(), indent=1, default=str))
    else:
        raise SystemExit(__doc__)
