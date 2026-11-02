"""Opens the BID window of the first listing in view (memory finds the BID button), saves a screenshot
(bidwin.png), prints every showing text in every enabled ScreenGui, then presses Cancel (the bot's own way).
No bid is placed. Walks to the market first and back to fishing after. Run on the bot PC's desktop with the bot
paused. Usage: python tools/probe_bidwindow.py"""
import os
import sys

import cv2

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
first = (mem_market.listings() or [None])[0]
print("first listing:", first and {k: first[k] for k in ("name", "serial", "bid")}, flush=True)
before = set()
gui = mem_gui.gui()
mb = gui.mb


def showing_texts():
    out = []
    for sg in mb._children(mb.player_gui):
        if mb._class_name(sg) != "ScreenGui" or not gui.screen_on(mb._name(sg)):
            continue
        for d, o in mb._walk(sg, depth=18, max_nodes=8000):
            if mb._class_name(o) in ("TextLabel", "TextButton", "TextBox") and gui._ok(o):
                geo = gui.geom(o)
                out.append((mb._name(sg), mb._class_name(o), (mb._content_text(o) or "")[:50], round(geo[0]), round(geo[1]),
                            mb._name(mb._parent(o)), o))
    return out


before = {t[6] for t in showing_texts()}
if first:
    g.click(*first["bid"])
    g.park_mouse()
    g.wait(2.0)
    cv2.imwrite("bidwin.png", g.frame())
    new = [t for t in showing_texts() if t[6] not in before]
    print(f"===== {len(new)} texts that appeared with the BID window", flush=True)
    for t in new:
        print("  ", t[:6], flush=True)
    print("enabled screens:", [mb._name(s) for s in mb._children(mb.player_gui) if mb._class_name(s) == "ScreenGui"
                               and gui.screen_on(mb._name(s))], flush=True)
    market_scan._cancel_dialog(g)
    g.park_mouse()
    g.wait(1)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
