"""Prints the first tiles of one Index tab as memory has them (slot, size, card fields, shown), before and after a
scroll. Bot must be stopped. Usage: python tools/probe_index_tiles.py [rarity]"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import index_check  # noqa: E402
import mem_gui  # noqa: E402
import mem_market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

rarity = sys.argv[1] if len(sys.argv) > 1 else "atlantis"
g = Game()
ix = index_check.Index(g)
mb, gui = ix.mb, ix.gui
close_any_menu(g)
hit = mem_gui.locate(text="Index", screen="CardsUI")
g.click(hit[0], hit[1])
g.park_mouse()
g.wait(2)
main = next(m for m in index_check.SUBTAB_BARS if rarity in dict(ix.subtabs(m)))
ix.main_tab(main)
ix._settle(1.2)
ix._click(dict(ix.subtabs(main))[rarity])
ix._settle(1.2)
g.wait(0.5)


def show(tag):
    grid = ix.grid()
    rows = []
    for tile in mb._children(grid):
        geo = gui.geom(tile)
        cls = mb._class_name(tile)
        card = mb._find_child(tile, name="Card")
        texts = mem_market._texts(mb, tile, depth=9)
        rows.append((geo[1] if geo else 0, geo[0] if geo else 0, cls, mb._name(tile), geo, gui.is_shown(tile),
                     card is not None, [t[0] for t in texts][:8]))
    rows.sort()
    print(f"==== {tag}: {len(rows)} children", flush=True)
    for r in rows[:40]:
        geo = r[4]
        print(f"  {r[2]:<14} {r[3]!r:<10} ({geo[0]:.0f},{geo[1]:.0f} {geo[2]:.0f}x{geo[3]:.0f}) shown={r[5]} card={r[6]} {r[7]}"
              if geo else f"  {r[2]} {r[3]!r} nogeo", flush=True)


show("top")
gb = gui.geom(ix.grid())
g.scroll(gb[0], gb[1], -3, check=False)
ix._settle(1.0)
show("after scroll -3")
close_any_menu(g)
