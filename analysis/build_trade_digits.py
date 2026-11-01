"""Builds templates/trade_digits/ (the bank trade_badges.py matches digits against) from screenshots of the
trade window whose badge numbers were read by eye. Usage: python analysis/build_trade_digits.py [--test]"""
import os
import shutil
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import trade_badges as tb  # noqa: E402

COLS = (285, 449, 613, 777, 941)
BADGE_Y = (351, 583, 816)
SETS = [
    ("analysis/daily/tr_4.png", "1 1 3 3 4 4 10 47 59 124 165 199 203 207 298", BADGE_Y),
    ("analysis/daily/tr_2.png", "47 441 433 428 1024 1100 165 384 387 4 4 1 3 7248 4386", BADGE_Y),
    ("analysis/daily/tr_0.png", "1 1 1 1 1 1 1 1 1 1 1 1 1 1 1", BADGE_Y),
    ("analysis/daily/sc_2.png", "493 648 1 1 1 1 1 1 1 1", (383, 616)),
]
OUT = "templates/trade_digits"


def tiles(ys=BADGE_Y):
    return [(c, by) for by in ys for c in COLS]


def build(sets):
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    count = {}
    for path, labels, ys in sets:
        img = cv2.imread(path)
        for (c, by), lab in zip(tiles(ys), labels.split()):
            shapes = tb.slots(tb.badge_crop(img, c, by))
            names = ["hash"] + list(lab)
            if len(shapes) != len(names):
                print(f"  skip {os.path.basename(path)} tile ({c},{by}) '#{lab}': found {len(shapes)} shapes")
                continue
            for name, sh in zip(names, shapes):
                count[name] = count.get(name, 0) + 1
                cv2.imwrite(f"{OUT}/{name}_{count[name]}.png", sh.astype(np.uint8) * 255)
    print("bank:", dict(sorted(count.items())))


def test(path, labels, ys=BADGE_Y):
    img = cv2.imread(path)
    tb._BANK.clear()
    tb.bank()
    ok = 0
    for (c, by), lab in zip(tiles(ys), labels.split()):
        got = tb.read_serial(img, c, by)
        ok += got == lab
        if got != lab:
            print(f"   {os.path.basename(path)} ({c},{by}) expected #{lab}, read {got}")
    print(f"{os.path.basename(path)}: {ok}/{len(labels.split())} read right")


if __name__ == "__main__":
    if "--test" in sys.argv:
        # leave one screenshot out of the bank and read it
        for held in range(len(SETS)):
            build([s for i, s in enumerate(SETS) if i != held])
            test(*SETS[held])
    build(SETS)
    for p, l, y in SETS:
        test(p, l, y)
