"""Dumps ScreenGuis from memory to tools/dump_<name>.txt: every object's class, name, whether it's showing, centre and
size, its text, and an image's asset id. Read-only (no clicks).
Usage: python tools/dump_screen.py                 the list of ScreenGuis (enabled or not) with how big each is
       python tools/dump_screen.py Name [Name...] [--depth N] [--shown]   those ScreenGuis in full"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import card_art  # noqa: E402
import mem_gui  # noqa: E402
from memory_backend import get_backend  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
depth = int(sys.argv[sys.argv.index("--depth") + 1]) if "--depth" in sys.argv else 24
if "--depth" in sys.argv:
    args.remove(str(depth))
shown_only = "--shown" in sys.argv
mb = get_backend()
gui = mem_gui.gui()
sgs = [s for s in mb._children(mb.player_gui)]
if not args:
    for s in sgs:
        n = sum(1 for _ in mb._walk(s, depth=30, max_nodes=50000))
        print(f"{mb._class_name(s):<12} {mb._name(s)!r:<28} enabled={gui.screen_on(mb._name(s))} objects={n}")
    sys.exit()
for want in args:
    s = next((s for s in sgs if mb._name(s) == want), None)
    if s is None:
        print(f"no ScreenGui {want!r}")
        continue
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"dump_{want}.txt")
    lines = 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"== {want} enabled={gui.screen_on(want)}\n")
        for d, o in mb._walk(s, depth=depth, max_nodes=60000):
            if d == 0:
                continue
            shown = gui.is_shown(o)
            if shown_only and not shown:
                continue
            cls = mb._class_name(o)
            g = gui.geom(o)
            geo = f"({g[0]:.0f},{g[1]:.0f} {g[2]:.0f}x{g[3]:.0f})" if g and all(abs(v) < 1e5 for v in g) else ""
            txt = mb._content_text(o) if cls in ("TextLabel", "TextButton", "TextBox") else None
            img = card_art.image_id(mb, o) if cls in ("ImageLabel", "ImageButton") else None
            f.write(f"{'  ' * d}{cls} {mb._name(o)!r} {'S' if shown else '-'} {geo}"
                    f"{' ' + repr(txt[:120]) if txt else ''}{' img=' + img if img else ''}\n")
            lines += 1
    print(f"{want}: {lines} objects -> {path}")
