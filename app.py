"""RightPrice: fabric should-cost tool, version 1.  Run: streamlit run app.py"""
import datetime as dt
import html
import io
import os

import pandas as pd
import plotly.express as px
import streamlit as st

import masters
import price_import as pi

st.set_page_config(page_title="RightPrice", page_icon="🧵", layout="wide")

PURPLE = ["#5B4FC7", "#7468D4", "#8D83DD", "#A69EE6", "#BDB7EE", "#D2CEF4", "#E3E0F8"]
st.markdown("""
<style>
.sc-total{background:#5B4FC7;color:#fff;border-radius:10px;padding:18px 22px;margin:6px 0 14px 0}
.sc-total .big{font-size:34px;font-weight:700;line-height:1.1}
.sc-total .lbl{font-size:13px;opacity:.85}
.sc-row{display:flex;align-items:center;margin:7px 0;font-size:14px}
.sc-bar{height:30px;border-radius:6px;min-width:6px}
.sc-name{font-weight:600;margin-left:10px;white-space:nowrap}
.sc-pct{color:#5B4FC7;margin-left:10px;font-size:12px}
.sc-amt{font-weight:600;margin-left:10px;white-space:nowrap}
.sc-tag{display:inline-block;background:#FFF3CD;color:#7A5B00;border-radius:4px;padding:1px 7px;font-size:12px}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _load(mtime):
    return masters.load()


def get_masters():
    if not os.path.exists(masters.MASTER_PATH):
        masters.load()
    return _load(os.path.getmtime(masters.MASTER_PATH))


def save_sheet(name, df):
    m = dict(get_masters())
    m[name] = df
    masters.save(m)
    st.cache_data.clear()


def read_log():
    if os.path.exists(masters.LOG_PATH):
        return pd.read_csv(masters.LOG_PATH)
    return pd.DataFrame(columns=["Saved on", "Fabric code", "Description", "Supplier", "Should-cost Rs/m",
                                 "Should-cost Rs/kg", "Quoted Rs/m", "Gap Rs/m", "Gap %"])


def rupee(v, d=2):
    return f"Rs {v:,.{d}f}"


def placeholder_count(m):
    n = 0
    for df in m.values():
        if "Basis" in df.columns:
            n += int(df["Basis"].astype(str).str.startswith("Placeholder").sum())
    return n


def cost_view(res, title):
    """The cost picture: headline, one bar per bucket, second-level detail under each."""
    q = ""
    if res["quote"] is not None:
        word = "above" if res["gap"] >= 0 else "below"
        q = (f"<div class='lbl' style='margin-top:8px'>Quote {rupee(res['quote'])}/m is "
             f"{rupee(abs(res['gap']))} ({abs(res['gap_pct']):.1%}) {word} should-cost</div>")
    st.markdown(
        f"<div class='sc-total'><div class='lbl'>{html.escape(title)} &nbsp;·&nbsp; ex-mill should-cost</div>"
        f"<div class='big'>{rupee(res['total_per_m'])} / m</div>"
        f"<div class='lbl'>{rupee(res['per_kg'], 0)} / kg &nbsp;·&nbsp; about {res['gsm']:.0f} g/m² "
        f"&nbsp;·&nbsp; {res['finished_g_per_m']:.0f} g per running metre</div>{q}</div>",
        unsafe_allow_html=True)

    top = max(b["pct"] for b in res["buckets"]) or 1
    rows = ""
    for i, b in enumerate(res["buckets"]):
        w = max(1.0, 62 * b["pct"] / top)
        rows += (f"<div class='sc-row'><div class='sc-bar' style='width:{w:.1f}%;background:{PURPLE[i % 7]}'></div>"
                 f"<span class='sc-name'>{b['name']}</span><span class='sc-pct'>{b['pct']:.0%}</span>"
                 f"<span class='sc-amt'>{rupee(b['amount'])} / m</span></div>")
    st.markdown(rows, unsafe_allow_html=True)

    st.markdown("##### Second-level detail")
    for b in res["buckets"]:
        with st.expander(f"{b['name']}  ·  {rupee(b['amount'])} / m  ·  {b['pct']:.1%}"):
            d = pd.DataFrame(b["lines"]).rename(columns={"name": "Line", "basis": "How it is worked out",
                                                         "amount": "Rs/m"})
            d["Share of total"] = d["Rs/m"] / res["total_per_m"]
            st.dataframe(d.style.format({"Rs/m": "{:.2f}", "Share of total": "{:.1%}"}),
                         hide_index=True, use_container_width=True)

    with st.expander("Rates used and where each came from"):
        st.dataframe(pd.DataFrame(res["rates_used"]).astype(str), hide_index=True, use_container_width=True)
    if res["placeholders"]:
        st.warning("Placeholder rates were used for: " + ", ".join(res["placeholders"])
                   + ". These are starting guesses with no data behind them; treat this cost as provisional.")


def cost_sheet_xlsx(sel, res):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summ = [("Fabric code", sel.get("Fabric code")), ("Description", sel.get("Description")),
                ("Supplier", sel.get("Supplier")), ("Should-cost Rs/m", round(res["total_per_m"], 2)),
                ("Should-cost Rs/kg", round(res["per_kg"], 1)), ("Approx. GSM", round(res["gsm"], 1)),
                ("Quoted Rs/m", res["quote"]), ("Gap Rs/m", None if res["gap"] is None else round(res["gap"], 2))]
        summ += [(b["name"] + " Rs/m", round(b["amount"], 2)) for b in res["buckets"]]
        pd.DataFrame(summ, columns=["Item", "Value"]).to_excel(xw, sheet_name="Cost view", index=False)
        lines = [{"Bucket": b["name"], "Line": l["name"], "How it is worked out": l["basis"],
                  "Rs/m": round(l["amount"], 2)} for b in res["buckets"] for l in b["lines"]]
        pd.DataFrame(lines).to_excel(xw, sheet_name="Second level", index=False)
        pd.DataFrame(res["rates_used"]).astype(str).to_excel(xw, sheet_name="Rates used", index=False)
        pd.DataFrame([{"Input": k, "Value": v} for k, v in sel.items()]).astype(str).to_excel(xw, sheet_name="Inputs", index=False)
    return buf.getvalue()


# ------------------------------------------------------------------ pages
def page_dashboard(m):
    st.title("Dashboard")
    log = read_log()
    yr = m["Yarn_Rates"].set_index("Yarn key")
    cot = m["Cotton_Prices"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fabrics costed and saved", len(log))
    gaps = pd.to_numeric(log["Gap %"], errors="coerce").dropna()
    c2.metric("Average quote gap", f"{gaps.mean():.1f}%" if len(gaps) else "—")
    c3.metric("Cotton 40S in yarn master", f"Rs {yr.loc['Cotton 40S', 'Rate Rs/kg']:,.0f}/kg"
              if "Cotton 40S" in yr.index else "—")
    if len(cot):
        last = cot.iloc[-1]
        c4.metric("Shankar-6 cotton", f"Rs {float(last['Price']):,.0f}/candy", help=f"As of {last['Date']}")
    else:
        c4.metric("Shankar-6 cotton", "—")

    n = placeholder_count(m)
    if n:
        st.info(f"{n} rates in the rate tables are placeholders (starting guesses). "
                "They are marked in the Basis column on the Rate tables page.")

    st.subheader("Saved costings")
    if len(log):
        st.dataframe(log, hide_index=True, use_container_width=True)
        withq = log.dropna(subset=["Quoted Rs/m"])
        if len(withq):
            d = withq.melt(id_vars="Fabric code", value_vars=["Should-cost Rs/m", "Quoted Rs/m"],
                           var_name="", value_name="Rs/m")
            fig = px.bar(d, x="Fabric code", y="Rs/m", color="", barmode="group",
                         color_discrete_sequence=["#5B4FC7", "#F0A63A"])
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Nothing saved yet. Cost a fabric and press Save to dashboard.")

    st.subheader("Supplier cost ratios, % of sales")
    st.caption("Whole-company figures from published accounts; they include yarn, garments and other businesses.")
    st.dataframe(m["Supplier_Benchmarks"], hide_index=True, use_container_width=True)


def page_cost(m):
    st.title("Cost a fabric")
    L = masters.lists(m)
    a, b, c = st.columns(3)
    with a:
        st.markdown("**Fabric**")
        code = st.text_input("Fabric code", "Qlty-1")
        desc = st.text_input("Description", "100% Cotton 40x40 / 132x84 Dobby YD shirting")
        supplier = st.text_input("Supplier", "")
        route = st.selectbox("Route", L["Route"])
        weave = st.selectbox("Weave", L["Weave"], index=L["Weave"].index("Dobby") if "Dobby" in L["Weave"] else 0)
        pattern = st.selectbox("Pattern", L["Pattern"], index=L["Pattern"].index("Check") if "Check" in L["Pattern"] else 0)
        finish = st.selectbox("Finish", L["Finish"])
    yd = route == "Yarn Dyed"
    with b:
        st.markdown("**Yarn**")
        i40 = L["Yarn"].index("Cotton 40S") if "Cotton 40S" in L["Yarn"] else 0
        warp = st.selectbox("Warp yarn", L["Yarn"], index=i40)
        weft = st.selectbox("Weft yarn", L["Yarn"], index=i40)
        di = L["Yarn shade"].index("Medium" if yd else "Undyed")
        warp_shade = st.selectbox("Warp yarn dyeing", L["Yarn shade"], index=di, key=f"ws{yd}")
        weft_shade = st.selectbox("Weft yarn dyeing", L["Yarn shade"], index=di, key=f"fs{yd}")
        piece_shade = st.selectbox("Piece shade", L["Piece shade"], index=1, disabled=route != "Piece Dyed")
        st.markdown("**Mill and order**")
        loom = st.selectbox("Loom type", L["Loom type"])
        tier = st.selectbox("Mill tier", L["Mill tier"])
        slab = st.selectbox("Order size", L["Order size"])
    with c:
        st.markdown("**Construction**")
        epi = st.number_input("Ends per inch (EPI)", min_value=1.0, value=132.0, step=1.0)
        ppi = st.number_input("Picks per inch (PPI)", min_value=1.0, value=84.0, step=1.0)
        width = st.number_input("Finished width (inch)", min_value=1.0, value=58.0, step=0.5)
        reed = st.number_input("Reed space (inch), 0 = work out from width", min_value=0.0, value=67.0, step=0.5)
        st.markdown("**Compare and overrides (optional)**")
        quote = st.number_input("Supplier's quoted price (Rs/m), 0 = none", min_value=0.0, value=0.0, step=1.0)
        extra = st.number_input("Extra charge (Rs/m)", min_value=0.0, value=0.0, step=1.0)
        wv_over = st.number_input("Weaving rate override (Rs/pick), 0 = use table", min_value=0.0, value=0.0,
                                  step=0.01, format="%.3f")

    sel = {"Fabric code": code, "Description": desc, "Supplier": supplier, "Route": route, "Weave": weave,
           "Pattern": pattern, "Finish": finish, "Warp yarn": warp, "Weft yarn": weft,
           "Warp yarn dyeing": warp_shade, "Weft yarn dyeing": weft_shade, "Piece shade": piece_shade,
           "EPI": epi, "PPI": ppi, "Finished width (in)": width, "Reed space (in)": reed or None,
           "Loom type": loom, "Mill tier": tier, "Order size": slab, "Quoted price (Rs/m)": quote or None,
           "Extra charge (Rs/m)": extra or None, "Weaving rate override (Rs/pick)": wv_over or None}
    st.divider()
    try:
        res = masters.cost(sel, m)
    except Exception as e:
        st.error(f"Cannot cost this fabric: {e}")
        return
    cost_view(res, f"{code} — {desc}" if desc else code)

    s1, s2, _ = st.columns([1, 1, 3])
    if s1.button("Save to dashboard", type="primary"):
        log = read_log()
        row = {"Saved on": dt.date.today().isoformat(), "Fabric code": code, "Description": desc,
               "Supplier": supplier, "Should-cost Rs/m": round(res["total_per_m"], 2),
               "Should-cost Rs/kg": round(res["per_kg"], 1), "Quoted Rs/m": res["quote"],
               "Gap Rs/m": None if res["gap"] is None else round(res["gap"], 2),
               "Gap %": None if res["gap_pct"] is None else round(res["gap_pct"] * 100, 1)}
        pd.concat([log, pd.DataFrame([row])], ignore_index=True).to_csv(masters.LOG_PATH, index=False)
        st.success("Saved.")
    s2.download_button("Download cost sheet", cost_sheet_xlsx(sel, res), f"Should cost {code}.xlsx")


def page_bulk(m):
    st.title("Bulk upload")
    st.write("Cost many fabrics at once. The template's drop-downs carry the same lists as the tool.")
    st.download_button("Download upload template", masters.make_template(m), "Should_Cost_Upload_Template.xlsx")
    up = st.file_uploader("Upload the filled template", type=["xlsx"])
    if not up:
        return
    try:
        df = pd.read_excel(up, sheet_name="Fabrics")
    except Exception as e:
        st.error(f"Could not read a 'Fabrics' sheet from this file: {e}")
        return
    df = df.dropna(how="all")
    missing = [c for c, _, req in masters.TEMPLATE_COLUMNS if req and c not in df.columns]
    if missing:
        st.error("Required columns are missing: " + ", ".join(missing))
        return
    out = masters.cost_many(df, m)
    bad = out[out["Error"] != ""]
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows read", len(out))
    c2.metric("Costed", len(out) - len(bad))
    c3.metric("Rejected", len(bad))
    if len(bad):
        st.warning("Rejected rows are listed with the reason in the Error column.")
    st.dataframe(out, hide_index=True, use_container_width=True)
    buf = io.BytesIO()
    out.to_excel(buf, index=False)
    st.download_button("Download results", buf.getvalue(), "Should_Cost_Results.xlsx")
    good = out[out["Error"] == ""]
    if len(good):
        pick = st.selectbox("Open the cost view for", good["Fabric code"].astype(str).tolist())
        row = df[df["Fabric code"].astype(str) == pick].iloc[0].to_dict()
        cost_view(masters.cost(row, m), pick)


def page_yarn(m):
    st.title("Yarn prices")
    st.subheader("Yarn master (used in every costing)")
    st.caption("Edit a rate, update its date, then press Save. New rows become available in the drop-downs.")
    ed = st.data_editor(m["Yarn_Rates"], num_rows="dynamic", hide_index=True, use_container_width=True, key="yarn_ed")
    if st.button("Save yarn master", type="primary"):
        save_sheet("Yarn_Rates", ed)
        st.success("Yarn master saved.")

    st.subheader("Market reference")
    mk = m["Market_Yarn"]
    st.dataframe(mk, hide_index=True, use_container_width=True)
    rows = []
    cc = mk[mk["Yarn"] == "Cotton combed compact"]
    for _, y in m["Yarn_Rates"].iterrows():
        if str(y["Blend"]) != "Cotton":
            continue
        hit = cc[cc["Count"].astype(str).str.lower() == str(y["Count"]).lower()]
        if len(hit):
            lo, hi = float(hit["Low Rs/kg"].iloc[0]), float(hit["High Rs/kg"].iloc[0])
            rate = float(y["Rate Rs/kg"])
            where = "inside range" if lo <= rate <= hi else ("above market" if rate > hi else "below market")
            rows.append({"Yarn key": y["Yarn key"], "Master Rs/kg": rate, "Market low": lo, "Market high": hi,
                         "Position": where})
    if rows:
        st.markdown("**Master against market, combed compact cotton**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    with st.expander("Add or edit market reference rows"):
        ed2 = st.data_editor(mk, num_rows="dynamic", hide_index=True, use_container_width=True, key="mk_ed")
        if st.button("Save market reference"):
            save_sheet("Market_Yarn", ed2)
            st.success("Market reference saved.")
    st.divider()
    import_section(m)


def _stage(df, note=None):
    """Put rows read from any source into the review table."""
    st.session_state["price_stage"] = df if len(df) else pi.empty_stage()
    st.session_state["price_stage_note"] = note
    st.session_state["price_stage_ver"] = st.session_state.get("price_stage_ver", 0) + 1


def _column_mapper(df, source, key):
    df = df.rename(columns=str)
    st.dataframe(df.head(15), hide_index=True, use_container_width=True)
    cols = [None] + list(df.columns)
    c1, c2, c3, c4, c5 = st.columns(5)
    count_col = c1.selectbox("Count column", cols, key=f"{key}_c")
    low_col = c2.selectbox("Rate (or low) column", cols, key=f"{key}_l")
    high_col = c3.selectbox("High rate column", cols, key=f"{key}_h")
    yarn_col = c4.selectbox("Yarn description column", cols, key=f"{key}_y")
    date_col = c5.selectbox("Date column", cols, key=f"{key}_d")
    if st.button("Send to review table", key=f"{key}_go"):
        if not count_col or not low_col:
            st.error("Choose at least the count column and the rate column.")
        else:
            _stage(pi.map_columns(df, count_col, low_col, high_col, yarn_col, date_col, source))


def import_section(m):
    st.subheader("Bring in yarn prices")
    st.caption("Any source ends in the review table below. Nothing reaches the market reference until you "
               "press Add, and the yarn master is never changed from here.")
    t_xl, t_pdf, t_img, t_web, t_api = st.tabs(["Excel or CSV", "PDF", "Image", "Web link", "API"])
    with t_xl:
        up = st.file_uploader("Price list file", type=["xlsx", "xls", "csv"], key="pi_xl")
        if up:
            try:
                sheets = pi.read_table_file(up.name, up.getvalue())
                name = st.selectbox("Sheet", list(sheets), key="pi_xl_sheet")
                _column_mapper(sheets[name], up.name, "xl")
            except Exception as e:
                st.error(f"Could not read this file: {e}")
    with t_pdf:
        up = st.file_uploader("Price circular (PDF)", type=["pdf"], key="pi_pdf")
        if up:
            data = up.getvalue()
            try:
                rows, info = pi.read_pdf(data, up.name)
                if info["scanned"]:
                    st.warning(f"This PDF is a scan ({info['pages']} pages, no readable text). "
                               "Type the rates into the review table while looking at the page.")
                    pg = st.number_input("Page", 1, info["pages"], 1, key="pi_pdf_pg")
                    st.image(pi.pdf_page_image(data, pg - 1), use_container_width=True)
                else:
                    st.success(f"Read {len(rows)} price lines from {info['pages']} pages. Check them below.")
                    if info["image_pages"]:
                        st.warning(f"{info['image_pages']} of the pages are pictures with no readable text; "
                                   "rates on those pages are not in the table and need typing in.")
                        pg = st.number_input("Show page", 1, info["pages"], 1, key="pi_pdf_pg2")
                        st.image(pi.pdf_page_image(data, pg - 1), use_container_width=True)
                if st.button("Send to review table", key="pi_pdf_go"):
                    pi.keep_file(up.name, data)
                    _stage(rows, up.name)
            except Exception as e:
                st.error(f"Could not read this PDF: {e}")
    with t_img:
        up = st.file_uploader("Photo or screenshot of a price list", type=["png", "jpg", "jpeg", "webp"], key="pi_img")
        if up:
            st.image(up.getvalue(), use_container_width=True)
            st.info("This version cannot read text from pictures. Type the rates into the review table "
                    "while looking at the picture; the picture is kept with the tool as the source.")
            if st.button("Keep picture and open review table", key="pi_img_go"):
                pi.keep_file(up.name, up.getvalue())
                _stage(pi.empty_stage(), up.name)
    with t_web:
        url = st.text_input("Page address", key="pi_url", placeholder="https://...")
        if st.button("Read page", key="pi_url_go") and url:
            try:
                kind, payload = pi.fetch_link(url)
                st.session_state["pi_web"] = (kind, payload, url)
            except Exception as e:
                st.session_state.pop("pi_web", None)
                st.error(f"Could not read this page: {e}. Pages behind a login cannot be read.")
        if "pi_web" in st.session_state:
            kind, payload, src = st.session_state["pi_web"]
            if kind == "pdf":
                rows, info = pi.read_pdf(payload, src)
                st.write(f"The link is a PDF with {info['pages']} pages; {len(rows)} price lines read.")
                if st.button("Send to review table", key="pi_webpdf_go"):
                    _stage(rows, src)
            else:
                tables, text = payload
                if tables:
                    i = st.selectbox("Table on the page", range(len(tables)), key="pi_web_tbl",
                                     format_func=lambda i: f"Table {i + 1} ({len(tables[i])} rows)")
                    _column_mapper(tables[i], src, "web")
                else:
                    rows = pi.rows_from_text(text, src)
                    st.write(f"No tables on the page; {len(rows)} price-like lines found in its text.")
                    if st.button("Send to review table", key="pi_webtxt_go"):
                        _stage(rows, src)
    with t_api:
        st.caption("For a price service that returns JSON. The key is used for the call and is not saved.")
        a1, a2, a3 = st.columns([3, 1, 2])
        api_url = a1.text_input("Endpoint address", key="pi_api_url")
        hname = a2.text_input("Header name", key="pi_api_h", placeholder="x-api-key")
        hval = a3.text_input("Header value", key="pi_api_v", type="password")
        if st.button("Call", key="pi_api_go") and api_url:
            try:
                st.session_state["pi_api"] = (pi.fetch_api(api_url, hname, hval), api_url)
            except Exception as e:
                st.session_state.pop("pi_api", None)
                st.error(f"The call failed: {e}")
        if "pi_api" in st.session_state:
            df, src = st.session_state["pi_api"]
            _column_mapper(df, src, "api")

    if "price_stage" in st.session_state:
        st.markdown("**Review table**")
        note = st.session_state.get("price_stage_note")
        if note:
            st.caption(f"Source: {note}")
        ed = st.data_editor(st.session_state["price_stage"], num_rows="dynamic", hide_index=True,
                            use_container_width=True, key=f"stage_ed_{st.session_state.get('price_stage_ver', 0)}")
        b1, b2, _ = st.columns([2, 1, 4])
        if b1.button("Add to market reference", type="primary"):
            good = pi.clean_stage(ed)
            if good.empty:
                st.error("No complete rows: each row needs a count and a rate.")
            else:
                if note:
                    good["Source"] = good["Source"].fillna(note)
                save_sheet("Market_Yarn", pd.concat([m["Market_Yarn"], good], ignore_index=True))
                del st.session_state["price_stage"]
                st.success(f"{len(good)} rows added to the market reference.")
                st.rerun()
        if b2.button("Discard"):
            del st.session_state["price_stage"]
            st.rerun()


def page_cotton(m):
    st.title("Cotton prices")
    cot = m["Cotton_Prices"].copy()
    if cot.empty:
        st.info("No cotton price history loaded yet. Add rows below.")
    else:
        cot["Date"] = pd.to_datetime(cot["Date"], errors="coerce")
        cot = cot.dropna(subset=["Date"]).sort_values("Date")
        last = cot.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("Latest Shankar-6", f"Rs {float(last['Price']):,.0f}/candy", help=str(last["Date"].date()))
        c2.metric("As of", str(last["Date"].date()))
        prev = cot[cot["Date"] <= last["Date"] - pd.Timedelta(days=365)]
        if len(prev):
            c3.metric("Change over 12 months", f"{float(last['Price']) / float(prev.iloc[-1]['Price']) - 1:+.1%}")
        fig = px.line(cot, x="Date", y="Price", color_discrete_sequence=["#5B4FC7"])
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="Rs per candy")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Source: " + str(last["Source"]) + ". One candy is 355.6 kg of lint.")
        age = (pd.Timestamp.today() - last["Date"]).days
        if age > 30:
            st.warning(f"The latest cotton price is {age} days old. Add newer rows below.")
    with st.expander("Add or edit cotton price rows"):
        ed = st.data_editor(m["Cotton_Prices"].tail(30), num_rows="dynamic", hide_index=True,
                            use_container_width=True, key="cot_ed")
        if st.button("Save cotton prices"):
            full = pd.concat([m["Cotton_Prices"].iloc[:-30], ed], ignore_index=True)
            save_sheet("Cotton_Prices", full)
            st.success("Cotton prices saved.")


RATE_SHEETS = [("Weaving_Rates", "Weaving"), ("Weaving_Uplifts", "Pattern and loom uplifts"),
               ("Sizing_Rates", "Sizing"), ("Yarn_Dyeing", "Yarn dyeing"), ("Piece_Dyeing", "Piece dyeing"),
               ("Finishing_Rates", "Finishing"), ("Class_Defaults", "Crimp, wastage, overhead, margin"),
               ("Weaves", "Weave list"), ("Content_Groups", "Content groups")]


def page_rates(m):
    st.title("Rate tables")
    st.caption("Every drop-down choice looks up a number here. Basis shows where the number came from: "
               "V1 workbook, Placeholder (a starting guess) or Not set (zero until there is data).")
    for tab, (sheet, label) in zip(st.tabs([l for _, l in RATE_SHEETS]), RATE_SHEETS):
        with tab:
            ed = st.data_editor(m[sheet], num_rows="dynamic", hide_index=True, use_container_width=True,
                                key=f"ed_{sheet}")
            if st.button(f"Save {label.lower()}", key=f"sv_{sheet}"):
                save_sheet(sheet, ed)
                st.success("Saved.")


def page_settings(m):
    st.title("Settings")
    for sheet, label in (("Settings", "Calculation settings"), ("Mill_Tier", "Mill tiers"),
                         ("Order_Slab", "Order size slabs")):
        st.subheader(label)
        df = m[sheet].astype({"Value": str}) if sheet == "Settings" else m[sheet]
        ed = st.data_editor(df, num_rows="fixed" if sheet == "Settings" else "dynamic", hide_index=True,
                            use_container_width=True, key=f"set_{sheet}")
        if st.button(f"Save {label.lower()}", key=f"svs_{sheet}"):
            if sheet == "Settings":
                ed = ed.copy()
                ed["Value"] = [pd.to_numeric(v, errors="coerce") if str(v).replace(".", "", 1).isdigit() else v
                               for v in ed["Value"]]
            save_sheet(sheet, ed)
            st.success("Saved.")
    st.subheader("About this version")
    st.markdown(
        "- Method: the corrected method of *Should be Cost V1 23rd Nov.xlsx*; it reproduces all seven "
        "earlier qualities to the paisa.\n"
        "- Price basis: ex-mill, so freight is left out.\n"
        "- Scope: woven fabrics costed per metre; cost per kg is derived from the estimated fabric weight.\n"
        f"- All rates live in one workbook: `{masters.MASTER_PATH}`")


PAGES = {"Dashboard": page_dashboard, "Cost a fabric": page_cost, "Bulk upload": page_bulk,
         "Yarn prices": page_yarn, "Cotton prices": page_cotton, "Rate tables": page_rates,
         "Settings": page_settings}

with st.sidebar:
    st.markdown("## 🧵 RightPrice")
    st.caption("Fabric should-cost · version 1 · ex-mill · woven")
    choice = st.radio("Go to", list(PAGES), label_visibility="collapsed")

PAGES[choice](get_masters())
