"""The game's Trade window: detecting it, putting its card lists in serial order, reading the cards (mine and
theirs) for the website, and answering trade requests. Positions are relative to the screen centre at UI scale
1 (measured at 1920x1080); the window is centred, and the tiles are found from their red "x1" count badges, so
a scrolled grid reads the same.

Nothing here adds a card, presses READY or sends a trade on its own: the website asks for each of those.
"""
import re
import time

import cv2
import numpy as np

import trade_badges
from gifts import _words
from ocr import read_text

TITLE = (0.09, 0.07, 0.42, 0.14)  # "Trading with <name>"
POPUP = (0.30, 0.08, 0.70, 0.24)  # "<name> wants to trade!  [Accept] [Decline]"
GRID = (200, 225, 1040, 912)  # card grid, in 1920x1080 pixels
NOTCH = 100  # pixels the grid moves per mouse-wheel notch
RARITIES = ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "SECRET", "GLITCHED", "KAWAII", "RADIATION",
            "ICED", "MOLTEN", "CHARGED", "TIDAL", "SPOOKY", "ACID", "METEOR", "ECLIPSE", "BLOOD", "ATLANTIS")


def _scale(game, img):
    return game.ui_scale(img)


def _origin(img, s):
    """Offset that maps 1920x1080 / scale-1 coordinates to this screen (the window is centred)."""
    h, w = img.shape[:2]
    return w / 2 - 960 * s, h / 2 - 540 * s


def _pt(img, s, x, y):
    ox, oy = _origin(img, s)
    return ox + x * s, oy + y * s


# ---------- the window and the requests ----------

def window_open(game, img):
    """The other player's name if the trade window is up, else None."""
    text = " ".join(w[0] for w in _words(game, img, TITLE))
    m = re.search(r"trading\s*with\s*(.*)", text, re.I)
    return (m.group(1).strip() or "?") if m else None


def incoming(game, img):
    """A pending request popup: {"name", "accept": (x, y), "decline": (x, y)} or None."""
    words = _words(game, img, POPUP)
    text = " ".join(w[0] for w in words)
    if not re.search(r"wants?\s*to\s*trade", text, re.I):
        return None
    acc = [(x, y) for t, x, y in words if t.lower().startswith("accept")]
    dec = [(x, y) for t, x, y in words if t.lower().startswith("decline")]
    name = re.split(r"\s*wants?\s*to\s*trade", text, flags=re.I)[0].split()[-1] if text.split() else "?"
    if not acc or not dec:
        return None
    return {"name": name, "accept": acc[0], "decline": dec[0]}


def respond(game, accept, log=print):
    """Press Accept or Decline on the request popup. False if there isn't one."""
    req = incoming(game, game.frame())
    if not req:
        log("No trade request on screen")
        return False
    game.click(*(req["accept"] if accept else req["decline"]))
    game.park_mouse()
    log(f"{'Accepted' if accept else 'Declined'} the trade request from {req['name']}")
    return True


# ---------- sorting ----------

def _chips(game, img):
    """Centres of the sort chips' row: {'unowned': (x, y), 'az': (x, y)} from the text, plus the serial chip
    (between them: its own text can't be read when it's the selected, white-on-blue one)."""
    words = _words(game, img, (0.22, 0.14, 0.5, 0.22))
    un = [(x, y) for t, x, y in words if t.lower().startswith("unow") or t.lower().startswith("unow".replace("o", "0"))]
    az = [(x, y) for t, x, y in words if re.fullmatch(r"a\W?z", t.lower())]
    return un[0] if un else None, az[0] if az else None


def serial_chip(game, img):
    s = _scale(game, img)
    un, az = _chips(game, img)
    if un and az:
        return (un[0] + az[0]) / 2, (un[1] + az[1]) / 2
    return _pt(img, s, 801, 197)


def chip_selected(img, pos):
    """Selected chips are bright blue, the others dark navy."""
    x, y = int(pos[0]), int(pos[1])
    patch = img[y - 9:y + 9, x - 22:x + 22]
    if patch.size == 0:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return float(np.median(hsv[..., 2])) > 170


