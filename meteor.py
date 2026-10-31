"""The meteor event: meteors land in red circles near spawn; standing in one when it
lands gives a Meteor Pack.

Before the event starts: teleport to Spawn, tilt the camera to look down (hold
right-click and drag down) and zoom out, so the circles are visible around the
character (who stays in the middle of the screen). Then keep walking to the nearest
red circle until the event is over.

Not seen live yet: the circle colors and sizes are a best guess, so every few
seconds a screenshot goes to meteor_debug/ to tune this from.
"""
import os
import time

import cv2
import numpy as np

from game import HERE

DEBUG_DIR = os.path.join(HERE, "meteor_debug")
CAMERA_DRAG = 600  # pixels of downward mouse movement while holding right-click
ZOOM_OUT_NOTCHES = 80  # as far out as the game allows: player tiny, far circles visible
CLOSE_ENOUGH = 15  # pixels from the character that count as inside (zoomed far out)


def find_red_circles(img, scale):
    """Centers of red circles on the ground, nearest-to-character first."""
    h, w = img.shape[:2]
    # Leave out the UI around the edges (side buttons, top bar, roll button)
    x0, x1 = int(w * 0.12), int(w * 0.85)
    y0, y1 = int(h * 0.1), int(h * 0.8)
    area = img[y0:y1, x0:x1].astype(np.int16)
    b, g, r = area[..., 0], area[..., 1], area[..., 2]
    red = ((r > 160) & (g < 90) & (b < 90)).astype(np.uint8) * 255
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(red)
    cx, cy = w / 2, h / 2
    found = []
    for i in range(1, n):
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        fill = stats[i, cv2.CC_STAT_AREA] / float(bw * bh)
        # A circle on the ground is a big, roughly round, hollow ring; this skips
        # red name tags, pumpkins and other solid red things
        if bw < 25 * scale or bh < 15 * scale:  # far-away circles are small when zoomed out
            continue
        if not 0.4 < bw / bh < 3.0:
            continue
        if fill > 0.55:
            continue
        x, y = cents[i][0] + x0, cents[i][1] + y0
        found.append((x, y, stats[i, cv2.CC_STAT_AREA]))
    found.sort(key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
    return found


def setup_camera(game):
    game.drag_camera(CAMERA_DRAG)
    r = game.frame()
    game.scroll(r.shape[1] / 2, r.shape[0] / 2, -ZOOM_OUT_NOTCHES)  # wheel back = zoom out
    game.park_mouse()


# Measured on a test PC: from straight down, dragging up ~150px gives the usual
# view from behind the character (300+ swings up to the sky)
NORMAL_TILT_UP = 150
NORMAL_ZOOM_NOTCHES = 12  # from fully zoomed in, out to a normal third-person distance


def reset_camera(game):
    """Undo setup_camera before teleporting back, so the fishing spot's prompt is
    in view. Order matters (this is the order that was tested): straight down,
    zoom all the way in, zoom out to normal, then tilt back up."""
    game.drag_camera(CAMERA_DRAG)  # straight down first, so the tilt-up is exact
    r = game.frame()
    cx, cy = r.shape[1] / 2, r.shape[0] / 2
    game.scroll(cx, cy, ZOOM_OUT_NOTCHES)
    game.wait(0.3)
    game.scroll(cx, cy, -NORMAL_ZOOM_NOTCHES)
    game.drag_camera(-NORMAL_TILT_UP)
    game.park_mouse()


def chase_circles(game, still_on, log=print):
    """Walk into the nearest red circle, over and over, while still_on() is true."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    last_shot = 0
    shots = 0
    held = set()

    def hold(keys):
        for k in {"w", "a", "s", "d"} - keys:
            if k in held:
                game.key(k, False)
                held.discard(k)
        for k in keys - held:
            game.key(k, True)
            held.add(k)

    try:
        while still_on():
            img = game.frame()
            s = game.ui_scale(img)
            h, w = img.shape[:2]
            circles = find_red_circles(img, s)
            if time.time() - last_shot > 3 and shots < 60:
                cv2.imwrite(os.path.join(DEBUG_DIR, f"{time.strftime('%H-%M-%S')}.jpg"),
                            cv2.resize(img, None, fx=0.5, fy=0.5))
                last_shot, shots = time.time(), shots + 1
            if not circles:
                hold(set())
                game.wait(0.1)
                continue
            x, y, _ = circles[0]
            dx, dy = x - w / 2, y - h / 2
            near = CLOSE_ENOUGH * s
            keys = set()
            # Camera looks straight down, so screen up = forward (W)
            if dy < -near:
                keys.add("w")
            elif dy > near:
                keys.add("s")
            if dx < -near:
                keys.add("a")
            elif dx > near:
                keys.add("d")
            hold(keys)
            game.wait(0.05)
    finally:
        hold(set())
