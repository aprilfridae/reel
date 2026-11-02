"""Record your #1s from the Index, for every rarity except the common ones, read from memory.

The Index is a panel in CardsUI ("Index  11552/19394"). Its tabs (All / Rarities / Event / Ultra / Alt Covers /
Supporter), the Rarities and Event sub-tabs ("Iced 261/969", "🔱 Atlantis 404/969"; both rows are in memory even when
hidden, so new event rarities are picked up by themselves) and the sort button ("Sort: Serial") are all labels. The
open tab's grid holds one tile per artist; the tiles near the view have their card filled in: the artist, the serial
badge ("#1" in a frame named FirstTen), the rarity and the artwork (its picture id, see card_art). Sorted by serial,
a tab's #1 cards come first, so it's scrolled only until the first card that isn't a #1.

A #1 is known by its artist and rarity, so each is counted once without comparing pictures; the website draws it
from its artwork (see ones.py).

  python index_check.py      (or called by bot.py after each event)
"""
import json
import os
import re
import time
from datetime import datetime

import card_art
import mem_gui
import mem_market
import ones
from game import HERE, StopBot, Game
from packs import close_any_menu, close_popup

RECORDS_DIR = os.path.join(HERE, "number1s")

# The rarities left out (the author's list). "Uncommon" is NOT on it, so it is tracked.
EXCLUDED = {"common", "rare", "epic", "legendary", "mythic"}
MAIN_TABS = ("Rarities", "Event", "Ultra", "Alt Covers", "Supporter")
SUBTAB_BARS = {"Rarities": "RarityBar", "Event": "EventBar"}
MAX_SCROLLS = 40  # scroll steps per tab at most (a tab's #1s fit in a few)
STOP_RUN = 10  # this many cards in a row that aren't #1s (two rows) = past the #1s


# a card's labels that aren't its fields (a tile scrolled out of view loses its name, so these would pass for it)
_NOISE = re.compile(r"^(Owned\s+x\d+|LOADING$)", re.I)


class IndexReadError(Exception):
    """The Index isn't where memory says it should be (closed, or the game changed it)."""


def _key(name):
    return re.sub(r"[^a-z]+", "_", re.sub(r"^[^A-Za-z]+", "", name or "").strip().lower()).strip("_")


