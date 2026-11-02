"""Walks to the Card Market and opens it (the bot's own code), then prints what is showing in MarketUI on the Browse
tab, the My Listings tab and the Who owns? tab (class, name, text, centre, size, path), closes the market and goes back
to fishing. No bid, buy or search. Run on the bot PC's desktop with the bot paused. Usage: python tools/dump_market.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
import market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
gui = mem_gui.gui()
mb = gui.mb


def dump(title, limit=260):
    print(f"===== {title}", flush=True)
    sg = next(s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI")
    n = 0
    for d, inst in mb._walk(sg, depth=18, max_nodes=8000):
        cls = mb._class_name(inst)
        if cls not in ("TextLabel", "TextButton", "TextBox", "ImageButton", "ScrollingFrame"):
            continue
        geo = gui._ok(inst)
        if not geo:
            continue
        txt = mb._content_text(inst) if cls in ("TextLabel", "TextButton", "TextBox") else None
        path, node = [], mb._parent(inst)
        for _ in range(3):
            if node is None:
                break
            path.append(str(mb._name(node)))
            node = mb._parent(node)
        print(f"{cls:13} {str(mb._name(inst))[:18]:18} {repr((txt or '')[:30]):34} ({geo[0]:.0f},{geo[1]:.0f}) "
              f"{geo[2]:.0f}x{geo[3]:.0f}  <- {'/'.join(reversed(path))}", flush=True)
        n += 1
        if n >= limit:
            print("...", flush=True)
            break


print("go to market:", market.go_to_market(g), flush=True)
g.wait(2)
dump("BROWSE")
for tab, title in (("My Listings", "MY LISTINGS"), ("Who owns", "WHO OWNS")):
    hit = mem_gui.locate(text=tab, screen="MarketUI", contains=True)
    print(f"tab {tab!r} at {hit}", flush=True)
    if hit:
        g.click(hit[0], hit[1])
        g.park_mouse()
        g.wait(2.5)
        dump(title, limit=120)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
