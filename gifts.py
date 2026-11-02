"""Playtime gifts and the daily spin.

Left side: the rainbow "CLAIM GIFT!" button opens Playtime Gifts, where each ready
tier has a green "CLAIM!" button. If the button only shows a timer, nothing is ready.
Right side: the "Daily" button opens the spin wheel (or, once today's is used, the Daily
Spin box with "NEXT SPIN IN hh:mm:ss"); a new spin unlocks at 16:00 local time each day.
The buttons are found in memory (mem_gui) by their text or name, else by reading the screen's text (OCR).
"""
import os
import re
import time
from datetime import datetime, timedelta

import mem_gui
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
    """Position of the CLAIM GIFT button if it says a gift is ready, else None (memory first, then the screen)."""
    mem = mem_gui.locate(text="claim", screen="CardsUI", exact=False)
    if mem and mem[0] < img.shape[1] * 0.2:  # (the left column)
        mem_gui.stats["memory"] += 1
        return mem[0], mem[1]
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
        mem = mem_gui.locate(text="CLAIM!", screen="GiftUI") or mem_gui.locate(text="CLAIM", screen="GiftUI")
        buttons = [(mem[0], mem[1])] if mem else [
            (x, y) for t, x, y in _words(game, img, MIDDLE) if re.fullmatch(r"claim!?", t.strip().lower())]  # not "Claimed"
        if not buttons:
            break
        mem_gui.stats["memory" if mem else "screen"] += 1
        game.click(*buttons[0])
        game.park_mouse()
        claimed += 1
        game.wait(1.0)
    _close(game)
    if claimed:
        log(f"Claimed {claimed} playtime gift(s)")
    return claimed


SPIN_UNLOCK_HOUR = 16  # a new daily spin unlocks at 16:00 local time
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


_TIMER = re.compile(r"\d{1,2}:\d{2}:\d{2}")


def _menu_text(game):
    return " ".join(w[0] for w in _words(game, game.frame(), MIDDLE)).upper()


def _is_wheel(text):
    """The wheel screen ("DAY 5 SPIN", "12 prizes", "jackpot", "Streak rewards")."""
    return any(k in text for k in ("PRIZES", "JACKPOT", "STREAK REWARDS")) and "NEXT SPIN" not in text


def _is_summary(text):
    """The Daily Spin box with the streak days, today's prize and "NEXT SPIN IN hh:mm:ss"."""
    return "NEXT SPIN" in text or "DAILY SPIN" in text or "COME BACK" in text


def daily_spin(game, log=print):
    """Spin the daily wheel once a day (it unlocks at 16:00 local time). The Daily button
    shows a timer under its name once today's spin is used. When it's ready, the button
    opens the wheel: its green SPIN button is in the wheel's centre (OCR can't read it
    reliably, it pulses), and after the spin the Daily Spin box with "NEXT SPIN IN ..."
    comes up. Returns True if it spun."""
    if _spin_done_this_period():
        return False
    close_popup(game)
    img = game.frame()
    words = _words(game, img, RIGHT_BUTTONS)
    daily = [(x, y) for t, x, y in words if t.lower().startswith("daily")]
    if not daily:
        return False
    if any(_TIMER.fullmatch(t) and abs(y - daily[0][1]) < 60 for t, x, y in words):
        _mark_spin_done()  # a countdown under "Daily": already spun
        return False
    mem = mem_gui.locate(name="DailyBtn", screen="CardsUI")
    mem_gui.stats["memory" if mem else "screen"] += 1
    game.click(*((mem[0], mem[1]) if mem else daily[0]))
    game.park_mouse()
    text = ""
    for _ in range(5):
        game.wait(0.6)
        text = _menu_text(game)
        if _is_wheel(text) or _is_summary(text):
            break
    if _is_summary(text):
        _mark_spin_done()  # nothing to spin
        _close(game)
        return False
    if not _is_wheel(text):
        log(f"Clicked Daily but the Daily Spin menu didn't open (read: {text[:80]!r})")
        _close(game)
        return False
    h, w = game.frame().shape[:2]
    game.click(w // 2, h // 2)
    game.park_mouse()
    log("Spun the daily wheel")
    for _ in range(20):  # the wheel turns for about 6 seconds, then the prize box shows
        game.wait(1.0)
        if _is_summary(_menu_text(game)):
            break
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