def ensure_serial(game, log=print):
    """Put the trade window's card lists in serial order (lowest first). The choice is shared by both tabs."""
    img = game.frame()
    pos = serial_chip(game, img)
    if chip_selected(img, pos):
        return True
    for _ in range(2):
        game.click(*pos)
        game.park_mouse()
        game.wait(0.7)
        if chip_selected(game.frame(), pos):
            log("Trade window: sorted by serial")
            return True
    log("Trade window: couldn't switch to serial sort")
    return False


def show_tab(game, which):
    """'mine' or 'theirs'."""
    img = game.frame()
    s = _scale(game, img)
    game.click(*_pt(img, s, 267 if which == "mine" else 388, 190))
    game.park_mouse()
    game.wait(0.8)


# ---------- reading cards ----------

OFFER_MINE = (1060, 200, 1725, 540)  # "Your offer" panel's card area
OFFER_THEIRS = (1060, 585, 1725, 912)  # the other player's offer


def _anchors(img, s, grid=GRID):
    """Centres of the red count badges ('x1') of the tiles in the grid: [(x, y)], top-left to bottom-right."""
    ox, oy = _origin(img, s)
    x0, y0, x1, y1 = (int(ox + grid[0] * s), int(oy + grid[1] * s), int(ox + grid[2] * s), int(oy + grid[3] * s))
    reg = img[y0:y1, x0:x1].astype(np.int16)
    red = (reg[..., 2] > 190) & (reg[..., 1] < 90) & (reg[..., 0] < 100)
    n, _, st, cen = cv2.connectedComponentsWithStats(red.astype(np.uint8))
    out = []
    for i in range(1, n):
        if 120 * s * s <= st[i][4] <= 900 * s * s and 18 * s <= st[i][2] <= 40 * s:
            out.append((x0 + cen[i][0], y0 + cen[i][1]))
    return sorted(out, key=lambda p: (round(p[1] / (60 * s)), p[0]))


_INCOME = re.compile(r"\+?\s*([\d.,]+\s*[KMBTQ]?)\s*/\s*s", re.I)


def parse_tile_text(text):
    """'smoke55 RADIATION Ungraded +4.0K/s each' -> (name, rarity, grade, income)."""
    text = " ".join(text.split())
    m = re.search(r"\b(" + "|".join(RARITIES) + r")\b", text)
    name = text[:m.start()].strip() if m else text
    rarity = m.group(1) if m else ""
    rest = text[m.end():] if m else ""
    inc = _INCOME.search(rest)
    grade = (rest[:inc.start()] if inc else rest).strip()
    return name, rarity.lower(), grade, inc.group(1).replace(" ", "") if inc else ""


