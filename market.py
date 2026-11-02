"""Getting to the Card Market at Spawn.

Teleport to Spawn, then replay the author's recorded key presses exactly (ROUTE), and
press E at the "Open Market" prompt. The camera is never moved anywhere in the bot,
so W/A/S/D always point the same way and the recorded walk works as recorded.

Safety: E is only ever pressed when the one prompt in range is "Open Market". Spawn
has other E prompts nearby (the Potion Shop, a Creator Card pedestal that sells a Robux
pack...), so pressing E blindly is never OK here.

The game draws its prompts itself: each prompt in range gets a BillboardGui "Prompt" in
PlayerGui > CustomPrompts (gone again out of range), its button holding the action
("Open Market") and the object ("Card Market").
"""
import time

import chat
import mem_gui
from packs import close_any_menu, close_popup, teleport

# The author's recording (recordings/20261030-221958), from Spawn with the default camera:
# (keys held, seconds held, pause after). Replayed exactly as recorded.
ROUTE = [("aw", 2.356, 0), ("w", 0.200, 0), ("a", 1.532, 0),
         ("aw", 0.754, 0), ("w", 0.400, 0)]


LEG_PAUSE = 0.08  # seconds between legs (the recording had 0.5-2.2s of idle between them)


def prompts():
    """[(action, object)] of the prompts in range, e.g. [("Open Market", "Card Market")]."""
    g = mem_gui.gui()
    folder = g and g.mb._find_child(g.mb.player_gui, name="CustomPrompts")
    if not folder:
        return []
    mb, out = g.mb, []
    for bb in mb._children(folder):
        btn = mb._find_child(bb, cls="TextButton")
        texts = [t.strip() for c in (mb._children(btn) if btn else []) if (t := mb._content_text(c)) and t.strip()]
        out.append((texts[0] if texts else "", texts[1] if len(texts) > 1 else ""))
    return out


def prompt_position(img=None, game=None):
    """True-ish when the "[E] Open Market" prompt is the one prompt in range (only it may get an E), else None."""
    p = prompts()
    return (0, 0) if len(p) == 1 and p[0][0].lower() == "open market" else None


def market_open(img=None):
    """True if the Card Market window is showing."""
    return bool(mem_gui.showing("MarketUI", text="Card Market"))


def walk_route(game, until_prompt=True):
    """Replay the route, but only as far as needed: the "Open Market" prompt shows up
    well before the recorded walk ends (the last legs are just the author shuffling along
    the stall), so the walk stops the moment it's on screen. The recorded pauses between
    legs were the author's, not the game's, so they're cut to a short beat.
    True if it stopped because the prompt appeared."""
    def seen():
        game.alive()
        return until_prompt and prompt_position() is not None

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
        if prompt_position():
            game.tap("e", hold=0.15)
            for _ in range(4):
                game.wait(0.5)
                if market_open():
                    return True
        else:
            game.wait(0.5)
    return False


def clear_search(game, log=print):
    """The artist box beside the sort button is shared by Browse and Who owns?, and keeps what was typed (a
    Who owns? look-up leaves the artist's name in it): Browse then shows "No cards match your search" and a scan
    reads nothing. Empty it. True if there was something in it."""
    from ui_keys import clear_field
    mem = _search_box_mem(game.size()[1])  # (what's in it, x, y)
    if mem is None:
        return False
    text, cx, cy = mem
    if not text.strip():
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
    for _ in range(6):
        if on_browse():
            clear_search(game)
            return True
        tab = mem_gui.locate(text="Browse", screen="MarketUI", contains=True)
        if not tab:
            game.wait(0.6)
            continue
        chat.hide_window(game)  # (the open chat window lies over the tab)
        game.click(tab[0], tab[1])
        game.park_mouse()
        game.wait(1.2)
    return on_browse()


def on_browse():
    """The Browse tab is showing when its filter chips ("Rarities 93", "Ultra 1") are."""
    return bool(mem_gui.locate(text="Rarities", screen="MarketUI", exact=False)
                and mem_gui.locate(text="Ultra", screen="MarketUI", exact=False))


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
        near = ", ".join(a for a, _ in prompts()) or "none"
        log(f"Market attempt {attempt} didn't work (prompts in range: {near}); "
            + ("trying again" if attempt < attempts else "giving up"))
    log("Couldn't get the Card Market open.")
    return False
