"""For market listings whose name doesn't read (fancy-letter names come out as the footer, "Underground RNG"), dump
every object in the tile: class, name, and the raw string at the text offset (length and first bytes), to see where
the artist's name is. Walks to the market and back to fishing. Usage: python tools/probe_fancy_names.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import mem_gui  # noqa: E402
import mem_market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

g = Game()
print("go to market:", market.go_to_market(g), flush=True)
gui = mem_gui.gui()
mb = gui.mb
r = mb.r
grid = mem_market._grid(mb)
memo = {}
cards = mem_market.listings(shown_only=False, memo=memo) or []
print("names:", [c.get("name") for c in cards], flush=True)
bad = [e for e in memo if not isinstance(e, tuple)
       and (mem_market.parse(memo[e]).get("name") or "").startswith("Underground")]
print(f"{len(bad)} tile(s) without a readable name", flush=True)
for entry in bad[:2]:
    print("\n===== tile", hex(entry), flush=True)
    for d, o in mb._walk(entry, depth=10, max_nodes=300):
        cls = mb._class_name(o)
        line = f"{'  ' * d}{cls} {mb._name(o)!r}"
        if cls in ("TextLabel", "TextButton"):
            for off in (0xC60, 0xC40, 0xC80, 0xD00, 0xE00):
                p = r.u64(o + off)
                n = r.u32(p + 0x10) if p else None
                raw = None
                if n and 0 < n < 4096:
                    raw = r.read(r.u64(p) if n > 15 else p, min(n, 60))
                line += f" | +{off:#x} n={n} {raw!r}"
            line += f" | text={mb._content_text(o)!r}"
        print(line, flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
