"""From the market's Requests tab, click Browse and save what the screen shows (tools/after_browse.png), to see why
the tab doesn't switch. Walks to the market and back to fishing. Usage: python tools/probe_names_tabs.py"""
import os
import sys

import cv2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import mem_gui  # noqa: E402
import mybids  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
g = Game()
print("go to market:", market.go_to_market(g), flush=True)
print("Requests tab:", mybids._open_tab(g, "Requests"), flush=True)
cv2.imwrite(os.path.join(HERE, "on_requests.png"), g.frame())
tab = mem_gui.locate(text="Browse", screen="MarketUI", contains=True)
print("Browse tab at", tab, flush=True)
g.click(tab[0], tab[1])
g.park_mouse()
g.wait(1.5)
cv2.imwrite(os.path.join(HERE, "after_browse.png"), g.frame())
print("Ultra showing now:", mem_gui.showing("MarketUI", text="Ultra"), flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
