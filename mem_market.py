"""The Card Market's listings, read from memory instead of OCR.

Every listing in the market's grid is in memory with all its text: the artist (top of the card), the earnings
("+1500/s"), the serial badge ("#1", in a frame named FirstTen), the rarity ("ATLANTIS"), the copy ("#372/969"), the
price ("Start 500.0B", or the current bid after an icon), "Buy now 1.0T" or "Auction only", the time left
("20m 51s left"), the seller ("by ivr"), and its BID / BUY buttons. Each text is told apart by what it looks like, not by
where it sits, so a rearranged card still reads.

listings() gives the listings whose BID button is showing (not scrolled out of the grid), each as the dict
market_scan.read_listing() makes, plus "bid" / "buy" (where to click) and "box" (the card's edges, for its picture).
"""
import re

import card_art
import mem_gui

RARITIES = {"COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "SECRET", "GLITCHED", "KAWAII", "RADIATION",
            "ICED", "MOLTEN", "CHARGED", "TIDAL", "SPOOKY", "ACID", "METEOR", "ECLIPSE", "BLOOD", "ATLANTIS"}
_AMT = r"([\d.,]+\s*[KMBTQ]?)"


def _strip_icon(t):
    """Labels can start with an emoji (the hammer before a bid, the clock before the time): drop it."""
    return re.sub(r"^[^\w#+]+", "", t or "").strip()


def _texts(mb, inst, depth=9):
    """(text, centre x, centre y, parent's name, class) of every showing-or-not text under inst."""
    out = []
    for d, o in mb._walk(inst, depth=depth, max_nodes=400):
        cls = mb._class_name(o)
        if cls not in ("TextLabel", "TextButton"):
            continue
        t = mb._content_text(o)
        if not t:
            continue
        g = mem_gui.gui().geom(o)
        if g:
            out.append((t.strip(), g[0], g[1], mb._name(mb._parent(o)), o))
    return out


def _grid(mb):
    """The market's listing grid: the showing ScrollingFrame in MarketUI with BID buttons in it."""
    gui = mem_gui.gui()
    sg = next((s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI"), None)
    if not sg or not gui.screen_on("MarketUI"):
        return None
    for d, o in mb._walk(sg, depth=6, max_nodes=300):
        if mb._class_name(o) == "ScrollingFrame" and gui.is_shown(o):
            return o
    return None


def parse(texts):
    """A listing's fields from its texts (see the module doc)."""
    card = {"name": None, "serial": None, "rarity": None}
    top = min((t for t in texts if t[0] and not t[0].startswith("+") and not t[0].startswith("#")
               and t[0].upper() not in RARITIES), key=lambda t: t[2], default=None)
    if top:
        card["name"] = top[0]
    for t, x, y, parent, _ in texts:
        s = _strip_icon(t)
        if parent == "FirstTen" and re.fullmatch(r"#\d+", s):
            card["serial"] = s[1:]
        elif s.upper() in RARITIES:
            card["rarity"] = s.upper()
        elif m := re.fullmatch(r"#(\d+)\s*/\s*(\d+)", s):
            card["copy"] = f"{m.group(1)}/{m.group(2)}"
        elif m := re.fullmatch(r"\+" + _AMT + r"\s*/\s*s", s):
            card["income"] = m.group(1)
        elif m := re.fullmatch(r"Start\s+" + _AMT, s, re.I):
            card["start"] = m.group(1).replace(" ", "")
        elif m := re.fullmatch(r"Buy\s*now\s+" + _AMT, s, re.I):
            card["buy_now"] = m.group(1).replace(" ", "")
        elif re.fullmatch(r"Auction only", s, re.I):
            card["auction_only"] = True
        elif m := re.fullmatch(r"((?:\d+h\s*)?(?:\d+m\s*)?(?:\d+s)?)\s*left", s):
            card["time_left"] = m.group(1).strip()
        elif m := re.fullmatch(r"by\s+(.+)", s):
            card["seller"] = m.group(1).strip()
        elif s != t.strip() and re.fullmatch(_AMT, s) and "start" not in card:
            card["current_bid"] = s.replace(" ", "")  # an icon and an amount: the bid on it so far
    card["has_buy"] = "buy_now" in card
    return card


def dialog_words():
    """The bid window's texts as [(text, x, y)] (whole labels, screen pixels), plus ("<textbox>", x, y) for its amount
    box, or None if no such window is showing (or memory can't tell). The window is the frame around its Cancel
    button that also holds its title ("Bid on ...")."""
    gui = mem_gui.gui()
    if gui is None:
        return None
    try:
        mb = gui.mb
        cancel = gui.find(text="Cancel", screen="MarketUI", want_obj=True)
        if not cancel:
            return None
        node = cancel[2]
        for _ in range(5):  # up to the window: the first frame above Cancel that holds more than its button row
            node = mb._parent(node)
            if node is None:
                return None
            texts = [t for t in _texts(mb, node, depth=8) if gui.is_shown(t[4])]
            if any(re.match(r"(Bid on|Buy)\b", t[0], re.I) for t in texts):
                out = [(t[0], t[1], t[2]) for t in texts]
                for d, o in mb._walk(node, depth=8, max_nodes=200):
                    if mb._class_name(o) == "TextBox" and gui._ok(o):
                        g = gui.geom(o)
                        out.append(("<textbox>", g[0], g[1]))
                        out.append(("<typed>" + (mb._content_text(o) or ""), g[0], g[1]))
                return out
        return None
    except Exception:
        return None


def listings():
    """The listings in view (their BID button showing), read from memory; None if memory can't read the market
    (the caller then reads the screen)."""
    gui = mem_gui.gui()
    if gui is None:
        return None
    try:
        mb = gui.mb
        grid = _grid(mb)
        if grid is None:
            return None
        out, seen = [], set()
        for d, entry in mb._walk(grid, depth=3, max_nodes=2000):
            if d == 0 or mb._class_name(entry) != "Frame":
                continue
            texts = _texts(mb, entry)
            bid = next((t for t in texts if t[0].upper() == "BID"), None)
            if bid is None or bid[4] in seen:
                continue  # (a frame inside a listing: the listing itself was taken already)
            seen.add(bid[4])
            if not gui.is_shown(bid[4]):
                continue  # scrolled out of view: read when it's in view (its BID must be clickable)
            card = parse(texts)
            buy = next((t for t in texts if t[0].upper() == "BUY"), None)
            box = gui.geom(next((o for dd, o in mb._walk(entry, depth=2, max_nodes=40) if mb._name(o) == "Card"), entry))
            card["bid"] = (bid[1], bid[2])
            card["buy"] = (buy[1], buy[2]) if buy else None
            card["box"] = (box[0] - box[2] / 2, box[1] - box[3] / 2, box[0] + box[2] / 2, box[1] + box[3] / 2) if box else None
            card["cx"] = box[0] if box else bid[1]
            img = card_art._artwork(mb, entry)  # the card's own picture (the website shows it)
            card["art"] = card_art.image_id(mb, img) if img else None
            card_art.record(card.get("name"), card.get("rarity"), card["art"])
            out.append(card)
        return out
    except Exception:
        return None
