"""Live test of the converted market code (no bid or buy is placed): walks to the market with the bot's own code,
times reading a page from memory (twice: the second uses the class cache), runs the full scan (sort, pages, Show more,
top bidders from the bid window), then a dry-run bid of 1T on the first listing found (types the amount, checks it,
cancels: never presses PLACE BID), and goes back to fishing. Prints how the buttons were found.
Run on the bot PC's desktop with the bot paused. Usage: python tools/test_market_live.py"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import market_scan  # noqa: E402
import mem_gui  # noqa: E402
import mem_market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
t = time.time()
print("go to market:", market.go_to_market(g), f"({time.time() - t:.0f} s)", flush=True)
for i in range(2):
    t = time.time()
    n = len(mem_market.listings() or [])
    print(f"page read from memory #{i + 1}: {n} listings, {(time.time() - t) * 1000:.0f} ms", flush=True)
t = time.time()
cards = market_scan.scan(g, log=print)
print(f"scan: {len(cards)} listings #1-#3 in {time.time() - t:.0f} s", flush=True)
for c in cards[:8]:
    print("  ", {k: c.get(k) for k in ("name", "serial", "rarity", "start", "current_bid", "buy_now", "time_left", "seller",
                                       "top_bidder", "top_bid", "min_next_bid")}, flush=True)
print("bid window still open after the scan:", bool(mem_market.dialog_words()),
      "| listings in view:", [(c.get("name"), c.get("serial")) for c in mem_market.listings() or []], flush=True)
with_bids = [c for c in cards if c.get("top_bidder")]
print(f"listings with a top bidder read from the bid window: {len(with_bids)}", flush=True)
import mybids  # noqa: E402
t = time.time()
info = mybids.read_my_bids(g, log=print)
print(f"my bids in {time.time() - t:.1f} s:", info and {k: info[k] for k in ("winning", "selling", "requests", "amounts")}, flush=True)
for i in (info or {}).get("items", []):
    print("  ", {k: i.get(k) for k in ("kind", "status", "name", "serial", "rarity", "grade", "art", "amount", "time_left")}, flush=True)
if cards:
    want ={k: cards[0].get(k) for k in ("name", "serial", "seller", "start", "current_bid", "buy_now")}
    t = time.time()
    print("dry-run bid:", market_scan.place_bid(g, want, "1T", dry_run=True), f"({time.time() - t:.0f} s)", flush=True)
print("buttons found:", mem_gui.stats, flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
