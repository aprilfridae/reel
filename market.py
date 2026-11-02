"""Getting to the Card Market at Spawn.

Teleport to Spawn, then replay the author's recorded key presses exactly (ROUTE), and
press E at the "Open Market" prompt. The camera is never moved anywhere in the bot,
so W/A/S/D always point the same way and the recorded walk works as recorded.

Safety: E is only ever pressed when "Open Market" has been read on screen. Spawn
has other E prompts nearby (e.g. a Creator Card pedestal that sells a Robux pack),
so pressing E blindly is never OK here.
"""
import time

import cv2

import chat
import mem_gui
from game import HERE
from ocr import read_words
from packs import close_any_menu, close_popup, teleport

# The author's recording (recordings/20261030-221958), from Spawn with the default camera:
# (keys held, seconds held, pause after). Replayed exactly as recorded.
ROUTE = [("aw", 2.356, 0), ("w", 0.200, 0), ("a", 1.532, 0),
         ("aw", 0.754, 0), ("w", 0.400, 0)]


LEG_PAUSE = 0.08  # seconds between legs (the recording had 0.5-2.2s of idle between them)


_game = None


def prompt_position(img, game=None):
    """Where the "[E] Open Market" prompt is, or None. Only this prompt may get an E.
    Matched by picture (scores ~1.0 on the prompt, under 0.55 on anything else)."""
    g = game or _game
    hit = g.find("open_market_prompt", img, 0.85) if g else None
    return (hit[0], hit[1]) if hit else None


def market_open(img):
    """True if the Card Market window is showing (memory's yes is trusted; a no is checked on screen)."""
    if mem_gui.showing("MarketUI", text="Card Market"):
        return True
    h, w = img.shape[:2]
    text = " ".join(t for t, _, _ in read_words(img[int(h * 0.1):int(h * 0.45), int(w * 0.15):int(w * 0.85)],
                                                scale=2)).lower()
    return "browse" in text and ("listings" in text or "market" in text)


def walk_route(game, until_prompt=True):
    """Replay the route, but only as far as needed: the "Open Market" prompt shows up
    well before the recorded walk ends (the last legs are just the author shuffling along
    the stall), so the walk stops the moment it's on screen. The recorded pauses between
    legs were the author's, not the game's, so they're cut to a short beat.
    True if it stopped because the prompt appeared."""
    def seen():
        return until_prompt and prompt_position(game.frame(), game) is not None

    for keys, held, pause in ROUTE:
        for k in keys:
            game.key(k, True)
        end = time.time() + held
        try:
            while time.time() < end:
                if seen():
                    return True
                time.sleep(0.03)
        finally:
            for k in keys:
                game.key(k, False)
        time.sleep(LEG_PAUSE)
        if seen():
            return True
    return False


def _try_prompt(game):
    """Press E, but only while the "Open Market" prompt is on screen. True once the
    market is open."""
    # The prompt is flaky (it sometimes ignores E, especially with players nearby),
    # so keep pressing for a while as long as it's on screen
    for _ in range(8):
        if prompt_position(game.frame(), game):
            game.tap("e", hold=0.15)
            for _ in range(4):
                game.wait(0.5)
                if market_open(game.frame()):
                    return True
        else:
            game.wait(0.5)
    return False


def clear_search(game, log=print):
    """The artist box beside the sort button is shared by Browse and Who owns?, and keeps what was typed (a
    Who owns? look-up leaves the artist's name in it): Browse then shows "No cards match your search" and a scan
    reads nothing. Empty it. True if there was something in it."""
    from ocr import read_text
    from ui_keys import clear_field
    img = game.frame()
    s = game.ui_scale(img)
    h, w = img.shape[:2]
    mem = _search_box_mem(h)  # (what's in it, x, y), read from memory
    if mem is not None:
        text, cx, cy = mem
        if not text.strip():
            return False
    else:
        cx, cy = w / 2 + 323 * s, h / 2 - 294 * s
        box = img[int(cy - 16 * s):int(cy + 16 * s), int(cx - 95 * s):int(cx + 95 * s)]
        text = " ".join(read_text(box, scale=3).split()) if box.size else ""
        if not text or text.lower().startswith("search"):
            return False
    log(f"Market: clearing the search box ('{text}')")
    game.click(cx, cy)
    game.wait(0.3)
    clear_field()
    game.park_mouse()
    game.wait(1.0)
    return True


def _search_box_mem(h):
    """The market's search box from memory: (its text, x, y), the showing text box in the top band of the market
    window; None if memory can't tell."""
    g = mem_gui.gui()
    if g is None or not g.screen_on("MarketUI"):
        return None
    try:
        mb = g.mb
        sg = next(s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI")
        for d, o in mb._walk(sg, depth=6, max_nodes=400):
            if mb._class_name(o) == "TextBox":
                geo = g._ok(o)
                if geo and geo[1] < h * 0.3:
                    return mb._content_text(o) or "", geo[0], geo[1]
    except Exception:
        pass
    return None


def ensure_browse_tab(game):
    """The market opens on whichever tab was used last (My Listings, Requests...), but
    scanning and bidding need Browse, so click it. The chat window, if it's up, covers the
    Browse tab and the first column of cards, so it's closed first."""
    chat.hide_window(game)
    for _ in range(4):  # from memory: the Browse tab's chips show, and the tab is found by its name
        if mem_gui.showing("MarketUI", text="Ultra"):
            clear_search(game)
            return True
        tab = mem_gui.locate(text="Browse", screen="MarketUI", contains=True)
        if not tab:
            break
        game.click(tab[0], tab[1])
        game.park_mouse()
        game.wait(1.2)
    for _ in range(4):
        img = game.frame()
        words = read_words(img, scale=2)
        if _on_browse(words, img):
            clear_search(game)
            return True
        h, w = img.shape[:2]
        s = game.ui_scale(img)
        # Normally found by reading its name, but chat text drawn over the tab can hide it,
        # so fall back to where the tab always is (the market window is centred)
        spot = next(((x, y) for t, x, y in words if t.lower().startswith("brow") and y < h * 0.3),
                    (w / 2 - 539 * s, h / 2 - 294 * s))
        game.click(*spot)
        game.park_mouse()
        game.wait(1.2)
    return _on_browse(read_words(game.frame(), scale=2), game.frame())


def _on_browse(words, img):
    """The Browse tab is showing when its filter chips (All / Rarities / Event / Ultra) are."""
    names = {t.lower() for t, x, y in words if y < img.shape[0] * 0.35}
    return "rarities" in names and "ultra" in names


def go_to_market(game, log=print, attempts=3):
    """Teleport to Spawn, replay the recorded walk, open the market. True if open."""
    for attempt in range(1, attempts + 1):
        close_popup(game)
        close_any_menu(game)
        if not teleport(game, "Spawn", settle=0.6, poll=0.25):
            continue
        walk_route(game)
        if _try_prompt(game):
            ensure_browse_tab(game)
            return True
        cv2.imwrite(f"{HERE}/market_fail_{attempt}.png", game.frame())
        log(f"Market attempt {attempt} didn't work; " + ("trying again" if attempt < attempts else "giving up"))
    log("Couldn't get the Card Market open.")
    return False
