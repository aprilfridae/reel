"""Opening packs from the Packs menu, and teleporting back to the fishing spot, all read from the game's memory.

The Packs menu (CardsUI > Root, titled "Packs  •  242822") holds a grid of tiles, one per pack, each a frame named after
it ("Blood Moon Pack") with its count ("x131", the CountText label) and an OPEN button. Opening one shows the reveal
(CardsUI > Root > OpenStage): the cards, then a Continue button and "Open Another (x12)" (OpenAgain). Every revealed card
is read like any other card (name, serial, rarity and its artwork's picture id, see card_art) for the website's pack log.
"""
import re
import time

import mem_gui
import mem_market
from mem_catch_popup import close_button as _popup_close, read_catch_popup_mem as _read_catch_popup_mem
from mem_catch_popup import showing as _popup_showing

EVENT_PACKS = ["blood_moon", "eclipse", "volcano", "acid", "tsunami", "storm", "meteor"]
# The nightly pack session: Rainbow and rarer, plus every event pack, rarest first.
# (Basic, Bronze, Silver, Gold and Diamond are left alone.)
SESSION_PACKS = ["iced", "radiation", "kawaii", "glitched", "atlantis",
                 "blood_moon", "eclipse", "meteor", "acid", "tsunami", "storm", "volcano",
                 "underground", "halloween", "rainbow"]
MAX_OPENS_PER_VISIT = 20
RARE = {"BLOOD", "ECLIPSE"}  # the newest rarities (where #1s are still up for grabs): logged as they're pulled
_COUNT = re.compile(r"x\s*([\d,]+)", re.I)


def read_catch_popup(game, timeout=2.5):
    """Wait for the "You caught ..." popup after a reel. Returns (got_atlantis, title): title None if no popup came
    (the fish got away)."""
    g = mem_gui.gui()
    if g is None:
        return False, None
    return _read_catch_popup_mem(game, g.mb, timeout=timeout)


def read_catch_popup_mem(game, mb, timeout=2.5):
    return _read_catch_popup_mem(game, mb, timeout=timeout)


def pack_title(pack):
    """A pack's tile in the Packs menu is named after it: "blood_moon" -> "Blood Moon Pack"."""
    return pack.replace("_", " ").title() + " Pack"


# ---- the reveal ----
def _stage():
    root = mem_gui.cards_root()
    return root and mem_gui.gui().mb._find_child(root, name="OpenStage")


def reveal_buttons():
    """(Continue, Open Another) of the showing reveal, each a button or None. Open Another only while it has packs
    left ("Open Another (x0)" doesn't count)."""
    stage = _stage()
    if not mem_gui.shown(stage):
        return None, None
    cont = mem_gui.button(stage, "Continue", depth=2)
    another = mem_gui.gui().mb._find_child(stage, name="OpenAgain")
    if another is not None:
        m = _COUNT.search(mem_gui.text_of(another))
        if not mem_gui.shown(another) or (m and int(m.group(1).replace(",", "")) == 0):
            another = None
    return cont, another


def reveal_cards():
    """[{name, serial, rarity, art, income, grade, copy}] of the cards on the showing reveal."""
    import card_art
    stage = _stage()
    g = mem_gui.gui()
    if not mem_gui.shown(stage):
        return []
    mb, out = g.mb, []
    for d, o in mb._walk(stage, depth=12, max_nodes=4000):
        if mb._name(o) != "Card" or not g.is_shown(o):
            continue
        texts = mem_market._texts(mb, o, depth=8)
        if not texts:
            continue
        f = mem_market.parse(texts)
        img = card_art._artwork(mb, o)
        f["art"] = card_art.image_id(mb, img) if img else None
        if f.get("art"):
            card_art.record(f.get("name"), f.get("rarity"), f["art"])
        if f.get("name"):
            out.append({k: f.get(k) for k in ("name", "serial", "rarity", "art", "income", "grade", "copy") if f.get(k)})
    return out


