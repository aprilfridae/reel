"""Why did find_listing miss a listing? Walks to the market, reads the first page from memory, then runs the same
steps as market_scan._find_once for its first listing, printing what each page reads; then a dry-run bid (never
presses PLACE BID). Run on the bot PC's desktop with the bot paused. Usage: python tools/test_findlisting.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import market_scan as ms  # noqa: E402
import mem_market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
print("go to market:", market.go_to_market(g), flush=True)
first = mem_market.listings()[0]
want = {k: first.get(k) for k in ("name", "serial", "seller", "start", "current_bid", "buy_now")}
want["price"] = ms._price(want)
print("want:", want, flush=True)
ms.set_sort_lowest_serial(g)
img = g.frame()
h, w = img.shape[:2]
print("scroll to top:", g.scroll(w / 2, h * 0.55, 30), flush=True)
g.wait(0.6)
for page in range(4):
    img = g.frame()
    cards = ms.page_cards(g, img)
    print(f"page {page}: {len(cards)} cards (memory listings in view: {len(mem_market.listings() or [])})", flush=True)
    for bid, c in cards:
        print(f"   {c.get('name')!r} #{c.get('serial')} wanted={ms._is_wanted(c, want)} bid={tuple(round(v) for v in bid)}", flush=True)
    g.scroll(w / 2, h * 0.55, -2)
    g.wait(0.8)
print("dry-run bid:", ms.place_bid(g, want, "1T", dry_run=True), flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
