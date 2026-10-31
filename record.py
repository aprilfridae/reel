"""Record the Roblox window, plus E, W/A/S/D/space, mouse buttons and clicks.

Usage: python record.py [max_seconds]
Starts after a 5 second countdown. Press F8 to stop early.
Output: recordings/<date-time>/frame_00000.jpg ... and frames.csv
Each run gets its own folder, so older recordings are kept.
"""
import ctypes
import ctypes.wintypes as wt
import csv
import os
import sys
import time

import cv2
import mss
import numpy as np

FPS = 15
VK_E, VK_F8, VK_LBUTTON, VK_RBUTTON = 0x45, 0x77, 0x01, 0x02
MOVE_KEYS = {"w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44, "space": 0x20}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings",
                   time.strftime("%Y%m%d-%H%M%S"))

user32 = ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coordinates on scaled displays


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
    return found[0] if found else None


def client_rect(hwnd):
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return {"left": pt.x, "top": pt.y, "width": r.right, "height": r.bottom}


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def main():
    max_seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 180
    hwnd = find_roblox()
    if not hwnd:
        sys.exit("Couldn't find a window titled 'Roblox'. Open the game first.")

    os.makedirs(OUT, exist_ok=True)

    for i in range(5, 0, -1):
        print(f"Recording starts in {i}... switch to Roblox")
        time.sleep(1)
    print(f"Recording (up to {max_seconds:.0f}s). Press F8 to stop.")

    rows = []
    start = time.perf_counter()
    with mss.mss() as sct:
        n = 0
        while True:
            t = time.perf_counter() - start
            if t > max_seconds or key_down(VK_F8):
                break
            region = client_rect(hwnd)
            img = np.array(sct.grab(region))[:, :, :3]
            name = f"frame_{n:05d}.jpg"
            cv2.imwrite(os.path.join(OUT, name), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            keys = "".join(k[0] for k, vk in MOVE_KEYS.items() if key_down(vk))
            rows.append((n, f"{t:.3f}", int(key_down(VK_E)), int(key_down(VK_LBUTTON)),
                         pt.x - region["left"], pt.y - region["top"], keys,
                         int(key_down(VK_RBUTTON)), name))
            n += 1
            time.sleep(max(0, (n / FPS) - (time.perf_counter() - start)))

    with open(os.path.join(OUT, "frames.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "time", "e_down", "click", "mouse_x", "mouse_y", "keys", "right_mouse", "file"])
        w.writerows(rows)
    print(f"Saved {len(rows)} frames to {OUT}")


if __name__ == "__main__":
    main()
