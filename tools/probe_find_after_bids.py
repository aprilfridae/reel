"""Why the Browse tab doesn't come back after a scan and My Bids: loads the whole list (as a scan does), reads My
Bids, then prints what memory says the Browse tab is and saves the screen before and after clicking it
(tools/fab_before.png, fab_after.png). No bid is placed. Walks to the market and back to fishing.
Usage: python tools/probe_find_after_bids.py"""
import os
import sys

import cv2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import market_scan as ms  # noqa: E402
import mem_gui  # noqa: E402
import mybids  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
g = Game()
print("go to market:", market.go_to_market(g), flush=True)
cards = ms._load_all(g, ms._grid_mid(g), lambda cs: False)
print("loaded:", cards and len(cards), flush=True)
print("my bids:", bool(mybids.read_my_bids(g, log=print)), flush=True)
gui = mem_gui.gui()
mb = gui.mb
sg = next(s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI")
for d, o in mb._walk(sg, depth=14, max_nodes=8000):
    if mb._class_name(o) in ("TextLabel", "TextButton"):
        t = mb._content_text(o) or ""
        if "browse" in t.lower() or "listin" in t.lower() or "request" in t.lower():
            print(f"  {t!r} {mb._class_name(o)} {mb._name(o)!r} shown={gui.is_shown(o)} geo={gui.geom(o)}", flush=True)
tab = mem_gui.locate(text="Browse", screen="MarketUI", contains=True)
print("Browse tab at", tab, flush=True)
cv2.imwrite(os.path.join(HERE, "fab_before.png"), g.frame())
if tab:
    g.click(tab[0], tab[1])
    g.park_mouse()
    g.wait(1.5)
cv2.imwrite(os.path.join(HERE, "fab_after.png"), g.frame())
print("chips:", mem_gui.locate(text="Rarities", screen="MarketUI", exact=False),
      mem_gui.locate(text="Ultra", screen="MarketUI", exact=False), flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
