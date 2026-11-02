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
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader import Reader


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

    # ---- lifecycle -------------------------------------------------------
    def start(self):
        """Attach to Roblox, locate DataModel + Players + local PlayerGui.
        Results are cached to disk so subsequent starts take ~0.1s."""
        r = self.r
        import json

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
                            and self._class_name(pg) == "PlayerGui"):
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

    def _full_scan(self):
        r = self.r
        regions = list(self._regions())
        dm = players = None

        # ---- build pointer index (pointer value -> source addresses) ----
        ptr_index = {}
        CHUNK = 4 * 1024 * 1024
        for base, size in regions:
            off = 0
            while off < size:
                n = min(CHUNK, size - off)
                d = r.read(base + off, n)
                if d:
                    chunk_addr = base + off
                    start_i = (8 - (chunk_addr % 8)) % 8
                    for i in range(start_i, len(d) - 7, 8):
                        v = int.from_bytes(d[i:i + 8], "little")
                        if self._valid(v):
                            src = chunk_addr + i
                            if v not in ptr_index:
                                ptr_index[v] = []
                            ptr_index[v].append(src)
                off += n
        print(f"[+] indexed {len(ptr_index)} unique pointer values")

        # ---- find string structs matching any username needle ----
        needles = [b"knotschaser", b"ivrilt", b"ka_bel", b"jelllllycat", b"PrepyDZN"]
        string_structs = []
        for base, size in regions:
            off = 0
            while off < size:
                n = min(CHUNK, size - off)
                d = r.read(base + off, n)
                if d:
                    for needle in needles:
                        i = d.find(needle)
                        while i != -1:
                            s = base + off + i
                            if r.u32(s + 0x10) == len(needle):
                                string_structs.append(s)
                            i = d.find(needle, i + 1)
                off += n

        # ---- trace each string -> Player -> Players -> DataModel ----
        for s in string_structs[:30]:
            for src in ptr_index.get(s, []):
                inst = src - 0x68  # OFF_NAME
                if not self._valid(r.u64(inst + 0x18)):
                    continue
                par = self._parent(inst)
                if not par or not self._valid(r.u64(par + 0x18)):
                    continue
                if self._class_name(par) == "Players":
                    gp = self._parent(par)
                    if gp and self._class_name(gp) == "DataModel":
                        dm, players = gp, par
                        print(f"[+] Player 0x{inst:x} -> Players 0x{par:x} -> DataModel 0x{gp:x}")
                        break
            if dm:
                break

        if not dm:
            raise RuntimeError("could not locate DataModel — is the game loaded?")

        lp = pg = None
        for p in self._children(players):
            if self._class_name(p) == "Player":
                pg_candidate = self._find_child(p, cls="PlayerGui")
                if pg_candidate:
                    lp, pg = p, pg_candidate
                    break
        if not lp:
            raise RuntimeError("local player not found")

        self.data_model, self.players = dm, players
        self.local_player, self.player_gui = lp, pg
        print(f"[+] DataModel 0x{dm:x}  Players 0x{players:x}")
        print(f"[+] local player: {self._name(lp)!r}")
        self._abs_pos_off = self._resolve_abs_pos(pg)
        print(f"[+] AbsolutePosition offset: 0x{self._abs_pos_off:x}")
        self._started = True

        try:
            with open(self.cache_path, "w") as f:
                json.dump({"data_model": dm, "players": players,
                           "local_player": lp, "player_gui": pg}, f)
        except Exception:
            pass

    def close(self):
        self.r.close()

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
        return self.r.read_str(ptr) if self._valid(ptr) else None

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
