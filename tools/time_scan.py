"""Times finding the game in Roblox's memory from scratch (no cache), with the peak memory it took, then reads
the balance and the fishing state. Read-only. Usage: python tools/time_scan.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402

cache = "time_scan_cache.json"
if os.path.exists(cache):
    os.remove(cache)
t = time.time()
mb = memory_backend.MemoryBackend(cache_path=cache)
mb.start()
print(f"found the game in {time.time() - t:.1f} s", flush=True)
try:
    import psutil
    print(f"peak memory: {psutil.Process().memory_info().peak_wset / 1e6:.0f} MB", flush=True)
except Exception:
    pass
t = time.time()
mb2 = memory_backend.MemoryBackend(cache_path=cache)
mb2.start()
print(f"second start, from the cache: {time.time() - t:.2f} s", flush=True)
print("balance:", mb.get_balance(), "| fishing:", mb.fish_state(), flush=True)
