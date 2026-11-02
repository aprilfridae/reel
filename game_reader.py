# game_reader.py — external read-only Roblox game-state reader for the
# Underground Artist RNG bot. Replaces CV/OCR with direct memory reads.
#
# Reads: balance, pack counts, button positions, fishing state, rebirth info.
# All read-only via ReadProcessMemory — no injection, no writes.
#
# Usage:
#   gr = GameReader()
#   gr.start()                     # attach + find DataModel
#   bal = gr.get_balance()         # "3.8T"
#   btn = gr.find_button("OPEN")   # button instance for clicking
#   x, y = gr.button_pos(btn)      # screen coords
#   state = gr.get_fish_state()    # "waiting" | "biting" | "caught"
#   gr.close()
import ctypes
import ctypes.wintypes as wt
import struct
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH32CS_SNAPPROCESS = 0x2
PROCESS_VM_READ = 0x10
PROCESS_QUERY_INFORMATION = 0x400

OFF_CLASSDESC = 0x18
OFF_PARENT = 0x60
OFF_NAME = 0x68
OFF_CHILDREN = 0x70

CONTENT_TEXT_OFF = 0xC60     # verified on this Roblox build
ABS_POS_OFFSETS = [0xFC, 0x110, 0xE4]  # LayerCollector / GuiBase2d / ScreenGui

DEFAULT_NEEDLES = [b"knotschaser", b"ivrilt", b"ka_bel", b"jelllllycat", b"PrepyDZN"]


def _valid(v):
    return v and 0x10000 < v < 0x7FFFFFFFFFFF


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
               ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
               ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
               ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
               ("szExeFile", ctypes.c_char * 260)]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD)]


