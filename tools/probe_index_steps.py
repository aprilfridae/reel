"""Scrolls one Index tab from the top and prints, per step, which rows have their card filled in and each card's
name/serial, plus the full texts of the first few filled cards. Bot must be stopped.
Usage: python tools/probe_index_steps.py [rarity] [notches]"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import index_check  # noqa: E402
import mem_gui  # noqa: E402
import mem_market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

rarity = sys.argv[1] if len(sys.argv) > 1 else "radiation"
notches = int(sys.argv[2]) if len(sys.argv) > 2 else 3
g = Game()
ix = index_check.Index(g)
mb, gui = ix.mb, ix.gui
close_any_menu(g)
hit = mem_gui.locate(text="Index", screen="CardsUI")
g.click(hit[0], hit[1])
g.park_mouse()
g.wait(2)
ix.ensure_serial_sort()
main = next((m for m in index_check.SUBTAB_BARS if rarity in dict(ix.subtabs(m))), None)
if main:
    ix.main_tab(main)
    ix._settle(1.2)
    ix._click(dict(ix.subtabs(main))[rarity])
else:
    ix.main_tab(next(m for m in index_check.MAIN_TABS if index_check._key(m) == rarity))
ix._settle(1.2)
g.wait(0.5)
gb = gui.geom(ix.grid())
print("grid", gb, flush=True)
g.scroll(gb[0], gb[1], 30, check=False)
ix._settle()

dumped = 0
for step in range(8):
    grid = ix.grid()
    rows = {}
    raw = []
    for tile in mb._children(grid):
        if mb._class_name(tile) != "Frame":
            continue
        geo = gui.geom(tile)
        if geo and geo[2] > 20:
            raw.append((geo, tile))
    w, h = raw[0][0][2], raw[0][0][3]
    x0, y0 = min(q[0] for q, _ in raw), min(q[1] for q, _ in raw)
    for geo, tile in raw:
        slot = (round((geo[1] - y0) / (h + 4)), round((geo[0] - x0) / (w + 4)))
        card = mb._find_child(tile, name="Card")
        if card is None:
            continue
        texts = mem_market._texts(mb, card, depth=8)
        f = mem_market.parse(texts) if texts else {}
        rows.setdefault(slot[0], []).append((slot[1], f.get("name"), f.get("serial")))
        if dumped < 6 and texts:
            dumped += 1
            print("  CARD", slot, [(t[0], round(t[1]), round(t[2]), t[3], mb._name(t[4])) for t in texts], flush=True)
    print(f"step {step} y0={y0:.0f} first-tile-y={raw[0][0][1]:.0f}", flush=True)
    for r in sorted(rows):
        print("   row", r, sorted(rows[r]), flush=True)
    g.scroll(gb[0], gb[1], -notches, check=False)
    ix._settle(1.0)
close_any_menu(g)
