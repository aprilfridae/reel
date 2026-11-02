"""The game's "YOU WERE OUTBID!" notice, read from memory: its title label, the lines beside it ("<player> bid 22.2B on
<card> (<rarity>) (you bid 21.1B)", "+21.1B coins back") and the card shown with it (its artwork's picture id, so the
website draws it).

The memory poller (mem_poller.py) looks for it every 2 seconds and saves each notice to outbid.json once; the bot's
Watcher only puts new ones in its log.
"""
import re
import time

import webstate

KEEP = 50  # notices kept for the website
NOTICE = re.compile(r"\bwere\s+outbid\b", re.I)
_AMT = r"([\d.,]+\s*[KMBTQ]?)"
_LINE = re.compile(rf"(\S+)\s+bid\s+{_AMT}\s+on\s+(.+?)\s*\(([^)]*)\)\s*\(?\s*you\s+bid\s+{_AMT}", re.I)


def parse(text):
    """The fields of a notice's text: {"text", "by", "amount", "card", "rarity", "mine"} (those that are there)."""
    out = {"text": text}
    m = _LINE.search(text)
    if m:
        out.update(by=m.group(1), amount=m.group(2).replace(" ", ""), card=m.group(3).strip(),
                   rarity=m.group(4).strip(), mine=m.group(5).replace(" ", ""))
    return out


def read_notice(mb, walk):
    """The showing notice as {text, by, amount, card, rarity, mine, art}, or None. `walk` walks PlayerGui (the poller's
    own, which skips the big lists). The game keeps its menus in memory when they close, and other text says "outbid"
    too (the bid window's "coins are held until you're outbid"), so only the notice's title counts, while showing."""
    import card_art
    import mem_gui
    g = mem_gui.gui()
    if g is None:
        return None
    title = next((i for d, i in walk(mb.player_gui, depth=16)
                  if NOTICE.search(mb._content_text(i) or "") and g.is_shown(i)), None)
    if title is None:
        return None
    box = mb._parent(title)
    parts = [(mb._content_text(c) or "").strip() for c in (mb._children(box) if box else [])]
    text = " / ".join(p for p in parts if p and not NOTICE.search(p)) or (mb._content_text(title) or "").strip()
    out = parse(text)
    for node in (box, mb._parent(box) if box else None):  # the card: beside the text, or one level up
        img = card_art._artwork(mb, node) if node else None
        art = card_art.image_id(mb, img) if img else None
        if art:
            out["art"] = art
            if out.get("card"):
                card_art.record(out["card"], out.get("rarity"), art)
            break
    return out


def save(notice):
    entry = {**notice, "at": time.strftime("%H:%M:%S"), "ts": time.time()}
    if entry.get("card") and not entry.get("name"):
        entry["name"] = entry["card"]  # (what the website's cards are drawn from)
    webstate.update("outbid.json", [], lambda lst: (lst + [entry])[-KEEP:])


class Watcher:
    """Logs the notices the memory poller saved."""

    def __init__(self, log=print):
        self.log = log
        self.checked = 0.0
        self.seen = max((e.get("ts", 0) for e in webstate.load("outbid.json", [])), default=0)

    def poll(self, img=None):
        """True if a new notice came in since the last look (looked at every second at most)."""
        now = time.time()
        if now - self.checked < 1.0:
            return False
        self.checked = now
        new = [e for e in webstate.load("outbid.json", []) if e.get("ts", 0) > self.seen]
        for n in new:
            self.seen = max(self.seen, n.get("ts", 0))
            if n.get("by"):
                self.log(f"Outbid! {n['by']} bid {n['amount']} on {n['card']} ({n['rarity']}), you bid {n['mine']}")
            else:
                self.log(f"Outbid! {n.get('text', '')}")
        return bool(new)
