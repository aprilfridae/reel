"""The website's live log of packs: every pack the bot opens (with any #1 cards seen on its reveal screen) and the
auto-roll's packs (counted from the label at the bottom right; the rarer ones are listed one by one).

  packlog.json    [{id, ts, time, kind: "open"|"roll", pack, ones, shot, n}]   newest last, 300 kept
  packroll.json   {since, total, by_kind: {"gold": 120, ...}, last, at}         the roll counter
"""
import os
import re
import threading
import time
import uuid

import cv2

import webstate
from paths import APP

SHOTS = os.path.join(APP, "web", "static", "packs")
KEEP = 300
NOTABLE_ROLLS = {"iced", "radiation", "kawaii", "glitched", "atlantis", "blood_moon", "eclipse", "meteor", "acid",
                 "tsunami", "storm", "volcano"}  # (listed one by one; the rest are only counted)
MAX_JUMP = 150  # packs between two reads of the label: more than that is a misread digit
_lock = threading.Lock()
_roll = {"since": time.strftime("%H:%M:%S"), "total": None, "start": None, "by_kind": {}, "last": None, "saved": 0.0,
         "odd": []}


def _human(key):
    return " ".join(w.capitalize() for w in str(key).split("_")) + " Pack"


def _add(entry):
    entry.update(id=uuid.uuid4().hex[:8], ts=time.time(), time=time.strftime("%H:%M:%S"))
    webstate.update("packlog.json", [], lambda log: (log + [entry])[-KEEP:])


KEEP_SHOTS = 150  # reveal pictures kept (older ones are deleted; their log lines keep no picture)


def record_open(pack, n, img, ones=0, others=()):
    """One pack reveal, with a picture of it for the website."""
    shot = None
    try:
        os.makedirs(SHOTS, exist_ok=True)
        shot = f"pk_{int(time.time() * 1000)}.jpg"
        small = cv2.resize(img, (960, int(img.shape[0] * 960 / img.shape[1])), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(SHOTS, shot), small, [cv2.IMWRITE_JPEG_QUALITY, 72])
        for old in sorted(os.listdir(SHOTS))[:-KEEP_SHOTS]:
            os.remove(os.path.join(SHOTS, old))
    except OSError:
        shot = None
    _add({"kind": "open", "pack": _human(pack), "ones": int(ones), "others": list(others), "shot": shot, "n": n})


_COUNT = re.compile(r"\+\s*([\d,]+)\s*packs?", re.I)


def roll_seen(key, text):
    """The auto-roll label was read: `key` the pack named on it ('gold'), `text` all of it ('+17 packs . last: Gold Pack').
    Packs rolled since the last look are counted for that kind (the label only names the newest one)."""
    m = _COUNT.search(text or "")
    total = int(m.group(1).replace(",", "")) if m else None
    with _lock:
        r = _roll
        gained = 0
        if total is not None:
            if r["total"] is None or r["start"] is None:
                r["start"], r["total"] = total, total
            elif r["total"] <= total <= r["total"] + MAX_JUMP:
                gained = total - r["total"]
                r["total"] = total
                r["odd"] = []
            else:
                # a digit misread (or the game's counter restarted): only believe a new value once it repeats
                r["odd"] = (r["odd"] + [total])[-3:]
                if len(r["odd"]) == 3 and max(r["odd"]) - min(r["odd"]) <= MAX_JUMP:
                    r["start"] = total - (r["total"] - r["start"])  # keep the count of rolls so far unbroken
                    r["total"] = total
                    r["odd"] = []
        if key and gained:
            r["by_kind"][key] = r["by_kind"].get(key, 0) + gained
        if key:
            r["last"] = _human(key)
        if key and key in NOTABLE_ROLLS and gained:
            _add({"kind": "roll", "pack": _human(key), "ones": 0, "shot": None, "n": gained})
        if time.time() - r["saved"] > 3:  # the website needn't know every roll
            r["saved"] = time.time()
            webstate.save("packroll.json", {"since": r["since"], "rolled": (total - r["start"]) if total is not None and r["start"] is not None else None,
                                            "by_kind": dict(r["by_kind"]), "last": r["last"], "at": time.strftime("%H:%M:%S")})
