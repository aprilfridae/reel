"""Files the bot and the website share (in web/data/), written atomically so neither
side ever reads half a file.

  market.json    latest market scan (bot writes)
  requests.json  bids / buy-nows asked for on the website, and their results
  chat.json      game chat as read off the screen (bot writes)
  outbox.json    chat messages typed on the website, waiting to be sent in game
  status.json    what the bot is doing (bot writes)
"""
import json
import msvcrt
import os
import threading
import time

from paths import APP as HERE  # noqa: E402
DATA = os.path.join(HERE, "web", "data")
_lock = threading.Lock()


def path(name):
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, name)


def load(name, default):
    try:
        with open(path(name), encoding="utf-8-sig") as f:  # -sig: files saved by PowerShell start with a BOM
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, data):
    # (a temp file of its own per process and thread: two writers never share one)
    tmp = f"{path(name)}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    for _ in range(20):  # the other side may have the file open for a moment
        try:
            os.replace(tmp, path(name))
            return
        except PermissionError:
            time.sleep(0.05)
    try:
        os.remove(tmp)  # couldn't replace it: don't leave the temp file behind
    except OSError:
        pass


class _ProcessLock:
    """A lock shared by every program using these files. The bot and the website can be
    two separate programs, each changing requests.json / outbox.json / mode.json (the
    website adds a request, the bot marks it done): without this, one could overwrite
    the other's change."""

    def __enter__(self):
        os.makedirs(DATA, exist_ok=True)
        self.f = open(os.path.join(DATA, ".lock"), "a+")
        for _ in range(300):  # up to ~3s, then carry on rather than hang
            try:
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.held = True
                return self
            except OSError:
                time.sleep(0.01)
        self.held = False
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self.f.close()


def update(name, default, fn):
    """Load, change with fn(data) -> data, save; as one step."""
    with _lock, _ProcessLock():
        data = fn(load(name, default))
        save(name, data)
        return data


def set_status(text):
    save("status.json", {"text": text, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
