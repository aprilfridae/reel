"""Roblox window access: capture, mouse/keyboard input, and finding buttons on screen."""
import ctypes
import ctypes.wintypes as wt
import os
import threading
import time

import cv2
import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# Handles are 64-bit; tell ctypes so they don't get truncated
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

from paths import APP as HERE, RES  # noqa: E402  (HERE: where we write; RES: bundled pictures)
TEMPLATES = os.path.join(RES, "templates")
STOP_FILE = os.path.join(HERE, "stop.flag")

VK_F8 = 0x77
MENU_CLOSE_BUTTONS = ("close_menu", "close_market", "close_daily", "close_gifts")
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
        if buf.value == "Roblox" and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    # Prefer the normal Roblox player (class WINDOWSCLIENT) over e.g. the Store app's frame
    found.sort(key=lambda hwnd: window_class(hwnd) != "WINDOWSCLIENT")
    return found[0] if found else None


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


user32.MonitorFromWindow.restype = wt.HANDLE
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]


def window_is_fullscreen(hwnd):
    """True when the window covers its whole monitor (Roblox's F11 fullscreen), taskbar and all."""
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    mon = MONITORINFO(ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mon))  # 2: nearest monitor
    m = mon.rcMonitor
    return (r.left, r.top, r.right, r.bottom) == (m.left, m.top, m.right, m.bottom)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


