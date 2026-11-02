"""The game's Trade window, read and clicked in memory: detecting it, putting its card lists in serial order, reading
the cards (mine and theirs, each with its artwork's picture id for the website), and answering trade requests.

In CardsUI: the request popup (a frame with "<name> wants to trade!" and Accept / Decline buttons, slid above the
screen's top when it isn't up), the Trade menu (a "Trade" panel listing the server's players: display name, "@user"
and a "Send trade" button each), and TradeWindow: "Trading with <name>", the "Your cards" / "Their cards" tabs, the
sort chips (Rarity ... Serial, A-Z), the search box, the card grid, both offers ("Your offer" / "<name>'s offer", each
with a READY / NOT READY tag, a summary line and its own grid), the coins box with Set, and Cancel / READY.

Nothing here adds a card, presses READY or sends a trade on its own: the website asks for each of those.
"""
import re

import card_art
import mem_gui
import mem_market

COUNT = re.compile(r"^x\s*(\d+)$", re.I)
WANTED = re.compile(r"^(WANTED|ASKED)\b(?:\s*x\s*(\d+))?", re.I)
_AMOUNT = re.compile(r"^\d+(\.\d+)?[KMBTQ]?$", re.I)


# ---------- finding the parts ----------

def _mb():
    g = mem_gui.gui()
    return g, g.mb if g else None


def _find(under, name=None, depth=4, cls=None):
    g, mb = _mb()
    if g is None or under is None:
        return None
    return next((o for _, o in mb._walk(under, depth, 6000)
                 if (name is None or mb._name(o) == name) and (cls is None or mb._class_name(o) == cls)), None)


def _labels(under, depth=10, shown=True, max_nodes=6000):
    """[(text, object)] of the texts under `under` (only the showing ones, if `shown`)."""
    g, mb = _mb()
    if g is None or under is None:
        return []
    out = []
    for _, o in mb._walk(under, depth, max_nodes):
        if mb._class_name(o) in mem_gui.TEXT_CLASSES:
            t = (mb._content_text(o) or "").strip()
            if t and (not shown or g.is_shown(o)):
                out.append((t, o))
    return out


def _window():
    """TradeWindow, while it's showing."""
    tw = _find(mem_gui.screen("CardsUI"), "TradeWindow", depth=3)
    return tw if mem_gui.shown(tw) else None


def _box(tw=None):
    """The window's main frame (TradeWindow > Frame)."""
    g, mb = _mb()
    tw = tw or _window()
    return next((c for c in mb._children(tw) if mb._class_name(c) == "Frame"), None) if tw else None


def _part_with(under, text, depth=3):
    """The child frame of `under` that has a label starting with `text` somewhere inside it."""
    g, mb = _mb()
    for c in mb._children(under) if under else []:
        if mb._class_name(c) == "Frame" and any(t.startswith(text) for t, _ in _labels(c, depth, shown=False, max_nodes=800)):
            return c
    return None


def _cards_panel():
    """The left half: tabs, sort chips, search box, the grid."""
    return _part_with(_box(), "Your cards")


def _offers_panel():
    return _part_with(_box(), "Your offer", depth=4)


def _offer(which):
    """One side's offer frame ("Your offer" / "<name>'s offer")."""
    g, mb = _mb()
    panel = _offers_panel()
    for c in mb._children(panel) if panel else []:
        heads = [t for t, o in _labels(c, 1, shown=False)]
        if which == "mine" and "Your offer" in heads or which == "theirs" and any(t.endswith("'s offer") for t in heads):
            return c
    return None


def _grid(frame):
    return _find(frame, cls="ScrollingFrame", depth=2)


# ---------- the window and the requests ----------

def window_open(game=None, img=None):
    """The other player's name if the trade window is up, else None."""
    box = _box()
    for t, _ in _labels(box, 1):
        m = re.match(r"Trading with\s+(.+)", t)
        if m:
            return m.group(1).strip() or "?"
    return "?" if box is not None else None


