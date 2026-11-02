"""With the Card Market open: Who owns? tab -> search an artist -> open it -> a rarity, writing the showing MarketUI
objects (class, name, text, geometry, depth) after each step to tools/dump_whoowns.txt. Never presses Join.
Usage: python tools/probe_whoowns.py [artist] [rarity]"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import market  # noqa: E402
import mem_gui  # noqa: E402
from game import Game  # noqa: E402
from ui_keys import clear_field, type_text  # noqa: E402

artist = sys.argv[1] if len(sys.argv) > 1 else "lluy"
rarity = sys.argv[2] if len(sys.argv) > 2 else "Common"
game = Game()
g = mem_gui.gui()
mb = g.mb
out = open(os.path.join(HERE, "dump_whoowns.txt"), "w", encoding="utf-8")


def dump(tag):
    sg = mem_gui.screen("MarketUI")
    out.write(f"===== {tag}\n")
    for d, o in mb._walk(sg, 22, 30000):
        if not g.is_shown(o):
            continue
        c = mb._class_name(o) or "?"
        if c.startswith("UI"):
            continue
        t = mb._content_text(o) if c in mem_gui.TEXT_CLASSES else None
        geo = g.geom(o)
        gs = f"({geo[0]:.0f},{geo[1]:.0f} {geo[2]:.0f}x{geo[3]:.0f})" if geo else ""
        out.write(f"{'  ' * d}{c} '{mb._name(o)}' {gs} {t!r}\n" if t else f"{'  ' * d}{c} '{mb._name(o)}' {gs}\n")
    out.flush()


print("market open:", market.market_open(), flush=True)
if not market.market_open():
    print("open the market first", flush=True)
    sys.exit()
tab = mem_gui.locate(text="Who owns", screen="MarketUI", contains=True)
print("tab", tab, flush=True)
game.click(tab[0], tab[1]); game.park_mouse(); game.wait(1.5)
dump("who owns tab")
box = market._search_box_mem(game.size()[1])
print("search box", box, flush=True)
game.click(box[1], box[2]); game.wait(0.3); clear_field(); type_text(artist); game.wait(2.0)
dump(f"searched {artist}")
tile = mem_gui.locate(text=artist, screen="MarketUI")
print("artist tile", tile, flush=True)
if tile:
    game.click(tile[0], tile[1]); game.park_mouse(); game.wait(2.0)
    dump("artist page")
    chip = mem_gui.locate(text=rarity, screen="MarketUI", exact=False)
    print("chip", chip, flush=True)
    if chip:
        game.click(chip[0], chip[1]); game.park_mouse(); game.wait(5.0)
        dump(f"rarity {rarity}")
out.close()
print("done", flush=True)
