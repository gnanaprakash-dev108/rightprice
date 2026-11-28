"""Checks the screens in a browser: every page of the shell opens, in light and dark and at phone width, with no error
in the browser's console, the main paths work, and each role is offered only what it may do.

Run: python check_browser.py     It must print ALL OK. It needs Python's playwright package and its Chromium
(on GitHub: pip install playwright; python -m playwright install --with-deps chromium).

What it does: starts the app on a temporary data folder and a SQLite file in it (the rate master that comes with the
code; nothing in data/ is touched, and DATABASE_URL from the environment is never used), then in Chromium, each page and
each path opened in a fresh tab (a first load, as from a bookmark or a reload). First the purchase file that came with
the code is loaded through the app (stage 2's purchase history), so every page is checked with it in place.
1. every page of the shell (Home, Prices, Right cost, a fabric's page, a supplier's page, a setup list) and every tab of the
   New cost popup, in light and in dark at 1366 x 900 and in light at 390 x 844: it draws (nothing left on "Loading...",
   no "could not be loaded"), carries its heading or its tab, shows the theme's colours (computed, not only the switch),
   on a phone nothing reaches past the screen's edge (the page, its own box, or a part cut off where it cannot be
   scrolled to), and the console stays empty; and stage 2's screens in the same three looks: a Fab group opened from
   Right cost's Fab group column (its chart drawn, its codes listed), the price popup from the same row (its chart with
   the group's other codes; Escape closes it), the list of Fab groups and Purchase files; the Fab library (GP, 28 Nov
   2026: a list made of the deployed extract loaded first) found by a code, and a code's page;
2. the main paths: Create cost (the example, Qlty-1, is Rs 181.40, with the rates it is on under the figure; Add to list
   adds a row; Print prints the cost alone, the cost in light colours and the shell left in its theme); Bulk upload (a
   mill sheet's rows, its alert and the rail's count); a row opened in Create cost at the list's should-cost; Compare of
   two ticked rows, each side at its row's should-cost; the pack of the ticked rows and its A4 landscape print (the pack
   alone in light colours); a Right cost row opened in Create cost, from the fabric's page and from its Negotiation tab,
   at the row's should-cost; the keys (Ctrl+F is the browser's find except on the list; Escape closes a chart's tooltip
   before the popup); the supplier page and a Prices page printing at their own type size with no other page's print
   rules; a rate table saved; prices brought in; a cotton price added (with Enter); a mill cost sheet's draft applied
   (and after it every page answers at once: Right cost is worked out again in the background);
   the rate master's lists read afresh for each popup (a yarn added since shows without a reload); stage 5's dated yarn
   rates (a rate entered on Yarn prices shows in its card and moves the purchase orders of its month, and no other;
   Bring in prices adds its rows as dated rates after asking the month and GST); a bookmark of the retired /classic;
   stage 2: a purchase order's price popup from its page and the Fab group from the popup, a code's popup from the
   group's page, a group found on the list of Fab groups, an upload's detail on Purchase files and the purchase file
   loaded again from that page (read in the background, changing nothing); the usual range over time: the group page's
   slider and the popup's (a period chosen works the figures out again, every purchase stays on the chart); the Fab
   library: a code found, its page and its Fab group, a list uploaded from the page;
3. with users and roles on (stage 3): a Viewer, a Buyer, a Rates editor and an Admin each see only the buttons their role
   may use; each walks every address (every page, every tab of the popup, Right cost, a fabric's page, a supplier's
   page, a setup list, Users and roles, a Fab group, the list of Fab groups, Purchase files, the Fab library): what the role may open draws, what it may not says so, the menus offer exactly
   what it may open, and the server is asked for nothing it refuses; and the same walk for a Buyer with each page
   unticked in turn.
A crash fails the run like any check, and whenever something failed the data folder and the servers' logs are kept.
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DESK, PHONE = {"width": 1366, "height": 900}, {"width": 390, "height": 844}
# the pages of the shell: address, the heading it shows
PAGES = [("dashboard", "Dashboard"), ("pilot", "Pilot results"), ("yarn", "Yarn prices"), ("cotton", "Cotton prices"),
         ("intake", "Bring in prices"), ("rates", "Rate tables"), ("ratecard", "Mill rate card"), ("settings", "Calculation settings"),
         ("costsheets", "Mill cost sheets"), ("fx", "Exchange rates")]
POPUP_TABS = [("cost", "Create cost"), ("bulk", "Bulk upload"), ("compare", "Compare"), ("pack", "Negotiation pack")]
# the colours each theme gives (computed): the page's background, a page's text, a card
THEME = {"light": ("rgb(246, 244, 238)", "rgb(29, 37, 33)", "rgb(255, 255, 255)"), "dark": ("rgb(15, 21, 19)", "rgb(232, 237, 233)", "rgb(22, 30, 27)")}
# the browser may be offline from the web font; that is not a fault of the app
IGNORE = ("fonts.googleapis.com", "fonts.gstatic.com")
DRAWN = """sel => { const r = document.querySelector(sel); return !!r && r.textContent.trim() !== 'Loading...' && r.children.length > 0 }"""
# how far anything reaches past what can be seen or scrolled to, with where: the document or the page's own box scrolling
# sideways; the box, or what holds it, past the screen's edge (the shell would cut it off); a part of the page cut off by
# something that hides what overflows it (a part that scrolls, or ends in "...", is reachable)
SIDEWAYS = """sel => { const b = document.querySelector(sel); if (!b) return [0, ''];
  let worst = [Math.max(document.documentElement.scrollWidth - innerWidth, b.scrollWidth - b.clientWidth), 'scrolls sideways'];
  const more = (v, what) => { if (v > worst[0]) worst = [v, what]; };
  for (let e = b; e && e !== document.body; e = e.parentElement) { const r = e.getBoundingClientRect(); more(r.right - innerWidth, 'past the right edge: ' + e.className); more(-r.left, 'past the left edge: ' + e.className); }
  for (const el of b.querySelectorAll('*')) {
    if (el.closest('svg')) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    for (let a = el.parentElement; a && a !== b; a = a.parentElement) {
      const cs = getComputedStyle(a), ox = cs.overflowX;
      if (ox === 'auto' || ox === 'scroll' || cs.textOverflow === 'ellipsis') break;
      if (ox === 'hidden' || ox === 'clip') { const ar = a.getBoundingClientRect(), what = 'cut off: ' + el.tagName.toLowerCase() + '.' + el.className + ' in .' + a.className;
        more(r.right - ar.right, what); more(ar.left - r.left, what); break; }
    }
  }
  return [Math.round(worst[0]), worst[1]]; }"""
PAGE_RULES = """() => [...document.styleSheets].some(ss => { try { return [...ss.cssRules].some(r => r instanceof CSSPageRule ||
    (r instanceof CSSMediaRule && [...r.cssRules].some(x => x instanceof CSSPageRule))); } catch (e) { return false; } })"""
# an element's own text and its type size on screen, in px
TYPE = """sels => sels.map(s => { const e = document.querySelector(s); if (!e) return [s, '', 0];
    return [s, [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(), parseFloat(getComputedStyle(e).fontSize)] })"""
# what each address needs (GP's permissions, rules/access.py): the shell's pages, and the New cost popup's tabs; a page
# or tab not named here needs nothing. Written out here, not read from web/access.js, so a wrong need there shows.
NEEDS = {"dashboard": "page:dashboard", "pilot": "page:pilot", "yarn": "page:prices", "cotton": "page:prices", "rates": "page:prices",
         "ratecard": "page:prices", "settings": "page:prices", "costsheets": "page:costsheets", "intake": "do:edit_rates",
         "rightcost": "page:rightcost", "item": "page:rightcost", "supplier": "page:rightcost", "users": "page:users",
         "cost": "page:cost", "compare": "page:cost", "bulk": "page:list", "pack": "page:pack",
         "group": "page:groups", "groups": "page:groups", "purchase-files": "page:purchase_files",         # stage 2 (web/purchases.js)
         "fab-library": "page:fab_library",                                                               # the Fab library (web/library.js)
         "purchase-lines": "page:purchase_lines", "fx": "page:prices"}                                     # every purchase line; Prices > Exchange rates
# what the menus offer: the Prices links, the sections' tabs above a page, the popup's tabs
OFFERED = """() => [...CONFIG.flyouts.prices.groups.flatMap(g => g[1]).map(x => x[1].slice(1)).filter(x => !x.startsWith('lib/')),
    ...Object.values(CONFIG.sections).flat(), ...CONFIG.popupTabs.map(t => t[0])]"""
# how many of these elements have a box drawn round them (a border or a background): stage 2's .note stays on its pages
BOXED = """sel => [...document.querySelectorAll(sel)].map(e => getComputedStyle(e)).filter(c => c.borderTopWidth !== '0px' || c.backgroundColor !== 'rgba(0, 0, 0, 0)').length"""
# records whether Ctrl+F reached the browser (not prevented), and stands in for the print dialog
INIT = """addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") setTimeout(() => { window.__ctrlF = e.defaultPrevented; }); });
window.__printed = 0; window.print = () => { window.__printed++; };"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mill_sheet_file():
    """A mill's price sheet as it comes (the headings of mill_sheet.COLUMNS): two costed rows and one NYD row."""
    import pandas as pd
    import mill_sheet
    base = {"Brand": "AS", "Fab Code": "B-1", "YD/NYD": "YD", "Material Type": "100% Cotton", "Warp": 40, "Weft": 40,
            "EPI": 136, "PPI": 90, "Variety": "YDS", "Weave": "2/1 RHT", "F.W.": 145, "Finish": "Normal",
            "Arvind Ref": "x/1", "Total order qnty": 2255, "Base Price": 164, "Std EPI": 122, "Std PPI": 76,
            "Actual EPI": 136, "Actual PPI": 90, "Diff EPI": 14, "Diff PPI": 14, "EPI Upch": 8.4, "PPI Upch": 12.6,
            "Finish Upch": 0, "Dobby Upch": 0, "Upcharge/Print/Mcount": 0, "Double beam": 0, "Price": 185,
            "Upcharge for less qnty": 0, "Discoun>2000 mts": 0, "Total price with qnty disc/upcharge": 185,
            "Ex mill price": 185, "C2FO @2.84%": 190.254}
    hi = {"Price": 240, "Ex mill price": 240, "Total price with qnty disc/upcharge": 240, "Total order qnty": 5000}
    rows = [base, dict(base, **hi, **{"Fab Code": "B-2", "EPI": 144}), dict(base, **{"Fab Code": "B-3", "YD/NYD": "NYD"})]
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
    return buf.getvalue()


def cost_sheet_file(template):
    """Two mills' cost sheets on the template, differing from the rate master on overhead (as check_server.build does)."""
    import pandas as pd
    cs = pd.read_excel(io.BytesIO(template), sheet_name="Cost sheet")
    cs.loc[0, "Overhead %"] = 6
    cs.loc[0, "Mill"] = "Mill A"
    cs2 = cs.copy()
    cs2["Mill"] = "Mill B"
    cs2.loc[0, "Overhead %"] = 8
    buf = io.BytesIO()
    pd.concat([cs, cs2]).to_excel(buf, index=False)
    return buf.getvalue()


def _pdf(data):
    try:
        import pymupdf as fitz
    except ImportError:          # an older PyMuPDF
        import fitz
    return fitz.open(stream=data, filetype="pdf")


def pdf_text(data):
    """The pages of a PDF: (count, landscape?, text)."""
    doc = _pdf(data)
    return doc.page_count, all(p.rect.width > p.rect.height for p in doc), "\n".join(p.get_text() for p in doc)


def type_on_paper(page, sels):
    """Each element's type on paper against its size on screen (a px is 0.75 pt), printed on paper as wide as the screen
    so the browser has no cause to shrink the page to fit: what is printed smaller or larger (a zoom, a scale, another
    size in print) is listed, as is an element not found."""
    want = page.evaluate(TYPE, sels)
    doc = _pdf(page.pdf(width=f"{DESK['width']}px", height="2000px", margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}))
    spans = [(s["text"].strip(), s["size"]) for p in doc for b in p.get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]
    off = []
    for sel, text, px in want:
        # the spans of that text (the same words may print elsewhere too): one of them at the size on screen
        got = sorted({round(size, 2) for t, size in spans if text and t and (t[:20] == text[:20] or (len(t) >= 6 and text.startswith(t)))})
        if not any(abs(g - px * 0.75) <= 0.1 for g in got):
            off.append(f"{sel} {text[:20]!r}: {got or 'not found'} pt on paper against {px * 0.75:g} pt")
    return off