def incoming(game=None, img=None):
    """A pending request popup: {"name", "accept", "decline"} (the buttons) or None."""
    g, mb = _mb()
    sg = mem_gui.screen("CardsUI")
    if g is None or sg is None:
        return None
    for _, o in mb._walk(sg, 3, 400):
        if mb._class_name(o) != "Frame":
            continue
        title = None
        for c in mb._children(o):
            t = (mb._content_text(c) or "").strip() if mb._class_name(c) == "TextLabel" else ""
            if re.search(r"wants?\s+to\s+trade", t, re.I):
                title = (t, c)
        if not title:
            continue
        geo = g.geom(title[1])
        if not g.is_shown(title[1]) or not geo or geo[1] < 0:  # (slid above the screen when there's none)
            return None
        acc, dec = mem_gui.button(o, "Accept", depth=2), mem_gui.button(o, "Decline", depth=2)
        if not acc or not dec:
            return None
        return {"name": re.split(r"\s+wants?\s+to\s+trade", title[0], flags=re.I)[0].strip(), "accept": acc,
                "decline": dec, "covered": False}
    return None


def respond(game, accept, log=print):
    """Press Accept or Decline on the request popup. False if there isn't one."""
    req = incoming()
    if not req:
        log("No trade request on screen")
        return False
    mem_gui.click(game, req["accept"] if accept else req["decline"])
    log(f"{'Accepted' if accept else 'Declined'} the trade request from {req['name']}")
    return True


# ---------- the card tiles ----------

def _tile(tile):
    """A tile's card: {name, rarity, serial, copy, grade, income, count, wanted, wanted_n, art}."""
    g, mb = _mb()
    texts = mem_market._texts(mb, tile, depth=8)
    if not texts:
        return None
    f = mem_market.parse([t for t in texts if not COUNT.match(t[0]) and not WANTED.match(t[0])])
    if not f.get("name"):
        return None
    count = next((int(m.group(1)) for t in texts if (m := COUNT.match(t[0]))), 1)
    want = next((m for t in texts if (m := WANTED.match(t[0])) and g.is_shown(t[4])), None)
    grade = f.get("grade") or next((t[0] for t in texts if t[0].lower() == "ungraded"), "")
    serial = f.get("serial") or (f.get("copy") or "").split("/")[0] or ""
    img = card_art._artwork(mb, tile)
    art = card_art.image_id(mb, img) if img else None
    if art:
        card_art.record(f["name"], f.get("rarity"), art)
    return {"name": f["name"], "rarity": (f.get("rarity") or "").lower(), "grade": grade, "income": f.get("income", ""),
            "serial": serial, "copy": f.get("copy", ""), "wanted": bool(want and want.group(1).upper() == "WANTED"),
            "wanted_n": int(want.group(2)) if want and want.group(2) else (1 if want else 0), "count": count,
            "art": art, "_obj": tile}


def _tiles(grid):
    """[card] of every tile in a grid (shown or scrolled away), in the grid's order."""
    g, mb = _mb()
    if grid is None:
        return []
    kids = [c for c in mb._children(grid) if mb._class_name(c) in ("Frame", "TextButton", "ImageButton")]
    cards = [c for c in (_tile(k) for k in kids) if c]
    return sorted(cards, key=lambda c: (round((g.geom(c["_obj"]) or (0, 0))[1] / 20), (g.geom(c["_obj"]) or (0, 0))[0]))


def _public(cards):
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in cards]


def _into_view(game, grid, tile):
    """Scroll the grid until the tile is showing. True if it is."""
    g, _ = _mb()
    box = g.geom(grid) if grid else None
    for _ in range(12):
        if g.is_shown(tile):
            return True
        geo = g.geom(tile)
        if not box or not geo:
            return False
        game.scroll(box[0], box[1], 2 if geo[1] < box[1] else -2, check=False)
        game.wait(0.35)
    return g.is_shown(tile)


def _click_tile(game, grid, tile):
    if not _into_view(game, grid, tile):
        return False
    ok = mem_gui.click(game, tile)
    game.wait(0.9)
    return ok


# ---------- sorting, tabs, search ----------

def _chip(text):
    return next((o for t, o in _labels(_cards_panel(), 4) if t == text), None)


def _in_serial_order(cards):
    nums = [int(c["serial"]) for c in cards if str(c.get("serial", "")).isdigit()]
    return nums == sorted(nums)


