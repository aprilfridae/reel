"""Memory-reading backend for the Underground Artist RNG bot.

Wraps game_reader.py to replace every CV/OCR dependency with direct
Roblox memory reads. Everything here is read-only (PROCESS_VM_READ) —
no injection, no writes, no hooks.

Provides the same interfaces the old CV modules exposed, so the rest of
the bot (fisher, market scan, packs, events...) can swap in with
minimal changes.

Usage:
    from memory_backend import MemoryBackend
    mb = MemoryBackend()
    mb.start()                       # attach + locate game tree (cached)
    bal = mb.get_balance()           # "3.9T"
    state = mb.fish_state()          # "waiting" | "biting" | "caught" | None
    btn = mb.find_button("OPEN")     # button instance for clicking
    x, y = mb.button_pos(btn)        # screen coords
    txt = mb.read_text(btn)          # button's visible text
    mb.close()
"""
import json
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader import Reader

# What the scan anchors on: the Players service's own name (always there), then a few usernames in case
_ANCHORS = [b"Players", b"knotschaser", b"ivrilt", b"ka_bel", b"jelllllycat", b"PrepyDZN"]
_SCAN_CHUNK = 4 * 1024 * 1024
_MAX_STRUCTS = 20000  # anchor strings followed up (a common name like "Players" occurs many times)

_TEXT_CLASSES = ("TextLabel", "TextButton", "TextBox")
# where each keeps its displayed text (see _content_text); a TextBox's is what's typed in it
_SHOWN_TEXT = {"TextLabel": 0xE08, "TextButton": 0xE20, "TextBox": 0xE00}

_shared = None
_shared_lock = threading.Lock()


def get_backend():
    """The one started MemoryBackend the whole program shares (the bot, the fisher and the website poller):
    finding the game in memory is the slow part, so it's done once."""
    global _shared
    with _shared_lock:
        if _shared is None:
            mb = MemoryBackend()
            mb.start()
            _shared = mb
        return _shared


