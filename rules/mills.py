"""Mill identity: one mill written several ways is one mill."""
import re


MILL_WORDS = {"ltd", "limited", "mills", "mill", "pvt", "private", "co", "company", "the", "p"}


_mill_alias = {}        # a name cut short in the purchase-order data -> the full name it is the start of (set in costs())


def _mill_base(name):
    words = re.sub(r"[^\w\u0900-\u0DFF ]+|_", " ", str(name or "").lower()).split()      # Indian scripts keep their vowel signs
    cut_ = lambda w: len(w) >= 3 and ("limited".startswith(w) or "private".startswith(w))
    keep = [w for w in words if w not in MILL_WORDS and not cut_(w)]
    if len(keep) > 1 and keep[-1] in ("l", "li", "lt"):          # "Raymond Luxury Cottons L": the name was cut off inside Ltd or Limited
        keep = keep[:-1]
    # Fashion and Fashions, Industrie (cut short) and Industries are one word
    return " ".join((w[:-1] if len(w) > 4 and w.endswith("s") else w) for w in (keep or words))


def mill_key(name, aliases=None):
    """One key for a mill however its name is written: "Arvind", "Arvind Ltd" and "ARVIND LIMITED" are one mill.
    Purchase-order names are cut at 24 characters ("Rajapalayam Mills Limite", "Nahar Industrial Enterpr"), so a cut-off
    Limited goes, and a cut-off name that is the start of exactly one fuller name is that mill. `aliases` (from
    mill_aliases) in place of the names Right cost last learned."""
    k = _mill_base(name)
    return (_mill_alias if aliases is None else aliases).get(k, k)


def mill_aliases(names):
    """Names cut short at 23 or 24 characters that are the start of exactly one other mill's name: {cut key: full key}."""
    bases, out = {}, {}
    for n in names:
        if n:
            bases.setdefault(_mill_base(n), set()).add(str(n).strip())
    for k, raw in bases.items():
        if len(k) >= 10 and any(len(r) >= 23 for r in raw):
            longer = [k2 for k2 in bases if k2 != k and k2.startswith(k)]
            if len(longer) == 1:
                out[k] = longer[0]
    return out


def _learn_mill_names(names):
    """Names cut short at 23 or 24 characters that are the start of exactly one other mill's name."""
    learned = mill_aliases(names)
    _mill_alias.clear()
    _mill_alias.update(learned)
