"""Game chat: read it off the screen, and send messages typed on the website.

Reading: the chat box sits at the top left. Its lines are OCR'd every few seconds
and only the new ones (past what was already there) are added to web/data/chat.json.
Sending: "/" opens the chat bar, the message is typed, Enter sends it.
"""
import re
import time
from difflib import SequenceMatcher

import numpy as np

import webstate
from game import INPUT, KEYBDINPUT, _send
from ocr import read_rows

CHAT_BOX = (0.0, 0.05, 0.24, 0.38)  # fractions of the window: x0, y0, x1, y1
SC_SLASH, SC_ENTER = 0x35, 0x1C
KEEP = 500  # lines kept in chat.json


def _key(sc):
    for up in (0, 0x0002):
        inp = INPUT(type=1)
        inp.ki = KEYBDINPUT(0, sc, 0x0008 | up, 0, 0)
        _send(inp)
        time.sleep(0.03)


def _type(text):
    for ch in text:
        for up in (0, 0x0002):
            inp = INPUT(type=1)
            inp.ki = KEYBDINPUT(0, ord(ch), 0x0004 | up, 0, 0)  # KEYEVENTF_UNICODE
            _send(inp)
        time.sleep(0.02)


def _split(line):
    """'[Supporter] TonySeeU: lmaooo' -> ('TonySeeU', 'lmaooo')."""
    m = re.match(r"^(?:\[[^\]]*\]\s*)*([^:\s][^:]{0,30}):\s*(.*)$", line)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", line.strip()


# Plain text only: a row with odd characters in it (accents, boxes, stray symbols) is
# OCR trying to read something that isn't clean text, so it isn't trusted
_CLEAN = re.compile(r"^[A-Za-z0-9 .,!?'\"&:;()\-*/+@#$%_<>=~\[\]|]+$")
# The game's own rotating announcements (they repeat all the time and aren't chat)
_ANNOUNCEMENT = ("favorite", "favourite", "submit", "leaderboard", "booth", "new updates", "enjoying the game",
                 "pulled the", "ultra]", "secret]", "in 100,000")  # (the last ones: rare-pull broadcasts)


_HINT = re.compile(r"\s*To chat\s*click here.*$", re.I)


def _is_announcement(row):
    low = row.lower()
    return row.startswith("*") or any(k in low for k in _ANNOUNCEMENT)


def _mask(img, thr=185):
    """Black text on white, keeping only the bright (white / light) pixels: drops most of
    the scenery behind the chat, which is what confuses the reader."""
    b, g, r = (img[:, :, i].astype(int) for i in range(3))
    keep = ((b + g + r) // 3 >= thr) | ((np.maximum(np.maximum(b, g), r) - np.minimum(np.minimum(b, g), r) > 90)
                                        & (np.maximum(np.maximum(b, g), r) > 200))
    out = np.full(img.shape, 255, np.uint8)
    out[keep] = 0
    return out


def _parse(rows):
    """Rows of text (top to bottom) -> [(who, text)] for the clean player messages.
    A clean row without a name right after a message is its wrapped second line."""
    out, last = [], None
    for row in rows:
        row = _HINT.sub("", row).strip()  # Roblox's "To chat click here or press / key" hint can share the row
        if len(row) < 2 or _is_announcement(row):
            last = None
            continue
        who, text = _split(row)
        # the message itself has to be clean; a garbled name is allowed here (it's matched
        # against the names already seen, or dropped, when the message is stored)
        if not text or not _CLEAN.match(text):
            last = None
            continue
        if who:
            out.append([who, text])
            last = out[-1]
        elif last is not None:
            last[1] = f"{last[1]} {text}".strip()
    return [(w, t) for w, t in out if t]


def _messages(box, deep=True):
    """The player messages in the chat box picture. One normal read; only if some row
    didn't read cleanly (and `deep`: the extra reads take a few tenths of a second), two
    more with the scenery filtered out, and the results pooled."""
    rows = read_rows(box, scale=2)
    found = _parse(rows)
    if deep and any(len(r.strip()) > 1 and not _CLEAN.match(r.strip()) and not _is_announcement(r) for r in rows):
        for variant, scale in ((_mask(box), 2), (_mask(box), 3)):
            for who, text in _parse(read_rows(variant, scale=scale)):
                for i, (w2, t2) in enumerate(found):
                    if SequenceMatcher(None, f"{w2}: {t2}".lower(), f"{who}: {text}".lower()).ratio() > 0.6:
                        if len(text) > len(t2):
                            found[i] = (who, text)  # same line, read more fully this time
                        break
                else:
                    found.append((who, text))
    return found


def _snap_name(who, roster):
    """A name read slightly wrong ("üpril friC;ue") becomes the known name it's closest
    to. A clean name nobody has used before is kept as it is; a garbled unknown one
    gives None (not trusted)."""
    roster = {n for n in roster if _NAME.match(n)}
    if who in roster:
        return who
    clean = bool(_NAME.match(who))
    if roster:
        best = max(roster, key=lambda n: SequenceMatcher(None, who.lower(), n.lower()).ratio())
        if SequenceMatcher(None, who.lower(), best.lower()).ratio() >= (0.72 if clean else 0.6):
            return best
    return who if clean else None


# A player name: letters, digits, spaces, dots, dashes, underscores (no brackets or odd symbols)
_NAME_CHARS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,24}$")


class _NameMatcher:
    def match(self, who):
        # a real name has at most one dot and two underscores; more is OCR noise
        return bool(_NAME_CHARS.match(who)) and who.count(".") <= 1 and who.count("_") <= 2 and ".." not in who


_NAME = _NameMatcher()


