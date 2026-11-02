"""Finds where a TextBox keeps its typed text: reads a string (inline and through a pointer) at every 8-byte offset of
each TextBox in MarketUI and prints the readable ones. Usage: python tools/probe_textbox.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402

gui = mem_gui.gui()
mb = gui.mb
r = mb.r
sg = next(s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI")
for d, o in mb._walk(sg, depth=14, max_nodes=30000):
    if mb._class_name(o) != "TextBox":
        continue
    print(f"TextBox {hex(o)} shown={gui.is_shown(o)} geom={gui.geom(o)}", flush=True)
    for off in range(0x100, 0x1200, 8):
        for how, addr in (("inline", o + off), ("ptr", r.u64(o + off))):
            if not addr or (how == "ptr" and not mb._valid(addr)):
                continue
            try:
                t = r.read_str(addr)
            except Exception:
                t = None
            if t and 0 < len(t) < 80 and t.isprintable():
                print(f"  +{off:#x} {how}: {t!r}", flush=True)
