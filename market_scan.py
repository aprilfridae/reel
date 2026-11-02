"""Reading the Card Market (already open), from memory (mem_market.py): every listing with a serial #1-#3, its price,
Buy Now price, time left, seller and top bidder; bidding and buying.

Every listing loaded so far is in memory, shown or scrolled away, so "Show more" is pressed until the list (sorted by
lowest serial) goes past #3 and the whole list is read at once. The bid / buy windows are read as whole labels too.
"""
import re
import time
from difflib import SequenceMatcher

import mem_gui
import mem_market


def time_text(text):
    """'1h 13m left' -> '1h 13m' (hours, minutes, seconds as shown), or None if the text has no time in it."""
    parts = re.findall(r"(\d+)\s*([hms])\b", text or "")
    if not parts:
        return None
    units = [u for _, u in parts]
    if len(set(units)) != len(units):  # the same unit twice: not a time
        return None
    return " ".join(f"{n}{u}" for n, u in parts)


def left_seconds(text):
    """'2h 31m' / '58m 29s' / '16s' -> seconds, or None."""
    if not text:
        return None
    total, found = 0, False
    for n, unit in re.findall(r"(\d+)\s*([hms])", text):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
        found = True
    return total if found else None


def fix_numbers(text):
    """(Kept for callers: the game's own text needs no fixing.)"""
    return text


SUFFIX = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "Q": 1e15}


def amount_value(text):
    """'650B' / '630.0B' / '1.2T' -> a number, or None."""
    m = re.fullmatch(r"\s*([\d.,]+)\s*([KMBTQ]?)\w*\s*", str(text).upper().replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1)) * SUFFIX[m.group(2)]
    except ValueError:
        return None


GRID_TOP = 0.31  # the card grid starts below the "N cards for sale" line
WANTED_SERIALS = {"1", "2", "3"}
CARD_TOP = -390  # top of a card above its BID button (UI scale 1)


def page_cards(game, img=None):
    """[(bid, card)] for the listings in view, bid = (x, y, card centre x). Cards cut off by the top of the grid are
    left out."""
    h = game.size()[1]
    s = game.ui_scale()
    return [((c["bid"][0], c["bid"][1], c["cx"]), c) for c in mem_market.listings() or []
            if (c["box"][1] if c.get("box") else c["bid"][1] + CARD_TOP * s) >= h * GRID_TOP]


def _dialog_words(game=None, memory=True):
    """The bid / buy window's labels with their screen positions, [] if none is showing."""
    mem = mem_market.dialog_words()
    if mem:
        mem_gui.stats["memory"] += 1
    return [w for w in mem or [] if not w[0].startswith("<")]


def _dialog_text(game):
    words = _dialog_words(game)
    return words, " ".join(t for t, _, _ in words)


