"""Finding the game's buttons in memory, by what they say or are called, instead of by their picture or a fixed spot on
the screen: a button that moves or gets restyled in a game update is still found.

Every GUI object in memory has its on-screen centre at +0xDC (floats, screen pixels; the same pixels the mouse uses,
checked against the screen for the HUD buttons and the reel) and its Visible flag at +0x575 (1 = showing; checked
against the fishing panel: 98.5% agreement, the rest are frames taken mid-change). A ScreenGui's Enabled flag is at
+0x48c (checked against the Card Market opening and closing: 99.3%). An object is on screen only when its ScreenGui is
enabled, it and all its parents are visible, and it isn't scrolled out of a list it's in.

A match by text is clicked at the text's own centre: a button frame's reported position can lag behind (seen on the
Packs menu's OPEN buttons), while the text inside it is where it's drawn.

locate() returns (x, y, 1.0) like Game.find(), or None, so a call site keeps its screen way as the backup:
    hit = locate(text="Packs", screen="CardsUI") or game.find("packs_button", img)
"""
import re
import struct
import time

VISIBLE = 0x575
ENABLED = 0x48c  # (ScreenGui)
GEOM = 0xDC  # centre x, y; size w, h at +0x20 from here
TEXT_CLASSES = ("TextLabel", "TextButton", "TextBox")
CLICKABLE = ("TextButton", "ImageButton")
CACHE_FOR = 30.0  # seconds a found object's address is reused (the game rebuilds some menus: then it's looked up again)

_gui = {"obj": None, "tried": 0.0}
stats = {"memory": 0, "screen": 0, "missing": 0}  # how the bot's buttons were found (shown in the log now and then)


def either(mem_hit, screen_find):
    """The memory hit if there is one, else what the screen finds (screen_find() is only run when needed),
    counted in `stats`."""
    if mem_hit:
        stats["memory"] += 1
        return mem_hit
    hit = screen_find()
    stats["screen" if hit else "missing"] += 1
    return hit


def gui():
    """The shared MemGui, or None when memory can't be read (the callers then use the screen)."""
    if _gui["obj"] is None and time.time() - _gui["tried"] > 60:
        _gui["tried"] = time.time()
        try:
            from memory_backend import get_backend
            _gui["obj"] = MemGui(get_backend())
        except Exception:
            _gui["obj"] = None
    return _gui["obj"]


def locate(text=None, screen=None, name=None, cls=None, within=None, exact=True, contains=False):
    """Where to click a showing button / label (see MemGui.find), or None (memory unavailable or not found)."""
    g = gui()
    if g is None:
        return None
    try:
        hit = g.find(text=text, screen=screen, name=name, cls=cls, within=within, exact=exact, contains=contains)
    except Exception:
        return None
    return (hit[0], hit[1], 1.0) if hit else None


def read(text=None, screen=None, name=None, cls=None, exact=False, contains=False):
    """(its text, x, y) for a showing object found like locate(), e.g. read("Sort:", "MarketUI") -> the sort label's
    whole text. None if memory can't tell."""
    g = gui()
    if g is None:
        return None
    try:
        hit = g.find(text=text, screen=screen, name=name, cls=cls, exact=exact, contains=contains, want_obj=True)
    except Exception:
        return None
    return (g.mb._content_text(hit[2]) or "", hit[0], hit[1]) if hit else None


def showing(screen, name=None, text=None, within=None):
    """Is something of this ScreenGui showing (an object named `name` and / or saying `text`; with neither, the
    ScreenGui itself)? None if memory can't tell (so the caller looks at the screen)."""
    g = gui()
    if g is None:
        return None
    try:
        if name is None and text is None:
            return g.screen_on(screen)
        return g.find(text=text, screen=screen, name=name, within=within) is not None
    except Exception:
        return None


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class MemGui:
    def __init__(self, mb):
        self.mb = mb
        self._memo = {}  # query -> (address, when)

    def screen_on(self, screen):
        sg = next((s for s in self.mb._children(self.mb.player_gui) if self.mb._name(s) == screen), None)
        b = self.mb.r.read(sg + ENABLED, 1) if sg else None
        return bool(b and b[0] == 1)

    def is_shown(self, inst):
        """Its ScreenGui is enabled, it and every parent are visible, and its centre isn't scrolled out of view."""
        mb, node = self.mb, inst
        g = self.geom(inst)
        for _ in range(40):
            if node is None:
                return False
            cls = mb._class_name(node)
            if cls == "ScreenGui":
                b = mb.r.read(node + ENABLED, 1)
                return bool(b and b[0] == 1)
            if cls == "PlayerGui":
                return True
            b = mb.r.read(node + VISIBLE, 1)
            if not b or b[0] != 1:
                return False
            if cls == "ScrollingFrame" and node != inst and g:
                box = self.geom(node)  # the list's visible window: the object's centre must be inside it
                if box and not (abs(g[0] - box[0]) <= box[2] / 2 and abs(g[1] - box[1]) <= box[3] / 2):
                    return False
            node = mb._parent(node)
        return False

    def geom(self, inst):
        b = self.mb.r.read(inst + GEOM, 0x28)
        if not b or len(b) < 0x28:
            return None
        cx, cy = struct.unpack_from("<2f", b, 0)
        w, h = struct.unpack_from("<2f", b, 0x20)
        return cx, cy, w, h

    def _ok(self, inst):
        g = self.geom(inst)
        return g if g and g[2] > 1 and g[3] > 1 and 0 <= g[0] <= 8000 and 0 <= g[1] <= 5000 and self.is_shown(inst) else None

    def _inside(self, inst, within):
        node = self.mb._parent(inst)
        for _ in range(12):
            if node is None:
                return False
            if self.mb._name(node) == within:
                return True
            node = self.mb._parent(node)
        return False

    def find(self, text=None, screen=None, name=None, cls=None, within=None, exact=True, contains=False, want_obj=False):
        """The centre (x, y) of a showing object in PlayerGui (in the ScreenGui `screen`, if given) whose text is
        `text` (or starts with it when exact=False, or has it anywhere when contains=True: labels can start with an
        emoji) and/or whose name is `name`, of class `cls` if given, inside an object named `within` if given.
        None if there's none showing."""
        key = (text, screen, name, cls, within, exact, contains)
        memo = self._memo.get(key)
        if memo and time.time() - memo[1] < CACHE_FOR:
            g = self._ok(memo[0])
            if g and (text is None or self._text_ok(memo[0], _norm(text), exact, contains)):
                return (g[0], g[1], memo[0]) if want_obj else (g[0], g[1])
        mb, want = self.mb, _norm(text) if text is not None else None
        roots = [s for s in mb._children(mb.player_gui) if mb._class_name(s) == "ScreenGui"
                 and (screen is None or mb._name(s) == screen)]
        for root in roots:
            for d, inst in mb._walk(root, depth=16, max_nodes=6000):
                if name is not None and mb._name(inst) != name:
                    continue
                c = mb._class_name(inst)
                if cls is not None and c != cls:
                    continue
                if want is not None and (c not in TEXT_CLASSES or not self._text_ok(inst, want, exact, contains)):
                    continue
                if within is not None and not self._inside(inst, within):
                    continue
                g = self._ok(inst)
                if g:
                    self._memo[key] = (inst, time.time())
                    return (g[0], g[1], inst) if want_obj else (g[0], g[1])
        return None

    def _text_ok(self, inst, want, exact, contains):
        have = _norm(self.mb._content_text(inst))
        return want in have if contains else have == want if exact else have.startswith(want)