class MemoryBackend:
    """High-level game-state reader built on Reader (external, read-only)."""

    def __init__(self, cache_path="gamereader_cache.json"):
        self.r = Reader()
        self.data_model = None
        self.players = None
        self.local_player = None
        self.player_gui = None
        self._abs_pos_off = None
        self._started = False
        self.cache_path = cache_path
        self._cls_cache = {}  # instance address -> (class name, when read)

    # ---- lifecycle -------------------------------------------------------
    def start(self):
        """Attach to Roblox, locate DataModel + Players + local PlayerGui.
        Results are cached to disk so subsequent starts take ~0.1s."""
        if self._started:
            return

        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r") as f:
                    cache = json.load(f)
                dm = cache.get("data_model")
                players = cache.get("players")
                lp = cache.get("local_player")
                pg = cache.get("player_gui")
                if all(self._valid(v) for v in (dm, players, lp, pg)):
                    if (self._class_name(dm) == "DataModel"
                            and self._class_name(players) == "Players"
                            and self._class_name(lp) == "Player"
                            and self._class_name(pg) == "PlayerGui"
                            and self._has_screen(pg, "CardsUI")):
                        self.data_model, self.players = dm, players
                        self.local_player, self.player_gui = lp, pg
                        print(f"[+] cache hit: DataModel 0x{dm:x}  Players 0x{players:x}")
                        print(f"[+] local player: {self._name(lp)!r}")
                        self._abs_pos_off = self._resolve_abs_pos(pg)
                        print(f"[+] AbsolutePosition offset: 0x{self._abs_pos_off:x}")
                        self._started = True
                        return
            except Exception:
                pass

        self._full_scan()

    def _chunks(self, regions):
        """(address, bytes) of every readable part of Roblox's memory, a few MB at a time (nothing is kept)."""
        for base, size in regions:
            off = 0
            while off < size:
                n = min(_SCAN_CHUNK, size - off)
                d = self.r.read(base + off, n)
                if d:
                    yield base + off, d
                off += n

    def _full_scan(self):
        """Find the DataModel from scratch. A Roblox name is a std::string (text inline when it's 15 characters
        or less, its length at +0x10) that an Instance points to from +0x68. So: 1) find the strings holding an
        anchor name, 2) one pass looking for any 8 bytes equal to one of those string addresses (numpy, a chunk
        at a time), 3) for each, check the Instance around it: Players under DataModel. Memory stays at a few MB
        (the old way kept a dict of every pointer in the game: gigabytes, and minutes)."""
        regions = list(self._regions())
        structs = {}
        for addr, d in self._chunks(regions):
            for needle in _ANCHORS:
                i = d.find(needle)
                while i != -1 and len(structs) < _MAX_STRUCTS:
                    if len(d) >= i + 0x14 and int.from_bytes(d[i + 0x10:i + 0x14], "little") == len(needle):
                        structs[addr + i] = needle
                    i = d.find(needle, i + 1)
        if not structs:
            raise RuntimeError("could not locate DataModel — is the game loaded?")
        wanted = np.array(sorted(structs), dtype=np.uint64)
        found = []  # Roblox keeps more than one DataModel (the place, and a shell). The shell's
        # PlayerGui is empty, so the first one found is often the wrong one: the walk then can't see Teleports.
        for addr, d in self._chunks(regions):
            pad = (8 - addr % 8) % 8
            usable = (len(d) - pad) // 8 * 8
            if usable <= 0:
                continue
            words = np.frombuffer(d, dtype="<u8", count=usable // 8, offset=pad)
            for k in np.nonzero(np.isin(words, wanted))[0]:
                inst = addr + pad + int(k) * 8 - 0x68  # the Instance whose Name this is
                if not self._valid(self.r.u64(inst + 0x18)):
                    continue
                if structs[int(words[k])] == b"Players":
                    cand, par = inst, self._parent(inst)  # the Players service itself
                else:
                    cand, par = self._parent(inst), None  # a Player: its parent should be Players
                    par = cand and self._parent(cand)
                if cand and par and self._class_name(cand) == "Players" and self._class_name(par) == "DataModel":
                    if any(par == d0 for d0, _ in found):
                        continue
                    found.append((par, cand))
                    print(f"[+] Players 0x{cand:x} -> DataModel 0x{par:x}", flush=True)
                    lp, pg = self._local_player_gui(cand)
                    if lp and self._has_screen(pg, "CardsUI"):
                        found = [(par, cand)]  # this is the place you're standing in; the others are empty shells
                        break
            else:
                continue
            break

        if not found:
            raise RuntimeError("could not locate DataModel — is the game loaded?")

        bound = []
        for dm, players in found:
            lp, pg = self._local_player_gui(players)
            if lp:
                bound.append((dm, players, lp, pg))
        if not bound:
            raise RuntimeError("local player not found")
        # the place you're standing in is the DataModel whose menus (CardsUI) are actually showing
        dm, players, lp, pg = next((b for b in bound if self._has_screen(b[3], "CardsUI")), bound[0])

        self.data_model, self.players = dm, players
        self.local_player, self.player_gui = lp, pg
        print(f"[+] DataModel 0x{dm:x}  Players 0x{players:x}")
        print(f"[+] local player: {self._name(lp)!r}")
        self._abs_pos_off = self._resolve_abs_pos(pg)
        print(f"[+] AbsolutePosition offset: 0x{self._abs_pos_off:x}")
        self._started = True

        if self._has_screen(pg, "CardsUI"):
            try:
                with open(self.cache_path, "w") as f:
                    json.dump({"data_model": dm, "players": players,
                               "local_player": lp, "player_gui": pg}, f)
            except Exception:
                pass

    def close(self):
        self.r.close()

    def _local_player_gui(self, players):
        """(player, PlayerGui) for the first player that has one, or (None, None)."""
        for p in self._children(players):
            if self._class_name(p) == "Player":
                pg = self._find_child(p, cls="PlayerGui")
                if pg:
                    return p, pg
        return None, None

    def _has_screen(self, gui, name):
        """True when this PlayerGui is showing a ScreenGui of this name (CardsUI is the game's own menus)."""
        return any(self._name(c) == name and self._class_name(c) == "ScreenGui" for c in self._children(gui))

    def alive(self):
        """Is the game we found still there (the same Roblox, the same DataModel, the menus still on it)?
        A reconnect builds a new one. An empty shell DataModel also fails this, so the next read finds the real one."""
        try:
            return (self.r.pid == Reader._find_pid("RobloxPlayerBeta.exe")
                    and self._class_name(self.player_gui) == "PlayerGui"
                    and self._parent(self._parent(self.player_gui)) == self.players
                    and self._has_screen(self.player_gui, "CardsUI"))
        except Exception:
            return False

    def reattach(self, tries=20, wait=10, force=False):
        """Find the game again, in place (everyone shares this object): after Roblox was restarted or reconnected
        (force: a reconnect's new DataModel, while the old one's memory can still read as valid for a while).
        True once found."""
        for k in range(tries):
            try:
                if self.alive() and not (force and k == 0):
                    return True
                if force and k == 0 and os.path.exists(self.cache_path):
                    os.remove(self.cache_path)  # (it holds the old addresses)
                if self.r.pid != Reader._find_pid("RobloxPlayerBeta.exe"):
                    try:
                        self.r.close()
                    except Exception:
                        pass
                    self.r = Reader()
                self._started = False
                self._cls_cache = {}
                self.generation = getattr(self, "generation", 0) + 1
                self.start()
                return True
            except Exception as e:
                print(f"[mem] game not found yet ({type(e).__name__}: {e})")
                if k < tries - 1:
                    time.sleep(wait)
        return False

    # ---- low level -------------------------------------------------------
    def _valid(self, v):
        return v and 0x10000 < v < 0x7FFFFFFFFFFF

    def _regions(self):
        import ctypes
        import ctypes.wintypes as wt
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        MEM_COMMIT = 0x1000
        READABLE = {0x02, 0x04, 0x20, 0x40}
        addr = 0

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                        ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                        ("Protect", wt.DWORD), ("Type", wt.DWORD)]

        mbi = MBI()
        out = []
        while addr < 0x7FFFFFFFFFFF:
            if not k32.VirtualQueryEx(self.r.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE and mbi.RegionSize:
                out.append((mbi.BaseAddress, mbi.RegionSize))
            addr = (mbi.BaseAddress or 0) + mbi.RegionSize
        return out

    def _class_name(self, inst):
        # An object's class never changes while it exists: remembered for a minute (an address can be reused by a
        # new object after the game rebuilds a menu, hence not for longer). Several reads saved per lookup.
        hit = self._cls_cache.get(inst)
        now = time.time()
        if hit and now - hit[1] < 60:
            return hit[0]
        cls = self._class_name_read(inst)
        if len(self._cls_cache) > 200000:
            self._cls_cache.clear()
        self._cls_cache[inst] = (cls, now)
        return cls

    def _class_name_read(self, inst):
        try:
            cd = self.r.u64(inst + 0x18)
            if not self._valid(cd):
                return None
            p = self.r.u64(cd + 0x8)
            if not self._valid(p):
                return None
            fl = self.r.u64(p + 0x18)
            if fl == 0x1F:
                p = self.r.u64(p)
                if not self._valid(p):
                    return None
            return self.r.read_str(p)
        except Exception:
            return None

    def _name(self, inst):
        if not inst:
            return None
        p = self.r.u64(inst + 0x68)
        return self.r.read_str(p) if p else None

    def _parent(self, inst):
        p = self.r.u64(inst + 0x60)
        return p if self._valid(p) else None

    def _children(self, inst):
        vs = self.r.u64(inst + 0x70) if inst else None
        if not self._valid(vs):
            return []
        begin = self.r.u64(vs)
        end = self.r.u64(vs + 8)
        if not self._valid(begin) or not end or end < begin or (end - begin) > 0x200000:
            return []
        out = []
        cur = begin
        while cur < end and len(out) < 10000:
            p = self.r.u64(cur)
            if p:
                out.append(p)
            cur += 0x10
        return out

    def _find_child(self, inst, name=None, cls=None):
        for c in self._children(inst):
            if name is not None and self._name(c) != name:
                continue
            if cls is not None and self._class_name(c) != cls:
                continue
            return c
        return None

    def _walk(self, inst, depth=20, max_nodes=30000):
        count = 0
        stack = [(0, inst)]
        while stack and count < max_nodes:
            d, i = stack.pop()
            yield d, i
            count += 1
            if d < depth:
                for c in reversed(self._children(i)):
                    stack.append((d + 1, c))

    def _content_text(self, inst):
        ptr = self.r.u64(inst + 0xC60)
        t = self.r.read_str(ptr) if self._valid(ptr) else None
        if t is None:
            # some labels (a countdown the game rewrites every second, Roblox's own chat, the market's rarity buttons)
            # leave that one empty: their displayed text (rich-text tags stripped) is also kept in the object itself
            off = _SHOWN_TEXT.get(self._class_name(inst))
            t = self.r.read_str(inst + off) if off else None
        return t

    def _resolve_abs_pos(self, test_inst):
        for off in (0xFC, 0x110, 0xE4):
            x = self.r.f32(test_inst + off)
            y = self.r.f32(test_inst + off + 4)
            if x is not None and y is not None and 0 <= x <= 3840 and 0 <= y <= 2160:
                return off
        return 0xFC

    # ---- public API ------------------------------------------------------
    def get_balance(self):
        """Coin balance read from the 💰 label, e.g. '3.9T'."""
        import re
        money_re = re.compile(r"^[\d.,]+[KMBT]?$")
        for d, i in self._walk(self.player_gui, depth=12):
            cls = self._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = self._content_text(i)
                if txt and money_re.match(txt.strip()):
                    node = i
                    for _ in range(8):
                        par = self._parent(node)
                        if not par:
                            break
                        for sib in self._children(par):
                            if sib != i:
                                st = self._content_text(sib)
                                if st and st.strip() == "💰":
                                    return txt.strip()
                        node = par
        # fallback: any money-pattern label near top of tree
        for d, i in self._walk(self.player_gui, depth=8):
            cls = self._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = self._content_text(i)
                if txt and money_re.match(txt.strip()):
                    return txt.strip()
        return None

    def fish_state(self):
        """'waiting' | 'biting' | 'caught' | None from FishingUI text."""
        fg = self._find_screen_gui("FishingUI")
        if not fg:
            return None
        for d, i in self._walk(fg, depth=10):
            txt = self._content_text(i)
            if not txt:
                continue
            tl = txt.lower()
            if "bite" in tl and "reel" in tl:
                return "biting"
            if "caught" in tl:
                return "caught"
            if "waiting" in tl:
                return "waiting"
        return None

    def _find_screen_gui(self, name):
        for c in self._children(self.player_gui):
            if self._name(c) == name and self._class_name(c) == "ScreenGui":
                return c
        return None

    def find_button(self, text_contains, under=None):
        """Find a TextButton whose visible text contains text_contains."""
        root = under or self.player_gui
        for d, i in self._walk(root):
            if self._class_name(i) == "TextButton":
                txt = self._content_text(i) or ""
                if text_contains.lower() in txt.lower():
                    return i
        return None

    def find_label(self, text_contains, under=None):
        """Find a TextLabel whose visible text contains text_contains."""
        root = under or self.player_gui
        for d, i in self._walk(root):
            if self._class_name(i) == "TextLabel":
                txt = self._content_text(i) or ""
                if text_contains.lower() in txt.lower():
                    return i
        return None

    def button_pos(self, inst):
        """Screen coords (x, y) of a GUI element's AbsolutePosition."""
        off = self._abs_pos_off
        x = self.r.f32(inst + off)
        y = self.r.f32(inst + off + 4)
        if x is None or y is None:
            return None
        return (x, y)

    def read_text(self, inst):
        """Visible text of a TextLabel/TextButton/TextBox."""
        return self._content_text(inst) or ""

    def screen_gui(self, name):
        """Find a ScreenGui child of PlayerGui by name."""
        return self._find_screen_gui(name)

    def find_text_in(self, text_contains, screen_gui_name):
        """Find a TextLabel/TextButton under a named ScreenGui whose text matches."""
        sg = self._find_screen_gui(screen_gui_name)
        if not sg:
            return None
        for d, i in self._walk(sg, depth=14):
            cls = self._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = self._content_text(i) or ""
                if text_contains.lower() in txt.lower():
                    return i
        return None


# quick self-test
if __name__ == "__main__":
    mb = MemoryBackend()
    mb.start()
    print("balance:", mb.get_balance())
    print("fish:", mb.fish_state())
    btn = mb.find_button("OPEN")
    if btn:
        print("OPEN button:", mb.button_pos(btn))
    mb.close()