def top_bidder(game, bid):
    """Open the BID window for this listing, read 'Top bid: X by Y', and Cancel. Never places a bid. The window is
    waited for only as long as it takes to show (and to close), instead of fixed pauses."""
    game.click(bid[0], bid[1])
    game.park_mouse()
    words, text = [], ""
    end = time.time() + 2.0
    while time.time() < end:
        words, text = _dialog_text(game)
        if re.search(r"Top\s*bid|Starting\s*bid", text, re.I):
            break
        game.wait(0.05)
    result = {}
    m = re.search(r"Top\s*bid:?\s*([\d.,]+\s*[KMBTQ]?)\s*by\s+(\S+)", text, re.I)
    if m:
        result = {"top_bid": m.group(1).replace(" ", ""), "top_bidder": m.group(2)}
    elif re.search(r"Starting\s*bid", text, re.I):
        result = {"top_bidder": None}
    m = re.search(r"Starting\s*bid:?\s*([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if m:
        result["start"] = m.group(1).replace(" ", "")
    m = re.search(r"need\s+at\s+least\s+([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if m:
        result["min_next_bid"] = m.group(1).replace(" ", "")
    cancel = [(x, y) for t, x, y in words if t.lower().startswith("cancel")]
    if cancel:
        game.click(*cancel[0])
    game.park_mouse()
    end = time.time() + 1.2
    while time.time() < end:  # until the window is gone
        game.wait(0.05)
        _, text2 = _dialog_text(game)
        if not re.search(r"Top\s*bid|Starting\s*bid|need\s+at\s+least", text2, re.I):
            break
    return result


def _fix_price(price):
    """A price with no unit can't be trusted (the bid window has to say). Returns (price, trusted)."""
    if price is None:
        return None, True
    return price, bool(re.search(r"[KMBTQ]$", price))


def wait_for_listings(game, timeout=10):
    """The market shows "Nothing for sale yet" for a moment while it loads."""
    end = time.time() + timeout
    while time.time() < end:
        if mem_market.listings():
            return True
        game.wait(0.5)
    return False


def set_sort_lowest_serial(game):
    """Open the Sort dropdown and pick 'Lowest serial' (checked by reading the sort label back)."""
    wait_for_listings(game)
    for _ in range(4):
        label = mem_gui.read(text="Sort:", screen="MarketUI")
        if not label:
            game.wait(0.5)
            continue
        if "lowest serial" in label[0].lower():
            return True
        game.click(label[1], label[2])
        game.wait(0.8)
        opt = mem_gui.locate(text="Lowest serial", screen="MarketUI")
        game.click(*(opt[:2] if opt else label[1:]))  # (no option: close the dropdown and look again)
        game.park_mouse()
        game.wait(1.5)
    return False


def _similar(a, b):
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _price(card):
    return card.get("start") or card.get("current_bid") or card.get("buy_now")


def _is_wanted(card, want):
    """Is this the listing the website asked about? The same serial, and the same name (or a close one with the same
    price or seller: the website's copy may be from an older read)."""
    if want.get("serial") and card.get("serial") != want["serial"]:
        return False
    name = _similar(card.get("name"), want.get("name"))
    same_price = bool(want.get("price")) and amount_value(_price(card) or "") == amount_value(want["price"])
    seller = _similar(card.get("seller"), want.get("seller")) if want.get("seller") else 0
    return name >= 0.8 or (name >= 0.5 and (same_price or seller >= 0.85))


def find_listing(game, want, tries=3):
    """_find_once, tried again before giving up: one look can miss a listing (the list was still loading)."""
    for attempt in range(tries):
        bid, card = _find_once(game, want, strict=attempt > 0)
        if bid:
            return bid, card
        game.wait(1.5)
    return None, None


def _to_top(game, mid):
    """Scroll the grid back to its top. The list grows with each "Show more" (a scan leaves it ~50 notches down), so
    one fixed scroll may not reach it: scroll until the list's first listing is in view (or the listings in view stop
    changing)."""
    first = (mem_market.listings(shown_only=False) or [None])[0]
    if first:
        for _ in range(8):
            game.scroll(*mid, 30, check=False)  # (the market is open)
            game.wait(0.25)
            at = mem_market.where_is(first["_bid"])
            if at and at[2]:
                return
    before = None
    for i in range(8):
        game.scroll(*mid, 30, check=False)
        game.wait(0.4)
        now = [(c.get("name"), c.get("serial")) for c in mem_market.listings() or []]
        if (now and now == before) or (not now and i >= 3):
            break
        before = now
    game.wait(0.2)


STOP_AFTER = 12  # this many cards in a row past #3 (two full rows) = we're past them all


def _find_once(game, want, strict=False):
    """Load the (lowest-serial sorted) market, pressing "Show more" as needed, until the listing the website asked
    about is in it, and scroll to it. Returns (bid_button, card) or (None, None).
    strict: go further past #3 before giving up."""
    import market
    market.ensure_browse_tab(game)  # (My Bids may have left the market on another tab)
    set_sort_lowest_serial(game)
    want = dict(want)
    want.setdefault("price", _price(want))
    grid_mid = _grid_mid(game)
    cards = _load_all(game, grid_mid, lambda cs: any(_is_wanted(c, want) for c in cs)
                      or sum(c.get("serial") not in WANTED_SERIALS for c in cs) >= STOP_AFTER * (3 if strict else 2))
    card = next((c for c in cards or [] if _is_wanted(c, want)), None)
    at = _into_view(game, card, grid_mid, [100.0]) if card else None
    if not at:
        return None, None
    card["bid"] = at
    buy = mem_market.listings()  # (where its BUY button is, now it's in view)
    card["buy"] = next((c.get("buy") for c in buy or [] if c.get("_bid") == card["_bid"]), card.get("buy"))
    return (at[0], at[1], at[0]), card


def _cancel_dialog(game):
    cancel = [(x, y) for t, x, y in _dialog_words(game) if t.lower().startswith("cancel")]
    if cancel:
        game.click(*cancel[0])
    game.park_mouse()
    game.wait(0.6)


def place_bid(game, want, amount, dry_run=False):
    """Bid `amount` (e.g. '650B') on the listing. Returns (ok, message). The minimum the game shows is checked first,
    the typed amount is read back from the box, and afterwards that the window closed."""
    from ui_keys import clear_field, type_text  # small keyboard helpers
    target = amount_value(amount)
    if not target:
        return False, f"couldn't understand the amount {amount!r}"
    bid, card = find_listing(game, want)
    if not bid:
        return False, "listing not found (sold, ended, or no longer in the top 10)"
    game.click(bid[0], bid[1])
    game.park_mouse()
    game.wait(1.0)
    words = _dialog_words(game)
    text = " ".join(t for t, _, _ in words)
    if not re.search(r"Bid\s+on", text, re.I):
        _cancel_dialog(game)
        return False, "the bid window didn't open"
    need = re.search(r"need\s+at\s+least\s+([\d.,]+\s*[KMBTQ]?)", text, re.I)
    if not need or not amount_value(need.group(1)):
        _cancel_dialog(game)
        return False, "couldn't read the minimum bid; didn't bid"
    if target < amount_value(need.group(1)):
        _cancel_dialog(game)
        return False, f"too low: you need at least {need.group(1).replace(' ', '')}"
    box = next(((x, y) for t, x, y in mem_market.dialog_words() or [] if t == "<textbox>"), None)
    if not box:
        _cancel_dialog(game)
        return False, "couldn't find the amount box"
    want_typed = amount.replace(" ", "").upper()
    for attempt in range(3):
        game.click(*box)
        game.wait(0.2)
        clear_field()
        type_text(amount)
        game.wait(0.4)
        typed = next((t[len("<typed>"):] for t, x, y in (mem_market.dialog_words() or []) if t.startswith("<typed>")),
                     None)
        if typed is not None and typed.replace(" ", "").upper() == want_typed:
            break  # (memory reads exactly what's in the box)
    else:
        _cancel_dialog(game)
        return False, f"typed the amount but the box says {typed!r}; didn't bid"
    if dry_run:
        _cancel_dialog(game)
        return True, f"dry run: would bid {amount} on {card['name']}"
    place = [(x, y) for t, x, y in _dialog_words(game) if t.upper().startswith("PLACE")]
    if not place:
        _cancel_dialog(game)
        return False, "couldn't find PLACE BID"
    game.click(*place[0])
    game.park_mouse()
    game.wait(1.5)
    after = " ".join(t for t, _, _ in _dialog_words(game))
    if re.search(r"Bid\s+on", after, re.I):  # window still up: something was wrong
        _cancel_dialog(game)
        return False, f"the game didn't take the bid: {after[:120]}"
    return True, f"bid {amount} on {card['name']}"


def _buy_window(game):
    """The Buy Now confirmation ("Buy <name>?", "Price: 1.0T coins", "Sold by X", [Cancel] [BUY 1.0T]) as
    (price shown, (x, y) of its BUY button), or None if it isn't up."""
    words = _dialog_words(game)
    if not any(re.match(r"Buy\b.*\?\s*$", t, re.I) for t, _, _ in words):
        return None
    m = re.search(r"Price:?\s*\S*?\s*([\d.,]+\s*[KMBTQ])", " ".join(t for t, _, _ in words), re.I)
    button = next(((x, y) for t, x, y in words if re.match(r"BUY\b", t) and not t.rstrip().endswith("?")), None)
    return (m.group(1).replace(" ", "") if m else None), button


def buy_now(game, want, price, dry_run=False):
    """Buy the listing at its Buy Now price. Only confirms if the price shown in game matches `price` (what the
    website showed). Returns (ok, message)."""
    target = amount_value(price)
    bid, card = find_listing(game, want)
    if not bid:
        return False, "listing not found (sold or ended)"
    if not card.get("buy_now"):
        return False, "that listing has no Buy Now (anymore)"
    if amount_value(card["buy_now"]) != target:
        return False, f"Buy Now price is now {card['buy_now']}, not {price}; didn't buy"
    if not card.get("buy"):
        return False, "couldn't find the listing's BUY button"
    game.click(*card["buy"])
    game.park_mouse()
    game.wait(1.0)
    win = _buy_window(game)
    if not win:
        _cancel_dialog(game)
        return False, "the buy window didn't open as expected"
    shown, button = win
    if not shown:
        _cancel_dialog(game)
        return False, "couldn't read the price in the buy window; didn't buy"
    if amount_value(shown) != target:
        _cancel_dialog(game)
        return False, f"price in the buy window is {shown}, not {price}; didn't buy"
    if not button:
        _cancel_dialog(game)
        return False, "couldn't find the green BUY button; didn't buy"
    if dry_run:
        _cancel_dialog(game)
        return True, f"dry run: would click BUY at {button} for {shown}"
    game.click(*button)
    game.park_mouse()
    game.wait(1.5)
    if _buy_window(game):  # window still open: it didn't go through
        _cancel_dialog(game)
        return False, "the purchase didn't go through (the buy window stayed open)"
    return True, f"bought {card['name']} for {shown}"


def _show_more(img=None):
    """Center of the "Show more (N)" button if it's showing."""
    mem = mem_gui.locate(text="Show more", screen="MarketUI", exact=False)
    return (mem[0], mem[1]) if mem else None


def _finish(card):
    """A listing as the website gets it."""
    card["seen_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    secs = left_seconds(card.get("time_left"))
    if secs is not None:
        card["ends_ts"] = time.time() + secs  # for the website's live countdown
    for k in ("raw", "bid", "buy", "box", "cx", "auction_only", "_bid"):  # (only for finding it on screen)
        card.pop(k, None)
    return card


def _needs_window(card):
    """Is the bid window worth opening for this listing? Only for what the listing itself can't say: who the top
    bidder is (a listing with a bid on it shows the bid, not who made it), or a start price with no unit."""
    start, trusted = _fix_price(card.get("start"))
    if start:
        card["start"] = start
    return "start" not in card or not trusted


def _into_view(game, card, grid_mid, px_per_notch):
    """Scroll until the listing's BID button is in the grid's window (worked out from where memory says it is, and
    how far one notch of the wheel moved it last time). (x, y) of the button, or None."""
    box = mem_market.grid_box()
    for _ in range(8):
        at = mem_market.where_is(card["_bid"])
        if not at or not box:
            return None
        x, y, shown = at
        if shown and box[0] + 40 < y < box[1] - 20:
            return x, y
        notches = int(round((y - (box[0] + box[1]) / 2) / px_per_notch[0])) or (1 if y > box[1] else -1)
        game.scroll(*grid_mid, -max(-15, min(15, notches)), check=False)
        game.wait(0.25)
        after = mem_market.where_is(card["_bid"])
        if after and after[1] != y and notches:
            px_per_notch[0] = max(20.0, abs(y - after[1]) / abs(notches))  # (learnt: the wheel's step on this screen)
    return None


def _grid_mid(game):
    w, h = game.size()
    return w / 2, h * 0.55


def _load_all(game, grid_mid, enough, should_stop=lambda: False):
    """Every listing loaded, after pressing "Show more" until enough(listings) (or the end of the list), top to
    bottom. None if memory can't read the market."""
    memo = {}
    _to_top(game, grid_mid)
    cards = mem_market.listings(shown_only=False, memo=memo)
    if not cards:
        return None
    for _ in range(20):
        if enough(cards) or should_stop():
            break
        game.scroll(*grid_mid, -60, check=False)  # (to the bottom, where the button is)
        game.wait(0.3)
        more = _show_more()
        if not more:
            break  # the end of the list
        n = len(cards)
        game.click(more[0], more[1])
        game.park_mouse()
        end = time.time() + 3.0
        while time.time() < end:  # until the new listings are in
            game.wait(0.15)
            cards = mem_market.listings(shown_only=False, memo=memo) or cards
            if len(cards) > n:
                game.wait(0.3)  # (the rest of the batch)
                cards = mem_market.listings(shown_only=False, memo=memo) or cards
                break
    return cards


def scan(game, read_bidders=True, max_pages=60, log=print, should_stop=lambda: False):
    """List every #1, #2 and #3 listing (sorted by lowest serial). Only a listing whose top bidder is wanted is
    scrolled to (its bid window is opened)."""
    if not set_sort_lowest_serial(game):
        log("Couldn't set the market sort to Lowest serial.")
    grid_mid = _grid_mid(game)
    t0 = time.time()
    cards = _load_all(game, grid_mid, lambda cs: sum(c.get("serial") not in WANTED_SERIALS for c in cs) >= 6, should_stop)
    if cards is None:
        log("Couldn't read the market's listings in memory (nothing for sale, or it didn't load).")
        return []
    t1 = time.time()
    wanted = [c for c in cards if c.get("serial") in WANTED_SERIALS]
    found, px = [], [100.0]
    if read_bidders and any(_needs_window(c) for c in wanted):
        _to_top(game, grid_mid)
    for card in wanted:
        if should_stop():
            log("Market scan cut short for a bid/buy")
            break
        if read_bidders and _needs_window(card):
            at = _into_view(game, card, grid_mid, px)
            if at:
                card.update(top_bidder(game, at))
        elif "start" in card:
            card["top_bidder"] = None
        found.append(_finish(card))
    log(f"Scanned {len(cards)} listing(s), {len(found)} #1-#3 "
        f"(loading the list {t1 - t0:.0f} s, top bidders {time.time() - t1:.0f} s)")
    return found
