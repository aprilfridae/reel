"""The program people run (and what gets packaged into the .exe).

  UndergroundBot.exe              opens Roblox + the game if needed, then runs the bot, with
                                  the website on http://<this PC>:8080 for the home network
  UndergroundBot.exe --dry-run-rebirth    (testing: rebirths stop before the confirming click)

Settings live in config.json next to the program (written with the defaults on first run).
F8 (or creating stop.flag) stops the bot.
"""
import os

# numpy's OpenBLAS can fail to start ("DLL initialization routine failed") on some PCs;
# one thread is plenty for this program and avoids it. Must be set before numpy loads.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import multiprocessing  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402

import config  # noqa: E402


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "this-pc"


def start_website(port):
    from web.app import serve
    threading.Thread(target=serve, args=(port,), daemon=True).start()
    print(f"Website: http://{lan_address()}:{port}  (on your home network)", flush=True)


def selftest():
    """--selftest: check that the pieces a packaged copy needs work (text reading, the
    button pictures, screen capture libraries) without touching the game."""
    import os

    import cv2
    import numpy as np

    from game import TEMPLATES
    from ocr import read_text

    img = np.full((120, 500, 3), 255, np.uint8)
    cv2.putText(img, "Rebirths: 120", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    text = read_text(img)
    print("text reading:", "OK" if "120" in text else f"FAILED (read {text!r})")
    n = len([f for f in os.listdir(TEMPLATES) if f.endswith(".png")])
    print(f"button pictures: {n} found", "(OK)" if n > 30 else "(FAILED)")
    import importlib.util
    print("screen capture library:", "OK" if importlib.util.find_spec("dxcam") else "MISSING")


def main():
    import sys
    if "--selftest" in sys.argv:
        return selftest()
    cfg = config.load()
    if cfg["website"]:
        start_website(cfg["website_port"])
    import bot
    bot.main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
