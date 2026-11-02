"""Checks the Visible candidates (+0x575 on GUI objects, +0x614 / +0x640 on ScreenGuis) with another menu: opens and
closes the Teleports menu twice and prints them for TeleportUI's objects each time. Run on the bot PC's desktop with
the bot paused (it clicks the Teleports button and the X). Usage: python tools/probe_visible2.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
g = Game()
sg = mb._find_screen_gui("TeleportUI")
objs = [(d, i) for d, i in mb._walk(sg, depth=3, max_nodes=80)]


def show(tag):
    byte = lambda i, off: (mb.r.read(i + off, 1) or b"?")[0]
    print(f"--- {tag}: ScreenGui +0x614={byte(sg, 0x614)} +0x640={byte(sg, 0x640)}", flush=True)
    for d, i in objs[1:14]:
        print(f"   {'  ' * d}{mb._class_name(i):13} {str(mb._name(i))[:18]:18} +0x575={byte(i, 0x575)} +0x540={byte(i, 0x540)}",
              flush=True)


close_any_menu(g)
g.wait(1)
for r in range(2):
    show(f"round {r + 1}, closed")
    hit = g.find("teleports_button", g.frame())
    if not hit:
        sys.exit("no Teleports button on screen")
    g.click(hit[0], hit[1])
    g.park_mouse()
    g.wait(1.5)
    show(f"round {r + 1}, open")
    close_any_menu(g)
    g.wait(1.2)
