"""Records the reel from memory 50 times a second while reels happen: every GUI object inside the fishing
panel's track (FishingUI/Frame/Frame/Frame/Frame and everything under those frames), with its centre, position
and size. Writes reel_rec.csv (t, object index, class, name, cx, cy, x, y, w, h) and prints which objects moved.
Read-only. Usage: python tools/record_reel.py [seconds]

Layout of a GUI object (found from the reel's frames): +0xDC/+0xE0 centre, +0xF4/+0xF8 top-left, +0xFC/+0x100 size."""
import os
import struct
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()


def objects():
    fg = mb._find_screen_gui("FishingUI")
    if not fg:
        return []
    out = []
    for d, inst in mb._walk(fg, depth=8, max_nodes=600):
        if d >= 4:
            out.append(inst)
    return out


def geo(inst):
    a = mb.r.read(inst + 0xDC, 8)
    b = mb.r.read(inst + 0xF4, 16)
    if not a or not b or len(a) < 8 or len(b) < 16:
        return None
    return struct.unpack("<2f", a) + struct.unpack("<4f", b)


objs = objects()
info = {i: (mb._class_name(o), mb._name(o)) for i, o in enumerate(objs)}
out = open("reel_rec.csv", "w", encoding="utf-8")
out.write("t,obj,cls,name,cx,cy,x,y,w,h\n")
vals = defaultdict(list)
end = time.time() + secs
t0 = time.time()
while time.time() < end:
    t = time.time() - t0
    for i, o in enumerate(objs):
        g = geo(o)
        if g and all(abs(v) < 1e5 for v in g):
            vals[i].append(g)
            out.write(f"{t:.3f},{i},{info[i][0]},{info[i][1]}," + ",".join(f"{v:.1f}" for v in g) + "\n")
    time.sleep(0.02)
out.close()
print(len(objs), "objects inside the track", flush=True)
for i, gs in vals.items():
    xs = [g[0] for g in gs]
    if max(xs) - min(xs) > 1:
        ws = [g[4] for g in gs]
        print(f"obj {i:3} {info[i][0]:12} {str(info[i][1])[:20]:20} centre x {min(xs):.0f}..{max(xs):.0f} ({len(set(xs))} values)"
              f"  y {gs[0][1]:.0f}  w {min(ws):.0f}..{max(ws):.0f}", flush=True)