def _junky(text):
    """True if the text looks like OCR garbage rather than something a person typed:
    words mixing letters and digits, capitals in the middle of a word, stray punctuation
    inside words, or mostly not letters."""
    words = text.split()
    if not words:
        return True
    bad = 0
    for w in words:
        core = w.strip(".,!?'\"()*:;-")
        if len(core) < 3:
            continue
        if re.search(r"\d", core) and re.search(r"[A-Za-z]", core) and not re.fullmatch(r"\d+[A-Za-z]{1,2}|[A-Za-z]{1,2}\d+", core):
            bad += 1
        elif re.search(r"[a-z][A-Z]", core) and not core.isupper():
            bad += 1
        elif re.search(r"[A-Za-z][^\w'](?=[A-Za-z])", core):
            bad += 1  # punctuation in the middle of a word ("c.ybersecurity")
    letters = sum(c.isalpha() for c in text)
    return bad > 0 or letters < 2 or (len(text) >= 6 and letters / len(text) < 0.55)


class Chat:
    def __init__(self, game, every=1.0):
        self.game = game
        self.every = every
        self.last_read = 0.0
        self.last_deep = 0.0
        self.seen = []  # messages read once, waiting for a second matching read
        self.sent = []  # texts we sent recently, to mark our own messages

    def due(self):
        return time.time() - self.last_read > self.every

    def read(self, img):
        """OCR the chat box and store the messages not stored yet.

        Only lines that read cleanly are kept: a line half-hidden behind a sprite or
        the scenery is skipped and picked up on a later look (every message stays on
        screen for a while, and the picture behind it keeps moving)."""
        self.last_read = time.time()
        h, w = img.shape[:2]
        box = img[int(CHAT_BOX[1] * h):int(CHAT_BOX[3] * h), int(CHAT_BOX[0] * w):int(CHAT_BOX[2] * w)]
        deep = time.time() - self.last_deep > 4.0
        if deep:
            self.last_deep = time.time()
        entries = _messages(box, deep)
        now = time.time()
        self.seen = [c for c in self.seen if now - c["t"] < 30]  # candidates not confirmed in 30s are dropped
        if not entries:
            return
        at = time.strftime("%H:%M:%S")
        same = lambda a, b: SequenceMatcher(None, a, b).ratio() > 0.72

        def add(stored):
            # What's on screen is the last several messages, so compare with the last
            # stored ones (loosely: OCR reads the same line a little differently each time)
            roster = {e["who"] for e in stored[-200:] if e.get("who") and e["who"] != "You"}
            recent = [f"{e['who']}: {e['text']}" for e in stored[-60:]]
            for who, text in entries:
                who = _snap_name(who, roster)
                if not who or _junky(text) or len(text) < 2:
                    continue
                longer = next((e for e in reversed(stored[-15:]) if e["who"] == who and len(text) > len(e["text"])
                               and text.lower().startswith(e["text"].lower()[:max(5, len(e["text"]) - 2)])), None)
                if longer:  # the same message, read more completely this time (e.g. its wrapped second line)
                    longer["text"] = text
                    continue
                if any(same(f"{who}: {text}", r) for r in recent):
                    continue
                # A message is only stored once it has been read twice, about the same
                # (garbage reads rarely agree with each other, real messages do)
                cand = next((c for c in self.seen if same(c["who"], who)
                             and SequenceMatcher(None, c["texts"][0].lower(), text.lower()).ratio() > 0.75), None)
                if cand is None:
                    self.seen.append({"who": who, "texts": [text], "t": now})
                    continue
                cand["texts"].append(text)
                texts = cand["texts"]
                def agree(i):
                    return sum(SequenceMatcher(None, texts[i].lower(), o.lower()).ratio()
                               for j, o in enumerate(texts) if j != i) / (len(texts) - 1)
                top = max(range(len(texts)), key=lambda i: (agree(i), len(texts[i])))
                best = texts[top]
                if agree(top) < 0.85:
                    continue  # the reads disagree too much: wait for a better one
                self.seen.remove(cand)
                text = best
                # A message sent from the website is already listed (it was added the
                # moment it was typed); the screen showing it just fills in the name
                echo = next((e for e in reversed(stored[-15:]) if e.get("pending_echo") and text
                             and e["text"].lower() in text.lower()), None)
                if echo:
                    echo["who"] = who or echo["who"]
                    echo.pop("pending_echo")
                    recent.append(f"{echo['who']}: {echo['text']}")
                    continue
                mine = any(text and s.lower() in text.lower() for s in self.sent)
                stored.append({"at": at, "who": who, "text": text, "mine": mine})
                recent.append(f"{who}: {text}")
            return stored[-KEEP:]
        webstate.update("chat.json", [], add)

    def pending(self):
        return bool(webstate.load("outbox.json", []))

    def send_pending(self, log=print):
        """Type out every message waiting in the outbox."""
        outbox = webstate.load("outbox.json", [])
        for msg in outbox:
            self.game.focus()
            _key(SC_SLASH)
            time.sleep(0.3)
            _type(msg["text"])
            time.sleep(0.1)
            _key(SC_ENTER)
            time.sleep(0.4)
            self.sent = (self.sent + [msg["text"]])[-20:]
            log(f"Sent chat: {msg['text']}")
            sent_ids = {msg["id"]}
            webstate.update("outbox.json", [], lambda o: [m for m in o if m["id"] not in sent_ids])
            # show it on the website right away; the next read of the screen fills in the name
            entry = {"at": time.strftime("%H:%M:%S"), "who": "You", "text": msg["text"],
                     "mine": True, "pending_echo": True}
            webstate.update("chat.json", [], lambda c, e=entry: (c + [e])[-KEEP:])
