"""Playtime gifts and the daily spin.

Left side: the rainbow "CLAIM GIFT!" button opens Playtime Gifts, where each ready
tier has a green "CLAIM!" button. If the button only shows a timer, nothing is ready.
Right side: the "Daily" button opens Daily Spin; its big button reads
"NEXT SPIN IN hh:mm:ss" until the next spin unlocks (17:00 local time each day).
Everything is found by reading the screen's text (OCR), so positions don't matter.
"""
import os
import re
import time
from datetime import datetime, timedelta

from game import HERE
from ocr import read_words
from packs import close_any_menu, close_popup


def _words(game, img, box):
    """OCR words inside box (x0, y0, x1, y1 as fractions of the window)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)
    return [(t, x0 + x, y0 + y) for t, x, y in read_words(img[y0:y1, x0:x1])]


def close_menus(game):
    return close_any_menu(game)


_close = close_menus


LEFT_BUTTONS = (0.0, 0.35, 0.12, 0.62)  # left column, around the Claim Gift button
RIGHT_BUTTONS = (0.86, 0.35, 1.0, 0.75)  # right column, around Daily
MIDDLE = (0.15, 0.15, 0.85, 0.85)


def gift_ready(game, img):
    """Position of the CLAIM GIFT button if it says a gift is ready, else None."""
    words = _words(game, img, LEFT_BUTTONS)
    for t, x, y in words:
        if t.upper().startswith("CLAIM"):
            return x, y
    return None


def claim_gifts(game, log=print):
    """Open Playtime Gifts and press every CLAIM! button. Returns how many."""
    close_popup(game)
    img = game.frame()
    spot = gift_ready(game, img)
    if not spot:
        return 0
    game.click(*spot)
    game.park_mouse()
    game.wait(1.2)
    claimed = 0
    for _ in range(12):
        img = game.frame()
        buttons = [(x, y) for t, x, y in _words(game, img, MIDDLE)
                   if re.fullmatch(r"claim!?", t.strip().lower())]  # not "Claimed"
        if not buttons:
            break
        game.click(*buttons[0])
        game.park_mouse()
        claimed += 1
        game.wait(1.0)
    _close(game)
    if claimed:
        log(f"Claimed {claimed} playtime gift(s)")
    return claimed


SPIN_UNLOCK_HOUR = 17  # a new daily spin unlocks at 17:00 local time
SPIN_STATE = os.path.join(HERE, "daily_spin_done.txt")


def _spin_period():
    """Which daily-spin window we're in: the date the current 17:00-to-17:00 began."""
    return (datetime.now() - timedelta(hours=SPIN_UNLOCK_HOUR)).date().isoformat()


def _spin_done_this_period():
    try:
        return open(SPIN_STATE).read().strip() == _spin_period()
    except OSError:
        return False


def _mark_spin_done():
    with open(SPIN_STATE, "w") as f:
        f.write(_spin_period())


def daily_spin(game, log=print):
    """Spin the daily wheel once per day (after 17:00). Opens the Daily menu and
    reads its big button: "NEXT SPIN IN ..." means today's is already used.
    Returns True if it spun."""
    if _spin_done_this_period():
        return False
    close_popup(game)
    img = game.frame()
    daily = [(x, y) for t, x, y in _words(game, img, RIGHT_BUTTONS) if t.lower().startswith("daily")]
    if not daily:
        return False
    game.click(*daily[0])
    game.park_mouse()
    game.wait(1.2)
    words = _words(game, game.frame(), MIDDLE)
    text = " ".join(w[0] for w in words).upper()
    if "DAILY" not in text:
        log("Clicked Daily but the Daily Spin menu didn't open")
        _close(game)
        return False
    if "NEXT SPIN" in text or "ALREADY CLAIMED" in text:
        _mark_spin_done()
        _close(game)
        return False
    # The big spin button is the lowest "SPIN" on the menu (the title also says SPIN)
    spin = sorted(((x, y) for t, x, y in words if "SPIN" in t.upper()), key=lambda p: p[1])
    if len(spin) < 2:
        log(f"Daily Spin is ready but its button wasn't found (read: {text[:100]!r})")
        _close(game)
        return False
    game.click(*spin[-1])
    game.park_mouse()
    log("Spun the daily wheel")
    game.wait(8)  # let the wheel finish
    _mark_spin_done()
    close_popup(game)
    _close(game)
    return True


class Chores:
    """Checks for gifts and the daily spin every few minutes (between catches)."""

    def __init__(self, game, every=300, log=print):
        self.game, self.every, self.log = game, every, log
        self.last = 0.0

    def due(self):
        return time.time() - self.last > self.every

    def run(self):
        self.last = time.time()
        claim_gifts(self.game, self.log)
        daily_spin(self.game, self.log)
