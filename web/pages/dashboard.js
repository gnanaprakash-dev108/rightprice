/* Home > Dashboard. Everything on it is the buyer's own data: purchase orders costed by the tool, the rate master,
   the cotton price history, the fabric list's quote alerts and the negotiation tracker. Nothing is an outside
   benchmark except panel 5, which says so. */
(function () {
  "use strict";
  const { h, fmt, rs, day, pct, pctSigned, plural, getJSON, postJSON, toast, withTip, dataTable, pageHead, GROUP_COLOR, can } = RP.kit;
  const state = RP.state;

  // a mill's name, opening its supplier page
  function millLink(name, key) {
    if (!key || !can("page:rightcost")) return name;
    return h("button", { type: "button", class: "linkish", title: "Open this mill's page: fabrics, money above the range, questions for the meeting", onclick: () => RP.shell.go("supplier/" + encodeURIComponent(key)) }, name);
  }
  // a gap is coloured only where the tool can be leaned on; elsewhere it is shown plainly with a caution
  function gapTag(gap, trust) {
    if (trust === "weak") return h("span", { class: "tag warn", title: "The tool fits past prices of this group poorly, so this gap says more about the tool than about the price" }, `${pctSigned(gap)} · tool unsure`);
    return h("span", { class: "tag " + (Math.abs(gap) <= 5 ? "flat" : gap > 0 ? "down" : "up"), title: Math.abs(gap) <= 5 ? "Within 5%: treat as noise" : gap > 0 ? "You paid above should-cost" : "You paid below should-cost" }, pctSigned(gap));
  }
  function yarnWhatIf(ins, list) {
    const ref = ins.reference, costed = list.rows.filter(r => r.should_cost !== null && r.inputs);
    const pick = h("select", { id: "wi-yarn" }, h("option", { value: "*" }, "All yarns"), state.meta.yarns.map(y => h("option", { value: y.key }, `${y.key} · Rs ${fmt(y.rate, 0)}/kg`)));
    const slider = h("input", { id: "wi-pct", type: "range", min: "-20", max: "20", step: "1", value: "5" });
    const num = h("input", { id: "wi-num", type: "number", min: "-50", max: "50", step: "1", value: "5", "aria-label": "Yarn price change, per cent" });
    const out = h("div", { class: "whatif-out", "aria-live": "polite" });
    let turn = 0;
    const run = async () => {
      const p = Number(num.value) || 0, mine = ++turn, key = pick.value;
      const parts = [];
      // the reference fabric: worked out here from its rupees per Rs 10 a kilo
      const uses = key === "*" || key === state.meta.example["Warp yarn"];
      const dRef = uses ? (ref.warp_per_10 * ref.warp_rate + ref.weft_per_10 * ref.weft_rate) / 10 * p / 100 : 0;
      parts.push(h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, "Reference shirting, 40s × 40s, 132 × 84"), h("b", { class: "num" }, `${rs(ref.total)} → ${rs(ref.total + dRef)}`), h("span", { class: "tag " + (dRef > 0.005 ? "down" : dRef < -0.005 ? "up" : "flat") }, uses ? `${dRef >= 0 ? "+" : "−"}${fmt(Math.abs(dRef))} /m (${pctSigned(dRef / ref.total * 100)})` : "does not use this yarn")));
      if (costed.length) {
        parts.push(h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `Your ${costed.length} listed fabrics`), h("b", { class: "num" }, "working out…")));
        out.replaceChildren(...parts);
        try {
          const v = await (await postJSON("/api/list", { yarn_pct: { [key]: p } })).json(); if (mine !== turn) return;
          const moved = v.rows.filter(r => r.should_cost !== null && (p === 0 || r.simulated !== null)).map(r => p === 0 ? Object.assign({}, r, { simulated: r.should_cost }) : r);
          const d = moved.map(r => r.simulated - r.should_cost), avg = d.reduce((a, x) => a + x, 0) / (d.length || 1), base = moved.reduce((a, r) => a + r.should_cost, 0) / (moved.length || 1);
          const hit = d.filter(x => Math.abs(x) >= 0.005).length;
          // the list is a tab of the New cost popup: the move goes with it
          const toList = () => { try { if (p) sessionStorage.setItem("rp-list-move", JSON.stringify({ yarn: key, pct: String(p) })); else sessionStorage.removeItem("rp-list-move"); } catch (e) { /* no handover */ } };
          parts[1] = h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `Your ${moved.length} listed fabrics, average`), h("b", { class: "num" }, `${rs(base)} → ${rs(base + avg)}`), h("span", { class: "tag " + (avg > 0.005 ? "down" : avg < -0.005 ? "up" : "flat") }, `${avg >= 0 ? "+" : "−"}${fmt(Math.abs(avg))} /m (${pctSigned(base ? avg / base * 100 : 0)})`), can("page:list") ? h("a", { href: "#bulk", class: "sub", style: "margin:0", onclick: toList }, p === 0 ? "see each in the list" : `${hit} of ${moved.length} use this yarn and move · see each in the list`) : p === 0 ? null : h("span", { class: "sub", style: "margin:0" }, `${hit} of ${moved.length} use this yarn and move`));
        } catch (e) { parts[1] = h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, "Your listed fabrics"), h("span", { class: "sub", style: "margin:0" }, e.message)); }
      }
      out.replaceChildren(...parts);
    };
    slider.addEventListener("input", () => { num.value = slider.value; run(); });
    num.addEventListener("input", () => { slider.value = Math.max(-20, Math.min(20, Number(num.value) || 0)); run(); });
    pick.addEventListener("change", run); run();
    return h("div", { class: "card whatif" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "If yarn prices move"), h("div", { class: "sub", style: "margin:2px 0 0" }, `A yarn price move does not reach the fabric in full. On the reference shirting, 10% on yarn is about ${(ref.yarn_share * 10).toFixed(1)}% on the fabric. Each Rs 10 a kilo on the warp yarn is ${rs(ref.warp_per_10)} a metre; on the weft, ${rs(ref.weft_per_10)}.`))),
      h("div", { class: "whatif-controls" }, h("div", { class: "field" }, h("label", { for: "wi-yarn" }, "Yarn"), pick), h("div", { class: "field grow" }, h("label", { for: "wi-pct" }, "Price change"), h("div", { class: "slider-row" }, h("span", { class: "sub", style: "margin:0" }, "−20%"), slider, h("span", { class: "sub", style: "margin:0" }, "+20%"), num, h("span", {}, "%")))),
      out);
  }

  RP.page("dashboard", { title: "Dashboard", section: "Home" }, async () => {
    const [ins, list] = await Promise.all([getJSON("/api/insights"), (await postJSON("/api/list", {})).json()]);
    state.list = list;
    const p = ins.pilot, nodes = [...pageHead("Dashboard", "What you pay against what it should cost, where the money goes, and what to ask before you negotiate. Panels 1, 2 and 4 are your purchase orders as Right cost costs them now: on the rates in use (the order month's dated yarn rate where there is one), worked out again at every rate edit or applied cost-sheet draft (every usual range comes from them); panel 3 is the cotton price history; panel 5 is from published accounts." + (ins.pilot_rates ? " " + ins.pilot_rates.replace(/^Panels 1, 2 and 4 are[^.]*\. */, "") : ""))];          // stage 5: and beside Right cost's rates
    // first: newly quoted fabrics that need a look before their price is accepted
    try {
      const box = h("div", { class: "card alerts", hidden: true });
      const seen = async body => { try { const a = await (await postJSON("/api/alerts/seen", body)).json(); last = JSON.stringify(a); paint(a); RP.shell.alertsChanged(); } catch (e) { toast(e.message, false); } };
      const open = { all: false, groups: new Set() };            // what the buyer has unfolded
      const marks = can("do:mark_seen"), toRightCost = can("page:rightcost");      // what this role may do (stage 3)
      const paint = a => {
        box.hidden = !a.count && !a.seen; box.classList.toggle("quiet", !a.count);
        if (!a.count) { box.replaceChildren(h("p", { class: "sub", style: "margin:0" }, `No quote alerts to look at. ${plural(a.seen, "alert")} marked seen. `, marks ? h("button", { type: "button", class: "linkish", onclick: () => seen({ restore: true }) }, "Bring them back") : null)); return; }
        const kinds = Object.entries(a.by_kind).filter(([, n]) => n).map(([k, n]) => `${n} ${a.kinds[k].toLowerCase()}`).join("; ");
        const money = [a.above_rows ? `Rs ${fmt(a.above_money, 0)} is quoted above the usual ranges on ${plural(a.above_rows, "row")}.` : null,
          a.sums_rows ? `On ${plural(a.sums_rows, "row")} the mills' own sums come to Rs ${fmt(a.sums_money, 0)} less than they ask` + (a.above_rows ? " (largely the same rupees seen another way: do not add the two)." : ".") : null,
          a.no_quantity ? `${plural(a.no_quantity, "flagged row")} with no quantity ${a.no_quantity === 1 ? "is" : "are"} in neither figure.` : null,
          a.repeat_rows ? `${plural(a.repeat_rows, "row")} repeating another order ${a.repeat_rows === 1 ? "is" : "are"} in neither figure either: if one is a real second order, its rupees are on its own line below.` : null].filter(Boolean).join(" ");
        const groups = open.all ? a.groups : a.groups.slice(0, 3);
        const row = r => h("li", {}, toRightCost ? h("button", { type: "button", class: "linkish", title: "Open this fabric", onclick: () => RP.shell.go("item/" + encodeURIComponent(r.key)) }, r.code) : h("b", {}, r.code),
          ...r.flags.map(f => h("div", { class: "alert-flag" }, h("span", { class: "tag " + (f.kind === "low" || f.kind === "repeat" ? "warn" : "down") }, a.kinds[f.kind]), " " + f.text)));
        box.replaceChildren(...[h("div", { class: "card-head" }, h("div", {}, h("h2", {}, `${plural(a.count, "new quote")} to look at`),
            h("div", { class: "sub", style: "margin:2px 0 0" }, `Rows of the fabric list that need a look before their price is accepted: ${kinds}. ${money}`)),
            toRightCost ? h("button", { type: "button", class: "btn", onclick: () => RP.shell.showAlerts() }, "Show them in Right cost") : null),
          ...groups.map(g => { const gk = g.mill + "|" + g.upload, rows = open.groups.has(gk) ? g.rows : g.rows.slice(0, 3);
            return h("div", { class: "alert-group" }, h("div", { class: "alert-head" }, h("b", {}, millLink(g.supplier, g.mill)), h("span", { class: "sub", style: "margin:0" }, ` · ${g.upload} · ${plural(g.rows.length, "fabric")}`),
              marks ? h("button", { type: "button", class: "btn small", onclick: () => seen({ ids: g.rows.map(r => r.id) }) }, g.rows.length === 1 ? "Mark seen" : `Mark all ${g.rows.length} seen`) : null),
              h("ul", { class: "alert-list" }, ...rows.map(row)),
              g.rows.length > rows.length ? h("button", { type: "button", class: "linkish", onclick: () => { open.groups.add(gk); paint(a); } }, `Show the other ${g.rows.length - rows.length} from this upload (the largest sums are shown)`) : null); }),
          a.groups.length > groups.length ? h("p", { style: "margin:12px 0 0" }, h("button", { type: "button", class: "linkish", onclick: () => { open.all = true; paint(a); } }, `Show ${plural(a.groups.length - groups.length, "more upload")} (${plural(a.groups.slice(3).reduce((n, g) => n + g.rows.length, 0), "fabric")})`)) : null,
          h("p", { class: "sub", style: "margin:10px 0 0" }, "The newest upload is first. Worked out from the list as it stands, on today's rates. An alert goes when it is marked seen (for everyone), when its row is removed, or when its price is agreed in the tracker." + (a.seen ? ` ${plural(a.seen, "alert")} marked seen. ` : ""), a.seen && marks ? h("button", { type: "button", class: "linkish", onclick: () => seen({ restore: true }) }, "Bring them all back") : null)].filter(Boolean));
      };
      let last = JSON.stringify(await getJSON("/api/alerts")); paint(JSON.parse(last));
      nodes.push(box);
      const again = async () => { if (!box.isConnected) { clearInterval(timer); removeEventListener("focus", again); return; } if (document.hidden) return;
        try { const now = JSON.stringify(await getJSON("/api/alerts")); if (now !== last) { last = now; paint(JSON.parse(now)); } } catch (e) { /* next time */ } };
      const timer = setInterval(again, 30000); addEventListener("focus", again);
    } catch (e) { /* no alerts on this server yet */ }
    nodes.push(yarnWhatIf(ins, list));

    if (p) {
      // 1. cost per metre by fabric type
      const top = Math.max(...p.categories.map(c => Math.max(c.paid, c.should)));
      const rows = p.categories.map(c => h("tr", {}, h("td", {}, h("b", {}, c.route), " · ", c.weave), h("td", { class: "cmp-cell" }, h("div", { class: "cmp-bars", "aria-hidden": "true" }, h("div", { class: "cmp-bar", style: `width:${c.paid / top * 100}%;background:var(--total)` }), h("div", { class: "cmp-bar", style: `width:${c.should / top * 100}%;background:var(--g1)` }))),
        h("td", { class: "n" }, fmt(c.paid, 0)), h("td", { class: "n" }, fmt(c.should, 0)), h("td", { class: "n" }, gapTag(c.gap, c.trust)), h("td", { class: "n" }, c.p25 === undefined ? "" : `${pctSigned(c.p25)} to ${pctSigned(c.p75)}`), h("td", { class: "n" }, pct(c.within10, 0)), h("td", { class: "n" }, fmt(c.fabrics, 0))));
      nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "1. Cost per metre by fabric type"), h("div", { class: "sub", style: "margin:2px 0 0" }, `${fmt(p.fabrics, 0)} fabrics in 100% cotton, bought Aug to Nov 2026, averaged over the metres bought; fabric types with fewer than 20 fabrics are left out, so the rows add up to less. Dark bar: price paid. Blue bar: should-cost. Plus means you paid above should-cost. Paid above should-cost is the average over the metres; the middle half is by fabric, half of them priced between the two figures. The average can sit outside the middle half when a few large orders were priced far from should-cost. Where the tool fits past prices poorly the gap is marked “tool unsure”: it says more about the tool than about the price.`))),
        h("div", { class: "table-wrap tall" }, h("table", { class: "cmp" }, h("thead", {}, h("tr", {}, h("th", {}, "Fabric type"), h("th", { class: "cmp-cell" }, ""), h("th", { class: "n" }, "Paid Rs/m"), h("th", { class: "n" }, "Should-cost Rs/m"), h("th", { class: "n" }, "Paid above should-cost"), h("th", { class: "n", title: "Half of these fabrics were priced between these two figures against should-cost; one in four above the higher, one in four below the lower. The negotiation brief treats this range (at least 5% and at most 10% either way) as in line" }, "Middle half of fabrics"), h("th", { class: "n", title: "Share of these fabrics where the should-cost is within 10% of the price paid" }, "Tool within 10%"), h("th", { class: "n" }, "Fabrics"))), h("tbody", {}, rows))),
        h("p", { class: "sub", style: "margin:10px 0 0" }, "Poly cotton and linen are not here: there are no costed purchases of them yet.")));

      // 2. where the rupee goes
      const names = p.split[0].shares.map(s => s.name);
      const bars = p.split.map(sp => { const conv = 1 - sp.shares[0].share; const seg = sp.shares.filter(s => s.share > 0.0005).map(s => { const i = names.indexOf(s.name); const el = h("div", { class: "stack-seg", tabindex: "0", style: `width:${s.share * 100}%;background:var(${GROUP_COLOR[i % 8]})` }, s.share > 0.06 ? h("span", {}, pct(s.share, 0)) : null); withTip(el, () => `<b>${s.name}</b>${pct(s.share)} of the should-cost of ${sp.route.toLowerCase()} fabrics`); return el; });
        return h("div", { class: "stack-row" }, h("div", { class: "stack-name" }, h("b", {}, sp.route), h("small", {}, `${fmt(sp.fabrics, 0)} fabrics · median Rs ${fmt(sp.median_cost, 0)}/m`)), h("div", { class: "stack", role: "img", "aria-label": `${sp.route}: ` + sp.shares.map(s => `${s.name} ${pct(s.share, 0)}`).join(", ") }, seg), h("div", { class: "stack-note num" }, `conversion ${pct(conv, 0)}`)); });
      const tbl = { columns: ["Cost group", ...p.split.map(s => s.route)], rows: names.map(n => [n, ...p.split.map(sp => pct((sp.shares.find(s => s.name === n) || { share: 0 }).share))]) };
      nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "2. Where the rupee goes, by process"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Share of the should-cost, which is the tool's estimate, not the mill's accounts. Yarn, dyeing and weaving rest on rates and purchase prices; losses, overhead and margin are the percentages assumed in the rate master. Conversion is everything except yarn: what the mill adds, and where negotiation has room."))),
        h("div", { class: "stacks" }, bars), h("div", { class: "legend", "aria-hidden": "true" }, names.map((n, i) => h("span", {}, h("i", { style: `background:var(${GROUP_COLOR[i % 8]})` }), n))),
        h("details", { style: "margin-top:12px" }, h("summary", { style: "cursor:pointer;color:var(--muted)" }, "The same as a table"), h("div", { style: "margin-top:8px" }, dataTable(tbl, { label: "Share of should-cost by cost group and route" })))));
    } else nodes.push(h("div", { class: "notice info" }, "Panels 1 and 2 need the pilot results, which are not on this server."));

    // 3. the trend there is data for: cotton
    const yrs = ins.cotton_years.filter(y => y.year >= 2022), ytop = Math.max(...yrs.map(y => y.average), 1), last = yrs[yrs.length - 1];
    nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "3. Cost trend, 2022 to 2026: cotton"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Shankar-6 cotton, average of the year, rupees per candy. Cotton is the trend the tool has data for; the yarn rates are of one date (Nov 2026), so a fabric cost per metre for earlier years cannot be drawn yet."))),
      h("div", { class: "bars" }, yrs.map((y, i) => { const prev = yrs[i - 1]; const chg = prev ? y.average / prev.average - 1 : null; const el = h("div", { class: "bar-row grp", tabindex: "0" }, h("span", { class: "year num" }, String(y.year)), h("div", { class: "bar", style: `width:${y.average / ytop * 56}%;background:var(--g1)` }), h("span", { class: "bar-text" }, h("span", { class: "bar-amt num" }, `Rs ${fmt(y.average, 0)}`), chg === null ? null : h("span", { class: "bar-pct num" }, `${pctSigned(chg * 100)} on ${prev.year}`), y === last ? h("span", { class: "bar-pct" }, `to ${day(y.to)}`) : null)); withTip(el, () => `<b>${y.year}</b>average Rs ${fmt(y.average, 0)} per candy<br>low Rs ${fmt(y.low, 0)}, high Rs ${fmt(y.high, 0)}`); return el; })),
      h("p", { class: "sub", style: "margin:10px 0 0" }, "To see what a yarn move does to a fabric, use “If yarn prices move” above, or on Create cost. ", can("page:prices") ? h("a", { href: "#cotton" }, "Cotton prices in full") : null)));

    nodes.push(askCard(ins));

    // what negotiation has won, from the tracker on each fabric in Right cost
    try {
      const box = h("div", { class: "card" });
      const paint = w => box.replaceChildren(...[h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Won in negotiation"),
        h("div", { class: "sub", style: "margin:2px 0 0" }, "From the tracker on each fabric's Negotiation tab in Right cost: the mill's first quote less the agreed price, times the metres. Open negotiations are not counted."))),
        ...(w.fabrics ? [h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `${plural(w.agreed, "fabric")} agreed, ${w.open} still open`),
            ...(w.agreed ? [h("b", { class: "num" + (w.won < 0 ? " loss" : "") }, `Rs ${fmt(Math.abs(w.won), 0)}`), h("span", { class: "sub", style: "margin:0" }, (w.won < 0 ? "above the mills' first quotes: a net loss" : w.won > 0 ? "below the mills' first quotes" : "against the mills' first quotes")
              + (w.lost && w.won >= 0 ? `, after Rs ${fmt(w.lost, 0)} lost on ${plural(w.lost_fabrics, "fabric")} agreed above the first quote` : ""))] : [h("span", { class: "sub", style: "margin:0" }, "Nothing agreed yet, so nothing is counted as won.")])),
          w.no_quantity || w.no_quote || w.duplicates ? h("p", { class: "sub" }, "Agreed but not counted: " + [w.no_quantity ? `${plural(w.no_quantity, "fabric")} with no metres` : null, w.no_quote ? `${plural(w.no_quote, "fabric")} with no mill quote recorded` : null, w.duplicates ? `${plural(w.duplicates, "row")} repeating another order` : null].filter(Boolean).join("; ") + ".") : null,
          w.to_check.length ? h("div", { class: "notice warn", style: "margin:8px 0" }, h("b", {}, `${plural(w.to_check.length, "fabric")} with a step to check (an agreed one is left out of the total until it is put right): `),
            h("ul", { style: "margin:4px 0 0;padding-left:18px" }, ...w.to_check.slice(0, 6).map(c => h("li", {}, h("b", {}, c.code), ": " + c.why)), w.to_check.length > 6 ? h("li", {}, `and ${w.to_check.length - 6} more: filter Right cost by Negotiation and look for "check a step"`) : null)) : null,
          h("div", { class: "table-wrap" }, h("table", { class: "wontable" }, h("thead", {}, h("tr", {}, h("th", {}, "Mill"), h("th", { class: "n" }, "Agreed / open"), h("th", { class: "n" }, "Won, Rs"))),
            h("tbody", {}, ...w.suppliers.map(b => h("tr", {}, h("td", {}, millLink(b.supplier, b.key)), h("td", { class: "n" }, `${b.agreed} / ${b.open}`),
              h("td", { class: "n" + (b.won < 0 ? " loss" : "") }, !b.agreed ? "nothing agreed yet" : (b.won < 0 ? `${fmt(Math.abs(b.won), 0)} lost` : fmt(b.won, 0)) + (b.lost && b.won >= 0 ? `, after ${fmt(b.lost, 0)} lost on ${plural(b.lost_fabrics, "fabric")}` : "") + (b.not_counted ? ` (${b.not_counted} not counted)` : "")))))))]
          : [h("p", { class: "empty" }, "Nothing tracked yet. Open a fabric in Right cost, go to its Negotiation tab and record the mill's quote, your counter and the agreed price.")])].filter(Boolean));
      let last = JSON.stringify(await getJSON("/api/negotiations/summary")); paint(JSON.parse(last));
      nodes.push(box);
      // the steps are shared: look again every half minute and when the window is looked at again
      const again = async () => { if (!box.isConnected) { clearInterval(timer); removeEventListener("focus", again); return; } if (document.hidden) return;
        try { const now = JSON.stringify(await getJSON("/api/negotiations/summary")); if (now !== last) { last = now; paint(JSON.parse(now)); } } catch (e) { /* next time */ } };
      const timer = setInterval(again, 30000); addEventListener("focus", again);
    } catch (e) { /* the tracker is not on this server yet */ }

    // 5. supplier cost ratios, and suppliers against should-cost
    const sup = p ? h("div", { class: "table-wrap tall" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Supplier"), h("th", { class: "n" }, "Fabrics costed"), h("th", { class: "n" }, "Paid above should-cost, middle fabric"), h("th", { class: "n" }, "Tool within 10%"), h("th", {}, "Mostly buys"))),
      h("tbody", {}, p.suppliers.map(s => h("tr", {}, h("td", {}, millLink(s.supplier, s.key)), h("td", { class: "n" }, String(s.fabrics)), h("td", { class: "n" }, gapTag(s.gap, s.trust)), h("td", { class: "n" }, pct(s.within10, 0)), h("td", {}, `${s.mostly} (${pct(s.mostly_share, 0)})`)))))) : null;
    nodes.push(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "5. Supplier cost ratios, % of sales")),
      h("p", { class: "sub" }, "Whole-company figures from published accounts; they include yarn, garments and other businesses. Operating profit shows how much room a supplier has."),
      dataTable(ins.benchmarks, { label: "Supplier cost ratios" }),
      sup ? h("div", { style: "margin-top:16px" }, h("h3", {}, "Your purchases from each supplier, against should-cost"), sup) : null));
    return nodes;
  });

  /* What to ask before a negotiation, from the buyer's chair. The answers quote the buyer's own figures. */
  function askCard(ins) {
    const p = ins.pilot, ref = ins.reference, q = ins.card.quantity, col = n => q.columns.indexOf(n);
    const small = q.rows.filter(r => r[col("Small-lot upcharge %")] > 0).map(r => `${r[col("Quantity band")]} +${r[col("Small-lot upcharge %")]}%`).join(", ");
    const disc = q.rows.filter(r => r[col("Volume discount Rs per metre")] > 0).map(r => `${r[col("Quantity band")]} −Rs ${r[col("Volume discount Rs per metre")]}`).join(", ");
    const share = ref.yarn_share;
    const firm = p ? p.suppliers.filter(s => s.gap > 5 && s.trust === "firm").sort((a, b) => b.gap - a.gap) : [];
    const unsure = p ? p.suppliers.filter(s => s.gap > 5 && s.trust === "weak").sort((a, b) => b.gap - a.gap) : [];
    const above = firm.map(s => `${s.supplier} ${pctSigned(s.gap)} on ${s.fabrics} fabrics`).join(", ");
    const qty = p ? p.quantity.filter(x => x.paid).map(x => `${x.band}: Rs ${fmt(x.paid, 0)}`).join("; ") : "";
    const items = [
      ["What should this fabric cost, and how sure is the figure?", `Cost it on Create cost, or load the mill's sheet under Bulk upload. ${p ? `Across ${fmt(p.fabrics, 0)} of your cotton purchases the should-cost lands within 10% of the price paid for ${pct(p.within10, 0)} of fabrics, with a median gap of ${pctSigned(p.median_gap)}.` : ""} What counts as in line depends on the fabric type: the negotiation brief uses the range where half your past purchases of that type were priced (panel 1, middle half), kept between 5% and 10% either way.`],
      ["The mill says yarn has gone up. How much should the fabric go up?", `Not by the same percentage. On the reference shirting 5% on yarn is about ${(share * 5).toFixed(1)}% on the fabric, and each Rs 10 a kilo is ${rs(ref.warp_per_10 + ref.weft_per_10)} a metre for warp and weft together. Ask which count went up, from what rate to what, and on what date; then move that yarn in “If yarn prices move”.`],
      ["What is the base price, for which construction, and what do I pay for each extra end and pick?", "Ask for the standard EPI and PPI behind the base price. On Arvind's rate card an extra end is Rs 0.60 and an extra pick Rs 0.90 (Rs 1.00 above 90 picks); on their sheet the base for 40s yarn dyed twill is Rs 164 at 122 × 76. Other mills will have their own figures: ask for them in the same form. The list under Bulk upload checks every row of a mill's sheet: base plus upcharges must equal the price."],
      ["Am I paying for a small order, or missing a volume discount?", `Arvind's rate card adds ${small || "a percentage"} for yarn dyed lots below 800 m, and takes off ${disc || "a few rupees"} a metre for volume. The card gives no volume discount on its basic 40s quality, split deliveries or end-of-season orders. ${qty ? `Your median price paid by order size: ${qty}.` : ""} Ask whether lots of the same fabric code can be clubbed to reach the next band.`],
      ["Which finish, print and dobby charges are in the price?", `Ask for each as its own line. Arvind's card: rotary print Rs ${ins.card.print.Rotary}, digital Rs ${ins.card.print.Digital} a metre; dobby 9 to 12 shafts Rs 8, 13 and above Rs 10, top beam Rs 10; ETI or Easy Care Rs 4, liquid ammonia Rs 10. A charge with no process behind it is the first to challenge.`],
      ["Which suppliers are above should-cost?", (above ? `More than 5% above should-cost, where the tool fits well: ${above}.` : "No supplier is more than 5% above should-cost on fabrics where the tool fits well.") + (unsure.length ? ` Also above, but the tool fits this supplier's own fabrics poorly, so ask for the break-up before raising it: ${unsure.map(s => `${s.supplier} ${pctSigned(s.gap)} (mostly ${s.mostly}; the tool is within 10% on ${pct(s.within10, 0)} of its fabrics)`).join(", ")}.` : "") + " Panel 5 has every supplier."],
      ["What break-up should I ask the mill for?", "Yarn count and rate per kilo for warp and weft; wastage per cent; weaving charge per pick; dyeing per kilo; finish; process loss; overhead and margin. With those seven the gap between the quote and the should-cost can be put on one line, instead of argued as a total."],
      ["Is there a financing charge in the price?", "The mill's sheet carries an early-payment column (C2FO at 2.84%). Compare ex-mill prices, not the financed ones, and decide the payment terms separately."],
      ["Where is the tool's figure weak, so I do not push on the wrong point?", `${ins.placeholders} rates are placeholders, mostly finishes; the cost view says so whenever one is used. Yarn dyed plain is over-costed by about 10% (most of it is in Amsler or slub yarn), and printed twill and plain by more. Poly cotton and linen run on placeholder yarn rates. On those, ask for the break-up before quoting a number.`],
    ];
    return h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "4. Ask before you negotiate"), h("div", { class: "sub", style: "margin:2px 0 0" }, "Questions from the buyer's side, each answered with your own figures."))),
      h("div", { class: "asks" }, items.map(([qn, an], i) => h("details", { class: "ask", open: i === 0 || null }, h("summary", {}, qn), h("p", {}, an)))));
  }
})();
