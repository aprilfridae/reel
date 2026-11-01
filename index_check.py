"""Record your #1s from the Index, for every rarity except the common ones.

Each Index tab, sorted by serial, lists the cards you own with the lowest serials first,
each with its serial badge (#1 is rainbow). This visits every tab and sub-tab, pages
through it, and saves each #1 card (once) to the website's collection (see ones.py).

  python index_check.py      (or called by bot.py after each event)

Tabs: Rarities (Common ... Iced), Event (Molten ... Atlantis, and any new ones), Ultra,
Alt Covers, Supporter. Sub-tab names are read off the screen, so new event rarities
are picked up by themselves.
"""
import json
import os
import re
import time
from datetime import datetime
from difflib import SequenceMatcher

import cv2
import numpy as np

import ones
from game import HERE, StopBot, Game
from ocr import read_words
from packs import close_any_menu, close_popup

RECORDS_DIR = os.path.join(HERE, "number1s")

# The rarities left out (the author's list). "Uncommon" is NOT on it, so it is tracked.
EXCLUDED = ("common", "rare", "epic", "legendary", "mythic")
ALSO_KNOWN = ("uncommon",)  # looks a lot like "common": listed so it isn't mistaken for it

# Index layout, as offsets in UI pixels from the window center (measured on a
# 1920x1009 window at UI scale 1; the Index panel is centered)
TAB_Y = -272
MAIN_TABS = {"rarities": -264, "event": -92, "ultra": 84, "alt_covers": 258, "supporter": 434}
HAS_SUBTABS = {"rarities", "event"}
SUBTAB_BAND = (-530, -250, 540, -216)  # x0, y0, x1, y1 where the sub-tab names are
SUBTAB_Y = -232
SORT_BUTTON = (160, -337)
SORT_LOWEST_SERIAL = (93, -7)
CLOSE = (505, -337)
GRID_X = (-535, 400)
GRID_BOTTOM = 360
# Top edge of the card grid: lower on tabs that have a row of sub-tabs
GRID_TOP = {True: -154, False: -199}  # with / without sub-tabs
INDEX_BELOW_PACKS = 68  # the Index button sits this far below the Packs button
MAX_PAGES = 6  # scroll positions looked at per tab (10 cards fit on screen at once)


def is_excluded(name):
    """Is this sub-tab one of the excluded rarities? Matched loosely, since OCR garbles
    names a little, but "uncommon" must never be taken for "common"."""
    best, score = max(((n, SequenceMatcher(None, name, n).ratio()) for n in EXCLUDED + ALSO_KNOWN),
                      key=lambda pair: pair[1])
    return best in EXCLUDED and score >= 0.6


EARLY_STOP = True  # stop paging a tab at the first page with no new #1 (they come first, sorted by serial)
FRAMES_PER_PAGE = 3  # looks at each scroll position: sparkles can hide a badge in one frame
FRAME_GAP = 0.12  # seconds between those looks


def _detect_page(game, s, rows):
    """The #1 cards on screen now, from a few frames a moment apart (a badge can be
    missed in a single frame). Returns (first frame, [[crop, (x, y), score], ...])."""
    first, found = None, []
    ones.CUT_SEEN = 0
    for k in range(FRAMES_PER_PAGE):
        img = game.frame()
        first = img if first is None else first
        crops = ones.card_crops(img, s, rows)
        ones.CUT_SEEN = max(ones.CUT_SEEN, ones.LAST_CUT)
        for crop, (x, y), score in crops:
            for f in found:
                if abs(f[1][0] - x) <= 15 and abs(f[1][1] - y) <= 15:
                    if score > f[2]:  # the same card: keep its best-looking frame
                        f[0], f[1], f[2] = crop, (x, y), score
                    break
            else:
                found.append([crop, (x, y), score])
        if k + 1 < FRAMES_PER_PAGE:
            game.wait(FRAME_GAP)
    return first, found


