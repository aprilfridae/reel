"""Rebirths: read the Rebirth menu, rebirth on request, and the nightly rebirth.

The Rebirth menu (right-hand side button) shows "Rebirths: N", your luck now and after,
and the cost in coins; its big REBIRTH button spends the coins for +luck. Cards, coins
you keep, packs and potions are all kept, so a rebirth is just "pay the price, get luck".

Nightly: after the rare-pack session, a budget of a quarter of the coins on hand is
spent rebirthing as many times as the budget covers (the price goes up each time, so it
is read again before every one). Every rebirth is checked afterwards (the counter has to
go up by one) before the next one.
"""
import json
import os
import re
import time

import tz

import mem_gui
import webstate
from balance import read_balance
from game import HERE
from market_scan import amount_value
from packs import close_any_menu, close_popup

STATE_FILE = os.path.join(HERE, "rebirth_state.json")
FRACTION = 0.25  # of the coins on hand, per night
MAX_PER_REQUEST = 50


# The menu, in memory: a frame under CardsUI > Root titled "Rebirth", holding "Rebirths: 145", "🍀 Luck now" / "x37.25",
# "🍀 After rebirth" / "x37.50", "Cost: 💰 106.6B" and the big button (its text in a "Label" child: "REBIRTH", then a
# confirm prompt after the first click).
def _panel():
    return mem_gui.panel(r"Rebirth\s*$")


def _texts(under, depth=8, max_nodes=3000):
    """[(text, object)] of the showing labels / buttons under `under`, in the menu's order."""
    g = mem_gui.gui()
    if g is None or under is None:
        return []
    mb = g.mb
    out = []
    for _, o in mb._walk(under, depth, max_nodes):
        if mb._class_name(o) in mem_gui.TEXT_CLASSES:
            t = (mb._content_text(o) or "").strip()
            if t and g.is_shown(o):
                out.append((t, o))
    return out


def menu_open(game=None, img=None):
    return mem_gui.shown(_panel())


def open_menu(game):
    """Open the Rebirth menu (the side button). True once it's showing."""
    close_popup(game)
    close_any_menu(game)
    for _ in range(3):
        spot = mem_gui.locate(text="Rebirth", screen="CardsUI")
        if not spot:
            game.wait(1)
            continue
        game.click(spot[0], spot[1])
        game.park_mouse()
        game.wait(1.2)
        if menu_open(game):
            return True
    return False


def read_state(game=None, img=None):
    """What the Rebirth menu says, as a dict (any missing field is None):
    rebirths, luck_now, luck_after, cost (text, e.g. '73.2B'), cost_value."""
    text = " ".join(t for t, _ in _texts(_panel()))
    state = {"rebirths": None, "luck_now": None, "luck_after": None, "cost": None, "cost_value": None}
    m = re.search(r"Rebirths?:?\s*(\d[\d,]*)", text, re.I)
    if m:
        state["rebirths"] = int(m.group(1).replace(",", ""))
    # the "x" in "x31.00" is read as all sorts of things (", *, €...), so skip any non-digits
    m = re.search(r"Luck\s*now\D{0,6}(\d+\.\d+)", text, re.I)
    if m:
        state["luck_now"] = float(m.group(1))
    m = re.search(r"After\s*rebirth\D{0,6}(\d+\.\d+)", text, re.I)
    if m:
        state["luck_after"] = float(m.group(1))
    m = re.search(r"Cost:?\W*([\d.,]+\s*[KMBTQ])", text, re.I)
    if m:
        state["cost"] = m.group(1).replace(" ", "")
        state["cost_value"] = amount_value(state["cost"])
    return state


def publish(state):
    """Let the website show the counter."""
    if state.get("rebirths") is not None:
        webstate.save("rebirth.json", {**{k: state.get(k) for k in
                                         ("rebirths", "luck_now", "luck_after", "cost")},
                                      "at": time.strftime("%H:%M:%S")})


def peek(game):
    """Open the menu, read it, publish the numbers, close it. Returns the state or None."""
    if not open_menu(game):
        return None
    state = read_state(game)
    publish(state)
    close_any_menu(game)
    return state


