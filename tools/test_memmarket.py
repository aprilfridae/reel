"""Live test of mem_market: walks to the Card Market, reads the listings in view from memory and by OCR (the bot's
current way) and prints them side by side; then opens the BID window of the first listing, prints what memory shows of
it, and presses Cancel (found in memory, else on screen). No bid is placed. Goes back to fishing.
Run on the bot PC's desktop with the bot paused. Usage: python tools/test_memmarket.py"""
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
print("go to market:", market.go_to_market(g), flush=True)
g.wait(2)
t = time.time()
mem = mem_market.listings()
print(f"memory: {len(mem or [])} listings in view ({(time.time() - t) * 1000:.0f} ms)", flush=True)
img = g.frame()
t = time.time()
ocr = [market_scan.read_listing(g, img, b) for b in market_scan.bid_buttons(g, img)]
print(f"OCR: {len(ocr)} listings ({(time.time() - t) * 1000:.0f} ms)", flush=True)
for m in mem or []:
    o = min(ocr, key=lambda c: 0, default=None)
    print("MEM", {k: m.get(k) for k in ("name", "serial", "rarity", "start", "current_bid", "buy_now", "time_left", "seller", "bid", "buy")}, flush=True)
for o in ocr:
    print("OCR", {k: o.get(k) for k in ("name", "serial", "start", "current_bid", "buy_now", "time_left", "seller")}, flush=True)

if mem:
    first = mem[0]
    g.click(*first["bid"])
    g.park_mouse()
    g.wait(1.5)
    gui = mem_gui.gui()
    mb = gui.mb
    print("===== BID WINDOW (showing texts)", flush=True)
    for sg in mb._children(mb.player_gui):
        if mb._class_name(sg) != "ScreenGui" or not gui.screen_on(mb._name(sg)) or mb._name(sg) in ("CardsUI", "EventHUD"):
            continue
        for d, o in mb._walk(sg, depth=16, max_nodes=6000):
            if mb._class_name(o) in ("TextLabel", "TextButton", "TextBox") and gui._ok(o):
                txt = mb._content_text(o) or ""
                if txt and not mem_market.re.search(r"left$|^by |^Start|^Buy now|/s$|^#", txt):
                    geo = gui.geom(o)
                    print(f"  {mb._name(sg):10} {mb._class_name(o):10} {txt[:50]!r:54} ({geo[0]:.0f},{geo[1]:.0f}) parent {mb._name(mb._parent(o))}", flush=True)
    cancel = mem_gui.locate(text="Cancel", contains=True)
    print("Cancel in memory:", cancel, flush=True)
    if cancel:
        g.click(cancel[0], cancel[1])
    else:
        market_scan._cancel_dialog(g)
    g.park_mouse()
    g.wait(1)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
