"""Screenshot how the game draws a card in every rarity, for styling the website's cards: Who owns? -> krby, then each
rarity button in turn; the card preview on the left is redrawn in that rarity and saved to tools/rarity/<rarity>.png.
Goes back to fishing after. Usage: python tools/shot_rarity_chips.py"""
import os
import sys

import cv2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market  # noqa: E402
import whoowns  # noqa: E402
from game import Game  # noqa: E402
from packs import close_any_menu, teleport_to_fishing  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rarity")
PREVIEW = (-606, -212, -418, 44)  # the card preview's edges from the window centre, at UI scale 1 (1920x1080)

g = Game()
os.makedirs(OUT, exist_ok=True)
print("go to market:", market.go_to_market(g), flush=True)
print("navigate:", whoowns.navigate(g, "krby", "common"), flush=True)
for rarity, off in whoowns.CHIPS.items():
    img = g.frame()
    g.click(*whoowns._at(g, img, off))
    g.park_mouse()
    g.wait(1.2)
    img = g.frame()
    h, w = img.shape[:2]
    s = g.ui_scale(img)
    x0, y0, x1, y1 = (int(w / 2 + PREVIEW[0] * s), int(h / 2 + PREVIEW[1] * s), int(w / 2 + PREVIEW[2] * s), int(h / 2 + PREVIEW[3] * s))
    cv2.imwrite(os.path.join(OUT, f"{rarity}.png"), img[y0:y1, x0:x1])
    print("saved", rarity, flush=True)
close_any_menu(g)
print("back to fishing:", teleport_to_fishing(g), flush=True)
