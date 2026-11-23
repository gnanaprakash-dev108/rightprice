"""Group thousands of fabric content (blend) spellings into a short list.

'65%Cotton30%Polyester5%Spandex' -> {'Cotton': 65, 'Polyester': 30, 'Elastane': 5}
                                 -> 'Cotton-rich polyester blend, stretch'
The rules are deliberately few, so a buyer can read the whole list.
"""
import re

# spelling -> standard fibre name
FIBRE = {
    "cotton": "Cotton", "bcicotton": "Cotton", "organiccotton": "Cotton", "supimacotton": "Cotton",
    "gizacotton": "Cotton", "pimacotton": "Cotton", "recycledcotton": "Cotton", "cottonbci": "Cotton",
    "polyester": "Polyester", "polyster": "Polyester", "poly": "Polyester", "recycledpolyester": "Polyester",
    "pet": "Polyester", "viscose": "Viscose", "rayon": "Viscose", "viscoserayon": "Viscose",
    "bamboo": "Viscose", "bambooviscose": "Viscose", "ecovero": "Viscose", "livaeco": "Viscose",
    "modal": "Modal", "micromodal": "Modal", "lyocell": "Lyocell", "tencel": "Lyocell",
    "excel": "Lyocell", "linen": "Linen", "flax": "Linen", "hemp": "Linen", "ramie": "Linen",
    "spandex": "Elastane", "elastane": "Elastane", "lycra": "Elastane", "elasthane": "Elastane",
    "elastomultiester": "Elastane", "t400": "Elastane", "nylon": "Nylon", "polyamide": "Nylon",
    "wool": "Wool", "merinowool": "Wool", "cashmere": "Wool", "silk": "Silk", "acrylic": "Acrylic",
    "acetate": "Other", "cupro": "Other", "metallic": "Other", "lurex": "Other",
    "terelene": "Polyester", "terylene": "Polyester", "coolmax": "Polyester", "thermolite": "Polyester",
    "cationicdyed": "Polyester", "elastine": "Elastane", "elastin": "Elastane", "spendex": "Elastane",
    "xla": "Elastane", "tfourhundred": "Elastane", "sorona": "Elastane", "biosorona": "Elastane",
    "triexta": "Elastane", "freefit": "Elastane", "merino": "Wool", "angora": "Wool", "viscos": "Viscose",
    "tactel": "Nylon",
}
CELLULOSIC = {"Viscose", "Modal", "Lyocell"}
PART = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*([A-Za-z][A-Za-z0-9 \-/]*?)(?=\d|$)")


def parse_blend(text):
    """Return {fibre: percent}. Unknown fibres are kept under 'Other'."""
    if text is None:
        return {}
    out = {}
    text = re.sub(r"T-?\s?400", "Tfourhundred", str(text).replace("\n", " "), flags=re.I)
    text = re.sub(r"(?<=[A-Za-z])%(?=\d)", "", text)   # 'Rayon%29%Polyester' typo
    for pct, name in PART.findall(text):
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        fibre = FIBRE.get(key)
        if fibre is None:
            fibre = next((v for k, v in FIBRE.items() if len(k) > 3 and k in key), "Other")
        out[fibre] = out.get(fibre, 0) + float(pct)
    return out


def blend_group(text):
    """Short content group for a blend string (stretch is reported separately)."""
    b = parse_blend(text)
    if not b or not 98 <= sum(b.values()) <= 102:
        return "Not readable"
    el = b.get("Elastane", 0)
    rest = {k: v for k, v in b.items() if k != "Elastane"}
    if not rest:
        return "Other blends"
    main = max(rest, key=rest.get)
    cot, pes, lin = rest.get("Cotton", 0), rest.get("Polyester", 0), rest.get("Linen", 0)
    cel = sum(rest.get(f, 0) for f in CELLULOSIC)
    wool, nyl = rest.get("Wool", 0), rest.get("Nylon", 0)

    if wool >= 10:
        return "Wool and wool blends"
    if len(rest) == 1:
        if main in CELLULOSIC:
            return "Viscose, modal or lyocell"
        return {"Cotton": "Cotton with stretch" if el else "100% cotton", "Polyester": "100% polyester",
                "Linen": "100% linen", "Nylon": "Nylon and nylon blends"}.get(main, "Other blends")
    if lin >= 15:
        return "Cotton linen" if cot >= 15 and cot + lin >= 85 else "Linen blends"
    if pes and cel and pes + cel >= 85:
        return "Polyester viscose (PV)"
    if cot and pes and cot + pes >= 85:
        return "Cotton-rich polyester blend (CVC)" if cot >= pes else "Polyester-rich cotton blend (PC)"
    if cot and cel and cot + cel >= 85:
        return "Cotton with viscose, modal or lyocell"
    if nyl >= 15:
        return "Nylon and nylon blends"
    if cot >= 50:
        return "Other cotton-rich blends"
    if pes >= 50:
        return "Other polyester-rich blends"
    return "Other blends"


def has_stretch(text):
    return parse_blend(text).get("Elastane", 0) > 0


WEAVE_GROUP_RULES = [  # first match wins; text is lower-cased
    ("jacquard", "Jacquard"), ("brocade", "Jacquard"),
    ("velvet", "Corduroy"), ("pile", "Corduroy"), ("corduroy", "Corduroy"),
    ("oxford", "Oxford"), ("satin", "Satin"), ("sateen", "Satin"),
    ("plain and", "Dobby/Matt"), ("dobby", "Dobby/Matt"), ("matt", "Dobby/Matt"), ("basket", "Dobby/Matt"),
    ("honeycomb", "Dobby/Matt"), ("waffle", "Dobby/Matt"), ("mockleno", "Dobby/Matt"), ("crepe", "Dobby/Matt"),
    ("bedford", "Dobby/Matt"), ("ottoman", "Dobby/Matt"), ("ribstop", "Dobby/Matt"), ("ripstop", "Dobby/Matt"),
    ("double", "Dobby/Matt"), ("royal", "Dobby/Matt"), ("birds eye", "Dobby/Matt"), ("fancy", "Dobby/Matt"),
    ("twill", "Twill"), ("herringbone", "Twill"), ("hbt", "Twill"), ("drill", "Twill"),
    ("gabardine", "Twill"), ("denim", "Twill"), ("chino", "Twill"),
    ("plain", "Plain"), ("poplin", "Plain"), ("gauze", "Plain"), ("rib", "Plain"), ("canvas", "Plain"),
    ("voile", "Plain"), ("cambric", "Plain"), ("chambray", "Plain"),
]


def weave_group(text):
    """Map any weave spelling to one of the seven weave groups that carry a weaving rate."""
    t = "" if text is None else str(text).strip().lower()
    for key, group in WEAVE_GROUP_RULES:
        if key in t:
            return group
    return None


if __name__ == "__main__":
    for t in ["100%Cotton", "98%Cotton2%Spandex", "65%Cotton30%Polyester5%Spandex", "60%Polyester40%Cotton",
              "50%Linen50%Polyester", "47%Rayon32%Nylon16%Polyester5%Spandex", "65%Polyester35%Viscose",
              "55%Linen45%Cotton", "100% Cotton BCI", "PVL 62/33/5"]:
        print(f"{t:45s} {parse_blend(t)}  ->  {blend_group(t)}")
