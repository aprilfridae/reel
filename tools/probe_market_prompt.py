"""Teleports to Spawn, replays the market walk (never presses E), then lists every label saying "Open Market" / "Market"
in PlayerGui and CoreGui with its path, and whether it shows. Usage: python tools/probe_market_prompt.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import mem_gui  # noqa: E402
import packs  # noqa: E402
from game import Game  # noqa: E402
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
game = Game()
g = mem_gui.gui()


def path(o):
    parts = []
    while o and len(parts) < 12:
        parts.append(f"{mb._class_name(o)}:{mb._name(o)}")
        o = mb._parent(o)
    return " < ".join(parts)


def scan(tag):
    core = mb._find_child(mb.data_model, cls="CoreGui")
    for root in (mb.player_gui, core):
        for _, o in mb._walk(root, 14, 60000):
            t = mb._content_text(o) or ""
            if "market" in t.lower() and len(t) < 40:
                print(tag, repr(t), "shown", g.is_shown(o), g.geom(o), path(o), flush=True)


packs.close_popup(game)
packs.close_any_menu(game)
print("teleport", packs.teleport(game, "Spawn", settle=0.6, poll=0.25), flush=True)
scan("at spawn:")
market.walk_route(game, until_prompt=False)
game.wait(0.8)
scan("after walk:")
