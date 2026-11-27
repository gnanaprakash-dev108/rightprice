"""A fabric's construction as one text: the nine fields that make two fabrics the same cloth, whatever their colour or
mill (content, route, weave, warp, weft, EPI, PPI, finished width, finish), tidied and joined.

Stage 2 builds the Fab groups on the same nine fields, in the database. Until that is merged this one small function
stands in for them (calibrate_splits.py uses it to keep a construction on one side of a test); stage 2's signature can
replace it, and nothing else need change.
"""
import re

FIELDS = ("content", "route", "weave", "warp", "weft", "epi", "ppi", "finished width (in)", "finish")


def _text(v):
    return re.sub(r"\s+", " ", str("" if v is None else v).strip().lower())


def _number(v):
    try:
        return f"{round(float(v), 1):g}"
    except (TypeError, ValueError):
        return _text(v)


def signature(content, route, weave, warp, weft, epi, ppi, width_in, finish):
    """'100% cotton | yarn dyed | twill-2/1 | cotton 40s | cotton 40s | 136 | 90 | 58 | normal'"""
    return " | ".join([_text(content), _text(route), _text(weave), _text(warp), _text(weft),
                       _number(epi), _number(ppi), _number(width_in), _text(finish)])