def ensure_serial(game, log=print):
    """Put the trade window's card lists in serial order (lowest first). The choice is shared by both tabs."""
    if _in_serial_order(_tiles(_grid(_cards_panel()))[:20]):
        return True
    chip = _chip("Serial")
    g, mb = _mb()
    if chip is None:
        log("Trade window: couldn't find the Serial sort")
        return False
    for _ in range(2):
        mem_gui.click(game, mb._parent(chip))
        game.wait(0.7)
        if _in_serial_order(_tiles(_grid(_cards_panel()))[:20]):
            log("Trade window: sorted by serial")
            return True
    log("Trade window: couldn't switch to serial sort")
    return False


def show_tab(game, which):
    """'mine' or 'theirs'."""
    g, mb = _mb()
    lab = next((o for t, o in _labels(_cards_panel(), 3) if t == ("Your cards" if which == "mine" else "Their cards")), None)
    if lab is not None:
        mem_gui.click(game, mb._parent(lab))
        game.wait(0.8)


def search_cards(game, query, log=print):
    """Type into the window's Search box (empty clears it)."""
    from ui_keys import clear_field, type_text
    box = _find(_cards_panel(), cls="TextBox", depth=2)
    if box is None or not mem_gui.click(game, box, park=False):
        return
    game.wait(0.3)
    clear_field()
    if query:
        type_text(query)
    game.park_mouse()
    game.wait(0.9)


# ---------- reading ----------

def read_cards(game, limit=20, log=print):
    """The first `limit` cards of the open tab, in the order the game shows them (serial order once ensure_serial has
    run). Every tile is in memory, scrolled away or not, so nothing is scrolled."""
    cards = _public(_tiles(_grid(_cards_panel()))[:limit])
    for i, c in enumerate(cards):
        c["rank"] = i + 1
    return cards


def read_wanted_header(game=None, img=None):
    """'they want N of your cards' -> N (0 if the line isn't there)."""
    for t, _ in _labels(_cards_panel(), 2):
        m = re.search(r"want\s*(\d+)\s*of", t, re.I)
        if m:
            return int(m.group(1))
    return 0


def read_offer(game, img=None, which="mine", scrolling=False):
    """What's in one side's offer: {"cards": [...], "ready", "summary": '5 wanted · 1 card · +4.0K/s', "total",
    "coins"}. which: 'mine' or 'theirs'."""
    frame = _offer(which)
    heads = [t for t, _ in _labels(frame, 2, shown=False)]
    ready = any(t.upper() == "READY" for t in heads)
    summary = next((t for t in heads if re.search(r"\d+\s*cards?|/s|wanted", t, re.I)), "")
    m = re.search(r"(\d+)\s*cards?", summary)
    cards, coins = [], ""
    for c in _tiles(_grid(frame)):
        cm = next((re.search(r"([\d.,]+\s*[KMBTQ]?)\s*COINS", t, re.I) for t, _ in _labels(c["_obj"], 6, shown=False)
                   if "COINS" in t.upper()), None)
        if cm:
            coins = cm.group(1).replace(" ", "")
        else:
            cards.append(c)
    if not coins:  # (a coins tile with no card text in it isn't a card: _tiles skipped it)
        for t, _ in _labels(_grid(frame), 6, shown=False):
            if (cm := re.search(r"([\d.,]+\s*[KMBTQ]?)\s*COINS", t, re.I)):
                coins = cm.group(1).replace(" ", "")
    return {"cards": _public(cards), "ready": ready, "summary": summary, "total": int(m.group(1)) if m else None,
            "coins": coins}


def add_wanted(game, log=print, max_cards=None):
    """Click each card of mine that the other player wants (the gold WANTED pill) into the offer, as many copies as
    the pill says. Wanted cards are listed first in 'Your cards'. Does not press READY. Returns the names added."""
    show_tab(game, "mine")
    clicked, added = {}, []
    for _ in range(40):
        grid = _grid(_cards_panel())
        target = next((c for c in _tiles(grid) if c["wanted"]
                       and clicked.get((c["name"], c["rarity"], c["serial"]), 0) < max(1, c["wanted_n"])), None)
        if not target or (max_cards is not None and len(added) >= max_cards):
            break
        key = (target["name"], target["rarity"], target["serial"])
        if not _click_tile(game, grid, target["_obj"]):
            break
        clicked[key] = clicked.get(key, 0) + 1
        added.append(target["name"])
        log(f"Trade: added {target['name']} to the offer")
    return added


