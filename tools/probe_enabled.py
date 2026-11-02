"""Finds the byte that switches a whole ScreenGui on and off (Enabled): while the bot makes a market trip, snapshots
the first 0x800 bytes of the MarketUI ScreenGui and of its Root frame ~3 times a second, with whether the screen shows
the open Card Market (market.market_open), then prints the bytes that match it. Read-only (the bot does the trip).
Run on the bot PC's desktop: python tools/probe_enabled.py [seconds]"""
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_backend  # noqa: E402
from game import WindowCapture, find_roblox  # noqa: E402
from market import market_open  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 150
cap = WindowCapture(find_roblox(), fast=False)
cap.from_screen = True
mb = memory_backend.MemoryBackend(cache_path="explore_cache.json")
mb.start()
sgs = {mb._name(s): s for s in mb._children(mb.player_gui) if mb._class_name(s) == "ScreenGui"}
mui = sgs["MarketUI"]
objs = [o for d, o in mb._walk(mui, depth=3, max_nodes=60)]
paths = [f"{mb._class_name(o)}:{mb._name(o)}#{i}" for i, o in enumerate(objs)]
others = [sgs[n] for n in ("CardsUI", "EventHUD", "ShopUI", "DailyUI", "GiftUI", "TeleportUI") if n in sgs]
import time  # noqa: E402

snaps, labels, other = [], [], []
end = time.time() + secs
while time.time() < end:
    img = cap.grab()
    if img is None:
        continue
    labels.append(market_open(img))
    snaps.append(np.stack([np.frombuffer((mb.r.read(o, 0x800) or b"").ljust(0x800, b"\0")[:0x800], np.uint8) for o in objs]))
    other.append(np.stack([np.frombuffer((mb.r.read(o, 0x800) or b"").ljust(0x800, b"\0")[:0x800], np.uint8) for o in others]))
    time.sleep(0.2)
S, y, O = np.stack(snaps), np.array(labels), np.stack(other)
print(f"{len(y)} samples, market open on screen in {y.mean():.0%}", flush=True)
if y.all() or not y.any():
    sys.exit("the market never opened / closed during the recording")
for k, nm in enumerate(paths):
    for off in range(0x800):
        v = S[:, k, off]
        if len(np.unique(v)) != 2:
            continue
        hi = v == v.max()
        acc = max((hi == y).mean(), (hi != y).mean())
        if acc > 0.97:
            a, b = set(v[y].tolist()), set(v[~y].tolist())
            print(f"{acc:.3f} {nm:28} +{off:#05x}: open {sorted(a)}  closed {sorted(b)}"
                  f"   (other ScreenGuis there: {[int(O[0, j, off]) for j in range(O.shape[1])]})", flush=True)
