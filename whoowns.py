"""The Card Market's "Who owns?" tab: pick an artist and a rarity, see who owns the lowest
serial numbers of that card, and join an owner's server (the game shows a "Join server" button
on owners who are online).

Everything is clicked at positions fixed relative to the market window's centre (the window is
centred and keeps its size at a given UI scale), and read back with OCR.
"""
import re
import time
from difflib import SequenceMatcher

import market
import mem_gui
import webstate
from market_scan import fix_numbers
from ocr import read_words
from ui_keys import clear_field, press_enter, type_text

# offsets from the window's centre, in UI pixels at scale 1 (measured on a 1920x1009 window)
TAB = (-74, -293)
SEARCH_BOX = (420, -293)
FIRST_RESULT_ALONE = (-4, -147)  # a single search result is centred
FIND_BOX = (423, -53)
FIRST_ROW_Y, ROW_PITCH, ROWS_SHOWN = 3, 56, 7
SERIAL_X, NAME_X = (-420, -320), (-290, 140)  # where a row's "#N" and its player name sit
JOIN_X = (260, 450)  # the "Join server" button
CHIPS = {  # the rarity buttons
    "common": (-350, -196), "uncommon": (-234, -196), "rare": (-118, -196), "epic": (-2, -196),
    "legendary": (114, -196), "mythic": (230, -196), "secret": (346, -196), "glitched": (462, -196),
    "kawaii": (-350, -152), "radiation": (-234, -152), "iced": (-118, -152), "molten": (-2, -152),
    "charged": (114, -152), "tidal": (230, -152), "spooky": (346, -152), "acid": (462, -152),
    "meteor": (-350, -108), "eclipse": (-234, -108), "blood": (-118, -108), "atlantis": (-2, -108),
}


def _at(game, img, off):
    h, w = img.shape[:2]
    s = game.ui_scale(img)
    return w / 2 + off[0] * s, h / 2 + off[1] * s


def _text(game, img=None, box=None):
    img = game.frame() if img is None else img
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box or (int(w * 0.18), int(h * 0.2), int(w * 0.82), int(h * 0.9))
    return [(t, x0 + x, y0 + y) for t, x, y in read_words(img[y0:y1, x0:x1], scale=2)]


def open_tab(game):
    """Click the "Who owns?" tab (found by name, else where it always is)."""
    img = game.frame()
    h = img.shape[0]
    mem = mem_gui.locate(text="Who owns", screen="MarketUI", contains=True)
    spot = mem_gui.either(mem and (mem[0], mem[1]), lambda: next(
        ((x, y) for t, x, y in read_words(img, scale=2) if t.lower().startswith("owns") and y < h * 0.3), None))
    game.click(*(spot or _at(game, img, TAB)))
    game.park_mouse()
    game.wait(1.2)


def _search(game, artist):
    """Type the artist into the search box and open the best match. Returns (ok, message)."""
    img = game.frame()
    box = market._search_box_mem(img.shape[0])  # (the same box Browse uses, found in memory)
    game.click(*(box[1:] if box else _at(game, img, SEARCH_BOX)))
    game.wait(0.3)
    clear_field()
    type_text(artist)
    game.wait(1.5)
    words = _text(game)
    text = fix_numbers(" ".join(t for t, _, _ in words))
    if re.search(r"No\s+artist\s+called", text, re.I):
        return False, f"no artist called \"{artist}\""
    m = re.search(r"(\d+)\s+match", text, re.I)
    n = int(m.group(1)) if m else 1
    img = game.frame()
    h, w = img.shape[:2]
    s = game.ui_scale(img)
    tile = mem_gui.locate(text=artist, screen="MarketUI")  # the artist's tile, by its exact name, from memory
    if tile:
        mem_gui.stats["memory"] += 1
        game.click(tile[0], tile[1])
    elif n <= 1:
        game.click(*_at(game, img, FIRST_RESULT_ALONE))
    else:
        # several artists match: the tile whose name (the first line of a tile) is the
        # closest to what was typed
        tops = [(t, x, y) for t, x, y in _text(game, img) if h / 2 - 225 * s < y < h / 2 - 205 * s and len(t) > 2]
        if not tops:
            game.click(w / 2 - 490 * s, h / 2 - 147 * s)  # the first tile
        else:
            t, x, y = max(tops, key=lambda a: SequenceMatcher(None, a[0].lower(), artist.lower()).ratio())
            game.click(x + 25 * s, y + 60 * s)
    game.park_mouse()
    game.wait(1.5)
    return True, f"{n} match(es)"


def _loaded(game):
    """(rows visible?, "still looking up"?) on the artist page."""
    text = " ".join(t for t, _, _ in _text(game)).lower()
    return ("request" in text or "join" in text), ("looking up" in text)


