"""reel. People run the packaged program (the file is still UndergroundBot.exe).

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
    """--selftest: check that the pieces a packaged copy needs load (the game's memory reader, the bot, the
    website) without touching the game. Exit code 1 if any don't."""
    import importlib

    ok = True
    for name in ("memory_backend", "mem_gui", "bot", "web.app"):
        try:
            importlib.import_module(name)
            print(f"{name}: OK")
        except Exception as e:
            print(f"{name}: FAILED ({e})")
            ok = False
    return 0 if ok else 1


def main():
    import sys
    if "--selftest" in sys.argv:
        return selftest()
    import updater
    from version import VERSION
    updater.wait_for_previous()  # just updated: the old copy must be gone (it holds the website's port)
    cfg = config.load()
    print(f"reel {VERSION}", flush=True)
    if cfg["website"]:
        start_website(cfg["website_port"])
    if cfg["auto_update"]:
        updater.start()

    # Memory poller: reads game state from Roblox memory in the background (balance, fishing state, event
    # banner, outbid) for the website. It shares the bot's memory reader, and waits for it in the background
    # (Roblox may not be open yet, and finding the game in memory takes a while the first time).
    poller = {}
    if cfg["memory_polling"]:
        def start_poller():
            import time
            from memory_backend import get_backend
            from mem_poller import MemoryPoller
            while True:
                try:
                    mb = get_backend()
                    break
                except Exception as e:
                    print(f"(memory polling waits: {e})", flush=True)
                    time.sleep(30)
            poller["p"] = MemoryPoller(mb, log=lambda m: print(f"[mem] {m}", flush=True))
            poller["p"].start()
        threading.Thread(target=start_poller, daemon=True, name="memory-poller-start").start()

    import bot
    bot.main()

    if poller.get("p"):
        poller["p"].stop()
    if updater.pending():
        updater.install_and_restart()


if __name__ == "__main__":
    import sys
    multiprocessing.freeze_support()
    sys.exit(main() or 0)
