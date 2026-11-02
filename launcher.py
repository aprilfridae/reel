"""Opening Roblox and joining the game.

Roblox registers a roblox:// link on Windows, so opening
  roblox://experiences/start?placeId=<id>
starts the player (logged in as whoever is signed in to Roblox on this PC) and joins that
game. A server can be picked with "gameInstanceId=<job id>" (config.json: server_id).
The player has to be signed in already; this never touches a password.
"""
import os
import re
import time

from game import WindowLost, find_roblox


def join_url(cfg):
    url = f"roblox://experiences/start?placeId={int(cfg['place_id'])}"
    if cfg.get("server_id"):
        url += f"&gameInstanceId={cfg['server_id']}"
    return url


def _backend(find=False):
    """The shared memory reader, pointed at the running game (found again when Roblox was restarted, if `find`), or
    None while the game isn't in memory yet."""
    from memory_backend import get_backend
    try:
        mb = get_backend()
    except Exception:
        return None
    if find and not mb.alive() and not mb.reattach(tries=1):
        return None
    return mb


def in_game(game):
    """True once the game's own screen is up (its Packs button is showing, in memory)."""
    import mem_gui
    try:
        return _backend(find=True) is not None and mem_gui.locate(text="Packs", screen="CardsUI") is not None
    except Exception:
        return False


def start_roblox(cfg, log=print):
    """Open the join link (does nothing if a Roblox window is already there)."""
    if find_roblox():
        return True
    log("Roblox isn't open: starting it and joining the game...")
    try:
        os.startfile(join_url(cfg))
    except OSError as e:
        log(f"Couldn't open Roblox ({e}). Is it installed and signed in?")
        return False
    return True


def wait_for_window(timeout=180, log=print):
    """Wait for the Roblox window to show up. True when it has."""
    end = time.time() + timeout
    while time.time() < end:
        if find_roblox():
            return True
        time.sleep(2)
    log("Roblox didn't open in time.")
    return False


def wait_in_game(game, timeout=240, log=print):
    """Wait until the game has loaded (UI visible). True when it has."""
    end = time.time() + timeout
    while time.time() < end:
        game.wait(3)
        if in_game(game):
            log("In the game.")
            return True
    log("The game didn't finish loading in time (continuing anyway).")
    return False


def ensure_running(cfg, log=print):
    """Before the bot starts: make sure a Roblox window exists (starting it if allowed).
    False if there's none and it couldn't be started."""
    if find_roblox():
        return True
    if not cfg.get("auto_launch"):
        log("Roblox isn't open (auto_launch is off in config.json).")
        return False
    return start_roblox(cfg, log) and wait_for_window(log=log)


_DISCONNECTED = re.compile(r"disconnected|lost connection|error code", re.I)


def is_disconnected(game, img=None):
    """Is Roblox's "Disconnected ... (Error Code: 277)" box up? (It appears when the internet drops; the window stays
    open, so it isn't noticed as a lost window.) Read in memory, in CoreGui's RobloxPromptGui. Returns the (Reconnect,
    Leave) button positions as a dict, or None."""
    import mem_gui
    mb, g = _backend(), mem_gui.gui()
    if mb is None or g is None:
        return None
    core = mb._find_child(mb.data_model, cls="CoreGui")
    prompt = core and mb._find_child(core, name="RobloxPromptGui")
    if not prompt:
        return None
    nodes = [i for _, i in mb._walk(prompt, 12, 1500)]
    if not any(_DISCONNECTED.search(mb._content_text(i) or "") and g.is_shown(i) for i in nodes):
        return None
    pos = {}
    for b in nodes:
        if mb._class_name(b) not in mem_gui.CLICKABLE or not g.is_shown(b):
            continue
        texts = [mb._content_text(b)] + [mb._content_text(c) for _, c in mb._walk(b, 3, 30)]
        word = next((t.strip().lower() for t in texts if t and t.strip().lower() in ("reconnect", "leave")), None)
        geo = g.geom(b)
        if word and geo:
            pos[word] = (geo[0], geo[1])
    return {"reconnect": pos.get("reconnect"), "leave": pos.get("leave")}


def reconnect(game, cfg, log=print):
    """Get out of the Disconnected box: press Reconnect (again every so often while the
    internet is still down), and after a few tries leave and rejoin through the join link.
    True once the game is showing again."""
    log("Disconnected from the game; reconnecting...")
    end = time.time() + 900
    tries = 0
    while time.time() < end:
        box = is_disconnected(game)
        if not box:
            mb = _backend()
            if mb and tries:
                game.wait(10)  # (rejoining: the game is built again in memory)
                mb.reattach(tries=12, force=True)
            return wait_in_game(game, timeout=120, log=log)
        if tries >= 3 and cfg.get("auto_launch") and box.get("leave"):
            log("Reconnect isn't working; leaving and rejoining.")
            game.click(*box["leave"])
            game.park_mouse()
            game.wait(5)
            return False  # the window goes away: recover() starts it again
        if box.get("reconnect"):
            game.click(*box["reconnect"])
            game.park_mouse()
            tries += 1
        for _ in range(25):  # up to ~50s for it to come back
            game.wait(2)
            if not is_disconnected(game):
                break
        else:
            game.wait(10)  # still down (internet off?): wait a bit before pressing it again
    return False


def recover(game, cfg, log=print):
    """The Roblox window went away, or it's showing "Disconnected": get back into the game
    (reconnect / start it again, join, attach to the new window). True when the bot can
    carry on."""
    try:
        if is_disconnected(game) and reconnect(game, cfg, log):
            return True
    except WindowLost:
        pass  # it closed meanwhile: start it again below
    if not cfg.get("auto_launch"):
        return False
    log("Lost the Roblox window.")
    time.sleep(5)
    if not find_roblox():
        if not start_roblox(cfg, log) or not wait_for_window(log=log):
            return False
    time.sleep(5)
    if not game.reattach():
        return False
    wait_in_game(game, log=log)
    if cfg.get("fullscreen"):
        game.ensure_fullscreen(log)
    return True
