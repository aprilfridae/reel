"""Checks why the bot isn't clicking: window size, what it can see, and whether
it can move the mouse. Run with Roblox open:  python diag.py"""
import ctypes
import ctypes.wintypes as wt
import time

import cv2

from game import Game, user32
from vision import detect

g = Game()
img = g.frame()
h, w = img.shape[:2]
print(f"Roblox window: {w}x{h}, UI scale {g.ui_scale(img):.2f}")
print(f"Screen DPI scale: {ctypes.windll.user32.GetDpiForWindow(g.hwnd) / 96:.0%}")
print(f"Roblox in front: {user32.GetForegroundWindow() == g.hwnd}")
print(f"Python running as admin: {bool(ctypes.windll.shell32.IsUserAnAdmin())}")

print("\nWhat the bot can find (score 1.00 = perfect, needs 0.80+):")
for name in ("teleports_button", "packs_button", "popup_log"):
    hit = g.find(name, img, threshold=0.0)
    print(f"  {name:18s} score {hit[2]:.2f} at {hit[:2]}")
print(f"  fishing panel: {detect(img, g.ui_scale(img))}")
cv2.imwrite("diag.png", img)
print("\nSaved a screenshot of what the bot sees: diag.png")

print("\nMouse test: the cursor should jump to the middle of Roblox, then move right.")
pt = wt.POINT()
user32.GetCursorPos(ctypes.byref(pt))
before = (pt.x, pt.y)
g.focus()
g._move_to(w // 2, h // 2)
time.sleep(0.3)
user32.GetCursorPos(ctypes.byref(pt))
mid = (pt.x, pt.y)
g._move_to(w // 2 + 200, h // 2)
time.sleep(0.3)
user32.GetCursorPos(ctypes.byref(pt))
after = (pt.x, pt.y)
print(f"  cursor: before {before} -> middle {mid} -> right {after}")
print("  mouse moved: " + ("YES" if mid != before and after != mid else "NO"))
