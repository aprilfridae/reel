"""The game's Trade window: detecting it, putting its card lists in serial order, reading the cards (mine and
theirs) for the website, and answering trade requests. Positions are relative to the screen centre at UI scale
1 (measured at 1920x1080); the window is centred, and the tiles are found from their red "x1" count badges, so
a scrolled grid reads the same.

Nothing here adds a card, presses READY or sends a trade on its own: the website asks for each of those.
"""
import hashlib
import os
import re

import cv2
import numpy as np

import trade_badges
from gifts import _words
from ocr import read_text
from paths import APP

PICS = os.path.join(APP, "web", "static", "tcards")  # card tiles as the website shows them

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
    """The other player's name if the trade window is up, else None. The title ("Trading with <name>") can be
    covered by the chat, so the other panel's header ("<name>'s offer", well away from the chat) also counts."""
    words = _words(game, img, TITLE)
    first = next((w for w in words if w[0].lower().startswith("trading")), None)
    if first:  # only the title's own row (the "@user" line under it is not part of the name)
        text = " ".join(t for t, x, y in words if abs(y - first[2]) < 10 * _scale(game, img))
        m = re.search(r"trading\s*with\s*(.*)", text, re.I)
        if m:
            return m.group(1).strip() or "?"
    s = _scale(game, img)
    x0, y0 = _pt(img, s, 1060, 551)
    head = read_text(img[int(y0):int(y0 + 32 * s), int(x0):int(x0 + 300 * s)], scale=2)
    m = re.search(r"(\S+?)\s*['’`´]?\s*s\s+offer\b", head, re.I)
    return m.group(1) if m and m.group(1).lower() != "your" else None


def incoming(game, img):
    """A pending request popup: {"name", "accept": (x, y), "decline": (x, y)} or None. The title line alone
    counts (a menu can cover the buttons, and their green/red text doesn't always read); the buttons then sit
    where they always are: 55 px under the title, 105 px either side of the screen's centre (at scale 1)."""
    words = _words(game, img, POPUP)
    text = " ".join(w[0] for w in words)
    if not re.search(r"wants?\s*to\s*trade", text, re.I):
        return None
    acc = [(x, y) for t, x, y in words if t.lower().startswith("accept")]
    dec = [(x, y) for t, x, y in words if t.lower().startswith("decline")]
    before = re.split(r"\s*wants?\s*to\s*trade", text, flags=re.I)[0].split()
    name = "_".join(before[-2:]) if len(before) >= 2 and len(before[-1]) <= 4 else (before[-1] if before else "?")  # "ka bel" = ka_bel
    title_y = next((y for t, x, y in words if t.lower().startswith("want")), None)
    s, cx = _scale(game, img), img.shape[1] / 2
    return {"name": name, "covered": not (acc and dec),
            "accept": acc[0] if acc else (cx - 105 * s, title_y + 55 * s),
            "decline": dec[0] if dec else (cx + 105 * s, title_y + 55 * s)}


def respond(game, accept, log=print):
    """Press Accept or Decline on the request popup. False if there isn't one."""
    req = incoming(game, game.frame())
    if req and req["covered"]:  # a menu is in front of the buttons: close it first
        from packs import close_any_menu
        close_any_menu(game)
        game.wait(0.5)
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
        # the pill is about 59 x 24 px; its dark letters leave holes ("ASKED", on their cards I asked for, is
        # only about 2/3 gold)
        if 52 <= w <= 66 and 20 <= h <= 27 and a >= 0.6 * w * h:
            return True
    return False


