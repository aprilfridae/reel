"""Files the bot and the website share (in web/data/), written atomically so neither
side ever reads half a file.

  market.json    latest market scan (bot writes)
  requests.json  bids / buy-nows asked for on the website, and their results
  chat.json      game chat as read off the screen (bot writes)
  outbox.json    chat messages typed on the website, waiting to be sent in game
  status.json    what the bot is doing (bot writes)
"""
import json
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
    tmp = path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    for _ in range(20):  # the other side may have the file open for a moment
        try:
            os.replace(tmp, path(name))
            return
        except PermissionError:
            time.sleep(0.05)


def update(name, default, fn):
    """Load, change with fn(data) -> data, save; as one step."""
    with _lock:
        data = fn(load(name, default))
        save(name, data)
        return data


def set_status(text):
    save("status.json", {"text": text, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
