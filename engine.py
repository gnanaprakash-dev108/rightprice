"""Woven fabric should-be cost engine.

Same arithmetic as 'Should be Cost V1 23rd Nov.xlsx', corrected method:
  warp kg/m = EPI x finished width x K x (1+warp crimp) x (1+warp wastage) / warp Ne
  weft kg/m = PPI x reed space x K x (1+weft wastage) / weft Ne
  base      = yarn + yarn dyeing + sizing + weaving + finishing + piece dyeing
  price     = base / (1-shrinkage) x (1 + process wastage + overhead) x (1 + margin) + extra

Everything here is plain numbers in, plain numbers out. Turning drop-down
choices into rates is done in masters.resolve().
"""

K_DEFAULT = 0.00059  # kg per end-metre for Ne 1, as in the V1 workbook


def to_ne(count, system="Ne"):
    """Convert a count in another system to English cotton count (Ne)."""
    count = float(count)
    if system == "Nm":
        return count / 1.6934
    if system == "Denier":
        return 5315.0 / count
    if system == "Tex":
        return 590.5 / count
    return count


def _n(d, key, default=0.0):
    v = d.get(key, default)
    try:
        if v is None or v == "" or v != v:  # v != v catches NaN
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def compute(inp):
    """Return the full cost build-up for one fabric.

    inp keys (all numeric): epi, ppi, width_in, reed_in, warp_ne, weft_ne,
    warp_rate, weft_rate, warp_dye, weft_dye, warp_crimp, warp_wastage,
    weft_wastage, weaving_rate, sizing_rate, finishing_rate, piece_dye_rate,
    extra_per_m, shrinkage, process_wastage, overhead, margin, k.
    Optional: weft_crimp + weft_method='Old' reproduces the old sheets.
    """
    k = _n(inp, "k", K_DEFAULT)
    epi, ppi = _n(inp, "epi"), _n(inp, "ppi")
    width, reed = _n(inp, "width_in"), _n(inp, "reed_in")
    warp_ne, weft_ne = _n(inp, "warp_ne"), _n(inp, "weft_ne")
    if min(epi, ppi, width, reed, warp_ne, weft_ne) <= 0:
        raise ValueError("EPI, PPI, width, reed space and both counts must be above zero")

    wc, ww = _n(inp, "warp_crimp"), _n(inp, "warp_wastage")
    wfw, wfc = _n(inp, "weft_wastage"), _n(inp, "weft_crimp")
    old = str(inp.get("weft_method", "Corrected")).startswith("Old")
    weft_allow = wfc if old else wfw

    warp_kg = epi * width * k * (1 + wc) * (1 + ww) / warp_ne
    weft_kg = ppi * reed * k * (1 + weft_allow) / weft_ne
    greige_kg = warp_kg + weft_kg

    warp_rate, weft_rate = _n(inp, "warp_rate"), _n(inp, "weft_rate")
    warp_dye, weft_dye = _n(inp, "warp_dye"), _n(inp, "weft_dye")
    weaving_rate, sizing_rate = _n(inp, "weaving_rate"), _n(inp, "sizing_rate")
    fin_rate, pd_rate = _n(inp, "finishing_rate"), _n(inp, "piece_dye_rate")
    extra = _n(inp, "extra_per_m")
    shrink, pw = _n(inp, "shrinkage"), _n(inp, "process_wastage")
    oh, margin = _n(inp, "overhead"), _n(inp, "margin")
    if shrink >= 1:
        raise ValueError("Shrinkage must be below 100%")

    warp_yarn = warp_kg * warp_rate
    weft_yarn = weft_kg * weft_rate
    warp_dyeing = warp_kg * warp_dye
    weft_dyeing = weft_kg * weft_dye
    sizing = warp_kg * sizing_rate
    weaving = ppi * weaving_rate
    finishing = greige_kg * fin_rate
    piece_dyeing = greige_kg * pd_rate

    base = (warp_yarn + weft_yarn + warp_dyeing + weft_dyeing + sizing + weaving
            + finishing + piece_dyeing)
    shrink_cost = base * (1 / (1 - shrink) - 1)
    subtotal = base + shrink_cost
    pw_cost = subtotal * pw
    oh_cost = subtotal * oh
    margin_cost = (subtotal + pw_cost + oh_cost) * margin
    total = subtotal + pw_cost + oh_cost + margin_cost + extra

    # Fabric weight: yarn that stays in the cloth (no wastage), per finished metre.
    fab_warp = epi * width * k * (1 + wc) / warp_ne
    fab_weft = ppi * reed * k / weft_ne
    finished_kg = (fab_warp + fab_weft) / (1 - shrink)
    gsm = finished_kg * 1000 / (width * 0.0254)

    def line(name, basis, amount):
        return {"name": name, "basis": basis, "amount": amount}

    buckets = [
        {"name": "Yarn", "lines": [
            line("Warp yarn", f"{warp_kg:.4f} kg/m x Rs {warp_rate:,.0f}/kg", warp_yarn),
            line("Weft yarn", f"{weft_kg:.4f} kg/m x Rs {weft_rate:,.0f}/kg", weft_yarn)]},
        {"name": "Yarn dyeing", "lines": [
            line("Warp yarn dyeing", f"{warp_kg:.4f} kg/m x Rs {warp_dye:,.0f}/kg", warp_dyeing),
            line("Weft yarn dyeing", f"{weft_kg:.4f} kg/m x Rs {weft_dye:,.0f}/kg", weft_dyeing)]},
        {"name": "Sizing and weaving", "lines": [
            line("Sizing", f"{warp_kg:.4f} kg warp x Rs {sizing_rate:,.0f}/kg", sizing),
            line("Weaving", f"{ppi:g} picks/inch x Rs {weaving_rate:.3f}/pick", weaving)]},
        {"name": "Dyeing and finishing", "lines": [
            line("Piece dyeing", f"{greige_kg:.4f} kg greige x Rs {pd_rate:,.0f}/kg", piece_dyeing),
            line("Finishing", f"{greige_kg:.4f} kg greige x Rs {fin_rate:,.0f}/kg", finishing),
            line("Extra charge", "fixed Rs/m, not marked up", extra)]},
        {"name": "Losses", "lines": [
            line("Finishing shrinkage", f"{shrink:.1%} of length lost", shrink_cost),
            line("Process wastage", f"{pw:.1%} of subtotal", pw_cost)]},
        {"name": "Overhead", "lines": [
            line("Mill overhead", f"{oh:.1%} of subtotal", oh_cost)]},
        {"name": "Margin", "lines": [
            line("Mill margin", f"{margin:.1%} on cost", margin_cost)]},
    ]
    for b in buckets:
        b["amount"] = sum(l["amount"] for l in b["lines"])
        b["pct"] = b["amount"] / total if total else 0.0

    return {
        "total_per_m": total,
        "per_kg": total / finished_kg if finished_kg else 0.0,
        "gsm": gsm,
        "finished_g_per_m": finished_kg * 1000,
        "warp_kg": warp_kg, "weft_kg": weft_kg, "greige_kg": greige_kg,
        "base": base, "subtotal": subtotal,
        "buckets": buckets,
    }
