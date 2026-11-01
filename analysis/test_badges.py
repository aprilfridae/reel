"""Offline: where does badges.numbered_badges() find #1-#10 badges on the saved trade screenshots?"""
import sys

import cv2

sys.path.insert(0, ".")
import badges  # noqa: E402

for path in sys.argv[1:]:
    img = cv2.imread(path)
    out = badges.numbered_badges(img, (0.2, 0.28, 0.8, 0.76) if "reveal" in path or "now2" in path else None)
    print(path, "->", [(badges.label(t, s), (b[0], b[1])) for t, b, s in out])
