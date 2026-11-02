"""Memory info poller: constantly reads all available game state from Roblox memory
and writes it to webstate files so the website is always up to date.

Runs as a background thread alongside the bot. Reads:
- Balance (every 5s)
- Fishing state (every 2s)
- Market cards enrichment (every 60s)
- Event banner (every 10s)
- Outbid / trade notifications (every 5s)
- Card pictures (every 30s, card_art)
"""
import threading
import time
import re
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import webstate
except ImportError:
    # Running standalone — stub webstate
    import json, tempfile
    _data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "data")
    os.makedirs(_data_dir, exist_ok=True)
    class webstate:
        @staticmethod
        def path(name):
            return os.path.join(_data_dir, name)
        @staticmethod
        def load(name, default):
            try:
                with open(webstate.path(name), encoding="utf-8-sig") as f:
                    return json.load(f)
            except (OSError, ValueError):
                return default
        @staticmethod
        def save(name, data):
            tmp = webstate.path(name) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, webstate.path(name))
        @staticmethod
        def update(name, default, fn):
            data = fn(webstate.load(name, default))
            webstate.save(name, data)


NOTICE = re.compile(r"\bwere\s+outbid\b", re.I)  # the notice's title, "YOU WERE OUTBID!"


class MemoryPoller:
    """Background thread that reads game state from Roblox memory and pushes to webstate."""

    def __init__(self, reader, interval_balance=5, interval_fish=2, interval_event=10,
                 interval_market=60, interval_outbid=2, interval_art=30, log=print):
        self.r = reader
        self.log = log
        self.intervals = {
            "balance": interval_balance,
            "fish": interval_fish,
            "event": interval_event,
            "market": interval_market,
            "outbid": interval_outbid,
            "art": interval_art,
        }
        self.last_run = {k: 0.0 for k in self.intervals}
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="memory-poller")
        self._thread.start()
        self.log("[mem-poller] started")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            now = time.time()
            for task, interval in self.intervals.items():
                if now - self.last_run[task] >= interval:
                    self.last_run[task] = now
                    try:
                        getattr(self, f"_poll_{task}")()
                    except Exception as e:
                        # Don't let one failure kill the poller
                        if self.log:
                            self.log(f"[mem-poller] {task} error: {e}")
            self._stop.wait(1.0)  # check every second

    # ---- helpers ----
    def _walk(self, inst, depth=20, max_nodes=40000):
        count = 0
        stack = [(0, inst)]
        while stack and count < max_nodes:
            d, i = stack.pop()
            yield d, i
            count += 1
            if d < depth:
                for c in reversed(self.r._children(i)):
                    stack.append((d + 1, c))

    def _find_child(self, inst, name=None, cls=None):
        for c in self.r._children(inst):
            if name is not None and self.r._name(c) != name:
                continue
            if cls is not None and self.r._class_name(c) != cls:
                continue
            return c
        return None

    def _find_screen_gui(self, pg, name):
        for c in self.r._children(pg):
            if self.r._name(c) == name and self.r._class_name(c) == "ScreenGui":
                return c
        return None

    # ---- polls ----
    def _poll_balance(self):
        """Read balance from the 💰 label and update balance.json."""
        bal = self.r.get_balance() if hasattr(self.r, 'get_balance') else self._read_balance()
        if bal:
            webstate.update("balance.json", {}, lambda d: {
                **d, "value": bal, "at": time.strftime("%H:%M:%S")})

    def _read_balance(self):
        """Fallback balance reading if r doesn't have get_balance."""
        pg = getattr(self.r, 'player_gui', None)
        if not pg:
            return None
        money_re = re.compile(r"^[\d.,]+[KMBT]?$")
        for d, i in self._walk(pg, depth=12):
            cls = self.r._class_name(i)
            if cls in ("TextLabel", "TextButton"):
                txt = self.r._content_text(i)
                if txt and money_re.match(txt.strip()):
                    node = i
                    for _ in range(8):
                        par = self.r._parent(node)
                        if not par:
                            break
                        for sib in self.r._children(par):
                            if sib != i:
                                st = self.r._content_text(sib)
                                if st and st.strip() == "💰":
                                    return txt.strip()
                        node = par
        return None

    def _poll_fish(self):
        """Read fishing state and update fishing.json for the website."""
        state = self.r.fish_state() if hasattr(self.r, 'fish_state') else self._read_fish_state()
        if state:
            # (its own file: fishing.json holds the website's fishing settings)
            webstate.save("mem_fishing.json", {"state": state, "at": time.strftime("%H:%M:%S")})

    def _read_fish_state(self):
        pg = getattr(self.r, 'player_gui', None)
        if not pg:
            return None
        fg = self._find_screen_gui(pg, "FishingUI")
        if not fg:
            return None
        for d, i in self._walk(fg, depth=10):
            txt = self.r._content_text(i)
            if not txt:
                continue
            tl = txt.lower()
            if "bite" in tl and "reel" in tl:
                return "biting"
            if "caught" in tl:
                return "caught"
            if "waiting" in tl:
                return "waiting"
        return None

    def _poll_event(self):
        """Read the event banner text and update events.json."""
        pg = getattr(self.r, 'player_gui', None)
        if not pg:
            return
        # Event banner is in EventHUD
        eh = self._find_screen_gui(pg, "EventHUD")
        if not eh:
            return
        for d, i in self._walk(eh, depth=8):
            txt = self.r._content_text(i)
            if txt and len(txt.strip()) > 3:
                webstate.update("mem_event.json", {}, lambda d: {
                    **d, "banner": txt.strip(), "at": time.strftime("%H:%M:%S")})
                break

    def _poll_art(self):
        """Record the pictures of the cards in the game's menus (card_art), downloading new ones."""
        import card_art
        if not getattr(self, "_art_started", False):
            self._art_started = True
            card_art.fetch_missing()  # (pictures recorded before a restart but not downloaded yet)
        n = card_art.harvest(self.r)
        if n:
            self.log(f"[mem-poller] {n} new card picture(s)")

    def _poll_market(self):
        """Enrich market data with memory-read card info."""
        try:
            from mem_market_scan import scan_market
            mem_cards = scan_market(self.r)
            if mem_cards:
                # Merge with existing market data
                def merge(market):
                    cards = market.get("cards", [])
                    for card in cards:
                        for mc in mem_cards:
                            if str(card.get("serial")) == str(mc.get("serial")):
                                for field in ("pack", "earnings", "grade", "name"):
                                    if mc.get(field) and not card.get(field):
                                        card[field] = mc[field]
                                break
                    return market
                webstate.update("market.json", {"cards": []}, merge)
        except ImportError:
            pass

    def _poll_outbid(self):
        """Check for the 'YOU WERE OUTBID!' notice in PlayerGui. Saved once when it shows up, not again while it
        stays up. The game keeps its menus in memory when they close, and other text says "outbid" too (the bid
        window's "coins are held until you're outbid"), so only the notice's title counts, and only while showing."""
        import outbid
        if not getattr(self.r, 'player_gui', None):
            return
        notice = outbid.read_notice(self.r, self._walk)
        if notice is None:
            self._outbid_up = None
            return
        if getattr(self, "_outbid_up", None) == notice["text"]:
            return  # the same notice, still up
        self._outbid_up = notice["text"]
        outbid.save(notice)

    def _poll_trade(self):
        """Check for incoming trade requests."""
        pg = getattr(self.r, 'player_gui', None)
        if not pg:
            return
        # Look for trade-related text
        for d, i in self._walk(pg, depth=16):
            txt = self.r._content_text(i)
            if txt and "wants to trade" in txt.lower():
                entry = {"at": time.strftime("%H:%M:%S"), "text": txt.strip(),
                         "ts": time.time()}
                webstate.update("mem_trade.json", {}, lambda d: {
                    **d, "incoming": entry})
                return
        # No active trade request
        webstate.update("mem_trade.json", {}, lambda d: {
            **d, "incoming": None})


# Convenience: attach to bot.py's Game
def attach_memory_poller(game, log=print):
    """Create and start a MemoryPoller alongside the bot's Game instance."""
    try:
        from memory_backend import get_backend
        mb = get_backend()
        poller = MemoryPoller(mb, log=log)
        poller.start()
        return poller, mb
    except Exception as e:
        log(f"[mem-poller] failed to start: {e}")
        return None, None


# Standalone test
if __name__ == "__main__":
    from memory_backend import MemoryBackend
    mb = MemoryBackend()
    mb.start()
    poller = MemoryPoller(mb, log=print)
    poller.start()
    print("Polling for 30 seconds...")
    time.sleep(30)
    poller.stop()
    mb.close()
    print("Done.")
