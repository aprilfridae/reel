"""Finds the custom prompt BillboardGui's 'showing' flag: its bytes away from the market stall (Fishing) vs at it (after
the recorded walk), twice each. Teleports and walks only; never presses E. Usage: python tools/probe_prompt_diff.py"""
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
N = 0x900


def parts():
    folder = mb._find_child(mb.player_gui, name="CustomPrompts")
    bbs = [c for c in mb._children(folder)] if folder else []
    return bbs


def snap(tag):
    out = []
    for bb in parts():
        btn = mb._find_child(bb, cls="TextButton")
        texts = [mb._content_text(c) for c in mb._children(btn)] if btn else []
        b = mb.r.read(bb, N) or b""
        bt = mb.r.read(btn, N) if btn else b""
        print(tag, mb._class_name(bb), mb._name(bb), [t for t in texts if t],
              "market open:", mem_gui.showing("MarketUI", text="Card Market"), flush=True)
        out.append((b, bt))
    return out


def away():
    packs.close_popup(game)
    packs.close_any_menu(game)
    packs.teleport(game, "Fishing", settle=0.6, poll=0.25)
    game.wait(1.5)


def stall():
    packs.close_any_menu(game)
    packs.teleport(game, "Spawn", settle=0.6, poll=0.25)
    market.walk_route(game, until_prompt=False)
    game.wait(1.0)


away(); B1 = snap("away1")
stall(); A1 = snap("stall1")
away(); B2 = snap("away2")
stall(); A2 = snap("stall2")
for k in range(min(len(A1), len(A2), len(B1), len(B2))):
    for which in (0, 1):
        a1, a2, b1, b2 = A1[k][which], A2[k][which], B1[k][which], B2[k][which]
        n = min(map(len, (a1, a2, b1, b2)))
        hits = [o for o in range(n) if a1[o] == a2[o] and b1[o] == b2[o] and a1[o] != b1[o]]
        print(f"prompt {k} {'billboard' if which == 0 else 'button'}: offsets stall!=away:",
              [(hex(o), a1[o], b1[o]) for o in hits][:40], flush=True)
packs.close_any_menu(game)
