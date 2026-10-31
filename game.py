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
REF_HEIGHT = 1369  # window height the templates were cut at

VK_F8 = 0x77
MENU_CLOSE_BUTTONS = ("close_menu", "close_market", "close_daily", "close_gifts")
SCANCODES = {"e": 0x12, "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20, "space": 0x39}


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

    def _grab_stream(self, w, h):
        frame = self._stream_frame(1.0)
        if frame is None:
            return None
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        x, y = max(0, pt.x), max(0, pt.y)
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
MOUSE_RIGHT_DOWN, MOUSE_RIGHT_UP = 0x0008, 0x0010


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

    cleaning = False  # set while tidying the screen on the way out: a stop request is already being obeyed

    def check_stop(self):
        if self.cleaning:
            return
        if user32.GetAsyncKeyState(VK_F8) & 0x8000 or os.path.exists(STOP_FILE):
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
            img = self.cap.grab()
            if img is not None and img.max() > 0:
                return img
            print("Can't see Roblox (minimized, or the display is off). Waking the display...")
            self.wake_display()
            time.sleep(2)

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

    # The camera is NEVER moved: recorded walks (market.ROUTE) only work if the camera
    # stays exactly where the game put it. So there is no right-drag anywhere, and the
    # mouse wheel is only used when a menu is open (over the world it would zoom).
    def drag_camera(self, *_, **__):
        raise RuntimeError("camera moves are disabled")

    turn_camera = drag_camera

    def menu_open(self, img=None):
        """True if a menu with a red X (Packs, Card Market, Gifts, Daily...) is showing."""
        img = self.frame() if img is None else img
        h, w = img.shape[:2]
        middle = (w * 0.15, h * 0.05, w * 0.85, h * 0.95)
        return any(self.find(n, img, 0.85, region=middle, optional=True) for n in MENU_CLOSE_BUTTONS)

    def scroll(self, x, y, notches):
        """Scroll a menu: positive up, negative down. Refused if no menu is open,
        since the wheel over the game world zooms the camera."""
        if not self.menu_open():
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

    def click_when_visible(self, name, timeout=5.0, threshold=0.8, white_text=False):
        end = time.time() + timeout
        while time.time() < end:
            hit = self.find(name, self.frame(), threshold, white_text=white_text)
            if hit:
                self.click(hit[0], hit[1])
                return True
            time.sleep(0.2)
        return False
