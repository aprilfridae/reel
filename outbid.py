"""The game's "YOU WERE OUTBID!" notice: a black box with a red border just under the top bar, with the card on the
left and two lines of text ("<player> bid 22.2B on <card> (<rarity>) (you bid 21.1B)" and "+21.1B coins back").

Looked for while fishing (cheap: a count of border-red pixels; the text is only read when there are enough). Each
notice goes to outbid.json for the website, with a picture of it.
"""
import os
import re
import time

import cv2
import numpy as np

import webstate
from ocr import read_lines
from paths import APP

REGION = (0.18, 0.03, 0.82, 0.32)  # where the notice can be, as fractions of the screen
CHECK_EVERY = 1.0  # seconds between looks
PICS = os.path.join(APP, "web", "static", "outbid")
KEEP = 50  # notices kept for the website
_AMT = r"([\d.,]+\s*[KMBTQ]?)"
_LINE = re.compile(rf"(\S+)\s+bid\s+{_AMT}\s+on\s+(.+?)\s*\(([^)]*)\)\s*\(?\s*you\s+bid\s+{_AMT}", re.I)


def _red(img):
    return (img[..., 2] > 190) & (img[..., 1] < 110) & (img[..., 0] < 110)


def find_box(img):
    """(x0, y0, x1, y1) of the notice in img if one is up, else None. The box is the red border: a wide red frame
    whose inside is nearly black."""
    h, w = img.shape[:2]
    rx0, ry0, rx1, ry1 = int(REGION[0] * w), int(REGION[1] * h), int(REGION[2] * w), int(REGION[3] * h)
    if h < 400:  # a cut-out picture of the notice (tests): look everywhere
        rx0, ry0, rx1, ry1 = 0, 0, w, h
    red = _red(img[ry0:ry1, rx0:rx1])
    if red.mean() < 0.004:
        return None
    n, _, stats, _ = cv2.connectedComponentsWithStats(red.astype(np.uint8), connectivity=8)
    for x, y, bw, bh, area in sorted(stats[1:], key=lambda s: -s[2]):
        if bw < 0.2 * (rx1 - rx0) or bh < 0.05 * h * (1080 / max(h, 1080)) or bw < 2 * bh:
            continue  # not a wide frame
        inside = img[ry0 + y + bh // 4: ry0 + y + 3 * bh // 4, rx0 + x + bw // 3: rx0 + x + bw - 20]
        if inside.size and inside.mean() < 60 and area < 0.25 * bw * bh:  # a thin frame around a dark box
            return rx0 + x, ry0 + y, rx0 + x + bw, ry0 + y + bh
    return None


def read_notice(img, box):
    """The notice's text: {"text", "by", "amount", "card", "rarity", "mine"} (the fields that could be read)."""
    x0, y0, x1, y1 = box
    text_part = img[y0 + 4:y1 - 4, x0 + int((x1 - x0) * 0.17):x1 - 4]  # right of the card picture
    lines = [ln.strip() for ln in read_lines(text_part, scale=1) if ln.strip()]
    if not any("outbid" in ln.lower().replace("0", "o") for ln in lines):
        return None
    rest = [ln for ln in lines if "outbid" not in ln.lower().replace("0", "o")]
    out = {"text": " / ".join(rest)}
    m = _LINE.search(" ".join(rest))
    if m:
        out.update(by=m.group(1), amount=m.group(2).replace(" ", ""), card=m.group(3).strip(),
                   rarity=m.group(4).strip(), mine=m.group(5).replace(" ", ""))
    return out


class Watcher:
    def __init__(self, log=print):
        self.log = log
        self.checked = 0.0
        self.last = None  # (text, when) of the notice last saved: one notice stays up for several looks

    def poll(self, img):
        """Cheap look (whole frames while fishing). Saves and logs a new notice; True if one was found."""
        now = time.time()
        if now - self.checked < CHECK_EVERY:
            return False
        self.checked = now
        box = find_box(img)
        if not box:
            return False
        notice = read_notice(img, box)
        if not notice:
            return False
        if self.last and self.last[0] == notice["text"] and now - self.last[1] < 120:
            return False
        self.last = (notice["text"], now)
        os.makedirs(PICS, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S") + ".jpg"
        x0, y0, x1, y1 = box
        cv2.imwrite(os.path.join(PICS, name), img[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4],
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        entry = {**notice, "at": time.strftime("%H:%M:%S"), "ts": now, "image": name}
        webstate.update("outbid.json", [], lambda lst: (lst + [entry])[-KEEP:])
        if notice.get("by"):
            self.log(f"Outbid! {notice['by']} bid {notice['amount']} on {notice['card']} ({notice['rarity']}), "
                     f"you bid {notice['mine']}")
        else:
            self.log(f"Outbid! {notice['text']}")
        return True
