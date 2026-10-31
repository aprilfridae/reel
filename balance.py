"""Reading your coin balance from the game's top bar (the pill right of "News")."""
import re
import time

import webstate
from market_scan import amount_value, fix_numbers
from ocr import read_text, read_words


def read_balance(game, img):
    """The balance as shown (e.g. '3.6T'), or None if it can't be read right now
    (e.g. a menu dims the screen)."""
    h, w = img.shape[:2]
    s = game.ui_scale(img)
    top = img[0:int(60 * s), int(w * 0.1):int(w * 0.55)]
    words = read_words(top, scale=3)
    news = [x for t, x, y in words if t.lower().strip("@") == "news"]
    if not news:
        return None
    # the balance pill starts just right of the News button
    x0 = int(w * 0.1 + news[0] + 30 * s)
    pill = img[int(5 * s):int(52 * s), x0:x0 + int(150 * s)]
    text = fix_numbers(read_text(pill, scale=4)).replace(" ", "").lstrip("@©$")
    text = re.sub(r"(?<=\d)S(?=[KMBTQ])", "5", text)  # 3.5T can read as 3ST / 3.ST
    m = re.search(r"\d+(?:\.\d+)?[KMBTQ]", text)
    if not m and re.fullmatch(r"\d{2,}[KMBTQ]", text):  # dot lost: 35T -> 3.5T
        text = text[0] + "." + text[1:]
        m = re.search(r"\d+(?:\.\d+)?[KMBTQ]", text)
    return m.group(0) if m and amount_value(m.group(0)) else None


def _amount_in(pill):
    text = fix_numbers(read_text(pill, scale=4)).replace(" ", "").lstrip("@©$")
    text = re.sub(r"(?<=\d)S(?=[KMBTQ])", "5", text)
    m = re.search(r"\d+(?:\.\d+)?[KMBTQ]", text)
    if not m and re.fullmatch(r"\d{2,}[KMBTQ]", text):
        text = text[0] + "." + text[1:]
        m = re.search(r"\d+(?:\.\d+)?[KMBTQ]", text)
    return m.group(0) if m and amount_value(m.group(0)) else None


def read_market_balance(game, img):
    """The balance from the Card Market window's own coin pill (top right of the window,
    next to Refresh), which is bright and clear while the market is open (the top bar is
    dimmed behind it). None if the market isn't up or it can't be read."""
    h, w = img.shape[:2]
    s = game.ui_scale(img)
    cx, cy = w / 2 + 450 * s, h / 2 - 357 * s  # the pill's middle, measured from the window's centre
    pill = img[int(cy - 20 * s):int(cy + 20 * s), int(cx - 20 * s):int(cx + 95 * s)]
    return _amount_in(pill)


class Balance:
    """Posts the balance to the website every `every` seconds. A reading far from the
    last posted one (OCR can drop a dot: 3.5T -> 305T) is only trusted once the same
    value has been read twice in a row."""

    def __init__(self, game, every=30):
        self.game, self.every, self.last = game, every, 0.0
        self.posted = amount_value(webstate.load("balance.json", {}).get("value", "")) or None
        self.candidate = None

    def due(self):
        return time.time() - self.last > self.every

    def update(self, img):
        self.last = time.time()
        self.post(read_balance(self.game, img))

    def after_spending(self, tries=5):
        """Right after a purchase or bid: read the balance off the market window until it
        shows the change (the game takes a moment), and post it to the website at once."""
        before = self.posted
        value = None
        for _ in range(tries):
            self.game.wait(1.0)
            img = self.game.frame()
            value = read_market_balance(self.game, img)  # (the top bar is dimmed behind the market: it misreads)
            v = amount_value(value) if value else None
            if v and (before is None or v != before):
                break
        if value:
            self.post(value, trust=True)  # (the market window's own pill is clear: no double-read needed)
        return value

    def post(self, value, trust=False):
        if not value:
            return
        v = amount_value(value)
        believable = trust or self.posted is None or 0.5 < v / self.posted < 2
        if not believable and value != self.candidate:
            self.candidate = value
            self.last = time.time() - self.every + 3  # look again in a few seconds
            return
        self.candidate, self.posted = None, v
        webstate.save("balance.json", {"value": value, "at": time.strftime("%H:%M:%S")})
