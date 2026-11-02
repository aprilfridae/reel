"""Finds GUI objects by their text in every ScreenGui and prints where memory says they are, whether they're showing
(+0x575 on them and every parent), and, for the HUD buttons the bot has pictures of, where the screen finds them.
Read-only. Usage: python tools/find_text.py Packs Teleports ...   (needs game.py next to it for the screen side)"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402

words = [w.lower() for w in sys.argv[1:]] or ["packs", "teleports", "index"]
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()


def shown(inst):
    node = inst
    for _ in range(40):
        cls = mb._class_name(node)
        if cls == "ScreenGui" or node is None:
            return True
        b = mb.r.read(node + 0x575, 1)
        if not b or b[0] != 1:
            return False
        node = mb._parent(node)
    return False


for sg in mb._children(mb.player_gui):
    if mb._class_name(sg) != "ScreenGui":
        continue
    for d, inst in mb._walk(sg, depth=14, max_nodes=4000):
        cls = mb._class_name(inst)
        if cls not in ("TextLabel", "TextButton"):
            continue
        txt = (mb._content_text(inst) or "").strip()
        if txt.lower() in words or any(txt.lower().startswith(w) and len(txt) < len(w) + 4 for w in words):
            b = mb.r.read(inst + 0xDC, 0x28)
            cx, cy = struct.unpack_from("<2f", b, 0)
            w, h = struct.unpack_from("<2f", b, 0x20)
            par = mb._parent(inst)
            print(f"{mb._name(sg):14} {cls:10} {txt[:20]!r:24} centre ({cx:.0f},{cy:.0f}) {w:.0f}x{h:.0f} "
                  f"shown={shown(inst)}  parent {mb._class_name(par)} {mb._name(par)!r}", flush=True)
try:
    from game import Game
    g = Game()
    img = g.frame()
    for t in ("packs_button", "teleports_button"):
        hit = g.find(t, img)
        print(f"screen: {t} at {hit[:2] if hit else None}", flush=True)
except Exception as e:
    print("(no screen check:", e, ")")
