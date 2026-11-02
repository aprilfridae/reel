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
    button pictures, screen capture libraries) without touching the game. Exit code 1 if any don't."""
    import importlib.util

    import cv2
    import numpy as np

    from game import TEMPLATES
    from ocr import read_text

    img = np.full((120, 500, 3), 255, np.uint8)
    cv2.putText(img, "Rebirths: 120", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    text = read_text(img)
    ok_text = "120" in text
    print("text reading:", "OK" if ok_text else f"FAILED (read {text!r})")
    n = len([f for f in os.listdir(TEMPLATES) if f.endswith(".png")])
    print(f"button pictures: {n} found", "(OK)" if n > 30 else "(FAILED)")
    ok_capture = importlib.util.find_spec("dxcam") is not None
    print("screen capture library:", "OK" if ok_capture else "MISSING")
    return 0 if ok_text and n > 30 and ok_capture else 1


def main():
    import sys
    if "--selftest" in sys.argv:
        return selftest()
    import updater
    from version import VERSION
    updater.wait_for_previous()  # just updated: the old copy must be gone (it holds the website's port)
    cfg = config.load()
    print(f"UndergroundBot {VERSION} (memory-reading fork)", flush=True)
    if cfg["website"]:
        start_website(cfg["website_port"])
    if cfg["auto_update"]:
        updater.start()

    # Memory poller: reads game state from Roblox memory in the background
    # (balance, fishing state, event banner, outbid, trade requests) and
    # writes it to web/data/ so the website is always up to date.
    mem_poller = None
    mb = None
    if cfg.get("memory_polling", True):
        try:
            from memory_backend import MemoryBackend
            from mem_poller import MemoryPoller
            mb = MemoryBackend()
            mb.start()
            mem_poller = MemoryPoller(mb, log=lambda m: print(f"[mem] {m}", flush=True))
            mem_poller.start()
        except Exception as e:
            print(f"(memory polling unavailable: {e})", flush=True)

    import bot
    bot.main()

    if mem_poller:
        mem_poller.stop()
    if mb:
        mb.close()
    if updater.pending():
        updater.install_and_restart()


if __name__ == "__main__":
    import sys
    multiprocessing.freeze_support()
    sys.exit(main() or 0)
