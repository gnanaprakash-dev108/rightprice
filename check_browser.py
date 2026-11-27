"""Checks the screens in a browser: every page of the shell opens, in light and dark and at phone width, with no error
in the browser's console, and the main paths work.

Run: python check_browser.py     It must print ALL OK. It needs Python's playwright package and its Chromium
(on GitHub: pip install playwright; python -m playwright install --with-deps chromium).

What it does: starts the app on a temporary data folder and a SQLite file in it (the rate master that comes with the
code; nothing in data/ is touched, and DATABASE_URL from the environment is never used), then in Chromium:
1. opens every page of the shell (Home, Prices, Right cost, a fabric's page, a supplier's page, a setup list) and
   every tab of the New cost popup, in light and in dark at 1366 x 900, and in light at phone width (390 x 844),
   and checks each one draws (no "could not be loaded", nothing left on "Loading..."), carries its heading, keeps
   the page from scrolling sideways on a phone, and leaves nothing in the console;
2. walks the main paths: cost a fabric (Load the example: Qlty-1 = Rs 181.40) and add it to the list; upload a mill
   sheet in Bulk upload and see its rows in the list; open a row in Create cost; compare two ticked rows; make the
   negotiation pack of the ticked rows; open a Right cost row and its Negotiation tab; close the popup with Escape.
"""
import io
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
# the browser may be offline from the web font; that is not a fault of the app
IGNORE = ("fonts.googleapis.com", "fonts.gstatic.com")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mill_sheet_file():
    """A mill's price sheet as it comes (the headings of mill_sheet.COLUMNS): two costed rows and one NYD row."""
    sys.path.insert(0, HERE)
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
    rows = [base, dict(base, **hi, **{"Fab Code": "B-2"}), dict(base, **{"Fab Code": "B-3", "YD/NYD": "NYD"})]
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=mill_sheet.COLUMNS).to_excel(buf, index=False)
    return buf.getvalue()


