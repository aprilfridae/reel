"""Reading the Card Market (already open): every listing with a serial badge
(#1-#10), its price, Buy Now price, time left, seller and top bidder.

Layout (UI scale 1): six cards per row, ~190px apart, centered in the window.
Each card's BID button sits under it; a BUY button sits next to BID when the
listing has Buy Now. The serial badge is the small box at the art's top-left:
rainbow = #1, gold = #2, bronze = #3; other badges = #4-#10; no badge = #11+.
(The badge text itself is too small to read reliably.)
"""
import glob
import os
import re
import time
from difflib import SequenceMatcher

import cv2
import numpy as np

from game import HERE, TEMPLATES
from ocr import read_text, read_words

CARDS_DIR = os.path.join(HERE, "web", "static", "cards")  # card pictures for the website
COLUMN_PITCH = 190
CARD_W = 190
# Offsets from a card's BID button center (at UI scale 1)
CARD_TOP = -390  # top of the card (its name line) above the BID button
BADGE = (-357, -332, 30, 63)  # badge box: y0, y1 relative to BID; x0, x1 relative to card left
TEXT_TOP = -140  # the price / time / seller lines
CARD_BOTTOM_TOP = (-393, -146)  # the card itself (no price box), relative to BID
CARD_HALF_W = 91


def _columns(w, s):
    return [w / 2 + (k - 2.5) * COLUMN_PITCH * s for k in range(6)]


def bid_buttons(game, img):
    """Centers of the BID buttons on screen (white 'BID' text on blue)."""
    s = game.ui_scale(img)
    hits = game.find_all("market_bid", img, 0.8, white_text=True)
    cols = _columns(img.shape[1], s)
    out = []
    for x, y, _ in hits:
        cx = min(cols, key=lambda c: abs(c - x))
        out.append((x, y, cx))
    return sorted(out, key=lambda b: (b[1], b[0]))


def badge_serial(img, card_left, bid_y, s):
    """'1', '2', '3', '4-10' from the badge, or None if the card has no badge."""
    y0, y1 = int(bid_y + BADGE[0] * s), int(bid_y + BADGE[1] * s)
    x0, x1 = int(card_left + BADGE[2] * s), int(card_left + BADGE[3] * s)
    if y0 < 0:
        return None
    b = img[y0:y1, x0:x1]
    if b.size == 0:
        return None
    # just the inside of the badge, where the digit is (same window the digit
    # templates were cut from)
    inner = img[int(bid_y - 355 * s):int(bid_y - 336 * s), int(card_left + 32 * s):int(card_left + 60 * s)]
    dark = (b.max(axis=2) < 90).sum()
    hsv = cv2.cvtColor(b, cv2.COLOR_BGR2HSV)
    color = hsv[(hsv[..., 1] > 110) & (hsv[..., 2] > 140)]
    if not (8 * s * s < dark < 200 * s * s) or len(color) < 0.25 * b.shape[0] * b.shape[1]:
        return None
    hues = np.histogram(color[:, 0], bins=6, range=(0, 180))[0]
    if (hues > 0.1 * len(color)).sum() >= 3:
        return "1"  # rainbow
    # #2 and up share a gold badge: tell them apart by the digit's shape
    return _match_digit(inner, s) or "2-10"


_GLYPHS = {}


