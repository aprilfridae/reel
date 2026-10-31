"""Find the fishing UI in a frame of the Roblox window (BGR numpy image)."""
import os

import cv2
import numpy as np

from paths import RES

# Where the fishing panel lives, in UI pixels (at UI scale 1) measured from the
# bottom-center of the window. Roblox keeps the panel anchored there.
PANEL_HALF_WIDTH = 360
TRACK_HALF_WIDTH = 212  # the reel track, measured on a test screen (track edges ±214)
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


def detect(img, scale=1.0):
    """scale = Roblox UI scale (1.0 on the PCs seen so far; see Game.ui_scale).
    Returns dict with:
    busy  - True if the fishing panel (waiting or reeling) is on screen
    zone  - (left, right) x of the green reel zone, or None
    fish  - x of the fish, or None
    scale - the UI scale used
    All x values are in panel-region pixels.
    """
    h, w = img.shape[:2]
    y0 = max(0, int(h - PANEL_FROM_BOTTOM[0] * scale))
    y1 = max(0, int(h - PANEL_FROM_BOTTOM[1] * scale))
    x0 = max(0, int(w / 2 - PANEL_HALF_WIDTH * scale))
    x1 = int(w / 2 + PANEL_HALF_WIDTH * scale)
    raw = img[y0:y1, x0:x1]
    busy = _has_stop_button(raw, scale)
    reg = raw.astype(np.int16)
    b, g, r = reg[..., 0], reg[..., 1], reg[..., 2]

    out = {"busy": busy, "zone": None, "fish": None, "scale": scale}
    if not busy:
        return out  # the reel bar always comes with the red Stop button

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
    out["zone"] = (int(cols.min()), int(cols.max()))

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


