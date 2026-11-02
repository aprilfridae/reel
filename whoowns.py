"""The Card Market's "Who owns?" tab: pick an artist and a rarity, see who owns the lowest serial numbers of that card,
and join an owner's server (the game shows a "Join server" button on owners who are online).

Read and clicked in memory (MarketUI): the tab, the search box, the artist tiles (by name), the rarity buttons
("Common" ... "Atlantis", the chosen one with a "✔ " in front), "N exist", the "Find #" box, and the list under
"Lowest serial numbers  •  last known owner": one row per serial ("#1", the owner's name, a "Request" or
"Join server" button).
"""
import re
import time
from difflib import SequenceMatcher

import market
import mem_gui
import webstate
from ui_keys import clear_field, press_enter, type_text

RARITIES = ("common", "uncommon", "rare", "epic", "legendary", "mythic", "secret", "glitched", "kawaii", "radiation",
            "iced", "molten", "charged", "tidal", "spooky", "acid", "meteor", "eclipse", "blood", "atlantis")


def _shown(cls=None, under=None, depth=22):
    """[(text, object, (x, y, w, h))] of the showing objects in MarketUI (of class `cls`)."""
    g = mem_gui.gui()
    root = under or mem_gui.screen("MarketUI")
    if g is None or root is None:
        return []
    mb, out = g.mb, []
    for _, o in mb._walk(root, depth, 30000):
        c = mb._class_name(o)
        if (cls and c not in cls) or (not cls and c not in mem_gui.TEXT_CLASSES):
            continue
        if g.is_shown(o):
            out.append(((mb._content_text(o) or "").strip() if c in mem_gui.TEXT_CLASSES else "", o, g.geom(o)))
    return out


def _all_text():
    return " ".join(t for t, _, _ in _shown())


def open_tab(game):
    """Click the "Who owns?" tab."""
    spot = mem_gui.locate(text="Who owns", screen="MarketUI", contains=True)
    if spot:
        game.click(spot[0], spot[1])
        game.park_mouse()
        game.wait(1.2)
    return bool(spot)


def _search(game, artist):
    """Type the artist into the search box and open the best match. Returns (ok, message)."""
    box = market._search_box_mem(game.size()[1])
    if not box:
        return False, "couldn't find the search box"
    game.click(box[1], box[2])
    game.wait(0.3)
    clear_field()
    type_text(artist)
    game.wait(1.5)
    text = _all_text()
    if re.search(r"No\s+artist\s+called", text, re.I):
        return False, f"no artist called \"{artist}\""
    m = re.search(r"(\d+)\s+match", text, re.I)
    n = int(m.group(1)) if m else 1
    tile = mem_gui.locate(text=artist, screen="MarketUI")  # the artist's tile, by its exact name
    if not tile:  # else the closest name among the tiles (below the tab row and the "N match" line)
        names = [(SequenceMatcher(None, t.lower(), artist.lower()).ratio(), geo) for t, _, geo in _shown(("TextLabel",))
                 if t and geo and geo[1] > box[2] + 70 and len(t) < 40]
        best = max(names, key=lambda a: a[0], default=None)
        if not best or best[0] < 0.6:
            return False, f"couldn't find \"{artist}\" among the {n} match(es)"
        tile = best[1]
    game.click(tile[0], tile[1])
    game.park_mouse()
    game.wait(1.5)
    return True, f"{n} match(es)"


def _chip(rarity):
    """The rarity button, and whether it's the chosen one."""
    for t, o, geo in _shown(("TextButton",)):
        name = t.lstrip("✔ ").strip().lower()
        if name == rarity and geo:
            return geo, t.startswith("✔")
    return None, False


def _find_box():
    """The "Find #" box: the text box nearest the "Find #" label."""
    label = next((geo for t, _, geo in _shown(("TextLabel",)) if t.startswith("Find #") and geo), None)
    boxes = [geo for _, _, geo in _shown(("TextBox",)) if geo]
    if not label or not boxes:
        return None
    return min(boxes, key=lambda b: abs(b[0] - label[0]) + abs(b[1] - label[1]))


def _list():
    """The ScrollingFrame of owner rows (beside the "Lowest serial numbers" label), or None."""
    g = mem_gui.gui()
    head = next((o for t, o, _ in _shown(("TextLabel",)) if t.startswith("Lowest serial numbers")), None)
    if g is None or head is None:
        return None
    par = g.mb._parent(head)
    return next((c for c in g.mb._children(par) if g.mb._class_name(c) == "ScrollingFrame"), None) if par else None


def _loaded(game=None):
    """(rows there?, "still looking up"?) on the artist page."""
    return bool(_read_rows()), "looking up" in _all_text().lower()


