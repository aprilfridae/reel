"""Dump the Card Market's My Listings and Requests tabs from memory (texts with their parent's name, position and
whether they're showing), and how the Browse grid's "Show more" button looks, for reading them without OCR.
Walks to the market and back to fishing. Usage: python tools/dump_mylistings.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import mem_gui  # noqa: E402
import mybids  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
gui = mem_gui.gui()
mb = gui.mb
print("go to market:", market.go_to_market(g), flush=True)


def dump(title):
    sg = next(s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI")
    print(f"\n===== {title}", flush=True)
    for d, o in mb._walk(sg, depth=14, max_nodes=6000):
        cls = mb._class_name(o)
        if cls not in ("TextLabel", "TextButton", "TextBox", "ScrollingFrame") and mb._name(o) != "Card":
            continue
        if cls == "ScrollingFrame" or mb._name(o) == "Card":
            if gui.is_shown(o) or cls == "ScrollingFrame":
                geo = gui.geom(o)
                print(f"{'  ' * d}[{cls} {mb._name(o)!r} shown={gui.is_shown(o)} geom={tuple(round(v) for v in geo) if geo else None} "
                      f"children={len(mb._children(o))}]", flush=True)
            continue
        t = mb._content_text(o)
        if not t or not gui.is_shown(o):
            continue
        geo = gui.geom(o)
        print(f"{'  ' * d}{cls} {mb._name(o)!r} parent={mb._name(mb._parent(o))!r} at={tuple(round(v) for v in geo[:2])} {t!r}", flush=True)


more = mem_gui.read(text="Show more", screen="MarketUI", contains=True)
print("Show more (only if in view):", more, flush=True)
for d, o in mb._walk(next(s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI"), depth=14, max_nodes=6000):
    t = mb._content_text(o) if mb._class_name(o) in ("TextLabel", "TextButton") else None
    if t and "show more" in t.lower():
        print("Show more object:", mb._class_name(o), repr(t), "shown", gui.is_shown(o), "geom", gui.geom(o),
              "parent", mb._name(mb._parent(o)), mb._class_name(mb._parent(o)), flush=True)
print("My Listings tab:", mybids._open_tab(g, "Listin"), flush=True)
g.wait(2.5)
dump("My Listings")
print("Requests tab:", mybids._open_tab(g, "Requests"), flush=True)
g.wait(2)
dump("Requests")
close_any_menu(g)
print("\nback to fishing:", teleport_to_fishing(g), flush=True)