def _read_rows(game):
    """[{serial, name, join}] for the rows visible now."""
    img = game.frame()
    h, w = img.shape[:2]
    s = game.ui_scale(img)
    words = _text(game, img)
    cy = h / 2
    rows = []
    for i in range(ROWS_SHOWN + 2):
        y = cy + (FIRST_ROW_Y + ROW_PITCH * i) * s
        row = [(t, x) for t, x, wy in words if abs(wy - y) < 24 * s]
        if not row:
            continue
        serial = None
        for t, x in row:
            m = re.fullmatch(r"#\s*(\d{1,6})", fix_numbers(t))
            if m and w / 2 + SERIAL_X[0] * s < x < w / 2 + SERIAL_X[1] * s:
                serial = int(m.group(1))
        name = " ".join(t for t, x in sorted(row, key=lambda r: r[1])
                        if w / 2 + NAME_X[0] * s < x < w / 2 + NAME_X[1] * s)
        join = any(t.lower().startswith("join") and w / 2 + JOIN_X[0] * s < x < w / 2 + JOIN_X[1] * s for t, x in row)
        if name or serial is not None:
            rows.append({"serial": serial, "name": name, "join": join, "y": y, "slot": i})
    # The coloured #1 / #2 / #3 badges are often not read, but the rows are consecutive
    # serials: fill a missing number in from the rows around it
    known = [r for r in rows if r["serial"] is not None]
    if known:
        anchor = known[0]
        for r in rows:
            if r["serial"] is None:
                r["serial"] = anchor["serial"] + (r["slot"] - anchor["slot"])
    else:
        for r in rows:
            r["serial"] = r["slot"] + 1  # (nothing readable: assume the list starts at #1)
    return [r for r in rows if r["serial"] > 0 and r["name"]]


def navigate(game, artist, rarity, find=None, log=print):
    """From the open market: Who owns? -> artist -> rarity (-> a serial number). Returns
    (ok, message, exist_text)."""
    rarity = (rarity or "common").lower()
    if rarity not in CHIPS:
        return False, f"unknown rarity {rarity!r}", None
    open_tab(game)
    ok, msg = _search(game, artist)
    if not ok:
        return False, msg, None
    img = game.frame()
    game.click(*_at(game, img, CHIPS[rarity]))
    game.park_mouse()
    game.wait(1.0)
    if find:
        game.click(*_at(game, game.frame(), FIND_BOX))
        game.wait(0.3)
        clear_field()
        type_text(str(find))
        press_enter()
        game.wait(0.5)
    end = time.time() + 20
    while time.time() < end:  # "Looking up who owns it..." for a few seconds
        game.wait(1.0)
        rows_up, looking = _loaded(game)
        if rows_up and not looking:
            break
    exist = None
    m = re.search(r"([\d,]+)\s+exist", fix_numbers(" ".join(t for t, _, _ in _text(game))), re.I)
    if m:
        exist = m.group(1)
    return True, "ok", exist


def lookup(game, artist, rarity="common", find=None, log=print):
    """The owners of an artist's lowest serials in one rarity. Saves web/data/lookup.json
    for the website and returns it."""
    ok, msg, exist = navigate(game, artist, rarity, find, log)
    result = {"artist": artist, "rarity": rarity, "find": find, "ok": ok, "message": msg, "exist": exist,
              "rows": [], "at": time.strftime("%H:%M:%S"), "ts": time.time()}
    if ok:
        seen = {}
        for _ in range(3):
            for r in _read_rows(game):
                seen.setdefault(r["serial"], r)
            img = game.frame()
            h, w = img.shape[:2]
            game.scroll(w / 2 + 200, h / 2 + 150, -3, check=False)
            game.wait(0.6)
        result["rows"] = [{k: v for k, v in r.items() if k != "y"} for _, r in sorted(seen.items())]
        if not result["rows"]:
            result["message"] = "nobody found (or it didn't load)"
    webstate.save("lookup.json", result)
    log(f"Who owns {artist} ({rarity}): {len(result['rows'])} owner(s) read")
    return result


def join(game, artist, rarity, serial, name, log=print):
    """Press "Join server" on the row for this serial (if its owner is still the one asked
    for). Returns (ok, message). The game then moves us to their server."""
    ok, msg, _ = navigate(game, artist, rarity, find=None, log=log)
    if not ok:
        return False, msg
    target = None
    for _ in range(4):
        for r in _read_rows(game):
            if r["serial"] == int(serial):
                target = r
                break
        if target:
            break
        img = game.frame()
        h, w = img.shape[:2]
        game.scroll(w / 2 + 200, h / 2 + 150, -3, check=False)
        game.wait(0.6)
    if not target:
        return False, f"couldn't find #{serial} in the list"
    if name and SequenceMatcher(None, target["name"].lower(), name.lower()).ratio() < 0.6:
        return False, f"#{serial} is now owned by {target['name']!r}, not {name!r}; didn't join"
    if not target["join"]:
        return False, f"{target['name']} isn't in a server you can join right now"
    img = game.frame()
    s = game.ui_scale(img)
    w = img.shape[1]
    game.click(w / 2 + 379 * s, target["y"])  # the Join server button
    game.park_mouse()
    return True, f"joining {target['name']}'s server"