def press(game, which):
    """READY or Cancel in the open trade window (the website asked for it)."""
    btn = mem_gui.button(_box(), "Cancel" if which == "cancel" else "READY", depth=3)
    if btn is None:
        return False
    mem_gui.click(game, btn)
    game.wait(0.8)
    return True


# ---------- the Trade menu (players) ----------

def _menu():
    return mem_gui.panel(r"Trade\s*$")


def _open_menu(game):
    """Open the Trade menu from the left-hand button. (ok, message)."""
    from packs import close_any_menu, close_popup
    close_popup(game)
    close_any_menu(game)
    if window_open():
        return False, "a trade window is open"
    spot = mem_gui.locate(text="Trade", screen="CardsUI")
    if not spot:
        return False, "couldn't find the Trade button"
    game.click(spot[0], spot[1])
    game.park_mouse()
    game.wait(1.2)
    if not mem_gui.shown(_menu()):
        return False, "the Trade menu didn't open"
    return True, ""


def _close_menu(game, img=None):
    x = mem_gui.close_x(_menu()) if mem_gui.shown(_menu()) else None
    if x is not None:
        mem_gui.click(game, x)
        game.wait(0.6)


def _player_tiles():
    """[(display name, user, Send trade button)] of every player in the Trade menu (shown or scrolled away)."""
    g, mb = _mb()
    out = []
    for _, o in mb._walk(_menu(), 5, 3000):
        if mb._class_name(o) != "Frame":
            continue
        labs = [(mb._content_text(c) or "").strip() for c in mb._children(o) if mb._class_name(c) == "TextLabel"]
        user = next((t[1:] for t in labs if t.startswith("@")), None)
        name = next((t for t in labs if t and not t.startswith("@")), None)
        send = mem_gui.button(o, "🤝 Send trade", depth=1, exact=False, shown=False) or next(
            (b for t, b in mem_gui.buttons(o, depth=1) if "send" in t.lower()), None)
        if user and send:
            out.append((name or user, user, send))
    return out


def read_players(game, log=print):
    """Everyone in the server, from the Trade menu's player list: ([{name, user}], total)."""
    ok, msg = _open_menu(game)
    if not ok:
        return None, msg
    head = next((t for t, _ in _labels(_menu(), 4) if re.search(r"\d+\s*players?", t)), "")
    m = re.search(r"(\d+)\s*players?", head)
    players = [{"name": n, "user": u} for n, u, _ in _player_tiles()]
    _close_menu(game)
    log(f"Trade: {len(players)} of {m.group(1) if m else '?'} players read")
    return sorted(players, key=lambda p: p["name"].lower()), int(m.group(1)) if m else None


def send_request(game, name, log=print, alt="", dry=False):
    """Trade menu -> the player's tile -> Send trade. Only when exactly one player is that name (their @user or
    display name)."""
    if not name:
        return False, "no player name"
    ok, msg = _open_menu(game)
    if not ok:
        return False, msg
    try:
        tiles = _player_tiles()
        hits = [t for t in tiles if t[1].lower() == name.lower()] or \
               [t for t in tiles if t[0].lower() in (name.lower(), (alt or "").lower())]
        if len(hits) != 1:
            return False, (f"{len(hits)} players match '{name}': be more specific" if hits
                           else f"no player matched '{name}'")
        disp, user, send = hits[0]
        if dry:
            return True, f"would send to {disp} (@{user})"
        grid = _find(_menu(), cls="ScrollingFrame", depth=1)
        if not _into_view(game, grid, send) or not mem_gui.click(game, send):
            return False, f"couldn't get {disp}'s Send trade button into view"
        game.wait(0.8)
        log(f"Sent a trade request to {disp} (@{user})")
        return True, f"request sent to {disp}"
    finally:
        _close_menu(game)


# ---------- adding / asking for / taking out cards ----------

