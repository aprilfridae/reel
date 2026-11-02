"""Finds what says the fishing panel / the reel is showing: records the screen (what vision.detect() sees: the
panel up = busy, a reel on = zone) alongside the first 0x400 bytes of the FishingUI ScreenGui, its top frame,
the panel, the track, the bar and the fish, ~10 times a second, then prints the bytes that match busy / reeling.
Read-only (it clicks nothing). Run on the bot PC's desktop, while the bot fishes:
    python tools/label_reel.py [seconds]      (needs game.py and vision.py next to it)"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402
from game import WindowCapture, find_roblox  # noqa: E402
from mem_reel import MemReel  # noqa: E402
from vision import detect  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 150
cap = WindowCapture(find_roblox(), fast=False)
cap.from_screen = True
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
reel = MemReel(mb)
assert reel._find(), "fishing panel not found"
sg = mb._find_screen_gui("FishingUI")
top = mb._parent(reel.panel)
objs = {"screengui": sg, "top": top, "panel": reel.panel, "track": reel.track, "bar": reel.bar, "fish": reel.fish,
        "progress": reel.progress}
names = list(objs)
raw, busy, reeling = [], [], []
end = time.time() + secs
while time.time() < end:
    img = cap.grab()
    if img is None:
        continue
    d = detect(img, 1.0)
    rows = []
    for k in names:
        b = mb.r.read(objs[k], 0x400) or b""
        rows.append(np.frombuffer(b.ljust(0x400, b"\0")[:0x400], np.uint8))
    raw.append(np.stack(rows))
    busy.append(d["busy"])
    reeling.append(d["zone"] is not None)
raw, busy, reeling = np.stack(raw), np.array(busy), np.array(reeling)
np.savez_compressed("reel_label.npz", raw=raw, busy=busy, reeling=reeling, names=np.array(names))
print(f"{len(busy)} samples: panel up in {busy.mean():.0%}, reeling in {reeling.mean():.0%}", flush=True)
for label, y in (("panel up", busy), ("reeling", reeling)):
    if y.all() or not y.any():
        print(f"{label}: always {bool(y[0])}, nothing to learn", flush=True)
        continue
    hits = []
    for o, k in enumerate(names):
        for off in range(0x400):
            v = raw[:, o, off]
            a, b = set(np.unique(v[y]).tolist()), set(np.unique(v[~y]).tolist())
            if not (a & b) and len(a) <= 2 and len(b) <= 2:
                hits.append((k, off, sorted(a), sorted(b)))
    print(f"{label}: {len(hits)} bytes tell it apart", flush=True)
    for k, off, a, b in hits[:15]:
        print(f"   {k:9} +{off:#05x}  when {label}: {a}   otherwise: {b}", flush=True)