class Index:
    def __init__(self, game):
        self.g = game
        self.gui = mem_gui.gui()
        if self.gui is None:
            raise IndexReadError("memory can't be read")
        self.mb = self.gui.mb

    # ---- finding things ----
    def panel(self):
        """The Index panel: the frame in CardsUI whose title says "Index  <owned>/<all>"."""
        mb = self.mb
        root = next((s for s in mb._children(mb.player_gui) if mb._name(s) == "CardsUI"), None)
        root = root and mb._find_child(root, name="Root")
        for fr in mb._children(root) if root else []:
            for c in mb._children(fr):
                if mb._class_name(c) == "TextLabel" and re.match(r"Index\s+\d+\s*/\s*\d+", mb._content_text(c) or ""):
                    return fr
        return None

    def is_open(self):
        p = self.panel()
        return bool(p and self.gui.is_shown(p))

    def _labels(self, under, depth=4):
        """(text, label) of every TextLabel under `under` (the card grid left out: it's big and looked at apart)."""
        mb, out, stack = self.mb, [], [(0, under)]
        while stack:
            d, node = stack.pop()
            cls = mb._class_name(node)
            if cls == "ScrollingFrame":
                continue
            if cls in ("TextLabel", "TextButton"):
                t = mb._content_text(node)
                if t:
                    out.append((t.strip(), node))
            if d < depth:
                stack.extend((d + 1, c) for c in mb._children(node))
        return out

    def _click(self, label):
        g = self.gui.geom(label)
        if not g:
            raise IndexReadError("a label has no position")
        self.g.click(g[0], g[1])
        self.g.park_mouse()

    def grid(self):
        p = self.panel()
        return p and self.mb._find_child(p, cls="ScrollingFrame")

    # ---- tabs and sorting ----
    def main_tab(self, name):
        hit = next((lab for t, lab in self._labels(self.panel(), depth=3) if t == name and self.gui.is_shown(lab)), None)
        if hit is None:
            raise IndexReadError(f"no {name} tab")
        self._click(hit)

    def subtabs(self, main):
        """[(rarity key, label)] of a Rarities / Event sub-tab row, left to right (read even while hidden)."""
        bar = self.mb._find_child(self.panel(), name=SUBTAB_BARS[main])
        if bar is None:
            raise IndexReadError(f"no {main} sub-tab row")
        out = []
        for t, lab in self._labels(bar, depth=4):
            if re.search(r"[A-Za-z]", t) and not re.search(r"\d", t):  # the name, not its "115/969" count
                g = self.gui.geom(lab)
                out.append((g[0] if g else 0, _key(t), lab))
        return [(k, lab) for _, k, lab in sorted(out, key=lambda o: o[0])]

    def ensure_serial_sort(self):
        p = self.panel()
        sort = next(((t, lab) for t, lab in self._labels(p, depth=3) if t.lower().startswith("sort:")), None)
        if sort is None:
            raise IndexReadError("no sort button")
        if "serial" in sort[0].lower():
            return
        self._click(sort[1])
        self.g.wait(0.6)
        menu = self.mb._find_child(p, name="SortMenu")
        opt = next((lab for t, lab in self._labels(menu, depth=4) if "serial" in t.lower() and self.gui.is_shown(lab)), None)
        if opt is None:
            raise IndexReadError("no Serial in the sort menu")
        self._click(opt)
        self.g.wait(1.0)

    # ---- the card grid ----
    def tiles(self):
        """[(slot, card fields or None, shown)] for every tile in the open tab's grid, in grid order. slot = (row,
        column) from the tile's place relative to the others, so it stays the same however far it's scrolled.
        Card fields (mem_market.parse plus "art") only for tiles whose card is filled in."""
        mb, gui = self.mb, self.gui
        grid = self.grid()
        if grid is None:
            raise IndexReadError("no card grid")
        raw = []
        for tile in mb._children(grid):
            if mb._class_name(tile) != "Frame":
                continue
            g = gui.geom(tile)
            if g and g[2] > 20:
                raw.append((g, tile))
        if not raw:
            return []
        w, h = raw[0][0][2], raw[0][0][3]
        x0, y0 = min(g[0] for g, _ in raw), min(g[1] for g, _ in raw)
        out = []
        for g, tile in raw:
            slot = (round((g[1] - y0) / (h + 4)), round((g[0] - x0) / (w + 4)))
            card = mb._find_child(tile, name="Card")
            fields = None
            if card is not None:
                texts = [t for t in mem_market._texts(mb, card, depth=8) if not _NOISE.search(t[0])
                         and (re.search(r"\w", t[0]) or t[0] == "?" or set(t[0]) <= set("★☆ "))]
                if texts:
                    fields = mem_market.parse(texts)
                    img = card_art._artwork(mb, card)
                    fields["art"] = card_art.image_id(mb, img) if img else None
                    if fields.get("art"):
                        card_art.record(fields.get("name"), fields.get("rarity"), fields["art"])
            out.append((slot, fields, gui.is_shown(tile)))
        out.sort(key=lambda o: o[0])
        return out

    def _settle(self, maxwait=1.5):
        """Wait until the grid's tiles stop moving (a tab switch, a scroll)."""
        def where():
            grid = self.grid()
            first = next((c for c in self.mb._children(grid) if self.mb._class_name(c) == "Frame"), None) if grid else None
            g = self.gui.geom(first) if first else None
            return (round(g[0]), round(g[1])) if g else None
        prev, end = where(), time.time() + maxwait
        while time.time() < end:
            self.g.wait(0.12)
            cur = where()
            if cur == prev:
                return
            prev = cur

    def collect_ones(self, rarity):
        """[{name, rarity, serial, art, income}] of every #1 in the open tab. "Sort: Serial" puts the #1s near the
        top, but not strictly first (favourites and head cards lead, and a #2 can sit among them), so it scrolls from
        the top until STOP_RUN cards in a row (in grid order, every slot read) aren't #1s, or the tab ends."""
        gbox = self.gui.geom(self.grid())
        mid = (gbox[0], gbox[1]) if gbox else None
        if mid:
            self.g.scroll(*mid, 30, check=False)  # to the top
            self._settle()
        seen = {}  # slot -> fields
        for step in range(MAX_SCROLLS):
            tiles = self.tiles()
            if not tiles:
                return []
            for slot, fields, _ in tiles:
                if fields and fields.get("name") and slot not in seen:  # the first read: later ones may be emptied
                    seen[slot] = fields
            order = [slot for slot, _, _ in tiles]
            last = max((i for i, s in enumerate(order) if s in seen), default=-1)
            prefix = [s for s in order[:last + 1] if s in seen]  # (a tile that never gets a card is passed over)
            run = 0
            for slot in reversed(prefix):
                if seen[slot].get("serial") == "1":
                    break
                run += 1
            if run >= STOP_RUN or last == len(order) - 1:
                out = {}
                for s in prefix:
                    f = seen[s]
                    if f.get("serial") == "1" and _key(f["name"]) not in out:
                        out[_key(f["name"])] = {"name": f["name"], "rarity": rarity, "serial": "1",
                                                "art": f.get("art"), "income": f.get("income")}
                return list(out.values())
            if not mid:
                break
            self.g.scroll(*mid, -3, check=False)
            self._settle(1.0)
        raise IndexReadError(f"couldn't get to the end of the #1s in {rarity}")


