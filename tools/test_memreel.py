"""Reads the reel from memory (mem_reel.MemReel) as fast as it can for a while, while reels happen: how many reads
a second, how often a reel was on, and the bar / fish ranges seen (screen x). Read-only.
Usage: python tools/test_memreel.py [seconds]"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402
from mem_reel import MemReel  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
reel = MemReel(mb)
n = on = starts = 0
was = False
zl, zr, fish = [], [], []
t0 = time.time()
while time.time() - t0 < secs:
    r = reel.read()
    n += 1
    if r:
        on += 1
        zl.append(r["zone"][0]); zr.append(r["zone"][1]); fish.append(r["fish"])
        if not was:
            starts += 1
    was = r is not None
el = time.time() - t0
print(f"{n / el:.0f} reads/s, a reel was on in {on / max(n, 1):.0%} of them ({starts} reels started)")
if on:
    print(f"bar left {min(zl):.0f}..{max(zl):.0f}, right {min(zr):.0f}..{max(zr):.0f}, fish {min(fish):.0f}..{max(fish):.0f}")