def _button(game=None):
    """The big REBIRTH button (whatever it says now: its text changes after the first click)."""
    return next((b for t, b in mem_gui.buttons(_panel(), depth=4) if t and t != "X" and mem_gui.shown(b)), None)


def _asks_to_confirm(game=None):
    """After the first click the button's text changes to a confirm prompt (it reads
    "CLICK AGAIN TO CONFIRM"; "are you sure" is accepted too in case it's reworded)."""
    text = " ".join(t for t, _ in _texts(_panel())).lower()
    return any(phrase in text for phrase in ("confirm", "click again", "are you sure", "you sure"))


def _press(game, button):
    if not mem_gui.click(game, button):
        raise RuntimeError("the REBIRTH button has no place on the screen")


ALLOW_BID_LOSS = True  # config.json "rebirth_forfeits_bids"


def _market_warning(game, wait=2.5):
    """With coins tied up in Market bids / requests, the second click opens a third screen:
    "Coins in the Market - You have 200.0B coins in Market bids / requests. If you rebirth,
    those coins are GONE ...", with REBIRTH ANYWAY and CANCEL. Returns None if it isn't
    showing, else ([(text, object)] of what's showing, coins text e.g. '200.0B')."""
    end = time.time() + wait
    while time.time() < end:
        root, g = mem_gui.cards_root(), mem_gui.gui()
        words = []
        for fr in (g.mb._children(root) if root is not None else []):  # (it may be its own menu, or in this one)
            if g.is_shown(fr):
                words += _texts(fr)
        text = " ".join(t for t, _ in words)
        if "anyway" in text.lower() or ("coins" in text.lower() and "gone" in text.lower()):
            m = re.search(r"have\s*\W*\s*([\d.,]+\s*[KMBTQ]?)\s*coins in", text, re.I)
            return words, (m.group(1).replace(" ", "") if m else "?")
        game.wait(0.3)
    return None


def _answer_market_warning(game, warning):
    """Click REBIRTH ANYWAY (or CANCEL when forfeiting bids isn't allowed). Returns the
    coins forfeited as text, or None if it was cancelled."""
    words, coins = warning
    saved = webstate.load("mode.json", {}).get("bid_anyway")  # the website's "Rebirth anyway" switch
    allow = saved if isinstance(saved, bool) else ALLOW_BID_LOSS
    webstate.save("bids_seen.json", {"coins": coins, "at": time.strftime("%H:%M:%S"), "went_ahead": allow})
    which = "anyway" if allow else "cancel"
    label = min(((len(t), o) for t, o in words if which in t.lower()), default=(0, None), key=lambda x: x[0])[1]
    if label is None or not mem_gui.click(game, label):
        raise RuntimeError("the Market-bids warning is up but its buttons couldn't be found")
    game.wait(0.8)
    return coins if allow else None


