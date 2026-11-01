"""Saves one full-size picture of the game window as grab.png (doesn't click anything)."""
import cv2

from game import WindowCapture, find_roblox

cap = WindowCapture(find_roblox(), fast=False)
cap.from_screen = True
cv2.imwrite("grab.png", cap.grab())
