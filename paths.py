"""Where files live.

When the program runs as a packaged .exe, the files bundled inside it (the button
pictures in templates/, the website page) are unpacked to a temporary folder (RES), while
everything the bot writes (settings, logs, saved cards, the website's data) goes in the
folder next to the .exe (APP), so it survives restarts. Run from source, both are the
project folder.
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
APP = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
