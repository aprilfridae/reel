"""Knowing which event is on, by reading the game's text with OCR.

Top-right banner, two forms:
  "VOLCANO ERUPTION 16:11 left • Volcano Packs dropping!"    (event running)
  "Next: Blood Moon starts in 39:37"                         (waiting for the next one)
Bottom-right auto-roll label:
  "AUTO-ROLLING +2740 packs • last: Rainbow Pack"            (the pack just rolled)

An event's pack is the one whose name is part of the event's name (Volcano Pack
during VOLCANO ERUPTION, Blood Moon Pack during BLOOD MOON, ...), so new events
work without changes as long as that holds.
"""
import re
import time

from ocr import read_text

# Pack names as they appear in text -> the bot's name for them (templates/pack_<name>.png)
EVENT_PACK_NAMES = {
    "blood moon": "blood_moon",
    "eclipse": "eclipse",
    "volcano": "volcano",
    "acid": "acid",
    "tsunami": "tsunami",
    "storm": "storm",
    "meteor": "meteor",
    "flood": "tsunami",  # "The Flood" drops Tsunami packs
    "lightning": "storm",
}
FILLER_WORDS = {"the", "a", "an", "of", "free", "skip", "next"}


def pack_key(name):
    """'Blood Moon' -> 'blood_moon', for any pack name."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _time_to_seconds(text):
    m = re.search(r"(\d+):(\d{2})(?::(\d{2}))?", text)
    if not m:
        return None
    parts = [int(p) for p in m.groups() if p is not None]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


def event_pack(event_name):
    """The pack that drops during this event, or None if it can't be told."""
    low = event_name.lower()
    for text, key in EVENT_PACK_NAMES.items():
        if text in low:
            return key
    # Unknown event: guess from its first real word (e.g. "FROST WAVE" -> frost)
    words = [w for w in re.findall(r"[a-z]+", low) if w not in FILLER_WORDS]
    return words[0] if words else None


class EventWatcher:
    def __init__(self, game):
        self.game = game
        self.state = None  # "active", "next" or None (banner not read)
        self.name = ""  # event name, e.g. "VOLCANO ERUPTION" / "Blood Moon"
        self.seconds = None  # time left (active) or until start (next)
        self.read_at = 0.0
        self.last_pack = None  # pack named on the auto-roll label
        self._label_pixels = None
        self._deferred = []
        self.raw = ""

    # ----- banner -----
    def _banner_area(self, img):
        h, w = img.shape[:2]
        s = self.game.ui_scale(img)
        # Only the banner itself: wider would take in the "Skip FREE" button beside it
        return img[0:int(110 * s), max(0, w - int(470 * s)):w]

    def update_banner(self, img, every=1.0):
        """Re-read the banner at most every `every` seconds."""
        if time.time() - self.read_at < every:
            return
        self.read_at = time.time()
        text = read_text(self._banner_area(img))
        self.raw = text
        if re.search(r"\bleft\b", text, re.I):
            self.state = "active"
            # The event name is the run of capital words right before the time
            # (other buttons next to the banner, like "Skip FREE", come before it)
            before = re.split(r"\d", text, maxsplit=1)[0]
            caps = re.findall(r"\b[A-Z]{3,}(?:\s+[A-Z]{2,})*\b", before)
            self.name = caps[-1] if caps else before.strip(" •.-")
            self.seconds = _time_to_seconds(text)
        elif re.search(r"starts\s+in", text, re.I):
            self.state = "next"
            name = re.split(r"starts\s+in", text, flags=re.I)[0]
            name = re.split(r"\bNext\b", name, flags=re.I)[-1]
            # Drop the event's icon, which OCR reads as a stray letter or symbol
            self.name = " ".join(w for w in re.findall(r"[A-Za-z]+", name) if len(w) > 1)
            self.seconds = _time_to_seconds(text.split("starts")[-1])
        else:
            self.state = None

    @property
    def active(self):
        return self.state == "active"

    @property
    def pack(self):
        """The current event's pack (only while an event is running)."""
        return event_pack(self.name) if self.active else None

    # ----- auto-roll label -----
    def update_label(self, img, defer=False):
        """Re-read the 'last: X Pack' label, but only when its pixels changed.
        Returns the pack key if it just changed to a new value, else None.
        defer=True (during a reel): don't spend time on OCR now, just keep a copy of
        the changed label; read_deferred() reads them afterwards."""
        h, w = img.shape[:2]
        s = self.game.ui_scale(img)
        area = img[h - int(70 * s):h, w - int(340 * s):w]
        small = area[::4, ::4]
        if self._label_pixels is not None and small.shape == self._label_pixels.shape \
                and abs(small.astype(int) - self._label_pixels).mean() < 2:
            return None
        self._label_pixels = small.astype(int)
        if defer:
            self._deferred.append(area.copy())
            return None
        return self._read_label(area)

    on_label = None  # called with (pack key, whole label text) each time the label is read: the website's roll count

    def _read_label(self, area):
        text = read_text(area)
        m = re.search(r"last\W+(.+?)\s+Pack", text, re.I)
        if not m:
            return None
        key = pack_key(m.group(1))
        if self.on_label:
            try:
                self.on_label(key, text)
            except Exception:
                pass
        changed = key != self.last_pack
        self.last_pack = key
        return key if changed else None

    def read_deferred(self):
        """Pack keys from labels saved during a reel."""
        found = {self._read_label(a) for a in self._deferred}
        self._deferred = []
        return found - {None}

    def describe(self):
        if self.state == "active":
            return f"{self.name} ({self.seconds // 60 if self.seconds else '?'} min left)"
        if self.state == "next":
            return f"next: {self.name} in {self.seconds}s"
        return f"unknown (banner read: {self.raw!r})"