def dismiss_reveal(game):
    """If a pack reveal is showing, click Continue. A reveal left open (e.g. the bot was stopped mid-session) covers
    everything else."""
    for _ in range(3):
        cont, _ = reveal_buttons()
        if not cont:
            return
        mem_gui.click(game, cont)
        game.wait(1.0)


# ---- menus and the catch popup ----
def open_menus():
    """The X of every menu showing (CardsUI's menus, and the other screens': Card Market, Gifts, Daily...)."""
    g = mem_gui.gui()
    if g is None:
        return []
    mb, out = g.mb, []
    root = mem_gui.cards_root()
    for fr in mb._children(root) if root else []:
        if mb._class_name(fr) == "Frame" and g.is_shown(fr):
            x = mem_gui.close_x(fr)
            if x is not None:
                out.append(x)
    for s in mb._children(mb.player_gui):
        name = mb._name(s)
        if name in ("CardsUI", "FishingUI") or mb._class_name(s) != "ScreenGui" or not g.screen_on(name):
            continue
        hit = g.find(text="X", screen=name, want_obj=True)
        if hit:
            out.append(hit[2])
    return out


def close_any_menu(game):
    """Close whatever menu is open (Packs, Card Market, Gifts, Daily...) with its X, and make sure it really closed:
    an open menu blocks the side buttons."""
    dismiss_reveal(game)
    for _ in range(4):
        xs = open_menus()
        if not xs:
            return True
        mem_gui.click(game, xs[0])
        game.wait(0.6)
    print("A menu wouldn't close.")
    return False


def dismiss_popup(game):
    """Click the catch popup's X and carry straight on, without waiting for it to go: it fades out by itself in a
    moment, and casting works while it does. (close_popup is the careful version, for before menus are used.)"""
    x = _popup_close()
    if x:
        game.click(*x)
        game.park_mouse()


def close_popup(game):
    """Close the catch popup if it's up (it gets in the way of menus)."""
    for _ in range(4):
        if not _popup_showing():
            return
        x = _popup_close()
        if x:
            game.click(*x)
            game.park_mouse()
        end = time.time() + 0.5
        while time.time() < end:  # until it's gone (not a fixed pause)
            time.sleep(0.04)
            if not _popup_showing():
                return


