"""Yarn price intake from any source: Excel/CSV, PDF, image, web link or API.

Every route ends in the same small table (Date, Yarn, Count, Low Rs/kg, High Rs/kg, Source)
that a person reviews before it is added to the market reference. Nothing here
changes the yarn master; that stays a deliberate, manual step.
"""
import datetime as dt
import io
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(os.environ.get("RIGHTPRICE_DATA") or os.path.join(HERE, "data"), "price_sources")
STAGE_COLS = ["Date", "Yarn", "Count", "Low Rs/kg", "High Rs/kg", "Source"]

COUNT_RE = re.compile(r"(?<![\d/.])(\d{1,3}/\d{1,3}|\d{1,3})\s*(?:'s|s|ne|nm|d)?(?![\d/.])", re.I)
NUM_RE = re.compile(r"(?<![\d/])(\d{2,4}(?:\.\d+)?)(?![\d/%])")


def empty_stage(rows=8):
    df = pd.DataFrame({c: [None] * rows for c in STAGE_COLS})
    df["Date"] = dt.date.today().isoformat()
    return df


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
# a phone's or a screen's own name carries the day the picture was taken or sent, not the date of the prices in it
PHONE_NAME = re.compile(r"(?i)(whatsapp|screenshot|screen shot|^img[-_ ]|^image[-_ ]|^photo|^pxl[-_]|^signal-|^vid[-_]|^scan[-_ ]?\d)")


def _day(y, mo, d):
    try:
        day = dt.date(y, mo, d)
    except ValueError:
        return None
    return day if dt.date(2019, 1, 1) <= day <= dt.date.today() else None


def read_dates(text):
    """Every date written in a text (a file name, a circular's first lines), in the order written: a month named in words
    with its year ("Oct 2026", "October'26") as {"kind": "month", "value": "2026-10"}, and a day ("21.11.2026", "21/11/2026"
    and "21-11-2026" day first as in India, "2026-11-21", "21 Nov 2026", "Nov 21, 2026") as {"kind": "day", "value":
    "2026-11-21"}. Only dates from 2019 to today. Stage 5: which of them is the document's date is decided in rules/rates.py."""
    t = str(text or "")
    found, days = [], []
    for m in re.finditer(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d\d)(?!\d)", t):
        days.append((m.start(), m.end(), _day(int(m.group(3)), int(m.group(2)), int(m.group(1))), m.group(0)))
    for m in re.finditer(r"(?<!\d)(20\d\d)-(\d{1,2})-(\d{1,2})(?!\d)", t):
        days.append((m.start(), m.end(), _day(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)))
    for m in re.finditer(r"(?i)(?<![\w])(\d{1,2})(?:st|nd|rd|th)?[\s-]+" + _MONTH_RE + r"\.?,?[\s'-]+(20\d\d)(?!\d)", t):
        days.append((m.start(), m.end(), _day(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1))), m.group(0)))
    for m in re.finditer(r"(?i)\b" + _MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)(?!\d)", t):
        days.append((m.start(), m.end(), _day(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))), m.group(0)))
    taken = [(a, b) for a, b, d, _ in days if d]
    for a, b, d, txt in days:
        if d:
            found.append((a, {"kind": "day", "value": d.isoformat(), "text": txt}))
    for m in re.finditer(r"(?i)\b" + _MONTH_RE + r"\.?(?:[\s-]*(20\d\d)|\s*['\u2019](\d\d))(?![\d/.-])", t):
        if any(a <= m.start() < b for a, b in taken):
            continue            # the month of a day already read
        y = int(m.group(2)) if m.group(2) else 2000 + int(m.group(3))       # a two-digit year only as 'Oct'26
        if _day(y, _MONTHS[m.group(1)[:3].lower()], 1) or (y == dt.date.today().year and _MONTHS[m.group(1)[:3].lower()] == dt.date.today().month):
            found.append((m.start(), {"kind": "month", "value": f"{y:04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}", "text": m.group(0)}))
    return [f for _, f in sorted(found, key=lambda x: x[0])]


def read_date(v):
    """One cell of a date column as an ISO date: a real date, an Excel day number, 2026-09-15, or 15/09/2026, 15.09.2026,
    15-09-2026 (day first, as in India), or a month written as 2026-09 or Sep 2026. None when blank or unreadable."""
    if v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "NaT", "nan", "None"):
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return (v.date() if isinstance(v, dt.datetime) else v).isoformat()
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime().date().isoformat()
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    t = str(v).strip()
    m = re.fullmatch(r"(20\d\d)-(\d{1,2})(?:-(\d{1,2}))?(?:[ T]00:00(?::00)?)?", t)
    if m:
        if m.group(3) is None:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}" if 1 <= int(m.group(2)) <= 12 else None
        d = _day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.isoformat() if d else None
    got = read_dates(t)
    return got[0]["value"] if len(got) == 1 else None


def find_date(text):
    """The first day written in a text, or None (kept for callers that want one day; the intake decides with read_dates)."""
    d = next((x["value"] for x in read_dates(text) if x["kind"] == "day"), None)
    return d


