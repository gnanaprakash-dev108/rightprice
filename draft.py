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

What you are given is a JSON object: who is writing, the mill, what the buyer wants from this message, and for each fabric its code, quantity, the mill's price, sometimes the price to name to the mill ("target"; it is the buyer's own counter when "our_counter" is given), and the points to raise. The points were worked out by the buyer's own costing; treat them as what the buyer wants to say, and say them in your own words.

Rules that matter more than style:
- Use only the figures given. Do not add, round, average or infer any figure, date, name or fact. If a name is missing, write the bracketed placeholder exactly as given.
- Write rupees as "Rs 185.00" and metres with Indian grouping as given.
- Say "our costing" or "our working" for the buyer's figures. Never mention software, a tool, a model, AI, "should-cost" or "usual range"; a price the buyer's costing supports is simply "what our costing supports".
- Some points are the buyer's private guidance to themselves ("hold our counter", "do not go above Rs ...", "ask only for ..."). Act on them in what you ask for, but never reveal a ceiling, a fallback or the highest price the buyer would accept. The price to name to the mill is the buyer's counter if one is given, otherwise the price our costing supports.
- A fabric marked already_bought was bought at that price: ask about it for the next order of the same cloth, not as a claim on the past order.
- Ask for exactly what the buyer wants (the break-up, a revised price, or both) and for a reply by a reasonable time without naming a date.
- For several fabrics, deal with each in a line or two, largest sums first, as given. Do not build a table.
- Do not promise an order, a quantity or anything else the figures do not say.

Reply in exactly this layout and nothing else:
SUBJECT: <one line>
EMAIL:
<the e-mail, at most about 170 words for one fabric and 280 for several, ending with the writer's name>
WHATSAPP:
<the same ask as one message a person would type on a phone, at most about 60 words, no greeting line of its own beyond the name>"""

OPENERS = ["Open straight with the fabric and the ask.", "Open with one line placing the quote (which fabric, which sheet or call), then the ask.",
           "Open by saying you have gone through the price and have a point to raise.", "Open with the figure that needs explaining."]


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _money(v):
    return None if v is None else round(float(v), 2)


def template(facts):
    """The plain draft used when there is no API key, or the API could not be reached. Same figures, fixed wording."""
    who, to = facts["writer"], facts["contact"]
    items = facts["items"]
    codes = ", ".join(i["code"] for i in items[:4]) + (f" and {len(items) - 4} more" if len(items) > 4 else "")
    ask = ASKS[facts["ask"]]
    lines = [f"Dear {to},", "", f"We have gone through your price for {codes} and need {ask} before we can take it further.", ""]
    notes = []
    for i in items:
        head = f"{i['code']}" + (f" ({i['quantity']} m)" if i.get("quantity") else "") + (
            f": {'we bought this at' if i.get('already_bought') else 'your price is'} Rs {i['price']:,.2f} a metre" if i.get("price") else "") + (
            (f"; our counter is Rs {i['target']:,.2f}." if i.get("our_counter") is not None else f"; our costing supports Rs {i['target']:,.2f}.") if i.get("target") else "." if i.get("price") else ":")
        lines.append(head)
        notes += [f"  - {p}" for p in i["points"]]
    lines += ["", "Please send this at the earliest so we can close the price.", "", "Regards,", who, "",
              "-- YOUR NOTES, NOT FOR THE MILL (delete before sending): the points to work into the message --"] + notes
    first = items[0]
    wa = (f"{to}, on {codes}: we need {ask} before we can go ahead."
          + (f" Your Rs {first['price']:,.2f} for {first['code']} is above what our costing supports" + (f" (our counter is Rs {first['target']:,.2f})" if first.get("our_counter") is not None else f" (Rs {first['target']:,.2f})" if first.get("target") else "") + "." if first.get("price") and first.get("high") else "")
          + f" Please send it today if you can. {who}")
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
        return dict(template(facts), source="template", note="Written from a fixed template: this server has no Claude API key "
                    "(the app setting ANTHROPIC_API_KEY). The figures are the same; the wording does not change between drafts.")
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
