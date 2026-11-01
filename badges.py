"""Finds the serial badges of #1 to #10 on a screenshot, at any card size: #1 is a rainbow badge, #2-#9 gold and #10
silver, all with dark lettering ("#3"); #11 and up are dark with white lettering and aren't looked for. The shape,
not the size, is what is matched (a pill about twice as wide as it is tall), so it works on the big cards of a pack
reveal as well as on the small ones in the Index or a trade window. A digit is read when the digit bank knows it.
"""
import cv2
import numpy as np

import trade_badges


def _pills(mask, min_area):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a >= min_area and 1.5 <= w / h <= 3.6 and a >= 0.55 * w * h and 14 <= h <= 90:
            out.append((x, y, w, h))
    return out


def _lettering(box, min_pieces=1):
    """The badge has a short line of dark lettering ('#', one or two digits): about a tenth to a third of it,
    in at most four pieces (a button or label with a word on it has more)."""
    g = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
    dark = (g < 95)
    if not 0.07 <= float(dark.mean()) <= 0.4:
        return False
    n, _, st, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8))
    pieces = [i for i in range(1, n) if st[i][3] >= 0.35 * box.shape[0] and st[i][4] >= 8]
    return min_pieces <= len(pieces) <= 4


def numbered_badges(img, region=None):
    """[(tier, (x, y, w, h), serial_or_None)] for every #1-#10 badge: tier is '1', '2-9' or '10'.
    region = (x0, y0, x1, y1) as fractions of the picture, to look only there (a reveal's big gold title is not a badge)."""
    if region:
        h0, w0 = img.shape[:2]
        x0, y0, x1, y1 = int(region[0] * w0), int(region[1] * h0), int(region[2] * w0), int(region[3] * h0)
        return [(t, (x + x0, y + y0, w, h), s) for t, (x, y, w, h), s in numbered_badges(img[y0:y1, x0:x1])]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_, s_, v_ = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    found = []
    # gold: #2-#9
    gold = ((h_ >= 14) & (h_ <= 30) & (s_ > 110) & (v_ > 170))
    # (the lettering is dark, so it leaves holes in the pill: close them)
    gold = cv2.morphologyEx(gold.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x, y, w, h in _pills(gold, 250):
        if _lettering(img[y:y + h, x:x + w]):
            found.append(("2-9", (x, y, w, h)))
    # rainbow: #1 (many hues across a pill)
    colour = ((s_ > 110) & (v_ > 150))
    colour = cv2.morphologyEx(colour.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x, y, w, h in _pills(colour, 250):
        box = hsv[y:y + h, x:x + w]
        hues = box[(box[..., 1] > 110) & (box[..., 2] > 150)][:, 0]
        if len(hues) > 0.3 * w * h and (np.histogram(hues, bins=6, range=(0, 180))[0] > 0.08 * len(hues)).sum() >= 3 \
                and _lettering(img[y:y + h, x:x + w]):
            found.append(("1", (x, y, w, h)))
    # silver: #10 (pale grey, darker than a white panel)
    silver = ((s_ < 50) & (v_ > 150) & (v_ < 240)).astype(np.uint8)
    silver = cv2.morphologyEx(silver, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x, y, w, h in _pills(silver, 300):
        if h <= 70 and w * h * 0.75 <= cv2.countNonZero(silver[y:y + h, x:x + w]) and _lettering(img[y:y + h, x:x + w], 2):
            found.append(("10", (x, y, w, h)))
    # one badge can be picked up by two of the passes: keep the first (rainbow beats gold beats silver)
    order = {"1": 0, "2-9": 1, "10": 2}
    found.sort(key=lambda f: order[f[0]])
    kept = []
    for tier, (x, y, w, h) in found:
        if not any(abs(x - k[1][0]) < w * 0.6 and abs(y - k[1][1]) < h * 0.6 for k in kept):
            kept.append((tier, (x, y, w, h)))
    out = []
    for tier, (x, y, w, h) in kept:
        serial = {"1": "1", "10": "10"}.get(tier)
        if tier == "2-9":
            # the badge's own digit, if the bank knows it (crop scaled to the size the bank was made at)
            f = 26.0 / h
            crop = cv2.resize(img[max(0, y - 2):y + h + 2, max(0, x - 8):x + w + 8], None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            shapes = trade_badges.slots(crop, 1.0)
            if len(shapes) == 2:
                (c0, s0), (c1, s1) = trade_badges.match(shapes[0]), trade_badges.match(shapes[1])
                if c0 == "hash" and s0 > 0.6 and c1 and c1.isdigit() and s1 > 0.72 and 2 <= int(c1) <= 9:
                    serial = c1
        out.append((tier, (x, y, w, h), serial))
    return out


def label(tier, serial):
    return f"#{serial}" if serial else f"#{tier}"
