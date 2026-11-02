"""Records the first 0x400 bytes of every frame in the fishing panel (FishingUI, depth 1-4) 20 times a second,
to find the byte that says whether an object is showing (Visible): saved to reel_raw.npz with the times, each
object's path and the reel bar's x (so reeling can be told from the bar moving). Read-only.
Usage: python tools/record_raw.py [seconds]"""
import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
fg = mb._find_screen_gui("FishingUI")
objs, paths = [], []
for d, inst in mb._walk(fg, depth=4, max_nodes=400):
    if 1 <= d <= 4 and mb._class_name(inst) in ("Frame", "TextLabel", "TextButton", "ImageLabel"):
        path, node = [], inst
        for _ in range(d + 1):
            path.append(f"{mb._name(node)}:{mb._class_name(node)}")
            node = mb._parent(node)
        objs.append(inst)
        paths.append("/".join(reversed(path)) + f"#{len(objs) - 1}")
print(len(objs), "objects", flush=True)
data, times = [], []
end = time.time() + secs
t0 = time.time()
while time.time() < end:
    row = []
    for o in objs:
        b = mb.r.read(o, 0x400) or b"\0" * 0x400
        row.append(np.frombuffer(b.ljust(0x400, b"\0")[:0x400], np.uint8))
    data.append(np.stack(row))
    times.append(time.time() - t0)
    time.sleep(0.05)
np.savez_compressed("reel_raw.npz", data=np.stack(data), times=np.array(times), paths=np.array(paths))
print("saved", len(times), "samples", flush=True)
