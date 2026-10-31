"""The website's "My #1s" collection: every #1 card ever found in the Index, for every
tracked rarity, kept for good in web/data/ones.json with a picture of the card in
web/static/ones/.

Cards are cut out of Index screenshots around their rainbow "#1" badge.

Telling a new card from one already stored is the hard part: the same card looks a bit
different every time (sparkles, a few pixels of shift), and OCR reads its name
differently each time, so "is this picture the same as that one?" never has a safe cut-off.
Instead it's done by counting. One sweep sees every #1 of a rarity at once, each counted
once by its position in the scrolling grid (see index_check.py). If that's more than are
stored for the rarity, the difference is new, and the new ones are the cards that match
the stored cards worst (a ranking, which holds up even when the scores are low).
"""
import os
import time

import cv2
import numpy as np

import packs
import webstate
from packs import number_one_hits

from paths import APP as HERE  # noqa: E402
ONES_DIR = os.path.join(HERE, "web", "static", "ones")

# The card relative to its #1 badge's center, at UI scale 1: left, top, width, height
CARD_LEFT, CARD_TOP, CARD_W, CARD_H = -36, -48, 174, 234
ART = (14, 22, 118, 108)  # the artwork inside the crop: x, y, w, h


_SCALE_AT = {}  # UI scale -> the badge template scale that matched there
LAST_CUT = 0  # in the last card_crops call: #1 badges seen whose card is cut off at the bottom


def card_crops(img, s=1.0, rows=None):
    """[(crop, (x, y), score)] for every #1 card whose whole card is on screen; (x, y)
    is where its badge is. rows = (top, bottom) of the area the cards are in: a card cut
    off by that edge is skipped (it's picked up at another scroll position)."""
    global LAST_CUT
    LAST_CUT = 0
    h, w = img.shape[:2]
    top, bottom = rows or (0, h)
    out = []
    # Only the card area is searched (a fraction of the screen), and once the badge size
    # at this UI scale is known only sizes near it are tried: the full search over the
    # whole screen took about a second per picture
    scales = None
    if s in _SCALE_AT:
        b = _SCALE_AT[s]
        scales = [b - 0.1, b, b + 0.1]
    t0 = max(0, int(top - 60 * s))
    hits = [(x, y + t0, sc) for x, y, sc in number_one_hits(img[t0:min(h, int(bottom + 10 * s))], scales=scales)]
    if scales is None and hits and packs.LAST_BEST_SCALE:
        _SCALE_AT[s] = packs.LAST_BEST_SCALE
    for x, y, score in sorted(hits, key=lambda hit: (round(hit[1] / 60), hit[0])):
        x0, y0 = int(x + CARD_LEFT * s), int(y + CARD_TOP * s)
        x1, y1 = x0 + int(CARD_W * s), y0 + int(CARD_H * s)
        if x0 < 0 or x1 > w or y0 < top or y1 > bottom:
            if y1 > bottom and y0 >= top:
                LAST_CUT += 1  # a #1 whose card runs off the bottom: more of the list is below
            continue
        out.append((img[y0:y1, x0:x1].copy(), (int(x), int(y)), float(score)))
    return out


def _clean(crop):
    """The crop with the animated sparkles painted out (tiny, very bright blobs)."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    median = cv2.medianBlur(gray, 9)
    sparkle = (gray > np.minimum(250, median.astype(int) + 60)).astype(np.uint8)
    return cv2.inpaint(crop, cv2.dilate(sparkle, np.ones((5, 5), np.uint8)), 3, cv2.INPAINT_TELEA)


def _edges(crop):
    gray = cv2.GaussianBlur(cv2.medianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 5), (5, 5), 0)
    return cv2.Canny(gray, 40, 110).astype(np.float32)


def similarity(crop_a, crop_b):
    """How alike two crops of a card are, by the outlines in their artwork (sparkles
    removed, a few pixels of shift allowed). Only useful for ranking: the same card can
    score low when it's sparkling, but nearly always scores higher than any other card."""
    ax, ay, aw, ah = ART
    a = _edges(_clean(crop_a)[ay:ay + ah, ax:ax + aw])[8:-8, 8:-8]
    b = _edges(_clean(crop_b)[ay - 8:ay + ah + 8, ax - 8:ax + aw + 8])
    return float(cv2.matchTemplate(b, a, cv2.TM_CCOEFF_NORMED).max())


def fingerprint(crop):
    """256-bit brightness pattern of the card's artwork, as a list of 0/1 (informational)."""
    h = crop.shape[0]
    ax, ay, aw, ah = (int(v * h / CARD_H) for v in ART)
    art = crop[ay:ay + ah, ax:ax + aw]
    small = cv2.resize(cv2.cvtColor(art, cv2.COLOR_BGR2GRAY), (16, 16), interpolation=cv2.INTER_AREA)
    return (small > small.mean()).flatten().astype(int).tolist()


def _picture(entry, cache={}):
    key = entry["image"]
    if key not in cache:
        cache[key] = cv2.imread(os.path.join(ONES_DIR, key))
    return cache[key]


def add_cards(rarity, crops, found_at=None, log=print):
    """`crops` = every #1 card of this rarity currently in the Index, each counted once.
    Adds the ones not stored yet. Returns the new entries."""
    os.makedirs(ONES_DIR, exist_ok=True)
    found_at = found_at or time.strftime("%Y-%m-%d %H:%M")
    new = []

    def update(entries):
        stored = [e for e in entries if e["rarity"] == rarity and _picture(e) is not None]
        extra = len(crops) - len(stored)
        if extra <= 0:
            return entries  # nothing more than is already kept
        # Pair each stored card with its best-matching crop, best matches first; the
        # crops left over are the new ones
        scores = [(similarity(c, _picture(e)), i, j)
                  for i, c in enumerate(crops) for j, e in enumerate(stored)]
        used_crops, used_stored = set(), set()
        for score, i, j in sorted(scores, reverse=True):
            if i not in used_crops and j not in used_stored:
                used_crops.add(i)
                used_stored.add(j)
        for i, crop in enumerate(crops):
            if i in used_crops:
                continue
            file = f"{rarity}_{int(time.time() * 1000)}_{len(entries)}.jpg"
            cv2.imwrite(os.path.join(ONES_DIR, file), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
            entry = {"id": file[:-4], "rarity": rarity, "image": file, "found_at": found_at,
                     "fp": fingerprint(crop)}
            entries.append(entry)
            new.append(entry)
        return entries

    webstate.update("ones.json", [], update)
    if new:
        log(f"New #1 card(s) for the website: {len(new)} {rarity}")
    return new
