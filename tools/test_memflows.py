"""Live test of the converted flows, with the bot's own code: opens the Packs menu, finds a pack's OPEN button (not
clicked), closes the menu, teleports to the fishing spot, and closes any menu; then shows how the buttons were found
(memory or screen). Nothing is opened or bought. Run on the bot PC's desktop with the bot paused.
Usage: python tools/test_memflows.py"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
from game import Game  # noqa: E402
from packs import Packs, close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
p = Packs(g)
t = time.time()
print("close_any_menu:", close_any_menu(g), flush=True)
print("open_menu:", p.open_menu(), f"({time.time() - t:.1f} s)", flush=True)
print("  menu open (memory or screen):", p.menu_is_open(g.frame()), flush=True)
print("  OPEN button for iced:", p.find_open_button("iced"), flush=True)
t = time.time()
p.close_menu()
print("close_menu done", f"({time.time() - t:.1f} s); menu open now:", p.menu_is_open(g.frame()), flush=True)
t = time.time()
print("teleport to fishing:", teleport_to_fishing(g), f"({time.time() - t:.1f} s)", flush=True)
print("buttons found:", mem_gui.stats, flush=True)
