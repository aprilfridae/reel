"""Opens the Packs menu, then the Teleports menu (with the bot's own clicks; nothing is opened, bought or teleported),
and prints every GUI object that is showing in each (class, name, text, centre, size, the path's last parts), then
closes it. Run on the bot PC's desktop with the bot paused. Usage: python tools/dump_open.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402
from game import Game  # noqa: E402
from mem_gui import MemGui  # noqa: E402
from packs import close_any_menu  # noqa: E402

mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
gui = MemGui(mb)
g = Game()


def dump(title):
    print(f"===== {title}", flush=True)
    for sg in mb._children(mb.player_gui):
        if mb._class_name(sg) != "ScreenGui":
            continue
        for d, inst in mb._walk(sg, depth=16, max_nodes=6000):
            cls = mb._class_name(inst)
            if cls not in ("TextLabel", "TextButton", "ImageButton", "Frame", "ScrollingFrame", "ImageLabel"):
                continue
            geo = gui._ok(inst)
            if not geo:
                continue
            txt = mb._content_text(inst) if cls in ("TextLabel", "TextButton") else None
            if cls in ("Frame", "ImageLabel") and not (geo[2] > 300 or mb._name(inst) not in ("Frame", "ImageLabel")):
                continue  # plain frames only when big or named
            path, node = [], mb._parent(inst)
            for _ in range(3):
                if node is None:
                    break
                path.append(str(mb._name(node)))
                node = mb._parent(node)
            print(f"{mb._name(sg):12} {cls:13} {str(mb._name(inst))[:20]:20} {repr((txt or '')[:24]):28} "
                  f"({geo[0]:.0f},{geo[1]:.0f}) {geo[2]:.0f}x{geo[3]:.0f}  <- {'/'.join(reversed(path))}", flush=True)


for button, title in (("packs_button", "PACKS MENU"), ("teleports_button", "TELEPORTS MENU")):
    close_any_menu(g)
    g.wait(1)
    hit = g.find(button, g.frame())
    if not hit:
        print("no", button, "on screen")
        continue
    g.click(hit[0], hit[1])
    g.park_mouse()
    g.wait(1.8)
    dump(title)
close_any_menu(g)