class WindowCapture:
    """Grabs the Roblox window even when other windows cover it (not when minimized).
    Some setups (e.g. the Microsoft Store Roblox) give a black picture that way; then it
    copies the window's area off the screen instead, which needs Roblox to be on top."""

    def __init__(self, hwnd, fast=True):
        self.hwnd = hwnd
        self.size = None
        self.from_screen = False
        # Fast path: stream the screen straight from the GPU (dxcam, ~8 ms a frame
        # vs ~30 ms). Needs Roblox on top and unobstructed, which it is on a PC
        # nobody is using; the bot keeps it in front anyway.
        self.cam = None
        if fast:
            try:
                import dxcam
                self.cam = dxcam.create(output_color="BGR")
                self.cam.start(target_fps=144, video_mode=True)
            except Exception as e:  # not installed, or no desktop to duplicate
                print(f"Fast capture unavailable ({e}); using window capture.")
                self.cam = None

    @property
    def mode(self):
        return "stream" if self.cam else ("screen" if self.from_screen else "window")

    def _stream_frame(self, timeout):
        """The newest streamed frame, or None if none arrives within `timeout` seconds.
        dxcam's own get_latest_frame() waits forever when the display is off (or the
        screen is locked), because nothing is drawn, so it runs in a helper thread
        that this waits on; a call still stuck from last time is reused, not stacked."""
        pending = getattr(self, "_pending", None)
        if pending is None:
            box = {"event": threading.Event(), "frame": None}

            def work():
                try:
                    box["frame"] = self.cam.get_latest_frame()
                finally:
                    box["event"].set()

            threading.Thread(target=work, daemon=True).start()
            pending = self._pending = box
        if not pending["event"].wait(timeout):
            return None
        self._pending = None
        return pending["frame"]

    def _set_stream_region(self, region):
        """Point the stream at (left, top, right, bottom) in screen pixels, or the whole screen (None). A strip
        costs the PC far less to copy than the whole screen; switching takes ~20 ms."""
        want = tuple(region) if region else (0, 0, self.cam.width, self.cam.height)
        if getattr(self, "_stream_region", (0, 0, self.cam.width, self.cam.height)) == want:
            return
        self.cam.stop()
        self._pending = None  # a helper still waiting on the old stream is abandoned
        self.cam.start(region=want, target_fps=144, video_mode=True)
        self._stream_region = want

    def _grab_stream(self, w, h):
        self._set_stream_region(None)
        frame = self._stream_frame(1.0)
        if frame is None:
            return None
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        x, y = max(0, pt.x), max(0, pt.y)
        if (x, y) == (0, 0) and frame.shape[:2] == (h, w):
            return frame  # fullscreen: the window is the whole frame (it's already our own copy)
        return frame[y:y + h, x:x + w].copy()

    def _setup(self, w, h):
        if self.size:
            gdi32.DeleteObject(self.bmp)
            gdi32.DeleteDC(self.mem)
            user32.ReleaseDC(self.hwnd, self.wdc)
        self.wdc = user32.GetDC(self.hwnd)
        self.mem = gdi32.CreateCompatibleDC(self.wdc)
        self.bmp = gdi32.CreateCompatibleBitmap(self.wdc, w, h)
        gdi32.SelectObject(self.mem, self.bmp)
        self.info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.buf = np.empty((h, w, 4), np.uint8)
        self.size = (w, h)

    def grab_region(self, x0, y0, x1, y1):
        """Only this rectangle of the window (client pixels), copied off the screen, as a full-size
        picture that is black everywhere else (so positions are the same as in a full frame).
        For PCs without the fast GPU stream, where a whole frame takes ~100 ms but this tiny part
        a few. None when it can't be done (stream mode, or the window moved/minimized)."""
        r = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        w, h = r.right, r.bottom
        x0, y0, x1, y1 = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
        cw, ch = x1 - x0, y1 - y0
        if w < 100 or h < 100 or cw < 8 or ch < 8:
            return None
        if self.cam:  # the stream, pointed at just this strip
            pt = wt.POINT(0, 0)
            user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
            self._set_stream_region((pt.x + x0, pt.y + y0, pt.x + x1, pt.y + y1))
            frame = self._stream_frame(1.0)
            if frame is None or frame.shape[:2] != (ch, cw):
                return None  # (a frame of the old region, or none yet)
            if getattr(self, "_canvas", None) is None or self._canvas.shape[:2] != (h, w):
                self._canvas = np.zeros((h, w, 3), np.uint8)
            self._canvas[y0:y1, x0:x1] = frame
            return self._canvas
        if getattr(self, "_rsize", None) != (cw, ch):
            if getattr(self, "_rsize", None):
                gdi32.DeleteObject(self.rbmp)
                gdi32.DeleteDC(self.rmem)
            screen = user32.GetDC(None)
            self.rmem = gdi32.CreateCompatibleDC(screen)
            self.rbmp = gdi32.CreateCompatibleBitmap(screen, cw, ch)
            user32.ReleaseDC(None, screen)
            gdi32.SelectObject(self.rmem, self.rbmp)
            self.rinfo = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), cw, -ch, 1, 32, 0, 0, 0, 0, 0, 0)
            self.rbuf = np.empty((ch, cw, 4), np.uint8)
            self._rsize = (cw, ch)
        if getattr(self, "_canvas", None) is None or self._canvas.shape[:2] != (h, w):
            self._canvas = np.zeros((h, w, 3), np.uint8)
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        screen = user32.GetDC(None)
        gdi32.BitBlt(self.rmem, 0, 0, cw, ch, screen, pt.x + x0, pt.y + y0, 0x00CC0020)  # SRCCOPY
        user32.ReleaseDC(None, screen)
        gdi32.GetDIBits(self.rmem, self.rbmp, 0, ch, self.rbuf.ctypes.data, ctypes.byref(self.rinfo), 0)
        self._canvas[y0:y1, x0:x1] = self.rbuf[:, :, :3]
        return self._canvas

    def grab(self):
        r = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        w, h = r.right, r.bottom
        if w < 100 or h < 100:
            return None  # minimized
        stalled = False
        if self.cam:
            frame = self._grab_stream(w, h)
            if frame is not None:
                self.stalled = False
                return frame
            # No frame in a second: the display is probably off or the screen locked.
            # Try a one-off grab of the window itself, without leaving stream mode.
            if not getattr(self, "stalled", False):
                print("Screen capture stalled (display off or locked?); trying the window directly.")
                self.stalled = True
            stalled = True
        if self.size != (w, h):
            self._setup(w, h)
        if not self.from_screen or stalled:
            user32.PrintWindow(self.hwnd, self.mem, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            gdi32.GetDIBits(self.mem, self.bmp, 0, h, self.buf.ctypes.data, ctypes.byref(self.info), 0)
            img = self.buf[:, :, :3]
            if img.max() > 0 or stalled:
                return img.copy()
            print("Window capture came back black; reading Roblox off the screen instead "
                  "(keep Roblox on top).")
            self.from_screen = True
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        screen = user32.GetDC(None)
        gdi32.BitBlt(self.mem, 0, 0, w, h, screen, pt.x, pt.y, 0x00CC0020)  # SRCCOPY
        user32.ReleaseDC(None, screen)
        gdi32.GetDIBits(self.mem, self.bmp, 0, h, self.buf.ctypes.data, ctypes.byref(self.info), 0)
        return self.buf[:, :, :3].copy()


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
        # while the bot runs (a dark display gives the screen capture nothing to read).
        # It only lasts as long as this program; no Windows setting is changed.
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        self.wake_display()
        self.cap = WindowCapture(self.hwnd)
        self.held = set()
        self._templates = {}
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
        img = self.cap.grab()
        size = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "minimized"
        print(f"Found Roblox ({window_class(self.hwnd)}), {size}, capture: {self.cap.mode}")

    def reattach(self):
        """Pick up a new Roblox window (after the game was closed and started again).
        False if there is none."""
        hwnd = find_roblox()
        if not hwnd:
            return False
        self.release_all()
        try:
            self.cap.close()
        except Exception:
            pass
        self.hwnd = hwnd
        self.cap = WindowCapture(hwnd)
        self.held = set()
        self.wake_display()
        return True

    def ensure_fullscreen(self, log=print):
        """Put Roblox in F11 fullscreen, so the window is the whole screen on every PC (no title
        bar, no taskbar strip). Roblox remembers the setting, so this usually finds it done.
        Returns True when the window fills the screen."""
        if window_is_fullscreen(self.hwnd):
            return True
        for _ in range(2):
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

    def frame(self):
        """Latest picture of the Roblox window. Also where F8 / stop.flag is noticed."""
        while True:
            self.check_stop()
            if not user32.IsWindow(self.hwnd):
                raise WindowLost()
            if self.cap.cam and user32.GetForegroundWindow() != self.hwnd:
                # Fast capture reads the screen itself, so Roblox has to be in front
                self.focus()
                time.sleep(0.1)
            t0 = time.time()
            img = self.cap.grab()
            if img is not None and img[::48, ::48].any():  # (a sample of pixels: a whole-frame max() costs ms on a weak PC)
                self._note_grab(time.time() - t0)
                return img
            print("Can't see Roblox (minimized, or the display is off). Waking the display...")
            self.wake_display()
            time.sleep(2)

    grab_ms, grab_n, strips = 0.0, 0, False

    def _note_grab(self, seconds):
        """Watch how long whole frames take. On a PC where that is long (27 ms on one weak PC; 8 on a good one) the
        stream is pointed at just the reel strip while fishing (see panel_capture)."""
        self.grab_n += 1
        self.grab_ms = seconds * 1000 if self.grab_n == 1 else 0.95 * self.grab_ms + 0.05 * seconds * 1000
        if self.cap.cam and not self.strips and self.grab_n >= 60 and self.grab_ms > 15:
            self.strips = True
            print(f"Whole frames take {self.grab_ms:.0f} ms here: reading just the reel strip while fishing.", flush=True)

    @property
    def slow_capture(self):
        """True when frames come from window/screen copies (no GPU stream): about 100 ms a frame on a weak PC."""
        return not self.cap.cam

    @property
    def panel_capture(self):
        """Fishing reads only the strip around the reel panel: always without the stream, and with it on a PC where
        whole frames are slow."""
        return self.slow_capture or self.strips

    def panel_frame(self, rows_from_bottom, half_width, scale):
        """A frame holding only the strip around the reel panel (see WindowCapture.grab_region): several
        times quicker than frame() when there's no GPU stream. Falls back to frame()."""
        self.check_stop()
        if not user32.IsWindow(self.hwnd):
            raise WindowLost()
        if user32.GetForegroundWindow() != self.hwnd:
            self.focus()  # reading the screen itself: Roblox has to be in front
        r = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        w, h = r.right, r.bottom
        img = self.cap.grab_region(w / 2 - half_width * scale, h - rows_from_bottom[0] * scale,
                                   w / 2 + half_width * scale, h - rows_from_bottom[1] * scale)
        if img is None or not img[int(h - rows_from_bottom[0] * scale):int(h - rows_from_bottom[1] * scale):8,
                                  int(w / 2 - half_width * scale):int(w / 2 + half_width * scale):8].any():
            return self.frame()
        return img

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

    # mouse (x, y are window pixels, as in frame())
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
        """True if a menu with a red X (Packs, Card Market, Gifts, Daily...) is showing."""
        img = self.frame() if img is None else img
        h, w = img.shape[:2]
        middle = (w * 0.15, h * 0.05, w * 0.85, h * 0.95)
        return any(self.find(n, img, 0.85, region=middle, optional=True) for n in MENU_CLOSE_BUTTONS)

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

    # finding things on screen
    def _template(self, name, scale, white_text=False):
        key = (name, round(scale, 2), white_text)
        if key not in self._templates:
            t = cv2.imread(os.path.join(TEMPLATES, name + ".png"), cv2.IMREAD_GRAYSCALE)
            if t is None:
                raise FileNotFoundError(f"templates/{name}.png is missing")
            if abs(scale - 1) > 0.01:
                t = cv2.resize(t, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            if white_text:
                t = self._white(t)
            self._templates[key] = t
        return self._templates[key]

    @staticmethod
    def _white(gray):
        return np.where(gray > 200, 255, 0).astype(np.uint8)

    def _text_color(self, patch):
        """Average color of the brightest quarter of pixels (the lettering)."""
        gray = patch.mean(axis=2)
        mask = gray >= np.percentile(gray, 75)
        return patch[mask].mean(axis=0)

    def ui_scale(self, img):
        """How big Roblox draws its buttons, relative to the templates. Roblox doesn't
        shrink the UI evenly with the window, so it's measured off the always-visible
        Packs button (once per window size)."""
        cache = self.__dict__.setdefault("_ui_scales", {})
        size = img.shape[:2]
        if size in cache:
            return cache[size]
        # Don't redo the (slow) search every frame while the button is hidden
        last_try = self.__dict__.setdefault("_ui_scale_tried", {})
        if time.time() - last_try.get(size, 0) < 10:
            return 1.0
        last_try[size] = time.time()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        t0 = cv2.imread(os.path.join(TEMPLATES, "packs_button.png"), cv2.IMREAD_GRAYSCALE)
        best_score, best = 0, 1.0
        for s in np.arange(0.5, 1.41, 0.02):
            t = cv2.resize(t0, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            if t.shape[0] > gray.shape[0] or t.shape[1] > gray.shape[1]:
                continue
            score = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))[1]
            if score > best_score:
                best_score, best = score, float(s)
        if best_score < 0.8:
            return 1.0  # Packs button hidden right now (e.g. a menu is open); try again later
        cache[size] = best
        print(f"Roblox UI scale for {size[1]}x{size[0]}: {best:.2f}")
        return best

    def find_all(self, name, img, threshold=0.8, region=None, color_check=False, white_text=False):
        """Centers (x, y, score) of every match, best first. region = (x0, y0, x1, y1).
        color_check also requires the lettering color to match the template's.
        white_text matches only the white lettering, ignoring what's behind it."""
        scale = self.ui_scale(img)
        t = self._template(name, scale, white_text)
        if color_check:
            want = self._text_color(cv2.imread(os.path.join(TEMPLATES, name + ".png")).astype(float))
        x0, y0 = 0, 0
        if region:
            x0, y0, x1, y1 = (max(0, int(v)) for v in region)
            img = img[y0:y1, x0:x1]
        if img.shape[0] < t.shape[0] or img.shape[1] < t.shape[1]:
            return []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if white_text:
            gray = self._white(gray)
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        th, tw = t.shape
        hits = []
        while True:
            _, score, _, (mx, my) = cv2.minMaxLoc(res)
            if score < threshold:
                break
            res[max(0, my - th // 2):my + th // 2 + 1, max(0, mx - tw // 2):mx + tw // 2 + 1] = -1
            if color_check:
                got = self._text_color(img[my:my + th, mx:mx + tw].astype(float))
                if np.abs(got - want).max() > 45:
                    continue
            hits.append((x0 + mx + tw // 2, y0 + my + th // 2, score))
        return hits

    def find(self, name, img, threshold=0.8, region=None, color_check=False, white_text=False,
             optional=False):
        """Best match or None. optional: a missing template counts as not found."""
        if optional and not os.path.exists(os.path.join(TEMPLATES, name + ".png")):
            return None
        hits = self.find_all(name, img, threshold, region, color_check, white_text)
        return hits[0] if hits else None