def rebirth_once(game, dry_run=False):
    """One rebirth from the open menu. It takes two clicks: the first turns the button
    into an "are you SURE you want to rebirth?" prompt, the second one does it. Returns
    (ok, message). Checked afterwards: the counter has to go up by exactly one.
    dry_run clicks once (which only arms the button), checks the prompt appeared, and
    stops before the second click, so nothing is ever spent."""
    before = read_state(game)
    if before["rebirths"] is None or before["cost_value"] is None:
        return False, "couldn't read the Rebirth menu"
    button = _button(game)
    if not button:
        return False, "couldn't find the REBIRTH button"
    armed = False
    for attempt in range(3):
        _press(game, button)  # first click: asks "are you SURE"
        game.wait(0.7 if attempt == 0 else 1.0)
        armed = _asks_to_confirm(game)
        if armed:
            break
        # Nothing showed: the menu was still settling after the last rebirth, or the click
        # was missed. Look again, then click again (unless it already went through).
        now = read_state(game)
        if now["rebirths"] is not None and now["rebirths"] > before["rebirths"]:
            publish(now)
            return True, f"rebirth #{now['rebirths']} done for {before['cost']} (luck now x{now['luck_now']})"
        game.wait(0.8)
        button = _button(game) or button
    if dry_run:
        game.wait(0.3)
        return armed, (f"dry run: rebirth #{before['rebirths'] + 1} for {before['cost']}; the 'are you sure' "
                       f"prompt {'showed' if armed else 'did NOT show'}; stopped before the second click")
    lost = None
    if armed:
        _press(game, button)  # second click (the button hasn't moved, only its text)
        warning = _market_warning(game)  # third screen, only with active Market bids
        if warning:
            try:
                lost = _answer_market_warning(game, warning)
            except RuntimeError as e:
                return False, f"{e} (text showing: {' | '.join(t for t, _ in warning[0])[:300]})"
            if lost is None:
                return False, (f"active Market bids ({warning[1]} coins) would be lost in a rebirth; "
                               "cancelled (turn on \"Rebirth anyway\" on the website to allow it)")
    # (no prompt: maybe it went straight through; the counter below tells either way)
    note = f"; {lost} coins in Market bids forfeited" if lost else ""
    for _ in range(8):
        game.wait(0.8)
        if not menu_open(game):  # the menu may close itself; reopen it to read the result
            if not open_menu(game):
                return False, "clicked REBIRTH but couldn't reopen the menu to check it"
        after = read_state(game)
        if after["rebirths"] is not None and after["rebirths"] > before["rebirths"]:
            publish(after)
            return True, f"rebirth #{after['rebirths']} done for {before['cost']} (luck now x{after['luck_now']}){note}"
    seen = " | ".join(t for t, _ in _texts(_panel()))[:300]  # to see what it got stuck on
    return False, ("clicked REBIRTH but the rebirth count didn't go up (maybe another confirm window or not enough "
                   f"coins; the menu says: {seen})")


def rebirth_many(game, count, budget=None, should_stop=lambda: False, dry_run=False, log=print):
    """Rebirth up to `count` times, stopping early when the next one would cost more
    than the budget (coins; None = no limit), when stopped, or when one fails.
    Returns (done, spent_coins, message)."""
    if not open_menu(game):
        return 0, 0.0, "couldn't open the Rebirth menu"
    done, spent, msg = 0, 0.0, ""
    try:
        for _ in range(count):
            if should_stop():
                msg = "stopped early"
                break
            state = read_state(game)
            if state["cost_value"] is None:
                msg = "couldn't read the cost"
                break
            if budget is not None and spent + state["cost_value"] > budget:
                msg = f"the next one ({state['cost']}) is over the budget"
                break
            ok, text = rebirth_once(game, dry_run)
            log(("Rebirth: " if ok else "Rebirth failed: ") + text)
            if not ok:
                msg = text
                break
            done += 1
            spent += state["cost_value"]
            game.wait(1.5)  # let the menu settle before the next one
            if dry_run:
                break  # reading the price after the first one tells nothing new
    finally:
        publish(read_state(game))
        close_any_menu(game)
    return done, spent, msg or f"did {done}"


# ---------- the nightly rebirth ----------

def _load():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def nightly_wanted():
    """Has tonight's rebirth round not been finished yet?"""
    return _load().get("done_date") != tz.now().date().isoformat()


def run_nightly(game, fraction=FRACTION, should_stop=lambda: False, dry_run=False, log=print):
    """Spend `fraction` of the coins on hand (worked out once per night and remembered,
    so a pause for a bid doesn't start over with a smaller or bigger budget) on rebirths.
    Returns True when finished for the night."""
    today = tz.now().date().isoformat()
    state = _load()
    if state.get("date") != today:
        close_popup(game)
        close_any_menu(game)
        balance = read_balance()
        coins = amount_value(balance or "")
        if not coins:
            log("Nightly rebirth: couldn't read the coin balance; skipping tonight.")
            _save({"date": today, "done_date": today})
            return True
        state = {"date": today, "budget": coins * fraction, "spent": 0.0, "done_date": None}
        log(f"Nightly rebirth: {balance} on hand, budget {fraction:.0%} of that")
        _save(state)
    done, spent, msg = rebirth_many(game, 999, budget=state["budget"] - state["spent"],
                                    should_stop=should_stop, dry_run=dry_run, log=log)
    state["spent"] += spent
    finished = not msg.startswith("stopped")
    if finished and not dry_run:
        state["done_date"] = today
    if not dry_run:
        _save(state)
    log(f"Nightly rebirth: {done} done, {msg}")
    return finished
