"""Roblox window access: mouse/keyboard input, focus and the window itself. What the game shows is read from its
memory (memory_backend.py / mem_gui.py); the screen is never grabbed."""
import ctypes
import ctypes.wintypes as wt
import os
import time

user32 = ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# Handles are 64-bit; tell ctypes so they don't get truncated
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

from paths import APP as HERE  # noqa: E402  (where we write)
STOP_FILE = os.path.join(HERE, "stop.flag")

VK_F8 = 0x77
SCANCODES = {"e": 0x12, "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20, "space": 0x39, "f11": 0x57}


class StopBot(Exception):
    """Raised when F8 is pressed or stop.flag appears."""


class WindowLost(Exception):
    """The Roblox window is gone (closed, crashed, or kicked from the game)."""


# ---------- window ----------

def find_roblox():
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        # Check by window title or by process name (Roblox in fullscreen may have empty title)
        is_roblox = (buf.value == "Roblox"
                     or (buf.value == "" and cls.value in ("WINDOWSCLIENT", "RobloxPlayerBeta")))
        # Also check if the process is RobloxPlayerBeta (fullscreen may not set the title)
        if not is_roblox:
            try:
                import psutil
                p = psutil.Process(pid.value)
                if "roblox" in p.name().lower():
                    is_roblox = True
            except Exception:
                pass
        if is_roblox:
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    # Prefer visible windows, then WINDOWSCLIENT class
    found.sort(key=lambda hwnd: (not user32.IsWindowVisible(hwnd), window_class(hwnd) != "WINDOWSCLIENT"))
    if found:
        return found[0]
    # Fallback: try FindWindow with Roblox's class name
    for cls_name in ("WINDOWSCLIENT", "RobloxPlayerBeta", "Roblox"):
        hwnd = user32.FindWindowW(cls_name, None)
        if hwnd:
            return hwnd
    return None


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


user32.MonitorFromWindow.restype = wt.HANDLE
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
GWL_STYLE, WS_CAPTION = -16, 0x00C00000


def window_is_fullscreen(hwnd):
    """True when Roblox is in F11 fullscreen: no title bar, and the window covers its whole monitor."""
    if not hwnd or user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CAPTION:
        return False
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    mon = MONITORINFO(ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mon))  # 2: nearest monitor
    m = mon.rcMonitor
    return (r.left, r.top, r.right, r.bottom) == (m.left, m.top, m.right, m.bottom)


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


# ---------- input ----------

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, 0)
    _send(inp)


MOUSE_MOVE, MOUSE_DOWN, MOUSE_UP, MOUSE_WHEEL = 0x0001, 0x0002, 0x0004, 0x0800


# ---------- the game ----------

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002


