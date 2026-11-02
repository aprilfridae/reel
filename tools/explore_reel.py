"""Records the fishing panel (PlayerGui.FishingUI) from memory while reels happen, to find the bar and the fish:
every GUI object's name, class and the floats around its AbsolutePosition, 20 times a second. Prints the objects
whose position moved, with their range. Read-only. Usage: python tools/explore_reel.py [seconds]"""
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
base = mb._abs_pos_off
print("AbsolutePosition offset", hex(base), flush=True)

seen = {}  # address -> (path, class)
xs, ys = defaultdict(list), defaultdict(list)
raw = defaultdict(list)  # address -> the floats from base-0x30 .. base+0x30, per sample
texts = defaultdict(set)
end = time.time() + secs
samples = 0
while time.time() < end:
    fg = mb._find_screen_gui("FishingUI")
    if fg:
        for d, inst in mb._walk(fg, depth=12, max_nodes=400):
            if inst not in seen:
                path, node = [], inst
                for _ in range(d + 1):
                    path.append(mb._name(node) or "?")
                    node = mb._parent(node)
                seen[inst] = ("/".join(reversed(path)), mb._class_name(inst))
            blob = mb.r.read(inst + base - 0x30, 0x60)
            if blob and len(blob) == 0x60:
                fl = struct.unpack("<24f", blob)
                raw[inst].append(fl)
                xs[inst].append(fl[12])  # = base
                ys[inst].append(fl[13])
            t = mb._content_text(inst)
            if t:
                texts[inst].add(t[:40])
        samples += 1
    time.sleep(0.05)

print(f"{samples} samples, {len(seen)} objects", flush=True)
rows = []
for inst, (path, cls) in seen.items():
    x = [v for v in xs[inst] if v == v]
    if not x:
        continue
    rows.append((max(x) - min(x), path, cls, min(x), max(x), min(ys[inst]), max(ys[inst]), inst))
rows.sort(reverse=True)
for span, path, cls, x0, x1, y0, y1, inst in rows[:25]:
    # which of the floats around the position changed most (the size / a fill fraction may be elsewhere)
    cols = list(zip(*raw[inst]))
    moving = [(f"{(i - 12) * 4:+#x}", round(min(c), 3), round(max(c), 3)) for i, c in enumerate(cols)
              if max(c) - min(c) > 0.5 and all(abs(v) < 1e6 for v in c)][:6]
    print(f"{span:7.1f}  {cls:12} {path[-70:]:70}  x {x0:.0f}..{x1:.0f}  y {y0:.0f}..{y1:.0f}  {sorted(texts[inst])[:2]}  moving {moving}",
          flush=True)
