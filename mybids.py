"""What you have tied up in the Card Market, read from the market's own tabs:
  My Listings: "Selling 0/6 - Winning 1", and the winning auctions with your bid on each;
  Requests:    "yours: 0/6" (cards you asked for, with coins held for them).
Coins in bids / requests are lost on a rebirth, so the website shows this next to Rebirth.
"""
import re
import time

import cv2

import mem_gui
import mem_market
import webstate
from market_scan import amount_value, badge_serial, fix_numbers, left_seconds, time_text
from ocr import read_words

_UNITS = (("Q", 1e15), ("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3))


def short(v):
    for unit, size in _UNITS:
        if v >= size:
            return f"{v / size:.1f}".rstrip("0").rstrip(".") + unit
    return str(int(v))


def _num(text):
    """A small count read by OCR ("1" often comes out as l, I or |, "0" as O)."""
    return int(text.translate(str.maketrans("IlLi|OoQ", "11111000")) or 0)


def _open_tab(game, label):
    """Click a market tab by its name (tabs are in the top strip). True if found."""
    img = game.frame()
    h = img.shape[0]
    s = game.ui_scale(img)
    mem = mem_gui.locate(text=label, screen="MarketUI", contains=True)  # (its label starts with an emoji)
    # (the market window is centred, so its rows are placed from the screen's middle, not as a share of its height:
    # the tab row is 294 px above the middle at UI scale 1 whatever the window size, in fullscreen or not)
    spot = mem_gui.either(mem and (mem[0], mem[1]), lambda: next(
        ((x, y) for t, x, y in read_words(img, scale=2) if label.lower() in t.lower() and y < h / 2 - 200 * s), None))
    if not spot:
        return False
    game.click(*spot)
    game.park_mouse()
    game.wait(1.5)
    return True


def _header(words, h, s=1.0):
    """The summary line under the tabs ("Selling 0/6 - Winning 1"): 252 px above the screen's middle (the tab row,
    at 294, is left out: its words would end up in the line)."""
    mid = h / 2 - 252 * s
    return " ".join(t for t, x, y in sorted(words, key=lambda w: w[1]) if abs(y - mid) < 20 * s)


def read_listings(game):
    """(winning count, [bid amounts]) from My Listings, or None if it couldn't be read."""
    if not _open_tab(game, "Listin"):  # (the tab's name is often read as "Listin")
        return None
    # The tab opens with "Winning 0 / You're not selling or winning anything" until the
    # market's data arrives (a second or two), so a zero isn't believed until it has
    # stayed that way for a few seconds
    m = None
    for _ in range(6):
        img = game.frame()
        h = img.shape[0]
        s = game.ui_scale(img)
        words = read_words(img, scale=2)
        m = re.search(r"Winning\W*([\dIlOo|]+)", _header(words, h, s), re.I)  # a lone "1" is often read as "l"
        if m and _num(m.group(1)) > 0:
            break
        game.wait(1.0)
    if not m:
        print(f"My Listings header read as: {_header(words, h, s)!r} (window {img.shape[1]}x{img.shape[0]})", flush=True)
        return None
    winning = _num(m.group(1))
    sell = re.search(r"Selling\W*([\dIlOo|]+)\s*/", _header(words, h, s), re.I)
    items = _tiles(game, img, words)
    amounts = [i["amount"] for i in items if i["kind"] == "bid" and i["status"] == "winning"]
    return winning, amounts, items, (_num(sell.group(1)) if sell else None)


def _tile_center(img, guess, ay, s):
    """The x of a tile's middle, from where its card sits in the picture: the card is a
    bright block on the dark market panel, so find the bright run of columns, in a band
    through the artwork, that contains the guess. (Buttons and amount text shift between
    tiles, so they're a poor guide; the card itself always has the same width.)"""
    y0, y1 = int(ay - 190 * s), int(ay - 120 * s)
    band = cv2.cvtColor(img[max(0, y0):y1, :], cv2.COLOR_BGR2GRAY).astype(float).mean(axis=0)
    bright = band > 60
    x = int(guess)
    if not (0 <= x < len(bright)) or not bright[x]:
        return guess
    l = r = x
    while l > 0 and bright[l - 1]:
        l -= 1
    while r < len(bright) - 1 and bright[r + 1]:
        r += 1
    width = r - l
    # a run about one card wide (182 px at UI scale 1); anything much wider is two tiles
    # touching, much narrower isn't a card: then keep the guess
    if 150 * s <= width <= 215 * s:
        return (l + r) / 2
    return guess


def _tiles(game, img, words):
    """(Read off the screen, when memory can't read the tab.) Every card tile on My Listings: its name, serial, amount, time left and
    whether you're winning it, were outbid, or it's your own listing. A tile is found from
    its amount line (the 🔨 200.0B under the card); the card above it has the same layout
    as in Browse, so the Browse measurements are reused."""
    s = game.ui_scale(img)
    h = img.shape[0]
    found = sorted(((x, y, fix_numbers(t)) for t, x, y in words
                    if y > h / 2 - 150 * s and re.fullmatch(r"[\d.,]+[KMBTQ]", fix_numbers(t))), key=lambda a: (a[1], a[0]))
    # A tile can show two amounts (its bid, and "Buy now 10.0T" a line below): the tile's
    # own is the top one, so a lower amount in about the same column belongs to that tile
    amounts = []
    for a in found:
        if not any(abs(a[0] - b[0]) < 80 * s and 0 < a[1] - b[1] < 60 * s for b in amounts):
            amounts.append(a)
    # The amount found may be the "Buy now 10.0T" line under the bid when the bid's own amount wasn't read (the 🔨 before it
    # confuses the reader): that line is ~20 px below the bid, so move up to the bid's row (the amount is then read
    # from there if possible, else "?")
    fixed = []
    for ax, ay, atext in amounts:
        if any(t.lower().startswith(("buy", "now")) and abs(y - ay) < 9 * s and 0 < ax - x < 150 * s for t, x, y in words):
            ay2 = ay - 20 * s
            own = next((fix_numbers(t) for t, x, y in words if abs(y - ay2) < 10 * s and abs(x - ax) < 70 * s
                        and re.fullmatch(r"[\d.,]+[KMBTQ]", fix_numbers(t))), None)
            if own is None:  # read just that line, right of the hammer icon, bigger
                strip = img[max(0, int(ay2 - 13 * s)):int(ay2 + 13 * s), max(0, int(ax - 40 * s)):int(ax + 75 * s)]
                from ocr import read_text
                m = re.search(r"[\d.,]+\s*[KMBTQ]", fix_numbers(read_text(strip, scale=4))) if strip.size else None
                own = m.group(0).replace(" ", "") if m else None
            fixed.append((ax, ay2, own or "?"))
        else:
            fixed.append((ax, ay, atext))
    amounts = fixed
    amounts.sort(key=lambda a: (round(a[1] / 40), a[0]))
    items = []
    for ax, ay, atext in amounts:
        cx = _tile_center(img, ax + 27 * s, ay, s)  # the amount sits left of the tile's middle (🔨 icon to its left)
        near = [(t, x, y) for t, x, y in words if abs(x - cx) < 100 * s and ay - 20 * s < y < ay + 160 * s]
        raw = " ".join(t for t, x, y in sorted(near, key=lambda w: (round(w[2] / 12), w[1])))
        low = raw.lower()
        status = "winning" if "winning" in low else "outbid" if "outbid" in low else ""
        kind = "bid" if status else "listing"
        top = ay - 268 * s
        bid_y = top + 390 * s  # (Browse measures its cards from the BID button)
        card_left = cx - 95 * s
        serial = None
        try:
            serial = badge_serial(img, card_left, bid_y, s)
        except Exception:
            pass
        name_words = [t for t, x, y in sorted(words, key=lambda w: w[1])
                      if abs(x - cx) < 95 * s and top + 8 * s < y < top + 38 * s]
        name = re.split(r"\s[+*x]\s*\d", " ".join(name_words))[0].strip(" +*") or None
        left = time_text(" ".join(t for t, x, y in near if ay + 20 * s < y < ay + 70 * s))
        secs = left_seconds(left)
        items.append({"kind": kind, "status": status, "name": name, "serial": serial, "amount": atext,
                      "time_left": left, "ends_ts": time.time() + secs if secs is not None else None,
                      "raw": raw[:160]})
    return items


def read_requests(game):
    """How many requests (cards asked for) are yours, from the Requests tab header."""
    if not _open_tab(game, "Requests"):
        return None
    img = game.frame()
    m = re.search(r"yours\W*([\dOIl|]+)\s*/", _header(read_words(img, scale=2), img.shape[0], game.ui_scale(img)), re.I)
    return _num(m.group(1)) if m else None


def _read_memory(game):
    """read_listings() + read_requests() from memory: (winning, amounts, items, selling, requests), or None if
    memory can't read the tabs. The tab shows "Winning 0" until the market's data arrives, so a zero is only
    believed after a couple of seconds."""
    if not _open_tab(game, "Listin"):
        return None
    end = time.time() + 3.0
    while True:
        head = mem_market.header() or ""
        win = re.search(r"Winning\W*(\d+)", head)
        if (win and int(win.group(1)) > 0) or time.time() > end:
            break
        game.wait(0.25)
    items = mem_market.my_listings()
    if not win or items is None:
        return None
    sell = re.search(r"Selling\W*(\d+)\s*/", head)
    for i in items:
        secs = left_seconds(i.get("time_left"))
        i["ends_ts"] = time.time() + secs if secs is not None else None
    amounts = [i["amount"] for i in items if i["kind"] == "bid" and i["status"] == "winning" and i.get("amount")]
    requests = None
    if _open_tab(game, "Requests"):
        end = time.time() + 3.0
        while requests is None and time.time() < end:  # (its own line: the last tab's "Selling" line can linger)
            hit = mem_gui.read(text="yours:", screen="MarketUI", contains=True)
            m = re.search(r"yours\W*(\d+)\s*/", hit[0] if hit else "")
            requests = int(m.group(1)) if m else None
            if requests is None:
                game.wait(0.2)
    return int(win.group(1)), amounts, items, int(sell.group(1)) if sell else None, requests


def read_my_bids(game, log=print):
    """With the market open: read both tabs and publish for the website. Returns the dict
    or None if My Listings couldn't be read."""
    mem = _read_memory(game)
    if mem:
        winning, amounts, items, selling, requests = mem
        return _publish(winning, amounts, items, selling, requests, log)
    listings = read_listings(game)
    if listings is None:
        log("Couldn't read My Listings.")
        return None
    winning, amounts, items, selling = listings
    return _publish(winning, amounts, items, selling, read_requests(game), log)


def _publish(winning, amounts, items, selling, requests, log):
    total = sum(amount_value(a) or 0 for a in amounts)
    info = {"winning": winning, "selling": selling, "amounts": amounts, "total": short(total) if amounts else "0",
            "requests": requests, "items": items, "at": time.strftime("%H:%M"), "ts": time.time()}
    webstate.save("mybids.json", info)
    log(f"My bids: {winning} winning ({', '.join(amounts) or 'no amounts read'}), "
        f"{requests if requests is not None else '?'} request(s)")
    return info
