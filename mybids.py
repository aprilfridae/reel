"""What you have tied up in the Card Market, read in memory from the market's own tabs:
  My Listings: "Selling 0/6 - Winning 1", and the winning auctions with your bid on each;
  Requests:    "yours: 0/6" (cards you asked for, with coins held for them).
Coins in bids / requests are lost on a rebirth, so the website shows this next to Rebirth.
"""
import re
import time

import mem_gui
import mem_market
import webstate
from market_scan import amount_value, left_seconds

_UNITS = (("Q", 1e15), ("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3))


def short(v):
    for unit, size in _UNITS:
        if v >= size:
            return f"{v / size:.1f}".rstrip("0").rstrip(".") + unit
    return str(int(v))


def _open_tab(game, label):
    """Click a market tab by its name (its label starts with an emoji). True if found."""
    spot = mem_gui.locate(text=label, screen="MarketUI", contains=True)
    if not spot:
        return False
    game.click(spot[0], spot[1])
    game.park_mouse()
    game.wait(1.5)
    return True


def _read_memory(game):
    """(winning, amounts, items, selling, requests), or None if the tabs can't be read. The tab shows "Winning 0"
    until the market's data arrives, so a zero is only believed after a few seconds."""
    if not _open_tab(game, "Listings"):
        return None
    end = time.time() + 3.0
    while True:
        head = mem_market.header() or ""
        win = re.search(r"Winning\W*(\d+)", head)
        if (win and int(win.group(1)) > 0) or time.time() > end:
            break
        game.wait(0.25)
    items = mem_market.my_listings()
    if not win or items is None:
        return None
    sell = re.search(r"Selling\W*(\d+)\s*/", head)
    for i in items:
        secs = left_seconds(i.get("time_left"))
        i["ends_ts"] = time.time() + secs if secs is not None else None
    amounts = [i["amount"] for i in items if i["kind"] == "bid" and i["status"] == "winning" and i.get("amount")]
    requests = None
    if _open_tab(game, "Requests"):
        end = time.time() + 3.0
        while requests is None and time.time() < end:  # (its own line: the last tab's "Selling" line can linger)
            hit = mem_gui.read(text="yours:", screen="MarketUI", contains=True)
            m = re.search(r"yours\W*(\d+)\s*/", hit[0] if hit else "")
            requests = int(m.group(1)) if m else None
            if requests is None:
                game.wait(0.2)
    return int(win.group(1)), amounts, items, int(sell.group(1)) if sell else None, requests


def read_my_bids(game, log=print):
    """With the market open: read both tabs and publish for the website. Returns the dict
    or None if My Listings couldn't be read."""
    mem = _read_memory(game)
    if not mem:
        log("Couldn't read My Listings.")
        return None
    return _publish(*mem, log)


def _publish(winning, amounts, items, selling, requests, log):
    total = sum(amount_value(a) or 0 for a in amounts)
    info = {"winning": winning, "selling": selling, "amounts": amounts, "total": short(total) if amounts else "0",
            "requests": requests, "items": items, "at": time.strftime("%H:%M"), "ts": time.time()}
    webstate.save("mybids.json", info)
    log(f"My bids: {winning} winning ({', '.join(amounts) or 'no amounts read'}), "
        f"{requests if requests is not None else '?'} request(s)")
    return info