class Packs:
    def __init__(self, game):
        self.game = game
        self.opened = 0

    # ---- the menu ----
    @staticmethod
    def _menu():
        return mem_gui.panel(r"Packs\b")

    def menu_is_open(self, img=None):
        return mem_gui.shown(self._menu())

    def _wait_menu(self, want_open, timeout=2.0):
        """Wait only as long as the Packs menu takes to appear / go: True when it's as wanted."""
        end = time.time() + timeout
        while time.time() < end:
            if self.menu_is_open() == want_open:
                return True
            self.game.wait(0.04)
        return self.menu_is_open() == want_open

    def open_menu(self):
        g = self.game
        close_popup(g)
        for _ in range(4):
            if self.menu_is_open():
                return True
            cont, _ = reveal_buttons()
            if cont:  # a leftover pack reveal covers the Packs button: finish it first
                mem_gui.click(g, cont)
                g.wait(1.0)
                continue
            hit = mem_gui.locate(text="Packs", screen="CardsUI")
            if hit:
                g.click(hit[0], hit[1])
                g.park_mouse()
                if self._wait_menu(True):
                    return True
            else:
                close_any_menu(g)  # (another menu over the side buttons)
                g.wait(1.0)
        print("Couldn't open the Packs menu.")
        return False

    def close_menu(self):
        for _ in range(3):
            menu = self._menu()
            if not mem_gui.shown(menu):
                return
            mem_gui.click(self.game, mem_gui.close_x(menu))
            if self._wait_menu(False, 1.2):
                return

    # ---- the tiles ----
    def _grid(self):
        menu = self._menu()
        return menu and mem_gui.gui().mb._find_child(menu, cls="ScrollingFrame")

    def tile(self, pack):
        grid = self._grid()
        return grid and mem_gui.gui().mb._find_child(grid, name=pack_title(pack))

    def has_tile(self, pack):
        """Is there such a pack in the menu at all (the game has a tile for it)?"""
        return self.tile(pack) is not None

    def count(self, pack):
        """How many of this pack there are to open (its tile's "x131"), 0 if none or no such pack."""
        t = self.tile(pack)
        lab = None
        if t is not None:
            mb = mem_gui.gui().mb
            lab = next((o for d, o in mb._walk(t, depth=8, max_nodes=600) if mb._name(o) == "CountText"), None)
        m = _COUNT.search(mem_gui.gui().mb._content_text(lab) or "") if lab else None
        return int(m.group(1).replace(",", "")) if m else 0

    def find_open_button(self, pack):
        """With the menu open, scroll until the pack's tile is in view. Its OPEN button, or None if there's none of
        this pack to open."""
        g = self.game
        t = self.tile(pack)
        if t is None or not self.count(pack):
            return None
        gui = mem_gui.gui()
        btn = mem_gui.button(t, "OPEN", depth=3, shown=False)
        grid = self._grid()
        for _ in range(8):
            if btn is None:
                return None
            if gui.is_shown(btn):
                return btn
            tb, box = gui.geom(btn), gui.geom(grid)
            if not tb or not box:
                return None
            g.scroll(box[0], box[1], 3 if tb[1] < box[1] else -3, check=False)
            g.wait(0.25)
        return None

    # ---- opening ----
    def open_pack(self, pack, should_stop=lambda: False, keep_menu=False):
        """Open every pack of this kind (or until should_stop). Leaves the menu closed (keep_menu=True leaves it open,
        for opening several kinds in a row). Returns how many times it opened."""
        if not self.open_menu():
            return 0
        btn = self.find_open_button(pack)
        if not btn:
            if not keep_menu:
                self.close_menu()
            return 0
        count = self._open_from(btn, pack, should_stop)
        if not keep_menu:
            self.close_menu()
        return count

    _logger = None

    def _log_reveal(self, pack, n, cards):
        """Note this reveal on the website's pack log (in the background)."""
        if Packs._logger is None:
            from concurrent.futures import ThreadPoolExecutor
            Packs._logger = ThreadPoolExecutor(max_workers=1)
        Packs._logger.submit(self._log_reveal_now, pack, n, cards)

    @staticmethod
    def _log_reveal_now(pack, n, cards):
        try:
            import packlog
            packlog.record_open(pack, n, cards)
            rare = [c for c in cards if (c.get("rarity") or "").upper() in RARE]
            ones = [c for c in cards if str(c.get("serial")) == "1"]
            shown = rare + [c for c in ones if c not in rare]
            if shown:
                print("Pulled " + ", ".join(f"{c['name']} ({(c.get('rarity') or '?').lower()}"
                                            f"{', #' + str(c['serial']) if c.get('serial') else ''})" for c in shown)
                      + (": a #1!" if ones else ""), flush=True)
        except Exception as e:
            print(f"(couldn't log a pack reveal: {type(e).__name__}: {e})", flush=True)

    def _wait_buttons(self, timeout=20):
        """Wait for the reveal to finish and its buttons to show: (continue, open_another). Looked at every 30 ms, so
        the next click is made the moment they appear (the reveal itself takes about 2.7s and can't be skipped)."""
        g = self.game
        end = time.time() + timeout
        while time.time() < end:
            cont, another = reveal_buttons()
            if cont or another:
                if not another:  # Open Another can show up a moment after Continue; look again
                    until = time.time() + 0.8
                    while time.time() < until and not another:
                        g.wait(0.03)
                        cont2, another = reveal_buttons()
                        cont = cont2 or cont
                return cont, another
            g.wait(0.03)
        return None, None

    def _wait_buttons_gone(self, timeout=1.5):
        """After a click: until the old reveal's buttons are gone (so they aren't taken for the next reveal's)."""
        end = time.time() + timeout
        while time.time() < end:
            cont, another = reveal_buttons()
            if not cont and not another:
                return
            self.game.wait(0.03)

    def _open_from(self, btn, pack, should_stop):
        """Click a pack's OPEN button, then Open Another until none are left."""
        g = self.game
        print(f"Opening {pack.replace('_', ' ')} packs")
        mem_gui.click(g, btn)
        count = 1
        while True:
            cont, another = self._wait_buttons()
            if cont or another:
                self._log_reveal(pack, count, reveal_cards())
            if another and count >= MAX_OPENS_PER_VISIT:
                # During an event auto-roll keeps adding packs while the reveal is up, so "Open Another" never runs
                # out. Take a break; the rest get opened on the next visit (after a catch, chores, website requests).
                print(f"Opened {count} {pack.replace('_', ' ')} packs; taking a break", flush=True)
                another = None
            if another and not should_stop():
                mem_gui.click(g, another)
                count += 1
                self._wait_buttons_gone()
                continue
            if cont:
                mem_gui.click(g, cont, park=False)
                g.wait(0.8)
            elif not another:
                print("Pack reveal didn't finish as expected; moving on.")
            break
        self.opened += count
        return count

    def open_session(self, should_stop, log=print):
        """Open every pack in SESSION_PACKS until none are left. Returns True when all are done, False if
        should_stop() cut it short. The Packs menu stays open from one kind of pack to the next."""
        try:
            for pack in SESSION_PACKS:
                while True:
                    if should_stop():
                        return False
                    n = self.open_pack(pack, should_stop, keep_menu=True)
                    if not n:
                        break
                    log(f"Opened {pack.replace('_', ' ')} x{n}")
            return True
        finally:
            self.close_menu()


