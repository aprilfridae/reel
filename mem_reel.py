"""The reel minigame, read from Roblox's memory instead of the screen.

The fishing panel (PlayerGui.FishingUI) is laid out like this (found by recording it during reels):

    FishingUI / Frame / Frame          the panel: 56 px tall while "Waiting for a bite", 190 while reeling
                          Frame        the track (428 px wide, centred on the screen)
                            Frame      the green bar (its width depends on the fish)
                            TextLabel  the fish (the fish emoji, 40 px wide)

A GUI object keeps its on-screen geometry at +0xDC (centre x, y), +0xF4 (top-left x, y) and +0xFC (size w, h),
as floats in screen pixels. Reading the objects is a few small reads: far quicker than grabbing the screen and
finding the bar and the fish in the picture.

When is a reel on? The panel is 56 px tall while "Waiting for a bite" and 190 while reeling, but it stays 190
once it's gone after a reel (no show/hide flag was found in these objects). Recorded against the screen, it
always goes gone -> waiting -> reel -> gone. So a reel starts only after the waiting panel was seen, and lasts
while something in it changes: the bar, the fish, or the catch-progress fill (it grows while the fish is in the
bar and shrinks while it's out; the bar and the fish alone can both rest for a second mid-reel). Once all three
stand still, it's over.
"""
import struct
import time

PANEL_TALL = 150  # px: taller than this = the reel panel (190), not the waiting one (56)
TRACK_W = 428  # px: the track's width at UI scale 1
GEOM = 0xDC  # centre x, centre y, then (after 16 bytes) top-left x, y and size w, h
GEOM_LEN = 0x28
STILL_ENDS = 0.4  # seconds of neither the bar nor the fish moving = the reel is over


class MemReel:
    def __init__(self, mb):
        self.mb = mb
        self.panel = self.track = self.bar = self.fish = self.progress = None
        self.armed = False  # the waiting panel was seen: the next tall panel is a reel
        self.reeling = False
        self.last_key = None  # (bar x, fish x) last read, and when they last changed
        self.moved_at = 0.0

    def _find(self):
        """Locate the panel, track, bar and fish by their structure (not by order: the panel's siblings vary)."""
        mb = self.mb
        self.panel = self.track = self.bar = self.fish = self.progress = None
        fg = mb._find_screen_gui("FishingUI")
        if not fg:
            return False
        for top in mb._children(fg):
            for panel in mb._children(top):
                if mb._class_name(panel) != "Frame":
                    continue
                track = fill = None
                for f in mb._children(panel):
                    if mb._class_name(f) != "Frame":
                        continue
                    kids = mb._children(f)
                    frames = [k for k in kids if mb._class_name(k) == "Frame"]
                    labels = [k for k in kids if mb._class_name(k) == "TextLabel"]
                    if len(frames) == 1 and len(labels) == 1:  # the track: the bar and the fish
                        track, bar, fish = f, frames[0], labels[0]
                    elif len(frames) == 1 and not labels:  # the progress bar: its fill
                        fill = frames[0]
                if track:
                    self.panel, self.track, self.bar, self.fish, self.progress = panel, track, bar, fish, fill
                    return True
        return False

    def _geom(self, inst):
        b = self.mb.r.read(inst + GEOM, GEOM_LEN)
        if not b or len(b) < GEOM_LEN:
            return None
        cx, cy = struct.unpack_from("<2f", b, 0)
        x, y, w, h = struct.unpack_from("<4f", b, 0x18)
        return cx, cy, x, y, w, h

    def panel_shown(self):
        """Is the fishing panel up (waiting for a bite, or a reel)? Its Visible flag (see mem_gui)."""
        import mem_gui
        if self.panel is None and not self._find():
            return False
        g = mem_gui.gui()
        return bool(g and g.is_shown(self.panel))

    def scale(self):
        """How big the game draws its UI here: the track is 428 px wide at scale 1."""
        t = self._geom(self.track) if self.track else None
        return t[4] / TRACK_W if t and 50 < t[4] < 2000 else None

    def read(self):
        """None if no reel is on (or the panel can't be read), else {"zone": (left, right), "fish": x} in screen
        pixels: the green bar's edges and the fish's centre."""
        if self.panel is None and not self._find():
            return None
        p = self._geom(self.panel)
        if p is None or not (0 < p[5] < 2000):
            self.panel = None  # the game rebuilt its GUI: find it again next time
            return None
        if p[5] < PANEL_TALL:  # "Waiting for a bite": a reel can come next
            self.armed, self.reeling, self.last_key = True, False, None
            return None
        if not self.armed:  # tall, but gone since the last reel (or never seen waiting since the start)
            return None
        bar, fish = self._geom(self.bar), self._geom(self.fish)
        if bar is None or fish is None or not (20 < bar[4] < 400):
            return None
        now = time.time()
        fill = self._geom(self.progress) if self.progress else None
        key = (bar[0], fish[0], fill[4] if fill else None)
        if key != self.last_key:
            self.last_key, self.moved_at = key, now
        if now - self.moved_at > STILL_ENDS:
            if self.reeling:  # it was moving and stopped: that reel is over
                self.armed = self.reeling = False
            return None
        self.reeling = True
        return {"zone": (bar[2], bar[2] + bar[4]), "fish": fish[0]}