def _save_picture(img, cx, ay, by, s, key):
    """The whole tile as the game draws it (picture, badges, name) -> web/static/tcards/, for the website.
    Named after what was read off it, so the same card isn't written again."""
    name = hashlib.md5(key.encode("utf-8", "ignore")).hexdigest()[:12] + ".jpg"
    path = os.path.join(PICS, name)
    if not os.path.exists(path):
        tile = img[max(0, int(ay - 10 * s)):int(by + 104 * s), max(0, int(cx - 76 * s)):int(cx + 76 * s)]
        if tile.size:
            os.makedirs(PICS, exist_ok=True)
            cv2.imwrite(path, tile, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return name


def read_tile(game, img, ax, ay, s):
    """One card tile from its count badge at (ax, ay): name, rarity, grade, income, serial, wanted, count, img."""
    cx, by = ax - 63 * s, ay + 112 * s  # tile centre column, the serial badge's row
    top = int(by + 20 * s)
    crop = img[top:int(by + 106 * s), int(cx - 72 * s):int(cx + 72 * s)]
    name, rarity, grade, inc = parse_tile_text(read_text(crop, scale=2) if crop.size else "")
    wanted = _wanted_label(img[int(by - 14 * s):int(by + 14 * s), int(cx - 72 * s):int(cx - 4 * s)])
    cnt = img[int(ay - 12 * s):int(ay + 12 * s), int(ax - 16 * s):int(ax + 16 * s)]
    m = re.search(r"(\d+)", read_text(cnt, scale=3)) if cnt.size else None
    serial = trade_badges.read_serial(img, cx, by, s)
    pic = _save_picture(img, cx, ay, by, s, f"{name}|{rarity}|{serial}|{grade}|{wanted}")
    return {"name": name, "rarity": rarity.lower(), "grade": grade, "income": inc,
            "serial": serial, "wanted": wanted, "img": pic, "_click": (int(cx), int(by - 45 * s)),
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
    coins = read_coins(img, s, area)
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
            t.pop("_click", None)
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
    return {"cards": cards, "ready": ready, "summary": summary, "total": total, "coins": coins}


_COINS = re.compile(r"([\d.,]+\s*[KMBTQ]?)\s*COINS", re.I)


def read_coins(img, s, area):
    """Coins in one side's offer: the gold coin-bag tile says '<amount> COINS'. '' when there are none."""
    ox, oy = _origin(img, s)
    crop = img[int(oy + area[1] * s):int(oy + area[3] * s), int(ox + area[0] * s):int(ox + area[2] * s)]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV) if crop.size else None
    if hsv is None or ((hsv[..., 0] >= 18) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 120)).mean() < 0.01:
        return ""  # no gold tile: skip the reading
    m = _COINS.search(read_text(crop, scale=1))  # (a gold grade badge also passes the colour test: no "COINS")
    return m.group(1).replace(" ", "") if m else ""


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
        c.pop("_click", None)
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
        # a 1 is often read as l or I, stuck to the word: "they wantl of your cards"
        m = re.search(r"want\s*([\dIl|O]+)\s*of", read_text(crop, scale=scale), re.I)
        if m:
            digits = m.group(1).translate(str.maketrans("Il|O", "1110"))
            if digits.isdigit():
                return int(digits)
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


def _same_card(t, want):
    """Does a tile read off the screen match the card the website asked for? The serial and rarity must agree
    (when both are known); the name only roughly, OCR drops or swaps a letter now and then."""
    for k in ("serial", "rarity"):
        if want.get(k) and t.get(k) and str(want[k]).lower() != str(t[k]).lower():
            return False
    a, b = _squash(t.get("name", "")), _squash(want.get("name", ""))
    return bool(a and b) and (a == b or a.startswith(b[:6]) or b.startswith(a[:6]))


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _search_key(name):
    """What to type into the game's search for a card name read off the screen: the part before the first
    letter OCR mixes up (I/l/1/|, O/0), since a wrong letter makes the search find nothing ("XHRIS2EAZY" is
    read "XHRlS2EAZY": "XHR" finds it). At least 3 characters; the serial picks the right tile afterwards."""
    name = name.strip()
    m = re.search(r"[Il1|O0]", name)
    key = name[:m.start()] if m else name
    return (key if len(key.strip()) >= 3 else name[:3]).strip()[:30]


COLS, ROW = 5, 233  # tiles per row; pixels from one row's count badge to the next (1080p, scale 1)
PIC_MATCH = 22  # mean colour difference (0-255) under which a tile is the card in a saved picture


