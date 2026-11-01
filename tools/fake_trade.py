"""Offline: fill the local website's trade.json with a believable open trade, using tiles read off a saved trade
window screenshot (so the pictures are real). Usage: python tools/fake_trade.py <trade window screenshot>"""
import sys
import time

import cv2

sys.path.insert(0, ".")
import trade  # noqa: E402
import webstate  # noqa: E402

img = cv2.imread(sys.argv[1])


class G:
    def ui_scale(self, im):
        return 1.0


cards = []
for ax, ay in trade._anchors(img, 1.0):
    if ay + 112 + 92 > trade.GRID[3] - 12:
        continue
    t = trade.read_tile(G(), img, ax, ay, 1.0)
    t.pop("_col"), t.pop("_click")
    cards.append(t)
print(len(cards), [c["name"] for c in cards])
for c in cards[2:5]:
    c["wanted"] = True
mine = cards
webstate.update("trade.json", {}, lambda t: {**t, "open": "cable", "incoming": None, "mine": mine, "theirs": cards[::-1],
                                             "wanted": [c for c in mine if c["wanted"]], "wanted_count": 3,
                                             "scanned_at": time.strftime("%H:%M:%S"), "snap": int(time.time()), "search": None,
                                             "offer": {"at": time.strftime("%H:%M:%S"),
                                                       "mine": {"cards": cards[2:4], "ready": False, "summary": "2 cards +24.0K/s", "total": 2, "coins": "1.0K"},
                                                       "theirs": {"cards": cards[7:8], "ready": True, "summary": "1 card +21.6K/s", "total": 1, "coins": ""}},
                                             "cmds": [], "ts": time.time()})
