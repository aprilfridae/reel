"""Every "Card" frame in the game's menus that card_art can't read: its ScreenGui path, name text and each ImageLabel
(size, and the strings at the Image offsets seen so far). Usage: python tools/probe_card_kinds.py"""
import os
import struct
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import card_art  # noqa: E402
import mem_market  # noqa: E402
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
stack, bad, good = [mb.player_gui], [], Counter()
while stack:
    node = stack.pop()
    if mb._name(node) == "Card":
        path, p = [], mb._parent(node)
        while p and len(path) < 12 and p != mb.player_gui:
            path.append(mb._name(p))
            p = mb._parent(p)
        where = "/".join(reversed(path[-3:]))
        (good.update([where]) if card_art.read_card(mb, node) else bad.append((where, node)))
        continue
    stack.extend(mb._children(node))
print("read ok:", dict(good))
print("not read:", Counter(w for w, _ in bad))
shown = set()
for where, node in bad:
    if where in shown:
        continue
    shown.add(where)
    info = mem_market.parse(mem_market._texts(mb, node, depth=8))
    print(f"\n== {where}: {info.get('name')!r} {info.get('rarity')}")
    for d, o in mb._walk(node, depth=8, max_nodes=300):
        cls = mb._class_name(o)
        if cls in ("ImageLabel", "ImageButton", "ViewportFrame"):
            g = mb.r.read(o + 0xFC, 8)
            w, h = struct.unpack("<2f", g) if g and len(g) == 8 else (0, 0)
            strs = {hex(off): mb.r.read_str(o + off) for off in (0x9a8, 0x9d0, 0xa78)}
            print(f"  {'  ' * d}{cls} {mb._name(o)!r} {w:.0f}x{h:.0f} {strs}")
