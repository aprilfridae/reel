"""Opening packs from the Packs menu, and teleporting back to the fishing spot."""
import os
import time
from datetime import datetime
from difflib import SequenceMatcher

import cv2
import numpy as np

from game import HERE, TEMPLATES
from ocr import read_text, read_words

# Rarest first; the bot works down this list during the pack hour
PRIORITY = ["iced", "radiation", "kawaii", "glitched", "acid", "tsunami", "storm", "volcano",
            "underground", "halloween", "rainbow", "diamond", "gold", "silver", "bronze", "basic"]
EVENT_PACKS = ["blood_moon", "eclipse", "volcano", "acid", "tsunami", "storm", "meteor"]
# The nightly pack session: Rainbow and rarer, plus every event pack, rarest first.
# (Basic, Bronze, Silver, Gold and Diamond are left alone.)
SESSION_PACKS = ["iced", "radiation", "kawaii", "glitched", "atlantis",
                 "blood_moon", "eclipse", "meteor", "acid", "tsunami", "storm", "volcano",
                 "underground", "halloween", "rainbow"]
# Their name pictures were cut while greyed out, so their color can't be checked.
# Every other pack is matched by shape AND color (a greyed-out one won't match,
# which is fine: there's nothing to open).
GREY_TEMPLATES = {"atlantis", "blood_moon", "eclipse", "meteor"}
NAME_THRESHOLD = 0.85
MAX_OPENS_PER_VISIT = 20
REVEALS_DIR = os.path.join(HERE, "reveals")
NUMBER1_THRESHOLD = 0.8
RARITY_THRESHOLD = 0.7  # real labels score 0.74+ at reveal size; normal cards stay under 0.6


_BADGE = None


def _dark(img):
    return np.where(img.max(axis=2) < 70, 255, 0).astype(np.uint8)


