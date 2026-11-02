"""Live test of reading My Bids (My Listings + Requests tabs) twice, timed. Walks to the market and back to fishing.
Usage: python tools/test_mybids_live.py"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import mybids  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
print("go to market:", market.go_to_market(g), flush=True)
for _ in range(2):
    t = time.time()
    info = mybids.read_my_bids(g, log=print)
    print(f"my bids in {time.time() - t:.1f} s:", info and {k: info[k] for k in ("winning", "selling", "requests")}, flush=True)
    print("browse tab after:", market.ensure_browse_tab(g), flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
