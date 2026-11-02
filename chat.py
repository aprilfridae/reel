"""Game chat: read it from the game's memory, and send messages typed on the website.

Reading: Roblox's chat window (CoreGui > ExperienceChat) keeps its recent messages as frames named
"<sender's user id>-{<message id>}", each with a PrefixText label (the sender: "[#8][#1] CASH5550:") and a BodyText
label (the prefix again, then the message). A label's text without its rich-text tags is a string inside it
(CONTENT_TEXT). The game's own lines (rare-pull broadcasts, "Enjoying the game?") come from user id 0 and are left out.
Every message is read whole and exactly, so it's stored the first time it's seen, by its id.
Sending: "/" opens the chat bar, the message is typed, Enter sends it.
"""
import re
import time

import webstate
from game import INPUT, KEYBDINPUT, _send

SC_SLASH, SC_ENTER = 0x35, 0x1C
KEEP = 500  # lines kept in chat.json
CONTENT_TEXT = 0xE08  # a TextLabel's displayed text (rich-text tags stripped), an inline std::string
_MSG = re.compile(r"^(\d+)-\{([0-9A-Fa-f-]{36})\}$")


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


# Accounts whose lines are never stored: the bot's own (the website already has those messages) and a friend's who
# runs this bot too. More can be added with "chat_ignore_names" in config.json.
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
    """Is this name the bot's own account (any name in the list, or one with a word of 4+ letters of one in it)?"""
    low = re.sub(r"[^a-z0-9 _]", "", (who or "").lower()).strip()
    if not low:
        return False
    for name in names or _self_names():
        n = name.lower()
        if low == n or any(len(p) >= 4 and p in low for p in n.split()):
            return True
    return False


# ---- the chat window in memory ----
def _mb():
    import mem_gui
    g = mem_gui.gui()
    return (g.mb, g) if g else (None, None)


def _app():
    """ExperienceChat's appLayout frame, or None."""
    mb, _ = _mb()
    if mb is None:
        return None
    core = next((s for s in mb._children(mb.data_model) if mb._class_name(s) == "CoreGui"), None)
    ec = core and next((c for c in mb._children(core) if mb._name(c) == "ExperienceChat"), None)
    return ec and mb._find_child(ec, name="appLayout")


def _text(mb, label):
    return (mb.r.read_str(label + CONTENT_TEXT) or "").strip() if label else ""


def _sender(prefix):
    """'[#8][#10] CASH5550:' -> 'CASH5550' (the tags in front: badges, [Team], [To ...])."""
    return re.sub(r"^(?:\[[^\]]*\]\s*)+", "", prefix).rstrip(":").strip()


def messages():
    """[(message id, user id, sender, text)] of the messages in the chat window, oldest first. None if memory
    can't be read."""
    mb, gui = _mb()
    app = _app()
    if app is None:
        return None
    view = None
    for d, o in mb._walk(app, depth=8, max_nodes=400):
        if mb._name(o) == "scrollView" and mb._class_name(o) == "ScrollingFrame":
            view = o
            break
    if view is None:
        return None
    out = []
    for fr in mb._children(view):
        m = _MSG.match(mb._name(fr) or "")
        if not m or m.group(1) == "0":
            continue
        tm = mb._find_child(fr, name="TextMessage")
        prefix = _text(mb, tm and mb._find_child(tm, name="PrefixText"))
        body = _text(mb, tm and mb._find_child(tm, name="BodyText"))
        if not prefix or not body.startswith(prefix):
            continue
        text = body[len(prefix):].strip()
        g = gui.geom(fr)
        if text:
            out.append((g[1] if g else 0, m.group(2).upper(), m.group(1), _sender(prefix), text))
    out.sort(key=lambda o: o[0])
    return [o[1:] for o in out]


def chat_enabled(game=None, img=None):
    """Is chat switched on (the speech-bubble button)? Its input row is showing exactly while it is. None if
    memory can't tell."""
    app = _app()
    if app is None:
        return None
    mb, gui = _mb()
    row = mb._find_child(app, name="chatInputRow")
    return bool(row and gui.is_shown(row))


def window_open(game=None, img=None):
    """Is Roblox's chat window showing (its Here / Global / Friends tabs)? It pops up when something is typed or
    said and fades after a while."""
    app = _app()
    if app is None:
        return False
    mb, gui = _mb()
    bar = mb._find_child(app, name="channelBar")
    return bool(bar and gui.is_shown(bar))


def _chat_button():
    """The speech-bubble button's centre (CoreGui > TopBarApp), or None."""
    mb, gui = _mb()
    if mb is None:
        return None
    core = next((s for s in mb._children(mb.data_model) if mb._class_name(s) == "CoreGui"), None)
    top = core and next((c for c in mb._children(core) if mb._name(c) == "TopBarApp"), None)
    if not top:
        return None
    for d, o in mb._walk(top, depth=30, max_nodes=8000):
        if mb._name(o) == "IntegrationIcon" and (mb._content_text(o) or "").startswith("speech-bubble"):
            g = gui.geom(o)
            return (g[0], g[1]) if g else None
    return None


_hidden_by_us = False


def _toggle(game):
    at = _chat_button()
    if not at:
        return False
    game.click(*at)
    game.park_mouse()
    game.wait(0.8)
    return True


def hide_window(game):
    """Switch chat off while something else needs the top-left of the screen (the open chat covers part of the Card
    Market). restore_window switches it back on."""
    global _hidden_by_us
    for _ in range(2):
        if not chat_enabled():  # (looked at each time: chat can come back on while the market is open)
            break
        if not _toggle(game):
            break
        if chat_enabled() is False:
            _hidden_by_us = True
    return _hidden_by_us


def restore_window(game):
    """Switch chat back on if hide_window switched it off."""
    global _hidden_by_us
    if not _hidden_by_us:
        return False
    if chat_enabled() is False:
        _toggle(game)
    _hidden_by_us = False
    return True


class Chat:
    def __init__(self, game, every=3.0):
        self.game = game
        self.every = every
        self.last_read = 0.0
        self.sent = []  # texts we sent recently, to learn the bot's own name
        self._on_checked = 0.0

    def due(self):
        return time.time() - self.last_read > self.every

    def _ensure_on(self):
        """Chat has to be switched on for messages to arrive in its window. It can be left off (a restart in the
        middle of a market trip forgets to switch it back), so it's switched on again: looked at every 20 s."""
        if _hidden_by_us or time.time() - self._on_checked < 20:
            return
        self._on_checked = time.time()
        try:
            if chat_enabled() is False and _toggle(self.game):
                print("Chat was switched off: switched it back on", flush=True)
        except Exception:
            pass

    def read(self, img=None):
        """Store the chat window's messages not stored yet."""
        self.last_read = time.time()
        self._ensure_on()
        try:
            msgs = messages()
        except Exception:
            msgs = None
        if not msgs:
            return
        at = time.strftime("%H:%M:%S")
        selves = _self_names()
        learned = []

        def add(stored):
            ids = {e.get("id") for e in stored if e.get("id")}
            recent = {(e.get("who"), e.get("text")) for e in stored[-60:] if not e.get("id")}  # (read off the screen before)
            for mid, uid, who, text in msgs:
                if mid in ids:
                    continue
                ids.add(mid)
                if is_self(who, selves):
                    continue  # the bot's own: on the website from the moment it was typed there
                if any(s.strip() == text for s in self.sent):
                    if who not in learned:
                        learned.append(who)  # one of ours under a name not known yet
                    continue
                if (who, text) in recent:
                    continue
                stored.append({"at": at, "who": who, "text": text, "mine": False, "id": mid, "uid": uid})
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
