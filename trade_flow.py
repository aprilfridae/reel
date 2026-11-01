"""Glue between the bot, the game's Trade window and the website (trade.json / trade_cmd.json).

The bot never completes a trade by itself. When a trade window is open it puts both card lists in serial
order, reads the first cards of each (plus which of mine the other player wants) for the website, and keeps a
small live picture there; every action (accept/decline a request, send one, READY, Cancel, search, rescan)
only happens when the website asks for it.
"""
import os
import time
import uuid

import cv2

import trade
import webstate
from paths import APP

SNAPSHOT = os.path.join(APP, "web", "static", "trade.jpg")
SNAP_EVERY = 2.0  # seconds between live pictures while a trade window is open
POLL_EVERY = 1.5  # seconds between looks for a window / request popup while fishing
LIST_LIMIT = 40  # cards read from each list (the website shows the 20 lowest serials)


def _serial_key(c):
    s = c.get("serial")
    if s is None:
        return 10 ** 9
    try:
        return int(s)
    except ValueError:
        return 5 if s == "2-9" else 10 ** 9


class TradeFlow:
    def __init__(self, game, log=print):
        self.game, self.log = game, log
        self.open = None  # the other player's name while the trade window is up
        self.popup = None  # a pending request popup
        self.checked = 0.0
        self.snap_at = 0.0
        self.window_seen_at = None  # when the current window was first seen (for the one-off sort + read)
        self.cmds_at = 0.0
        self.cmds_waiting = False

    # ---------- noticing ----------

    def poll(self, img):
        """Cheap look (called with whole frames while fishing, at most every POLL_EVERY seconds).
        True when the bot should stop and handle() something."""
        now = time.time()
        if now - self.checked < POLL_EVERY:
            return False
        self.checked = now
        name = trade.window_open(self.game, img)
        popup = None if name else trade.incoming(self.game, img)
        changed = name != self.open or bool(popup) != bool(self.popup)
        self.open, self.popup = name, popup
        if changed:  # (a request popup can stay up for ages: it's only recorded, fishing carries on)
            self._save(open=name, incoming=popup and {"name": popup["name"], "at": time.strftime("%H:%M:%S")})
        return bool(name) or self.has_cmds()

    def busy(self):
        """A trade window is open: nothing else may click around (it would cover or close it)."""
        return bool(self.open)

    def has_cmds(self):
        if time.time() - self.cmds_at > 1.0:
            self.cmds_at = time.time()
            self.cmds_waiting = any(c.get("status") == "waiting" for c in webstate.load("trade_cmd.json", []))
        return self.cmds_waiting

    # ---------- state for the website ----------

    def _save(self, **fields):
        webstate.update("trade.json", {}, lambda t: {**t, **fields, "ts": time.time()})

    def _finish(self, cid, ok, result=""):
        def fn(cmds):
            for c in cmds:
                if c["id"] == cid:
                    c["status"], c["result"] = ("done" if ok else "failed"), result
            return cmds[-40:]
        webstate.update("trade_cmd.json", [], fn)
        self.cmds_at = 0.0

    def read_offers(self, force=False):
        """What each side has put in the trade (re-read only when that part of the screen changed)."""
        img = self.game.frame()
        s = self.game.ui_scale(img)
        ox, oy = trade._origin(img, s)
        x0, y0, x1, y1 = (int(ox + 1060 * s), int(oy + 170 * s), int(ox + 1725 * s), int(oy + 912 * s))
        sig = cv2.resize(img[y0:y1, x0:x1], (48, 48), interpolation=cv2.INTER_AREA).astype("int16")
        old = getattr(self, "_offer_sig", None)
        if not force and old is not None and abs(sig - old).mean() < 2.5:
            return
        self._offer_sig = sig
        self._save(offer={"mine": trade.read_offer(self.game, img, "mine", scrolling=True),
                          "theirs": trade.read_offer(self.game, self.game.frame(), "theirs", scrolling=True),
                          "at": time.strftime("%H:%M:%S")})

    def snapshot(self):
        img = self.game.frame()
        small = cv2.resize(img, (960, int(img.shape[0] * 960 / img.shape[1])), interpolation=cv2.INTER_AREA)
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        cv2.imwrite(SNAPSHOT, small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        self.snap_at = time.time()
        self._save(snap=int(self.snap_at))

    # ---------- reading ----------

    def scan(self, query=None):
        """Both lists (and what they want of mine) -> trade.json."""
        g = self.game
        trade.ensure_serial(g, self.log)
        trade.show_tab(g, "mine")
        wanted_n = trade.read_wanted_header(g, g.frame())
        mine = trade.read_cards(g, min(LIST_LIMIT, 20 + wanted_n), self.log)
        trade.show_tab(g, "theirs")
        theirs = trade.read_cards(g, 20, self.log)
        trade.show_tab(g, "mine")
        self._save(open=self.open, mine=mine, theirs=theirs, wanted_count=wanted_n,
                   wanted=[c for c in mine if c.get("wanted")], scanned_at=time.strftime("%H:%M:%S"), sort="serial")
        self.log(f"Trade window: read {len(mine)} of my cards ({wanted_n} wanted) and {len(theirs)} of theirs")

    def search(self, tab, query):
        g = self.game
        trade.show_tab(g, "mine" if tab == "mine" else "theirs")
        trade.search_cards(g, query, self.log)
        cards = trade.read_cards(g, 20, self.log)
        trade.search_cards(g, "", self.log)  # clear it again
        self._save(search={"tab": tab, "query": query, "cards": cards, "at": time.strftime("%H:%M:%S")})
        trade.show_tab(g, "mine")
        return f"{len(cards)} card(s)"

    # ---------- doing ----------

    def handle(self):
        """One pass: refresh what's on screen, do the website's commands, keep the picture current."""
        g = self.game
        img = g.frame()
        name = trade.window_open(g, img)
        popup = None if name else trade.incoming(g, img)
        if name != self.open or bool(popup) != bool(self.popup):
            self._save(open=name, incoming=popup and {"name": popup["name"], "at": time.strftime("%H:%M:%S")})
        self.open, self.popup = name, popup
        if name and self.window_seen_at is None:
            self.window_seen_at = time.time()
            self.log(f"Trade window with {name}")
            try:
                self.scan()
            except Exception as e:  # reading is a convenience: the window stays usable
                self.log(f"(couldn't read the trade window: {type(e).__name__}: {e})")
        elif not name and self.window_seen_at is not None:
            self.window_seen_at = None
            self._save(open=None, mine=[], theirs=[], wanted=[], wanted_count=0, search=None, offer=None)
            self._offer_sig = None
            self.log("Trade window closed")
        if name and time.time() - self.snap_at > SNAP_EVERY:
            self.snapshot()
            try:
                self.read_offers()
            except Exception as e:
                self.log(f"(couldn't read the offers: {type(e).__name__}: {e})")
        for c in [c for c in webstate.load("trade_cmd.json", []) if c.get("status") == "waiting"]:
            try:
                ok, msg = self.run(c)
            except Exception as e:
                ok, msg = False, f"{type(e).__name__}: {e}"
            self._finish(c["id"], ok, msg)
        g.wait(0.4)

    def run(self, c):
        g, cmd, a = self.game, c.get("cmd"), c.get("args") or {}
        if cmd in ("accept", "decline"):
            return (trade.respond(g, cmd == "accept", self.log), cmd) if self.popup else (False, "no request on screen")
        if cmd == "send":
            return trade.send_request(g, str(a.get("name", "")).strip()[:40], self.log, str(a.get("alt", ""))[:40])
        if cmd == "players":
            players, total = trade.read_players(g, self.log)
            if players is None:
                return False, total
            self._save(players={"list": players, "total": total, "at": time.strftime("%H:%M:%S"), "ts": time.time()})
            return True, f"{len(players)} players"
        if not self.open:
            return False, "no trade window is open"
        if cmd == "refresh":
            self.scan()
            return True, "read again"
        if cmd == "search":
            return True, self.search(a.get("tab", "theirs"), str(a.get("query", ""))[:30])
        if cmd == "addwanted":
            added = trade.add_wanted(self.game, self.log)
            self.scan()  # the lists changed
            self.read_offers(force=True)
            return bool(added), (f"added {', '.join(added)} to the offer" if added else "no wanted cards found")
        if cmd in ("ready", "cancel"):
            ok = trade.press(g, cmd)
            self.snapshot()
            return ok, cmd
        return False, "unknown command"


def add_cmd(cmd, args=None):
    c = {"id": uuid.uuid4().hex[:8], "cmd": cmd, "args": args or {}, "status": "waiting", "result": "",
         "at": time.strftime("%H:%M:%S")}
    webstate.update("trade_cmd.json", [], lambda cs: (cs + [c])[-40:])
    return c


def sorted_top(cards, n=20):
    return sorted(cards, key=_serial_key)[:n]
