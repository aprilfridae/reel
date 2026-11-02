"""On a Who owns? artist page: the rarity chips' texts (every string-looking field), in screen order.
Usage: python tools/probe_chips.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402

g = mem_gui.gui()
mb = g.mb
sg = mem_gui.screen("MarketUI")
chips = []
for _, o in mb._walk(sg, 22, 30000):
    geo = g.geom(o)
    if mb._class_name(o) == "TextButton" and geo and abs(geo[2] - 108) < 2 and abs(geo[3] - 36) < 2 and g.is_shown(o):
        chips.append((round(geo[1]), geo[0], o))
for y, x, o in sorted(chips):
    found = []
    for off in range(0xA00, 0x1000, 8):
        try:
            s = mb.r.read_str(o + off)
        except Exception:
            s = None
        if s and 2 < len(s) < 60 and s.isprintable():
            found.append((hex(off), s))
    kids = [(mb._class_name(c), mb._name(c), mb._content_text(c)) for c in mb._children(o)]
    print(y, x, repr(mb._content_text(o)), found[:6], kids, flush=True)
