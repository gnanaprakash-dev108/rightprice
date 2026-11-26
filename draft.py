"""E-mail and WhatsApp drafts to a mill, written by Claude from the figures RightPrice already holds.

Nothing is sent by the tool: the draft is shown, edited and copied by the buyer. Each call writes a fresh draft.
Only the figures of the fabrics asked about go to the API: no price list, no rate master, no other mill.
Without ANTHROPIC_API_KEY (an app setting on Azure) a plain template is filled from the same figures instead.
"""
import os
import random
import re

MODEL = "claude-opus-5-5"
ASKS = {"breakup": "the cost break-up", "price": "a revised price", "both": "the cost break-up and a revised price"}

SYSTEM = """You draft messages for a fabric buyer at an Indian apparel company who is writing to the sales contact at a weaving mill about woven fabric prices (ex-mill, rupees per metre).

Write the way a seasoned buyer writes to a mill they will keep buying from: plain, courteous and firm, in Indian business English. Short sentences. No flattery, no apology, no threats, no jargon, and none of the stock phrases that mark a message as machine-written ("I hope this finds you well", "kindly do the needful", "circle back", "as per", dashes used for effect). It should read as typed by a person between meetings.

What you are given is a JSON object: who is writing, the mill, what the buyer wants from this message, and for each fabric its code, quantity, the mill's price, its "purpose", sometimes "price_to_name", and "points". The points are the buyer's private working, written for the buyer: use them to understand the case, and put to the mill only what a buyer would say aloud.

What each purpose means:
- "revise": a live quote that is too high. Ask for what the buyer wants. If price_to_name is given, that is the price to put to the mill (it is the buyer's own counter when our_counter is given: say "our counter of Rs ..."; otherwise say it is what our costing supports). If mills_own_build_up is given, the mill's own sheet adds up to that figure, less than it asks: say so plainly.
- "breakup_only": the buyer cannot judge this price yet. Ask only for the cost break-up (yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish, margin). Do not call the price high and do not name any price.
- "confirm_price": the price looks too low to be right. Ask the mill to confirm it is per metre, for this construction and finish. Do not ask for a revised price on it.
- Any fabric with already_bought true was bought at that price: speak of "the last order" and ask for the next order of the same cloth, never as a claim on the order already paid.
- "next_order": already bought at that price. Raise it for the next order of the same cloth, never as a claim on the order already paid.

Rules that matter more than style:
- Use only the figures given. Do not add, round, average or infer any figure, date, name or fact. If a name is missing, write the bracketed placeholder exactly as given.
- Never reveal a ceiling, a fallback, a range, or the highest price the buyer would accept. The only price of the buyer's you may name for a fabric is its price_to_name. If a point says "do not go above Rs ..." or "aim for Rs ...", that figure stays out of the message.
- Write rupees as "Rs 185.00" and metres as given.
- Say "our costing" or "our working" for the buyer's figures. Never mention software, a tool, a model, AI, "should-cost" or "usual range".
- Ask for a reply by a reasonable time without naming a date.
- For several fabrics, deal with each in a line or two, in the order given. Do not build a table.
- Do not promise an order, a quantity or anything else the figures do not say.

Reply in exactly this layout and nothing else:
SUBJECT: <one line>
EMAIL:
<the e-mail, at most about 170 words for one fabric and 280 for several, ending with the writer's name>
WHATSAPP:
<the same ask as one message a person would type on a phone, at most about 60 words, courteous>"""

OPENERS = ["Open straight with the fabric and the ask.", "Open with one line placing the quote (which fabric, which sheet or call), then the ask.",
           "Open by saying you have gone through the price and have a point to raise.", "Open with the figure that needs explaining."]


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _money(v):
    return None if v is None else round(float(v), 2)


