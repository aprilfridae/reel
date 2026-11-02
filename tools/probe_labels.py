"""Prints the event banner (EventHUD), the auto-roll label (CardsUI AutoPill) and the catch popup (FishingUI) as memory
has them, both text fields (+0xC60 pointer and +0xE08 inline), a few times a second for N seconds.
Usage: python tools/probe_labels.py [seconds]"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3
gui = mem_gui.gui()
mb = gui.mb


def sg(name):
    return next((s for s in mb._children(mb.player_gui) if mb._name(s) == name), None)


def labels(root, depth=6):
    out = []
    for d, o in mb._walk(root, depth=depth, max_nodes=400):
        if mb._class_name(o) in ("TextLabel", "TextButton"):
            out.append((mb._content_text(o), mb.r.read_str(o + 0xE08), gui.is_shown(o)))
    return out


cards = sg("CardsUI")
root = mb._find_child(cards, name="Root")
pill = mb._find_child(root, name="AutoPill")
end = time.time() + secs
last = None
while time.time() < end:
    now = (labels(sg("EventHUD")), labels(pill, 2),
           [x for x in labels(sg("FishingUI"), 4) if x[2]])
    if now != last:
        last = now
        print(time.strftime("%H:%M:%S"), flush=True)
        for part in now:
            print("   ", part, flush=True)
    time.sleep(0.3)
