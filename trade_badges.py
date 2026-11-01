"""Reads the serial badge ("#47") on a card tile in the trade window.

Windows OCR reads 3-4 digit badges but misses most 1-2 digit ones, and #1-#9 sit on gold or rainbow badges
with dark lettering. The badge font is bold with touching characters, all about the same width, so the
lettering is cut into equal slots (the number of characters follows from its width) and each slot is matched
against a bank of labelled ones (templates/trade_digits/<char>_<n>.png, made by analysis/build_trade_digits.py).
"""
import glob
import os

import cv2
import numpy as np

from game import TEMPLATES

SLOT = 10.8  # pixels from one character to the next at UI scale 1
SIZE = (8, 12)  # slots are compared at this size (w, h)
_BANK = []


def bank():
    if not _BANK:
        from paths import APP
        for folder in (os.path.join(TEMPLATES, "trade_digits"), os.path.join(APP, "trade_digits")):
            for f in glob.glob(os.path.join(folder, "*.png")):
                _BANK.append((os.path.basename(f).split("_")[0], cv2.imread(f, cv2.IMREAD_GRAYSCALE) > 0))
    return _BANK


def badge_crop(img, cx, cy, s=1.0):
    """The strip of the tile where the badge sits (cx: the tile's centre column, cy: the badge's row)."""
    return img[int(cy - 11 * s):int(cy + 15 * s), int(cx - 16 * s):int(cx + 68 * s)]


def lettering(crop, s=1.0):
    """Mask of the badge's lettering (dark on gold/rainbow, light on the dark badges) and its x-range,
    or (None, None)."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    best = (0, None, None)
    for m in (g < 85, g > 215):
        n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
        cand = [(st[i][0], st[i][1], st[i][2], st[i][3], st[i][4], i) for i in range(1, n)
                if 8 * s <= st[i][3] <= 15 * s and 2 <= st[i][2] <= 24 * s and st[i][4] >= 14 * s * s
                and 3 * s <= st[i][1] <= 18 * s]
        if not cand:
            continue
        # the lettering is one tight row of shapes: start from the biggest, take neighbours
        # whose top is level with it and that follow on closely (photo speckle is left out)
        cand.sort()
        seed = max(range(len(cand)), key=lambda k: cand[k][4])
        group = [cand[seed]]
        for k in range(seed - 1, -1, -1):
            x, y, w, h, a, i = cand[k]
            if abs(y - group[0][1]) <= 3 * s and group[0][0] - (x + w) <= 4 * s:
                group.insert(0, cand[k])
            else:
                break
        for k in range(seed + 1, len(cand)):
            x, y, w, h, a, i = cand[k]
            if abs(y - group[-1][1]) <= 3 * s and x - (group[-1][0] + group[-1][2]) <= 4 * s:
                group.append(cand[k])
            else:
                break
        keep = np.zeros(m.shape, bool)
        for x, y, w, h, a, i in group:
            keep |= lab == i
        xs = [group[0][0], group[-1][0] + group[-1][2]]
        if keep.sum() > best[0]:
            best = (int(keep.sum()), keep, (min(xs), max(xs)))
    return best[1], best[2]


def slots(crop, s=1.0):
    """The lettering as a list of normalized binary shapes, one per character, left to right."""
    mask, span = lettering(crop, s)
    if mask is None:
        return []
    x0, x1 = span
    ys = np.where(mask.any(axis=1))[0]
    y0, y1 = ys.min(), ys.max() + 1
    n = max(1, int(round((x1 - x0) / (SLOT * s))))
    out = []
    for i in range(n):
        a, b = int(round(x0 + i * (x1 - x0) / n)), int(round(x0 + (i + 1) * (x1 - x0) / n))
        piece = mask[y0:y1, a:b]
        cols = np.where(piece.any(axis=0))[0]
        if not len(cols):
            out.append(np.zeros(SIZE[::-1], bool))
            continue
        piece = piece[:, cols.min():cols.max() + 1].astype(np.uint8) * 255
        out.append(cv2.resize(piece, SIZE, interpolation=cv2.INTER_AREA) > 100)
    return out


def match(shape):
    best, best_score = None, 0.0
    for ch, t in bank():
        score = np.logical_and(shape, t).sum() / max(1, np.logical_or(shape, t).sum())
        if score > best_score:
            best, best_score = ch, score
    return best, best_score


def tier(crop):
    """'1' (rainbow), '2-9' (gold) or '' (silver / dark: #10 and up) from the badge's colour."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    colour = hsv[(hsv[..., 1] > 110) & (hsv[..., 2] > 150)]
    if len(colour) < 0.25 * hsv.shape[0] * hsv.shape[1]:
        return ""
    hues = np.histogram(colour[:, 0], bins=6, range=(0, 180))[0]
    if (hues > 0.1 * len(colour)).sum() >= 3:
        return "1"
    gold = ((colour[:, 0] >= 12) & (colour[:, 0] <= 30)).mean()
    return "2-9" if gold > 0.7 else ""


def _ocr_number(crop):
    """OCR vote over a few clean-ups of the badge; only trusted for 3-4 digit numbers (short ones are missed)."""
    import re
    from collections import Counter

    from ocr import read_text
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    votes = Counter()
    for v in (crop, cv2.cvtColor(255 - g, cv2.COLOR_GRAY2BGR),
              cv2.cvtColor(np.where(g > 190, 255, 0).astype(np.uint8), cv2.COLOR_GRAY2BGR)):
        v = cv2.copyMakeBorder(v, 10, 10, 10, 10, cv2.BORDER_REPLICATE)
        for scale in (3, 5):
            m = re.search(r"#\s*(\d{3,5})", read_text(v, scale=scale))
            if m:
                votes[m.group(1)] += 1
    top = votes.most_common(1)
    return top[0][0] if top and top[0][1] >= 3 else None


def _learn(shapes, text):
    """Keep the shapes of a badge whose number is certain (read by OCR): the bank grows with use."""
    import time

    from paths import APP
    d = os.path.join(APP, "trade_digits")
    os.makedirs(d, exist_ok=True)
    for ch, sh in zip(["hash"] + list(text), shapes):
        _BANK.append((ch, sh))
        cv2.imwrite(os.path.join(d, f"{ch}_{int(time.time() * 1000) % 10**9}.png"), sh.astype(np.uint8) * 255)


def read_serial(img, cx, cy, s=1.0, min_score=0.72):
    """The badge's number as text: '47'; '1' for the rainbow badge; '2-9' for a gold one whose digit isn't known;
    None when it can't be read with confidence. 3-4 digit numbers are also checked by OCR, which teaches the bank."""
    crop = badge_crop(img, cx, cy, s)
    t = tier(crop[:, 8:])
    if t == "1":
        return "1"
    shapes = slots(crop, s)
    read = None
    if len(shapes) >= 2:
        chars = []
        for sh in shapes:
            ch, score = match(sh)
            if ch is None or score < min_score:
                chars = None
                break
            chars.append(ch)
        if chars and chars[0] == "hash" and "".join(chars[1:]).isdigit():
            read = "".join(chars[1:])
    if len(shapes) >= 4 and read is None:  # 3+ digits: OCR knows them
        text = _ocr_number(crop)
        if text and len(text) + 1 == len(shapes):
            _learn(shapes, text)
            return text
    return read or (t or None)