def template(facts):
    """The plain draft used when there is no API key, or the API could not be reached. Same figures, fixed wording.
    Only what is for the mill: the buyer's own points are shown beside the draft, never inside it."""
    who, to = facts["writer"], facts["contact"]
    items = facts["items"]
    codes = ", ".join(i["code"] for i in items[:4]) + (f" and {len(items) - 4} more" if len(items) > 4 else "")
    live = [i for i in items if i["purpose"] in ("revise", "breakup_only")]
    only_breakup = facts["ask"] == "breakup" or not any(i["purpose"] in ("revise", "next_order") for i in items)
    confirm_only = all(i["purpose"] == "confirm_price" for i in items)
    ask = "confirmation of the price" if confirm_only else ASKS["breakup"] if only_breakup else ASKS[facts["ask"]]
    qty = lambda i: f" ({i['quantity']} m)" if i.get("quantity") else ""
    rs = lambda v: f"Rs {v:,.2f}"
    lines = [f"Dear {to},", ""]
    if confirm_only:
        lines.append(f"Before we take {codes} further, we need you to confirm the price.")
    elif all(i.get("already_bought") for i in items):
        lines.append(f"Before the next order of {codes}, we need {ask}.")
    else:
        lines.append(f"We have gone through your price for {codes} and need {ask} before we can take it further.")
    lines.append("")
    for i in items:
        p = i["purpose"]
        if p == "confirm_price":
            lines.append(f"{i['code']}{qty(i)}: please confirm that {rs(i['price'])} is the price per metre for this construction and finish.")
        elif p == "breakup_only" and i.get("already_bought"):
            lines.append(f"{i['code']}{qty(i)}: the last order was at {rs(i['price'])} a metre. Before the next order of this cloth, please send the cost break-up: yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish and margin.")
        elif p == "breakup_only" or (only_breakup and p == "revise"):
            lines.append(f"{i['code']}{qty(i)}: your price is {rs(i['price'])} a metre. Please send the cost break-up: yarn count and rate, wastage, weaving per pick, dyeing per kilo, finish and margin.")
        elif p == "next_order":
            lines.append(f"{i['code']}{qty(i)}: the last order was at {rs(i['price'])} a metre." + (f" For the next order our costing supports {rs(i['price_to_name'])}." if i.get("price_to_name") and not only_breakup else "")
                         + " Please send the cost break-up for this cloth.")
        else:
            said = (f" Our counter is {rs(i['price_to_name'])}." if i.get("our_counter") is not None else f" Our costing supports {rs(i['price_to_name'])}.") if i.get("price_to_name") else ""
            own = f" Your own sheet adds up to {rs(i['mills_own_build_up'])} for it." if i.get("mills_own_build_up") else ""
            lines.append(f"{i['code']}{qty(i)}: your price is {rs(i['price'])} a metre.{own}{said}")
    lines += ["", "Please reply at the earliest." if confirm_only or only_breakup else "Please reply at the earliest so that we can close the price.", "", "Regards,", who]
    first = items[0]
    if confirm_only:
        wa = f"{to}, please confirm that {rs(first['price'])} for {first['code']} is per metre for this construction and finish" + (f" (and the same for {len(items) - 1} more, details by mail)" if len(items) > 1 else "") + f". Thank you. {who}"
    else:
        named = first.get("price_to_name") if first["purpose"] == "revise" and not only_breakup else None
        wa = (f"{to}, on {codes}: we need {ask} before {'the next order' if all(i.get('already_bought') for i in items) else 'we can go ahead'}."
              + (f" For {first['code']} {'our counter is' if first.get('our_counter') is not None else 'our costing supports'} {rs(named)} against your {rs(first['price'])}." if named else "")
              + f" Please reply when you can. Thank you. {who}")
    return {"subject": f"{codes}: request for {ask}", "email": "\n".join(lines), "whatsapp": wa}


def parse(text):
    """The three parts of Claude's reply. A reply that does not follow the layout is refused, not guessed at."""
    m = re.search(r"SUBJECT:\s*(.+?)\s*\n\s*EMAIL:\s*\n?(.*?)\n\s*WHATSAPP:\s*\n?(.*)\Z", text.strip(), re.S)
    if not m or not m.group(2).strip() or not m.group(3).strip():
        raise ValueError("the reply did not have a subject, an e-mail and a WhatsApp message")
    return {"subject": m.group(1).strip(), "email": m.group(2).strip(), "whatsapp": m.group(3).strip()}


def write(facts, client=None):
    """A fresh draft from Claude. Returns {subject, email, whatsapp, source, note}. Never raises: when the API cannot be
    used the template is returned with a note saying why, so the buyer always has something to edit."""
    import json
    if client is None and not available():
        return dict(template(facts), source="template", note="Written from a fixed template, not by Claude: the Claude key has not been set up on this server "
                    "(whoever looks after RightPrice's Azure settings adds it as ANTHROPIC_API_KEY). The figures are right and the draft is safe to use; "
                    "the wording is the same every time.")
    try:
        import anthropic
        client = client or anthropic.Anthropic(timeout=60.0, max_retries=1)
        payload = dict(facts, how_to_open=random.choice(OPENERS))
        # Opus 5.5 thinks adaptively (it cannot be switched off); low effort is enough for a short letter.
        # Server-side fallbacks: if the model declines, the API re-runs the request on its default fallback.
        res = client.beta.messages.create(
            model=MODEL, max_tokens=4000, system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Write the e-mail and the WhatsApp message for this.\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)}])
        if res.stop_reason == "refusal":
            return dict(template(facts), source="template", note="Claude declined to write this one, so a fixed template is shown instead. The figures are the same.")
        if res.stop_reason == "max_tokens":
            raise ValueError("the reply was cut off")
        text = "".join(b.text for b in res.content if b.type == "text")
        return dict(parse(text), source="claude", note="Written by Claude from the figures above. Read it before you send it: nothing is sent by RightPrice.")
    except Exception as e:      # no network, a bad key, a rate limit, a reply out of layout: the buyer still gets a draft
        kind = type(e).__name__
        why = {"AuthenticationError": "the Claude API key was not accepted", "RateLimitError": "the Claude API is busy (rate limit); try again in a minute",
               "APIConnectionError": "the Claude API could not be reached", "APITimeoutError": "the Claude API took too long",
               "PermissionDeniedError": "the Claude API key is not allowed to use this model"}.get(kind, f"the draft could not be written ({kind}: {str(e)[:160]})")
        return dict(template(facts), source="template", note=f"A fixed template is shown because {why}. The figures are the same.")