class Reader:
    """Low-level read-only memory reader for one Roblox process."""

    def __init__(self, exe="RobloxPlayerBeta.exe"):
        pid = self._find_pid(exe)
        if not pid:
            raise OSError(f"{exe} is not running")
        self.pid = pid
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise OSError(f"OpenProcess failed: {ctypes.GetLastError()}")

    @staticmethod
    def _find_pid(name):
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(pe)
        ok = k32.Process32First(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.decode(errors="replace").lower() == name.lower():
                pid = pe.th32ProcessID
                k32.CloseHandle(snap)
                return pid
            ok = k32.Process32Next(snap, ctypes.byref(pe))
        k32.CloseHandle(snap)
        return None

    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        return buf.raw[: got.value]

    def u32(self, addr):
        d = self.read(addr, 4)
        return struct.unpack("<I", d)[0] if d and len(d) == 4 else None

    def u64(self, addr):
        d = self.read(addr, 8)
        return struct.unpack("<Q", d)[0] if d and len(d) == 8 else None

    def f32(self, addr):
        d = self.read(addr, 4)
        return struct.unpack("<f", d)[0] if d and len(d) == 4 else None

    def read_str(self, addr):
        """Read a Roblox std::string whose pointer is at `addr`."""
        if not _valid(addr):
            return None
        n = self.u32(addr + 0x10)
        if n is None or not (0 < n <= 512):
            return None
        if n > 15:
            p = self.u64(addr)
            if not _valid(p):
                return None
            d = self.read(p, n)
        else:
            d = self.read(addr, n)
        if not d or len(d) != n:
            return None
        try:
            s = d.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return s if s.isprintable() else None

    def close(self):
        k32.CloseHandle(self.h)


class GameReader:
    """High-level game-state reader built on Reader."""

    def __init__(self):
        self.r = Reader()
        self.data_model = None
        self.players = None
        self.local_player = None
        self.player_gui = None
        self._abs_pos_off = None

    # ---- regions ----------------------------------------------------------
    def _regions(self):
        MEM_COMMIT = 0x1000
        READABLE = {0x02, 0x04, 0x20, 0x40}
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        out = []
        while addr < 0x7FFFFFFFFFFF:
            if not k32.VirtualQueryEx(self.r.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE and mbi.RegionSize:
                out.append((mbi.BaseAddress, mbi.RegionSize))
            addr = (mbi.BaseAddress or 0) + mbi.RegionSize
        return out

    # ---- instance tree ----------------------------------------------------
    def _class_name(self, inst):
        try:
            cd = self.r.u64(inst + OFF_CLASSDESC)
            if not _valid(cd):
                return None
            p = self.r.u64(cd + 0x8)
            if not _valid(p):
                return None
            fl = self.r.u64(p + 0x18)
            if fl == 0x1F:
                p = self.r.u64(p)
                if not _valid(p):
                    return None
            return self.r.read_str(p)
        except Exception:
            return None

    def _name(self, inst):
        if not inst:
            return None
        p = self.r.u64(inst + OFF_NAME)
        return self.r.read_str(p) if p else None

    def _parent(self, inst):
        p = self.r.u64(inst + OFF_PARENT)
        return p if _valid(p) else None

    def _children(self, inst):
        vs = self.r.u64(inst + OFF_CHILDREN) if inst else None
        if not _valid(vs):
            return []
        begin = self.r.u64(vs)
        end = self.r.u64(vs + 8)
        if not _valid(begin) or not end or end < begin or (end - begin) > 0x200000:
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
        ptr = self.r.u64(inst + CONTENT_TEXT_OFF)
        return self.r.read_str(ptr) if _valid(ptr) else None

    # ---- start: locate DataModel + Players via username anchor -------------
    def start(self, cache_path="gamereader_cache.json"):
        import os, json
        r = self.r
        regions = list(self._regions())

        # ---- try cache first ----
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    cache = json.load(f)
                dm = cache.get("data_model")
                players = cache.get("players")
                lp = cache.get("local_player")
                pg = cache.get("player_gui")
                if all(_valid(v) for v in (dm, players, lp, pg)):
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
                        return
            except Exception:
                pass

        # ---- full scan: build pointer index ----
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
                        v = struct.unpack_from("<Q", d, i)[0]
                        if _valid(v):
                            src = chunk_addr + i
                            if v not in ptr_index:
                                ptr_index[v] = []
                            ptr_index[v].append(src)
                off += n
        print(f"[+] indexed {len(ptr_index)} unique pointer values")

        # ---- find string structs matching any username needle ----
        needles = DEFAULT_NEEDLES
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
        dm = players = None
        for s in string_structs[:30]:
            for src in ptr_index.get(s, []):
                inst = src - OFF_NAME
                if not _valid(r.u64(inst + OFF_CLASSDESC)):
                    continue
                par = self._parent(inst)
                if not par or not _valid(r.u64(par + OFF_CLASSDESC)):
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

        # local player = the Player with a PlayerGui child
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

        # save cache
        try:
            with open(cache_path, "w") as f:
                json.dump({"data_model": dm, "players": players,
                           "local_player": lp, "player_gui": pg}, f)
        except Exception:
            pass

    def _resolve_abs_pos(self, test_inst):
        for off in ABS_POS_OFFSETS:
            x = self.r.f32(test_inst + off)
            y = self.r.f32(test_inst + off + 4)
            if x is not None and y is not None and 0 <= x <= 3840 and 0 <= y <= 2160:
                return off
        return ABS_POS_OFFSETS[0]

    # ---- public API -------------------------------------------------------
    def get_balance(self):
        """Read coin balance from the 💰 label area."""
        money_re = re.compile(r"^[\d.,]+[KMBT]?$")
        # first pass: look for money label with 💰 nearby (parent chain)
        for d, i in self._walk(self.player_gui, depth=12):
            cls = self._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = self._content_text(i)
                if txt and money_re.match(txt.strip()):
                    # check parent chain for 💰 within 8 levels
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
        # second pass: any money-pattern label near top of tree
        for d, i in self._walk(self.player_gui, depth=8):
            cls = self._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = self._content_text(i)
                if txt and money_re.match(txt.strip()):
                    return txt.strip()
        return None

    def get_fish_state(self):
        """Return 'waiting' | 'biting' | 'caught' | None from FishingUI."""
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
        root = under or self.player_gui
        for d, i in self._walk(root):
            if self._class_name(i) == "TextButton":
                txt = self._content_text(i) or ""
                if text_contains.lower() in txt.lower():
                    return i
        return None

    def find_label(self, text_contains, under=None):
        root = under or self.player_gui
        for d, i in self._walk(root):
            if self._class_name(i) == "TextLabel":
                txt = self._content_text(i) or ""
                if text_contains.lower() in txt.lower():
                    return i
        return None

    def button_pos(self, inst):
        off = self._abs_pos_off
        x = self.r.f32(inst + off)
        y = self.r.f32(inst + off + 4)
        if x is None or y is None:
            return None
        return (x, y)

    def close(self):
        self.r.close()
