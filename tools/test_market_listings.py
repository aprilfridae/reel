"""Live test of reading the market's listings from memory, with errors shown: gets to the Browse tab, sets the sort,
then reads the grid step by step. Usage: python tools/test_market_listings.py"""
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import market_scan  # noqa: E402
import mem_gui  # noqa: E402
import mem_market  # noqa: E402
import packs  # noqa: E402
from game import Game  # noqa: E402

game = Game()
if not market.market_open():
    packs.close_popup(game)
    packs.close_any_menu(game)
    print("teleport", packs.teleport(game, "Spawn", settle=0.6, poll=0.25), flush=True)
    print("walk stopped at prompt:", market.walk_route(game), "prompts:", market.prompts(), flush=True)
    print("market opened:", market._try_prompt(game), flush=True)
print("browse tab:", market.ensure_browse_tab(game), "market open:", market.market_open(), flush=True)
print("sort:", market_scan.set_sort_lowest_serial(game), flush=True)
gui = mem_gui.gui()
mb = gui.mb
try:
    grid = mem_market._grid(mb)
    print("grid:", grid and hex(grid), grid and mb._class_name(grid), grid and gui.geom(grid), flush=True)
    n = 0
    for entry, texts in mem_market._entries(mb, grid, lambda ts: any(t[0].upper() == "BID" for t in ts), None):
        n += 1
        if n <= 3:
            print(" entry", hex(entry), [t[0] for t in texts], flush=True)
            bid = next(t for t in texts if t[0].upper() == "BID")
            print("  shown:", gui.is_shown(bid[4]), "card:", mem_market._card_of(mb, gui, entry, texts), flush=True)
    print("entries with BID:", n, flush=True)
    if not n and grid:
        for d, o in mb._walk(grid, 3, 60):
            print("  " * d, mb._class_name(o), mb._name(o), repr(mb._content_text(o))[:40], flush=True)
except Exception:
    traceback.print_exc()
print("listings(shown):", len(mem_market.listings() or []), "all:", len(mem_market.listings(shown_only=False) or []), flush=True)
print("page_cards:", len(market_scan.page_cards(game)), flush=True)
