/* New cost > Create cost: numbered steps on the left (fabric, route, yarn, dyeing, construction, finish, name), each
   deciding what the next asks; the cost on the right, updated as choices change, with its brief for the negotiation,
   the yarn what-if, what has moved since a listed fabric was added, and five charts. Nothing is costed here: every
   figure comes from /api/cost.
   What the other tabs of the popup need from it (the steps, the stance words, opening a fabric) is RP.cost. */
(function () {
  "use strict";
  const { $, h, svg, fmt, rs, day, pct, pctSigned, blank, postJSON, download, toast, withTip, dataTable, GROUP_COLOR } = RP.kit;
  const state = RP.state;
  let costBox = null;                      // the popup's box the page is drawn in: its size is what the window's was in the frame
  const boxWidth = () => costBox && costBox.isConnected ? costBox.clientWidth : innerWidth;

  const contentOfYarn = key => (state.meta.yarns.find(y => y.key === key) || {}).content;
  function blankSel() { return { Content: "", Route: "" }; }
  function exampleSel() {
    const ex = state.meta.example;
    return Object.assign(blankSel(), ex, { Content: contentOfYarn(ex["Warp yarn"]) || state.meta.contents[0], "Weft (yarn dyed)": state.meta.lists["Weft (yarn dyed)"][0] });
  }
  function selFromRow(row) {          // a bulk upload row opened in the cost view
    const s = Object.assign(blankSel(), Object.fromEntries(Object.entries(row).filter(([, v]) => !blank(v))));
    s.Content = contentOfYarn(s["Warp yarn"]) || state.meta.contents[0];
    return s;
  }
  // what each route asks for in the colouring step; anything else is not shown and not sent
  const ROUTE_FIELDS = { "Yarn Dyed": ["Warp yarn dyeing", "Weft (yarn dyed)", "Weft yarn dyeing", "Print method"], "Piece Dyed": ["Piece shade"], "Printed": ["Print method"], "RFD / Bleached": [] };
  const yarnText = (sel, side) => blank(sel[side + " count"]) ? sel[side + " yarn"] : `${sel[side + " yarn"]} typed as ${sel[side + " count"]} ${String(sel["Count system"] || "English count (Ne)").replace(/ count| \(linen\)/g, "")}`;
  const COUNT_TO_NE = { "English count (Ne)": v => v, "Metric count (Nm)": v => v / 1.6934, Tex: v => 590.5 / v, Denier: v => 5315 / v, "Lea (linen)": v => v * 300 / 840, "Worsted count (Nw)": v => v * 560 / 840 };
  const NE_TO_COUNT = { "English count (Ne)": v => v, "Metric count (Nm)": v => v * 1.6934, Tex: v => 590.5 / v, Denier: v => 5315 / v, "Lea (linen)": v => v * 840 / 300, "Worsted count (Nw)": v => v * 840 / 560 };
  function fieldOn(sel, name) {
    const L = state.meta.lists, first = n => L[n][0];
    if (["Warp yarn dyeing", "Weft (yarn dyed)", "Weft yarn dyeing", "Piece shade", "Print method"].includes(name)) {
      if (!(ROUTE_FIELDS[sel.Route] || []).includes(name)) return false;
      if (name === "Weft yarn dyeing") return (sel["Weft (yarn dyed)"] || first("Weft (yarn dyed)")) === first("Weft (yarn dyed)");
      return true;
    }
    if (name === "Dobby shafts" || name === "Top beam") return state.meta.weave_group[sel.Weave] === "Dobby/Matt";
    if (name === "Order size") return (sel["Rate card quantity"] || first("Rate card quantity")) === first("Rate card quantity");
    return true;
  }
  // what /api/cost is sent: the choices, plus the remarks of the list row the fabric was opened from
  const costBody = sel => Object.assign(payload(sel), state.listId && state.rowNotes && state.rowNotes.length ? { _notes: state.rowNotes } : {});
  function payload(sel) {
    const out = {};
    for (const [k, v] of Object.entries(sel)) if (!blank(v) && fieldOn(sel, k)) out[k] = v;
    return out;
  }
  const STEPS = [
    { id: "fabric", title: "Fabric", need: "Choose the fabric", done: s => !!s.Content, sum: s => s.Content },
    { id: "route", title: "How it is coloured", need: "Choose yarn dyed, piece dyed, bleached or printed", done: s => !!s.Route, sum: s => s.Route },
    { id: "yarn", title: "Yarn", need: "Choose the warp and weft yarn", done: s => !!s["Warp yarn"] && !!s["Weft yarn"], sum: s => `${yarnText(s, "Warp")} × ${yarnText(s, "Weft")}` },
    { id: "dye", title: s => ({ "Yarn Dyed": "Yarn dyeing", "Piece Dyed": "Piece dyeing", Printed: "Printing", "RFD / Bleached": "Bleaching" }[s.Route] || "Dyeing"), done: () => true, sum: s => [["Warp yarn dyeing", "warp "], ["Weft (yarn dyed)", "weft "], ["Weft yarn dyeing", "weft shade "], ["Piece shade", ""], ["Print method", "print: "]].filter(([f]) => fieldOn(s, f) && s[f]).map(([f, p]) => p + s[f]).join(" · ") },
    { id: "cons", title: "Weave and construction", need: "Choose the weave and type EPI, PPI and width", done: s => !!s.Weave && s.EPI > 0 && s.PPI > 0 && s["Finished width (in)"] > 0, sum: s => `${s.Weave} · ${s.EPI} × ${s.PPI} · ${s["Finished width (in)"]} in` },
    { id: "finish", title: "Finish, mill and order", done: () => true, sum: s => [s.Finish, fieldOn(s, "Order size") ? s["Order size"] : s["Rate card quantity"]].filter(Boolean).join(" · ") },
    { id: "name", title: "Name and compare (optional)", done: () => true, sum: s => [s["Fabric code"], s["Quoted price (Rs/m)"] ? "quote Rs " + s["Quoted price (Rs/m)"] : ""].filter(Boolean).join(" · ") },
  ];
  const ready = sel => STEPS.every(st => st.done(sel));

  RP.page("cost", { title: "Create cost", popup: true }, async (arg, ctx) => {
    costBox = ctx.root;
    const L = state.meta.lists, M = state.meta;
    if (!state.sel) state.sel = blankSel();
    const sel = state.sel;
    const flow = h("div", { class: "flow" }), out = h("div", { class: "cost-out", "aria-live": "polite" });

    let timer, last = 0;
    const recalc = () => {
      clearTimeout(timer);
      if (!ready(sel)) { ++last; return out.replaceChildren(waiting(sel)); }
      timer = setTimeout(async () => {
        const mine = ++last;
        try { const res = await (await postJSON("/api/cost", costBody(sel))).json(); if (mine === last) out.replaceChildren(...costView(res, sel)); }
        catch (e) { if (mine === last) { const old = out.querySelector(".cannot"); if (old) old.remove(); out.prepend(h("div", { class: "notice err cannot", role: "alert", style: "margin-top:0" }, h("b", {}, "Cannot cost this as typed: "), e.message + (out.children.length ? " The figures below are from before this change." : ""))); } }
      }, 160);
    };
    const doneNow = () => STEPS.map(st => st.done(sel));
    const advance = before => {            // the open step has just been finished: fold it and open the next
      const after = doneNow(), i = STEPS.findIndex(st => st.id === state.openStep);
      if (i >= 0 && !before[i] && after[i] && i < STEPS.length - 1) { state.openStep = STEPS[i + 1].id; return true; }
      return false;
    };
    const set = (name, value, repaint = true) => {
      if (!["Fabric code", "Description", "Supplier", "Quoted price (Rs/m)", "Order quantity (m)"].includes(name)) state.reopened = null;      // once a costed choice changes, it is no longer the costing that was saved
      const before = doneNow();
      if (name === "Count system") {          // the same yarn, written in the new system: the typed numbers follow
        const from = COUNT_TO_NE[sel["Count system"] || "English count (Ne)"], to = NE_TO_COUNT[value];
        for (const f of ["Warp count", "Weft count"]) if (!blank(sel[f]) && sel[f] > 0 && from && to) sel[f] = Number(to(from(sel[f])).toPrecision(6));
      }
      sel[name] = value;
      if (name === "Content") { let cleared = false; for (const y of ["Warp yarn", "Weft yarn"]) if (sel[y] && contentOfYarn(sel[y]) !== value) { sel[y] = ""; cleared = true; } if (cleared) toast(`Yarn cleared: choose a ${value.toLowerCase()} yarn in step 3`); }
      if (name === "Route") {                    // each route starts from its own defaults
        // choices made for another route are kept, out of sight, in case the buyer comes back to it
        const fill = (f, v) => { if (blank(sel[f])) sel[f] = v; };
        if (value === "Yarn Dyed") { fill("Warp yarn dyeing", "Medium"); fill("Weft yarn dyeing", "Medium"); fill("Weft (yarn dyed)", L["Weft (yarn dyed)"][0]); }
        if (value === "Piece Dyed") fill("Piece shade", "Medium");
        if (value !== "Yarn Dyed" && M.small_lot_bands.includes(sel["Rate card quantity"])) { sel["Rate card quantity"] = L["Rate card quantity"][0]; toast("Quantity band cleared: bands below 800 m are for yarn dyed fabrics only"); }
      }
      if (name === "Warp yarn" && !sel["Weft yarn"]) sel["Weft yarn"] = value;      // most fabrics use one yarn both ways
      const moved = repaint && (name === "Content" || name === "Route") && advance(before);     // a chip finishes its step; elsewhere "Next" moves on
      if (repaint) paint(moved ? null : name, moved);
      recalc();
    };

    // --- field builders
    const idOf = n => "f-" + n.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    const wrap = (name, label, input, hint, wide) => h("div", { class: "field" + (wide ? " wide" : "") }, h("label", { for: idOf(name) }, label || name), input, hint ? h("span", { class: "hint" }, hint) : null);
    const pick = (name, list, o = {}) => {
      const opts = (o.options || L[list]).map(v => typeof v === "string" ? { value: v, text: v } : v);
      if (blank(sel[name]) && !o.blank) sel[name] = opts[0].value;
      const input = h("select", { id: idOf(name) }, o.blank ? h("option", { value: "" }, o.blank) : null, opts.map(v => h("option", { value: v.value, disabled: v.disabled || null }, v.text)));
      input.value = sel[name] ?? "";
      input.addEventListener("change", () => set(name, input.value));
      return wrap(name, o.label, input, o.hint, o.wide);
    };
    const typed = (name, o = {}) => {
      const input = h("input", { id: idOf(name), type: o.text ? "text" : "number", value: sel[name] ?? "", step: o.step || (o.text ? null : "any"), min: o.text ? null : "0", inputmode: o.text ? null : "decimal", placeholder: o.placeholder });
      let wasDone = doneNow();
      input.addEventListener("input", () => { set(name, o.text ? input.value : (input.value === "" ? "" : Number(input.value)), false); });
      input.addEventListener("change", () => {      // typing finished (or unfinished) the step: unlock what follows, keep the buyer where they are
        const before = wasDone.join(); wasDone = doneNow();
        if (wasDone.join() !== before) setTimeout(() => { const id = document.activeElement && document.activeElement.id; paint(); const el = id && document.getElementById(id); if (el) el.focus({ preventScroll: true }); }, 0);
      });
      return wrap(name, o.label, input, o.hint, o.wide);
    };
    const chipset = (name, values, label) => h("div", { class: "field wide" }, h("span", { class: "lbl", id: idOf(name) + "-l" }, label),
      h("div", { class: "chips", role: "group", "aria-labelledby": idOf(name) + "-l" }, values.map(v => h("button", { type: "button", class: "chip", "aria-pressed": String(sel[name] === v), "data-v": v, onclick: () => set(name, v) }, v))));
    const yarnOptions = () => M.yarns.filter(y => y.content === sel.Content).map(y => ({ value: y.key, text: `${y.key} · Rs ${fmt(y.rate, 0)}/kg${y.basis.startsWith("Placeholder") ? " · placeholder" : ""}` }));

    const bodies = {
      fabric: () => [chipset("Content", M.contents, "Fabric content"),
        sel.Content && sel.Content !== M.contents[0] ? h("div", { class: "notice wide", style: "margin:0" }, "Yarn rates for this content are placeholders, and the weaving, dyeing and finishing rates were measured on 100% cotton. Treat the cost as provisional.") : null],
      route: () => [chipset("Route", L.Route, "Route")],
      yarn: () => { const opts = yarnOptions(); return opts.length ? [pick("Warp yarn", null, { options: opts, blank: "Choose...", wide: true }), pick("Weft yarn", null, { options: opts, blank: "Choose...", wide: true }),
        h("details", { class: "wide more", open: state.countOpen || !blank(sel["Warp count"]) || !blank(sel["Weft count"]) || null, ontoggle: e => { state.countOpen = e.target.open; } }, h("summary", {}, "Type a different count (optional)"),
          h("div", { class: "fields", style: "margin-top:10px" }, pick("Count system", "Count system", { wide: true, hint: "Ne for cotton, lea for linen, denier for filament" }),
            typed("Warp count", { hint: "Blank = the yarn's own" }), typed("Weft count", { hint: "Blank = the yarn's own" }),
            h("p", { class: "sub wide", style: "margin:0;font-size:12px" }, "A typed count changes the weight of yarn in the cloth. The rate per kg stays that of the yarn chosen above.")))] : [h("div", { class: "notice wide", style: "margin:0" }, "No yarn of this content is in the yarn master yet. Add one under Yarn prices.")]; },
      dye: () => {
        const f = [];
        if (fieldOn(sel, "Warp yarn dyeing")) f.push(pick("Warp yarn dyeing", "Yarn shade", { label: "Warp shade" }));
        if (fieldOn(sel, "Weft (yarn dyed)")) f.push(pick("Weft (yarn dyed)", "Weft (yarn dyed)", { label: "Weft: dyed or undyed" }));
        if (fieldOn(sel, "Weft yarn dyeing")) f.push(pick("Weft yarn dyeing", "Yarn shade", { label: "Weft shade" }));
        if (fieldOn(sel, "Piece shade")) f.push(pick("Piece shade", "Piece shade"));
        if (fieldOn(sel, "Print method")) f.push(pick("Print method", "Print method", sel.Route === "Printed" ? { hint: "Not selected = the calibrated printing rate per kg. Rotary or Digital uses the mill rate card instead", wide: true } : { label: "Print over the cloth", hint: "Leave at Not selected for no print" }));
        return f.length ? f : [h("p", { class: "sub wide", style: "margin:0" }, "Bleached only: nothing to choose here.")];
      },
      cons: () => [pick("Weave", "Weave", { blank: "Choose..." }), pick("Pattern", "Pattern", { hint: "No price uplift is set for any pattern yet" }),
        typed("EPI", { label: "Ends per inch (EPI)" }), typed("PPI", { label: "Picks per inch (PPI)" }), typed("Finished width (in)", { label: "Finished width (inch)" }), typed("Reed space (in)", { label: "Reed space (inch)", hint: "Blank = from width" }),
        fieldOn(sel, "Dobby shafts") ? pick("Dobby shafts", "Dobby shafts") : null, fieldOn(sel, "Top beam") ? pick("Top beam", "Top beam") : null],
      finish: () => [pick("Finish", "Finish", { wide: true }), pick("Loom type", "Loom type"), pick("Mill tier", "Mill tier"),
        pick("Rate card quantity", null, { label: "Quantity band (mill rate card)", hint: "When set, used instead of Order size", options: L["Rate card quantity"].map(v => ({ value: v, text: v, disabled: sel.Route !== "Yarn Dyed" && M.small_lot_bands.includes(v) })) }),
        fieldOn(sel, "Order size") ? pick("Order size", "Order size", { label: "Order size (pilot slabs)" }) : null],
      name: () => [typed("Fabric code", { text: true }), typed("Supplier", { text: true }), typed("Description", { text: true, wide: true }),
        typed("Quoted price (Rs/m)", { label: "Supplier's quote (Rs/m)" }), typed("Order quantity (m)", { hint: "Shows the money at stake" }), typed("Extra charge (Rs/m)", { wide: true }), typed("Weaving rate override (Rs/pick)", { step: "0.01", wide: true, hint: "Blank = use the rate table" })],
    };

    /* One step is open at a time. A finished step folds to a line that says what was chosen;
       clicking it opens it again. A step cannot be opened before the ones above it are done. */
    const paint = (focusName, moved) => {
      let reachable = true;
      if (!state.openStep || !STEPS.some(st => st.id === state.openStep)) state.openStep = (STEPS.find(st => !st.done(sel)) || {}).id || null;
      flow.replaceChildren(...STEPS.map((st, i) => {
        const title = typeof st.title === "function" ? st.title(sel) : st.title;
        const open = reachable && state.openStep === st.id;
        if (open) state.visited.add(st.id);
        const mine = reachable, done = mine && st.done(sel) && (!!st.need || state.visited.has(st.id));
        if (mine && !st.done(sel)) reachable = false;
        const sum = mine && st.done(sel) && !open ? ((done ? "" : "default: ") + st.sum(sel)).replace(/^default: $/, "") : "";
        const head = [h("span", { class: "step-n", "aria-hidden": "true" }, done ? "✓" : String(i + 1)), h("h2", {}, title), sum ? h("span", { class: "step-sum" }, sum) : null, mine ? h("span", { class: "step-caret", html: svg('<path d="m6 9 6 6 6-6"/>', 14) }) : null];
        const next = STEPS[i + 1];
        return h("section", { class: "step" + (mine ? "" : " locked") + (done ? " done" : "") + (open ? " open" : ""), "aria-label": `Step ${i + 1}: ${title}` },
          mine ? h("button", { type: "button", class: "step-head", "aria-expanded": String(open), "data-step": st.id, onclick: () => { state.openStep = open ? null : st.id; paint(null, true); } }, head) : h("div", { class: "step-head" }, head),
          open ? h("div", { class: "fields" }, bodies[st.id](), next && st.done(sel) ? h("div", { class: "wide" }, h("button", { type: "button", class: "btn small", onclick: () => { state.openStep = next.id; paint(null, true); } }, "Next: " + (typeof next.title === "function" ? next.title(sel) : next.title))) : null) : null);
      }));
      if (focusName) { const el = flow.querySelector(`[data-v="${CSS.escape(String(sel[focusName] ?? ""))}"]`) || $("#" + idOf(focusName), flow); if (el) el.focus({ preventScroll: true }); }
      else if (moved) { const el = flow.querySelector(".step.open .fields button, .step.open .fields select, .step.open .fields input") || flow.querySelector(`[data-step="${state.openStep}"]`); if (el) el.focus({ preventScroll: true }); const sec = flow.querySelector(".step.open"); if (sec) sec.scrollIntoView({ block: "nearest" }); }
    };
    state.setChoice = (name, value) => { set(name, value); };
    paint(); recalc();

    const actions = h("div", { class: "row-actions", style: "margin:0" },
      h("button", { class: "btn small", type: "button", onclick: () => { open(null, null); ctx.reload(); } }, "New fabric"),
      h("button", { class: "btn small", type: "button", onclick: () => { state.sel = exampleSel(); state.listId = null; state.rowNotes = null; state.sim = null; state.reopened = null; state.openStep = null; STEPS.forEach(st => state.visited.add(st.id)); ctx.reload(); } }, "Load the example"));
    // the two panes take exactly the height left in the popup, so the page itself does not scroll
    const split = h("div", { class: "cost-split" }, h("div", { class: "pane pane-in", role: "form", "aria-label": "Fabric inputs" }, h("div", { class: "pane-head" }, actions), flow), h("div", { class: "pane pane-out" }, out));
    const fit = () => {
      if (!split.isConnected) return removeEventListener("resize", fit);
      const box = ctx.root, top = split.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
      split.style.height = box.clientWidth > 1000 ? Math.max(420, box.clientHeight - top - 14) + "px" : "";
    };
    addEventListener("resize", fit); requestAnimationFrame(fit); setTimeout(fit, 300);
    return [split];
  });

  /* The negotiation brief: what to say about one quote. Where the tool is unsure of this kind of fabric it
     gives no target and says to ask for the break-up instead. Every figure is compared as printed, so the
     sums can be checked on the page. */
  const STANCE = { check: ["warn", "Check the quote first: it is more than 30% below should-cost"], push: ["down", "Push: the quote is above the usual range"], fair: ["flat", "Fair: in line with the usual range"], below: ["up", "Below should-cost: a saving, if the specification holds"], ask: ["warn", "Ask for the break-up before naming a price"] };
  // the stance of a row once its gap has moved (a yarn move on the list): the same range, the new gap
  const stanceFor = (b, gapPct) => b.stance === "ask" ? "ask" : gapPct > b.band.hi + 1e-9 ? "push" : gapPct < b.band.lo - 1e-9 ? "below" : "fair";
  function briefCard(b, sel, moved) {
    const w = b.would_need, above = b.gap > 0, st = b.implausible ? ["warn", "Check the quote first"] : STANCE[b.stance];
    const lines = [], gapText = `${rs(Math.abs(b.gap))} (${pct(Math.abs(b.gap_pct))}) ${b.gap > 0 ? "above" : b.gap < 0 ? "below" : "at"} should-cost`;
    const band = `${rs(b.lower)} to ${rs(b.settle_up_to)}`;
    for (const c of b.caveats || []) lines.push(h("li", { class: "caveat" }, h("b", {}, "Before you use these figures: "), c));
    if (b.stance === "ask") {
      if (b.qty_only) lines.push(h("li", {}, h("b", {}, "Set the quantity first. "), b.weak[0].charAt(0).toUpperCase() + b.weak[0].slice(1) + ". Change it in step 6, and the brief will give a stance."));
      else lines.push(h("li", {}, h("b", {}, "Do not open with a number. "), "The should-cost is not firm here: " + b.weak.join("; ") + ". Ask for yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish and margin, then cost it again."));
      if (b.qty_fix && state.setChoice) lines.push(h("li", {}, h("button", { type: "button", class: "btn small", onclick: () => state.setChoice(b.qty_fix.field, b.qty_fix.value) }, `Set ${b.qty_fix.field === "Order size" ? "the order size" : "the quantity band"} to ${b.qty_fix.value}`), " to cost it on the quantity typed."));
    } else if (b.stance === "push") lines.push(h("li", {}, h("b", {}, `Open at ${rs(b.open_at)} a metre and aim to settle at ${rs(b.settle_up_to)}, the top of the usual range. `), `The usual range for this fabric is ${band}: ${b.band.why}. The quote is ${rs(b.above_band)} above its top; ask the mill to show where that comes from. ` + (b.open_at > b.should + 0.005 ? `The opening figure is as far below the top of the range as the quote is above it, so it moves with the quote; it never goes below the should-cost, ${rs(b.should)}, which is where it stops once the quote is ${rs(b.settle_up_to - b.should)} or more above the range.` : `The opening figure is the should-cost: the quote is so far above the range that the mill has to justify all of the gap.`)));
    else if (b.stance === "fair") lines.push(h("li", {}, h("b", {}, "The quote is in line. "), `It is ${gapText}, inside the usual range of ${band}: ${b.band.why}. Use the time on quantity terms, finish and delivery instead.`));
    else if (b.implausible) lines.push(h("li", {}, h("b", {}, "Check the quote first. "), `It is ${gapText}. No saving is counted until the quote is confirmed for this cloth, per metre.`));
    else lines.push(h("li", {}, h("b", {}, "The quote is below the usual range: a saving, if the specification holds. "), `It is ${gapText}; the usual range is ${band}. Before taking it, confirm the yarn, the construction and the finish are the ones costed here: a low price sometimes means a lighter cloth or a different yarn.`));
    if (above && (b.stance === "push" || b.stance === "ask")) {
      const parts = [], about = v => `about ${v}`;
      const phNote = " (the tool's own rate here is a placeholder, so ask for the mill's figure)";
      if (w.yarn) {
        const same = Math.abs(w.yarn.weft_now - w.yarn.warp_now) < 0.5;
        const t = same ? `warp and weft yarn both cost ${about("Rs " + fmt(w.yarn.warp, 0))} a kilo` + (w.yarn.placeholder ? phNote : `, not Rs ${fmt(w.yarn.warp_now, 0)}`)
          : `warp yarn costs ${about("Rs " + fmt(w.yarn.warp, 0))} a kilo and weft yarn ${about("Rs " + fmt(w.yarn.weft, 0))}` + (w.yarn.placeholder ? phNote : `, not Rs ${fmt(w.yarn.warp_now, 0)} and Rs ${fmt(w.yarn.weft_now, 0)}`);
        parts.push(h("li", {}, `${t} (${pctSigned(w.yarn.pct, 1)})`));
      }
      parts.push(h("li", {}, `or weaving is ${about("Rs " + w.weaving.rate.toFixed(3))} a pick` + (w.weaving.placeholder ? phNote : `, not Rs ${w.weaving.now.toFixed(3)}`) + ` (the gap less the losses, overhead and margin the mill adds on it is ${rs(w.weaving.per_m_before)} a metre, over ${fmt(w.weaving.picks, 0)} picks)`));
      parts.push(h("li", {}, `or the mill's margin is ${about(pct(w.margin.rate, 1))}` + (w.margin.placeholder ? phNote : `, not ${pct(w.margin.now, 1)}`)));
      lines.push(h("li", {}, h("b", {}, `For the quote to be right, one of these would have to be true; each alone explains the whole ${rs(b.gap)} a metre: `), h("ul", {}, parts), "Ask which it is. Each can be checked: the yarn against the yarn master and the market, the others against the mill's own sheet."));
    }
    if (b.at_stake !== null && b.quantity && !b.implausible) {
      const amt = `Rs ${fmt(Math.abs(b.at_stake), 0)}`, per = `${fmt(b.quantity, 0)} m × ${rs(Math.abs(b.gap))} a metre`;
      lines.push(h("li", {}, b.gap > 0 ? [h("b", {}, `At stake: ${amt} `), `above should-cost (${per}).`] : b.gap < 0 ? [h("b", {}, `Saving against should-cost: ${amt} `), `(${per}).`] : [h("b", {}, "Nothing at stake: "), "the quote equals the should-cost."]));
    }
    const fit = b.fit ? h("p", { class: "sub", style: "margin:8px 0 0;font-size:12px" }, `On ${b.fit.type} the tool is within 10% of the price paid for ${pct(b.fit.within10, 0)} of ${fmt(b.fit.fabrics, 0)} fabrics bought; on average they were paid ${pctSigned(b.fit.gap)} against should-cost, and the middle half between ${pctSigned(b.fit.p25)} and ${pctSigned(b.fit.p75)} (dashboard panel 1).`) : null;
    return h("div", { class: "card brief" }, h("div", { class: "card-head", style: "margin-bottom:8px" }, h("h2", {}, "For the negotiation" + (moved ? ` · ${moved}` : "")), h("span", { class: "tag " + st[0] }, st[1])),
      h("p", { class: "sub", style: "margin:0 0 8px" }, `Quote ${rs(b.quote)}, should-cost ${rs(b.should)}: the quote is ${gapText}.`),
      h("ul", { class: "brief-list" }, lines), fit);
  }

  /* What a move in the yarn price does to this fabric. The sliders re-cost it with the warp and weft
     rates moved; nothing is saved and the rate master is untouched. */
  function yarnSim(res, sel) {
    const y = res.yarn, sim = state.sim = state.sim || { warp: 0, weft: 0, both: true };
    const out = h("div", { class: "whatif-out", "aria-live": "polite" });
    let turn = 0, timer;
    const show = async () => {
      const mine = ++turn;
      const swapBrief = (b, label) => { const old = document.querySelector(".cost-out .brief"); if (old && b) old.replaceWith(briefCard(b, sel, label)); };
      const heroMoved = r => { const el = document.querySelector(".cost-out .hero-moved"); if (!el) return; el.hidden = !r; if (r) el.textContent = `With the yarn moved on the sliders below (warp Rs ${fmt(y.warp_rate * (1 + sim.warp / 100), 0)}/kg, weft Rs ${fmt(y.weft_rate * (1 + sim.weft / 100), 0)}/kg) the should-cost is ${rs(r.total_per_m)}` + (r.quote !== null ? `, and the quote is ${rs(Math.abs(r.gap))} (${pct(Math.abs(r.gap_pct))}) ${r.gap >= 0 ? "above" : "below"} it.` : "."); };
      if (!sim.warp && !sim.weft) { heroMoved(null); swapBrief(res.brief, null); return out.replaceChildren(h("span", { class: "sub", style: "margin:0" }, "Move a slider to see the price at a different yarn rate.")); }
      try {
        const body = Object.assign(costBody(sel), { "Warp yarn price override": y.warp_rate * (1 + sim.warp / 100), "Weft yarn price override": y.weft_rate * (1 + sim.weft / 100) });
        const r = await (await postJSON("/api/cost", body)).json(); if (mine !== turn) return;
        heroMoved(r);
        swapBrief(r.brief, sim.warp === sim.weft ? `with yarn ${pctSigned(sim.warp, 0)}` : `with warp ${pctSigned(sim.warp, 0)}, weft ${pctSigned(sim.weft, 0)}`);
        const d = r.total_per_m - res.total_per_m;
        out.replaceChildren(h("div", { class: "whatif-fig" }, h("span", { class: "lbl" }, `Warp at Rs ${fmt(y.warp_rate * (1 + sim.warp / 100), 0)}/kg, weft at Rs ${fmt(y.weft_rate * (1 + sim.weft / 100), 0)}/kg`), h("b", { class: "num" }, `${rs(res.total_per_m)} → ${rs(r.total_per_m)}`), h("span", { class: "tag " + (d > 0.005 ? "down" : d < -0.005 ? "up" : "flat") }, `${d >= 0 ? "+" : "−"}${fmt(Math.abs(d))} /m (${pctSigned(d / res.total_per_m * 100)})`),
          r.quote !== null ? h("span", { class: "sub", style: "margin:0" }, `the quote would be ${pct(Math.abs(r.gap_pct))} ${r.gap >= 0 ? "above" : "below"}`) : null));
      } catch (e) { if (mine === turn) out.replaceChildren(h("span", { class: "sub", style: "margin:0" }, e.message)); }
    };
    const row = (key, label, rate) => {
      const span = String(Math.max(20, Math.abs(sim.warp), Math.abs(sim.weft)));
      const slider = h("input", { type: "range", min: "-" + span, max: span, step: "1", value: String(sim[key]), id: "sim-" + key, "aria-label": label + " yarn price change, per cent" });
      const val = h("span", { class: "num simval" }, pctSigned(sim[key], 0));
      slider.addEventListener("input", () => { sim[key] = Number(slider.value); if (sim.both) { sim.warp = sim.weft = sim[key]; for (const k of ["warp", "weft"]) { $("#sim-" + k).value = sim[k]; $("#sim-" + k).nextSibling.textContent = pctSigned(sim[k], 0); } } else val.textContent = pctSigned(sim[key], 0); clearTimeout(timer); timer = setTimeout(show, 120); });
      return h("div", { class: "simrow" }, h("label", { for: "sim-" + key }, `${label} · Rs ${fmt(rate, 0)}/kg`), slider, val);
    };
    const both = h("input", { type: "checkbox", id: "sim-both" }); both.checked = sim.both; both.addEventListener("change", () => { sim.both = both.checked; });
    show();
    return h("div", { class: "card whatif" }, h("div", { class: "card-head", style: "margin-bottom:8px" }, h("div", {}, h("h2", {}, "If yarn prices move"), h("div", { class: "sub", style: "margin:2px 0 0" }, `On this fabric 10% on yarn is about ${(y.yarn_share * 10).toFixed(1)}% on the price. Each Rs 10 a kilo on the warp is ${rs(y.warp_per_10)} a metre; on the weft, ${rs(y.weft_per_10)}.`)),
        h("div", { style: "display:flex;gap:12px;align-items:center" }, h("label", { for: "sim-both", class: "opt" }, both, "Move both together"), h("button", { class: "btn small", type: "button", onclick: () => { state.sim = null; const c = document.querySelector(".cost-out .whatif"); c.replaceWith(yarnSim(res, sel)); } }, "Reset"))),
      row("warp", "Warp", y.warp_rate), row("weft", "Weft", y.weft_rate), out);
  }

  /* A saved costing opened again is costed on today's rates. Say what it cost then, what it costs now,
     and which rates behind it have changed. */
  function movedCard(res, re) {
    const then = re.then, diff = res.total_per_m - then.total_per_m, same = Math.abs(diff) < 0.005;
    const was = Object.fromEntries((then.rates || []).map(u => [u.Item, u]));
    const show = u => `${typeof u.Value === "number" ? fmt(u.Value, Math.abs(u.Value) < 10 ? 3 : 2).replace(/\.?0+$/, "") : u.Value}${u.Unit ? " " + u.Unit : ""}`;
    const rates = res.rates_used.filter(u => was[u.Item] && (String(was[u.Item].Value) !== String(u.Value) || String(was[u.Item].Choice) !== String(u.Choice)))
      .map(u => h("tr", {}, h("td", {}, u.Item), h("td", {}, show(was[u.Item])), h("td", {}, show(u)), h("td", { class: "wrap" }, String(was[u.Item].Choice) !== String(u.Choice) ? `${was[u.Item].Choice} → ${u.Choice}` : String(u.Choice))));
    const groupWas = Object.fromEntries(then.buckets.map(b => [b.name, b.amount]));
    const groups = res.buckets.filter(b => Math.abs(b.amount - (groupWas[b.name] ?? 0)) >= 0.005)
      .map(b => h("tr", {}, h("td", {}, b.name), h("td", { class: "n" }, fmt(groupWas[b.name] ?? 0)), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, (b.amount >= (groupWas[b.name] ?? 0) ? "+" : "") + fmt(b.amount - (groupWas[b.name] ?? 0)))));
    return h("div", { class: "card moved" },
      h("div", { class: "card-head", style: "margin-bottom:8px" }, h("h2", {}, `Since it was added on ${day(re.on)}`),
        h("span", { class: "tag " + (same ? "flat" : diff > 0 ? "down" : "up") }, same ? "no change" : `${diff > 0 ? "▲" : "▼"} ${rs(Math.abs(diff))} (${pct(Math.abs(diff) / then.total_per_m)}) ${diff > 0 ? "dearer" : "cheaper"}`)),
      h("p", { class: "sub", style: "margin:0 0 10px" }, same ? `It cost ${rs(then.total_per_m)} per metre then and costs the same on today's rates.` : `It cost ${rs(then.total_per_m)} per metre then and costs ${rs(res.total_per_m)} on today's rates.`),
      rates.length && !same ? h("div", { class: "table-wrap tall" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Rate that changed"), h("th", {}, "Then"), h("th", {}, "Now"), h("th", {}, "Choice"))), h("tbody", {}, rates))) : (same ? null : h("p", { class: "sub", style: "margin:0" }, "No single rate in the list differs; a table behind the costing (for example crimp, wastage or a setting) has changed.")),
      groups.length ? h("details", { style: "margin-top:10px" }, h("summary", { style: "cursor:pointer;color:var(--muted)" }, "By cost group, Rs per metre"), h("div", { class: "table-wrap tall", style: "margin-top:8px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Group"), h("th", { class: "n" }, "Then"), h("th", { class: "n" }, "Now"), h("th", { class: "n" }, "Change"))), h("tbody", {}, groups)))) : null);
  }

  function waiting(sel) {
    const todo = STEPS.filter(st => st.need);
    let reached = true;
    return h("div", { class: "card waiting" }, h("h2", {}, "The cost appears here"), h("p", { class: "sub" }, "Finish these steps. Everything after them has a default you can change."),
      h("ol", { class: "todo" }, todo.map(st => { const ok = reached && st.done(sel); if (!ok) reached = false; return h("li", { class: ok ? "ok" : "" }, h("span", { "aria-hidden": "true" }, ok ? "✓" : "○"), " ", st.need, ok ? h("span", { class: "visually-hidden" }, " (done)") : null); })));
  }

  const CHARTS = [["bars", "Bars"], ["waterfall", "Waterfall"], ["pie", "Pie"], ["treemap", "Treemap"], ["line", "Line"]];
  const CHART_NOTE = { bars: "One bar per cost, from zero, largest at the top. Best for seeing what matters most.", waterfall: "Each step starts where the one before ended. Best for seeing how the price builds up.", pie: "Each group's share of the price.", treemap: "Area is rupees per metre; sub-costs sit inside their group. Best for seeing where the money is.", line: "The running total after each step." };
  function costView(res, sel) {
    const title = [[sel["Fabric code"], sel.Description].filter(v => !blank(v)).join(" — "), sel.Supplier].filter(v => !blank(v)).join(" · ");
    let quote = null;
    if (res.quote !== null) {
      const above = res.gap >= 0;
      const verdict = res.brief ? (res.brief.implausible ? "warn" : STANCE[res.brief.stance][0]) : (above ? "down" : "up");
      quote = h("div", { class: "quote" }, h("span", { class: "tag " + verdict }, `${above ? "▲" : "▼"} Quote ${rs(res.quote)}/m is ${rs(Math.abs(res.gap))} (${pct(Math.abs(res.gap_pct))}) ${above ? "above" : "below"} should-cost`));
    }
    const hero = h("div", { class: "card hero" },
      h("div", { class: "hero-row" },
        h("div", {}, h("div", { class: "lbl" }, title ? title + " · " : "", "ex-mill should-cost"), h("div", { class: "big num" }, `${rs(res.total_per_m)} / m`)),
        h("div", { class: "row-actions", style: "margin:0" },
          h("button", { class: "btn primary", onclick: async e => { const b = e.currentTarget; b.disabled = true; try { const r = await (await postJSON("/api/list/add", Object.assign({}, payload(sel), state.listId ? { _id: state.listId } : {}))).json(); toast(state.listId ? "Row updated in the list" : "Added to the list under Bulk upload"); state.listId = r.id; RP.shell.listChanged(); state.list = null; b.textContent = "Update in list"; } catch (err) { toast("Not added: " + err.message, false); } b.disabled = false; } }, state.listId ? "Update in list" : "Add to list"),
          h("button", { class: "btn", onclick: async () => { try { await download(await postJSON("/api/cost-sheet", payload(sel)), `Should cost ${sel["Fabric code"] || "fabric"}.xlsx`); } catch (err) { toast(err.message, false); } } }, "Download cost sheet"),
          h("button", { class: "btn", onclick: printSheet }, "Print"))),
      h("div", { class: "facts" }, h("span", {}, [sel.Content, sel.Route, sel.Weave, `${yarnText(sel, "Warp")} × ${yarnText(sel, "Weft")}`, `${sel.EPI} × ${sel.PPI}`, `${sel["Finished width (in)"]} in wide`].filter(Boolean).join(" · "))),
      h("div", { class: "facts num" }, h("span", {}, `${rs(res.per_kg, 0)} / kg`), h("span", {}, `about ${fmt(res.gsm, 0)} g/m²`), h("span", {}, `${fmt(res.finished_g_per_m, 0)} g per running metre`)),
      quote, h("div", { class: "notice info hero-moved", hidden: true, style: "margin:10px 0 0" }));

    const box = h("div"), note = h("div", { class: "sub", style: "margin:2px 0 0" });
    const negative = res.buckets.some(b => b.lines.some(l => l.amount < -0.005));
    const draw = () => {
      const fn = { bars: barsChart, waterfall, pie: pieChart, treemap: treemapChart, line: buildLine }[state.chart];
      box.replaceChildren(fn(res));
      if (negative && (state.chart === "pie" || state.chart === "treemap")) box.append(h("p", { class: "sub", style: "margin:10px 0 0" }, "A discount cannot be drawn as an area, so it is left out of this view. The bars and the waterfall show it."));
      note.textContent = state.chart === "pie" && state.wfMode === "all" ? "Each sub-cost's share of the price; sub-costs of one group share its colour and sit together."
        : state.chart === "bars" && !state.bySize ? "One bar per cost, from zero, in the order the price is built." : CHART_NOTE[state.chart];
      bigLabel.hidden = !(state.chart === "bars" || state.chart === "pie");
    };
    const seg = (items, key, label) => { const g = h("div", { class: "seg", role: "group", "aria-label": label }); for (const [v, text] of items) g.append(h("button", { type: "button", "aria-pressed": String(state[key] === v), onclick: () => { state[key] = v; state.wfOpen.clear(); [...g.children].forEach(b => b.setAttribute("aria-pressed", String(b.textContent === text))); draw(); } }, text)); return g; };
    const zero = h("input", { type: "checkbox", id: "zero" }); zero.checked = state.showZero;
    zero.addEventListener("change", () => { state.showZero = zero.checked; draw(); });
    const big = h("input", { type: "checkbox", id: "bysize" }); big.checked = state.bySize;
    big.addEventListener("change", () => { state.bySize = big.checked; draw(); });
    const bigLabel = h("label", { for: "bysize", class: "opt", title: "Largest cost first. Untick for the order the price is built in." }, big, "Largest first");
    draw();
    const chart = h("div", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, "Where the price comes from"), note),
        h("div", { style: "display:flex;gap:10px 14px;align-items:center;flex-wrap:wrap" }, seg(CHARTS, "chart", "Chart"), seg([["groups", "Groups"], ["all", "All sub-costs"]], "wfMode", "Level of detail"),
          bigLabel,
          h("label", { for: "zero", class: "opt" }, zero, "Lines at zero"))),
      box,
      h("div", { class: "legend", "aria-hidden": "true" }, res.buckets.map((b, i) => h("span", {}, h("i", { style: `background:var(${GROUP_COLOR[i % 8]})` }), b.name))));

    const lineRows = [];
    for (const b of res.buckets) {
      lineRows.push(h("tr", { class: "grp" }, h("td", {}, b.name), h("td", { class: "n" }, fmt(b.amount)), h("td", { class: "n" }, pct(b.pct)), h("td", {})));
      for (const l of b.lines) lineRows.push(h("tr", {}, h("td", {}, l.name), h("td", { class: "n" }, fmt(l.amount)), h("td", { class: "n" }, pct(res.total_per_m ? l.amount / res.total_per_m : 0)), h("td", { class: "wrap" }, l.basis)));
    }
    lineRows.push(h("tr", { class: "grp" }, h("td", {}, "Should-cost"), h("td", { class: "n" }, fmt(res.total_per_m)), h("td", { class: "n" }, "100.0%"), h("td", {})));
    const tableView = h("details", { class: "card" }, h("summary", {}, "Table of every line"),
      h("div", { class: "table-wrap tall" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Line"), h("th", { class: "n" }, "Rs/m"), h("th", { class: "n" }, "Share"), h("th", {}, "How it is worked out"))), h("tbody", {}, lineRows))));
    const used = { columns: ["Item", "Choice", "Value", "Unit", "Basis"], rows: res.rates_used.map(u => [u.Item, u.Choice, u.Value, u.Unit, u.Basis]) };
    const ratesView = h("details", { class: "card" }, h("summary", {}, "Rates used and where each came from"), dataTable(used, { label: "Rates used" }));
    const odd = (res.warnings || []).length ? h("div", { class: "notice err", role: "alert" }, h("b", {}, "Check what was typed. "), res.warnings.join(" ")) : null;
    const moved = state.reopened ? movedCard(res, state.reopened) : null;
    const chosen = Object.entries(payload(sel)).filter(([k]) => !["Fabric code", "Description", "Supplier"].includes(k));
    const choices = h("details", { class: "card" }, h("summary", {}, "Choices behind this cost"), dataTable({ columns: ["Choice", "Value"], rows: chosen.map(([k, v]) => [k, String(v)]) }, { label: "Choices behind this cost" }));
    const warn = res.placeholders.length ? h("div", { class: "notice", role: "status" }, h("b", {}, "Provisional. "), "Placeholder rates were used for: " + res.placeholders.join(", ") + ". These are starting guesses with no data behind them.") : null;
    return [hero, odd, res.brief ? briefCard(res.brief, sel) : null, yarnSim(res, sel), moved, warn, chart, tableView, choices, ratesView].filter(Boolean);
  }

  // printed from the browser's own menu: open the tables too, so nothing prints as an empty heading
  addEventListener("beforeprint", () => { if (document.body.classList.contains("printing")) return; const closed = [...document.querySelectorAll(".cost-out details:not([open])")]; closed.forEach(d => { d.open = true; }); addEventListener("afterprint", () => closed.forEach(d => { d.open = false; }), { once: true }); });
  /* Print the cost on paper or to PDF: the result pane only, in light colours, with every table opened. */
  function printSheet() {
    const root = document.documentElement, theme = root.dataset.theme;
    const closed = [...document.querySelectorAll(".cost-out details:not([open])")];
    closed.forEach(d => { d.open = true; });
    root.dataset.theme = "light"; document.body.classList.add("printing");
    const stamp = h("p", { class: "print-stamp" }, `RightPrice ex-mill should-cost · printed ${day(new Date())} · on the rates in the rate master that day`);
    $(".cost-out").prepend(stamp);
    const done = () => { root.dataset.theme = theme; document.body.classList.remove("printing"); closed.forEach(d => { d.open = false; }); stamp.remove(); removeEventListener("afterprint", done); };
    addEventListener("afterprint", done);
    setTimeout(() => print(), 60);
  }

  // the steps a chart draws: groups, or every sub-cost, each with its group's colour
  function chartItems(res, positiveOnly) {
    const items = [];
    res.buckets.forEach((b, i) => {
      const color = GROUP_COLOR[i % 8];
      if (state.wfMode === "groups") items.push({ name: b.name, group: b.name, amount: b.amount, color, basis: `${b.lines.length} sub-costs` });
      else for (const l of b.lines) items.push({ name: l.name, group: b.name, amount: l.amount, color, basis: l.basis });
    });
    return items.filter(it => positiveOnly ? it.amount > 0.005 : (state.showZero || Math.abs(it.amount) >= 0.005));
  }
  const bySize = (list, get) => state.bySize ? [...list].sort((p, q) => Math.abs(get(q)) - Math.abs(get(p))) : list;
  const itemTip = (it, total) => () => `<b>${it.name}</b>${it.group !== it.name ? it.group + "<br>" : ""}${rs(it.amount)} per metre · ${pct(total ? it.amount / total : 0)} of the price${it.basis && it.group !== it.name ? "<br>" + it.basis : ""}`;

  /* Bars: one bar per group from zero, with its name, share and rupees beside it. A group opens
     into its sub-costs on a click; 'All sub-costs' opens every group. */
  function barsChart(res) {
    const total = res.total_per_m;
    // with a quote on the chart, every bar shares the scale of the quote and the should-cost
    const top = res.quote !== null ? Math.max(total, res.quote) : Math.max(...res.buckets.map(b => Math.abs(b.amount)), 0.01);
    const box = h("div", { class: "bars", role: "list" });
    const row = (name, amount, color, cls, tipFn, button) => {
      const bar = h("div", { class: "bar" + (amount < 0 ? " neg" : ""), style: `width:${Math.max(0.6, Math.abs(amount) / top * 62)}%;background-color:var(${color})` });
      const text = h("span", { class: "bar-text" }, button || h("span", { class: "bar-name" }, name), h("span", { class: "bar-pct num" }, pct(total ? amount / total : 0, 0)), h("span", { class: "bar-amt num" }, `${rs(amount)} / m`));
      const el = h("div", { class: "bar-row " + cls, role: "listitem", tabindex: button ? null : "0" }, bar, text);
      withTip(el, tipFn); box.append(el);
    };
    bySize(res.buckets.map((b, i) => ({ b, i })), g => g.b.amount).forEach(({ b, i }) => {      // colour stays with the group, whatever the order
      const color = GROUP_COLOR[i % 8], open = state.wfMode === "all" || state.wfOpen.has(b.name);
      const btn = h("button", { type: "button", class: "bar-name", "aria-expanded": String(open), onclick: () => { open ? state.wfOpen.delete(b.name) : state.wfOpen.add(b.name); box.replaceWith(barsChart(res)); } }, h("span", { class: "caret", html: svg('<path d="m9 6 6 6-6 6"/>', 10) }), b.name);
      row(b.name, b.amount, color, "grp", () => `<b>${b.name}</b>${rs(b.amount)} per metre · ${pct(b.pct)} of the price`, btn);
      if (open) for (const l of bySize(b.lines.filter(l => state.showZero || Math.abs(l.amount) >= 0.005), l => l.amount))
        row(l.name, l.amount, color, "sub-row", itemTip({ name: l.name, group: b.name, amount: l.amount, basis: l.basis }, total));
    });
    if (res.quote !== null) {
      box.append(h("div", { class: "wf-sep", role: "presentation" }));
      const top2 = top;
      for (const [name, v, cls] of [["Should-cost", total, "totalbar"], ["Supplier's quote", res.quote, "quotebar"]])
        box.append(h("div", { class: "bar-row grp" }, h("div", { class: "bar " + cls, style: `width:${v / top2 * 62}%` }), h("span", { class: "bar-text" }, h("span", { class: "bar-name" }, name), h("span", { class: "bar-amt num" }, `${rs(v)} / m`))));
    }
    return box;
  }

  function pieChart(res) {
    let items = chartItems(res, true);
    if (state.bySize) {            // largest group first, and inside a group its largest sub-cost first, so one colour stays in one piece
      const groupSize = {}; for (const it of items) groupSize[it.group] = (groupSize[it.group] || 0) + it.amount;
      items = [...items].sort((p, q) => groupSize[q.group] - groupSize[p.group] || q.amount - p.amount);
    }
    const sum = items.reduce((a, it) => a + it.amount, 0) || 1, total = res.total_per_m;
    const R = 100, r = 58, C = 110;
    let a0 = -Math.PI / 2;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    g.setAttribute("viewBox", "0 0 220 220"); g.setAttribute("role", "img"); g.setAttribute("aria-label", "Share of the price by " + (state.wfMode === "groups" ? "cost group" : "sub-cost"));
    for (const it of items) {
      const a1 = a0 + it.amount / sum * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0, pt = (a, rad) => `${(C + rad * Math.cos(a)).toFixed(2)} ${(C + rad * Math.sin(a)).toFixed(2)}`;
      const p = document.createElementNS(g.namespaceURI, "path");
      p.setAttribute("d", items.length === 1 ? `M${C} ${C - R}A${R} ${R} 0 1 1 ${C - 0.01} ${C - R}L${C - 0.01} ${C - r}A${r} ${r} 0 1 0 ${C} ${C - r}Z` : `M${pt(a0, R)}A${R} ${R} 0 ${big} 1 ${pt(a1, R)}L${pt(a1, r)}A${r} ${r} 0 ${big} 0 ${pt(a0, r)}Z`);
      p.setAttribute("class", "slice"); p.style.fill = `var(${it.color})`; p.setAttribute("tabindex", "0");
      withTip(p, itemTip(it, total)); g.append(p); a0 = a1;
    }
    const mid = document.createElementNS(g.namespaceURI, "g");
    mid.innerHTML = `<text x="${C}" y="${C - 4}" text-anchor="middle" class="pie-big">${fmt(total)}</text><text x="${C}" y="${C + 16}" text-anchor="middle" class="pie-small">Rs per metre</text>`;
    g.append(mid);
    const list = h("div", { class: "pie-list" }, items.map(it => h("div", { class: "pie-item" }, h("span", { class: "dot", style: `background:var(${it.color})` }), h("span", { class: "pie-name" }, it.name), h("span", { class: "num" }, pct(it.amount / total, 0)), h("span", { class: "num pie-amt" }, fmt(it.amount)))));
    return h("div", { class: "pie" }, h("div", { class: "pie-svg" }, g), list);
  }

  function splitRects(items, x, y, w, hgt) {      // halve the list by value, cut the longer side, repeat
    if (!items.length) return [];
    if (items.length === 1) return [Object.assign({}, items[0], { x, y, w, h: hgt })];
    const total = items.reduce((a, it) => a + it.v, 0);
    let acc = 0, i = 0;
    while (i < items.length - 1 && (i === 0 || acc + items[i].v <= total / 2)) { acc += items[i].v; i++; }
    const f = acc / total, a = items.slice(0, i), b = items.slice(i);
    return w >= hgt ? [...splitRects(a, x, y, w * f, hgt), ...splitRects(b, x + w * f, y, w * (1 - f), hgt)] : [...splitRects(a, x, y, w, hgt * f), ...splitRects(b, x, y + hgt * f, w, hgt * (1 - f))];
  }
  function treemapChart(res) {
    const total = res.total_per_m, W = 100, H = 46;      // drawn in a 100 x 46 box, as percentages
    const groups = res.buckets.map((b, i) => ({ b, color: GROUP_COLOR[i % 8], v: b.lines.reduce((a, l) => a + Math.max(l.amount, 0), 0) })).filter(g => g.v > 0.005).sort((p, q) => q.v - p.v);
    const box = h("div", { class: "treemap", role: "list", style: `aspect-ratio:${W}/${H}` });
    const place = (el, r, bw, bh) => { el.style.cssText += `left:${r.x / bw * 100}%;top:${r.y / bh * 100}%;width:${r.w / bw * 100}%;height:${r.h / bh * 100}%;`; return el; };
    for (const g of splitRects(groups, 0, 0, W, H)) {
      const cell = place(h("div", { class: "tm-group", role: "listitem", tabindex: "0", style: `background-color:var(${g.color});` }), g, W, H);
      const fits = (r, bw, bh) => r.w / bw * (g.w / W) > 0.085 && r.h / bh * (g.h / H) > 0.11;      // room for a label, as a share of the whole chart
      const label = h("div", { class: "tm-label" }, h("b", {}, g.b.name), h("span", { class: "num" }, `${fmt(g.b.amount)} · ${pct(g.b.pct, 0)}`));
      if (state.wfMode === "groups") { cell.append(label); withTip(cell, () => `<b>${g.b.name}</b>${rs(g.b.amount)} per metre · ${pct(g.b.pct)} of the price`); }
      else {
        const inner = h("div", { class: "tm-inner" });
        const kids = g.b.lines.filter(l => l.amount > 0.005).map(l => ({ l, v: l.amount })).sort((p, q) => q.v - p.v);
        for (const k of splitRects(kids, 0, 0, g.w, g.h)) {
          const kid = place(h("div", { class: "tm-kid", tabindex: "0", "aria-label": `${k.l.name}, ${fmt(k.l.amount)} rupees per metre` }, fits(k, g.w, g.h) ? h("div", { class: "tm-label" }, h("b", {}, k.l.name), h("span", { class: "num" }, fmt(k.l.amount))) : null), k, g.w, g.h);
          withTip(kid, itemTip({ name: k.l.name, group: g.b.name, amount: k.l.amount, basis: k.l.basis }, total)); inner.append(kid);
        }
        cell.removeAttribute("tabindex"); cell.append(inner);
      }
      box.append(cell);
    }
    return box;
  }

  function buildLine(res) {
    const items = chartItems(res, false), total = res.total_per_m;
    const narrow = boxWidth() < 700, W = narrow ? 430 : 760, H = narrow ? 380 : 360, m = { l: 46, r: 16, t: 20, b: state.wfMode === "all" ? 130 : 100 };
    let run = 0; const pts = items.map(it => { run += it.amount; return { it, y: run }; });
    const top = Math.max(...pts.map(p => p.y), total, 1), n = pts.length;
    const X = i => m.l + (n === 1 ? 0.5 : i / (n - 1)) * (W - m.l - m.r), Y = v => m.t + (1 - v / top) * (H - m.t - m.b);
    let g = "";
    for (let k = 0; k <= 4; k++) { const v = top * k / 4; g += `<line class="grid-line" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis-text" x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, 0)}</text>`; }
    const path = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(p.y).toFixed(1)}`).join("");
    const el = h("div", { class: "chart", html: `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Running total of the price after each step, ending at ${fmt(total)} rupees per metre">${g}<path class="line" style="stroke:var(--total)" d="${path}"/></svg>` });
    const s = el.firstChild, ns = s.namespaceURI;
    pts.forEach((p, i) => {
      const c = document.createElementNS(ns, "circle"); c.setAttribute("cx", X(i)); c.setAttribute("cy", Y(p.y)); c.setAttribute("r", 6); c.setAttribute("class", "pt"); c.style.fill = `var(${p.it.color})`; c.setAttribute("tabindex", "0");
      withTip(c, () => `<b>${p.it.name}</b>+${fmt(p.it.amount)} → running total ${rs(p.y)}`); s.append(c);
      const t = document.createElementNS(ns, "text"); t.setAttribute("class", "axis-text"); t.setAttribute("text-anchor", "end"); t.setAttribute("transform", `translate(${X(i) + 4} ${H - m.b + 16}) rotate(-50)`); const cut = narrow ? 15 : 22; t.textContent = p.it.name.length > cut ? p.it.name.slice(0, cut - 1) + "…" : p.it.name; if (!(narrow && n > 12 && i % 2)) s.append(t);
    });
    const end = document.createElementNS(ns, "text"); end.setAttribute("class", "pie-small"); end.setAttribute("x", X(n - 1)); end.setAttribute("y", Y(pts[n - 1].y) - 12); end.setAttribute("text-anchor", "end"); end.textContent = `Rs ${fmt(total)} / m`; s.append(end);
    return el;
  }

  /* Waterfall: each step starts where the one before ended. In 'groups' a group is one bar that
     opens into its sub-costs; in 'all' every group is open. A discount steps back to the left. */
  function waterfall(res) {
    const total = res.total_per_m;
    let run = 0, peak = 0;
    for (const b of res.buckets) for (const l of b.lines) { run += l.amount; peak = Math.max(peak, run); }
    if (res.quote !== null) peak = Math.max(peak, res.quote);
    const scale = v => (v / (peak || 1)) * 100;
    const box = h("div", { class: "wf", role: "list" });
    const bar = (from, amount, cls, color) => {
      const lo = Math.min(from, from + amount), w = Math.abs(amount);
      return h("div", { class: "wf-bar " + cls + (amount < 0 ? " neg" : ""), style: `left:${scale(lo)}%;width:${scale(w)}%;${color ? `background-color:var(${color})` : ""}` });
    };
    const row = (o) => {
      const el = h("div", { class: "wf-row " + (o.cls || ""), role: "listitem", tabindex: o.button ? null : "0" },
        h("div", { class: "wf-label " + (o.labelCls || ""), title: o.name || null }, o.button || [o.color ? h("span", { class: "dot", style: `background:var(${o.color})` }) : null, h("span", { class: "txt" }, o.name)]),
        h("div", { class: "wf-track" }, o.bar),
        h("div", { class: "wf-val " + (o.labelCls || "") }, o.value));
      if (o.tip) withTip(el, o.tip);
      box.append(el);
    };
    run = 0;
    res.buckets.forEach((b, i) => {
      const color = GROUP_COLOR[i % 8], start = run, open = state.wfMode === "all" || state.wfOpen.has(b.name);
      const lines = b.lines.filter(l => state.showZero || Math.abs(l.amount) >= 0.005);
      const tipG = () => `<b>${b.name}</b>${rs(b.amount)} per metre · ${pct(b.pct)} of the price<br>Running total ${rs(start + b.amount)}`;
      const toggle = state.wfMode === "groups" ? h("button", { type: "button", "aria-expanded": String(open), onclick: () => { open ? state.wfOpen.delete(b.name) : state.wfOpen.add(b.name); box.replaceWith(waterfall(res)); } },
        h("span", { class: "caret", html: svg('<path d="m9 6 6 6-6 6"/>', 10) }), h("span", { class: "dot", style: `background:var(${color})` }), h("span", { class: "txt" }, b.name)) : null;
      if (!open || (state.wfMode === "all" && !lines.length)) {       // closed, or nothing in it to show
        if (!toggle) { row({ name: b.name, color, labelCls: "total", bar: bar(start, b.amount, "", color), value: fmt(b.amount), tip: tipG }); run += b.amount; return; }
        row({ button: toggle, bar: bar(start, b.amount, "", color), value: fmt(b.amount), tip: tipG });
        run += b.amount;
        return;
      }
      row({ cls: "head", button: toggle, name: b.name, color, labelCls: "total", bar: bar(start, b.amount, "sumbar"), value: [fmt(b.amount), h("small", {}, pct(b.pct))], tip: tipG });
      for (const l of lines) {
        const from = run;
        row({ name: l.name, labelCls: "step", bar: bar(from, l.amount, "", color), value: fmt(l.amount),
          tip: () => `<b>${l.name}</b>${rs(l.amount)} per metre · ${pct(total ? l.amount / total : 0)} of the price<br>${l.basis}` });
        run += l.amount;
      }
      run = start + b.amount;
    });
    box.append(h("div", { class: "wf-sep", role: "presentation" }));
    row({ cls: "sum", name: "Should-cost", labelCls: "total", bar: bar(0, total, "totalbar"), value: fmt(total), tip: () => `<b>Should-cost</b>${rs(total)} per metre, ex-mill` });
    if (res.quote !== null) {
      const above = res.gap >= 0;
      row({ cls: "sum", name: "Supplier's quote", labelCls: "total", bar: [bar(0, res.quote, "quotebar"), h("div", { class: "wf-gap " + (above ? "over" : "under"), style: `left:${scale(Math.min(total, res.quote))}%;width:${scale(Math.abs(res.gap))}%` })],
        value: [fmt(res.quote), h("small", {}, `${above ? "+" : "−"}${pct(Math.abs(res.gap_pct))}`)],
        tip: () => `<b>Supplier's quote</b>${rs(res.quote)} per metre<br>${rs(Math.abs(res.gap))} (${pct(Math.abs(res.gap_pct))}) ${above ? "above" : "below"} should-cost` });
    }
    box.append(h("div", { class: "wf-axis", "aria-hidden": "true" }, h("span", {}, "Rs 0"), h("span", { class: "mid" }, `Rs ${fmt(peak / 2, 0)}`), h("span", {}, `Rs ${fmt(peak, 0)}/m`)));
    return box;
  }

  /* A fabric opened in Create cost from elsewhere (Right cost, a list row): its choices and the list row it came from.
     With no choices, a new fabric. */
  function open(choices, listId) {
    state.sel = choices ? selFromRow(choices) : blankSel(); state.listId = listId || null; state.rowNotes = null; state.sim = null; state.reopened = null; state.openStep = null;
    if (choices) STEPS.forEach(st => state.visited.add(st.id)); else state.visited.clear();
  }

  RP.cost = { open, STEPS, STANCE, stanceFor, ready, payload, selFromRow, blankSel };
})();
