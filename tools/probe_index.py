"""Opens the Index (memory finds the button), dumps what's showing in CardsUI to tools/dump_index_<tab>.txt for the
tab it opens on and for the Event tab, then closes it. Nothing is changed in the game. Bot must be stopped.
Usage: python tools/probe_index.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import card_art  # noqa: E402
import mem_gui  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
g = Game()
gui = mem_gui.gui()
mb = gui.mb


def panel():
    root = next(s for s in mb._children(mb.player_gui) if mb._name(s) == "CardsUI")
    for d, o in mb._walk(root, depth=4, max_nodes=400):
        if mb._class_name(o) == "TextLabel" and (mb._content_text(o) or "").startswith("Index") and "/" in mb._content_text(o):
            return mb._parent(o)


def dump(tag):
    p = panel()
    path = os.path.join(HERE, f"dump_index_{tag}.txt")
    n = 0
    t = time.time()
    with open(path, "w", encoding="utf-8") as f:
        for d, o in mb._walk(p, depth=30, max_nodes=80000):
            cls = mb._class_name(o)
            shown = gui.is_shown(o)
            geo = gui.geom(o)
            geo = f"({geo[0]:.0f},{geo[1]:.0f} {geo[2]:.0f}x{geo[3]:.0f})" if geo and all(abs(v) < 1e5 for v in geo) else ""
            txt = mb._content_text(o) if cls in ("TextLabel", "TextButton", "TextBox") else None
            img = card_art.image_id(mb, o) if cls in ("ImageLabel", "ImageButton") else None
            f.write(f"{'  ' * d}{cls} {mb._name(o)!r} {'S' if shown else '-'} {geo}"
                    f"{' ' + repr(txt[:100]) if txt else ''}{' img=' + img if img else ''}\n")
            n += 1
    print(f"{tag}: {n} objects in {time.time() - t:.1f}s -> {path}", flush=True)


close_any_menu(g)
g.wait(0.8)
hit = mem_gui.locate(text="Index", screen="CardsUI") or mem_gui.locate(text="Index", screen="CardsUI", contains=True)
print("Index button:", hit, flush=True)
g.click(hit[0], hit[1])
g.park_mouse()
g.wait(2.0)
print("panel shown:", gui.is_shown(panel()), flush=True)
dump("first")
ev = mem_gui.locate(text="Event", screen="CardsUI", exact=False)
print("Event tab:", ev, flush=True)
if ev:
    g.click(ev[0], ev[1])
    g.park_mouse()
    g.wait(1.5)
    dump("event")
close_any_menu(g)
