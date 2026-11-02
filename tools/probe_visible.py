"""Finds the byte that says a GUI object is showing (Visible): opens and closes the Packs menu a few times (with the
bot's own clicks; nothing is bought or opened) and snapshots the first 0x1000 bytes of every object in every
ScreenGui each time, then prints the (object, offset) pairs that are one value whenever the menu is open and another
whenever it's closed. Run on the bot PC's desktop with the bot paused (it clicks the Packs button and the X).
    python tools/probe_visible.py           (needs game.py and packs.py next to it)"""
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

SPAN = 0x1000
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
g = Game()

objs, paths = [], []
for sg in mb._children(mb.player_gui):
    if mb._class_name(sg) != "ScreenGui":
        continue
    for d, inst in mb._walk(sg, depth=3, max_nodes=200):
        cls = mb._class_name(inst) or ""
        if cls in ("ScreenGui", "Frame", "ImageButton", "TextButton", "ImageLabel", "ScrollingFrame", "CanvasGroup"):
            objs.append(inst)
            paths.append(f"{mb._name(sg)}{'/' if d else ''}{'.../' * max(0, d - 1)}{mb._name(inst) if d else ''}:{cls}")
print(len(objs), "objects", flush=True)


def snap():
    return np.stack([np.frombuffer((mb.r.read(o, SPAN) or b"").ljust(SPAN, b"\0")[:SPAN], np.uint8) for o in objs])


def open_packs():
    hit = g.find("packs_button", g.frame())
    if hit:
        g.click(hit[0], hit[1])
        g.park_mouse()
    g.wait(1.5)
    return g.find("packs_header", g.frame()) is not None


closed, opened = [], []
close_any_menu(g)
g.wait(1.0)
for i in range(3):
    closed.append(snap())
    ok = open_packs()
    print(f"round {i + 1}: packs menu open = {ok}", flush=True)
    if not ok:
        break
    opened.append(snap())
    close_any_menu(g)
    g.wait(1.2)
closed.append(snap())
if not opened:
    sys.exit("the Packs menu didn't open")
C, O = np.stack(closed), np.stack(opened)
same_c = (C == C[0]).all(0)
same_o = (O == O[0]).all(0)
flip = same_c & same_o & (C[0] != O[0])
hits = np.argwhere(flip)
print(len(hits), "bytes flip with the menu", flush=True)
offs = Counter(int(off) for _, off in hits if {int(C[0][_, off]), int(O[0][_, off])} <= {0, 1})
print("offsets that are 0/1 and flip, by how many objects:", offs.most_common(10), flush=True)
for o, off in hits[:60]:
    a, b = int(C[0][o, off]), int(O[0][o, off])
    if {a, b} <= {0, 1}:
        print(f"  {paths[o][:60]:60} +{off:#06x}  closed {a} open {b}", flush=True)