def _tile_sig(img, cx, ay, by, s):
    """A tile shrunk to compare with a saved picture (the same crop _save_picture saves)."""
    tile = img[max(0, int(ay - 10 * s)):int(by + 104 * s), max(0, int(cx - 76 * s)):int(cx + 76 * s)]
    return cv2.resize(tile, (38, 56), interpolation=cv2.INTER_AREA).astype(np.int16) if tile.size else None


def _ref_sig(card):
    name = str(card.get("img") or "")
    ref = cv2.imread(os.path.join(PICS, name)) if re.fullmatch(r"[0-9a-f]{12}\.jpg", name) else None
    return cv2.resize(ref, (38, 56), interpolation=cv2.INTER_AREA).astype(np.int16) if ref is not None else None


def _pick_tile(game, img, s, card, ref, near=None):
    """The tile in sight that is this card, read (read_tile), or None. Candidates: tiles that look like its
    saved picture (or, with no picture, the tile at its place), closest look / place first. The serial must
    agree too: copies of one card look alike apart from the #1 / #2 badge, and a card asked for moves to the
    front, so the tile at the card's old place can be its other copy."""
    _, oy = _origin(img, s)
    cands = []
    for ax, ay in _anchors(img, s):
        cx, by = ax - 63 * s, ay + 112 * s
        if ay < oy + GRID[1] * s or by + 20 * s > oy + GRID[3] * s:
            continue  # its picture isn't fully in sight
        sig = _tile_sig(img, cx, ay, by, s)
        score = float(np.abs(sig - ref).mean()) if ref is not None and sig is not None else None
        dist = ((ax - near[0]) ** 2 + (ay - near[1]) ** 2) ** 0.5 if near else 0
        if score is not None and score >= PIC_MATCH or score is None and dist > 60 * s:
            continue
        cands.append((score or 0, dist, ax, ay))
    for _, _, ax, ay in sorted(cands):
        t = read_tile(game, img, ax, ay, s)
        if not card.get("serial") or not t.get("serial") or str(t["serial"]) == str(card["serial"]):
            return t
    return None