class Game:
    def __init__(self):
        self.hwnd = find_roblox()
        if not self.hwnd:
            raise SystemExit("Couldn't find the Roblox window. Open the game first.")
        # Tell Windows this program is busy so it doesn't turn the display off or sleep
        # while the bot runs (clicks on a dark, locked display go nowhere).
        # It only lasts as long as this program; no Windows setting is changed.
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        self.wake_display()
        self.held = set()
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
        w, h = self.size()
        print(f"Found Roblox ({window_class(self.hwnd)}), {w}x{h}")

    def reattach(self):
        """Pick up a new Roblox window (after the game was closed and started again).
        False if there is none."""
        hwnd = find_roblox()
        if not hwnd:
            return False
        self.release_all()
        self.hwnd = hwnd
        self.held = set()
        self.wake_display()
        return True

    def ensure_fullscreen(self, log=print):
        """Put Roblox in F11 fullscreen, so the window is the whole screen on every PC (no title
        bar, no taskbar strip). Roblox remembers the setting, so this usually finds it done.
        Returns True when the window fills the screen."""
        if window_is_fullscreen(self.hwnd):
            log("Roblox is already fullscreen")
            return True
        for _ in range(2):
            log("Pressing F11")
            self.focus()
            self.tap("f11", 0.06)
            end = time.time() + 4
            while time.time() < end:
                self.wait(0.25)
                if window_is_fullscreen(self.hwnd):
                    log("Roblox is now fullscreen (F11)")
                    return True
        log("Couldn't put Roblox in fullscreen")
        return False

    _stop_checked, _stop_file = 0.0, False
    cleaning = False  # set while tidying the screen on the way out: a stop request is already being obeyed

    def check_stop(self):
        if self.cleaning:
            return
        now = time.time()
        if now - self._stop_checked > 0.2:  # (a file lookup per frame is slow on a PC with a busy virus scanner)
            self._stop_checked = now
            self._stop_file = os.path.exists(STOP_FILE)
        if user32.GetAsyncKeyState(VK_F8) & 0x8000 or self._stop_file:
            raise StopBot()

    def alive(self):
        """Where F8 / stop.flag (StopBot) and a closed Roblox window (WindowLost) are noticed."""
        self.check_stop()
        if not user32.IsWindow(self.hwnd):
            raise WindowLost()

    def wake_display(self):
        """A one-pixel mouse nudge there and back: any input wakes a sleeping display."""
        _mouse(MOUSE_MOVE, 1, 0)
        time.sleep(0.05)
        _mouse(MOUSE_MOVE, -1, 0)
        time.sleep(0.5)

    def wait(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.check_stop()
            time.sleep(min(0.1, max(0, end - time.time())))

    def focus(self):
        if user32.GetForegroundWindow() == self.hwnd:
            return
        user32.keybd_event(0x12, 0, 0, 0)  # tapping Alt lets us take the foreground
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.1)

    # keyboard
    def key(self, name, down):
        if down == (name in self.held):
            return
        if down:
            self.focus()
        inp = INPUT(type=1)
        inp.ki = KEYBDINPUT(0, SCANCODES[name], 0x0008 | (0 if down else 0x0002), 0, 0)
        _send(inp)
        (self.held.add if down else self.held.discard)(name)

    def tap(self, name, hold=0.1):
        self.key(name, True)
        time.sleep(hold)
        self.key(name, False)

    def release_all(self):
        for name in list(self.held):
            self.key(name, False)

    # mouse (x, y are window pixels, as the game's GUI positions are)
    def _move_to(self, x, y):
        pt = wt.POINT(int(x), int(y))
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        user32.SetCursorPos(pt.x, pt.y)
        # Roblox only notices real mouse movement, so nudge it
        _mouse(MOUSE_MOVE, 1, 0)
        _mouse(MOUSE_MOVE, -1, 0)
        time.sleep(0.05)

    def click(self, x, y):
        self.focus()
        self._move_to(x, y)
        _mouse(MOUSE_DOWN)
        time.sleep(0.05)
        _mouse(MOUSE_UP)
        time.sleep(0.1)

    def park_mouse(self):
        """Move the cursor to an empty part of the screen so it isn't hovering a button."""
        r = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        self._move_to(r.right * 0.3, r.bottom * 0.3)

    def menu_open(self, img=None):
        """True if a menu with a red X (Packs, Card Market, Gifts, Daily...) is showing (read in memory)."""
        from packs import open_menus
        return bool(open_menus())

    def scroll(self, x, y, notches, check=True):
        """Scroll a menu: positive up, negative down. Refused if no menu is open,
        since the wheel over the game world zooms the camera. (check=False skips that
        look, for a caller that has just made sure the menu is open: it takes ~0.3s.)"""
        if check and not self.menu_open():
            print("Not scrolling: no menu open (it would zoom the camera).")
            return False
        self.focus()
        self._move_to(x, y)
        for _ in range(abs(notches)):
            _mouse(MOUSE_WHEEL, data=120 if notches > 0 else -120)
            time.sleep(0.03)
        return True

    def size(self):
        """(width, height) of the window's inside, in the pixels the mouse and the game's GUI use."""
        r = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        return r.right, r.bottom

    def ui_scale(self, img=None):
        """How big Roblox draws its menus, relative to a 1920x1080 window (where the side buttons are 180 px wide).
        Roblox doesn't shrink the UI evenly with the window, so it's measured in memory off the Daily button's width
        (once per window size)."""
        cache = self.__dict__.setdefault("_ui_scales", {})
        size = self.size()
        if size in cache:
            return cache[size]
        import mem_gui
        g = mem_gui.gui()
        btn = mem_gui.locate(name="DailyBtn", screen="CardsUI") and g and next(
            (o for _, o in g.mb._walk(mem_gui.screen("CardsUI"), 4, 4000) if g.mb._name(o) == "DailyBtn"), None)
        geo = g.geom(btn) if btn else None
        if not geo or geo[2] <= 0:
            return 1.0  # (not in memory right now: try again next time)
        cache[size] = round(geo[2] / 180, 3)
        print(f"Roblox UI scale for {size[0]}x{size[1]}: {cache[size]:.2f}")
        return cache[size]
