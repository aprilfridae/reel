"""Opening Roblox and joining the game.

Roblox registers a roblox:// link on Windows, so opening
  roblox://experiences/start?placeId=<id>
starts the player (logged in as whoever is signed in to Roblox on this PC) and joins that
game. A server can be picked with "gameInstanceId=<job id>" (config.json: server_id).
The player has to be signed in already; this never touches a password.
"""
import os
import time

from game import find_roblox


def join_url(cfg):
    url = f"roblox://experiences/start?placeId={int(cfg['place_id'])}"
    if cfg.get("server_id"):
        url += f"&gameInstanceId={cfg['server_id']}"
    return url


def in_game(game):
    """True once the game's own screen is up (its Packs button is showing)."""
    try:
        return game.find("packs_button", game.frame(), 0.7) is not None
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


def recover(game, cfg, log=print):
    """The Roblox window went away: start it again, join, and attach to the new window.
    True when the bot can carry on."""
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
    return True
