"""Does switching chat off (the speech-bubble button) show in memory? Prints ExperienceChat's appLayout / chatWindow /
channelBar shown state and the message count, clicks the chat button, prints again, and clicks it back.
Usage: python tools/probe_chat_toggle.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mem_gui  # noqa: E402
from game import Game  # noqa: E402

g = Game()
gui = mem_gui.gui()
mb = gui.mb
core = next(s for s in mb._children(mb.data_model) if mb._class_name(s) == "CoreGui")
ec = next(c for c in mb._children(core) if mb._name(c) == "ExperienceChat")
app = mb._find_child(ec, name="appLayout")
win = mb._find_child(app, name="chatWindow")
bar = mb._find_child(app, name="channelBar")
inp = mb._find_child(app, name="chatInputRow")
icon = None
for top in mb._children(core):
    if mb._name(top) == "TopBarApp":
        for d, o in mb._walk(top, depth=30, max_nodes=8000):
            if mb._name(o) == "IntegrationIcon" and mb._content_text(o) == "speech-bubble-align-center":
                icon = o
print("icon", icon and gui.geom(icon), flush=True)


def state(tag):
    print(tag, {"ec_enabled": mb.r.u8(ec + 0x48c) if hasattr(mb.r, "u8") else None,
                "app": gui.is_shown(app), "win": gui.is_shown(win), "bar": gui.is_shown(bar), "input": gui.is_shown(inp),
                "icon": mb._content_text(icon), "icon_parent": [mb._name(mb._parent(icon))],
                "icons": [mb._content_text(o) for d, o in mb._walk(mb._parent(mb._parent(icon)), depth=4, max_nodes=50)
                          if mb._class_name(o) == "TextLabel"]}, flush=True)


state("before")
geo = gui.geom(icon)
g.click(geo[0], geo[1])
g.park_mouse()
g.wait(1.0)
state("after 1 click")
g.click(geo[0], geo[1])
g.park_mouse()
g.wait(1.0)
state("after 2 clicks")
g.wait(3.0)
state("3s later")