def keep_file(name, data):
    """Keep a copy of the source document so a rate can be traced back to it."""
    os.makedirs(SOURCE_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    path = os.path.join(SOURCE_DIR, f"{dt.datetime.now():%Y%m%d-%H%M%S} {safe}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def rows_from_text(text, source, lo=100, hi=2000):
    """Best-effort reading of price lines such as '40s combed compact 343 - 358'.

    A line is used when it has a count and one or two numbers in the Rs/kg range.
    The result always needs a human check.
    """
    out = []
    for line in str(text).splitlines():
        line = line.strip()
        if len(line) < 4:
            continue
        m = COUNT_RE.search(line)
        if not m:
            continue
        rest = re.sub(r"(\d{3,4})\s*/\s*(\d{3,4})", r"\1 - \2", line[m.end():])   # '307/314' is a range
        nums = [float(n) for n in NUM_RE.findall(rest) if lo <= float(n) <= hi]
        if not nums:
            continue
        label = re.sub(r"[\d.,/\-–]+|\bto\b|\brs\b", " ", rest, flags=re.I)
        label = re.sub(r"\s+", " ", label).strip(" :|-")
        out.append({"Date": dt.date.today().isoformat(), "Yarn": label[:60] or None,
                    "Count": m.group(0).strip(), "Low Rs/kg": min(nums[:2]), "High Rs/kg": max(nums[:2]),
                    "Source": source})
    return pd.DataFrame(out, columns=STAGE_COLS)


def read_pdf(data, source):
    """Text PDFs are parsed; scanned PDFs return no rows and say so."""
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = [page.get_text() for page in doc]
    text = "\n".join(pages)
    info = {"pages": doc.page_count, "characters": len(text.strip()),
            "image_pages": sum(1 for p in pages if len(p.strip()) < 40),
            "dates": read_dates(text[:4000])}          # the dates in the circular's first lines (rules/rates.py decides)
    if info["characters"] < 40 * max(1, doc.page_count):
        info["scanned"] = True
        return pd.DataFrame(columns=STAGE_COLS), info
    info["scanned"] = False
    return rows_from_text(text, source), info


def pdf_page_image(data, page=0, dpi=110):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    return doc[page].get_pixmap(dpi=dpi).tobytes("png")


def read_table_file(name, data):
    """Excel or CSV -> dict of sheet name -> DataFrame."""
    if name.lower().endswith(".csv"):
        return {"CSV": pd.read_csv(io.BytesIO(data))}
    return pd.read_excel(io.BytesIO(data), sheet_name=None)


def _addresses(host, port):
    """Every address a host name stands for (the one DNS lookup made for a fetch)."""
    import socket
    return [i[4][0] for i in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _public_ip(text):
    """Whether an address is on the public internet: not this machine, a private network, link-local (169.254.x, where
    the cloud's metadata and identity endpoints answer), multicast or reserved."""
    import ipaddress
    ip = ipaddress.ip_address(str(text).split("%", 1)[0])
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def _target(url):
    """Where a fetch of this address goes: (scheme, host, port, path with query, the checked IP to connect to); or
    ValueError with the words of the refusal. RULE: Bring in prices reads public web addresses only, over http or https:
    never this machine, a private network, a link-local address or this site's own address. The address is read once,
    and must read the same to Python's parser and to urllib3 (the library that connects): a backslash, a user name or
    password before the host, spaces or control characters are refused, so no address can mean one host to the check
    and another to the connection. The host name is looked up once, every address it gives must be public, and the
    connection is made to the address checked (so the name cannot be pointed elsewhere between the check and the fetch)."""
    from urllib.parse import urlsplit
    from urllib3.util import parse_url
    text = str(url or "").strip()
    if not text or "\\" in text or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("That is not a web address RightPrice reads (no backslashes, spaces or control characters).")
    try:
        p, q = urlsplit(text), parse_url(text)
        host, port = (p.hostname or "").lower().rstrip("."), p.port
    except ValueError:
        raise ValueError("That is not a web address.")
    if p.scheme.lower() not in ("http", "https") or not host:
        raise ValueError("Only web addresses starting http:// or https:// are read.")
    if "@" in p.netloc or p.username or p.password or q.auth:
        raise ValueError("An address with a user name or password before the host is not read.")
    if (q.host or "").lower().strip("[]").rstrip(".") != host.strip("[]") or q.port != port or (q.scheme or "").lower() != p.scheme.lower():
        raise ValueError("That address reads differently to the parts of RightPrice that check it and that connect to it, so it is not read.")
    own = (os.environ.get("WEBSITE_HOSTNAME") or "").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or (own and host == own):
        raise ValueError(f"{host} is not a public address: Bring in prices reads public pages only.")
    port = port or (443 if p.scheme.lower() == "https" else 80)
    try:
        found = _addresses(host.strip("[]"), port)
    except (OSError, UnicodeError, ValueError):
        raise ValueError(f"{host} could not be found.")
    if not found or not all(_public_ip(a) for a in found):
        raise ValueError(f"{host} is not a public address (this machine, a private network, or the cloud's own link-local network): "
                         "Bring in prices reads public pages only.")
    return p.scheme.lower(), host.strip("[]"), port, (p.path or "/") + (f"?{p.query}" if p.query else ""), found[0]


def not_public(url):
    """Why RightPrice will not fetch this address (the words), or None. See _target."""
    try:
        _target(url)
    except ValueError as e:
        return str(e)
    return None


class _Reply:
    """What a fetch got: its status, headers and body (the parts of a requests response the readers use)."""

    def __init__(self, status, headers, content):
        self.status_code, self.headers, self.content = status, headers, content

    @property
    def text(self):
        import re as _re
        hit = _re.search(r"charset=([\w.-]+)", self.headers.get("content-type", ""), _re.I)
        try:
            return self.content.decode(hit.group(1) if hit else "utf-8", errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self):
        import json as _json
        return _json.loads(self.text)


MAX_FETCH = 20 * 1024 * 1024        # a price page or reply larger than this is not read


def _get(url, headers=None, timeout=20):
    """GET a public address, connecting to the address checked by _target (never a second lookup), following where it
    sends RightPrice on at most five times, each checked the same way. A header given by the person goes to the first
    host only. No proxy is used: the connection goes straight to the checked address."""
    import certifi
    import urllib3
    from urllib.parse import urljoin
    first = None
    for _ in range(6):
        scheme, host, port, path, ip = _target(url)           # ValueError: refused, with the words
        first = first or host
        mine = (headers or {}) if host == first else {}
        default = (scheme, port) in (("https", 443), ("http", 80))
        hosted = (f"[{host}]" if ":" in host else host) + ("" if default else f":{port}")
        if scheme == "https":
            pool = urllib3.HTTPSConnectionPool(ip, port, server_hostname=host, assert_hostname=host, cert_reqs="CERT_REQUIRED",
                                               ca_certs=certifi.where(), timeout=timeout, retries=False, maxsize=1)
        else:
            pool = urllib3.HTTPConnectionPool(ip, port, timeout=timeout, retries=False, maxsize=1)
        try:
            r = pool.urlopen("GET", path, headers=dict({"Host": hosted, "User-Agent": "Mozilla/5.0 (price reader)", "Accept-Encoding": "identity"}, **mine),
                             redirect=False, preload_content=False, assert_same_host=False)
            body = r.read(MAX_FETCH + 1, decode_content=True)
            r.release_conn()
        finally:
            pool.close()
        if len(body) > MAX_FETCH:
            raise ValueError("the page is larger than 20 MB")
        hd = {k.lower(): v for k, v in r.headers.items()}
        if r.status in (301, 302, 303, 307, 308) and hd.get("location"):
            url = urljoin(url, hd["location"])
            continue
        if r.status >= 400:
            raise ValueError(f"the address answered {r.status}")
        return _Reply(r.status, hd, body), url
    raise ValueError("the page sends RightPrice on too many times")


def fetch_link(url, timeout=20):
    """Public web page -> (list of tables, plain text). Pages behind a login will not work."""
    from bs4 import BeautifulSoup
    if not re.match(r"^https?://", url):
        url = "https://" + url
    r, url = _get(url, timeout=timeout)
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return "pdf", r.content
    try:
        tables = pd.read_html(io.StringIO(r.text), flavor="lxml")
    except (ValueError, ImportError):            # no table on the page (or none lxml can read)
        tables = []
    text = BeautifulSoup(r.text, "lxml").get_text("\n")
    return "html", (tables, text)


def fetch_api(url, header_name=None, header_value=None, timeout=20):
    """JSON endpoint -> flat table. The key is used for this call only and is not stored."""
    headers = {header_name: header_value} if header_name and header_value else {}
    r, _ = _get(url, headers=headers, timeout=timeout)
    payload = r.json()
    if isinstance(payload, dict):  # use the first list found inside the reply
        lists = [v for v in payload.values() if isinstance(v, list)]
        payload = lists[0] if lists else [payload]
    return pd.json_normalize(payload)


def map_columns(df, count_col, low_col, high_col=None, yarn_col=None, date_col=None, source="Upload"):
    out = pd.DataFrame({
        "Date": df[date_col].map(read_date) if date_col else dt.date.today().isoformat(),     # day first, Excel dates; blank: None
        "Yarn": df[yarn_col].astype(str) if yarn_col else None,
        "Count": df[count_col].astype(str),
        "Low Rs/kg": pd.to_numeric(df[low_col], errors="coerce"),
        "High Rs/kg": pd.to_numeric(df[high_col if high_col else low_col], errors="coerce"),
        "Source": source,
    })
    return out.dropna(subset=["Low Rs/kg"])[STAGE_COLS].reset_index(drop=True)


def clean_stage(df):
    """Rows a reviewer kept: a count and a low rate are the minimum."""
    df = df.copy()
    for c in ("Low Rs/kg", "High Rs/kg"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["Count"].notna() & (df["Count"].astype(str).str.strip() != "") & df["Low Rs/kg"].notna()]
    df["High Rs/kg"] = df["High Rs/kg"].fillna(df["Low Rs/kg"])
    return df[STAGE_COLS].reset_index(drop=True)