def _squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _same_card(t, want):
    """Is this tile the card the website asked for? The serial and rarity must agree (when both are known), and
    the name."""
    for k in ("serial", "rarity"):
        if want.get(k) and t.get(k) and str(want[k]).lower() != str(t[k]).lower():
            return False
    return bool(_squash(t.get("name"))) and _squash(t.get("name")) == _squash(want.get("name"))


def _click_card(game, tab, card, log=print):
    """Click one card of a tab's grid once (searched for first, if the website's copy came from a search). Returns
    the tile clicked, or None."""
    show_tab(game, tab)
    search_cards(game, str(card.get("query") or ""), log)
    grid = _grid(_cards_panel())
    t = next((c for c in _tiles(grid) if _same_card(c, card)), None)
    if t is None and not card.get("query"):  # not among the loaded tiles: the game's search by name
        search_cards(game, card.get("name", "")[:30], log)
        grid = _grid(_cards_panel())
        t = next((c for c in _tiles(grid) if _same_card(c, card)), None)
    if t is None or not _click_tile(game, grid, t["_obj"]):
        return None
    return t


def add_card(game, card, log=print):
    """Click one of my cards into my offer: the website names it ({"name", "serial", "rarity"}). Does not press
    READY."""
    try:
        t = _click_card(game, "mine", card, log)
        if not t:
            return False, f"couldn't find {card.get('name')} #{card.get('serial')} in my cards"
        log(f"Trade: added {t['name']} #{t['serial']} to the offer")
        return True, f"added {t['name']} #{t['serial']}"
    finally:
        search_cards(game, "", log)


def request_card(game, card, log=print):
    """Click one of the other player's cards in "Their cards": that asks for it (the game puts a WANTED tag on it,
    on both screens; clicking again takes the request back). Returns (ok, message, wanted now)."""
    try:
        t = _click_card(game, "theirs", card, log)
        if not t:
            return False, f"couldn't find {card.get('name')} #{card.get('serial')} in their cards", None
        game.wait(0.4)
        again = next((c for c in _tiles(_grid(_cards_panel())) if _same_card(c, {**card, "serial": t["serial"]})), None)
        now = (again or t)["wanted"] if again else not t["wanted"]
        log(f"Trade: {'asked for' if now else 'no longer asking for'} {t['name']} #{t['serial']}")
        return True, f"{'asked for' if now else 'took back the request for'} {t['name']} #{t['serial']}", now
    finally:
        search_cards(game, "", log)
        show_tab(game, "mine")


def remove_card(game, card, log=print):
    """Click one card in my offer, which takes it back out."""
    grid = _grid(_offer("mine"))
    t = next((c for c in _tiles(grid) if _same_card(c, card)), None)
    if t is None:
        return False, f"{card.get('name')} isn't in my offer"
    if not _click_tile(game, grid, t["_obj"]):
        return False, f"couldn't get {t['name']} into view in my offer"
    log(f"Trade: took {t['name']} #{t['serial']} out of the offer")
    return True, f"took out {t['name']} #{t['serial']}"


def set_coins(game, amount, log=print):
    """Type an amount into the coins box and press Set ("0" takes the coins back out)."""
    from ui_keys import clear_field, type_text
    amount = amount.strip().replace(",", "").upper()
    if not _AMOUNT.match(amount):
        return False, f"not an amount: {amount}"
    bottom = _part_with(_box(), "Both press READY") or _part_with(_box(), "💰")
    box = _find(bottom, cls="TextBox", depth=3)
    set_btn = mem_gui.button(bottom, "Set", depth=3)
    if box is None or set_btn is None:
        return False, "couldn't find the coins box"
    before = {t for t, _ in _labels(bottom, 3)}
    mem_gui.click(game, box, park=False)
    game.wait(0.3)
    clear_field()
    type_text(amount)
    game.wait(0.3)
    mem_gui.click(game, set_btn)
    game.wait(1.0)
    said = " ".join(t for t, _ in _labels(bottom, 3) if t not in before and t not in ("Set", "Cancel", "READY"))
    log(f"Trade: coins set to {amount} ({said or 'no message'})")
    if re.search(r"not\s*enough|invalid|can'?t", said, re.I):
        return False, said
    return True, said or f"coins: {amount}"