def main():
    from playwright.sync_api import sync_playwright

    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{name}: {'OK' if good else 'MISMATCH'} {detail}")

    data = tempfile.mkdtemp(prefix="rightprice-browser-")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "RIGHTPRICE_DATA", "ANTHROPIC_API_KEY", "RIGHTPRICE_MCP_TOKEN")}
    env.update(RIGHTPRICE_DATA=data, DATABASE_URL=f"sqlite:///{os.path.join(data, 'rightprice.db')}", PYTHONUNBUFFERED="1")
    log = open(os.path.join(data, "server.log"), "w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                              cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    sheet = os.path.join(data, "mill sheet.xlsx")
    with open(sheet, "wb") as f:
        f.write(mill_sheet_file())
    try:
        for _ in range(240):
            try:
                if urllib.request.urlopen(base + "/api/store", timeout=5).status == 200:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("The app did not start: see " + log.name)
        check("The app starts on a temporary folder and SQLite", "sqlite" in urllib.request.urlopen(base + "/api/store").read().decode().lower())

        with sync_playwright() as p:
            browser = p.chromium.launch()

            def new_page(theme, size):
                ctx = browser.new_context(viewport=size, device_scale_factor=1)
                ctx.add_init_script(f"try {{ localStorage.setItem('rp-theme', '{theme}'); }} catch (e) {{}}")
                page = ctx.new_page()
                page.errors = []
                page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" and not any(x in (m.text + str(m.location)) for x in IGNORE) else None)
                page.on("pageerror", lambda e: page.errors.append(str(e)))
                page.set_default_timeout(30000)
                return page

            drawn = """() => { const r = document.querySelector('.pgbox > .pg, .pgbox > .pgshell');
                return !!r && r.textContent.trim() !== 'Loading...' && r.children.length > 0 }"""

            def page_ok(page, label, heading, phone):
                """The page drew, says what it is, has no error in it or in the console, and fits a phone's width."""
                try:
                    page.wait_for_function(drawn, timeout=60000)
                    page.wait_for_timeout(600)
                except Exception as e:  # noqa: BLE001 - reported as a mismatch
                    page.errors.append(f"never drew: {e}")
                txt = page.inner_text(".pgbox")
                title = page.inner_text(".main .title") if page.locator(".main .title").count() else ""
                wide = page.evaluate("document.documentElement.scrollWidth - innerWidth") if phone else 0
                good = not page.errors and "could not be loaded" not in txt and "could not be read" not in txt and title == heading and wide <= 1
                check(label, good, "" if good else f"heading {title!r}, sideways {wide}px, console {page.errors[:3]}, text {txt[:120]!r}")
                page.errors.clear()

            # 1. every page, light and dark at a desk, light on a phone
            for theme, size, tag in (("light", DESK, "light"), ("dark", DESK, "dark"), ("light", PHONE, "phone")):
                page = new_page(theme, size)
                for addr, heading in PAGES:
                    page.goto(f"{base}/#{addr}")
                    page_ok(page, f"{heading} opens ({tag})", heading, size is PHONE)
                check(f"The theme is {theme} ({tag})", page.evaluate("document.documentElement.dataset.theme") == theme)
                for tab, label in POPUP_TABS:
                    page.goto(f"{base}/#dashboard?new={tab}")
                    try:
                        page.wait_for_function("() => { const r = document.querySelector('.popup .pgbox > .pg'); return !!r && r.textContent.trim() !== 'Loading...' }", timeout=60000)
                        page.wait_for_timeout(600)
                    except Exception as e:  # noqa: BLE001
                        page.errors.append(f"never drew: {e}")
                    on = page.locator(".popup .ptab.on").inner_text() if page.locator(".popup .ptab.on").count() else ""
                    txt = page.inner_text(".popup .pgbox")
                    if tab == "pack" and txt.startswith("The list is empty"):
                        # with nothing in the list the server refuses a pack (400) and the page says why: the refusal is expected
                        page.errors = [e for e in page.errors if "status of 400" not in e]
                    wide = page.evaluate("document.documentElement.scrollWidth - innerWidth") if size is PHONE else 0
                    good = not page.errors and on == label and "could not be loaded" not in txt and wide <= 1
                    check(f"New cost > {label} opens ({tag})", good, "" if good else f"tab {on!r}, sideways {wide}px, console {page.errors[:3]}, text {txt[:120]!r}")
                    page.errors.clear()
                page.goto(f"{base}/#rightcost")
                page.wait_for_selector(".grid tbody tr td .code")
                page.wait_for_timeout(500)
                check(f"Right cost lists the costings ({tag})", not page.errors and page.locator(".grid tbody tr").count() >= 50, str(page.errors[:3]))
                page.errors.clear()
                page.goto(f"{base}/#lib/Payment terms")
                page.wait_for_timeout(800)
                check(f"A setup list opens ({tag})", not page.errors and page.locator(".main .title").inner_text() == "Payment terms", str(page.errors[:3]))
                page.errors.clear()
                page.context.close()

            # 2. the main paths, in light at a desk
            page = new_page("light", DESK)
            page.goto(f"{base}/#dashboard")
            page.wait_for_function(drawn, timeout=60000)
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
            page.click(".popup .hero .btn.primary")
            page.wait_for_function("() => document.querySelector('.popup .hero .btn.primary').textContent === 'Update in list'")
            check("Create cost: Add to list adds it", "Added to the list" in page.inner_text("#toast"))

            page.click(".popup .ptab:has-text('Bulk upload')")
            page.wait_for_selector(".popup #bulk-file")
            page.set_input_files(".popup #bulk-file", sheet)
            page.wait_for_selector(".popup .notice.info:has-text('added from a mill sheet')", timeout=60000)
            page.wait_for_function("() => [...document.querySelectorAll('.popup table.list td.s1')].some(td => td.textContent === 'B-3')")
            codes = page.locator(".popup table.list td.s1").all_inner_texts()
            notice = page.inner_text(".popup .notice.info")
            check("Bulk upload: a mill sheet's rows join the list", {"B-1", "B-2", "B-3"} <= set(codes) and "3 rows added" in notice, f"{notice} {codes}")
            check("Bulk upload: the NYD row is listed, not costed", "not costed" in page.locator(".popup table.list tr", has_text="B-3").inner_text())
            check("Bulk upload: a row above its range raises a quote alert", page.locator(".popup .notice.warn li", has_text="B-2").count() == 1)

            page.locator(".popup table.list td.s1 .linkish", has_text="B-1").click()
            page.wait_for_selector(".popup .hero .big")
            check("Bulk upload: Open carries the row on to Create cost", page.get_attribute(".scrim[data-popup]", "data-tab") == "cost"
                  and "B-1" in page.inner_text(".popup .hero .lbl") and page.locator(".popup .card.moved").count() == 1)

            page.click(".popup .ptab:has-text('Bulk upload')")
            page.wait_for_selector(".popup table.list")
            for code in ("B-1", "B-2"):
                page.locator(".popup table.list tr", has_text=code).locator("input[type=checkbox]").check()
            page.click(".popup .actionbar .btn:has-text('Compare')")
            page.wait_for_selector(".popup #cmp-b")
            page.wait_for_selector(".popup .notice.info:has-text('should-cost')")
            a_, b_ = page.locator("#cmp-a option:checked").inner_text(), page.locator("#cmp-b option:checked").inner_text()
            check("Compare: the two ticked rows are A and B", {a_[:3], b_[:3]} == {"B-1", "B-2"}, f"{a_} / {b_}")

            page.click(".popup .ptab:has-text('Bulk upload')")
            page.wait_for_selector(".popup table.list")
            page.click(".popup .actionbar a:has-text('Negotiation pack')")
            page.wait_for_selector(".popup .pack-title")
            check("Negotiation pack: made of the ticked rows", page.locator("#pack-scope option:checked").inner_text() == "Rows ticked on the list (2)"
                  and "negotiation pack" in page.inner_text(".popup .pack-title") and page.locator(".popup .pack-table tbody tr").count() == 2)
            page.click(".popup a:has-text('Back to the list')")
            page.wait_for_selector(".popup table.list")
            check("Negotiation pack: Back to the list", page.get_attribute(".scrim[data-popup]", "data-tab") == "bulk")
            page.keyboard.press("Escape")
            page.wait_for_function("() => !document.querySelector('.scrim[data-popup]')")
            check("Escape closes the popup and the address follows", "new=" not in page.url)
            check("The rail counts the quote alerts", page.locator(".rail .badge").count() == 1)

            page.goto(f"{base}/#rightcost")
            page.wait_for_selector(".grid tbody tr td .code")
            page.locator(".grid tbody tr td .code").first.click()
            page.wait_for_selector(".dhead h1")
            check("Right cost: a row opens its own page", "#item/" in page.url and page.locator(".main .tabs .tab").count() == 4)
            page.click(".main .tabs .tab:has-text('Negotiation')")
            page.wait_for_function("() => { const b = document.querySelector('.brief'); return b && !/Working it out/.test(b.textContent) }", timeout=60000)
            check("Right cost: the fabric's Negotiation tab gives its brief", "should-cost" in page.inner_text(".brief"))
            page.click(".dicons button[aria-label='Open in Create cost']")
            page.wait_for_selector(".popup .hero .big")
            check("Right cost: Open in Create cost costs the row in the popup", page.get_attribute(".scrim[data-popup]", "data-tab") == "cost"
                  and "purchase order" in page.inner_text(".popup .pnote"))
            page.go_back()
            page.wait_for_function("() => !document.querySelector('.scrim[data-popup]')")
            check("Back closes the popup", "#item/" in page.url)

            page.goto(f"{base}/#dashboard")
            page.wait_for_function(drawn, timeout=60000)
            page.wait_for_selector(".pg .alert-head .linkish")
            page.locator(".pg .alert-head .linkish").first.click()
            page.wait_for_selector(".dhead h1")
            check("Dashboard: a mill's name opens its supplier page", "#supplier/" in page.url and "Questions for the next meeting" in page.inner_text(".main"))
            check("No error in the console on the main paths", not page.errors, str(page.errors[:5]))
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        if ok:
            shutil.rmtree(data, ignore_errors=True)
        else:
            print(f"The server's log and the data are kept in {data}")
    print("ALL OK" if ok else "SOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