# ---- teleporting ----
def _place_spot(place):
    """Where to click `place` in the open Teleport list, or None: its entry's left part (its icon), since the
    leaderboard (if open) covers the right part of the Teleport menu and would take the click instead."""
    g = mem_gui.gui()
    hit = g and g.find(text=place, screen="TeleportUI", exact=False, want_obj=True)
    if not hit:
        return None
    entry = g.geom(g.mb._parent(hit[2]))
    return (entry[0] - entry[2] * 0.35, entry[1]) if entry and entry[2] > 0 else (hit[0], hit[1])


def _teleports_button():
    return mem_gui.locate(name="TeleportBtn", screen="CardsUI")


def teleport(game, place, settle=1.5, poll=0.5):
    """Teleports menu -> `place` (e.g. "Fishing", "Spawn"). `settle` is how long to let the world load in afterwards,
    `poll` how often to look for the menu closing. The game may say 'Wait a moment' first."""
    close_popup(game)
    close_any_menu(game)  # an open menu (e.g. the Card Market) covers the Teleports button
    for _ in range(4):
        spot = _place_spot(place)
        if not spot:
            hit = _teleports_button()
            if not hit:
                game.wait(1)
                continue
            game.click(hit[0], hit[1])
            game.wait(0.8)
            spot = _place_spot(place)
            if not spot:
                continue
        game.click(*spot)
        game.park_mouse()
        # Done once the Teleport list has closed (two looks in a row)
        end = time.time() + 8
        gone = 0
        while time.time() < end:
            game.wait(poll)
            gone = gone + 1 if not _place_spot(place) else 0
            if gone >= 2:
                game.wait(settle)  # let the world load in
                return True
        # Still open, or nothing happened ("Wait a moment"): close the list and retry
        if _place_spot(place):
            hit = _teleports_button()
            if hit:
                game.click(hit[0], hit[1])
                game.park_mouse()
                game.wait(0.8)
    print(f"Couldn't teleport to {place}.")
    return False


def teleport_to_fishing(game):
    return teleport(game, "Fishing")
