"""What you have tied up in the Card Market, read from the market's own tabs:
  My Listings: "Selling 0/6 - Winning 1", and the winning auctions with your bid on each;
  Requests:    "yours: 0/6" (cards you asked for, with coins held for them).
Coins in bids / requests are lost on a rebirth, so the website shows this next to Rebirth.
"""
import os
import re
import time

import cv2

import webstate
from game import HERE
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
    # (the market window is centred, so its rows are placed from the screen's middle, not as a share of its height:
    # the tab row is 294 px above the middle at UI scale 1 whatever the window size, in fullscreen or not)
    spot = next(((x, y) for t, x, y in read_words(img, scale=2) if label.lower() in t.lower() and y < h / 2 - 200 * s), None)
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
        try:  # what was on screen, so a failure can be looked at
            cv2.imwrite(os.path.join(HERE, "mybids_fail.png"), img)
            print(f"My Listings header read as: {_header(words, h, s)!r} (window {img.shape[1]}x{img.shape[0]})", flush=True)
        except Exception:
            pass
        return None
    winning = _num(m.group(1))
    sell = re.search(r"Selling\W*([\dIlOo|]+)\s*/", _header(words, h, s), re.I)
    items = _tiles(game, img, words)
    amounts = [i["amount"] for i in items if i["kind"] == "bid" and i["status"] == "winning"]
    return winning, amounts, items, (_num(sell.group(1)) if sell else None)


MINE_DIR = os.path.join(HERE, "web", "static", "mine")


def _card_span(img, guess, ay, s):
    """(left, right) of the card around `guess`, the same way _tile_center finds it, or None."""
    y0, y1 = int(ay - 190 * s), int(ay - 120 * s)
    band = cv2.cvtColor(img[max(0, y0):y1, :], cv2.COLOR_BGR2GRAY).astype(float).mean(axis=0)
    bright = band > 60
    x = int(guess)
    if not (0 <= x < len(bright)) or not bright[x]:
        return None
    l = r = x
    while l > 0 and bright[l - 1]:
        l -= 1
    while r < len(bright) - 1 and bright[r + 1]:
        r += 1
    return (l, r) if 150 * s <= r - l <= 215 * s else None


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
    """Every card tile on My Listings: its picture, name, serial, amount, time left and
    whether you're winning it, were outbid, or it's your own listing. A tile is found from
    its amount line (the 🔨 200.0B under the card); the card above it has the same layout
    as in Browse, so the Browse measurements are reused."""
    s = game.ui_scale(img)
    h = img.shape[0]
    os.makedirs(MINE_DIR, exist_ok=True)
    for f in os.listdir(MINE_DIR):
        os.remove(os.path.join(MINE_DIR, f))
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
    # from there if possible, else "?": the website shows the picture to read it from)
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
        fname = f"m_{len(items):02d}.jpg"
        # the whole tile from the card's top to its "You're winning!" line (card, amount, time left), twice the size,
        # so the website can show it enlarged when the reading of it was wrong
        # cut to the card's own edges when they can be found, so every picture is the same size with the card filling
        # it (a fixed width around a guessed centre left some cards small, with slices of the neighbours beside them)
        span = _card_span(img, ax + 27 * s, ay, s)
        x0, x1 = (span[0] - 14 * s, span[1] + 14 * s) if span else (cx - 99 * s, cx + 99 * s)  # (a dark card edge reads as background)
        crop = img[max(0, int(top - 6 * s)):min(h, int(ay + 100 * s)), max(0, int(x0)):int(x1)]
        if crop.size:
            cv2.imwrite(os.path.join(MINE_DIR, fname),
                        cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), [cv2.IMWRITE_JPEG_QUALITY, 90])
        items.append({"kind": kind, "status": status, "name": name, "serial": serial, "amount": atext,
                      "time_left": left, "ends_ts": time.time() + secs if secs is not None else None,
                      "image": fname if crop.size else None, "raw": raw[:160]})
    return items


def read_requests(game):
    """How many requests (cards asked for) are yours, from the Requests tab header."""
    if not _open_tab(game, "Requests"):
        return None
    img = game.frame()
    m = re.search(r"yours\W*([\dOIl|]+)\s*/", _header(read_words(img, scale=2), img.shape[0], game.ui_scale(img)), re.I)
    return _num(m.group(1)) if m else None


def read_my_bids(game, log=print):
    """With the market open: read both tabs and publish for the website. Returns the dict
    or None if My Listings couldn't be read."""
    listings = read_listings(game)
    if listings is None:
        log("Couldn't read My Listings.")
        return None
    winning, amounts, items, selling = listings
    requests = read_requests(game)
    total = sum(amount_value(a) or 0 for a in amounts)
    info = {"winning": winning, "selling": selling, "amounts": amounts, "total": short(total) if amounts else "0",
            "requests": requests, "items": items, "at": time.strftime("%H:%M"), "ts": time.time()}
    webstate.save("mybids.json", info)
    log(f"My bids: {winning} winning ({', '.join(amounts) or 'no amounts read'}), "
        f"{requests if requests is not None else '?'} request(s)")
    return info
