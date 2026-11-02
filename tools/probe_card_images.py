"""Can a card's picture be read from memory? Walks to the market and, for the first two listings, prints every
object in the card (class, name, size) and, for image objects, every asset string ("rbxassetid://..." etc.) found in
the object's memory: inline at an offset or behind a pointer at that offset. Then goes back to fishing.
Run on the bot PC's desktop with the bot paused. Usage: python tools/probe_card_images.py"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import mem_gui  # noqa: E402
import mem_market  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

ASSET = re.compile(rb"(rbxassetid://\d+|rbxasset://[\x21-\x7e]+|rbxthumb://[\x21-\x7e]+|https?://[\x21-\x7e]+)")
IMAGE_CLASSES = {"ImageLabel", "ImageButton", "ViewportFrame", "Decal", "Texture", "VideoFrame"}


def asset_strings(mb, inst, span=0x1400):
    """{offset: string} of asset-looking strings stored inline at, or behind a pointer at, each 8-byte offset."""
    r = mb.r
    raw = r.read(inst, span) or b""
    found = {}
    for m in ASSET.finditer(raw):
        found[f"raw+{m.start():#x}"] = m.group(0).decode()
    for off in range(0, len(raw) - 8, 8):
        s = r.read_str(inst + off)  # an std::string kept in the object
        if s and ASSET.match(s.encode("utf-8", "replace")):
            found[f"str@{off:#x}"] = s
        p = int.from_bytes(raw[off:off + 8], "little")
        if mb._valid(p):
            s = r.read_str(p)  # a pointer to one
            if s and ASSET.match(s.encode("utf-8", "replace")):
                found[f"ptr@{off:#x}"] = s
            else:
                d = r.read(p, 64) or b""
                m = ASSET.match(d)
                if m:
                    found[f"ptr->raw@{off:#x}"] = m.group(0).decode()
    return found


g = Game()
print("go to market:", market.go_to_market(g), flush=True)
g.wait(2)
gui = mem_gui.gui()
mb = gui.mb
grid = mem_market._grid(mb)
print("grid:", hex(grid) if grid else None, flush=True)
summary = []
done = 0
seen = set()
for d, entry in mb._walk(grid, depth=3, max_nodes=2000):
    if d == 0 or mb._class_name(entry) != "Frame":
        continue
    texts = mem_market._texts(mb, entry)
    bid = next((t for t in texts if t[0].upper() == "BID"), None)
    if bid is None or bid[4] in seen or not gui.is_shown(bid[4]):
        continue
    seen.add(bid[4])
    card = mem_market.parse(texts)
    print(f"\n=== listing: {card.get('name')} #{card.get('serial')} {card.get('rarity')}", flush=True)
    for dd, o in mb._walk(entry, depth=10, max_nodes=400):
        cls = mb._class_name(o)
        geo = gui.geom(o)
        size = f"{geo[2]:.0f}x{geo[3]:.0f}" if geo else "-"
        line = f"{'  ' * dd}{cls} {mb._name(o)!r} {size}"
        if cls in ("TextLabel", "TextButton"):
            line += f" text={mb._content_text(o)!r}"
        print(line, flush=True)
        if cls in IMAGE_CLASSES or (cls and "Image" in cls):
            hits = asset_strings(mb, o)
            for k, v in hits.items():
                print(f"{'  ' * dd}    {k}: {v}", flush=True)
            summary.append({"card": card.get("name"), "rarity": card.get("rarity"), "name": mb._name(o), "class": cls,
                            "size": size, "assets": hits})
    done += 1
    if done >= 2:
        break
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "card_images.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=1)
close_any_menu(g)
print("\nback to fishing:", teleport_to_fishing(g), flush=True)
