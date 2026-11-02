"""Which "menus" does packs.open_menus() see (their X's path, class, text, place)? Usage: python tools/probe_open_menus.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
import packs  # noqa: E402

g = mem_gui.gui()
mb = g.mb
for x in packs.open_menus():
    path, o = [], x
    while o and len(path) < 9:
        path.append(f"{mb._class_name(o)}:{mb._name(o)}")
        o = mb._parent(o)
    print(repr(mb._content_text(x)), g.geom(x), " < ".join(path), flush=True)
