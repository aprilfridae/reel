"""Find the fishing UI in a frame of the Roblox window (BGR numpy image)."""
import os

import cv2
import numpy as np

from paths import RES

# Where the fishing panel lives, in UI pixels (at UI scale 1) measured from the
# bottom-center of the window. Roblox keeps the panel anchored there.
PANEL_HALF_WIDTH = 360
TRACK_HALF_WIDTH = 212  # the reel track, measured on Angie's screen (track edges ±214)
PANEL_X = None  # (kept for old analysis scripts)
PANEL_FROM_BOTTOM = (620, 160)

_STOP = cv2.imread(os.path.join(RES, "templates", "stop_button.png"), cv2.IMREAD_GRAYSCALE)
_stop_scaled = {}


def _has_stop_button(reg, scale):
    """The red Stop button is on both the 'waiting' and the 'reeling' panel."""
    key = round(scale, 2)
    if key not in _stop_scaled:
        _stop_scaled[key] = _STOP if key == 1 else cv2.resize(
            _STOP, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    t = _stop_scaled[key]
    if reg.shape[0] < t.shape[0] or reg.shape[1] < t.shape[1]:
        return False
    gray = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    return cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))[1] > 0.8


TRACK_ROWS = (332, 282)  # the track's top and bottom edge, in UI pixels above the window's bottom
BUTTON_ROWS = (258, 205)  # the big blue "HOLD E TO REEL" button's rows, the same way


def _has_reel_button(img, scale):
    """Is the big blue HOLD E TO REEL button showing? It's only there while reeling, so it
    tells a real reel bar from the "Waiting for a bite" / "It got away" panels."""
    h, w = img.shape[:2]
    y0, y1 = int(h - BUTTON_ROWS[0] * scale), int(h - BUTTON_ROWS[1] * scale)
    x0, x1 = int(w / 2 - 200 * scale), int(w / 2 + 200 * scale)
    reg = img[max(0, y0):y1, max(0, x0):x1]
    if reg.size == 0:
        return False
    hsv = cv2.cvtColor(reg, cv2.COLOR_BGR2HSV)
    blue = (hsv[..., 0] >= 95) & (hsv[..., 0] <= 115) & (hsv[..., 1] > 110) & (hsv[..., 2] > 170)
    return float(blue.mean()) > 0.3


REEL_ROWS = (400, 190)  # the part of the panel a reel needs (Stop button, track, blue button), from the bottom


def detect(img, scale=1.0, rows=PANEL_FROM_BOTTOM):
    """scale = Roblox UI scale (1.0 on the PCs seen so far; see Game.ui_scale).
    Returns dict with:
    busy  - True if the fishing panel (waiting or reeling) is on screen
    zone  - (left, right) x of the green reel zone, or None
    fish  - x of the fish, or None
    scale - the UI scale used
    All x values are in panel-region pixels.
    """
    h, w = img.shape[:2]
    y0 = max(0, int(h - rows[0] * scale))
    y1 = max(0, int(h - rows[1] * scale))
    x0 = max(0, int(w / 2 - PANEL_HALF_WIDTH * scale))
    x1 = int(w / 2 + PANEL_HALF_WIDTH * scale)
    raw = img[y0:y1, x0:x1]
    busy = _has_stop_button(raw, scale)
    out = {"busy": busy, "zone": None, "fish": None, "scale": scale}
    if not busy:
        return out  # the reel bar always comes with the red Stop button
    if not _has_reel_button(img, scale):
        return out  # "Waiting for a bite" / "It got away": the Stop button but no reel bar
    # Only the track's own rows are looked at, not the whole panel region: in events like
    # Acid Rain the world is full of bright green streaks that look just like the zone.
    t0 = max(0, int(h - TRACK_ROWS[0] * scale) - y0)
    t1 = max(t0 + 1, int(h - TRACK_ROWS[1] * scale) - y0)
    reg = raw[t0:t1].astype(np.int16)
    b, g, r = reg[..., 0], reg[..., 1], reg[..., 2]

    green = (g > r + 40) & (g > b + 30) & (g > 110)
    row_hits = green.sum(1)
    rows = np.where(row_hits > 25 * scale)[0]
    if len(rows) < 8 * scale:
        return out
    # Split into runs of touching rows. The progress bar under the track turns green
    # near the end of a catch, so take the tallest run: the zone (~30px) is taller than
    # the progress bar (~10px), and a player's green nametag is taller than 45px.
    runs = np.split(rows, np.where(np.diff(rows) > 2)[0] + 1)
    run = max(runs, key=len)
    height = run[-1] - run[0] + 1
    if height < 15 * scale or height > 45 * scale:
        return out
    band = slice(run[0], run[-1] + 1)
    bb, gb, rb = b[band], g[band], r[band]
    hi = np.maximum(np.maximum(bb, gb), rb)
    lo = np.minimum(np.minimum(bb, gb), rb)

    # Only look inside the track itself (the dark bar). Whatever is behind the panel
    # in the game world, e.g. the dock's glowing cyan bucket with the default camera,
    # must never count as the zone or the fish.
    # The track is centered in the panel, TRACK_HALF_WIDTH either side (UI pixels)
    mid = w / 2 - x0
    left = max(0, int(mid - TRACK_HALF_WIDTH * scale))
    right = min(hi.shape[1], int(mid + TRACK_HALF_WIDTH * scale))
    inside = np.zeros(hi.shape[1], bool)
    inside[left:right] = True

    cols = np.where((green[band].sum(0) > 0.3 * height) & inside)[0]
    if len(cols) < 20 * scale:
        return out
    # The zone is one wide block (the fish icon can split it in two, so pieces within a
    # fish's width of each other are one block); thin green streaks elsewhere in the
    # track aren't part of it: take the widest block
    groups = np.split(cols, np.where(np.diff(cols) > 50 * scale)[0] + 1)
    block = max(groups, key=lambda grp: int(grp.max() - grp.min()))
    if block.max() - block.min() < 20 * scale:
        return out
    out["zone"] = (int(block.min()), int(block.max()))

    # The fish is whatever bright, non-green, non-white thing sits in the track.
    # Not keyed to blue, since rarer fish may use other colors.
    fish = (hi > 140) & (hi - lo > 70) & ~green[band] & inside[None, :]
    edge = max(1, int(4 * scale))  # ignore the track's rounded ends
    fish[:, :left + edge] = False
    fish[:, max(0, right - edge):] = False
    fcols = np.where(fish.sum(0) > 2)[0]
    if len(fcols) > 3 * scale:
        out["fish"] = float(np.median(fcols))
    return out


