"""Is the Card Market showing, per memory? Also lists PlayerGui / CoreGui ScreenGuis that are enabled.
Usage: python tools/probe_market_shown.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
g = mem_gui.gui()
print("showing Card Market:", mem_gui.showing("MarketUI", text="Card Market"), "screen_on", g.screen_on("MarketUI"), flush=True)
core = mb._find_child(mb.data_model, cls="CoreGui")
for root in (mb.player_gui, core):
    for s in mb._children(root):
        if mb._class_name(s) == "ScreenGui" and g.screen_on(mb._name(s)) if root == mb.player_gui else False:
            print("  enabled:", mb._name(s), flush=True)
for _, o in mb._walk(mb.player_gui, 14, 60000):
    t = mb._content_text(o) or ""
    if t.strip() in ("Card Market", "Open Market") or "open market" in t.lower():
        print(repr(t), "shown", g.is_shown(o), g.geom(o), flush=True)
ws = mb._find_child(mb.data_model, cls="Workspace")
n = 0
for _, o in mb._walk(ws, 12, 200000):
    c = mb._class_name(o)
    if c in ("ProximityPrompt", "BillboardGui"):
        n += 1
        if n < 40:
            par = mb._parent(o)
            print(c, mb._name(o), "<", mb._name(par) if par else None, flush=True)
print("prompts/billboards:", n, flush=True)
