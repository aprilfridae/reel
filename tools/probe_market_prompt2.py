"""At the market stall: closes the market, then shows the "Open Market" label's path and state (its BillboardGui's
flags too) a few times, and takes no other action. Usage: python tools/probe_market_prompt2.py"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
import packs  # noqa: E402
from game import Game  # noqa: E402
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
game = Game()
g = mem_gui.gui()


def chain(o):
    out = []
    while o and len(out) < 10:
        b = mb.r.read(o + mem_gui.VISIBLE, 1)
        e = mb.r.read(o + mem_gui.ENABLED, 1)
        out.append(f"{mb._class_name(o)}:{mb._name(o)}[v{b[0] if b else '?'} e{e[0] if e else '?'}]")
        o = mb._parent(o)
    return " < ".join(out)


labels = [o for _, o in mb._walk(mb.player_gui, 14, 60000) if (mb._content_text(o) or "").strip() == "Open Market"]
print("labels:", len(labels), flush=True)
for state in ("market open", "after close", "after 2s"):
    if state == "after close":
        packs.close_any_menu(game)
        game.wait(0.8)
    elif state == "after 2s":
        game.wait(2)
    for o in labels:
        print(state, "shown", g.is_shown(o), g.geom(o), chain(o), flush=True)
        par = mb._parent(o)
        for c in mb._children(par) if par else []:
            print("    sibling", mb._class_name(c), mb._name(c), repr(mb._content_text(c)), flush=True)
