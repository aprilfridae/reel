"""Prints the PlayerGui's ScreenGuis and their first levels (class, name, centre and size, text), to see how the
game's screens are built in memory. Read-only. Usage: python tools/dump_gui.py [depth]"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402

depth = int(sys.argv[1]) if len(sys.argv) > 1 else 2
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
for sg in mb._children(mb.player_gui):
    print(f"== {mb._class_name(sg)} {mb._name(sg)!r}", flush=True)
    for d, inst in mb._walk(sg, depth=depth, max_nodes=300):
        if d == 0:
            continue
        cls = mb._class_name(inst)
        b = mb.r.read(inst + 0xDC, 0x28) or b""
        geo = ""
        if len(b) == 0x28:
            cx, cy = struct.unpack_from("<2f", b, 0)
            w, h = struct.unpack_from("<2f", b, 0x20)
            if all(abs(v) < 1e5 for v in (cx, cy, w, h)):
                geo = f"centre ({cx:.0f},{cy:.0f}) size {w:.0f}x{h:.0f}"
        txt = mb._content_text(inst) if cls in ("TextLabel", "TextButton", "TextBox") else None
        print(f"{'  ' * d}{cls} {mb._name(inst)!r} {geo} {repr(txt[:30]) if txt else ''}", flush=True)
