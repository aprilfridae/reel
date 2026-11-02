"""Playtime gifts and the daily spin, read and clicked from memory.

Left side: CardsUI's PlaytimeGiftBtn says "New gifts in" / "12:55:36" while nothing is ready, and "CLAIM GIFT!" when
something is; it opens PlaytimeGifts (a full-screen frame in CardsUI), where each ready tier has a "CLAIM!" button.
Right side: DailyBtn ("Daily", with a "12:55:37" countdown under it once today's spin is used) opens DailyUI: the wheel
(its "SPIN" button in the middle), or the "🎁 DAILY SPIN" box with the streak days and "NEXT SPIN IN ...". A new spin
unlocks at 16:00 local time each day.
"""
import os
import re
import time
from datetime import datetime, timedelta

import mem_gui
from game import HERE
from packs import close_any_menu, close_popup

_TIMER = re.compile(r"\d{1,2}:\d{2}:\d{2}")


def _labels(inst, depth=3):
    """The showing texts under `inst` (its own included)."""
    g = mem_gui.gui()
    if g is None or inst is None:
        return []
    mb = g.mb
    return [t for _, o in mb._walk(inst, depth, 200)
            if mb._class_name(o) in mem_gui.TEXT_CLASSES and (t := (mb._content_text(o) or "").strip())
            and g.is_shown(o)]


def _child(screen, name):
    sg = mem_gui.screen(screen)
    g = mem_gui.gui()
    if sg is None or g is None:
        return None
    return next((o for _, o in g.mb._walk(sg, 4, 4000) if g.mb._name(o) == name), None)


def close_menus(game):
    return close_any_menu(game)


def _close_gifts(game):
    """PlaytimeGifts' own X (a small square button at its top right), else whatever menu is open."""
    g, overlay = mem_gui.gui(), _child("CardsUI", "PlaytimeGifts")
    if g is not None and overlay is not None and g.is_shown(overlay):
        x = mem_gui.close_x(overlay)
        if x is None:
            small = [(geo, b) for _, b in mem_gui.buttons(overlay, depth=3)
                     if (geo := g.geom(b)) and 30 < geo[2] < 70 and abs(geo[2] - geo[3]) < 6 and g.is_shown(b)]
            x = max(small, key=lambda s: s[0][0])[1] if small else None
        if x is not None and mem_gui.click(game, x):
            game.wait(0.6)
            return
    close_any_menu(game)


def gift_ready(game=None, img=None):
    """The CLAIM GIFT button if it says a gift is ready, else None."""
    btn = _child("CardsUI", "PlaytimeGiftBtn")
    if not mem_gui.shown(btn):
        return None
    texts = _labels(btn)
    if any(t.lower().startswith("claim") for t in texts) or (texts and not any(_TIMER.fullmatch(t) for t in texts)):
        return btn  # (says CLAIM, or at least no longer counts down to the next one)
    return None


def claim_gifts(game, log=print):
    """Open Playtime Gifts and press every CLAIM! button. Returns how many."""
    close_popup(game)
    btn = gift_ready(game)
    if btn is None or not mem_gui.click(game, btn):
        return 0
    game.wait(1.2)
    claimed = 0
    for _ in range(12):
        overlay = _child("CardsUI", "PlaytimeGifts")
        if not mem_gui.shown(overlay):
            break
        ready = next((b for t, b in mem_gui.buttons(overlay, depth=4)
                      if re.fullmatch(r"claim!?", (t or " ".join(_labels(b, 1))).strip().lower())  # (not "Claimed")
                      and mem_gui.shown(b)), None)
        if ready is None or not mem_gui.click(game, ready):
            break
        claimed += 1
        game.wait(1.0)
    _close_gifts(game)
    if claimed:
        log(f"Claimed {claimed} playtime gift(s)")
    return claimed


SPIN_UNLOCK_HOUR = 16  # a new daily spin unlocks at 16:00 local time
SPIN_STATE = os.path.join(HERE, "daily_spin_done.txt")


def _spin_period():
    """Which daily-spin window we're in: the date the current 16:00-to-16:00 began."""
    return (datetime.now() - timedelta(hours=SPIN_UNLOCK_HOUR)).date().isoformat()


def _spin_done_this_period():
    try:
        return open(SPIN_STATE).read().strip() == _spin_period()
    except OSError:
        return False


def _mark_spin_done():
    with open(SPIN_STATE, "w") as f:
        f.write(_spin_period())


def _spin_button():
    """The wheel's SPIN button, while the wheel is showing."""
    return mem_gui.button(mem_gui.screen("DailyUI"), "SPIN", depth=8)


def _is_summary():
    """The Daily Spin box with the streak days, today's prize and "NEXT SPIN IN hh:mm:ss"."""
    text = " ".join(_labels(mem_gui.screen("DailyUI"), 8)).upper()
    return _spin_button() is None and any(k in text for k in ("NEXT SPIN", "DAILY SPIN", "COME BACK"))


def _close_daily(game):
    g, sg = mem_gui.gui(), mem_gui.screen("DailyUI")
    if g is not None and sg is not None and g.screen_on("DailyUI"):
        x = mem_gui.button(sg, "X", depth=8)
        if x is not None and mem_gui.click(game, x):
            game.wait(0.6)
            return
    close_any_menu(game)


def daily_spin(game, log=print):
    """Spin the daily wheel once a day (it unlocks at 16:00 local time). The Daily button shows a countdown under its
    name once today's spin is used; when it's ready, the button opens the wheel, and after the spin the Daily Spin box
    with "NEXT SPIN IN ..." comes up. Returns True if it spun."""
    if _spin_done_this_period():
        return False
    close_popup(game)
    daily = _child("CardsUI", "DailyBtn")
    if not mem_gui.shown(daily):
        return False
    if any(_TIMER.fullmatch(t) for t in _labels(daily)):
        _mark_spin_done()  # a countdown under "Daily": already spun
        return False
    if not mem_gui.click(game, daily):
        return False
    spin = None
    for _ in range(5):
        game.wait(0.6)
        spin = _spin_button()
        if spin is not None or _is_summary():
            break
    if spin is None:
        if _is_summary():
            _mark_spin_done()  # nothing to spin
        else:
            log("Clicked Daily but the Daily Spin menu didn't open")
        _close_daily(game)
        return False
    mem_gui.click(game, spin)
    log("Spun the daily wheel")
    for _ in range(20):  # the wheel turns for about 6 seconds, then the prize box shows
        game.wait(1.0)
        if _is_summary():
            break
    _mark_spin_done()
    close_popup(game)
    _close_daily(game)
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
