"""Checks the screens in a browser: every page of the shell opens, in light and dark and at phone width, with no error
in the browser's console, the main paths work, and each role is offered only what it may do.

Run: python check_browser.py     It must print ALL OK. It needs Python's playwright package and its Chromium
(on GitHub: pip install playwright; python -m playwright install --with-deps chromium).

What it does: starts the app on a temporary data folder and a SQLite file in it (the rate master that comes with the
code; nothing in data/ is touched, and DATABASE_URL from the environment is never used), then in Chromium, each page and
each path opened in a fresh tab (a first load, as from a bookmark or a reload):
1. every page of the shell (Home, Prices, Right cost, a fabric's page, a supplier's page, a setup list) and every tab of the
   New cost popup, in light and in dark at 1366 x 900 and in light at 390 x 844: it draws (nothing left on "Loading...",
   no "could not be loaded"), carries its heading or its tab, shows the theme's colours (computed, not only the switch),
   on a phone neither the page nor the page's own box scrolls sideways, and the console stays empty;
2. the main paths: Create cost (the example, Qlty-1, is Rs 181.40; Add to list adds a row; Print prints the cost alone);
   Bulk upload (a mill sheet's rows, its alert and the rail's count); a row opened in Create cost at the list's
   should-cost; Compare of two ticked rows, each side at its row's should-cost; the pack of the ticked rows and its
   A4 landscape print; a Right cost row opened in Create cost, from the fabric's page and from its Negotiation tab, at
   the row's should-cost; a rate table saved; prices brought in; a cotton price added (with Enter); a mill cost sheet's
   draft applied; the supplier page printing with no other page's print rules; the keys (Ctrl+F is the browser's find
   except on the list; Escape closes a chart's tooltip before the popup); a bookmark of the retired /classic;
3. with users and roles on (stage 3): a Viewer, a Buyer and an Admin each see only the buttons their role may use, and
   a Viewer's walk through every page asks the server for nothing it refuses.
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
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DESK, PHONE = {"width": 1366, "height": 900}, {"width": 390, "height": 844}
# the pages of the shell: address, the heading it shows
PAGES = [("dashboard", "Dashboard"), ("pilot", "Pilot results"), ("yarn", "Yarn prices"), ("cotton", "Cotton prices"),
         ("intake", "Bring in prices"), ("rates", "Rate tables"), ("ratecard", "Mill rate card"), ("settings", "Calculation settings"),
         ("costsheets", "Mill cost sheets")]
POPUP_TABS = [("cost", "Create cost"), ("bulk", "Bulk upload"), ("compare", "Compare"), ("pack", "Negotiation pack")]
# the colours each theme gives (computed): the page's background, a page's text, a card
THEME = {"light": ("rgb(246, 244, 238)", "rgb(29, 37, 33)", "rgb(255, 255, 255)"), "dark": ("rgb(15, 21, 19)", "rgb(232, 237, 233)", "rgb(22, 30, 27)")}
# the browser may be offline from the web font; that is not a fault of the app
IGNORE = ("fonts.googleapis.com", "fonts.gstatic.com")
DRAWN = """sel => { const r = document.querySelector(sel); return !!r && r.textContent.trim() !== 'Loading...' && r.children.length > 0 }"""
SIDEWAYS = """sel => { const b = document.querySelector(sel); return Math.max(document.documentElement.scrollWidth - innerWidth,
    b ? b.scrollWidth - b.clientWidth : 0) }"""
PAGE_RULES = """() => [...document.styleSheets].some(ss => { try { return [...ss.cssRules].some(r => r instanceof CSSPageRule ||
    (r instanceof CSSMediaRule && [...r.cssRules].some(x => x instanceof CSSPageRule))); } catch (e) { return false; } })"""
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


def pdf_text(data):
    """The pages of a PDF: (count, landscape?, text)."""
    try:
        import pymupdf as fitz
    except ImportError:          # an older PyMuPDF
        import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    return doc.page_count, all(p.rect.width > p.rect.height for p in doc), "\n".join(p.get_text() for p in doc)


class App:
    """The app on a free port, on the given data folder, with extra settings; stopped by stop()."""

    def __init__(self, data, extra=None):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "RIGHTPRICE_DATA", "ANTHROPIC_API_KEY", "RIGHTPRICE_MCP_TOKEN",
                                                                "RIGHTPRICE_ADMINS", "WEBSITE_SITE_NAME", "WEBSITE_AUTH_ENABLED")}
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
        raise SystemExit("The app did not start: see " + self.log.name)

    def api(self, path, body=None, who=None, method=None):
        headers = {"Content-Type": "application/json"}
        if who:
            headers["X-MS-CLIENT-PRINCIPAL-NAME"] = who
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers,
                                     method=method or ("GET" if body is None else "POST"))
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if r.headers.get("content-type", "").startswith("application/json") else raw

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def main():
    sys.path.insert(0, HERE)
    from playwright.sync_api import sync_playwright

    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    data = tempfile.mkdtemp(prefix="rightprice-browser-")
    files = {"sheet": os.path.join(data, "mill sheet.xlsx"), "prices": os.path.join(data, "yarn prices.csv"), "costsheet": os.path.join(data, "cost sheets.xlsx")}
    with open(files["sheet"], "wb") as f:
        f.write(mill_sheet_file())
    with open(files["prices"], "w") as f:
        f.write("Count,Rate,Yarn\n40s,352,Combed compact\n60s,430,Combed compact\n")
    app = App(data)
    try:
        check("The app starts on a temporary folder and SQLite", app.api("/api/store")["store"] == "sqlite")
        with open(files["costsheet"], "wb") as f:
            f.write(cost_sheet_file(app.api("/api/costsheet/template")))
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

            # ---------------------------------------------------------------- 1. every page, in each look
            for theme, size, look in (("light", DESK, "light"), ("dark", DESK, "dark"), ("light", PHONE, "phone")):
                for addr, heading in PAGES:
                    page = tab(theme, size)
                    open_at(page, addr)
                    txt = page.inner_text(".pgbox")
                    title = page.inner_text(".main .title") if page.locator(".main .title").count() else ""
                    wide = page.evaluate(SIDEWAYS, ".pgbox") if size is PHONE else 0
                    hue, got = colours(page, theme, ".pgbox > .pg")
                    good = not page.errors and "could not be" not in txt and title == heading and wide <= 1 and hue
                    check(f"{heading} opens ({look})", good, "" if good else f"heading {title!r}, sideways {wide}px, colours {got}, console {page.errors[:3]}, text {txt[:100]!r}")
                    page.context.close()
                for tab_id, label in POPUP_TABS:
                    page = tab(theme, size)
                    open_at(page, f"dashboard?new={tab_id}", ".popup .pgbox > .pg")
                    on = page.locator(".popup .ptab.on").inner_text() if page.locator(".popup .ptab.on").count() else ""
                    txt = page.inner_text(".popup .pgbox")
                    if tab_id == "pack" and txt.startswith("The list is empty"):
                        # with nothing in the list the server refuses a pack (400) and the page says why: that refusal is expected
                        page.errors = [e for e in page.errors if "status of 400" not in e]
                    wide = page.evaluate(SIDEWAYS, ".popup .pgbox") if size is PHONE else 0
                    hue, got = colours(page, theme, ".popup .pgbox > .pg")
                    good = not page.errors and on == label and "could not be" not in txt and wide <= 1 and hue
                    check(f"New cost > {label} opens ({look})", good, "" if good else f"tab {on!r}, sideways {wide}px, colours {got}, console {page.errors[:3]}, text {txt[:100]!r}")
                    page.context.close()
                page = tab(theme, size)
                open_at(page, "rightcost", None)
                page.wait_for_selector(".grid tbody tr td .code")
                page.wait_for_timeout(500)
                check(f"Right cost lists the costings ({look})", not page.errors and page.locator(".grid tbody tr").count() >= 50 and page.evaluate(SIDEWAYS, ".main") <= 1, str(page.errors[:3]))
                page.locator(".grid tbody tr td .code").first.click()
                page.wait_for_selector(".dhead h1")
                check(f"A fabric's page opens ({look})", not page.errors and page.locator(".main .tabs .tab").count() == 4 and page.evaluate(SIDEWAYS, ".main") <= 1, str(page.errors[:3]))
                page.context.close()
                page = tab(theme, size)
                open_at(page, "lib/Payment terms", None)
                page.wait_for_selector(".main .title")
                check(f"A setup list opens ({look})", not page.errors and page.inner_text(".main .title") == "Payment terms", str(page.errors[:3]))
                page.context.close()

            # ---------------------------------------------------------------- 2. the main paths, each in a fresh tab
            # Create cost: the example; a chart's tooltip and Escape; Print
            page = tab()
            open_at(page, "dashboard")
            page.click(".fab")
            page.wait_for_selector(".popup .step")
            check("New cost opens on Create cost", page.get_attribute(".scrim[data-popup]", "data-tab") == "cost" and "new=cost" in page.url)
            page.click(".popup button:has-text('Load the example')")
            page.wait_for_selector(".popup .hero .big")
            big = page.inner_text(".popup .hero .big")
            check("Create cost: the example (Qlty-1) costs Rs 181.40 a metre", big.strip() == "Rs 181.40 / m", big)
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
            during = page.evaluate("""() => [document.body.classList.contains('printing'), document.documentElement.dataset.theme,
                !!document.querySelector('.cost-out .print-stamp'), [...document.querySelectorAll('style')].some(s => /@page \\{ margin: 14mm/.test(s.textContent))]""")
            count, _, text = pdf_text(page.pdf())
            page.evaluate("dispatchEvent(new Event('afterprint'))")
            after = page.evaluate("""() => [document.body.classList.contains('printing'), [...document.querySelectorAll('style')].some(s => /@page/.test(s.textContent))]""")
            check("Create cost: Print lays out the cost alone (light, stamped, every table open), then puts the page back",
                  during == [True, "light", True, True] and "Rs 181.40" in text and "printed" in text and "Load the example" not in text
                  and "Settings and account" not in text and "Table of every line" in text and after == [False, False], f"{during} {count} pages {after}")
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

            # Bulk upload: a mill sheet, its rows, its alert and the rail's count
            page = tab()
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
            during = page.evaluate("""() => [document.body.classList.contains('printing-pack'), [...document.querySelectorAll('style')].some(s => /A4 landscape/.test(s.textContent))]""")
            count, landscape, text = pdf_text(page.pdf(prefer_css_page_size=True))
            page.evaluate("dispatchEvent(new Event('afterprint'))")
            check("Negotiation pack: Print gives the pack alone on A4 landscape, then puts the page back", during == [True, True] and landscape and "negotiation pack" in text
                  and "Back to the list" not in text and "Settings and account" not in text and not page.evaluate("document.body.classList.contains('printing-pack')"), f"{during} {count} pages")
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

            # the Dashboard's mill names, and the supplier page on paper
            page = tab()
            open_at(page, "dashboard")
            page.wait_for_selector(".pg .alert-head .linkish")
            page.locator(".pg .alert-head .linkish").first.click()
            page.wait_for_selector(".dhead h1")
            page.wait_for_timeout(500)
            count, _, text = pdf_text(page.pdf())
            check("Dashboard: a mill's name opens its supplier page", "#supplier/" in page.url and "Questions for the next meeting" in page.inner_text(".main"))
            check("The supplier page prints with no page's print rules but its own (no @page set anywhere)", not page.evaluate(PAGE_RULES)
                  and "Questions for the next meeting" in text and count >= 1, f"{count} pages")
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
            page = tab()
            open_at(page, "intake")
            market = len(app.api("/api/table/Market_Yarn")["rows"])
            page.set_input_files("#in-file", files["prices"])
            page.wait_for_selector(".pg table.edit tbody tr, #map-count")
            if page.locator("#map-count").count():          # a table was read: say which column is which, then review
                page.select_option("#map-count", "Count")
                page.select_option("#map-low", "Rate")
                page.select_option("#map-yarn", "Yarn")
                page.click(".pg button:has-text('Send to review')")
                page.wait_for_selector(".pg table.edit tbody tr")
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
            page.context.close()

            # a bookmark of the retired earlier screens
            page = tab()
            page.goto(f"{app.base}/classic/")
            page.wait_for_function(DRAWN, arg=".pgbox > .pg", timeout=60000)
            check("A bookmark of the retired /classic opens the app", page.url.rstrip("/").split("#")[0] == app.base and page.inner_text(".main .title") == "Dashboard"
                  and not page.errors, page.url)
            page.context.close()
            browser.close()
        app.stop()

        # ---------------------------------------------------------------- 3. users and roles on (stage 3)
        app = App(data, {"RIGHTPRICE_ADMINS": "gp@example.com"})
        for email, role in (("v@example.com", "Viewer"), ("b@example.com", "Buyer")):
            app.api("/api/users/add", {"email": email, "role": role, "name": role}, who="gp@example.com")
        with sync_playwright() as p:
            browser = p.chromium.launch()

            def offered(who):
                """What a person sees offered on each page that has something to change."""
                ctx = browser.new_context(viewport=DESK, extra_http_headers={"X-MS-CLIENT-PRINCIPAL-NAME": who})
                ctx.add_init_script(INIT)
                page = ctx.new_page()
                page.set_default_timeout(30000)
                errors = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not any(x in (m.text + str(m.location)) for x in IGNORE) else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                seen = {}

                def at(address, where=".pgbox > .pg"):
                    page.goto(f"{app.base}/?at={time.time()}#{address}")
                    page.wait_for_function(DRAWN, arg=where, timeout=60000)
                    page.wait_for_timeout(700)
                    return page.locator(where)

                box = at("yarn")
                seen["edit rates"] = box.locator("button:has-text('Edit'):visible").count() > 0
                seen["bring in prices"] = box.locator("a:has-text('Bring in prices')").count() > 0 or page.locator(".main .tab:has-text('Bring in prices')").count() > 0
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
                intake = at("intake", ".main")
                seen["intake page"] = "not open to your role" not in intake.inner_text()
                ctx.close()
                return seen, [e for e in errors if "403" in e or "401" in e]

            want = {"Viewer": set(), "Buyer": {"mark seen", "list upload", "list remove", "add to list", "cost sheet upload"},
                    "Admin": {"edit rates", "bring in prices", "rate tables edit", "add cotton", "cost sheet upload", "apply drafts", "mark seen",
                              "list upload", "list remove", "add to list", "intake page"}}
            for who, role in (("v@example.com", "Viewer"), ("b@example.com", "Buyer"), ("gp@example.com", "Admin")):
                seen, refused = offered(who)
                got = {k for k, v in seen.items() if v}
                check(f"Roles: {'an' if role[0] in 'AEIOU' else 'a'} {role} is offered exactly what the role may do, and no page asks the server for what it refuses",
                      got == want[role] and not refused, f"offered {sorted(got)}, refused {refused[:3]}")
            browser.close()
    finally:
        app.stop()
        if ok:
            shutil.rmtree(data, ignore_errors=True)
        else:
            print(f"The servers' logs and the data are kept in {data}")
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
