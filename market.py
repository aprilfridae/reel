"""Getting to the Card Market at Spawn.

Teleport to Spawn, then replay a recorded key sequence exactly (ROUTE), and
press E at the "Open Market" prompt. The camera is never moved anywhere in the bot,
so W/A/S/D always point the same way and the recorded walk works as recorded.

Safety: E is only ever pressed when "Open Market" has been read on screen. Spawn
has other E prompts nearby (e.g. a Creator Card pedestal that sells a Robux pack),
so pressing E blindly is never OK here.
"""
import time

import cv2

from game import HERE
from ocr import read_words
from packs import close_any_menu, close_popup, teleport

# A recording from Spawn with the default camera:
# (keys held, seconds held, pause after). Replayed exactly as recorded.
ROUTE = [("aw", 2.356, 0), ("w", 0.200, 0), ("a", 1.532, 0),
         ("aw", 0.754, 0), ("w", 0.400, 0)]


LEG_PAUSE = 0.08  # seconds between legs (the recording had 0.5-2.2s of idle between them)


def _hold(game, keys, seconds):
    for k in keys:
        game.key(k, True)
    time.sleep(seconds)
    for k in keys:
        game.key(k, False)


_game = None


def prompt_position(img, game=None):
    """Where the "[E] Open Market" prompt is, or None. Only this prompt may get an E.
    Matched by picture (scores ~1.0 on the prompt, under 0.55 on anything else)."""
    g = game or _game
    hit = g.find("open_market_prompt", img, 0.85) if g else None
    return (hit[0], hit[1]) if hit else None


def market_open(img):
    """True if the Card Market window is showing."""
    h, w = img.shape[:2]
    text = " ".join(t for t, _, _ in read_words(img[int(h * 0.1):int(h * 0.45), int(w * 0.15):int(w * 0.85)],
                                                scale=2)).lower()
    return "browse" in text and ("listings" in text or "market" in text)


def walk_route(game, until_prompt=True):
    """Replay the route, but only as far as needed: the "Open Market" prompt shows up
    well before the recorded walk ends (the last legs are just the player shuffling along
    the stall), so the walk stops the moment it's on screen. The recorded pauses between
    legs were the recording's, not the game's, so they're cut to a short beat.
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


def go_to_market(game, log=print, attempts=3):
    """Teleport to Spawn, replay the recorded walk, open the market. True if open."""
    for attempt in range(1, attempts + 1):
        close_popup(game)
        close_any_menu(game)
        if not teleport(game, "Spawn", settle=0.6, poll=0.25):
            continue
        walk_route(game)
        if _try_prompt(game):
            return True
        cv2.imwrite(f"{HERE}/market_fail_{attempt}.png", game.frame())
        log(f"Market attempt {attempt} didn't work; " + ("trying again" if attempt < attempts else "giving up"))
    log("Couldn't get the Card Market open.")
    return False
