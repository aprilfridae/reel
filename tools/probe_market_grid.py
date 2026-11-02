"""Dumps MarketUI (the market must be open): every object's class, name, shown flag and text, and every
ScrollingFrame with how many BID labels are under it. Writes dump_market.txt. Usage: python tools/probe_market_grid.py"""
import collections
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mem_gui  # noqa: E402

gui = mem_gui.gui()
mb = gui.mb
sg = next((s for s in mb._children(mb.player_gui) if mb._name(s) == "MarketUI"), None)
print("MarketUI:", sg and hex(sg), "screen_on:", gui.screen_on("MarketUI"), "children:", len(mb._children(sg)), flush=True)
classes = collections.Counter()
lines = []
for d, o in mb._walk(sg, depth=14, max_nodes=30000):
    cls = mb._class_name(o)
    classes[cls] += 1
    lines.append(f"{'  ' * d}{cls} {mb._name(o)!r} shown={gui.is_shown(o)} {mb._content_text(o)!r}")
    if cls == "ScrollingFrame":
        bids = sum(1 for _, t in mb._walk(o, 8, 6000) if (mb._content_text(t) or "").strip().upper() == "BID")
        print(f"ScrollingFrame {mb._name(o)!r} depth {d} shown={gui.is_shown(o)} geom={gui.geom(o)} BIDs={bids}",
              flush=True)
print("nodes:", len(lines), dict(classes.most_common(12)), flush=True)
bid_labels = [ln for ln in lines if ln.rstrip().endswith("'BID'")]
print("BID labels anywhere:", len(bid_labels), flush=True)
with open(os.path.join(HERE, "dump_market.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines[:60]), flush=True)
