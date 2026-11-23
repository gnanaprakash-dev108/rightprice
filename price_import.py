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
SOURCE_DIR = os.path.join(HERE, "data", "price_sources")
STAGE_COLS = ["Date", "Yarn", "Count", "Low Rs/kg", "High Rs/kg", "Source"]

COUNT_RE = re.compile(r"(?<![\d/.])(\d{1,3}/\d{1,3}|\d{1,3})\s*(?:'s|s|ne|nm|d)?(?![\d/.])", re.I)
NUM_RE = re.compile(r"(?<![\d/])(\d{2,4}(?:\.\d+)?)(?![\d/%])")


def empty_stage(rows=8):
    df = pd.DataFrame({c: [None] * rows for c in STAGE_COLS})
    df["Date"] = dt.date.today().isoformat()
    return df


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
            "image_pages": sum(1 for p in pages if len(p.strip()) < 40)}
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


def fetch_link(url, timeout=20):
    """Public web page -> (list of tables, plain text). Pages behind a login will not work."""
    import requests
    from bs4 import BeautifulSoup
    if not re.match(r"^https?://", url):
        url = "https://" + url
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (price reader)"})
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return "pdf", r.content
    try:
        tables = pd.read_html(io.StringIO(r.text))
    except ValueError:
        tables = []
    text = BeautifulSoup(r.text, "lxml").get_text("\n")
    return "html", (tables, text)


def fetch_api(url, header_name=None, header_value=None, timeout=20):
    """JSON endpoint -> flat table. The key is used for this call only and is not stored."""
    import requests
    headers = {header_name: header_value} if header_name and header_value else {}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):  # use the first list found inside the reply
        lists = [v for v in payload.values() if isinstance(v, list)]
        payload = lists[0] if lists else [payload]
    return pd.json_normalize(payload)


def map_columns(df, count_col, low_col, high_col=None, yarn_col=None, date_col=None, source="Upload"):
    out = pd.DataFrame({
        "Date": df[date_col].astype(str) if date_col else dt.date.today().isoformat(),
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