def number_one_hits(img, threshold=NUMBER1_THRESHOLD):
    """Every '#1' serial badge on screen, as [(x, y, score)].
    The badge is a black '#1' on a rainbow box whose colors are animated, so the
    black lettering is matched, then the box around it must be rainbow (many hues);
    the gold #2 and bronze #3 badges are one color and are rejected. Card sizes vary,
    so a range of sizes is tried."""
    global _BADGE
    if _BADGE is None:
        _BADGE = cv2.imread(os.path.join(TEMPLATES, "number1_badge_index.png"))
    dark = _dark(img)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    best = None
    for s in np.arange(0.7, 2.6, 0.1):
        # Resize the color badge smoothly, then take its dark lettering
        t = _dark(cv2.resize(_BADGE, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC))
        if t.shape[0] > dark.shape[0] or t.shape[1] > dark.shape[1]:
            continue
        res = cv2.matchTemplate(dark, t, cv2.TM_CCOEFF_NORMED)
        if best is None or res.max() > best[0].max():
            best = (res, t.shape)
    if best is None:
        return []
    res, (th, tw) = best
    hits = []
    while True:
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if score < threshold:
            return hits
        res[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = -1
        box = hsv[y:y + th, x:x + tw]
        colorful = box[(box[..., 1] > 120) & (box[..., 2] > 120)]
        if len(colorful) > 0.25 * th * tw:
            hues = np.histogram(colorful[:, 0], bins=6, range=(0, 180))[0]
            if (hues > 0.08 * len(colorful)).sum() >= 3:  # at least 3 distinct hues
                hits.append((x + tw // 2, y + th // 2, score))


def find_number_one(img, threshold=NUMBER1_THRESHOLD):
    hits = number_one_hits(img, threshold)
    return hits[0] if hits else None


_RARITY = {}


def find_rarity_cards(img, threshold=RARITY_THRESHOLD):
    """Cards on screen whose rarity label says BLOOD or ECLIPSE.
    Matches the white label word only (white_text), over a range of sizes since
    reveal cards are drawn bigger than Index cards. Returns {rarity: [(x, y, score)]}
    for rarities with at least one hit (with threshold=0: the best score each)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white = np.where(gray > 200, 255, 0).astype(np.uint8)
    out = {}
    for rarity in ("blood", "eclipse"):
        if rarity not in _RARITY:
            _RARITY[rarity] = cv2.imread(os.path.join(TEMPLATES, f"rarity_{rarity}.png"),
                                         cv2.IMREAD_GRAYSCALE)
        best = None
        for s in np.arange(0.9, 2.61, 0.05):
            # Resize the gray word first, then threshold, so letters stay solid
            t = cv2.resize(_RARITY[rarity], None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            t = np.where(t > 170, 255, 0).astype(np.uint8)
            res = cv2.matchTemplate(white, t, cv2.TM_CCOEFF_NORMED)
            if best is None or res.max() > best[0].max():
                best = (res, t.shape)
        res, (th, tw) = best
        hits = []
        while True:
            _, score, _, (x, y) = cv2.minMaxLoc(res)
            if threshold == 0:
                hits.append((x + tw // 2, y + th // 2, score))
                break
            if score < threshold:
                break
            hits.append((x + tw // 2, y + th // 2, score))
            res[max(0, y - th):y + th, max(0, x - tw):x + tw] = -1
        if hits:
            out[rarity] = hits
    return out


def read_catch_popup(game, timeout=2.5):
    """Wait for the "You caught ..." popup. Returns (got_atlantis, popup_image).
    An Atlantis catch's title reads "You caught an Atlantis Pack!".
    The popup animates in, so it's watched for about a second (picture match on
    each frame) and its text is also read with OCR, before deciding it's not Atlantis."""
    end = time.time() + timeout
    while time.time() < end:
        img = game.frame()
        log = game.find("popup_log", img)
        if log:
            break
        game.wait(0.1)
    else:
        return False, None
    s = game.ui_scale(img)
    x, y = log[0], log[1]
    title = (x - 60 * s, y + 50 * s, x + 450 * s, y + 140 * s)
    whole = (x - 80 * s, y - 30 * s, x + 420 * s, y + 230 * s)  # the whole popup
    read = False
    watch_until = time.time() + 1.2
    while time.time() < watch_until:
        if game.find("popup_atlantis", img, region=title) is not None:
            return True, img
        if not read and time.time() > watch_until - 0.8:  # once it's settled
            x0, y0, x1, y1 = (max(0, int(v)) for v in whole)
            if "atlantis" in read_text(img[y0:y1, x0:x1], scale=2).lower():
                return True, img
            read = True
        game.wait(0.1)
        img = game.frame()
        if not game.find("popup_log", img):
            break  # popup went away on its own
    return False, img


CLOSE_BUTTONS = ("close_daily", "close_gifts", "close_market", "close_menu")  # the menus' red X's differ


def dismiss_reveal(game):
    """If a pack reveal ("Continue" / "Open Another") is on screen, click Continue. A
    reveal left open (e.g. the bot was stopped mid-session) covers everything else."""
    p = Packs(game)
    for _ in range(3):
        cont, _ = p._find_buttons(game.frame())
        if not cont:
            return
        game.click(*cont)
        game.park_mouse()
        game.wait(1.0)


def close_any_menu(game):
    """Close whatever menu is open (Packs, Card Market, Gifts, Daily...) with its red X,
    and make sure it really closed: an open menu blocks the side buttons."""
    dismiss_reveal(game)
    for _ in range(4):
        img = game.frame()
        h, w = img.shape[:2]
        middle = (w * 0.15, h * 0.1, w * 0.85, h * 0.9)
        hit = next((x for x in (game.find(n, img, 0.85, region=middle) for n in CLOSE_BUTTONS) if x), None)
        if not hit:
            return True
        game.click(hit[0], hit[1])
        game.park_mouse()
        game.wait(0.6)
    print("A menu wouldn't close.")
    return False


def close_popup(game):
    """Close the catch popup if it's up (it gets in the way of menus)."""
    for _ in range(4):
        img = game.frame()
        if not game.find("popup_log", img):
            return
        x = game.find("popup_close", img)
        if x:
            game.click(x[0], x[1])
            game.park_mouse()
        game.wait(0.4)


class Packs:
    def __init__(self, game):
        self.game = game
        self.opened = 0

    def _scale(self, img):
        return self.game.ui_scale(img)

    def menu_is_open(self, img):
        return self.game.find("packs_header", img) is not None

    def open_menu(self):
        g = self.game
        close_popup(g)
        for _ in range(4):
            img = g.frame()
            if self.menu_is_open(img):
                return True
            cont, _ = self._find_buttons(img)
            if cont:
                # A leftover pack reveal covers the Packs button; finish it first
                g.click(*cont)
                g.park_mouse()
                g.wait(1.0)
                continue
            hit = g.find("packs_button", img)
            if hit:
                g.click(hit[0], hit[1])
            g.wait(1.0)
        print("Couldn't open the Packs menu.")
        return False

    def close_menu(self):
        g = self.game
        for _ in range(3):
            img = g.frame()
            if not self.menu_is_open(img):
                return
            hit = g.find("close_menu", img)
            if hit:
                g.click(hit[0], hit[1])
            g.wait(0.6)

    def _menu_center(self, img):
        h, w = img.shape[:2]
        return w // 2, h // 2

    def _find_buttons(self, img):
        """(continue, open_another) centers or None. Open Another's text shrinks to fit
        its count, so it's found as the orange button to the right of Continue."""
        g = self.game
        cont = g.find("continue_pair", img) or g.find("continue_button", img)
        if not cont:
            return None, None
        s = self._scale(img)
        cx, cy = cont[0], cont[1]
        x0, x1 = int(cx + 60 * s), int(min(img.shape[1], cx + 500 * s))
        y0, y1 = int(cy - 30 * s), int(cy + 30 * s)
        strip = img[y0:y1, x0:x1].astype(int)
        b, gr, r = strip[..., 0], strip[..., 1], strip[..., 2]
        orange = (r > 200) & (gr > 90) & (gr < 200) & (b < 110)
        if orange.sum() < 3000 * s * s:
            return (cx, cy), None
        return (cx, cy), (x0 + int(np.where(orange)[1].mean()), cy)

    def find_open_button(self, pack):
        """With the menu open, scroll until the pack is found.
        Returns the (x, y) of its OPEN button, or None if it's missing or greyed out."""
        g = self.game
        img = g.frame()
        cx, cy = self._menu_center(img)
        g.scroll(cx, cy, 15)  # back to the top
        g.wait(0.4)
        for _ in range(6):
            img = g.frame()
            s = self._scale(img)
            name = g.find("pack_" + pack, img, NAME_THRESHOLD, color_check=pack not in GREY_TEMPLATES)
            if name:
                x, y, _ = name
                # The OPEN button sits right under the name, inside the same tile
                region = (x - 90 * s, y + 5 * s, x + 90 * s, y + 80 * s)
                btn = g.find("open_button", img, threshold=0.75, region=region)
                if btn:
                    return btn[0], btn[1]
                if y < img.shape[0] * 0.65:
                    return None  # tile fully in view and greyed out: none to open
                # Name near the bottom edge: its button may be cut off; scroll on
            g.scroll(cx, cy, -3)
            g.wait(0.4)
        return None

    def open_pack(self, pack, should_stop=lambda: False):
        """Open every pack of this kind (or until should_stop). Leaves the menu closed.
        Returns how many times it opened."""
        g = self.game
        if not self.open_menu():
            return 0
        btn = self.find_open_button(pack)
        if not btn:
            self.close_menu()
            return 0
        count = self._open_from(btn, pack, should_stop)
        self.close_menu()
        return count

    def _open_button_under(self, img, pack):
        """OPEN button of this pack if its tile is on screen and openable."""
        g = self.game
        s = self._scale(img)
        name = g.find("pack_" + pack, img, NAME_THRESHOLD, color_check=pack not in GREY_TEMPLATES)
        if not name:
            return None, False
        x, y, _ = name
        region = (x - 90 * s, y + 5 * s, x + 90 * s, y + 80 * s)
        btn = g.find("open_button", img, threshold=0.75, region=region)
        return ((btn[0], btn[1]) if btn else None), True


    def _learn_last_label(self, img, pack):
        """No picture of 'last: Eclipse Pack' exists yet. Save the auto-roll label from
        the first Eclipse reveal so it can be cut into one later."""
        if pack == "eclipse" and not os.path.exists(os.path.join(TEMPLATES, "last_eclipse.png")):
            path = os.path.join(HERE, "eclipse_label_sample.png")
            if not os.path.exists(path):
                h, w = img.shape[:2]
                cv2.imwrite(path, img[int(h * 0.9):, int(w * 0.8):])

    def _record_reveal(self, img, pack):
        """Save a reveal only if it has a Blood or Eclipse rarity card in it (the new
        rarities, where #1s are still up for grabs). The #1 badge doesn't always show
        here, so the Index check after the event is the real record."""
        self._learn_last_label(img, pack)
        rare = find_rarity_cards(img)
        if not rare:
            return
        os.makedirs(REVEALS_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        kinds = " ".join(f"{len(v)}x{k}" for k, v in rare.items())
        shot = f"{stamp} {kinds}.png"
        cv2.imwrite(os.path.join(REVEALS_DIR, shot), img)
        badge = find_number_one(img)
        log = os.path.join(REVEALS_DIR, "log.csv")
        new = not os.path.exists(log)
        with open(log, "a", encoding="utf-8") as f:
            if new:
                f.write("time,pack,blood_cards,eclipse_cards,number1_badge_seen,screenshot\n")
            f.write(f"{stamp},{pack},{len(rare.get('blood', []))},{len(rare.get('eclipse', []))},"
                    f"{'yes' if badge else 'no'},{shot}\n")
        print(f"Pulled {kinds} card(s)" + (" with a #1 badge!" if badge else "")
              + f" - saved reveals/{shot}", flush=True)

    def _open_from(self, btn, pack, should_stop):
        """Click a pack's OPEN button, then Open Another until none are left."""
        g = self.game
        print(f"Opening {pack.replace('_', ' ')} packs")
        g.click(*btn)
        g.park_mouse()
        count = 1
        while True:
            # Wait for the reveal to finish and the buttons to show up
            end = time.time() + 20
            another = cont = None
            img = None
            while time.time() < end:
                img = g.frame()
                cont, another = self._find_buttons(img)
                if another:
                    break
                if cont:
                    # Open Another can show up a moment after Continue; look again
                    g.wait(0.8)
                    img = g.frame()
                    cont2, another = self._find_buttons(img)
                    cont = cont2 or cont
                    break
                g.wait(0.2)
            if (cont or another) and pack in EVENT_PACKS:
                self._record_reveal(img, pack)
            if another and count >= MAX_OPENS_PER_VISIT:
                # During an event auto-roll keeps adding packs while the reveal is up,
                # so "Open Another" never runs out. Take a break; the rest get opened
                # on the next visit (after a catch, chores, website requests).
                print(f"Opened {count} {pack.replace('_', ' ')} packs; taking a break", flush=True)
                another = None
            if another and not should_stop():
                g.click(*another)
                g.park_mouse()  # a hovered button changes color
                count += 1
                g.wait(0.5)  # let the old buttons disappear
                continue
            if cont:
                g.click(*cont)
                g.wait(0.8)
            elif not another:
                print("Pack reveal didn't finish as expected; moving on.")
            break
        self.opened += count
        return count

    def open_session(self, should_stop, log=print):
        """Open every pack in SESSION_PACKS until none are left.
        Returns True when all are done, False if should_stop() cut it short."""
        for pack in SESSION_PACKS:
            while True:
                if should_stop():
                    return False
                n = self.open_pack(pack, should_stop)
                if not n:
                    break
                log(f"Opened {pack.replace('_', ' ')} x{n}")
        return True

    def open_by_priority(self, should_stop):
        for pack in PRIORITY:
            if should_stop():
                return
            self.open_pack(pack, should_stop)


def _find_place(game, img, place):
    """Center of the word `place` in the Teleport list, read with OCR, or None.
    Matched loosely: the leaderboard can show through the menu and garble letters
    (e.g. "Spawn" read as "Sptown")."""
    h, w = img.shape[:2]
    # Only the column the Teleport list opens in (left of the right-hand buttons);
    # the dock's "Fish - Fishing spot" prompt would otherwise count as "Fishing"
    x0, x1, y0, y1 = int(w * 0.68), int(w * 0.93), int(h * 0.2), int(h * 0.85)
    best, best_score = None, 0.6
    for text, x, y in read_words(img[y0:y1, x0:x1]):
        score = SequenceMatcher(None, text.lower().strip(".,-"), place.lower()).ratio()
        if score > best_score:
            best, best_score = (x0 + x, y0 + y), score
    return best


def teleport(game, place, settle=1.5, poll=0.5):
    """Teleports menu -> `place` (e.g. "Fishing", "Spawn"). `settle` is how long to let
    the world load in afterwards, `poll` how often to look for the menu closing. The game may say
    'Wait a moment' first. The list is read with OCR, so the background showing
    through the menu doesn't matter."""
    close_popup(game)
    close_any_menu(game)  # an open menu (e.g. the Card Market) covers the Teleports button
    for _ in range(4):
        img = game.frame()
        spot = _find_place(game, img, place)
        if not spot:
            hit = game.find("teleports_button", img)
            if not hit:
                game.wait(1)
                continue
            game.click(hit[0], hit[1])
            game.wait(0.8)
            img = game.frame()
            spot = _find_place(game, img, place)
            if not spot:
                continue
        # Click the button's icon, left of the word: the leaderboard (if open) covers
        # the right part of the Teleport menu and would take the click instead
        s = game.ui_scale(img)
        before = _thumb(img)
        game.click(spot[0] - 80 * s, spot[1])
        game.park_mouse()
        # Done once the Teleport list has closed (two looks in a row, since one OCR
        # miss isn't proof) and the view has actually changed (we moved)
        end = time.time() + 8
        gone = 0
        while time.time() < end:
            game.wait(poll)
            now = game.frame()
            gone = gone + 1 if not _find_place(game, now, place) else 0
            if gone >= 2:
                game.wait(settle)  # let the world load in
                return True
        # Still open, or nothing happened ("Wait a moment"): close the list and retry
        if _find_place(game, game.frame(), place):
            hit = game.find("teleports_button", game.frame())
            if hit:
                game.click(hit[0], hit[1])
                game.park_mouse()
                game.wait(0.8)
    print(f"Couldn't teleport to {place}.")
    return False


def _thumb(img):
    """Small grayscale copy of the world view (without the side menus) for
    'did the view change' checks."""
    h, w = img.shape[:2]
    mid = img[int(h * 0.1):int(h * 0.85), int(w * 0.1):int(w * 0.6)]
    return cv2.cvtColor(cv2.resize(mid, (64, 48)), cv2.COLOR_BGR2GRAY).astype(int)


def teleport_to_fishing(game):
    return teleport(game, "Fishing")
