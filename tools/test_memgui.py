"""Live test of mem_gui with memory-only clicks (nothing is opened, bought or teleported): opens the Packs menu with the
"Packs" button found in memory, checks it opened (memory and screen agree), finds the OPEN button of a pack, closes the
menu with the X found in memory; then the same with the Teleports menu (finds the Fishing entry, doesn't click it).
Run on the bot PC's desktop with the bot paused. Usage: python tools/test_memgui.py"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

g = Game()
close_any_menu(g)
g.wait(1)


def timed(label, fn):
    t = time.time()
    out = fn()
    print(f"{label}: {out}  ({(time.time() - t) * 1000:.0f} ms)", flush=True)
    return out


print("market screen on (should be False):", mem_gui.showing("MarketUI"), flush=True)
hit = timed("Packs button", lambda: mem_gui.locate(text="Packs", screen="CardsUI"))
g.click(hit[0], hit[1])
g.park_mouse()
g.wait(1.5)
print("screen says packs menu open:", g.find("packs_header", g.frame()) is not None, flush=True)
timed("  OPEN in Iced Pack", lambda: mem_gui.locate(text="OPEN", within="Iced Pack"))
timed("  OPEN in Atlantis Pack (none if you have none)", lambda: mem_gui.locate(text="OPEN", within="Atlantis Pack"))
x = timed("  close X", lambda: mem_gui.locate(text="X", screen="CardsUI"))
g.click(x[0], x[1])
g.park_mouse()
g.wait(1.2)
print("screen says packs menu open after X:", g.find("packs_header", g.frame()) is not None, flush=True)
print("memory finds an X after closing:", mem_gui.locate(text="X", screen="CardsUI"), flush=True)

hit = timed("Teleports button", lambda: mem_gui.locate(name="TeleportBtn", screen="CardsUI"))
print("teleport screen on before:", mem_gui.showing("TeleportUI"), flush=True)
g.click(hit[0], hit[1])
g.park_mouse()
g.wait(1.5)
print("teleport screen on after:", mem_gui.showing("TeleportUI"), flush=True)
for place in ("Fishing", "Spawn"):
    timed(f"  {place} entry", lambda: mem_gui.locate(text=place, screen="TeleportUI", exact=False))
x = timed("  close X", lambda: mem_gui.locate(text="X", screen="TeleportUI"))
if x:
    g.click(x[0], x[1])
    g.park_mouse()
    g.wait(1.2)
print("teleport screen on after X:", mem_gui.showing("TeleportUI"), flush=True)
close_any_menu(g)