def snapshot(game, log=print, should_stop=lambda: False):
    """Open the Index and go through every tab except the excluded rarities, saving each #1 card to the website's
    collection. Stops early (between tabs) if should_stop() says so, e.g. a bid/buy is waiting.
    Returns ({rarity: #1 cards}, finished)."""
    g = game
    finished = True
    close_popup(g)
    close_any_menu(g)
    try:
        ix = Index(g)
    except IndexReadError as e:
        log(f"Index check: {e}.")
        return {}, False
    hit = mem_gui.locate(text="Index", screen="CardsUI")
    if not hit:
        log("Index check: couldn't find the Index button.")
        return {}, False
    g.click(hit[0], hit[1])
    g.park_mouse()
    end = time.time() + 3
    while not ix.is_open() and time.time() < end:
        g.wait(0.1)
    if not ix.is_open():
        log("Index check: the Index didn't open.")
        return {}, False

    os.makedirs(RECORDS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M")
    counts, skipped = {}, []
    try:
        ix.ensure_serial_sort()
        for main in MAIN_TABS:
            if should_stop():
                finished = False
                break
            ix.main_tab(main)
            ix._settle(1.2)
            if main in SUBTAB_BARS:
                tabs = ix.subtabs(main)
                todo = [(k, lab) for k, lab in tabs if k not in EXCLUDED]
                skipped += [k for k, _ in tabs if k in EXCLUDED]
            else:
                todo = [(_key(main), None)]
            for rarity, lab in todo:
                if should_stop():
                    finished = False
                    break
                if lab is not None:
                    ix._click(lab)
                    ix._settle(1.2)
                    g.wait(0.3)  # (the tiles are filled in a moment after the switch)
                when = datetime.now().strftime("%Y-%m-%d %H:%M")
                try:
                    cards = ix.collect_ones(rarity)
                except IndexReadError as e:
                    log(f"Index check: {e}; skipping {rarity}.")
                    finished = False
                    continue
                counts[rarity] = len(cards)
                ones.set_rarity(rarity, cards, when, log=log)
    except IndexReadError as e:
        log(f"Index check stopped: {e}.")
        finished = False
    finally:
        try:
            close_any_menu(g)
        except StopBot:
            raise

    if finished:
        with open(os.path.join(RECORDS_DIR, "last_counts.json"), "w") as f:
            json.dump(counts, f)
    total = sum(counts.values())
    with open(os.path.join(RECORDS_DIR, "sweeps.csv"), "a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write("time,total_number1s,by_rarity\n")
        f.write(f"{stamp},{total},\"{counts}\"\n")
    shown = ", ".join(f"{n.replace('_', ' ')} {c}" for n, c in counts.items() if c) or "none"
    log(f"#1s in the Index ({len(counts)} tabs{'' if finished else ', stopped early'}, "
        f"skipped {', '.join(skipped) or 'nothing'}): {shown}")
    return counts, finished


if __name__ == "__main__":
    game = Game()
    try:
        snapshot(game)
    except StopBot:
        pass
    finally:
        game.release_all()
