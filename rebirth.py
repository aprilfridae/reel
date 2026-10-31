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
from datetime import datetime

import webstate
from balance import read_balance
from game import HERE
from market_scan import amount_value, fix_numbers
from ocr import read_words
from packs import close_any_menu, close_popup

STATE_FILE = os.path.join(HERE, "rebirth_state.json")
FRACTION = 0.25  # of the coins on hand, per night
MAX_PER_REQUEST = 50


def _menu_words(game, img=None):
    img = game.frame() if img is None else img
    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(w * 0.2), int(h * 0.12), int(w * 0.8), int(h * 0.9)
    return [(t, x0 + x, y0 + y) for t, x, y in read_words(img[y0:y1, x0:x1], scale=2)], (x0, y0, x1, y1)


def menu_open(game, img=None):
    words, _ = _menu_words(game, img)
    return any(t.lower().startswith("rebirths") for t, _, _ in words)


def open_menu(game):
    """Open the Rebirth menu (the side button). True once it's showing."""
    close_popup(game)
    close_any_menu(game)
    for _ in range(3):
        img = game.frame()
        h, w = img.shape[:2]
        words = read_words(img[int(h * 0.3):int(h * 0.85), int(w * 0.86):], scale=2)
        spot = next(((int(w * 0.86) + x, int(h * 0.3) + y) for t, x, y in words if t.lower() == "rebirth"), None)
        if not spot:
            game.wait(1)
            continue
        game.click(*spot)
        game.park_mouse()
        game.wait(1.2)
        if menu_open(game):
            return True
    return False


def read_state(game, img=None):
    """What the Rebirth menu says, as a dict (any missing field is None):
    rebirths, luck_now, luck_after, cost (text, e.g. '73.2B'), cost_value."""
    words, _ = _menu_words(game, img)
    text = fix_numbers(" ".join(t for t, _, _ in words))
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


def _button(game):
    """The big REBIRTH button: the lowest all-capitals 'REBIRTH' in the menu."""
    words, _ = _menu_words(game)
    buttons = [(x, y) for t, x, y in words if t == "REBIRTH" or (t.upper() == t and t.startswith("REBIRT"))]
    return max(buttons, key=lambda b: b[1]) if buttons else None


def _asks_to_confirm(game):
    """After the first click the button's text changes to a confirm prompt (it reads
    "CLICK AGAIN TO CONFIRM"; "are you sure" is accepted too in case it's reworded)."""
    words, _ = _menu_words(game)
    text = " ".join(t for t, _, _ in words).lower()
    return any(phrase in text for phrase in ("confirm", "click again", "are you sure", "you sure"))


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
    game.click(*button)  # first click: asks "are you SURE"
    game.park_mouse()
    game.wait(0.7)
    armed = _asks_to_confirm(game)
    if dry_run:
        game.wait(0.3)
        return armed, (f"dry run: rebirth #{before['rebirths'] + 1} for {before['cost']}; the 'are you sure' "
                       f"prompt {'showed' if armed else 'did NOT show'}; stopped before the second click")
    if armed:
        game.click(*button)  # second click (the button hasn't moved, only its text)
        game.park_mouse()
    # (no prompt: maybe it went straight through; the counter below tells either way)
    for _ in range(8):
        game.wait(0.8)
        if not menu_open(game):  # the menu may close itself; reopen it to read the result
            if not open_menu(game):
                return False, "clicked REBIRTH but couldn't reopen the menu to check it"
        after = read_state(game)
        if after["rebirths"] is not None and after["rebirths"] > before["rebirths"]:
            publish(after)
            return True, f"rebirth #{after['rebirths']} done for {before['cost']} (luck now x{after['luck_now']})"
    return False, "clicked REBIRTH but the rebirth count didn't go up (maybe a confirm window or not enough coins)"


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
    return _load().get("done_date") != datetime.now().date().isoformat()


def run_nightly(game, fraction=FRACTION, should_stop=lambda: False, dry_run=False, log=print):
    """Spend `fraction` of the coins on hand (worked out once per night and remembered,
    so a pause for a bid doesn't start over with a smaller or bigger budget) on rebirths.
    Returns True when finished for the night."""
    today = datetime.now().date().isoformat()
    state = _load()
    if state.get("date") != today:
        close_popup(game)
        close_any_menu(game)
        balance = read_balance(game, game.frame())
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
