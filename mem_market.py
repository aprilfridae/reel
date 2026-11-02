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
               and t[0].upper() not in RARITIES and not set(t[0]) <= set("★☆ ")
               and not re.match(r"(Underground RNG|Earns)\b|GRADE$|\d{1,2}$", t[0], re.I)),  # (footer lines, the grade)
              key=lambda t: t[2], default=None)
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
    # a graded card has a "GRADE" label over its grade ("10") at the art's top right: the closest number under it
    label = next((t for t in texts if t[0].strip().upper() == "GRADE"), None)
    if label:
        nums = [t for t in texts if re.fullmatch(r"\d{1,2}", t[0].strip()) and abs(t[1] - label[1]) < 40 and 0 < t[2] - label[2] < 40]
        if nums:
            card["grade"] = min(nums, key=lambda t: t[2] - label[2])[0].strip()
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


def _entries(mb, grid, is_entry, memo=None):
    """[(entry frame, its texts)] of the grid's tiles: the first frames down from the grid whose texts pass
    is_entry (a tile isn't looked inside again). memo: {frame: texts} kept by the caller between reads, so the
    tiles already read aren't read again (their positions in it are then out of date)."""
    out, stack = [], [(1, c) for c in mb._children(grid)]
    while stack:
        d, node = stack.pop()
        if memo is not None and node in memo:
            out.append((node, memo[node]))
            continue
        if mb._class_name(node) != "Frame":
            continue
        texts = _texts(mb, node)
        if memo is not None and is_entry(texts):
            memo[node] = texts
        if is_entry(texts):
            out.append((node, texts))
        elif d < 3 and texts:
            stack.extend((d + 1, c) for c in mb._children(node))
    return out


def _card_of(mb, gui, entry, texts):
    """A tile's card fields (parse()), plus its picture id ("art") and "box" (the card's edges on screen)."""
    card = parse(texts)
    box = gui.geom(next((o for dd, o in mb._walk(entry, depth=2, max_nodes=40) if mb._name(o) == "Card"), entry))
    card["box"] = (box[0] - box[2] / 2, box[1] - box[3] / 2, box[0] + box[2] / 2, box[1] + box[3] / 2) if box else None
    card["cx"] = box[0] if box else None
    img = card_art._artwork(mb, entry)  # the card's own picture (the website shows it)
    card["art"] = card_art.image_id(mb, img) if img else None
    card_art.record(card.get("name"), card.get("rarity"), card["art"])
    return card


def listings(shown_only=True, memo=None):
    """The Browse grid's listings, read from memory: those whose BID button is showing, or (shown_only=False) every
    listing loaded so far, scrolled into view or not, top to bottom. Each also has "_bid": its BID label in memory
    (where_is() says where it is now). memo: see _entries (then "bid" / "buy" / "box" may be out of date: use
    where_is). None if memory can't read the market (the caller then reads the screen)."""
    gui = mem_gui.gui()
    if gui is None:
        return None
    try:
        mb = gui.mb
        grid = _grid(mb)
        if grid is None:
            return None
        out = []
        for entry, texts in _entries(mb, grid, lambda ts: any(t[0].upper() == "BID" for t in ts), memo):
            bid = next(t for t in texts if t[0].upper() == "BID")
            if shown_only and not gui.is_shown(bid[4]):
                continue  # scrolled out of view: read when it's in view (its BID must be clickable)
            if memo is not None and ("card", entry) in memo:
                out.append(dict(memo[("card", entry)]))
                continue
            card = _card_of(mb, gui, entry, texts)
            buy = next((t for t in texts if t[0].upper() == "BUY"), None)
            card["bid"] = (bid[1], bid[2])
            card["buy"] = (buy[1], buy[2]) if buy else None
            card["cx"] = card["cx"] or bid[1]
            card["_bid"] = bid[4]
            if memo is not None:
                memo[("card", entry)] = dict(card)
            out.append(card)
        if memo is not None:  # (the positions read before a scroll are out of date: where the buttons are now)
            for c in out:
                g = gui.geom(c["_bid"])
                if g:
                    c["bid"] = (g[0], g[1])
        out.sort(key=lambda c: (round(c["bid"][1] / 20), c["bid"][0]))
        return out
    except Exception:
        return None


def where_is(obj):
    """(x, y, shown?) of an object now (a BID label after scrolling), or None."""
    gui = mem_gui.gui()
    try:
        g = gui.geom(obj)
        return (g[0], g[1], gui.is_shown(obj)) if g else None
    except Exception:
        return None


def grid_box():
    """(top, bottom) of the showing grid on screen, or None."""
    gui = mem_gui.gui()
    try:
        g = gui.geom(_grid(gui.mb))
        return (g[1] - g[3] / 2, g[1] + g[3] / 2) if g else None
    except Exception:
        return None


def header():
    """The summary line under the market's tabs ("Selling 0/6 · Winning 1 · ...", "116 requests ... yours: 0/6 ..."),
    or None."""
    hit = mem_gui.read(text="Selling", screen="MarketUI", contains=True) or \
        mem_gui.read(text="yours:", screen="MarketUI", contains=True)
    return hit[0] if hit else None


def my_listings():
    """The My Listings tiles in memory: [{kind, status, name, serial, rarity, grade, art, amount, time_left}], kind
    "bid" (an auction you bid on: status winning / outbid) or "listing" (your own). None if memory can't read it."""
    gui = mem_gui.gui()
    if gui is None:
        return None
    try:
        mb = gui.mb
        grid = _grid(mb)
        if grid is None:
            return None
        items = []
        for entry, texts in _entries(mb, grid, lambda ts: any(re.search(r"\bleft$", t[0]) for t in ts)
                                     and any(t[3] == "FirstTen" for t in ts)):
            card = _card_of(mb, gui, entry, texts)
            low = " ".join(t[0] for t in texts).lower()
            status = "winning" if "winning" in low else "outbid" if "outbid" in low else ""
            amount = card.get("current_bid") or card.get("start") or card.get("buy_now")
            items.append({"kind": "bid" if status else "listing", "status": status, "name": card.get("name"),
                          "serial": card.get("serial"), "rarity": card.get("rarity"), "grade": card.get("grade"),
                          "art": card.get("art"), "income": card.get("income"), "copy": card.get("copy"),
                          "amount": amount, "time_left": card.get("time_left"), "y": card["box"][1] if card["box"] else 0,
                          "x": card["cx"] or 0})
        items.sort(key=lambda i: (round(i.pop("y") / 20), i.pop("x")))
        return items
    except Exception:
        return None
