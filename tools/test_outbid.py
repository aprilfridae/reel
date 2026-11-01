"""Offline: find and read the outbid notice in a saved picture. Usage: python tools/test_outbid.py picture.png
(saves the picture with the box drawn on it as <picture>_box.png)"""
import sys

import cv2

sys.path.insert(0, ".")
import outbid  # noqa: E402

img = cv2.imread(sys.argv[1])
box = outbid.find_box(img)
print("box", box)
if box:
    print(outbid.read_notice(img, box))
    x0, y0, x1, y1 = box
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 255, 0), 2)
    cv2.imwrite(sys.argv[1].rsplit(".", 1)[0] + "_box.png", img)
