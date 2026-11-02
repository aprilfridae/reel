"""Knowing which event is on, from the game's memory.

Top-right banner (EventHUD > Pill, two labels), two forms:
  "☄ METEOR SHOWER" / "16:11 left • Meteor Packs dropping!"     (event running)
  "Next: ☄ Meteor Shower" / "starts in 39:37"                    (waiting for the next one)
Bottom-right auto-roll label (CardsUI > Root > AutoPill):
  "AUTO-ROLLING" / "+2740 packs  •  last: Rainbow Pack"           (the pack just rolled)

An event's pack is the one whose name is part of the event's name (Volcano Pack
during VOLCANO ERUPTION, Blood Moon Pack during BLOOD MOON, ...), so new events
work without changes as long as that holds.
"""
import re
import time

import mem_gui

# Pack names as they appear in text -> the bot's name for them
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


def _words(text):
    return " ".join(w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 1)


def _labels(root, depth=4):
    """The texts of the labels under root, in order (empty ones left out), or None if memory can't be read."""
    g = mem_gui.gui()
    if g is None or root is None:
        return None
    mb = g.mb
    out = []
    for d, o in mb._walk(root, depth=depth, max_nodes=80):
        if mb._class_name(o) in ("TextLabel", "TextButton"):
            t = (mb._content_text(o) or "").strip()
            if t:
                out.append(t)
    return out


def banner_text():
    """The event banner's two lines as one ("Next: ☄ Meteor Shower starts in 39:37"), "" if it isn't showing, None if
    memory can't be read."""
    g = mem_gui.gui()
    if g is None:
        return None
    sg = next((s for s in g.mb._children(g.mb.player_gui) if g.mb._name(s) == "EventHUD"), None)
    if sg is None or not g.screen_on("EventHUD"):
        return ""
    texts = _labels(sg)
    return " ".join(texts) if texts else ""


def roll_text():
    """The auto-roll label ("+2740 packs  •  last: Rainbow Pack"), None if it isn't showing."""
    g = mem_gui.gui()
    if g is None:
        return None
    mb = g.mb
    cards = next((s for s in mb._children(mb.player_gui) if mb._name(s) == "CardsUI"), None)
    root = cards and mb._find_child(cards, name="Root")
    pill = root and mb._find_child(root, name="AutoPill")
    if not pill or not g.is_shown(pill):
        return None
    return next((t for t in _labels(pill, 2) or [] if re.search(r"last\W", t, re.I)), None)


class EventWatcher:
    def __init__(self, game=None):
        self.game = game
        self.state = None  # "active", "next" or None (banner not read)
        self.name = ""  # event name, e.g. "VOLCANO ERUPTION" / "Blood Moon"
        self.seconds = None  # time left (active) or until start (next)
        self.read_at = 0.0
        self.last_pack = None  # pack named on the auto-roll label
        self._label_text = None
        self._deferred = set()
        self.raw = ""

    # ----- banner -----
    def update_banner(self, img=None, every=1.0):
        """Re-read the banner at most every `every` seconds. (img: unused, it's read from memory.)"""
        if time.time() - self.read_at < every:
            return
        self.read_at = time.time()
        text = banner_text()
        if text is None:
            return  # (memory can't be read right now: the last reading stands)
        self.raw = text
        if re.search(r"\bleft\b", text, re.I):
            self.state = "active"
            # The event name is the run of capital words right before the time
            before = re.split(r"\d", text, maxsplit=1)[0]
            caps = re.findall(r"\b[A-Z]{3,}(?:\s+[A-Z]{2,})*\b", before)
            self.name = caps[-1] if caps else _words(before)
            self.seconds = _time_to_seconds(text)
        elif re.search(r"starts\s+in", text, re.I):
            self.state = "next"
            name = re.split(r"starts\s+in", text, flags=re.I)[0]
            self.name = _words(re.split(r"\bNext\b", name, flags=re.I)[-1])  # (its icon, an emoji, left out)
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
    def update_label(self, img=None, defer=False):
        """Re-read the 'last: X Pack' label (memory: a few small reads, so it's read even during a reel).
        Returns the pack key if it just changed to a new value, else None. defer=True (during a reel): the change is
        kept for read_deferred() instead."""
        text = roll_text()
        if not text or text == self._label_text:
            return None
        self._label_text = text
        key = self._read_label(text)
        if defer:
            if key:
                self._deferred.add(key)
            return None
        return key

    on_label = None  # called with (pack key, whole label text) each time the label changes: the website's roll count

    def _read_label(self, text):
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
        """Pack keys the label changed to during a reel."""
        found, self._deferred = self._deferred, set()
        return found

    def describe(self):
        if self.state == "active":
            return f"{self.name} ({self.seconds // 60 if self.seconds else '?'} min left)"
        if self.state == "next":
            return f"next: {self.name} in {self.seconds}s"
        return f"unknown (banner read: {self.raw!r})"