def _read_rows(game=None):
    """[{serial, name, join, y, shown, button}] of every row loaded in the list (shown or scrolled away)."""
    g, lst = mem_gui.gui(), _list()
    if lst is None:
        return []
    mb, rows = g.mb, []
    for row in mb._children(lst):
        if mb._class_name(row) != "Frame":
            continue
        serial = name = None
        button = None
        for _, o in mb._walk(row, 3, 40):
            c = mb._class_name(o)
            t = (mb._content_text(o) or "").strip() if c == "TextLabel" else ""
            if c == "TextLabel" and mb._parent(o) == row and t:
                name = t
            elif c == "TextLabel" and (m := re.fullmatch(r"#\s*(\d{1,7})", t)):
                serial = int(m.group(1))
            elif c == "TextButton":
                button = o
        if serial is None or not name:
            continue
        btext = mem_gui.text_of(button).lower() if button else ""
        geo = g.geom(button or row)
        rows.append({"serial": serial, "name": name, "join": btext.startswith("join"), "y": geo[1] if geo else None,
                     "shown": bool(button and g.is_shown(button)), "button": button})
    return sorted(rows, key=lambda r: r["serial"])


def navigate(game, artist, rarity, find=None, log=print):
    """From the open market: Who owns? -> artist -> rarity (-> a serial number). Returns (ok, message, exist_text)."""
    rarity = (rarity or "common").lower()
    if rarity not in RARITIES:
        return False, f"unknown rarity {rarity!r}", None
    if not open_tab(game):
        return False, "couldn't find the Who owns? tab", None
    ok, msg = _search(game, artist)
    if not ok:
        return False, msg, None
    chip, chosen = _chip(rarity)
    if not chip:
        return False, f"no {rarity} button on {artist}'s page", None
    if not chosen:
        game.click(chip[0], chip[1])
        game.park_mouse()
        game.wait(1.0)
    if find:
        box = _find_box()
        if box:
            game.click(box[0], box[1])
            game.wait(0.3)
            clear_field()
            type_text(str(find))
            press_enter()
            game.wait(0.5)
    end = time.time() + 20
    while time.time() < end:  # "Looking up who owns it..." for a few seconds
        game.wait(1.0)
        rows_up, looking = _loaded()
        if rows_up and not looking:
            break
    m = re.search(r"([\d,]+)\s+exist", _all_text(), re.I)
    return True, "ok", m.group(1) if m else None


def lookup(game, artist, rarity="common", find=None, log=print):
    """The owners of an artist's lowest serials in one rarity. Saves web/data/lookup.json for the website and
    returns it."""
    ok, msg, exist = navigate(game, artist, rarity, find, log)
    result = {"artist": artist, "rarity": rarity, "find": find, "ok": ok, "message": msg, "exist": exist,
              "rows": [], "at": time.strftime("%H:%M:%S"), "ts": time.time()}
    if ok:
        result["rows"] = [{k: r[k] for k in ("serial", "name", "join")} for r in _read_rows()]
        if not result["rows"]:
            result["message"] = "nobody found (or it didn't load)"
    webstate.save("lookup.json", result)
    log(f"Who owns {artist} ({rarity}): {len(result['rows'])} owner(s) read")
    return result


def join(game, artist, rarity, serial, name, log=print):
    """Press "Join server" on the row for this serial (if its owner is still the one asked for). Returns
    (ok, message). The game then moves us to their server."""
    ok, msg, _ = navigate(game, artist, rarity, find=None, log=log)
    if not ok:
        return False, msg
    target = next((r for r in _read_rows() if r["serial"] == int(serial)), None)
    if not target:
        return False, f"couldn't find #{serial} in the list"
    if name and SequenceMatcher(None, target["name"].lower(), name.lower()).ratio() < 0.6:
        return False, f"#{serial} is now owned by {target['name']!r}, not {name!r}; didn't join"
    if not target["join"]:
        return False, f"{target['name']} isn't in a server you can join right now"
    g, lst = mem_gui.gui(), _list()
    box = g.geom(lst) if lst else None
    for _ in range(10):  # scroll the row's button into view
        target = next((r for r in _read_rows() if r["serial"] == int(serial)), target)
        if target["shown"] or not box or target["y"] is None:
            break
        game.scroll(box[0], box[1], 3 if target["y"] < box[1] else -3, check=False)
        game.wait(0.4)
    if not target["shown"] or not mem_gui.click(game, target["button"]):
        return False, f"couldn't get #{serial}'s Join server button into view"
    return True, f"joining {target['name']}'s server"