def _click_card(game, tab, card, log=print):
    """Click one card of a tab of the grid once. Returns the tile as read before the click, or None.

    The website lists the cards in the game's own order, so card["rank"] (its place in that order, 1 = first)
    says which row to scroll to and which column it's in. The card's saved picture (card["img"]) confirms the
    tile: a card put in the offer leaves the grid and the ones after it move up a place, so the picture decides
    among the tiles in sight (with no picture, the tile at the card's place is taken). A card from an in-game
    search has card["query"]: the same search is typed first, its place is in those results. Last resort: the
    game's search by name, matched by serial. The search is left in place for a read-back; the caller clears it."""
    show_tab(game, tab)
    search_cards(game, str(card.get("query") or ""), log)
    ref, rank = _ref_sig(card), int(card.get("rank") or 0)
    if rank:
        row, col = (rank - 1) // COLS, (rank - 1) % COLS
        notches = max(0, -(-(240 + row * ROW + 67 - 800) // NOTCH))  # the row's pictures into view
        scroll_grid(game, 40)
        if notches:
            scroll_grid(game, -notches)
        img = game.frame()
        s = _scale(game, img)
        ox, oy = _origin(img, s)
        ex, ey = ox + (285 + 63 + col * 164) * s, oy + (240 + row * ROW - notches * NOTCH) * s  # its count badge
        t = _pick_tile(game, img, s, card, ref, (ex, ey))
        if not t and ref is not None and notches:  # a card asked for moves to the front: look at the top too
            scroll_grid(game, 40)
            img = game.frame()
            t = _pick_tile(game, img, s, card, ref)
        if t:
            game.click(*t["_click"])
            game.park_mouse()
            game.wait(0.9)
            return t
        log(f"Trade: {card.get('name')} wasn't at place {rank}; looking it up by name")
    search_cards(game, _search_key(card.get("name", "")), log)
    img = game.frame()
    s = _scale(game, img)
    t = _pick_tile(game, img, s, card, ref) if ref is not None else None
    if not t:
        _, oy = _origin(img, s)
        t = next((x for x in (read_tile(game, img, ax, ay, s) for ax, ay in _anchors(img, s)
                              if ay + 132 * s <= oy + GRID[3] * s) if _same_card(x, card)), None)
    if t:
        game.click(*t["_click"])
        game.park_mouse()
        game.wait(0.9)
    return t


def add_card(game, card, log=print):
    """Click one of my cards into my offer: the website names it ({"name", "serial", "rarity"}). Does not
    press READY."""
    try:
        t = _click_card(game, "mine", card, log)
        if not t:
            return False, f"couldn't find {card.get('name')} #{card.get('serial')} in my cards"
        log(f"Trade: added {t['name']} #{t['serial']} to the offer")
        return True, f"added {t['name']} #{t['serial']}"
    finally:
        search_cards(game, "", log)


def request_card(game, card, log=print):
    """Click one of the other player's cards in "Their cards": that asks for it (the game puts a gold WANTED
    tag on it, on both screens; clicking again takes the request back). Returns (ok, message, wanted now)."""
    try:
        t = _click_card(game, "theirs", card, log)
        if not t:
            return False, f"couldn't find {card.get('name')} #{card.get('serial')} in their cards", None
        game.wait(0.4)  # read the tag back, wherever the card is now (one asked for moves to the front)
        img = game.frame()
        s = _scale(game, img)
        again = _pick_tile(game, img, s, {**card, "serial": t.get("serial") or card.get("serial")}, _ref_sig(card))
        if again:
            now = again["wanted"]
        else:  # not found again (no picture to go by): the tag where it was clicked
            cx, by = t["_click"][0], t["_click"][1] + 45 * s
            now = _wanted_label(img[int(by - 14 * s):int(by + 14 * s), int(cx - 72 * s):int(cx - 4 * s)])
        log(f"Trade: {'asked for' if now else 'no longer asking for'} {t['name']} #{t['serial']}")
        return True, f"{'asked for' if now else 'took back the request for'} {t['name']} #{t['serial']}", now
    finally:
        search_cards(game, "", log)
        show_tab(game, "mine")


def remove_card(game, card, log=print):
    """Click one card in my offer, which takes it back out."""
    img = game.frame()
    s = _scale(game, img)
    for _ in range(4):
        for ax, ay in _anchors(img, s, OFFER_MINE):
            t = read_tile(game, img, ax, ay, s)
            if _same_card(t, card):
                game.click(*t["_click"])
                game.park_mouse()
                game.wait(0.9)
                log(f"Trade: took {t['name']} #{t['serial']} out of the offer")
                return True, f"took out {t['name']} #{t['serial']}"
        ox, oy = _origin(img, s)  # not in sight: scroll the offer down a bit and look again
        game.scroll(ox + 1390 * s, oy + 370 * s, -2, check=False)
        game.wait(0.6)
        img = game.frame()
    return False, f"{card.get('name')} isn't in my offer"


_AMOUNT = re.compile(r"^\d+(\.\d+)?[KMBTQ]?$", re.I)


def set_coins(game, amount, log=print):
    """Type an amount into the coins box and press Set ("0" takes the coins back out)."""
    from ui_keys import clear_field, type_text
    amount = amount.strip().replace(",", "").upper()
    if not _AMOUNT.match(amount):
        return False, f"not an amount: {amount}"
    img = game.frame()
    s = _scale(game, img)
    game.click(*_pt(img, s, 330, 951))
    game.wait(0.3)
    clear_field()
    type_text(amount)
    game.wait(0.3)
    game.click(*_pt(img, s, 482, 951))  # Set
    game.park_mouse()
    game.wait(1.0)
    x0, y0 = _pt(img, s, 560, 905)
    said = " ".join(read_text(game.frame()[int(y0):int(y0 + 42 * s), int(x0):int(x0 + 800 * s)], scale=2).split())
    log(f"Trade: coins set to {amount} ({said or 'no message'})")
    if re.search(r"not\s*enough|invalid|can'?t", said, re.I):
        return False, said
    return True, said or f"coins: {amount}"


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
