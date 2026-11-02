"""Live test of the memory Index sweep, without saving: opens the Index, lists the sub-tabs, and reads the #1s of a few
tabs (timed). Bot must be stopped. Usage: python tools/test_index_mem.py [rarity ...]"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import index_check  # noqa: E402
import mem_gui  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu  # noqa: E402

want = sys.argv[1:] or ["radiation", "atlantis", "ultra"]
g = Game()
ix = index_check.Index(g)
close_any_menu(g)
hit = mem_gui.locate(text="Index", screen="CardsUI")
g.click(hit[0], hit[1])
g.park_mouse()
end = time.time() + 3
while not ix.is_open() and time.time() < end:
    g.wait(0.1)
print("open:", ix.is_open(), flush=True)
ix.ensure_serial_sort()
for main in index_check.SUBTAB_BARS:
    print(main, [k for k, _ in ix.subtabs(main)], flush=True)
for rarity in want:
    main = next((m for m in index_check.SUBTAB_BARS if rarity in [k for k, _ in ix.subtabs(m)]), None)
    t = time.time()
    if main:
        ix.main_tab(main)
        ix._settle(1.2)
        lab = dict(ix.subtabs(main))[rarity]
        ix._click(lab)
        ix._settle(1.2)
        g.wait(0.3)
    else:
        ix.main_tab(next(m for m in index_check.MAIN_TABS if index_check._key(m) == rarity))
        ix._settle(1.2)
        g.wait(0.3)
    try:
        cards = ix.collect_ones(rarity)
    except index_check.IndexReadError as e:
        print(rarity, "ERROR", e, flush=True)
        tiles = ix.tiles()
        print("  filled:", [(s, f.get("name"), f.get("serial"), f.get("rarity")) for s, f, sh in tiles if f][:20])
        continue
    print(f"{rarity}: {len(cards)} #1s in {time.time() - t:.1f}s", flush=True)
    for c in cards:
        print("   ", c["name"], c["art"], c["income"], flush=True)
close_any_menu(g)
