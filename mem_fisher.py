"""Fishing for Underground Artist RNG — memory-reading version.

Replaces the CV-based vision.py reel detection with direct Roblox memory
reads. Detects fishing state (waiting / biting / caught) from the live
FishingUI text labels, and controls E key holds based on state.

Usage (standalone):
    python mem_fisher.py   (Roblox open, at a fishing spot; Ctrl-C stops)

Usage (inside bot_mem.py or bot.py):
    fisher = MemFisher()
    fisher.start()
    fisher.run(should_stop=..., on_catch=..., on_stuck=...)

Read-only memory access — no injection, no writes, no hooks.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory_backend import get_backend
from mem_catch_popup import read_catch_popup_mem

import ctypes as _ct
_user32 = _ct.windll.user32

CAST_DELAY = 0.3
RECAST_EVERY = 0.4
STUCK_AFTER = 15
WATCH_EVERY = 0.25  # seconds between the bot's looks at the screen (events, trades, chat) while not reeling


def _find_roblox_hwnd():
    found = []

    @_ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        buf = _ct.create_unicode_buffer(256)
        _user32.GetWindowTextW(hwnd, buf, 256)
        cls = _ct.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls, 256)
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        is_roblox = (buf.value == "Roblox"
                     or (buf.value == "" and cls.value in ("WINDOWSCLIENT", "RobloxPlayerBeta")))
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

    _user32.EnumWindows(cb, 0)
    found.sort(key=lambda hwnd: (not _user32.IsWindowVisible(hwnd),))
    return found[0] if found else None


def _focus(hwnd):
    if hwnd:
        _user32.keybd_event(0x12, 0, 0, 0)
        _user32.keybd_event(0x12, 0, 2, 0)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)


class MemFisher:
    def __init__(self, debug=False, log_path=None, on_log_ready=None, settings=None, mb=None, frame=None):
        self.mb = mb  # the shared backend (get_backend() in start() if none is given)
        self.frame = frame  # a screen frame for the bot's watch() (it reads events, trades and chat off the screen)
        self.debug = debug
        self.catches = 0
        self.log = open(log_path, "a", buffering=1) if log_path else None
        if self.log and self.log.tell() == 0:
            self.log.write("reel,t,state,hold,caught\n")
        self.on_log_ready = on_log_ready
        self.settings = settings or (lambda: {})
        self.state = "idle"
        self.idle_since = 0.0
        self.last_cast = 0.0
        self.pending = False
        self.reel_id = 0
        self.inp = None
        self.hwnd = None

    # ---- lifecycle -------------------------------------------------------
    def start(self):
        if self.mb is None:
            self.mb = get_backend()
        self.hwnd = _find_roblox_hwnd()
        if self.hwnd:
            print(f"[+] Roblox window found: 0x{self.hwnd:x}")
        else:
            print("[!] Roblox window not found (input disabled — memory reading still works)")

    def close(self):
        self._key("e", False)
        if self.inp:
            self.inp.release_all()
        if self.log:  # (the memory backend is shared: it stays open)
            self.log.close()

    # ---- input -----------------------------------------------------------
    def _key(self, name, down):
        if down and self.hwnd:
            _focus(self.hwnd)
        scancodes = {"e": 0x12}
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_size_t)]
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]
        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", ctypes.c_ulong), ("u", _U)]
        inp = INPUT(type=1)
        inp.ki = KEYBDINPUT(0, scancodes[name], 0x0008 | (0 if down else 0x0002), 0, 0)
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _tap(self, name, hold=0.1):
        self._key(name, True)
        time.sleep(hold)
        self._key(name, False)

    # ---- memory-backed helpers ------------------------------------------
    def _fish_state(self):
        return self.mb.fish_state()

    # ---- main loop -------------------------------------------------------
    def run(self, should_stop=lambda: False, on_catch=None, on_stuck=None,
            watch=None, act=None):
        watched = 0.0
        try:
            while True:
                if should_stop():
                    return
                now = time.time()
                # between reels, let the bot look at the screen (events, trades, chat, chores) and act on it
                if watch and self.frame and self.state != "reel" and now - watched > WATCH_EVERY:
                    watched = now
                    if watch(self.frame(), False):
                        self._key("e", False)
                        if act:
                            act()
                        if should_stop():
                            return
                        self.idle_since = time.time()
                        continue
                state = self._fish_state()

                if state == "biting":
                    if self.state != "reel":
                        self.state = "reel"
                        self.reel_t0 = now
                        if self.debug:
                            print("Bite detected — reeling.")
                    self._key("e", True)
                    time.sleep(0.01)
                    continue

                if state == "caught":
                    self._key("e", False)
                    self.catches += 1
                    won_pack, _ = read_catch_popup_mem(None, self.mb)
                    self.reel_id += 1
                    secs = max(time.time() - getattr(self, "reel_t0", now), 0.1)
                    msg = f"Reel finished ({self.catches} so far)"
                    if won_pack:
                        msg += ", got an Atlantis pack!"
                    print(msg)
                    if self.log:
                        self.log.write(f"{self.reel_id},{now:.3f},caught,1,{int(won_pack)}\n")
                        self.log.flush()
                    if on_catch:
                        on_catch()
                    self.state = "idle"
                    self.idle_since = time.time()
                    self.pending = False
                    continue

                if state == "waiting":
                    if self.state == "reel":
                        self._key("e", False)
                        self.state = "idle"
                        self.idle_since = now
                        self.pending = False
                        if self.debug:
                            print("Fish got away.")
                    if (now - self.idle_since > CAST_DELAY
                            and now - self.last_cast > RECAST_EVERY):
                        if now - self.idle_since > STUCK_AFTER:
                            print("Casting isn't working.")
                            if on_stuck:
                                on_stuck()
                        self._tap("e")
                        self.last_cast = time.time()
                    time.sleep(0.01)
                    continue

                # state is None: FishingUI not visible
                if self.state == "reel":
                    self._key("e", False)
                    self.state = "idle"
                    self.idle_since = now
                time.sleep(0.05)

        except KeyboardInterrupt:
            pass
        finally:
            self._key("e", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true", help="print state every second")
    args = ap.parse_args()

    fisher = MemFisher(debug=args.debug)
    print("Fishing (memory-reading). Press Ctrl-C to stop.")
    try:
        fisher.start()
        fisher.run()
    except KeyboardInterrupt:
        pass
    finally:
        fisher.close()
        print(f"Stopped. {fisher.catches} reels.")


if __name__ == "__main__":
    main()
