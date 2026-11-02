"""Finds Roblox's chat in memory: lists the DataModel's services, then dumps CoreGui's ExperienceChat (or whatever in
CoreGui holds chat text) to tools/dump_chat.txt. Usage: python tools/probe_chat.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memory_backend import get_backend  # noqa: E402
import mem_gui  # noqa: E402

mb = get_backend()
gui = mem_gui.gui()
dm = mb.data_model
svc = mb._children(dm)
core = next((s for s in svc if mb._class_name(s) == "CoreGui"), None)
print("CoreGui:", hex(core) if core else None, flush=True)
if core:
    print("CoreGui children:", [(mb._name(c), mb._class_name(c)) for c in mb._children(core)], flush=True)
    out = []
    for top in mb._children(core):
        if mb._name(top) not in ("ExperienceChat", "RobloxGui", "TopBarApp"):
            continue
        for d, o in mb._walk(top, depth=40, max_nodes=40000):
            cls = mb._class_name(o) or "?"
            t = mb._content_text(o) if cls in ("TextLabel", "TextButton", "TextBox") else None
            if mb._name(top) != "ExperienceChat" and not t:
                continue
            g = gui.geom(o) if cls.startswith(("Text", "Frame", "Scrolling", "Image")) else None
            out.append(f"{'  ' * d}{cls} {mb._name(o)!r} {hex(o)}"
                       f"{f' ({g[0]:.0f},{g[1]:.0f} {g[2]:.0f}x{g[3]:.0f})' if g else ''}"
                       f"{f' shown={gui.is_shown(o)}' if g else ''}{f' :: {t!r}' if t else ''}")
        out.append("")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dump_chat.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("wrote", p, len(out), "lines", flush=True)
tcs = next((s for s in svc if mb._class_name(s) == "TextChatService"), None)
if tcs:
    print("TextChatService:", [(d, mb._name(o), mb._class_name(o)) for d, o in mb._walk(tcs, depth=4, max_nodes=200)], flush=True)
