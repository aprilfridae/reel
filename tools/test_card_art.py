"""Time card_art.harvest() on the running game (no clicks), list what it found, and wait for the pictures to download.
Usage: python tools/test_card_art.py [--market] (--market: walk to the market first, then back to fishing)"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import card_art  # noqa: E402
from memory_backend import get_backend  # noqa: E402

mb = get_backend()
if "--market" in sys.argv:
    import market
    from game import Game
    g = Game()
    print("go to market:", market.go_to_market(g), flush=True)
    g.wait(2)
for i in range(2):
    t = time.time()
    n = card_art.harvest(mb)
    print(f"harvest #{i + 1}: {n} new picture(s) in {time.time() - t:.2f} s, offset {card_art._state['offset']:#x}", flush=True)
idx = card_art._index()
print(f"{len(idx)} artist(s) known", flush=True)
for e in list(idx.values())[:15]:
    print("  ", e["name"], e["ids"], flush=True)
multi = [e for e in idx.values() if len(set(e["ids"].values())) > 1]
print(f"artists with a different picture per rarity: {len(multi)}", flush=True)
for e in multi[:5]:
    print("  ", e["name"], e["ids"], flush=True)
t = time.time()
while card_art._state["queue"] and time.time() - t < 90:
    time.sleep(2)
have = sum(os.path.exists(card_art.file_for(a)) for e in idx.values() for a in e["ids"].values())
print(f"downloaded: {have} picture(s), still queued {len(card_art._state['queue'])}, {time.time() - t:.0f} s", flush=True)
print("art_for('zombie griff'):", card_art.art_for("zombie griff"), "| art_for('vnnepire'):", card_art.art_for("vnnepire"))
if "--market" in sys.argv:
    from packs import close_any_menu, teleport_to_fishing
    close_any_menu(g)
    print("back to fishing:", teleport_to_fishing(g), flush=True)
