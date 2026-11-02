"""Your coin balance, read from the game's memory (the label beside the 💰 in the top bar)."""
import time

import webstate
from market_scan import amount_value


def read_balance(game=None, img=None):
    """The balance as shown (e.g. '3.6T'), or None if memory can't tell right now."""
    from memory_backend import get_backend
    try:
        value = get_backend().get_balance()
    except Exception:
        return None
    return value if value and amount_value(value) else None


class Balance:
    """Posts the balance to the website every `every` seconds."""

    def __init__(self, game, every=30):
        self.game, self.every, self.last = game, every, 0.0
        self.posted = amount_value(webstate.load("balance.json", {}).get("value", "")) or None

    def due(self):
        return time.time() - self.last > self.every

    def update(self, img=None):
        self.last = time.time()
        self.post(read_balance())

    def after_spending(self, tries=5):
        """Right after a purchase or bid: read the balance until it shows the change (the game takes a moment), and
        post it to the website at once."""
        before = self.posted
        value = None
        for _ in range(tries):
            self.game.wait(1.0)
            value = read_balance()
            v = amount_value(value) if value else None
            if v and (before is None or v != before):
                break
        self.post(value)
        return value

    def post(self, value, trust=True):
        if not value:
            return
        self.posted = amount_value(value)
        webstate.save("balance.json", {"value": value, "at": time.strftime("%H:%M:%S")})
