"""Keeps the pictures the bot saves from piling up on the disk. Run at start-up and every few hours.

Each kind of picture keeps only its newest N (and nothing older than a few days where that makes sense); the website's
#1 card pictures are kept as long as the website lists them.
"""
import glob
import os
import time

import webstate
from paths import APP

DAY = 86400
# (folder, pattern, keep newest, max age in days or None)
RULES = [
    ("", "stuck_*.jpg", 20, 7),  # fish the vision couldn't find
    ("", "reel_*_*.png", 30, 3),  # reel pictures (only with --log-reels)
    ("", "scan_page_*.jpg", 60, 3),  # market pages from the last scans
    ("", "market_fail_*.png", 3, 7),
    ("serial_glyphs", "*.png", 200, 14),  # badge digits the market reader didn't know
    ("reveals", "*.png", 100, 14),  # event pack reveals with Blood / Eclipse cards
    ("number1s", "*.png", 60, 14),  # Index screenshots of #1s
    ("meteor_debug", "*.jpg", 50, 3),
    ("trade_digits", "*.png", 400, None),  # digits learned from the trade window (small)
    (os.path.join("web", "static", "packs"), "*.jpg", 150, 7),  # pack reveal pictures for the pack log
    (os.path.join("web", "static", "cards"), "*.jpg", 120, 3),  # market card pictures
    (os.path.join("web", "static", "mine"), "*.jpg", 30, 3),
    (os.path.join("web", "static", "outbid"), "*.jpg", 50, 14),  # "you were outbid" notices
    (os.path.join("web", "static", "tcards"), "*.jpg", 400, 7),  # card tiles read in the trade window
]


def _purge(folder, pattern, keep, max_days, protect=()):
    files = sorted(glob.glob(os.path.join(APP, folder, pattern)), key=os.path.getmtime, reverse=True)
    now, removed, freed = time.time(), 0, 0
    for i, f in enumerate(files):
        if os.path.basename(f) in protect:
            continue
        old = max_days is not None and now - os.path.getmtime(f) > max_days * DAY
        if i >= keep or old:
            try:
                freed += os.path.getsize(f)
                os.remove(f)
                removed += 1
            except OSError:
                pass
    return removed, freed


def run(log=print):
    """Delete the old pictures. Returns (files removed, bytes freed)."""
    total, freed = 0, 0
    for folder, pattern, keep, days in RULES:
        protect = ()
        if folder.endswith("cards"):  # pictures the current market list still shows
            protect = {c.get("image") for c in webstate.load("market.json", {}).get("cards", []) if c.get("image")}
        n, b = _purge(folder, pattern, keep, days, protect)
        total, freed = total + n, freed + b
    # the website's #1 pictures: only those no longer listed (and a day old, so one being written isn't taken)
    listed = {e.get("image") for e in webstate.load("ones.json", []) if e.get("image")}
    for f in glob.glob(os.path.join(APP, "web", "static", "ones", "*.jpg")):
        if os.path.basename(f) not in listed and time.time() - os.path.getmtime(f) > DAY:
            try:
                freed += os.path.getsize(f)
                os.remove(f)
                total += 1
            except OSError:
                pass
    if total:
        log(f"Cleaned up {total} old picture(s), {freed / 1e6:.1f} MB")
    return total, freed
