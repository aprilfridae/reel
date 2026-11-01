"""Offline: read the player list off a saved Trade-menu screenshot (only what's on that one screen)."""
import sys

import cv2

sys.path.insert(0, ".")
from gifts import _words  # noqa: E402
from ocr import read_text  # noqa: E402

img = cv2.imread(sys.argv[1])


class G:
    def frame(self):
        return img

    def ui_scale(self, im):
        return 1.0


g = G()
sends = [(x, y) for t, x, y in _words(g, img, (0.2, 0.25, 0.8, 0.92)) if t.lower().startswith("send")]
for sx, sy in sends:
    cx = min((608, 957, 1306), key=lambda c: abs(c - sx))
    x0, x1 = cx - 170, cx + 170
    name = " ".join(read_text(img[int(sy - 74):int(sy - 47), x0:x1], scale=2).split())
    user = "".join(read_text(img[int(sy - 51):int(sy - 27), x0:x1], scale=2).split())
    print(f"send at ({sx:.0f},{sy:.0f}) -> name {name!r} user {user!r}")