def load_shipped(app):
    """Stage 2: the purchase file that came with the code, loaded through the app (read in the background); its upload
    once it is read, and Right cost's rows worked out again with it."""
    up = app.api("/api/purchases/load-shipped", {})
    for _ in range(600):
        u = app.api(f"/api/purchases/uploads/{up['id']}")
        if u["status"] in ("done", "failed"):
            app.costs()
            return u
        time.sleep(1)
    return {"status": "still being read after 10 minutes"}


def post_file(app, path, name, data):
    """A file sent as the page sends it (multipart form), its answer."""
    import uuid
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(app.base + path, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def load_library(app):
    """The Fab library: a PLM fabric code list made of the extract deployed with the code (its 19,669 codes, as they are, so
    nothing in the purchase history changes), uploaded through the app as an admin would and read in the background."""
    import pandas as pd
    plm = pd.read_csv(os.path.join(HERE, "data", "plm_specs_for_po.csv"), dtype=str).fillna("")
    up = post_file(app, "/api/fab-library/upload", "PLM list, as deployed.csv", plm.to_csv(index=False).encode("utf-8-sig"))
    for _ in range(900):
        u = app.api(f"/api/fab-library/uploads/{up['id']}")
        if u["status"] == "failed" or (u["status"] == "done" and (u["summary"] or {}).get("regroup")):
            app.costs()
            return u
        time.sleep(1)
    return {"status": "still being read after 15 minutes"}


def rich_row(app):
    """A purchase order of Right cost in the Fab group with the most codes (and purchases): its code and its group. The
    group page and the price popup then have other codes and many dots to draw."""
    groups = {g["code"]: g for g in app.api("/api/groups")["groups"]}
    po = [r for r in app.costs() if r["source"] == "Purchase orders" and r.get("fab_group") in groups and r.get("price") is not None]
    if not po:
        return None
    r = min(po, key=lambda r: (-groups[r["fab_group"]]["codes"], -groups[r["fab_group"]]["purchases"], r["code"]))
    return {"code": r["code"], "group": r["fab_group"], "codes": groups[r["fab_group"]]["codes"]}


class App:
    """The app on a free port, on the given data folder, with extra settings; stopped by stop()."""

    def __init__(self, data, extra=None):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "RIGHTPRICE_DATA", "ANTHROPIC_API_KEY", "RIGHTPRICE_MCP_TOKEN",
                                                                "RIGHTPRICE_ADMINS", "WEBSITE_SITE_NAME", "WEBSITE_AUTH_ENABLED")}
        # what we usually pay rests on the last 12 months ending today (GP, 28 Nov 2026): today fixed, so the pages read the same whenever this runs
        env.setdefault("RIGHTPRICE_TODAY", "2026-11-28")
        env.update(RIGHTPRICE_DATA=data, DATABASE_URL=f"sqlite:///{os.path.join(data, 'rightprice.db')}", PYTHONUNBUFFERED="1", **(extra or {}))
        self.log = open(os.path.join(data, f"server-{self.port}.log"), "w")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(self.port)],
                                     cwd=HERE, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(240):
            try:
                if urllib.request.urlopen(self.base + "/api/me", timeout=5).status == 200:
                    return
            except OSError:
                time.sleep(0.5)
        self.stop()
        raise RuntimeError("The app did not start: see " + self.log.name)

    def api(self, path, body=None, who=None, method=None):
        headers = {"Content-Type": "application/json"}
        if who:
            headers["X-MS-CLIENT-PRINCIPAL-NAME"] = who
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers,
                                     method=method or ("GET" if body is None else "POST"))
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if r.headers.get("content-type", "").startswith("application/json") else raw

    def costs(self, who=None):
        """Right cost's rows once their verdicts are worked out (in the background after a start or a change of rates;
        until then the dated rates' months wait for them too)."""
        for _ in range(240):
            d = self.api("/api/costs", who=who)
            if d["ready"]:
                return d["rows"]
            time.sleep(1)
        raise RuntimeError("Right cost's verdicts were not ready after 4 minutes")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def main():
    sys.path.insert(0, HERE)
    import masters
    from playwright.sync_api import sync_playwright

    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    data = tempfile.mkdtemp(prefix="rightprice-browser-")
    files = {"sheet": os.path.join(data, "mill sheet.xlsx"), "prices": os.path.join(data, "yarn prices.csv"), "costsheet": os.path.join(data, "cost sheets.xlsx")}
    app = None
    try:
        with open(files["sheet"], "wb") as f:
            f.write(mill_sheet_file())
        with open(files["prices"], "w") as f:
            f.write("Count,Rate,Yarn\n40s,352,Combed compact\n60s,430,Combed compact\n")
        app = App(data)
        check("The app starts on a temporary folder and SQLite", app.api("/api/store")["store"] == "sqlite")
        with open(files["costsheet"], "wb") as f:
            f.write(cost_sheet_file(app.api("/api/costsheet/template")))
        # stage 2: the purchase history, as on the live site once GP loads it: the purchase file that came with the code,
        # read in the background; every page below is checked with it in place
        shipped = load_shipped(app)
        rich = rich_row(app)
        check("Stage 2: the purchase file that came with the code loads through the app, and Right cost's purchase orders carry their Fab group",
              shipped["status"] == "done" and shipped["rows_loaded"] and rich, f"{shipped.get('status')} {shipped.get('error') or ''} {rich}")
        n_groups = app.api("/api/groups")["counts"]["groups"]
        library = load_library(app)
        check("The Fab library: a PLM fabric code list (the deployed extract's codes) loads through the app, and the Fab groups stay as they were",
              library["status"] == "done" and library["codes_total"] == 19669 and app.api("/api/groups")["counts"]["groups"] == n_groups,
              f"{library.get('status')} {library.get('error') or ''} {library.get('codes_total')}")
        where = {"group": "group/" + rich["group"]}           # a fabric's page, a supplier's page and a Fab group, for the walks of section 3
        with sync_playwright() as p:
            browser = p.chromium.launch()

            def tab(theme="light", size=DESK, who=None):
                """A fresh tab: its own context (nothing kept from another tab), the console watched."""
                ctx = browser.new_context(viewport=size, device_scale_factor=1, extra_http_headers={"X-MS-CLIENT-PRINCIPAL-NAME": who} if who else None)
                ctx.add_init_script(f"try {{ localStorage.setItem('rp-theme', '{theme}'); }} catch (e) {{}}\n" + INIT)
                page = ctx.new_page()
                page.errors = []
                page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" and not any(x in (m.text + str(m.location)) for x in IGNORE) else None)
                page.on("pageerror", lambda e: page.errors.append(str(e)))
                page.set_default_timeout(30000)
                return page

            def open_at(page, address, where=".pgbox > .pg"):
                """Load the app afresh at this address (a full load, as a bookmark), and wait for the page to draw."""
                page.goto(f"{app.base}/?at={time.time()}#{address}")
                if where:
                    try:
                        page.wait_for_function(DRAWN, arg=where, timeout=60000)
                        page.wait_for_timeout(500)
                    except Exception as e:  # noqa: BLE001 - reported by the check that follows
                        page.errors.append(f"never drew: {e}")

            def colours(page, theme, sel):
                got = page.evaluate("""sel => { const pg = document.querySelector(sel), card = pg && pg.querySelector('.card, .pack-tile, .pane-in');
                    return [getComputedStyle(document.body).backgroundColor, pg ? getComputedStyle(pg).color : '', card ? getComputedStyle(card).backgroundColor : null] }""", sel)
                want = THEME[theme]
                return got[0] == want[0] and got[1] == want[1] and (got[2] is None or got[2] == want[2]), got

            def stage2_colours(page, theme, sel, card):
                """Stage 2's pages draw straight into the shell's page (no box of their own), and the price popup over it:
                the theme's colours on the page, its text and its tiles."""
                got = page.evaluate("""([sel, card]) => { const el = document.querySelector(sel), c = card && document.querySelector(card);
                    return [getComputedStyle(document.body).backgroundColor, getComputedStyle(el).color, c ? getComputedStyle(c).backgroundColor : null,
                            sel === '.main' ? null : getComputedStyle(el).backgroundColor] }""", [sel, card])
                want = THEME[theme]
                return got[0] == want[0] and got[1] == want[1] and got[2] in (None, want[2]) and got[3] in (None, want[2]), got

            def right_cost_row(page, code, fresh=True):
                """Right cost found by a code in its search box (a fresh load at #rightcost first): that code's row."""
                if fresh:
                    open_at(page, "rightcost", None)
                    page.wait_for_selector(".grid tbody tr td .code")
                    page.fill("#search", code)
                    page.press("#search", "Enter")
                page.wait_for_function("c => [...document.querySelectorAll('.grid tbody tr')].some(tr => tr.textContent.includes(c) && tr.querySelector('.fgcell'))", arg=code)
                return page.locator(".grid tbody tr", has_text=code).first

            active_rail = lambda page: page.evaluate("() => [...document.querySelectorAll('.rail .item.active')].map(b => b.dataset.id)")

            # ---------------------------------------------------------------- 1. every page, in each look
            for theme, size, look in (("light", DESK, "light"), ("dark", DESK, "dark"), ("light", PHONE, "phone")):
                for addr, heading in PAGES:
                    page = tab(theme, size)
                    open_at(page, addr)
                    txt = page.inner_text(".pgbox")
                    title = page.inner_text(".main .title") if page.locator(".main .title").count() else ""
                    wide = page.evaluate(SIDEWAYS, ".pgbox") if size is PHONE else [0, ""]
                    hue, got = colours(page, theme, ".pgbox > .pg")
                    good = not page.errors and "could not be" not in txt and title == heading and wide[0] <= 1 and hue
                    check(f"{heading} opens ({look})", good, "" if good else f"heading {title!r}, sideways {wide}, colours {got}, console {page.errors[:3]}, text {txt[:100]!r}")
                    page.context.close()
                for tab_id, label in POPUP_TABS:
                    page = tab(theme, size)
                    open_at(page, f"dashboard?new={tab_id}", ".popup .pgbox > .pg")
                    on = page.locator(".popup .ptab.on").inner_text() if page.locator(".popup .ptab.on").count() else ""
                    txt = page.inner_text(".popup .pgbox")
                    if tab_id == "pack" and txt.startswith("The list is empty"):
                        # with nothing in the list the server refuses a pack (400) and the page says why: that refusal is expected
                        page.errors = [e for e in page.errors if "status of 400" not in e]
                    wide = page.evaluate(SIDEWAYS, ".popup .pgbox") if size is PHONE else [0, ""]
                    hue, got = colours(page, theme, ".popup .pgbox > .pg")
                    good = not page.errors and on == label and "could not be" not in txt and wide[0] <= 1 and hue
                    check(f"New cost > {label} opens ({look})", good, "" if good else f"tab {on!r}, sideways {wide}, colours {got}, console {page.errors[:3]}, text {txt[:100]!r}")
                    page.context.close()
                page = tab(theme, size)
                open_at(page, "rightcost", None)
                page.wait_for_selector(".grid tbody tr td .code")
                page.wait_for_timeout(500)
                wide = page.evaluate(SIDEWAYS, ".main")
                check(f"Right cost lists the costings ({look})", not page.errors and page.locator(".grid tbody tr").count() >= 50 and wide[0] <= 1, f"{wide} {page.errors[:3]}")
                page.locator(".grid tbody tr td .code").first.click()
                page.wait_for_selector(".dhead h1")
                wide = page.evaluate(SIDEWAYS, ".main")
                check(f"A fabric's page opens ({look})", not page.errors and page.locator(".main .tabs .tab").count() == 4 and wide[0] <= 1, f"{wide} {page.errors[:3]}")
                page.context.close()
                page = tab(theme, size)
                open_at(page, "lib/Payment terms", None)
                page.wait_for_selector(".main .title")
                check(f"A setup list opens ({look})", not page.errors and page.inner_text(".main .title") == "Payment terms", str(page.errors[:3]))
                page.context.close()

                # stage 2 (web/purchases.js), in the shell with no frame: a Fab group opened from Right cost's Fab group column,
                # the price popup from the same row, the list of Fab groups, Purchase files
                page = tab(theme, size)
                row = right_cost_row(page, rich["code"])
                link = row.locator(".fgcell button.code")
                in_cell = link.inner_text()
                link.click()
                page.wait_for_function("g => (document.querySelector('.main .dhead h1') || {}).textContent === g", arg=in_cell)
                page.wait_for_selector(".main .pchart svg circle.dotm")
                page.wait_for_timeout(400)
                dots = page.locator(".main .pchart svg circle.dotm").count()
                wide = page.evaluate(SIDEWAYS, ".main") if size is PHONE else [0, ""]
                hue, got = stage2_colours(page, theme, ".main", ".main .stile")
                good = (in_cell == rich["group"] and page.inner_text(".main .dhead h1") == rich["group"] and page.url.endswith("#group/" + rich["group"])
                        and "the last 12 months" in page.inner_text(".main .pbar .pwords")
                        and page.title() == rich["group"] + " - RightPrice" and active_rail(page) == ["costs"] and dots >= 2
                        and rich["code"] in page.inner_text(".main") and not page.errors and wide[0] <= 1 and hue)
                check(f"Stage 2: a Fab group opens from Right cost's Fab group column, its chart drawn and its codes listed ({look})", good,
                      "" if good else f"cell {in_cell!r}, {page.url}, {page.title()!r}, rail {active_rail(page)}, {dots} dots, sideways {wide}, colours {got}, console {page.errors[:3]}")
                page.go_back()
                row = right_cost_row(page, rich["code"], fresh=False)
                row.locator(".fgcell .pib").click()
                page.wait_for_selector(".pdialog .pchart svg circle.dotm")
                page.wait_for_timeout(400)
                dots = page.locator(".pdialog .pchart svg circle.dotm").count()
                head = page.inner_text(".pdialog .phead h2")
                wide = page.evaluate(SIDEWAYS, ".pdialog") if size is PHONE else [0, ""]
                hue, got = stage2_colours(page, theme, ".pdialog", ".pdialog .stile")
                page.keyboard.press("Escape")
                page.wait_for_function("() => !document.querySelector('.pdialog')")
                good = head == "Price over time: " + rich["code"] and dots >= 2 and page.locator(".pdialog .stile").count() == 0 and not page.errors and wide[0] <= 1 and hue
                check(f"Stage 2: the price popup opens from the same row, its chart drawn with the group's other codes, and Escape closes it ({look})", good,
                      "" if good else f"{head!r}, {dots} dots, sideways {wide}, colours {got}, console {page.errors[:3]}")
                page.context.close()
                # the Fab library (web/library.js): its page, a search, a code's page
                page = tab(theme, size)
                open_at(page, "fab-library", None)
                page.wait_for_selector(".main .rp-lib .stiles")
                page.fill(".main .toolbar input.search", rich["code"])
                page.press(".main .toolbar input.search", "Enter")
                page.wait_for_selector(".main .libfound .grid tbody tr button.code")
                first_hit = page.locator(".main .libfound .grid tbody tr").first.inner_text()
                wide = page.evaluate(SIDEWAYS, ".main") if size is PHONE else [0, ""]
                hue, got = stage2_colours(page, theme, ".main", ".main .stile")
                good = (page.inner_text(".main .ptitle") == "Fab library" and page.title() == "Fab library - RightPrice" and first_hit.startswith(rich["code"])
                        and rich["group"] in first_hit and "19,669" in page.inner_text(".main .stiles") and not page.errors and wide[0] <= 1 and hue)
                check(f"The Fab library opens, and finds a code with its construction, Fab group and purchases ({look})", good,
                      "" if good else f"{page.title()!r} {first_hit[:200]!r}, sideways {wide}, colours {got}, console {page.errors[:3]}")
                page.click(f".main .libfound .grid tbody tr button.code:has-text('{rich['code']}')")
                page.wait_for_function("c => (document.querySelector('.main .dhead h1') || {}).textContent === c", arg=rich["code"])
                page.wait_for_timeout(300)
                wide = page.evaluate(SIDEWAYS, ".main") if size is PHONE else [0, ""]
                hue, got = stage2_colours(page, theme, ".main", ".main .stile")
                good = (page.url.endswith("#fab-library/" + rich["code"]) and page.locator(".main .gfields dt").count() == 26 and rich["group"] in page.inner_text(".main .stiles")
                        and page.title() == rich["code"] + " - RightPrice" and not page.errors and wide[0] <= 1 and hue)
                check(f"The Fab library: a code's page, its 26 values and its Fab group ({look})", good,
                      "" if good else f"{page.url} {page.locator('.main .gfields dt').count()} values, sideways {wide}, colours {got}, console {page.errors[:3]}")
                page.context.close()
                for addr, title, sel in (("groups", "Fab groups", ".main .toolbar"), ("purchase-files", "Purchase files", ".main .stiles"),
                                         ("purchase-lines", "Purchase lines", ".main .plfilters")):
                    page = tab(theme, size)
                    open_at(page, addr, None)
                    page.wait_for_selector(sel)
                    page.wait_for_selector(".main .grid tbody tr")
                    page.wait_for_timeout(400)
                    wide = page.evaluate(SIDEWAYS, ".main") if size is PHONE else [0, ""]
                    hue, got = stage2_colours(page, theme, ".main", ".main .stile" if addr != "groups" else None)
                    good = (page.inner_text(".main .ptitle") == title and page.title() == title + " - RightPrice" and not page.errors and wide[0] <= 1 and hue
                            and (page.inner_text(".main .toolbar .count") == f"{n_groups:,} groups" if addr == "groups"
                                 else " lines of " in page.inner_text(".main .toolbar .count") and page.locator(".main .grid tbody tr").count() >= 10 if addr == "purchase-lines"
                                 else page.locator(".main .grid .upst.done").count() >= 1))
                    check(f"Stage 2: {title} opens ({look})", good, "" if good else f"{page.title()!r}, sideways {wide}, colours {got}, console {page.errors[:3]}")
                    page.context.close()

            # ---------------------------------------------------------------- 2. the main paths, each in a fresh tab
            # Create cost: the example and the rates it is on; a chart's tooltip and Escape; Print (in dark: only the cost turns light)
            page = tab("dark")
            open_at(page, "dashboard")
            page.click(".fab")
            page.wait_for_selector(".popup .step")
            check("New cost opens on Create cost", page.get_attribute(".scrim[data-popup]", "data-tab") == "cost" and "new=cost" in page.url)
            page.click(".popup button:has-text('Load the example')")
            page.wait_for_selector(".popup .hero .big")
            big = page.inner_text(".popup .hero .big")
            check("Create cost: the example (Qlty-1) costs Rs 181.40 a metre", big.strip() == "Rs 181.40 / m", big)
            rates_of = page.inner_text(".popup .hero .rates-of") if page.locator(".popup .hero .rates-of").count() else ""
            check("Create cost: under the figure, the rates it is on (stage 5)", rates_of.startswith("Today's rates"), repr(rates_of))
            page.click(".popup .seg button:has-text('Waterfall')")
            page.click(".popup .seg button:has-text('All sub-costs')")
            check("Create cost: the waterfall opens into every sub-cost", page.locator(".popup .wf .wf-label.step").count() >= 10)
            page.locator(".popup .wf .wf-row").nth(1).hover()
            shown = page.is_visible(".pgtip")
            page.keyboard.press("Escape")
            check("Escape closes a chart's tooltip first, and leaves the popup and the fabric open",
                  shown and not page.is_visible(".pgtip") and page.locator(".scrim[data-popup]").count() == 1 and page.inner_text(".popup .hero .big").strip() == "Rs 181.40 / m")
            page.mouse.move(5, 5)
            page.click(".popup .hero button:has-text('Print')")
            page.wait_for_function("() => window.__printed === 1")
            look = """() => [document.documentElement.dataset.theme, getComputedStyle(document.body).backgroundColor,
                getComputedStyle(document.querySelector('.popup .pgbox > .pg')).color]"""
            during = page.evaluate("""() => [document.body.classList.contains('printing'), !!document.querySelector('.cost-out .print-stamp'),
                [...document.querySelectorAll('style')].some(s => /@page \\{ margin: 14mm/.test(s.textContent))]""") + page.evaluate(look)
            count, _, text = pdf_text(page.pdf())
            page.evaluate("dispatchEvent(new Event('afterprint'))")
            after = page.evaluate("""() => [document.body.classList.contains('printing'), [...document.querySelectorAll('style')].some(s => /@page/.test(s.textContent))]""") + page.evaluate(look)
            check("Create cost: Print lays out the cost alone (stamped, every table open), the cost light and the shell left dark, then puts the page back",
                  during == [True, True, True, "dark", THEME["dark"][0], THEME["light"][1]] and "Rs 181.40" in text and "printed" in text and "Load the example" not in text
                  and "Settings and account" not in text and "Table of every line" in text and after == [False, False, "dark", THEME["dark"][0], THEME["dark"][1]],
                  f"{during} {count} pages {after}")
            check("No error in the console in Create cost", not page.errors, str(page.errors[:3]))
            page.context.close()

            page = tab()
            open_at(page, "dashboard?new=cost", ".popup .pgbox > .pg")
            before = len(app.api("/api/list", {})["rows"])
            page.click(".popup button:has-text('Load the example')")
            page.wait_for_selector(".popup .hero .btn.primary")
            page.click(".popup .hero .btn.primary")
            page.wait_for_function("() => document.querySelector('.popup .hero .btn.primary').textContent === 'Update in list'")
            rows = app.api("/api/list", {})["rows"]
            check("Create cost: Add to list adds the fabric to the list", len(rows) == before + 1 and "Added to the list" in page.inner_text("#toast")
                  and any((r["inputs"] or {}).get("Fabric code") == "Qlty-1" for r in rows))
            page.context.close()

            # Bulk upload: a mill sheet, its rows, its alert and the rail's count (in dark: the pack prints light, the shell stays dark)
            page = tab("dark")
            open_at(page, "dashboard?new=bulk", ".popup .pgbox > .pg")
            page.set_input_files(".popup #bulk-file", files["sheet"])
            page.wait_for_selector(".popup .notice.info:has-text('added from a mill sheet')", timeout=60000)
            page.wait_for_function("() => [...document.querySelectorAll('.popup table.list td.s1')].some(td => td.textContent === 'B-3')")
            notice = page.inner_text(".popup .notice.info")
            codes = page.locator(".popup table.list td.s1").all_inner_texts()
            check("Bulk upload: a mill sheet's three rows join the list", notice == "3 rows added from a mill sheet. 1 could not be costed yet; the reason is in Remarks."
                  and {"B-1", "B-2", "B-3"} <= set(codes), f"{notice!r} {codes}")
            check("Bulk upload: the NYD row is listed, not costed", "not costed" in page.locator(".popup table.list tr", has_text="B-3").inner_text())
            check("Bulk upload: the row above its range raises a quote alert", page.locator(".popup .notice.warn li", has_text="B-2").count() == 1)
            alerts = app.api("/api/alerts")["count"]
            page.wait_for_function(f"() => {{ const b = document.querySelector('.rail .badge'); return b && b.textContent === '{alerts}'; }}", timeout=40000)
            check("The rail counts the quote alerts, the number the server gives", alerts >= 1 and page.inner_text(".rail .badge") == str(alerts), f"{alerts}")
            listed = {(r["mill"] or {}).get("Fab Code"): r for r in app.api("/api/list", {})["rows"]}
            page.locator(".popup table.list td.s1 .linkish", has_text="B-1").click()
            page.wait_for_selector(".popup .hero .big")
            got = page.inner_text(".popup .hero .big")
            check("Bulk upload: Open carries the row on to Create cost, at the list's should-cost", page.get_attribute(".scrim[data-popup]", "data-tab") == "cost"
                  and "B-1" in page.inner_text(".popup .hero .lbl") and got == f"Rs {listed['B-1']['should_cost']:,.2f} / m" and page.locator(".popup .card.moved").count() == 1,
                  f"{got} against {listed['B-1']['should_cost']}")

            page.click(".popup .ptab:has-text('Bulk upload')")
            page.wait_for_selector(".popup table.list")
            for code in ("B-1", "B-2"):
                page.locator(".popup table.list tr", has_text=code).locator("input[type=checkbox]").check()
            page.click(".popup .actionbar .btn:has-text('Compare')")
            page.wait_for_selector(".popup .card.hero .big")
            sides = {}
            for side in ("a", "b"):
                label = page.locator(f"#cmp-{side} option:checked").inner_text()
                sides[label.split(" · ")[0]] = page.locator(".popup .card.hero .big").nth(0 if side == "a" else 1).inner_text()
            want = {c: f"Rs {listed[c]['should_cost']:,.2f} / m" for c in ("B-1", "B-2")}
            check("Compare: the two ticked rows are A and B, each at its row's should-cost", sides == want, f"{sides} against {want}")

            page.click(".popup .ptab:has-text('Bulk upload')")
            page.wait_for_selector(".popup table.list")
            page.click(".popup .actionbar a:has-text('Negotiation pack')")
            page.wait_for_selector(".popup .pack-title")
            pack_codes = sorted(page.locator(".popup .pack-table tbody td.pack-fab b").all_inner_texts())
            check("Negotiation pack: made of the two ticked rows", page.locator("#pack-scope option:checked").inner_text() == "Rows ticked on the list (2)"
                  and pack_codes == ["B-1", "B-2"] and "negotiation pack" in page.inner_text(".popup .pack-title"), str(pack_codes))
            page.click(".popup .pack-tools .btn.primary")
            page.wait_for_function("() => window.__printed === 1")
            during = page.evaluate("""() => [document.body.classList.contains('printing-pack'), [...document.querySelectorAll('style')].some(s => /A4 landscape/.test(s.textContent))]""") + page.evaluate(look)
            count, landscape, text = pdf_text(page.pdf(prefer_css_page_size=True))
            page.evaluate("dispatchEvent(new Event('afterprint'))")
            after = [page.evaluate("document.body.classList.contains('printing-pack')")] + page.evaluate(look)
            check("Negotiation pack: Print gives the pack alone on A4 landscape, the pack light and the shell left dark, then puts the page back",
                  during == [True, True, "dark", THEME["dark"][0], THEME["light"][1]] and landscape and "negotiation pack" in text
                  and "Back to the list" not in text and "Settings and account" not in text and after == [False, "dark", THEME["dark"][0], THEME["dark"][1]],
                  f"{during} {count} pages {after}")
            page.click(".popup a:has-text('Back to the list')")
            page.wait_for_selector(".popup table.list")
            check("Negotiation pack: Back to the list", page.get_attribute(".scrim[data-popup]", "data-tab") == "bulk")
            page.keyboard.press("Escape")
            page.wait_for_function("() => !document.querySelector('.scrim[data-popup]')")
            check("Escape closes the popup and the address follows", "new=" not in page.url)
            check("No error in the console in Bulk upload, Compare and the pack", not page.errors, str(page.errors[:3]))
            page.context.close()

            # Right cost, in a fresh tab at its old address: a row opened in Create cost, from its page and its Negotiation tab
            page = tab()
            page.goto(f"{app.base}/rightcost")
            page.wait_for_selector(".grid tbody tr td .code")
            page.locator(".grid tbody tr td .code").first.click()
            page.wait_for_selector(".dhead h1")
            fabric_page = page.url
            where["item"] = fabric_page.split("#", 1)[1]
            should = float(page.locator(".form2 .f", has_text="Should-cost Rs/m").locator("span").nth(1).inner_text().replace(",", ""))
            page.click(".dicons button[aria-label='Open in Create cost']")
            page.wait_for_selector(".popup .hero .big")
            got = float(page.inner_text(".popup .hero .big").replace("Rs", "").replace("/ m", "").replace(",", ""))
            check("Right cost: Open in Create cost, on a first load, costs the row in the popup at its should-cost",
                  page.get_attribute(".scrim[data-popup]", "data-tab") == "cost" and abs(got - should) < 0.02, f"{got} against {should}")
            page.context.close()
            page = tab()
            page.goto(fabric_page.replace("/#", f"/?at={time.time()}#"))
            page.wait_for_selector(".dhead h1")
            page.click(".main .tabs .tab:has-text('Negotiation')")
            page.wait_for_function("() => { const b = document.querySelector('.brief'); return b && /should-cost is Rs/.test(b.textContent) }", timeout=60000)
            brief = page.inner_text(".brief")
            should = float(brief.split("should-cost is Rs ")[1].split(";")[0].replace(",", ""))
            page.click(".brief .btn.fill")
            page.wait_for_selector(".popup .hero .big")
            got = float(page.inner_text(".popup .hero .big").replace("Rs", "").replace("/ m", "").replace(",", ""))
            check("Right cost: the Negotiation tab's Create cost, after a reload on the fabric's page, opens the popup at the brief's should-cost",
                  page.get_attribute(".scrim[data-popup]", "data-tab") == "cost" and abs(got - should) < 0.005, f"{got} against {should}")
            page.go_back()
            page.wait_for_function("() => !document.querySelector('.scrim[data-popup]')")
            check("Back closes the popup", "#item/" in page.url)
            # the keys: Ctrl+F on the list, over the popup, on a fabric's page
            page.goto(f"{app.base}/?at={time.time()}#rightcost")
            page.wait_for_selector(".grid tbody tr td .code")
            page.click(".main .title")
            page.keyboard.press("Escape")
            page.keyboard.press("Control+f")
            page.wait_for_function("() => window.__ctrlF !== undefined")
            on_list = [page.evaluate("window.__ctrlF"), page.evaluate("document.activeElement.id")]
            page.evaluate("window.__ctrlF = undefined")
            page.click(".fab")
            page.wait_for_selector(".popup .step")
            page.click(".popup .pane-in")
            page.keyboard.press("Control+f")
            page.wait_for_function("() => window.__ctrlF !== undefined")
            over_popup = [page.evaluate("window.__ctrlF"), page.evaluate("document.activeElement.id")]
            check("Ctrl+F: on the list it goes to the list's search; over the New cost popup it is the browser's own find",
                  on_list == [True, "search"] and over_popup[0] is False and over_popup[1] != "search", f"{on_list} {over_popup}")
            check("No error in the console in Right cost", not page.errors, str(page.errors[:3]))
            page.context.close()
            for addr in ("yarn", "dashboard"):
                page = tab()
                open_at(page, addr)
                page.click(".pgbox .sub")
                page.keyboard.press("Control+f")
                page.wait_for_function("() => window.__ctrlF !== undefined")
                check(f"Ctrl+F on {addr}: the browser's own find", page.evaluate("window.__ctrlF") is False)
                page.context.close()

            # the Dashboard's mill names, and the supplier page and a Prices page on paper
            page = tab()
            open_at(page, "dashboard")
            page.wait_for_selector(".pg .alert-head .linkish")
            page.locator(".pg .alert-head .linkish").first.click()
            page.wait_for_selector(".dhead h1")
            page.wait_for_timeout(500)
            where["supplier"] = page.url.split("#", 1)[1]
            count, _, text = pdf_text(page.pdf())
            check("Dashboard: a mill's name opens its supplier page", "#supplier/" in page.url and "Questions for the next meeting" in page.inner_text(".main"))
            check("The supplier page prints with no page's print rules but its own (no @page set anywhere)", not page.evaluate(PAGE_RULES)
                  and "Questions for the next meeting" in text and count >= 1, f"{count} pages")
            off = type_on_paper(page, [".dhead h1", ".stile .sb"])
            check("The supplier page prints its type at the size it has on screen (nothing zooms or scales it in print)", not off, "; ".join(off))
            page.context.close()
            page = tab()
            open_at(page, "yarn")
            off = type_on_paper(page, [".main .title", ".pg .card-head h2", ".pg .sub"])
            check("Yarn prices prints its type at the size it has on screen", not off, "; ".join(off))
            page.context.close()

            # a rate table saved (a note, so no rate changes), prices brought in, a cotton price added with Enter
            page = tab()
            open_at(page, "ratecard/Quantity_Terms")
            page.click(".pg button:has-text('Edit this table')")
            page.locator(".pg table.edit input[aria-label='Note']").first.fill("Checked in the browser")
            page.click(".pg .btn.primary:has-text('Save')")
            page.wait_for_selector(".pg button:has-text('Edit this table')")
            terms = app.api("/api/table/Quantity_Terms")
            check("Rate tables: an edited table is saved to the rate master", "Saved to the rate master" in page.inner_text("#toast")
                  and terms["rows"][0][terms["columns"].index("Note")] == "Checked in the browser" and not page.errors, str(page.errors[:3]))
            page.context.close()

            def bring_in(page):
                """Bring in prices: the yarn prices file read and its rows sent to review."""
                open_at(page, "intake")
                page.set_input_files("#in-file", files["prices"])
                page.wait_for_selector(".pg table.edit tbody tr, #map-count")
                if page.locator("#map-count").count():          # a table was read: say which column is which, then review
                    page.select_option("#map-count", "Count")
                    page.select_option("#map-low", "Rate")
                    page.select_option("#map-yarn", "Yarn")
                    page.click(".pg button:has-text('Send to review')")
                    page.wait_for_selector(".pg table.edit tbody tr")
            page = tab()
            market = len(app.api("/api/table/Market_Yarn")["rows"])
            bring_in(page)
            page.click(".pg button:has-text('Add to market reference')")
            page.wait_for_function("() => location.hash === '#yarn'")
            check("Bring in prices: the reviewed rows reach the market reference, and Yarn prices opens",
                  len(app.api("/api/table/Market_Yarn")["rows"]) == market + 2 and "2 rows added" in page.inner_text("#toast") and not page.errors, str(page.errors[:3]))
            page.context.close()
            page = tab()
            open_at(page, "cotton")
            page.fill("#cot-price", "55800")
            page.fill("#cot-source", "browser check")
            page.press("#cot-price", "Enter")
            page.wait_for_function("() => /55,800/.test((document.querySelector('.pg .stat .val') || {}).textContent || '')")
            check("Cotton prices: a price added with Enter is saved and shown", app.api("/api/cotton")["points"][-1][1] == 55800
                  and "Cotton price added" in page.inner_text("#toast") and not page.errors, str(page.errors[:3]))
            page.context.close()

            # a mill cost sheet's draft applied
            page = tab()
            open_at(page, "costsheets")
            page.set_input_files("#cs-file", files["costsheet"])
            page.wait_for_selector(".pg tbody input[type=checkbox]")
            draft = app.api("/api/costsheet")["drafts"][0]
            page.locator(".pg tbody input[type=checkbox]").first.check()
            apply = page.locator(".pg .card-head .btn.primary")
            apply.click()
            asked = apply.inner_text()
            apply.click()
            page.wait_for_selector(".pg .notice.info:has-text('Applied.')")
            check("Mill cost sheets: a ticked draft is applied after asking once more", asked.endswith("sure?") and draft["id"] not in {d["id"] for d in app.api("/api/costsheet")["drafts"]}
                  and not page.errors, f"{asked!r} {page.errors[:3]}")
            # a change of rates (the draft just applied) holds up no page: Right cost is worked out again in the background,
            # showing the rows last worked out meanwhile, so Create cost, Right cost and the Dashboard answer at once
            took = {}
            for name, path, body in (("Create cost's costing", "/api/cost", masters.EXAMPLE_ROW), ("Right cost", "/api/costs", None),
                                     ("the Dashboard", "/api/insights", None), ("the quote alerts", "/api/alerts", None)):
                t0 = time.time()
                app.api(path, body)
                took[name] = round(time.time() - t0, 1)
            check("After a change of rates every page answers at once (within 10 s each; Right cost is worked out again in the background)",
                  max(took.values()) <= 10, str(took))
            page.context.close()

            # the rate master's lists are read afresh for each popup: a yarn added since (by someone else) shows without a reload
            page = tab()
            open_at(page, "dashboard")

            def warp_yarns():
                page.click(".fab")
                page.wait_for_selector(".popup .step")
                page.click(".popup button:has-text('Load the example')")
                page.wait_for_selector(".popup .hero .big")
                page.click(".popup .step-head[data-step=yarn]")
                page.wait_for_selector(".popup #f-warp-yarn")
                got = page.locator(".popup #f-warp-yarn option").all_inner_texts()
                page.keyboard.press("Escape")
                page.wait_for_function("() => !document.querySelector('.scrim[data-popup]')")
                return got
            first = warp_yarns()
            yarn_table = app.api("/api/table/Yarn_Rates")
            app.api("/api/table/Yarn_Rates", {"columns": yarn_table["columns"], "rows": yarn_table["rows"] + [["Cotton 99S", "Cotton", "99S", 99, 500, time.strftime("%Y-%m-%d"), "Browser check"]]}, method="PUT")
            second = warp_yarns()
            app.api("/api/table/Yarn_Rates", {"columns": yarn_table["columns"], "rows": yarn_table["rows"]}, method="PUT")     # as it was
            check("Create cost reads the rate master's lists afresh each time the popup opens: a yarn added since shows without a reload",
                  not any("Cotton 99S" in o for o in first) and any("Cotton 99S" in o for o in second) and not page.errors, f"{len(first)} then {len(second)} yarns, {page.errors[:3]}")
            page.context.close()

            # stage 5: a dated yarn rate entered on Yarn prices shows in its card and moves the purchase orders of that month
            rows = app.costs()
            pos = [r for r in rows if r["source"] == "Purchase orders" and (r.get("rates") or {}).get("month") and r["warp"] == r["weft"]]
            po = pos[0]
            yarn, month, label = po["warp"], po["rates"]["month"], po["rates"]["label"]
            other = next((r for r in rows if r["source"] == "Purchase orders" and yarn in (r["warp"], r["weft"])
                          and (r.get("rates") or {}).get("month") not in (None, month)), None)
            rate = round(next(y["rate"] for y in app.api("/api/meta")["yarns"] if y["key"] == yarn) * 1.2, 2)
            page = tab()
            open_at(page, "yarn")
            page.wait_for_selector(".pg .dr-card #dr-yarn", timeout=120000)
            month_box = page.locator(".pg .dr-card .dr-month", has_text=label)
            before = month_box.inner_text()
            page.select_option("#dr-yarn", yarn)
            page.fill("#dr-month", month)
            page.fill("#dr-rate", str(rate))
            page.select_option("#dr-rests", "circular")
            page.fill("#dr-note", "browser check")
            page.click(".pg .dr-card button:has-text('Save the dated rate')")
            page.wait_for_selector(".pg .dr-card h3:has-text('In force (1)')")
            shown = page.locator(".pg .dr-card tr", has_text=yarn).filter(has_text=label).filter(has_text=f"{rate:,.2f}").count()
            after = month_box.inner_text()
            check("Yarn prices: a dated rate entered shows in the dated yarn rates card, and its month's orders say they have one",
                  shown == 1 and "no dated yarn rate yet" in before
                  and "no dated yarn rate yet" not in after and not page.errors, f"{shown} rows; {before!r} then {after!r}; {page.errors[:3]}")
            page.context.close()
            moved = None
            for _ in range(120):
                rows = app.costs()
                moved = next(r for r in rows if r["source"] == "Purchase orders" and r["code"] == po["code"])
                if moved["rates"].get("dated"):
                    break
                time.sleep(1)
            still = other and next(r for r in rows if r["source"] == "Purchase orders" and r["code"] == other["code"])
            check("The dated rate moves the purchase orders of that month (on the dated rate, at a higher should-cost), and no other month's",
                  moved["rates"].get("dated") and moved["should"] > po["should"] and (not other or abs(still["should"] - other["should"]) < 0.005),
                  f"{po['code']} {po['should']} -> {moved['should']} ({moved['rates_of']}); other month {other and other['should']} -> {still and still['should']}")

            # stage 5: Bring in prices adds the reviewed rows as dated yarn rates, after asking the month and whether GST is in
            month2 = next(o["month"] for o in app.api("/api/dated-rates")["orders"] if o["month"] != month)
            page = tab()
            bring_in(page)
            page.click(".pg button:has-text('Add as dated yarn rates')")
            page.wait_for_selector(".pg .dr-card .dr-months")
            say = lambda: page.inner_text(".pg .dr-card [aria-live]")
            unasked = page.locator(".pg .dr-card .dr-months").all_inner_texts()
            for row, key in ((1, "Cotton 40S"), (2, "Cotton 60S")):
                page.select_option(f".pg .dr-card select[aria-label='Yarn of the yarn master for row {row}']", key)
            add = page.locator(".pg .dr-card button:has-text('Add the dated rates')")
            add.click()
            page.wait_for_function("() => /Choose the month/.test(document.querySelector('.pg .dr-card [aria-live]').textContent)")
            no_month = say()
            page.fill("#dr-in-month", month2)
            page.dispatch_event("#dr-in-month", "change")
            label2 = next(o["label"] for o in app.api("/api/dated-rates")["orders"] if o["month"] == month2)
            page.wait_for_function("l => [...document.querySelectorAll('.pg .dr-card .dr-months')].every(td => td.textContent === l)", arg=label2)
            add.click()
            page.wait_for_function("() => /include GST/.test(document.querySelector('.pg .dr-card [aria-live]').textContent)")
            no_gst = say()
            page.check("#dr-in-gst-no")
            add.click()
            page.wait_for_function("() => /dated rates added/.test(document.querySelector('.pg .dr-card [aria-live]').textContent)")
            added = say()
            entries = {(e["yarn_key"], e["month"], e["rate"]) for e in app.api("/api/dated-rates")["entries"]}
            check("Bring in prices: Add as dated yarn rates asks the month, then whether the prices include GST",
                  set(unasked) == {"choose the month above"} and "Choose the month" in no_month and "include GST" in no_gst, f"{unasked} {no_month!r} {no_gst!r}")
            check("Bring in prices: the rows are added as dated yarn rates of the month chosen", added.startswith("2 dated rates added from 2 rows")
                  and {("Cotton 40S", month2, 352), ("Cotton 60S", month2, 430)} <= entries and not page.errors, f"{added!r} {page.errors[:3]}")
            page.context.close()

            # a bookmark of the retired earlier screens
            page = tab()
            page.goto(f"{app.base}/classic/")
            page.wait_for_function(DRAWN, arg=".pgbox > .pg", timeout=60000)
            check("A bookmark of the retired /classic opens the app", page.url.rstrip("/").split("#")[0] == app.base and page.inner_text(".main .title") == "Dashboard"
                  and not page.errors, page.url)
            page.context.close()

            # stage 2's main paths: on a purchase order's page the price popup, and from it the Fab group; on the group's page a
            # code's price popup; the list of Fab groups searched and a group opened; Purchase files: an upload's detail, and
            # the purchase file that came with the code loaded again from the page (it changes nothing)
            page = tab()
            open_at(page, "item/Purchase orders|" + rich["code"], None)
            page.wait_for_selector(".dhead h1")
            page.click(".dicons button[aria-label='Price over time (purchase history)']")
            page.wait_for_selector(".pdialog .pchart svg circle.dotm")
            head = page.inner_text(".pdialog .phead h2")
            page.click(f".pdialog .acts button:has-text('Open Fab group {rich['group']}')")
            # the fabric's page has a heading of the same kind: wait for the group's own
            page.wait_for_function("g => (document.querySelector('.main .dhead h1') || {}).textContent === g", arg=rich["group"])
            check("Stage 2: a purchase order's page opens its price popup, and the popup opens its Fab group's page",
                  head == "Price over time: " + rich["code"] and page.locator(".pdialog").count() == 0 and page.inner_text(".main .dhead h1") == rich["group"]
                  and page.url.endswith("#group/" + rich["group"]) and not page.errors, f"{head!r} {page.url} {page.errors[:3]}")
            other = page.locator(".main button.code[title='Price over time for this code']").first
            code = other.inner_text()
            other.click()
            page.wait_for_selector(".pdialog .pchart svg circle.dotm")
            check("Stage 2: on a Fab group's page, a code of the group opens its price popup", page.inner_text(".pdialog .phead h2") == "Price over time: " + code
                  and rich["codes"] >= 2 and not page.errors, f"{code} {page.errors[:3]}")
            page.context.close()
            # the usual range over time (GP, 28 Nov 2026): on the group page, a period chosen with the slider works the figures
            # out again (a view only), every purchase stays on the chart (those outside faded); "Last 12 months" puts it back; the
            # price popup has the same slider
            page = tab()
            open_at(page, where["group"], None)
            page.wait_for_selector(".main .pbar input[type=range]")
            page.wait_for_selector(".main .pchart svg circle.dotm")
            tile = lambda: page.inner_text(".main .stiles .stile:first-child .sb")
            dots0, n0_ = page.locator(".main .pchart svg circle.dotm").count(), tile()
            months = page.evaluate("() => +document.querySelector(\".main .pbar input[aria-label='From the month']\").max + 1")
            slide = """([label, v]) => { const i = document.querySelector(`.main .pbar input[aria-label='${label}']`); i.value = String(v);
                i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true })); }"""
            page.evaluate(slide, ["From the month", months - 1])
            page.wait_for_function("() => /the period chosen/.test((document.querySelector('.main .pbar .pwords') || {}).textContent || '')")
            page.wait_for_selector(".main .pchart svg circle.dotm")
            page.wait_for_timeout(300)
            dots1, n1_, faded = page.locator(".main .pchart svg circle.dotm").count(), tile(), page.locator(".main .pchart svg g.pt.out").count()
            last_m = app.api(f"/api/groups/{rich['group']}")["months"][-1]
            wanted = app.api(f"/api/groups/{rich['group']}?from={last_m}&to={last_m}")
            page.click(".main .pbar button:has-text('Last 12 months')")
            page.wait_for_function("() => /the last 12 months/.test((document.querySelector('.main .pbar .pwords') || {}).textContent || '')")
            page.wait_for_selector(".main .pchart svg circle.dotm")
            back_ = tile()
            check("The usual range over time: the group page's slider chooses a period (its last month) and the figures are worked out again for it; "
                  "every purchase stays on the chart, those outside faded; Last 12 months puts it back",
                  months >= 2 and n1_ == f"{wanted['purchases']:,}" and dots1 == dots0 and (faded > 0) == (wanted["outside_period"] > 0) and back_ == n0_ and not page.errors,
                  f"{months} months, {n0_} then {n1_} (want {wanted['purchases']}), dots {dots0}/{dots1}, faded {faded}, back {back_}, {page.errors[:3]}")
            other = page.locator(".main button.code[title='Price over time for this code']").first
            code = other.inner_text()
            other.click()
            page.wait_for_selector(".pdialog .pbar input[type=range]")
            page.evaluate(slide.replace(".main .pbar", ".pdialog .pbar"), ["From the month", months - 1])
            page.wait_for_function("() => /the period chosen/.test((document.querySelector('.pdialog .pbar .pwords') || {}).textContent || '')")
            page.wait_for_selector(".pdialog .pchart svg circle.dotm")
            check("The usual range over time: the price popup has the same slider; a period chosen redraws it for that period, every purchase still on its chart",
                  page.inner_text(".pdialog .phead h2") == "Price over time: " + code and page.locator(".pdialog .pchart svg circle.dotm").count() >= 1 and not page.errors,
                  str(page.errors[:3]))
            page.context.close()
            # every row of a purchase file stored (GP, 28 Nov 2026): a code with sample or yardage orders (or deleted lines) shows them
            # in its price popup by type, in no figure, those in rupees per metre as hollow dots; Purchase files says what was stored
            gp_ = app.api(f"/api/groups/{rich['group']}")
            with_other = next((o["code"] for o in gp_.get("others", []) if o.get("plotted")), None) or next((o["code"] for o in gp_.get("others", [])), None)
            if with_other is None:          # the busiest group has none: any code of the history that has one
                for g_ in app.api("/api/groups")["groups"][:200]:
                    page_ = app.api(f"/api/groups/{g_['code']}")
                    if page_.get("others"):
                        with_other = page_["others"][0]["code"]
                        break
            hx = app.api(f"/api/purchases/history?code={with_other}") if with_other else {"others": []}
            page = tab()
            open_at(page, "dashboard", ".pgbox > .pg")
            page.evaluate("c => RP_PURCH.openHistory(c)", with_other)
            page.wait_for_selector(".pdialog .othl tbody tr")
            rows_o = page.locator(".pdialog .othl tbody tr").count()
            hollow = page.locator(".pdialog .pchart circle.dotm.oth").count()
            plotted = sum(1 for o in hx["others"] if o["plotted"])
            open_at(page, "purchase-files", None)
            page.wait_for_selector(".main .grid tbody tr")
            page.click(".main .grid tbody tr button.code:has-text('#')")
            page.wait_for_selector(".main .updetail h3")
            stored_words = page.inner_text(".main .updetail")
            check("Every purchase-order line stored: a code's price popup lists its other order lines (sample, yardage, deleted ...) by type, in no "
                  "figure, and draws those in rupees per metre as hollow dots; an upload's page says how many rows were stored and how many count",
                  with_other and rows_o == len(hx["others"]) and (hollow >= 1) == (plotted >= 1) and "Stored: " in stored_words and "in no figure" in stored_words
                  and not page.errors, f"{with_other} {rows_o}/{len(hx['others'])} hollow {hollow} plotted {plotted} {page.errors[:3]}")
            page.context.close()
            # the Fab library: a code found, its page, its Fab group; a list uploaded from the page and read in the background
            page = tab()
            open_at(page, "fab-library", None)
            page.wait_for_selector(".main .rp-lib .uprow input[type=file]")
            page.fill(".main .toolbar input.search", rich["code"].lower())
            page.click(".main .toolbar button:has-text('Search')")
            page.wait_for_selector(".main .libfound .grid tbody tr button.code")
            page.click(f".main .libfound .grid tbody tr button.code:has-text('{rich['code']}')")
            page.wait_for_function("c => (document.querySelector('.main .dhead h1') || {}).textContent === c", arg=rich["code"])
            page.click(f".main .acts button:has-text('Open Fab group {rich['group']}')")
            page.wait_for_function("g => (document.querySelector('.main .dhead h1') || {}).textContent === g", arg=rich["group"])
            via = page.url
            import pandas as pd
            one = pd.read_csv(os.path.join(HERE, "data", "plm_specs_for_po.csv"), dtype=str).fillna("")
            one = one[one["article_code"] == rich["code"]]
            open_at(page, "fab-library", None)
            page.wait_for_selector(".main .rp-lib .uprow input[type=file]")
            page.set_input_files(".main .rp-lib .uprow input[type=file]", files=[{"name": "PLM list, one code.csv", "mimeType": "text/csv", "buffer": one.to_csv(index=False).encode("utf-8-sig")}])
            page.click(".main .rp-lib .uprow button:has-text('Upload')")
            page.wait_for_function("() => { const t = document.querySelector('.main .libups .grid'); return !!t && t.tBodies[0].rows.length === 2 && t.querySelectorAll('.upst.done').length === 2 && /grouped again/.test(t.tBodies[0].rows[0].textContent) }", timeout=300000)
            newest = page.locator(".main .libups .grid tbody tr").first.inner_text()
            check("The Fab library: a code found by its code in small letters opens its page, and from it its Fab group; a list uploaded from the page is "
                  "read in the background, its counts shown (one code, the same)",
                  via.endswith("#group/" + rich["group"]) and "Uploaded" in page.inner_text("#toast") and "1 code ·" in newest and "0 new, 0 corrected, 1 the same" in newest
                  and not page.errors, f"{via} {newest[:200]!r} {page.errors[:3]}")
            page.context.close()
            # with no frame, stage 2's own look stays on its pages: no box round a stat's note on Pilot results (the profile's
            # notes: section 3); and Pilot results says it is the pilot as it was run (stage 2's line, carried from the frame)
            page = tab()
            open_at(page, "pilot")
            on_pilot = page.evaluate(BOXED, ".pg .stat .note")
            as_run = page.locator(".pg .notice.info", has_text="the pilot as it was run").count()
            check("Stage 2's own look stays on its pages (no box round a stat's note on Pilot results); Pilot results says it is the pilot as run",
                  page.locator(".pg .stat .note").count() >= 4 and on_pilot == 0 and as_run == 1 and not page.errors, f"{on_pilot} boxed, {as_run} {page.errors[:3]}")
            page.context.close()
            page = tab()
            open_at(page, "groups", None)
            page.wait_for_selector(".main .toolbar")
            page.fill(".main .toolbar input.search", rich["group"])
            page.press(".main .toolbar input.search", "Enter")
            page.wait_for_function("() => document.querySelectorAll('.main .grid tbody tr').length === 1")
            page.click(f".main .grid tbody tr button.code:has-text('{rich['group']}')")
            page.wait_for_function("g => (document.querySelector('.main .dhead h1') || {}).textContent === g", arg=rich["group"])
            check("Stage 2: the list of Fab groups finds a group by its code and opens its page", page.inner_text(".main .dhead h1") == rich["group"]
                  and not page.errors, str(page.errors[:3]))
            page.context.close()
            page = tab()
            open_at(page, "purchase-files", None)
            page.wait_for_selector(".main .grid tbody tr")
            page.click(".main .grid tbody tr button.code:has-text('#')")
            page.wait_for_selector(".main .updetail h3")
            detail = page.inner_text(".main .updetail h3")
            before = app.api("/api/purchases/status")["counts"]
            page.click(".main button:has-text('Load the purchase file that came with the code')")
            # the uploads are the page's first table (an upload's detail below it has tables of its own)
            page.wait_for_function("() => { const t = document.querySelector('.main .grid'); return !!t && t.tBodies[0].rows.length === 2 && t.querySelectorAll('.upst.done').length === 2 }", timeout=600000)
            newest = page.locator(".main .grid tbody tr").first.inner_text()
            after = app.api("/api/purchases/status")["counts"]
            check("Purchase files: an upload opens to what it held; the file that came with the code, loaded again from the page, is read in the background and changes nothing",
                  detail.startswith(f"Upload #{shipped['id']}: ") and "Loading the purchase file" in page.inner_text("#toast") and "already in" in newest
                  and after == before and not page.errors, f"{detail!r} {newest[:160]!r} {page.errors[:3]}")
            page.context.close()
            # a purchase file chosen on the page and uploaded (the file box keeps the file chosen while the page is drawn again)
            import pandas as pd
            cols = ["Purchasing Document", "Plant", "Document Date", "Item", "Material", "Short Text", "Purchasing Doc. Type", "Order Quantity",
                    "Order Unit", "Net Price", "Name of Supplier", "Currency", "Deletion Indicator"]
            xb = io.BytesIO()
            pd.DataFrame([{"Purchasing Document": 9400000001, "Plant": "F007", "Document Date": pd.Timestamp("2026-11-10"), "Item": 10, "Material": rich["code"],
                           "Short Text": "made up for the checks", "Purchasing Doc. Type": "BO", "Order Quantity": 100, "Order Unit": "M", "Net Price": 123,
                           "Name of Supplier": "1200094    ARVIND LTD", "Currency": "INR", "Deletion Indicator": None}], columns=cols).to_excel(xb, index=False)
            page = tab()
            open_at(page, "purchase-files", None)
            page.wait_for_selector(".main .uprow input[type=file]")
            page.set_input_files(".main .uprow input[type=file]", files=[{"name": "orders chosen on the page.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": xb.getvalue()}])
            page.wait_for_timeout(300)
            page.click(".main .uprow button:has-text('Upload')")
            page.wait_for_function("() => { const t = document.querySelector('.main .grid'); return !!t && t.tBodies[0].rows.length === 3 && /orders chosen on the page/.test(t.tBodies[0].rows[0].textContent) && t.tBodies[0].rows[0].querySelector('.upst.done') }", timeout=300000)
            newest = page.locator(".main .grid tbody tr").first.inner_text()
            check("Purchase files: a file chosen on the page stays chosen while the page is drawn again, and Upload sends it; it is read in the background",
                  "Uploaded" in page.inner_text("#toast") and "1 new" in newest and not page.errors, f"{newest[:200]!r} {page.errors[:3]}")
            page.context.close()
            app.costs()             # Right cost worked out again after the load, before the next checks
            browser.close()
        app.stop()

        # ---------------------------------------------------------------- 3. users and roles on (stage 3)
        app = App(data, {"RIGHTPRICE_ADMINS": "gp@example.com"})
        people = (("v@example.com", "Viewer"), ("b@example.com", "Buyer"), ("r@example.com", "Rates editor"), ("gp@example.com", "Admin"))
        for email, role in people[:3]:
            app.api("/api/users/add", {"email": email, "role": role, "name": role}, who="gp@example.com")
        app.costs(who="gp@example.com")         # the server's work after a start done, so a page's wait is the page's own
        with sync_playwright() as p:
            browser = p.chromium.launch()

            def person(who):
                """A tab as this person, with every refusal of the server and every script error kept."""
                ctx = browser.new_context(viewport=DESK, extra_http_headers={"X-MS-CLIENT-PRINCIPAL-NAME": who})
                ctx.add_init_script(INIT)
                page = ctx.new_page()
                page.set_default_timeout(30000)
                page.refused, page.errors = [], []
                page.on("response", lambda r: page.refused.append(f"{r.status} {r.request.method} {r.url.split(app.base)[-1]}") if r.status in (401, 403) else None)
                page.on("pageerror", lambda e: page.errors.append(str(e)))
                return page

            # a page has drawn, or says it is not open to the role
            shut = """sel => /not open to your role/.test((document.querySelector('.main .ua-nopage') || {}).textContent || '')
                || (sel === '.pgbox > .pg' ? (r => !!r && r.textContent.trim() !== 'Loading...' && r.children.length > 0)(document.querySelector(sel)) : !!document.querySelector(sel))"""
            popup_drawn = """() => document.querySelector('.popup .ptab.on') && (r => !!r && r.textContent.trim() !== 'Loading...' && r.children.length > 0)(document.querySelector('.popup .pgbox > .pg'))"""

            def offered(who):
                """What a person sees offered on each page that has something to change."""
                page = person(who)
                seen = {}

                def at(address, where=".pgbox > .pg"):
                    page.goto(f"{app.base}/?at={time.time()}#{address}")
                    page.wait_for_function(DRAWN, arg=where, timeout=60000)
                    page.wait_for_timeout(700)
                    return page.locator(where)

                box = at("yarn")
                page.wait_for_selector(".pg .dr-card h3:has-text('In force')", timeout=120000)
                seen["edit rates"] = box.locator("button:has-text('Edit'):visible").count() > 0
                seen["bring in prices"] = box.locator("a:has-text('Bring in prices')").count() > 0 or page.locator(".main .tab:has-text('Bring in prices')").count() > 0
                seen["dated rate entry"] = box.locator("#dr-yarn").count() > 0
                seen["rate tables edit"] = at("rates").locator("button:has-text('Edit this table')").is_visible()
                seen["add cotton"] = at("cotton").locator("#cot-price").count() > 0
                box = at("costsheets")
                seen["cost sheet upload"] = box.locator("#cs-file").count() > 0
                seen["apply drafts"] = box.locator(".card-head .btn.primary").count() > 0
                box = at("dashboard")
                seen["mark seen"] = box.locator(".alert-head .btn").count() > 0
                box = at("dashboard?new=bulk", ".popup .pgbox > .pg")
                seen["list upload"] = box.locator("#bulk-file").count() > 0
                seen["list remove"] = box.locator(".actionbar .btn.danger").count() > 0
                box = at("dashboard?new=cost", ".popup .pgbox > .pg")
                page.click(".popup button:has-text('Load the example')")
                page.wait_for_selector(".popup .hero .big")
                seen["add to list"] = page.locator(".popup .hero .btn.primary").count() > 0
                page.goto(f"{app.base}/?at={time.time()}#intake")
                page.wait_for_function(shut, arg=".pgbox > .pg", timeout=60000)
                seen["intake page"] = page.locator(".main .ua-nopage", has_text="not open to your role").count() == 0
                seen["merge groups"] = at("groups", ".main .toolbar").locator("xpath=..").locator(".mergerow").count() > 0          # stage 2
                seen["purchase upload"] = at("purchase-files", ".main .stiles").locator("xpath=..").locator(".uprow input[type=file]").count() > 0
                seen["library upload"] = at("fab-library", ".main .rp-lib .stiles").locator("xpath=..").locator(".uprow input[type=file]").count() > 0   # the Fab library
                seen["order types"] = at("purchase-lines", ".main .plfilters").locator("xpath=..").locator("select[aria-label^='Order type of']").count() > 0
                seen["exchange rate entry"] = at("fx").locator("#fx-rate").count() > 0
                page.context.close()
                return seen, page.refused + page.errors

            # every address the shell has: how to reach it, and what shows once it has drawn
            addresses = [(a, a, ".pgbox > .pg") for a, _ in PAGES] + [("rightcost", "rightcost", ".grid tbody tr td .code"),
                         ("item", where["item"], ".dhead h1"), ("supplier", where["supplier"], ".dhead h1"), (None, "lib/Payment terms", ".main .title"),
                         ("users", "users", ".main .ua-card"), ("group", where["group"], ".main .dhead h1"), ("groups", "groups", ".main .toolbar"),
                         ("purchase-files", "purchase-files", ".main .stiles"), ("fab-library", "fab-library", ".main .rp-lib .stiles"),
                         ("purchase-lines", "purchase-lines", ".main .plfilters")] + [(t, f"dashboard?new={t}", None) for t, _ in POPUP_TABS]

            def walk(who):
                """Every address as this person, each from a fresh load: what the role may open draws, what it may not says so
                (a popup tab is not offered), the menus offer exactly what it may open, and the server refuses nothing asked."""
                allowed = set(app.api("/api/me", who=who)["allowed"])

                def may(addr):
                    return addr not in NEEDS or NEEDS[addr] in allowed
                page, wrong = person(who), []
                for addr, hsh, sel in addresses:
                    page.goto(f"{app.base}/?at={time.time()}#{hsh}")
                    try:
                        if sel:
                            page.wait_for_function(shut, arg=sel, timeout=60000)
                            said = page.locator(".main .ua-nopage", has_text="not open to your role").count() > 0
                            if said == may(addr):
                                wrong.append(f"{hsh}: {'says not open' if said else 'opens'}")
                        else:
                            page.wait_for_function(popup_drawn, timeout=60000)
                            tabs = page.locator(".popup .ptab").all_inner_texts()
                            label = dict(POPUP_TABS)[addr]
                            if (label in tabs) != may(addr) or (may(addr) and page.inner_text(".popup .ptab.on") != label):
                                wrong.append(f"{hsh}: tabs {tabs}")
                        page.wait_for_timeout(400)
                    except Exception as e:  # noqa: BLE001 - a page that never draws is reported like any other fault
                        wrong.append(f"{hsh}: never drew ({str(e).splitlines()[0]})")
                    if addr == "dashboard":
                        page.wait_for_function("() => typeof RPA !== 'undefined' && !!RPA.me")
                        menus = set(page.evaluate(OFFERED))
                        want = {a for a in ["dashboard", "pilot", "yarn", "cotton", "intake", "rates", "ratecard", "costsheets", "settings", "fx", "cost", "bulk", "compare", "pack"] if may(a)}
                        if menus != want:
                            wrong.append(f"the menus offer {sorted(menus - want)} too, and not {sorted(want - menus)}")
                page.context.close()
                return wrong + page.refused + page.errors

            want = {"Viewer": set(), "Buyer": {"mark seen", "list upload", "list remove", "add to list", "cost sheet upload"}}
            want["Rates editor"] = want["Admin"] = {"edit rates", "bring in prices", "dated rate entry", "rate tables edit", "add cotton", "cost sheet upload",
                                                    "apply drafts", "mark seen", "list upload", "list remove", "add to list", "intake page",
                                                    "merge groups", "purchase upload", "library upload", "order types", "exchange rate entry"}
            for who, role in people:
                seen, refused = offered(who)
                got = {k for k, v in seen.items() if v}
                an = "an" if role[0] in "AEIOU" else "a"
                check(f"Roles: {an} {role} is offered exactly what the role may do, and no page asks the server for what it refuses",
                      got == want[role] and not refused, f"offered {sorted(got)}, refused {refused[:3]}")
                wrong = walk(who)
                check(f"Roles: {an} {role} walks every address ({len(addresses)}): each opens or says it is not open as the role says, the menus agree, nothing refused",
                      not wrong, "; ".join(wrong[:4]))
            # the profile's notes (the e-mail, the role) stay as the shell draws them: stage 2's .note is its pages' own
            page = person("gp@example.com")
            page.goto(f"{app.base}/?at={time.time()}#dashboard")
            page.wait_for_function("() => typeof RPA !== 'undefined' && !!RPA.me")
            page.click("#avatar")
            page.wait_for_selector(".flyout:not([hidden]) .note")
            notes, boxed = page.locator(".flyout .note").count(), page.evaluate(BOXED, ".flyout .note")
            check("The profile's notes (the role; the e-mail on Azure) have no box round them: stage 2's look stays on its own pages", notes >= 1 and boxed == 0 and not page.errors,
                  f"{boxed} of {notes} boxed {page.errors[:3]}")
            page.context.close()
            # each page unticked in turn, for a Buyer: that page goes, every other still works, and nothing is refused
            for perm in [k for k in sorted(set(NEEDS.values())) if k.startswith("page:") and k != "page:users"]:
                app.api("/api/users/permissions", {"changes": [{"role": "Buyer", "permission": perm, "allowed": False}]}, who="gp@example.com")
                wrong = walk("b@example.com")
                app.api("/api/users/permissions", {"changes": [{"role": "Buyer", "permission": perm, "allowed": True}]}, who="gp@example.com")
                check(f"Roles: a Buyer with {perm} unticked walks every address as the role now says, nothing refused", not wrong, "; ".join(wrong[:4]))
            browser.close()
    except BaseException:           # a crash fails the run like any check, and keeps what it needs to be looked into
        ok = False
        print("CRASHED:")
        traceback.print_exc()
    finally:
        if app:
            app.stop()
        if ok:
            shutil.rmtree(data, ignore_errors=True)
        else:
            print(f"The servers' logs and the data are kept in {data}")
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
