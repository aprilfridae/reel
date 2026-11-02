"""Glue between the bot, the game's Trade window and the website (trade.json / trade_cmd.json).

The bot never completes a trade by itself. When a trade window is open it puts both card lists in serial
order, reads the first cards of each (plus which of mine the other player wants) for the website, and keeps both
offers there up to date (all read in memory; the website draws the cards from their artwork); every action
(accept/decline a request, send one, add / take out / ask for a card, coins, READY, Cancel, search, rescan) only
happens when the website asks for it.
"""
import json
import time

import chat
import trade
import webstate

OFFERS_EVERY = 1.0  # seconds between looks at the two offers while a trade window is open
POLL_EVERY = 1.5  # seconds between looks for a window / request popup while fishing
LIST_LIMIT = 40  # cards read from each list (the website shows the 20 lowest serials)
WANTS_EVERY = 3.0  # seconds between looks at "they want N of your cards" while a trade window is open


class TradeFlow:
    def __init__(self, game, log=print):
        self.game, self.log = game, log
        self.open = None  # the other player's name while the trade window is up
        self.popup = None  # a pending request popup
        self.checked = 0.0
        self.offers_at = 0.0
        self.window_seen_at = None  # when the current window was first seen (for the one-off sort + read)
        self.cmds_at = 0.0
        self.cmds_waiting = False
        self.wanted_n, self.wants_seen, self.wants_at = 0, (0, 0), 0.0  # how many of my cards they want
        # whatever trade.json says is from before this start (a trade open when the bot stopped or updated):
        # nothing is open until it's seen again, or the website would show that trade for good
        self._closed_state()

    def _closed_state(self):
        self._save(open=None, incoming=None, mine=[], theirs=[], wanted=[], wanted_count=0, search=None, offer=None)

    def _window_closed(self):
        self.window_seen_at = None
        self.wanted_n, self.wants_seen = 0, (0, 0)
        self._offer_sig = None
        self._closed_state()
        self.log("Trade window closed")
        chat.restore_window(self.game)

    # ---------- noticing ----------

    def poll(self, img=None):
        """Cheap look (called while fishing, at most every POLL_EVERY seconds).
        True when the bot should stop and handle() something."""
        now = time.time()
        if now - self.checked < POLL_EVERY:
            return False
        self.checked = now
        name = trade.window_open()
        popup = None if name else trade.incoming()
        changed = name != self.open or bool(popup) != bool(self.popup)
        self.open, self.popup = name, popup
        if not name and self.window_seen_at is not None:
            self._window_closed()  # (closed while fishing: the next window must be read afresh)
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
        """What each side has put in the trade (saved for the website only when it changed)."""
        self.offers_at = time.time()
        offer = {"mine": trade.read_offer(self.game, None, "mine"), "theirs": trade.read_offer(self.game, None, "theirs")}
        sig = json.dumps(offer, sort_keys=True)
        if not force and sig == getattr(self, "_offer_sig", None):
            if time.time() - getattr(self, "_offer_saved", 0) > 30:  # (the website takes an unsaved window as gone)
                self._offer_saved = time.time()
                self._save()
            return
        self._offer_sig, self._offer_saved = sig, time.time()
        self._save(offer={**offer, "at": time.strftime("%H:%M:%S")})

    def snapshot(self):
        """(Kept for the commands that ended with a new picture: the offers are read again instead.)"""
        self.read_offers()

    # ---------- reading ----------

    def scan(self, query=None):
        """Both lists (and what they want of mine) -> trade.json."""
        g = self.game
        trade.ensure_serial(g, self.log)
        trade.show_tab(g, "mine")
        wanted_n = trade.read_wanted_header()
        mine = trade.read_cards(g, min(LIST_LIMIT, 20 + wanted_n), self.log)
        trade.show_tab(g, "theirs")
        theirs = trade.read_cards(g, 20, self.log)
        trade.show_tab(g, "mine")
        self._save(open=self.open, mine=mine, theirs=theirs, wanted_count=wanted_n,
                   wanted=[c for c in mine if c.get("wanted")], scanned_at=time.strftime("%H:%M:%S"), sort="serial")
        self.wanted_n, self.wants_seen = wanted_n, (wanted_n, 0)
        self.log(f"Trade window: read {len(mine)} of my cards ({wanted_n} wanted) and {len(theirs)} of theirs")

    def check_wants(self):
        """The other player can ask for more of my cards (or take requests back) at any time: "Your cards" says
        how many they want, so that line is watched, and my cards are read again when it changes (the cards
        they want are listed first, so the order changes too). A new number must read the same twice."""
        if time.time() - self.wants_at < WANTS_EVERY:
            return
        self.wants_at = time.time()
        n = trade.read_wanted_header()
        if n == self.wanted_n:
            self.wants_seen = (n, 0)
            return
        self.wants_seen = (n, self.wants_seen[1] + 1 if self.wants_seen[0] == n else 1)
        if self.wants_seen[1] < 2:
            return
        self.log(f"Trade: {self.open} now wants {n} of my cards")
        trade.show_tab(self.game, "mine")
        mine = trade.read_cards(self.game, min(LIST_LIMIT, 20 + n), self.log)
        self.wanted_n = n
        self._save(mine=mine, wanted_count=n, wanted=[c for c in mine if c.get("wanted")],
                   scanned_at=time.strftime("%H:%M:%S"))

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
        g.alive()
        name = trade.window_open()
        popup = None if name else trade.incoming()
        if name != self.open or bool(popup) != bool(self.popup):
            self._save(open=name, incoming=popup and {"name": popup["name"], "at": time.strftime("%H:%M:%S")})
        self.open, self.popup = name, popup
        if name and self.window_seen_at is None:
            self.window_seen_at = time.time()
            self.log(f"Trade window with {name}")
            chat.hide_window(g)  # the chat is drawn over the window's left side (its tabs and first cards)
            try:
                self.scan()
            except Exception as e:  # reading is a convenience: the window stays usable
                self.log(f"(couldn't read the trade window: {type(e).__name__}: {e})")
        elif not name and self.window_seen_at is not None:
            self._window_closed()
        if name and time.time() - self.offers_at > OFFERS_EVERY:
            try:
                self.read_offers()
            except Exception as e:
                self.log(f"(couldn't read the offers: {type(e).__name__}: {e})")
        if name and self.window_seen_at is not None:
            try:
                self.check_wants()
            except Exception as e:
                self.log(f"(couldn't read what they want: {type(e).__name__}: {e})")
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
        if cmd in ("add", "remove"):
            card = {k: str(a.get(k, ""))[:40] for k in ("name", "serial", "rarity", "rank", "copy", "query")}
            ok, msg = (trade.add_card if cmd == "add" else trade.remove_card)(g, card, self.log)
            self.read_offers(force=True)
            self.snapshot()
            return ok, msg
        if cmd == "want":  # ask for one of their cards
            card = {k: str(a.get(k, ""))[:40] for k in ("name", "serial", "rarity", "rank", "copy", "query")}
            ok, msg, now = trade.request_card(g, card, self.log)
            if now is not None:  # mark it on the website's list (and in a search's results) as asked for or not
                def mark(t):
                    for lst in (t.get("theirs") or [], (t.get("search") or {}).get("cards") or []):
                        for c in lst:
                            if trade._same_card(c, card):
                                c["wanted"] = now
                    return t
                webstate.update("trade.json", {}, mark)
            self.snapshot()
            return ok, msg
        if cmd == "coins":
            ok, msg = trade.set_coins(g, str(a.get("amount", ""))[:20], self.log)
            self.read_offers(force=True)
            self.snapshot()
            return ok, msg
        if cmd in ("ready", "cancel"):
            ok = trade.press(g, cmd)
            self.snapshot()
            return ok, cmd
        return False, "unknown command"
