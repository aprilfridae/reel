"""Game chat: read it off the screen, and send messages typed on the website.

Reading: the chat box sits at the top left. Its lines are OCR'd every few seconds
and only the new ones (past what was already there) are added to web/data/chat.json.
Sending: "/" opens the chat bar, the message is typed, Enter sends it.
"""
import re
import time
from difflib import SequenceMatcher

import cv2
import numpy as np

import webstate
from game import INPUT, KEYBDINPUT, _send
from ocr import read_rows, read_words

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
                 "pulled the", "ultra]", "secret]", "in 100,000",  # (rare-pull broadcasts)
                 "joined the experience", "left the experience", "your friend")  # (Roblox's join / leave notices)


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


# Accounts whose lines are never read back off the screen: the bot's own (the website already has those messages)
# and a friend's who runs this bot too. More can be added with "chat_ignore_names" in config.json.
SELF_NAMES = ["april fridae", "cable"]
SELF_FILE = "chat_self.json"  # names learned to be the bot's own (its sent messages came back under them)


def _self_names():
    try:
        import config
        extra = [n for n in config.load().get("chat_ignore_names", []) if isinstance(n, str)]
    except Exception:
        extra = []
    return SELF_NAMES + extra + [n for n in webstate.load(SELF_FILE, []) if isinstance(n, str)]


def is_self(who, names=None):
    """Is this (OCR-read, maybe garbled) name the bot's own account? Loosely: any part of the name, or a close
    match ("üpril friC;ue" is still april fridae)."""
    low = re.sub(r"[^a-z0-9 ]", "", (who or "").lower()).strip()
    if not low:
        return False
    for name in names or _self_names():
        n = name.lower()
        parts = [p for p in n.split() if len(p) >= 4]
        if any(p in low or (len(low) >= 4 and low in p) for p in parts):
            return True
        if any(SequenceMatcher(None, w, p).ratio() >= 0.75 for w in low.split() for p in parts):
            return True
        if SequenceMatcher(None, low, n).ratio() >= 0.6:
            return True
    return False


CHAT_ICON = (138, 34)  # the speech-bubble button in the top-left corner, at UI scale 1
_hidden_by_us = False


def window_open(game, img=None):
    """Is Roblox's chat window showing (its Here / Global / Friends tabs)? It pops up when
    something is typed or said and fades after a while."""
    img = game.frame() if img is None else img
    h, w = img.shape[:2]
    words = {t.lower() for t, x, y in read_words(img[:int(h * 0.45), :int(w * 0.3)], scale=2)}
    return "global" in words and "friends" in words


def chat_enabled(game, img=None):
    """Is chat switched on? The speech-bubble button is a solid white bubble when it is and
    an outline when it isn't. While it's on, chat text (even the faded kind) is drawn over
    the top-left and takes clicks that land there."""
    img = game.frame() if img is None else img
    s = game.ui_scale(img)
    cx, cy, r = int(CHAT_ICON[0] * s), int(CHAT_ICON[1] * s), int(14 * s)
    icon = cv2.cvtColor(img[cy - r:cy + r, cx - r:cx + r], cv2.COLOR_BGR2GRAY)
    return float((icon > 200).mean()) > 0.25


def hide_window(game):
    """Close the chat window while something else needs the top-left of the screen (the
    open chat covers part of the Card Market). Clicking the chat button switches chat off
    until it's clicked again (restore_window does that)."""
    global _hidden_by_us
    if not chat_enabled(game):  # (looked at each time, not remembered: chat can come back on while the market is open)
        return False
    s = game.ui_scale(game.frame())
    for _ in range(2):
        game.click(CHAT_ICON[0] * s, CHAT_ICON[1] * s)
        game.park_mouse()
        game.wait(0.8)
        if not chat_enabled(game):
            _hidden_by_us = True
            break
    return _hidden_by_us


def restore_window(game):
    """Switch chat back on if hide_window switched it off."""
    global _hidden_by_us
    if not _hidden_by_us:
        return False
    s = game.ui_scale(game.frame())
    game.click(CHAT_ICON[0] * s, CHAT_ICON[1] * s)
    game.park_mouse()
    game.wait(0.6)
    _hidden_by_us = False
    return True


class Chat:
    def __init__(self, game, every=5.0):  # (a look at the chat every 5 s: a line stays on screen far longer than that)
        self.game = game
        self.every = every
        self.last_read = 0.0
        self.last_deep = 0.0
        self.seen = []  # messages read once, waiting for a second matching read
        self.sent = []  # texts we sent recently, to mark our own messages

    def due(self):
        return time.time() - self.last_read > self.every

    _on_checked = 0.0

    def _ensure_on(self, img):
        """Chat has to be switched on for anything to be read. It can be left off (the bot switches it off for the
        Card Market, and a restart in the middle of a market trip forgets to switch it back), so if the chat button
        shows it off, click it on: looked at every 20 s at most."""
        if _hidden_by_us or time.time() - self._on_checked < 20:
            return
        self._on_checked = time.time()
        try:
            if not chat_enabled(self.game, img):
                s = self.game.ui_scale(img)
                self.game.click(CHAT_ICON[0] * s, CHAT_ICON[1] * s)
                self.game.park_mouse()
                print("Chat was switched off: switched it back on", flush=True)
        except Exception:
            pass

    def read(self, img):
        """OCR the chat box and store the messages not stored yet.

        Only lines that read cleanly are kept: a line half-hidden behind a sprite or
        the scenery is skipped and picked up on a later look (every message stays on
        screen for a while, and the picture behind it keeps moving)."""
        self.last_read = time.time()
        self._ensure_on(img)
        h, w = img.shape[:2]
        box = img[int(CHAT_BOX[1] * h):int(CHAT_BOX[3] * h), int(CHAT_BOX[0] * w):int(CHAT_BOX[2] * w)]
        deep = time.time() - self.last_deep > 2.0  # (the filtered extra reads, at most every 2 s: they catch lines the plain read garbles)
        if deep:
            self.last_deep = time.time()
        entries = _messages(box, deep)
        now = time.time()
        self.seen = [c for c in self.seen if now - c["t"] < 30]  # candidates not confirmed in 30s are dropped
        if not entries:
            return
        at = time.strftime("%H:%M:%S")
        same = lambda a, b: SequenceMatcher(None, a, b).ratio() > 0.72

        selves = _self_names()
        learned = []

        def add(stored):
            # What's on screen is the last several messages, so compare with the last
            # stored ones (loosely: OCR reads the same line a little differently each time)
            roster = {e["who"] for e in stored[-200:] if e.get("who") and e["who"] != "You" and not is_self(e["who"], selves)}
            recent = [f"{e['who']}: {e['text']}" for e in stored[-60:]]
            for who, text in entries:
                # the bot's own account: never read back. Its messages are on the website from the moment
                # they were typed there, so a read of them would only show them twice
                if is_self(who, selves):
                    continue
                if any(len(s) >= 4 and SequenceMatcher(None, s.lower(), text.lower()).ratio() > 0.8 for s in self.sent):
                    # one of ours under a name not known yet: remember the name, skip the line
                    if _NAME.match(who) and who not in learned:
                        learned.append(who)
                    continue
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
                stored.append({"at": at, "who": who, "text": text, "mine": False})
                recent.append(f"{who}: {text}")
            return stored[-KEEP:]
        webstate.update("chat.json", [], add)
        if learned:
            webstate.update(SELF_FILE, [], lambda names: (names + [n for n in learned if n not in names])[-10:])

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
            # (it is already on the website: the website adds it to the chat the moment it's typed there)
