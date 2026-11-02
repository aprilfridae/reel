# reader.py — external, read-only Roblox instance-tree reader (stdlib only).
# Anchors on a known username string in memory, walks Parent pointers up to the
# DataModel. Uses only stable Instance-structure offsets, so it survives weekly
# Roblox updates without static pointers. Never writes, never injects.
import ctypes
import ctypes.wintypes as wt
import struct

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH32CS_SNAPPROCESS = 0x2
TH32CS_SNAPMODULE = 0x8 | 0x10
PROCESS_VM_READ = 0x10
PROCESS_QUERY_INFORMATION = 0x400

OFF_CLASSDESC = 0x18
OFF_PARENT = 0x60
OFF_NAME = 0x68
OFF_CHILDREN = 0x70

# current-content text offsets (TextLabel/TextButton/TextBox ContentText)
TEXT_OFFSETS = {"TextLabel": 0xC60, "TextButton": 0xC60, "TextBox": 0xC60}

# usernames to anchor on (must be <=15 chars, and currently/ recently in server)
DEFAULT_NEEDLES = [b"knotschaser", b"ivrilt", b"ka_bel", b"jelllllycat", b"PrepyDZN"]


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


def _valid(v):
    return v and 0x10000 < v < 0x7FFFFFFFFFFF


class Reader:
    def __init__(self, pid=None, exe="RobloxPlayerBeta.exe"):
        if pid is None:
            pid = self._find_pid(exe)
        if not pid:
            raise OSError(f"{exe} is not running")
        self.pid = pid
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise OSError(f"OpenProcess failed: {ctypes.GetLastError()}")
        self.data_model = None
        self.players = None
        self.local_player = None

    # ---- low level -------------------------------------------------------
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
        """Roblox std::string: inline data if len<=15, else pointer at +0."""
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

    def _regions(self):
        MEM_COMMIT = 0x1000
        READABLE = {0x02, 0x04, 0x20, 0x40}
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        out = []
        while addr < 0x7FFFFFFFFFFF:
            if not k32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE and mbi.RegionSize:
                out.append((mbi.BaseAddress, mbi.RegionSize))
            addr = (mbi.BaseAddress or 0) + mbi.RegionSize
        return out

    # ---- instance tree ---------------------------------------------------
    def class_name(self, inst):
        try:
            cd = self.u64(inst + OFF_CLASSDESC)
            if not _valid(cd):
                return None
            p = self.u64(cd + 0x8)
            if not _valid(p):
                return None
            fl = self.u64(p + 0x18)
            if fl == 0x1F:
                p = self.u64(p)
                if not _valid(p):
                    return None
            return self.read_str(p)
        except Exception:
            return None

    def name(self, inst):
        if not inst:
            return None
        p = self.u64(inst + OFF_NAME)
        return self.read_str(p) if p else None

    def parent(self, inst):
        p = self.u64(inst + OFF_PARENT)
        return p if _valid(p) else None

    def children(self, inst):
        vs = self.u64(inst + OFF_CHILDREN) if inst else None
        if not _valid(vs):
            return []
        begin = self.u64(vs)
        end = self.u64(vs + 8)
        if not _valid(begin) or not end or end < begin or (end - begin) > 0x200000:
            return []
        out = []
        cur = begin
        while cur < end and len(out) < 10000:
            p = self.u64(cur)
            if p:
                out.append(p)
            cur += 0x10
        return out

    def find_child(self, inst, name=None, cls=None):
        for c in self.children(inst):
            if name is not None and self.name(c) != name:
                continue
            if cls is not None and self.class_name(c) != cls:
                continue
            return c
        return None

    def find_children(self, inst, name=None, cls=None):
        out = []
        for c in self.children(inst):
            if name is not None and self.name(c) != name:
                continue
            if cls is not None and self.class_name(c) != cls:
                continue
            out.append(c)
        return out

    def walk(self, inst, depth=3, max_nodes=2000):
        """Yield (depth, instance) in pre-order."""
        count = 0
        stack = [(0, inst)]
        while stack and count < max_nodes:
            d, i = stack.pop()
            yield d, i
            count += 1
            if d < depth:
                for c in reversed(self.children(i)):
                    stack.append((d + 1, c))

    def text(self, inst):
        """ContentText of a TextLabel/TextButton/TextBox (offset per class)."""
        cls = self.class_name(inst)
        off = TEXT_OFFSETS.get(cls)
        if not off:
            return None
        return self.read_str(self.u64(inst + off)) if _valid(self.u64(inst + off)) else None

    # ---- anchors ----------------------------------------------------------
    def _find_string_structs(self, needle):
        hits = []
        for base, size in self._regions():
            off = 0
            while off < size:
                n = min(4 * 1024 * 1024, size - off)
                d = self.read(base + off, n)
                if d:
                    i = d.find(needle)
                    while i != -1:
                        s = base + off + i
                        if self.u32(s + 0x10) == len(needle):
                            hits.append(s)
                        i = d.find(needle, i + 1)
                off += n
        return hits

    def _find_pointers_to(self, target):
        pat = struct.pack("<Q", target)
        hits = []
        for base, size in self._regions():
            off = 0
            while off < size:
                n = min(4 * 1024 * 1024, size - off)
                d = self.read(base + off, n)
                if d:
                    i = d.find(pat)
                    while i != -1:
                        a = base + off + i
                        if a % 8 == 0:
                            hits.append(a)
                        i = d.find(pat, i + 1)
                off += n
        return hits

    def find_tree(self, needles=DEFAULT_NEEDLES):
        """Locate DataModel + Players via a known username. Returns (data_model, players)."""
        for needle in needles:
            for s in self._find_string_structs(needle)[:20]:
                for ptr_addr in self._find_pointers_to(s)[:80]:
                    inst = ptr_addr - OFF_NAME
                    if inst < 0x10000 or not _valid(self.u64(inst + OFF_CLASSDESC)):
                        continue
                    par = self.parent(inst)
                    if not par or not _valid(self.u64(par + OFF_CLASSDESC)):
                        continue
                    if self.class_name(par) == "Players":
                        gp = self.parent(par)
                        if gp and self.class_name(gp) == "DataModel":
                            self.data_model, self.players = gp, par
                            return gp, par
        raise RuntimeError("could not locate the instance tree (server may be empty?)")

    def find_local_player(self):
        """The Player that has a PlayerGui child (only the local player does)."""
        if self.local_player:
            return self.local_player
        if not self.players:
            self.find_tree()
        for p in self.children(self.players):
            if self.class_name(p) == "Player":
                if self.find_child(p, cls="PlayerGui"):
                    self.local_player = p
                    return p
        return None

    def player_gui(self):
        lp = self.find_local_player()
        return self.find_child(lp, cls="PlayerGui") if lp else None

    def close(self):
        k32.CloseHandle(self.h)