def _glyph(badge):
    """The badge's dark lettering, cropped tight, small specks removed."""
    m = (badge.max(axis=2) < 90).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 6:
            keep[lab == i] = 255
    ys, xs = np.where(keep > 0)
    if not len(ys):
        return None
    return keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _match_digit(badge, s):
    """Compare the badge's digit with known ones (templates/serial_<n>.png).
    Unknown ones are saved to serial_glyphs/ so their number can be added later."""
    if not _GLYPHS:
        for f in glob.glob(os.path.join(TEMPLATES, "serial_*.png")):
            n = os.path.basename(f)[7:-4]
            _GLYPHS[n] = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
    g = _glyph(badge)
    if g is None:
        return None
    best, best_score, second = None, 0.0, 0.0
    for n, t in _GLYPHS.items():
        if n == "1":
            continue  # #1 is recognized by its rainbow badge
        tt = cv2.resize(t, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
        score = (np.logical_and(tt > 0, g > 0).sum() / max(1, np.logical_or(tt > 0, g > 0).sum()))
        if score > best_score:
            best, best_score, second = n, score, best_score
        elif score > second:
            second = score
    # The badge font is a fixed pixel font, so a real #2 / #3 matches its template at
    # about 0.87 (and the other digit at 0.65-0.7). A #5 or #8 only resembles a 2 or 3
    # roughly (0.6-0.75): it has to be a clear match, clearly ahead of the other digit
    if best_score >= 0.78 and best_score - second >= 0.1:
        return best
    os.makedirs(os.path.join(HERE, "serial_glyphs"), exist_ok=True)
    cv2.imwrite(os.path.join(HERE, "serial_glyphs", f"{int(time.time() * 1000)}.png"), g)
    return None


def time_text(text):
    """'e 1h 13m left' / 'lh 03m lef' -> '1h 13m' (hours, minutes, seconds as shown),
    or None if the text has no time in it."""
    # the clock icon before the time is read as I or |: 'Ilh 01m' is '⏱ 1h 01m' (left alone, the hours were lost)
    text = re.sub(r"(?<![A-Za-z0-9])[I|]([Il|\d]{1,2})(?=\s*h\b)", r"\1", text or "")
    text = fix_numbers(text)
    text = re.sub(r"(?<![A-Za-z0-9])[Il|]{1,2}(?=\s*h\b)", lambda m: "1" * len(m.group(0)), text)  # 'lh' is '1h'
    parts = re.findall(r"(\d+)\s*([hms])\b", text)
    if not parts:
        return None
    units = [u for _, u in parts]
    if len(set(units)) != len(units):  # the same unit twice: not a time
        return None
    return " ".join(f"{n}{u}" for n, u in parts)


def left_seconds(text):
    """'2h 31m' / '58m 29s' / '16s' -> seconds, or None."""
    if not text:
        return None
    total, found = 0, False
    for n, unit in re.findall(r"(\d+)\s*([hms])", text):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
        found = True
    return total if found else None


def fix_numbers(text):
    """OCR often reads 0 as O and 1 as I/l in amounts ('1.OT', 'I.0T'); fix those."""
    text = re.sub(r"(?<![A-Za-z])[Il|](?=h\b)", "1", text)  # 'lh 03m' -> '1h 03m'
    # Whole amount-shaped tokens like 'I.IT', 'l.OT', '6OO.OB': digits/look-alikes,
    # at least one dot or digit, then a K/M/B/T/Q suffix
    def amount_token(m):
        body = m.group(1).translate(str.maketrans("IlO|o", "11010"))
        return body + m.group(2)
    text = re.sub(r"(?<![A-Za-z])([\dIlO|o]*[.,\d][\dIlO|o.,]*)([KMBTQ])\b", amount_token, text)
    for _ in range(3):
        text = re.sub(r"(?<=[\d.,])[Oo]|[Oo](?=[\d.,])", "0", text)
    text = re.sub(r"(?<![A-Za-z])[Il|](?=[.,]?\d)", "1", text)
    return text


def _parse(text):
    """Pull the fields out of a card's OCR text."""
    text = fix_numbers(text)
    out = {}
    m = re.search(r"Start\s+([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if m:
        out["start"] = m.group(1).replace(" ", "")
    m = re.search(r"Buy\s*now\s+([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if m:
        out["buy_now"] = m.group(1).replace(" ", "")
    text = re.sub(r"(\d)\s*[.,]\s*[Oo]\s*([KMBTQ])", r"\1.0\2", text)  # OCR reads 0 as O
    if "start" not in out:
        m = re.search(r"([\d.,]+\s*[KMBTQ])\b", text)
        if m:
            out["current_bid"] = m.group(1).replace(" ", "")
    m = re.search(r"((?:\d+h\s*)?(?:\d+m\s*)?\d+[ms])\s*left", text)
    if m:
        out["time_left"] = m.group(1)
    m = re.search(r"\bby\s+(\S+)", text)
    if m:
        out["seller"] = m.group(1)
    return out


def read_listing(game, img, bid):
    x, y, cx = bid
    s = game.ui_scale(img)
    left = int(cx - CARD_W / 2 * s)
    serial = badge_serial(img, left, y, s)
    top = int(y + CARD_TOP * s)
    # the name, left of the "+1500/s" earnings at the card's top-right
    name_line = img[max(0, top):top + int(30 * s), left:left + int(CARD_W * 0.78 * s)]
    name = read_text(name_line, scale=3).strip()
    # strip the earnings ("+1500/s") that sits right of the name
    name = re.sub(r"(\s+[+•*·]\S*|\s+\S{1,2})+$", "", name).strip()
    info = img[int(y + TEXT_TOP * s):int(y - 18 * s), left:left + int(CARD_W * s)]
    text = read_text(info, scale=3)
    # The price line on its own: short prices next to the hammer icon get skipped
    # when the whole block is read at once
    price_line = img[int(y + (TEXT_TOP - 4) * s):int(y + (TEXT_TOP + 22) * s), left:left + int(CARD_W * s)]
    text = read_text(price_line, scale=4) + " " + text
    card = {"name": name, "serial": serial, **_parse(text), "raw": text}
    # The "58m 29s left" line is read on its own: it sits at the same height whether or
    # not the listing has a Buy Now line, and reading it as part of the block sometimes
    # dropped it (or its hours)
    time_row = img[int(y - 101 * s):int(y - 77 * s), left:left + int(CARD_W * s)]
    readings = [time_text(read_text(time_row, scale=sc)) for sc in (4, 3, 5)] + [time_text(text)]
    left_text = max((r for r in readings if r), key=lambda r: len(r.split()), default=None)
    if left_text:
        card["time_left"] = left_text
    else:
        card.pop("time_left", None)
    card["has_buy"] = bool(re.search(r"Buy\s*now", text, re.I))
    return card


def _dialog_text(game):
    img = game.frame()
    h, w = img.shape[:2]
    words = read_words(img[int(h * 0.3):int(h * 0.75), int(w * 0.25):int(w * 0.75)], scale=2)
    return words, fix_numbers(" ".join(t for t, _, _ in words)), (w, h)


def top_bidder(game, bid):
    """Open the BID window for this listing, read 'Top bid: X by Y', and Cancel.
    Never places a bid. The window is waited for only as long as it takes to show (and to
    close), instead of fixed pauses."""
    game.click(bid[0], bid[1])
    game.park_mouse()
    words = text = size = None
    end = time.time() + 2.0
    game.wait(0.2)
    while time.time() < end:
        words, text, size = _dialog_text(game)
        if re.search(r"Top\s*bid|Starting\s*bid", text, re.I):
            break
        game.wait(0.05)
    w, h = size
    result = {}
    m = re.search(r"Top\s*bid:?\s*([\d.,]+\s*[KMBTQ]?)\s*by\s+(\S+)", text, re.I)
    if m:
        result = {"top_bid": m.group(1).replace(" ", ""), "top_bidder": m.group(2)}
    elif re.search(r"Starting\s*bid", text, re.I):
        result = {"top_bidder": None}
    # The bid window's text is bigger and cleaner than the listing's, so prefer it
    m = re.search(r"Starting\s*bid:?\s*([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if m:
        result["start"] = m.group(1).replace(" ", "")
    m = re.search(r"need\s+at\s+least\s+([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if m:
        result["min_next_bid"] = m.group(1).replace(" ", "")
    cancel = [(x, y) for t, x, y in words if t.lower().startswith("cancel")]
    if cancel:
        game.click(int(w * 0.25) + cancel[0][0], int(h * 0.3) + cancel[0][1])
    game.park_mouse()
    end = time.time() + 1.2
    while time.time() < end:  # until the window is gone
        game.wait(0.05)
        _, text2, _ = _dialog_text(game)
        if not re.search(r"Top\s*bid|Starting\s*bid|need\s+at\s+least", text2, re.I):
            break
    return result


def _fix_price(price):
    """A price read without its unit: the "T" of "1.5T" is often read as a 7 ("1.57"), and
    no price here is a bare number with one decimal ending in 7. Returns (price, trusted)."""
    if price is None:
        return None, True
    if re.search(r"[KMBTQ]$", price):
        return price, True
    m = re.fullmatch(r"(\d+\.\d)7", price)
    if m:
        return m.group(1) + "T", True
    return price, False  # no unit and no known misreading: the bid window has to say


def wait_for_listings(game, timeout=10):
    """The market shows "Nothing for sale yet" for a moment while it loads."""
    end = time.time() + timeout
    while time.time() < end:
        if bid_buttons(game, game.frame()):
            return True
        game.wait(0.5)
    return False


def set_sort_lowest_serial(game):
    """Open the Sort dropdown and pick 'Lowest serial' (checked by reading it back)."""
    # "Lowest" is read as Louest, Leuest...; "serial" is the only option with that word, so the option is found by it
    serial = re.compile(r"^seri[a-z]{0,2}$", re.I)
    wait_for_listings(game)
    for _ in range(3):
        words = read_words(game.frame(), scale=2)
        sort = [(i, x, y) for i, (t, x, y) in enumerate(words) if t.startswith("Sort")]
        if not sort:
            return False
        i, sx, sy = sort[0]
        # The label right after "Sort:" on the same line
        after = [t for t, x, y in words[i + 1:i + 3] if abs(y - sy) < 12]
        if after and serial.match(after[-1]):
            return True
        game.click(sx, sy)
        game.wait(0.8)
        words = read_words(game.frame(), scale=3)
        opt = [(x - 25, y) for t, x, y in words if serial.match(t) and y > sy + 20 and abs(x - sx) < 250]
        if opt:
            game.click(*opt[0])
        else:
            game.click(sx, sy)  # option not read: close the dropdown and look again
        game.park_mouse()
        game.wait(1.5)
    return False


SUFFIX = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "Q": 1e15}


def amount_value(text):
    """'650B' / '630.0B' / '1.2T' -> a number, or None."""
    m = re.fullmatch(r"\s*([\d.,]+)\s*([KMBTQ]?)\w*\s*", str(text).upper().replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1)) * SUFFIX[m.group(2)]
    except ValueError:
        return None


def _similar(a, b):
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _price(card):
    return card.get("start") or card.get("current_bid") or card.get("buy_now")


def _is_wanted(card, want):
    """Is this the listing the website asked about? Names and sellers come from OCR
    and can be garbled, so: same serial, and a good name match, or a fair name match
    with the same price, or the same price with a similar seller."""
    if want.get("serial") and card.get("serial") != want["serial"]:
        return False
    name = _similar(card.get("name"), want.get("name"))
    same_price = bool(want.get("price")) and amount_value(_price(card) or "") == amount_value(want["price"])
    seller = _similar(card.get("seller"), want.get("seller")) if want.get("seller") else 0
    # (a fancy-font name is often read differently each time, but the seller usually isn't)
    # (the same seller often lists several cards at the same price, so a seller and price
    # match alone isn't enough: the name has to be at least a little alike too)
    return name >= 0.8 or (name >= 0.5 and (same_price or seller >= 0.85))


def find_listing(game, want, tries=3):
    """find_once, tried again (re-sorting and scrolling back to the top each time) before
    giving up: one look can miss a listing (the list was still loading, a misread card
    badge ended the search early) and a bid that fails for that is useless."""
    for attempt in range(tries):
        bid, card = _find_once(game, want, strict=attempt > 0)
        if bid:
            return bid, card
        game.wait(1.5)
    return None, None


def _find_once(game, want, strict=False, max_pages=60):
    """Go through the (lowest-serial sorted) market, pressing "Show more" as needed,
    for the listing the website asked about. Returns (bid_button, card) or (None, None).
    strict: don't stop early on cards that read as past #3 (go through all the pages)."""
    set_sort_lowest_serial(game)
    img = game.frame()
    h, w = img.shape[:2]
    mid = (w / 2, h * 0.55)
    game.scroll(*mid, 30)
    game.wait(0.6)
    want = dict(want)
    want.setdefault("price", _price(want))
    stale = past = 0
    for _ in range(max_pages):
        img = game.frame()
        s = game.ui_scale(img)
        new = False
        for bid in bid_buttons(game, img):
            if bid[1] + CARD_TOP * s < h * GRID_TOP:
                continue
            card = read_listing(game, img, bid)
            if _is_wanted(card, want):
                return bid, card
            new = True
            past = past + 1 if card["serial"] not in WANTED_SERIALS else 0
        if past >= STOP_AFTER * (3 if strict else 2):
            break  # well past #3: it's not on the market anymore
        more = _show_more(img)
        if more:
            game.click(*more)
            game.park_mouse()
            game.wait(1.5)
            continue
        stale = 0 if new else stale + 1
        if stale >= 4:
            break
        game.scroll(*mid, -2)
        game.wait(0.8)
    return None, None


def _dialog_words(game):
    img = game.frame()
    h, w = img.shape[:2]
    x0, y0 = int(w * 0.2), int(h * 0.25)
    return [(t, x0 + x, y0 + y) for t, x, y in read_words(img[y0:int(h * 0.8), x0:int(w * 0.8)], scale=2)]


def _cancel_dialog(game):
    words = _dialog_words(game)
    cancel = [(x, y) for t, x, y in words if t.lower().startswith("cancel")]
    if cancel:
        game.click(*cancel[0])
    game.park_mouse()
    game.wait(0.6)


def place_bid(game, want, amount, dry_run=False):
    """Bid `amount` (e.g. '650B') on the listing. Returns (ok, message).
    The amount is typed by the program (not read back with OCR); the minimum the game
    shows is checked first, and afterwards that the dialog closed."""
    from ui_keys import clear_field, type_text  # small keyboard helpers
    target = amount_value(amount)
    if not target:
        return False, f"couldn't understand the amount {amount!r}"
    bid, card = find_listing(game, want)
    if not bid:
        return False, "listing not found (sold, ended, or no longer in the top 10)"
    game.click(bid[0], bid[1])
    game.park_mouse()
    game.wait(1.0)
    words = _dialog_words(game)
    text = fix_numbers(" ".join(t for t, _, _ in words))
    if not re.search(r"Bid\s+on", text, re.I):
        _cancel_dialog(game)
        return False, "the bid window didn't open"
    need = re.search(r"need\s+at\s+least\s+([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if not need or not amount_value(need.group(1)):
        _cancel_dialog(game)
        return False, "couldn't read the minimum bid; didn't bid"
    if target < amount_value(need.group(1)):
        _cancel_dialog(game)
        return False, f"too low: you need at least {need.group(1).replace(' ', '')}"
    mins = [(x, y) for t, x, y in words if t.lower() == "min"]
    if not mins:
        _cancel_dialog(game)
        return False, "couldn't find the amount box"
    s = game.ui_scale(game.frame())
    box = (mins[0][0] + 113 * s, mins[0][1] - 48 * s)  # the amount box sits above Min / +25% / x2
    game.click(*box)
    game.wait(0.2)
    clear_field()
    type_text(amount)
    game.wait(0.4)
    # The text is typed by the program, so it isn't read back with OCR (which can't read a
    # short number like "5T" anyway). All that's checked is that something did get typed:
    # the box has white text in it (it's dark and empty otherwise).
    bx, by = int(box[0]), int(box[1])
    for attempt in range(3):
        img = game.frame()
        region = img[by - int(14 * s):by + int(14 * s), bx - int(160 * s):bx + int(160 * s)]
        if (region.min(axis=2) > 200).sum() >= 6 * s * s:
            break
        game.click(*box)  # nothing in the box: the click or the typing missed; do it again
        game.wait(0.3)
        clear_field()
        type_text(amount)
        game.wait(0.4)
    else:
        cv2.imwrite(os.path.join(HERE, "bid_readback_fail.png"), img)
        _cancel_dialog(game)
        return False, "typed the amount but the box stayed empty; didn't bid"
    if dry_run:
        _cancel_dialog(game)
        return True, f"dry run: would bid {amount} on {card['name']}"
    words = _dialog_words(game)
    place = [(x, y) for t, x, y in words if t.upper().startswith("PLACE")]
    if not place:
        _cancel_dialog(game)
        return False, "couldn't find PLACE BID"
    game.click(*place[0])
    game.park_mouse()
    game.wait(1.5)
    after = " ".join(t for t, _, _ in _dialog_words(game))
    if re.search(r"Bid\s+on", after, re.I):  # dialog still up: something was wrong
        msg = after[:120]
        _cancel_dialog(game)
        return False, f"the game didn't take the bid: {msg}"
    return True, f"bid {amount} on {card['name']}"


def buy_now(game, want, price, dry_run=False):
    """Buy the listing at its Buy Now price. Only confirms if the price shown in
    game matches `price` (what the website showed). Returns (ok, message)."""
    target = amount_value(price)
    bid, card = find_listing(game, want)
    if not bid:
        return False, "listing not found (sold or ended)"
    if not card.get("buy_now"):
        return False, "that listing has no Buy Now (anymore)"
    if amount_value(card["buy_now"]) != target:
        return False, f"Buy Now price is now {card['buy_now']}, not {price}; didn't buy"
    s = game.ui_scale(game.frame())
    game.click(bid[0] + 85 * s, bid[1])  # BUY sits right of BID
    game.park_mouse()
    game.wait(1.0)
    # The confirmation window: "Buy <name>?  Price: 1.0T coins  Sold by X" with
    # [Cancel] and a green [BUY 1.0T] button at the bottom
    words = _dialog_words(game)
    title = _buy_title(words)
    cancel = [(x, y) for t, x, y in words if t.lower().startswith("cancel")]
    if not title or not cancel:
        _cancel_dialog(game)
        return False, "the buy window didn't open as expected"
    title = [title]
    shown = _buy_window_price(game, title[0], s)
    if not shown:
        _cancel_dialog(game)
        return False, "couldn't read the price in the buy window; didn't buy"
    if amount_value(shown) != target:
        _cancel_dialog(game)
        return False, f"price in the buy window is {shown}, not {price}; didn't buy"
    button = _green_button_right_of(game.frame(), cancel[0], s)
    if not button:
        _cancel_dialog(game)
        return False, "couldn't find the green BUY button; didn't buy"
    if dry_run:
        _cancel_dialog(game)
        return True, f"dry run: would click BUY at {button} for {shown}"
    game.click(*button)
    game.park_mouse()
    game.wait(1.5)
    if _buy_window_price(game, title[0], s):  # window still open: it didn't go through
        _cancel_dialog(game)
        return False, "the purchase didn't go through (the buy window stayed open)"
    return True, f"bought {card['name']} for {shown}"


def _buy_title(words):
    """Where "Buy <name>?" is, in the buy window's title. Other words "Buy" are on the
    screen too (every card says "Buy now", and has a BUY button), so the right one is the
    "Buy" just above the window's "Price:" line (or, failing that, the one followed by a
    word ending in "?"). None if the window isn't up."""
    buys = [(x, y) for t, x, y in words if t.lower() == "buy"]
    for t, px, py in words:
        if t.lower().startswith("price:"):  # (cards say "Price history", with no colon)
            above = [(x, y) for x, y in buys if abs(x - px) < 70 and 15 < py - y < 100]
            if above:
                return min(above, key=lambda b: py - b[1])
    for x, y in buys:
        if any(t.endswith("?") and abs(wy - y) < 10 and 0 < wx - x < 150 for t, wx, wy in words):
            return (x, y)
    return None


def _buy_window_price(game, title, s):
    """The 'Price: 1.0T coins' line under the window's 'Buy <name>?' title, read
    from just that small area enlarged; None if it isn't there."""
    img = game.frame()
    x, y = title
    area = img[int(y - 20 * s):int(y + 70 * s), int(x - 25 * s):int(x + 300 * s)]
    text = fix_numbers(" ".join(t for t, _, _ in read_words(area, scale=4)))
    m = re.search(r"Price:?\s*([\d.,]+\s*[KMBTQ])", text, re.I)
    return m.group(1).replace(" ", "") if m else None


def _green_button_right_of(img, cancel, s):
    """Center of the green button on the same row as Cancel, to its right."""
    cx, cy = cancel
    x0, x1 = int(cx + 40 * s), int(cx + 260 * s)
    y0, y1 = int(cy - 18 * s), int(cy + 18 * s)
    strip = img[y0:y1, x0:x1].astype(int)
    b, g, r = strip[..., 0], strip[..., 1], strip[..., 2]
    green = (g > 150) & (g > r + 50) & (g > b + 50)
    if green.sum() < 1500 * s * s:
        return None
    ys, xs = np.where(green)
    return x0 + int(xs.mean()), y0 + int(ys.mean())


GRID_TOP = 0.31  # the card grid starts below the "N cards for sale" line


def _similar_key(a, b):
    """Same listing, allowing for small OCR differences in the seller's name."""
    return (a[0] == b[0] and a[2] == b[2] and SequenceMatcher(None, a[1], b[1]).ratio() > 0.75
            and SequenceMatcher(None, a[3], b[3]).ratio() > 0.6)


def _show_more(img):
    """Center of the "Show more (N)" button if it's on screen."""
    h, w = img.shape[:2]
    x0, y0 = int(w * 0.15), int(h * GRID_TOP)
    words = read_words(img[y0:int(h * 0.9), x0:int(w * 0.85)], scale=2)
    for i, (t, x, y) in enumerate(words):
        if t.lower() == "show" and i + 1 < len(words) and words[i + 1][0].lower().startswith("more"):
            return x0 + x + 30, y0 + y
    return None


def _grid_thumb(img):
    h, w = img.shape[:2]
    grid = img[int(h * GRID_TOP):int(h * 0.88), int(w * 0.2):int(w * 0.75)]
    return cv2.cvtColor(cv2.resize(grid, (80, 50)), cv2.COLOR_BGR2GRAY).astype(int)


def _settle_grid(game, maxwait=1.0, first=0.12):
    """Wait until the card grid has stopped moving (a scroll, more cards loading), not a
    fixed time: two looks 0.1s apart that match."""
    game.wait(first)
    prev = _grid_thumb(game.frame())
    end = time.time() + maxwait
    while time.time() < end:
        game.wait(0.1)
        cur = _grid_thumb(game.frame())
        if float(np.abs(cur - prev).mean()) < 3.0:
            return
        prev = cur


WANTED_SERIALS = {"1", "2", "3"}
DEBUG_PAGES = os.environ.get("SCAN_DEBUG") == "1"
STOP_AFTER = 12  # this many cards in a row past #3 (two full rows) = we're past them all


def scan(game, read_bidders=True, max_pages=60, log=print, should_stop=lambda: False):
    """List every #1, #2 and #3 listing. Sorted by lowest serial, so it scrolls down
    until two full rows in a row are all past #3."""
    if not set_sort_lowest_serial(game):
        log("Couldn't set the market sort to Lowest serial.")
    img = game.frame()
    h, w = img.shape[:2]
    grid_mid = (w / 2, h * 0.55)
    game.scroll(*grid_mid, 30, check=False)  # back to the top
    _settle_grid(game, 1.0)
    found, seen = [], set()
    done = False
    past = 0  # cards in a row with a serial above #3
    stale = 0  # pages in a row with nothing new (end of the list)
    for page in range(max_pages):
        if should_stop():
            log("Market scan cut short for a bid/buy")
            break
        img = game.frame()
        s = game.ui_scale(img)
        if DEBUG_PAGES:
            cv2.imwrite(os.path.join(HERE, f"scan_page_{page:02d}.jpg"), cv2.resize(img, None, fx=0.5, fy=0.5))
        new = 0
        for bid in bid_buttons(game, img):
            if bid[1] + CARD_TOP * s < h * GRID_TOP:
                continue  # card cut off at the top; it's read fully on another page
            card = read_listing(game, img, bid)
            # Same listing seen again on another scroll position? Artwork can be
            # animated, so match on what doesn't change: serial, seller and price
            key = (card["serial"], (card.get("seller") or "").lower()[:10],
                   card.get("start") or card.get("current_bid") or card.get("buy_now"),
                   (card.get("name") or "").lower())
            if key in seen or any(_similar_key(key, k) for k in seen):
                continue
            seen.add(key)
            new += 1
            if card["serial"] not in WANTED_SERIALS:
                past += 1
                if past >= STOP_AFTER:
                    done = True
                    break
                continue
            past = 0
            # a picture of just the card for the website (names in fancy fonts don't
            # OCR well): from its top edge down to where the price box starts
            cx = bid[2]
            thumb = img[max(0, int(bid[1] + CARD_BOTTOM_TOP[0] * s)):int(bid[1] + CARD_BOTTOM_TOP[1] * s),
                        int(cx - CARD_HALF_W * s):int(cx + CARD_HALF_W * s)]
            card["image"] = f"card_{len(found):03d}.jpg"
            os.makedirs(CARDS_DIR, exist_ok=True)
            # (twice the size, so it stays sharp when the website shows it enlarged)
            cv2.imwrite(os.path.join(CARDS_DIR, card["image"]), cv2.resize(thumb, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
                        [cv2.IMWRITE_JPEG_QUALITY, 88])
            # The bid window is only opened when it has something the listing can't give: who
            # the top bidder is (a listing with a bid on it), or a start price whose unit
            # couldn't be read. A listing with no bids just has "Start <price>" and no bidder
            start, trusted = _fix_price(card.get("start"))
            if start:
                card["start"] = start
            if read_bidders and ("start" not in card or not trusted):
                card.update(top_bidder(game, bid))
            elif "start" in card:
                card["top_bidder"] = None
            card["seen_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            secs = left_seconds(card.get("time_left"))
            if secs is not None:
                card["ends_ts"] = time.time() + secs  # for the website's live countdown
            card.pop("raw", None)
            found.append(card)
        if done:
            break
        # Only part of the market is loaded at a time; a "Show more (N)" button sits
        # at the end of what's loaded. Press it when it's on screen.
        more = _show_more(img)
        if more:
            game.click(*more)
            game.park_mouse()
            _settle_grid(game, 2.0)
            stale = 0
            continue
        stale = stale + 1 if new == 0 else 0
        if stale >= 4:
            break  # nothing new for a while and no Show more: the end of the list
        game.scroll(*grid_mid, -2, check=False)  # (the market is open: no need to check it each time)
        _settle_grid(game, 1.0)
    log(f"Scanned {len(seen)} listing(s) over {page + 1} page(s)")
    return found