def _same_view(prev_img, img, box):
    """Is the card grid showing the same thing in both pictures (so it didn't scroll)?
    Compared coarsely, so animated sparkles don't count as a change."""
    x0, y0, x1, y1 = box
    small = lambda im: cv2.GaussianBlur(cv2.cvtColor(cv2.resize(im[y0:y1, x0:x1], (64, 40)),
                                                     cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(int)
    return float(np.abs(small(prev_img) - small(img)).mean()) < 4


def _scrolled(prev_img, img, box):
    """How many pixels the card grid moved up between two screenshots, or None if that
    can't be told. Takes the most detailed strip of the earlier picture and finds it in
    the later one."""
    x0, y0, x1, y1 = box
    blur = lambda im: cv2.GaussianBlur(cv2.cvtColor(im[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (5, 5), 0)
    a, b = blur(prev_img), blur(img)
    strip = 80
    top = max(range(0, a.shape[0] - strip, 20), key=lambda t: float(a[t:t + strip].std()))
    _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(b, a[top:top + strip], cv2.TM_CCOEFF_NORMED))
    return top - loc[1] if score >= 0.5 else None


def _settle(game, box, maxwait=1.2, first=0.15):
    """Wait only as long as the card grid is still changing (a tab switching, the list
    scrolling), instead of a fixed pause: returns as soon as two looks 0.12s apart agree."""
    game.wait(first)
    prev = game.frame()
    end = time.time() + maxwait
    while time.time() < end:
        game.wait(0.12)
        cur = game.frame()
        if _same_view(prev, cur, box):
            return cur
        prev = cur
    return prev


def _collect_ones(game, rarity, s, box, found_at, log=print):
    """Page through the open tab (sorted by serial) and add its #1 cards to the website's
    collection. Each card is counted once however many pages it shows on, by its place
    in the scrolling grid (the scroll distance is measured). Returns how many #1 cards
    the tab has.

    The tab is sorted by lowest serial, so its #1 cards are all at the start: as soon as a
    page shows no new #1 card, there are no more, and the rest isn't looked at."""
    x0, y0, x1, y1 = box
    mid = ((x0 + x1) / 2, (y0 + y1) / 2)
    distinct, prev, scrolled = [], None, 0  # distinct: [crop, x, y in the whole list]
    for page in range(MAX_PAGES):
        first, cards = _detect_page(game, s, (y0, y1))
        if page == 0 and not cards:  # nothing on the first look: make sure it wasn't still loading
            _settle(game, box, 0.8, 0.3)
            first, cards = _detect_page(game, s, (y0, y1))
        before = len(distinct)
        if prev is not None:
            if _same_view(prev, first, box):
                break  # it didn't move: that was the last page
            moved = _scrolled(prev, first, box)
            if moved is None:
                if len(distinct) >= 8:  # a nearly empty tab has nothing to track: not worth a warning
                    log(f"Index check: lost track of the scrolling in the {rarity} tab; "
                        f"using the {len(distinct)} #1 card(s) seen so far.")
                break
            if moved < 3:
                break  # it didn't move: that was the last page
            scrolled += moved
        for crop, (x, y), _ in cards:
            if not any(abs(d[1] - x) <= 18 and abs(d[2] - (y + scrolled)) <= 18 for d in distinct):
                distinct.append([crop, x, y + scrolled])
        # (a #1 whose card is cut off at the bottom of the grid isn't counted yet, but it
        # means there's more to see further down)
        if EARLY_STOP and len(distinct) == before and not getattr(ones, "CUT_SEEN", 0):
            break  # no new #1 on this page: sorted by serial, so there are none further down
        prev = first
        if not game.scroll(*mid, -2, check=False):  # (the Index was checked to be open at the start)
            break
        _settle(game, box, 0.9, 0.15)
    if prev is not None:  # only scroll back if it was scrolled at all
        game.scroll(*mid, 15, check=False)  # back to the top
    ones.add_cards(rarity, [d[0] for d in distinct], found_at, log=log)
    return len(distinct)


# Sub-tab names in the order they appear. Used to give OCR'd names their right spelling
# (so one rarity is never stored under two names) and to fill in a tab OCR missed.
KNOWN_SUBTABS = {
    "rarities": ["common", "uncommon", "rare", "epic", "legendary", "mythic", "secret",
                 "glitched", "kawaii", "radiation", "iced"],
    "event": ["molten", "charged", "tidal", "spooky", "acid", "meteor", "eclipse", "blood", "atlantis"],
}


def _canonical(name, known):
    """The known name this OCR'd name is closest to (if close enough), else itself."""
    best = max(known, key=lambda k: SequenceMatcher(None, name, k).ratio())
    return best if SequenceMatcher(None, name, best).ratio() >= 0.6 else name


def _subtabs(game, at, main="event"):
    """[(name, x)] for the sub-tabs showing now, left to right. Names are read off the
    screen and snapped to the known spelling; a tab OCR missed is filled in from the
    even spacing of the tabs (and named by its place in the known order)."""
    img = game.frame()
    x0, y0 = (int(v) for v in at(SUBTAB_BAND[:2]))
    x1, y1 = (int(v) for v in at(SUBTAB_BAND[2:]))
    known = KNOWN_SUBTABS.get(main, [])
    found = []
    for text, x, y in read_words(img[y0:y1, x0:x1], scale=2):
        name = re.sub(r"[^a-z]", "", text.lower())
        if len(name) >= 3:
            found.append((_canonical(name, known) if known else name, x0 + x))
    found.sort(key=lambda item: item[1])
    if len(found) < 3:
        return found
    # Fill gaps: a gap of ~2 tab widths between neighbours means one was missed
    pitch = float(np.median(np.diff([x for _, x in found])))
    filled = []
    for i, (name, x) in enumerate(found):
        filled.append((name, x))
        if i + 1 < len(found):
            gap = found[i + 1][1] - x
            k = int(round(gap / pitch))
            filled += [(None, x + gap * j / k) for j in range(1, k)]
    # Name the gaps by their place in the known order when the count matches
    if known and len(filled) == len(known):
        filled = [(name or known[i], x) for i, (name, x) in enumerate(filled)]
    else:
        filled = [(name or f"{main}_tab{i + 1}", x) for i, (name, x) in enumerate(filled)]
    return filled


def _ensure_serial_sort(game, at):
    """Sort every tab by serial (the setting is shared by all tabs)."""
    img = game.frame()
    x0, y0 = (int(v) for v in at((SORT_BUTTON[0] - 120, SORT_BUTTON[1] - 20)))
    x1, y1 = (int(v) for v in at((SORT_BUTTON[0] + 120, SORT_BUTTON[1] + 20)))
    label = " ".join(t for t, _, _ in read_words(img[y0:y1, x0:x1], scale=2)).lower()
    if "serial" in label:
        return
    game.click(*at(SORT_BUTTON))
    game.wait(0.6)
    game.click(*at(SORT_LOWEST_SERIAL))
    game.park_mouse()
    game.wait(1.5)


def snapshot(game, log=print, should_stop=lambda: False):
    """Open the Index and go through every tab except the excluded rarities, saving each
    #1 card (once) to the website's collection. Stops early (between tabs) if
    should_stop() says so, e.g. a bid/buy is waiting.
    Returns ({rarity: #1 cards seen}, finished)."""
    g = game
    finished = True
    close_popup(g)
    close_any_menu(g)
    img = g.frame()
    s = g.ui_scale(img)
    h, w = img.shape[:2]
    at = lambda off: (w / 2 + off[0] * s, h / 2 + off[1] * s)

    packs = g.find("packs_button", img)
    if not packs:
        log("Index check: couldn't find the Packs/Index buttons.")
        return {}, False
    g.click(packs[0], packs[1] + INDEX_BELOW_PACKS * s)
    g.wait(1.2)
    if not g.menu_open():
        g.wait(1.0)
        if not g.menu_open():
            log("Index check: the Index didn't open.")
            return {}, False

    os.makedirs(RECORDS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M")
    counts, skipped = {}, []
    last_file = os.path.join(RECORDS_DIR, "last_counts.json")
    try:
        with open(last_file) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = {}
    x0, x1 = (int(at((GRID_X[0], 0))[0]), int(at((GRID_X[1], 0))[0]))
    try:
        _ensure_serial_sort(g, at)
        for main, xoff in MAIN_TABS.items():
            if should_stop():
                finished = False
                break
            g.click(*at((xoff, TAB_Y)))
            g.park_mouse()
            _settle(g, (x0, int(at((0, GRID_TOP[True]))[1]), x1, int(at((0, GRID_BOTTOM))[1])), 1.2, 0.25)
            if main in HAS_SUBTABS:
                tabs = _subtabs(g, at, main)
                known = KNOWN_SUBTABS[main]
                if len(tabs) != len(known):
                    log(f"Index check: {main} has {len(tabs)} sub-tabs ({[n for n, _ in tabs]}), "
                        f"expected {len(known)}; going with what was read.")
                if len(tabs) < 3:
                    log(f"Index check: couldn't read the {main} sub-tabs ({[n for n, _ in tabs]}); skipping it.")
                    continue
                todo = [(name, x) for name, x in tabs if not is_excluded(name)]
                skipped += [name for name, _ in tabs if is_excluded(name)]
            else:
                todo = [(main, None)]
            for name, x in todo:
                if should_stop():
                    finished = False
                    break
                top = int(at((0, GRID_TOP[main in HAS_SUBTABS]))[1])
                box = (x0, top, x1, int(at((0, GRID_BOTTOM))[1]))
                if x is not None:
                    g.click(x, at((0, SUBTAB_Y))[1])
                    g.park_mouse()
                    _settle(g, box, 1.2, 0.25)
                if name == todo[0][0] and main == "event":  # one full screenshot for the record
                    cv2.imwrite(os.path.join(RECORDS_DIR, f"{stamp} {main}.png"), g.frame())
                when = datetime.now().strftime("%Y-%m-%d %H:%M")
                counts[name] = _collect_ones(g, name, s, box, when, log)
                if counts[name] < last.get(name, 0):
                    # fewer than last time: a badge may have been hidden by a sparkle in every
                    # frame, so look at this tab once more (a card really gone shows up the
                    # same way again, and then the lower number is remembered)
                    counts[name] = max(counts[name], _collect_ones(g, name, s, box, when, log))
    finally:
        try:
            g.click(*at(CLOSE))
            g.wait(0.8)
            close_any_menu(g)
        except StopBot:
            raise

    if finished:  # (a sweep cut short has no numbers for the tabs it never reached)
        with open(last_file, "w") as f:
            json.dump(counts, f)
    total = sum(counts.values())
    with open(os.path.join(RECORDS_DIR, "sweeps.csv"), "a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write("time,total_number1s,by_rarity\n")
        f.write(f"{stamp},{total},\"{counts}\"\n")
    shown = ", ".join(f"{n.replace('_', ' ')} {c}" for n, c in counts.items() if c) or "none"
    log(f"#1s in the Index ({len(counts)} tabs{'' if finished else ', stopped early'}, "
        f"skipped {', '.join(skipped) or 'nothing'}): {shown}")
    return counts, finished


if __name__ == "__main__":
    game = Game()
    try:
        snapshot(game)
    except StopBot:
        pass
    finally:
        game.release_all()