def _wanted_label(crop):
    """The gold 'WANTED' pill at the picture's lower left (the other player wants this card)."""
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gold = ((hsv[..., 0] >= 18) & (hsv[..., 0] <= 28) & (hsv[..., 1] > 120) & (hsv[..., 2] > 200)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(gold)
    # a solid pill about 40-65 px wide and 12-24 tall (a photo's orange or a picture's gold edges aren't)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if 52 <= w <= 66 and 20 <= h <= 27 and a >= 0.75 * w * h:  # the pill is about 59 x 24 px
            return True
    return False


def read_tile(game, img, ax, ay, s):
    """One card tile from its count badge at (ax, ay): name, rarity, grade, income, serial, wanted, count."""
    cx, by = ax - 63 * s, ay + 112 * s  # tile centre column, the serial badge's row
    top = int(by + 20 * s)
    crop = img[top:int(by + 106 * s), int(cx - 72 * s):int(cx + 72 * s)]
    name, rarity, grade, inc = parse_tile_text(read_text(crop, scale=2) if crop.size else "")
    wanted = _wanted_label(img[int(by - 14 * s):int(by + 14 * s), int(cx - 72 * s):int(cx - 4 * s)])
    cnt = img[int(ay - 12 * s):int(ay + 12 * s), int(ax - 16 * s):int(ax + 16 * s)]
    m = re.search(r"(\d+)", read_text(cnt, scale=3)) if cnt.size else None
    return {"name": name, "rarity": rarity.lower(), "grade": grade, "income": inc,
            "serial": trade_badges.read_serial(img, cx, by, s), "wanted": wanted,
            "count": int(m.group(1)) if m else 1, "_col": int(round((cx - (img.shape[1] / 2 - 675 * s)) / (164 * s)))}


def read_offer(game, img, which, scrolling=False):
    """What's in one side's offer: {"cards": [...], "ready": bool, "summary": '5 wanted · 1 card · +4.0K/s'}.
    which: 'mine' or 'theirs'."""
    s = _scale(game, img)
    area = OFFER_MINE if which == "mine" else OFFER_THEIRS
    # header line of the panel: "Your offer  NOT READY   .. 5 cards . +16.0K/s"
    hy = 175 if which == "mine" else 551
    x0, y0 = _pt(img, s, 1060, hy)
    head = read_text(img[int(y0):int(y0 + 32 * s), int(x0):int(x0 + 660 * s)], scale=2)
    ready = bool(re.search(r"\bready\b", head, re.I)) and not re.search(r"not\s*ready", head, re.I)
    summary = " ".join(re.findall(r"\d+\s*wanted|\d+\s*cards?|\+?[\d.]+\s*[KMBT]?\s*/\s*s", head, re.I))
    m = re.search(r"(\d+)\s*cards?", summary)
    total = int(m.group(1)) if m else None
    cards, seen = [], set()
    _, oy = _origin(img, s)
    bottom = oy + area[3] * s
    ox, _ = _origin(img, s)
    px, py = ox + 1390 * s, oy + (area[1] + area[3]) / 2 * s
    for step in range(5 if scrolling else 1):
        for ax, ay in _anchors(img, s, area):
            if ay + 112 * s + 100 * s > bottom:
                continue  # a row cut off by the panel's edge: read after scrolling
            t = read_tile(game, img, ax, ay, s)
            t.pop("_col", None)
            key = (t["name"], t["rarity"], t["serial"], t["grade"])
            if key not in seen:
                seen.add(key)
                cards.append(t)
        if not scrolling or total is None or len(cards) >= total:
            break
        game.scroll(px, py, -2, check=False)
        game.wait(0.6)
        img = game.frame()
    if scrolling and step:
        game.scroll(px, py, 20, check=False)  # back to the top
        game.wait(0.3)
    return {"cards": cards, "ready": ready, "summary": summary, "total": total}


def scroll_grid(game, notches):
    img = game.frame()
    s = _scale(game, img)
    x, y = _pt(img, s, 613, 560)
    game.scroll(x, y, notches, check=False)
    game.wait(0.7)


def read_cards(game, limit=20, log=print):
    """The first `limit` cards of the open tab, in the order the game shows them (serial order once
    ensure_serial has run). Scrolls the grid as needed and puts it back at the top."""
    scroll_grid(game, 40)
    cards, seen, scrolled = [], set(), 0
    for _ in range(12):
        img = game.frame()
        s = _scale(game, img)
        _, oy = _origin(img, s)
        bottom = oy + (GRID[3] - 12) * s
        new = 0
        for ax, ay in _anchors(img, s):
            if ay + 112 * s + 92 * s > bottom:
                continue  # the text of this row is cut off: read it after the next scroll
            key = (int(round((ax - _origin(img, s)[0]) / (164 * s))), int(round((ay + scrolled * NOTCH * s) / (20 * s))))
            if key in seen:
                continue
            seen.add(key)
            cards.append(read_tile(game, img, ax, ay, s))
            new += 1
            if len(cards) >= limit:
                break
        if len(cards) >= limit:
            break
        scroll_grid(game, -2)
        scrolled += 2
        if not new and scrolled > 4:
            break
    scroll_grid(game, 40)
    for i, c in enumerate(cards):
        c.pop("_col", None)
        c["rank"] = i + 1
    return cards[:limit]


def read_wanted_header(game, img):
    """'they want N of your cards' -> N (0 if the line isn't there)."""
    s = _scale(game, img)
    x0, y0 = _pt(img, s, 200, 200)
    crop = img[int(y0):int(y0 + 30 * s), int(x0):int(x0 + 320 * s)]
    if not crop.size:
        return 0
    for scale in (3, 2, 4):
        m = re.search(r"want\s*(\d+)", read_text(crop, scale=scale), re.I)
        if m:
            return int(m.group(1))
    return 0


def _wanted_qty(crop):
    """The pill says 'WANTED' or 'WANTED x2': how many copies they want."""
    m = re.search(r"x\s*(\d+)", read_text(crop, scale=3), re.I)
    return max(1, min(int(m.group(1)), 9)) if m else 1


def add_wanted(game, log=print, max_cards=None):
    """Click each card of mine that the other player wants (the gold WANTED pill) into the offer, as many
    copies as the pill says. Wanted cards are listed first in 'Your cards'. Does not press READY.
    Returns the names added."""
    show_tab(game, "mine")
    scroll_grid(game, 40)
    clicked, added = {}, []
    for _ in range(14):
        img = game.frame()
        s = _scale(game, img)
        _, oy = _origin(img, s)
        bottom = oy + (GRID[3] - 12) * s
        target = None
        for ax, ay in _anchors(img, s):
            cx, by = ax - 63 * s, ay + 112 * s
            if by + 20 * s > bottom:
                continue
            pill = img[int(by - 14 * s):int(by + 14 * s), int(cx - 72 * s):int(cx - 4 * s)]
            if not _wanted_label(pill):
                continue
            t = read_tile(game, img, ax, ay, s)
            key = (t["name"], t["rarity"], t["serial"])
            if clicked.get(key, 0) < _wanted_qty(pill):
                target = (cx, by - 45 * s, key, t["name"])
                break
        if not target or (max_cards is not None and len(added) >= max_cards):
            break
        game.click(target[0], target[1])
        game.park_mouse()
        game.wait(0.9)
        clicked[target[2]] = clicked.get(target[2], 0) + 1
        added.append(target[3])
        log(f"Trade: added {target[3]} to the offer")
    return added


def press(game, which):
    """READY or Cancel in the open trade window (the website asked for it)."""
    img = game.frame()
    words = _words(game, img, (0.5, 0.84, 1.0, 0.99))
    if which == "cancel":
        hit = [(x, y) for t, x, y in words if t.lower().startswith("cancel")]
    else:
        hit = sorted((x, y) for t, x, y in words if t.upper().rstrip("!") == "READY" and x > img.shape[1] * 0.72)
    if not hit:
        return False
    game.click(*hit[-1])
    game.park_mouse()
    game.wait(0.8)
    return True


def _menu_title(game, img):
    s = _scale(game, img)
    x0, y0 = _pt(img, s, 470, 175)
    crop = img[int(y0):int(y0 + 55 * s), int(x0):int(x0 + 260 * s)]
    return bool(crop.size) and "trade" in read_text(crop, scale=2).lower()


def _open_menu(game):
    """Open the Trade menu from the left-hand button. (ok, message)."""
    from packs import close_any_menu, close_popup
    close_popup(game)
    close_any_menu(game)
    img = game.frame()
    if window_open(game, img):
        return False, "a trade window is open"
    left = [(x, y) for t, x, y in _words(game, img, (0.0, 0.4, 0.14, 0.98)) if t.lower().startswith("trade")]
    if not left:
        return False, "couldn't find the Trade button"
    game.click(*left[0])
    game.park_mouse()
    game.wait(1.2)
    if not _menu_title(game, game.frame()):
        return False, "the Trade menu didn't open"
    return True, ""


def _close_menu(game, img):
    if _menu_title(game, game.frame()):
        s = _scale(game, img)
        game.click(*_pt(img, s, 1466, 202))
        game.park_mouse()
        game.wait(0.6)


_PLAYER = re.compile(r"^(.*?)\s*@\s*(\S+)\s*$")


def read_players(game, log=print):
    """Everyone in the server, from the Trade menu's player list (it scrolls): ([{name, user}], total)."""
    from ui_keys import clear_field
    ok, msg = _open_menu(game)
    if not ok:
        return None, msg
    img = game.frame()
    s = _scale(game, img)
    game.click(*_pt(img, s, 960, 263))
    game.wait(0.3)
    clear_field()
    game.park_mouse()
    game.wait(1.0)
    img = game.frame()
    x0, y0 = _pt(img, s, 600, 290)
    head = read_text(img[int(y0):int(y0 + 35 * s), int(x0):int(x0 + 700 * s)], scale=2)
    m = re.search(r"(\d+)\s*players?", head, re.I)
    total = int(m.group(1)) if m else None
    players, seen, stall = [], set(), 0
    gx, gy = _pt(img, s, 960, 600)
    for _ in range(14):
        img = game.frame()
        sends = [(x, y) for t, x, y in _words(game, img, (0.2, 0.25, 0.8, 0.92)) if t.lower().startswith("send")]
        new = 0
        for sx, sy in sends:
            if sy + 24 * s > _pt(img, s, 0, 905)[1]:
                continue  # button cut off by the list's edge: its name may be too
            cx = min((_pt(img, s, c, 0)[0] for c in (608, 957, 1306)), key=lambda c: abs(c - sx))
            x0, x1 = int(cx - 170 * s), int(cx + 170 * s)
            # the display name and the @user name are read as two separate lines: read together, an "@" read as
            # an "O" ("cable" / "Oka-bel") left a player out of the list altogether
            name = " ".join(read_text(img[int(sy - 74 * s):int(sy - 47 * s), x0:x1], scale=2).split())
            user = "".join(read_text(img[int(sy - 51 * s):int(sy - 27 * s), x0:x1], scale=2).split())
            if user[:1] == "@":
                user = user[1:]
            elif user[:1] in "O0Qo©®" and len(user) > 2:
                user = user[1:]  # the "@" misread
            if not name or not user:
                mm = _PLAYER.match(" ".join(read_text(img[int(sy - 75 * s):int(sy - 20 * s), x0:x1], scale=2).split()))
                if not mm or not mm.group(1):
                    continue
                name, user = mm.group(1).strip(), mm.group(2)
            key = user.lower()
            if key not in seen:
                seen.add(key)
                players.append({"name": name, "user": user})
                new += 1
        if total is not None and len(players) >= total:
            break
        stall = stall + 1 if not new else 0
        if stall >= 2:
            break
        game.scroll(gx, gy, -2, check=False)
        game.wait(0.7)
    game.scroll(gx, gy, 30, check=False)
    _close_menu(game, game.frame())
    log(f"Trade: {len(players)} of {total} players read")
    return sorted(players, key=lambda p: p["name"].lower()), total


def send_request(game, name, log=print, alt="", dry=False):
    """Trade menu -> search the player -> Send trade. Only when exactly one player matches."""
    from ui_keys import clear_field, type_text
    if not name:
        return False, "no player name"
    ok, msg = _open_menu(game)
    if not ok:
        return False, msg
    img = game.frame()
    s = _scale(game, img)
    game.click(*_pt(img, s, 960, 263))
    game.wait(0.3)
    # the name was read off the screen and may have a misread letter: try the whole name, the display name,
    # then the start of each, until exactly one player matches
    tries = []
    for q in (name, alt, name[:7], alt[:7]):
        q = "".join(ch for ch in (q or "") if ch.isascii() and not ch.isspace())
        if q and q not in tries:
            tries.append(q)
    result = (False, f"no player matched '{name}'")
    for q in tries:
        game.click(*_pt(img, s, 960, 263))
        game.wait(0.3)
        clear_field()
        type_text(q)
        game.park_mouse()
        game.wait(1.2)
        img = game.frame()
        x0, y0 = _pt(img, s, 600, 290)
        head = read_text(img[int(y0):int(y0 + 35 * s), int(x0):int(x0 + 700 * s)], scale=2)
        m = re.search(r"(\d+)\s*of\s*(\d+)\s*players?\s*match", head, re.I)
        n = int(m.group(1)) if m else 0
        sends = [(x, y) for t, x, y in _words(game, img, (0.2, 0.25, 0.8, 0.9)) if t.lower().startswith("send")]
        if n == 1 and sends:
            if dry:  # (testing: find the player but don't send)
                result = (True, f"would send to the one player matching '{q}'")
                break
            game.click(*sends[0])
            game.park_mouse()
            game.wait(0.8)
            log(f"Sent a trade request to {name}")
            result = (True, f"request sent to {name}")
            break
        if n > 1:
            result = (False, f"{n} players match '{q}': be more specific")
    if _menu_title(game, game.frame()):  # still open: close it with its X
        game.click(*_pt(img, s, 1466, 202))
        game.park_mouse()
        game.wait(0.6)
    return result


def search_cards(game, query, log=print):
    """Type into the window's Search box (empty clears it)."""
    from ui_keys import clear_field, type_text
    img = game.frame()
    s = _scale(game, img)
    game.click(*_pt(img, s, 975, 197))
    game.wait(0.3)
    clear_field()
    if query:
        type_text(query)
    game.park_mouse()
    game.wait(0.9)
