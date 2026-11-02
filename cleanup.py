"""Clears away the screenshots older versions of the bot saved (it reads the game from memory now and saves none).
Run at start-up and every few hours.

The cards' artwork (web/static/art, see card_art.py) is what the website draws cards from, and is kept.
"""
import glob
import os

from paths import APP

STATIC = os.path.join("web", "static")
OLD_PICTURES = [
    ("", "stuck_*.jpg"), ("", "reel_*_*.png"), ("", "scan_page_*.jpg"), ("", "market_fail_*.png"),
    ("", "atlantis_popup*.png"), ("serial_glyphs", "*.png"), ("reveals", "*.png"), ("number1s", "*.png"),
    ("trade_digits", "*.png"), (os.path.join(STATIC, "packs"), "*.jpg"), (os.path.join(STATIC, "cards"), "*.jpg"),
    (os.path.join(STATIC, "mine"), "*.jpg"), (os.path.join(STATIC, "outbid"), "*.jpg"),
    (os.path.join(STATIC, "tcards"), "*.jpg"), (os.path.join(STATIC, "ones"), "*.jpg"), (STATIC, "trade.jpg"),
]


def run(log=print):
    """Delete the old screenshots. Returns (files removed, bytes freed)."""
    total, freed = 0, 0
    for folder, pattern in OLD_PICTURES:
        for f in glob.glob(os.path.join(APP, folder, pattern)):
            try:
                size = os.path.getsize(f)
                os.remove(f)
                total, freed = total + 1, freed + size
            except OSError:
                pass
    if total:
        log(f"Cleaned up {total} old screenshot(s), {freed / 1e6:.1f} MB")
    return total, freed
