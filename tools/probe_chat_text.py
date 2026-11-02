"""Where a chat message label keeps its text: for the first few PrefixText / BodyText labels of Roblox's chat, every
offset that holds a readable string (inline or by pointer). Usage: python tools/probe_chat_text.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
r = mb.r


def strat(addr):
    n = r.u32(addr + 0x10)
    if n is None or not (0 < n <= 4000):
        return None
    if n > 15:
        p = r.u64(addr)
        if not mb._valid(p):
            return None
        d = r.read(p, n)
    else:
        d = r.read(addr, n)
    if not d or len(d) != n:
        return None
    try:
        s = d.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return s if sum(ch.isprintable() for ch in s) >= len(s) * 0.8 else None


core = next(s for s in mb._children(mb.data_model) if mb._class_name(s) == "CoreGui")
ec = next(c for c in mb._children(core) if mb._name(c) == "ExperienceChat")
labels = []
for d, o in mb._walk(ec, depth=30, max_nodes=20000):
    if mb._name(o) in ("PrefixText", "BodyText") and mb._class_name(o) == "TextLabel":
        labels.append(o)
print(len(labels), "labels", flush=True)
for lab in labels[:6]:
    print("==", mb._name(lab), hex(lab), "parent", mb._name(mb._parent(mb._parent(lab))), flush=True)
    for off in range(0x0, 0x1800, 8):
        s = strat(lab + off)
        if s and off not in (0x68,):
            print(f"   +{off:#x} inline {s[:200]!r}", flush=True)
        p = r.u64(lab + off)
        if mb._valid(p):
            s = strat(p)
            if s and len(s) > 1:
                print(f"   +{off:#x} ptr    {s[:200]!r}", flush=True)
