"""The full bot: fishing + every event.

  python bot.py            (Roblox open, in the game; F8 stops)

What it does:
  - Fishes nonstop. When a catch's popup says Atlantis Pack, it opens it.
  - Reads the event banner (top right) to know which event is running or next.
  - During any event whose pack drops from rolling (1 in 10): keeps fishing, and the
    moment the auto-roll label says "last: <that event's> Pack", finishes the current
    reel, opens those packs, and goes back to fishing. Also checks the Packs menu once
    a minute in case one slipped past.
  - The camera is never moved (walks are replayed from recorded key presses), so
    meteor events, which need a top-down camera, are skipped: it keeps fishing.
  - After a Blood Moon / Eclipse event: records the #1s from the Index.
  - Every few minutes: claims ready playtime gifts; after 17:00 spins the daily wheel.
  - At 1:00 each night: stops fishing and opens every Rainbow-or-rarer pack and
    every event pack, then goes back to fishing.
"""
import argparse
import os
import time
from datetime import datetime

import cv2

import balance
import chat
import gifts
import index_check
import launcher
import market
import market_scan
import mybids
import rebirth
import webstate
from config import load as load_config
from events import EventWatcher
from fisher import DEFAULT_LEAD, Fisher
from game import HERE, TEMPLATES, Game, StopBot, WindowLost, find_roblox
from packs import Packs, close_any_menu, close_popup, teleport_to_fishing

FULL_CHECK_EVERY = 60  # seconds; backup Packs-menu check during an event
METEOR_STOP_FISHING = 20  # seconds before a meteor event: don't start new casts
METEOR_TELEPORT = 4  # seconds before it: teleport to Spawn (the teleport takes ~2.5s)
CFG = load_config()
ATLANTIS_POPUP = os.path.join(HERE, "atlantis_popup.png")
PACK_SESSION_START, PACK_SESSION_LATEST = CFG["session_start_hour"], CFG["session_end_hour"]
SESSION_STATE = os.path.join(HERE, "pack_session_done.txt")
MARKET_EVERY = CFG["market_every_minutes"] * 60  # seconds between market checks
MARKET_TRIPS = CFG["market_trips"]
WEB_CHECK_EVERY = 1  # seconds between looks at the website's requests / chat outbox
REBIRTH_PEEK_EVERY = 1800  # seconds between looks at the Rebirth menu for the website counter
DRY_REBIRTH = False  # --dry-run-rebirth: do everything but the second (confirming) click


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    webstate.set_status(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lead", type=float, default=DEFAULT_LEAD)
    ap.add_argument("--log-reels", help="write every reel frame-by-frame to this CSV")
    ap.add_argument("--dry-run-rebirth", action="store_true",
                    help="rebirths stop before the confirming click (nothing is spent)")
    args = ap.parse_args()
    global DRY_REBIRTH
    DRY_REBIRTH = args.dry_run_rebirth
    rebirth.ALLOW_BID_LOSS = CFG["rebirth_forfeits_bids"]

    was_open = find_roblox() is not None
    if not launcher.ensure_running(CFG, log=lambda m: print(m, flush=True)):
        raise SystemExit("Roblox isn't open and couldn't be started.")
    game = Game()
    if not was_open:
        launcher.wait_in_game(game, log=log)
    fisher = Fisher(game, args.lead, log_path=args.log_reels)
    packs = Packs(game)
    events = EventWatcher(game)
    chores = gifts.Chores(game, log=log)
    log("Bot started. Press F8 (or create stop.flag) to stop.")

    req = {"checked": 0.0, "any": False}

    def has_request():
        """A bid or buy waiting from the website? Checked at most once a second; it's
        what everything slow (pack opening, sessions, market scans) checks to let a
        bid or buy go first."""
        if time.time() - req["checked"] > 1.0:
            req["checked"] = time.time()
            req["any"] = any(r.get("status") == "waiting" and (MARKET_TRIPS or r.get("kind") == "rebirth")
                             for r in webstate.load("requests.json", []))
        return req["any"]

    # What the website says to do (mode.json): mode "auto" (the schedule, the default),
    # "fish" (just fish; no pack sessions, rebirths, Index or hourly market checks) or
    # "pause" (do nothing); and one-time jobs in "once" ("packs", "index").
    ms = {"checked": 0.0, "value": {}}

    def settings():
        if time.time() - ms["checked"] > 1.0:
            ms["checked"] = time.time()
            ms["value"] = webstate.load("mode.json", {})
        return ms["value"]

    def mode():
        return settings().get("mode", "auto")

    def auto():
        return mode() == "auto"

    def once(what):
        return what in settings().get("once", [])

    def done_once(what):
        webstate.update("mode.json", {}, lambda m: {**m, "once": [w for w in m.get("once", []) if w != what]})
        ms["checked"] = 0.0

    cw = {"checked": 0.0, "value": False}

    def chat_waiting():
        """A message typed on the website, waiting to be sent in game (looked at most
        once a second). Typing needs no menu or walking, so it's sent at the next safe
        point of whatever the bot is doing, which then carries on."""
        if time.time() - cw["checked"] > 1.0:
            cw["checked"] = time.time()
            cw["value"] = talk.pending()
            if talk.due():  # everything slow calls this often, so the chat is also read through them
                talk.read(game.frame())
        return cw["value"]

    def send_chat():
        talk.send_pending(log=log)
        cw["checked"] = 0.0

    def interrupted():
        """Slow work (pack opening, Index, nightly rebirth) stops at its next safe point for this."""
        return has_request() or chat_waiting()

    mw = {"checked": 0.0, "value": False}

    def market_work():
        """Anything that needs the market: a bid/buy, a "Check market now" press, or the
        hourly check being due. Slow work (the pack session, fishing) stops for it."""
        if time.time() - mw["checked"] > 1.0:
            mw["checked"] = time.time()
            mw["value"] = has_request() or market_due()
        return mw["value"]

    def check_atlantis():
        n = packs.open_pack("atlantis", should_stop=interrupted)
        if n:
            log(f"Opened Atlantis pack x{n}")
            if fisher.last_popup is not None and not os.path.exists(ATLANTIS_POPUP):
                cv2.imwrite(ATLANTIS_POPUP, fisher.last_popup)

    state = {"pack": None, "last_full": 0.0, "ended": None}
    talk = chat.Chat(game)
    coins = balance.Balance(game)
    web = {"checked": 0.0, "wants": False}

    def chores_due():
        return CFG["claim_gifts"] and chores.due()

    rb = {"wanted": False, "peeked": 0.0}

    def rb_peek_due():
        """Time to look at the Rebirth menu again so the website's counter stays current."""
        return time.time() - rb["peeked"] > REBIRTH_PEEK_EVERY

    def rebirth_peek():
        rb["peeked"] = time.time()
        state = rebirth.peek(game)
        if state:
            log(f"Rebirths: {state['rebirths']} (next costs {state['cost']}, luck x{state['luck_now']} -> x{state['luck_after']})")

    def run_nightly_rebirth():
        log("Nightly rebirth")
        finished = rebirth.run_nightly(game, fraction=CFG["rebirth_fraction"], should_stop=lambda: market_work() or chat_waiting(),
                                       dry_run=DRY_REBIRTH, log=log)
        rb["wanted"] = not finished and not DRY_REBIRTH
        rb["peeked"] = time.time()

    def waiting_requests(kinds=("bid", "buy")):
        """Requests from the website still waiting, of these kinds (bids/buys by default)."""
        reqs = [r for r in webstate.load("requests.json", [])
                if r["status"] == "waiting" and r["kind"] in kinds]
        if reqs and not MARKET_TRIPS and any(k in kinds for k in ("bid", "buy")):
            for r in reqs:
                if r["kind"] in ("bid", "buy"):
                    set_request(r["id"], status="failed", result="market trips are switched off for now")
            reqs = [r for r in reqs if r["kind"] not in ("bid", "buy")]
        return reqs

    def do_rebirth_requests():
        """Rebirths asked for on the website: no walking needed, so they go first."""
        for r in waiting_requests(("rebirth",)):
            try:
                count = max(1, min(rebirth.MAX_PER_REQUEST, int(float(r["amount"]))))
            except ValueError:
                count = 1
            set_request(r["id"], status="working", result=f"rebirthing x{count}...")
            try:
                done, spent, msg = rebirth.rebirth_many(game, count, dry_run=DRY_REBIRTH, log=log)
            except StopBot:
                raise
            except Exception as e:
                done, msg = 0, f"error: {e}"
            ok = done > 0 and done == count
            set_request(r["id"], status="done" if ok else "failed",
                        result=f"{done} of {count} done" + ("" if ok else f": {msg}") + f" ({datetime.now():%H:%M})")
        req["checked"] = 0

    def market_due():
        if not MARKET_TRIPS:
            return False
        scanned = webstate.load("market.json", {}).get("scanned_ts", 0)
        hourly = auto() and time.time() - scanned > MARKET_EVERY
        return hourly or os.path.exists(webstate.path("scan_now.json"))

    def web_wants_something():
        """Chat to send, a bid/buy to place, or a market check due (looked at every
        few seconds, not every frame)."""
        if time.time() - web["checked"] > WEB_CHECK_EVERY:
            web["checked"] = time.time()
            web["wants"] = (talk.pending() or bool(waiting_requests(("bid", "buy", "rebirth")))
                            or market_due() or rb_peek_due())
        return web["wants"]

    def set_request(rid, **fields):
        def fn(reqs):
            for r in reqs:
                if r["id"] == rid:
                    r.update(fields)
            return reqs
        webstate.update("requests.json", [], fn)

    def do_requests():
        """Place every waiting bid / buy (the market is already open)."""
        for r in waiting_requests():
            set_request(r["id"], status="working", result="placing it now...")
            try:
                if r["kind"] == "bid":
                    ok, msg = market_scan.place_bid(game, r["card"], r["amount"])
                else:
                    ok, msg = market_scan.buy_now(game, r["card"], r["amount"])
            except StopBot:
                raise
            except Exception as e:  # keep the bot alive; report it on the website
                ok, msg = False, f"error: {e}"
            set_request(r["id"], status="done" if ok else "failed",
                        result=f"{msg} ({datetime.now():%H:%M})")
            log(("Done: " if ok else "Failed: ") + msg)
            if ok:  # the money counter on the website, straight away
                now = coins.after_spending()
                if now:
                    log(f"Balance now {now}")
        req["checked"] = 0

    def market_trip():
        """Go to the Card Market: place waiting bids / buys, then scan the #1-#3
        listings for the website, and come back to fishing. (Rebirth requests are done
        first, without going anywhere.)"""
        do_rebirth_requests()
        reqs = waiting_requests()
        if not reqs and not market_due():
            return
        log("Going to the Card Market" + (f" ({len(reqs)} request(s))" if reqs else ""))
        if not market.go_to_market(game, log=log):
            for r in reqs:
                set_request(r["id"], status="failed", result="couldn't get the market open; try again")
            webstate.save("market.json", {**webstate.load("market.json", {}), "scanned_ts": time.time()})
            try:
                os.remove(webstate.path("scan_now.json"))  # it was tried; don't retry in a loop
            except OSError:
                pass
            chat.restore_window(game)
            teleport_to_fishing(game)
            return
        try:
            do_requests()
            # The scan takes a couple of minutes; a bid/buy that comes in meanwhile cuts
            # it short, gets placed right away (already at the market), then it rescans
            for _ in range(3):
                # (chat waits for the end of the trip, about a minute: the chat window covers
                # part of the market while it's open, so it's kept closed during the trip)
                cards = market_scan.scan(game, log=log, should_stop=has_request)
                if not has_request():
                    break
                req["checked"] = 0
                do_requests()
            try:
                mybids.read_my_bids(game, log=log)  # what's tied up in bids / requests, for the website
            except StopBot:
                raise
            except Exception as e:
                log(f"(couldn't read my bids: {e})")
            webstate.save("market.json", {"cards": cards, "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                          "scanned_ts": time.time()})
            try:
                os.remove(webstate.path("scan_now.json"))
            except OSError:
                pass
            log(f"Market checked: {len(cards)} listing(s) with serial #1-#3")
            gifts.close_menus(game)
        finally:
            # whatever happened (a stop, the window closing), chat must not stay switched off
            try:
                chat.restore_window(game)
            except Exception:
                pass
        teleport_to_fishing(game)

    idx = {"wanted": False}

    def run_index():
        """Go through the Index for #1s (every rarity but the excluded ones). A bid/buy
        stops it between tabs; it's picked up again right after (idx["wanted"])."""
        log("Recording #1s from the Index")
        _, finished = index_check.snapshot(game, log=log, should_stop=lambda: market_work() or chat_waiting())
        idx["wanted"] = not finished

    def open_event_packs(pack):
        if not auto():
            return
        if not os.path.exists(os.path.join(TEMPLATES, f"pack_{pack}.png")):
            log(f"Don't know what the {pack} pack looks like in the menu yet; skipping.")
            return
        n = packs.open_pack(pack, should_stop=interrupted)
        if n:
            log(f"Opened {pack.replace('_', ' ')} x{n}")

    def meteor_soon():
        # Chasing meteor circles needs a top-down camera, and the camera is never
        # moved anymore (recorded walks depend on it), so meteor events are skipped:
        # the bot just keeps fishing through them.
        return False

    def watch(img, reeling):
        """Runs on every frame while fishing; True means 'stop and act()'.
        During a reel only cheap work: changed labels are kept and read afterwards."""
        if reeling:
            events.update_label(img, defer=True)
            return False
        if talk.due():
            talk.read(img)
        if coins.due():
            coins.update(img)
        rolled_during_reel = events.read_deferred()
        events.update_banner(img)
        pack = events.pack
        if pack != state["pack"]:
            if state["pack"]:
                log(f"{state['pack'].replace('_', ' ')} event over")
                state["ended"] = state["pack"]
            if pack:
                log(f"Event started: {events.name} (pack: {pack})")
                state["last_full"] = time.time()
            state["pack"] = pack
        rolled = events.update_label(img)
        if state["ended"] or chores_due() or web_wants_something():
            return True
        if pack and pack != "meteor":
            if rolled == pack or pack in rolled_during_reel:
                return True
            if time.time() - state["last_full"] > FULL_CHECK_EVERY:
                return True
        return False

    def act():
        if waiting_requests(("bid", "buy", "rebirth")) or market_due():  # bids / buys first
            market_trip()
        if rb_peek_due():
            rebirth_peek()
        if talk.pending():
            send_chat()
        web["wants"] = False
        if has_request():
            return  # another one came in: go straight back for it
        if chores_due():
            chores.run()  # playtime gifts + daily spin
        if not state["ended"] and not state["pack"]:
            return
        if state["ended"]:
            ended, state["ended"] = state["ended"], None
            open_event_packs(ended)  # anything that rolled in at the very end
            if auto():
                idx["wanted"] = True  # every event can bring new #1s: check the Index
                run_index()
            return
        if state["pack"] and state["pack"] != "meteor":
            open_event_packs(state["pack"])
            state["last_full"] = time.time()

    def session_due():
        """The nightly pack session starts between 1:00 and 6:00, once a day."""
        now = datetime.now()
        if not auto() or not CFG["nightly_session"] or not PACK_SESSION_START <= now.hour < PACK_SESSION_LATEST:
            return False
        try:
            return open(SESSION_STATE).read().strip() != now.date().isoformat()
        except OSError:
            return True

    def run_session():
        manual = once("packs")  # "Open packs now" on the website
        log("Pack session: opening every Rainbow-or-rarer and event pack" + (" (asked for on the website)" if manual else ""))
        done = packs.open_session(should_stop=lambda: meteor_soon() or market_work() or chat_waiting()
                                  or mode() == "pause" or (not manual and not auto()), log=log)
        if done:
            with open(SESSION_STATE, "w") as f:
                f.write(datetime.now().date().isoformat())
            log("Pack session finished: all of those packs are open")
            if manual:
                done_once("packs")
            in_window = PACK_SESSION_START <= datetime.now().hour < PACK_SESSION_LATEST
            rb["wanted"] = auto() and in_window and CFG["nightly_rebirth"] and rebirth.nightly_wanted()
        else:
            log("Pack session paused (bid/buy/chat); it picks up again right after")

    # restarted after tonight's packs were opened but before its rebirths were done?
    try:
        packs_done_today = open(SESSION_STATE).read().strip() == datetime.now().date().isoformat()
    except OSError:
        packs_done_today = False
    rb["wanted"] = (CFG["nightly_rebirth"] and packs_done_today and rebirth.nightly_wanted()
                    and datetime.now().hour < PACK_SESSION_LATEST)

    def one_round():
        if chat_waiting():
            send_chat()
            return
        events.update_banner(game.frame(), every=0)
        log(f"Event: {events.describe()}")
        if market_work():
            market_trip()
            return
        if mode() == "pause":
            game.release_all()
            log("Paused from the website (chat, bids and rebirths still go through)")
            game.wait(1)
            return
        if once("index"):
            idx["wanted"] = True
            done_once("index")
        if idx["wanted"]:
            run_index()
            return
        if once("packs") or session_due():
            run_session()
            return
        if rb["wanted"] and auto():
            run_nightly_rebirth()
            return
        log("Fishing" + ("" if auto() else " only (set on the website)"))
        teleport_to_fishing(game)
        fishing_mode = mode()
        fisher.run(should_stop=lambda: meteor_soon() or session_due() or market_work()
                   or once("packs") or once("index") or mode() != fishing_mode,
                   on_catch=check_atlantis,
                   on_stuck=lambda: teleport_to_fishing(game),
                   watch=watch, act=act)

    try:
        while True:
            try:
                one_round()
            except WindowLost:
                # Roblox closed or crashed: start it again, join the game, carry on
                if not launcher.recover(game, CFG, log=log):
                    log("Roblox is gone and couldn't be restarted; stopping.")
                    break
    except StopBot:
        pass
    finally:
        game.release_all()
        # Stopping in the middle of a pack reveal / menu would leave it covering the
        # game, so tidy up first (the stop request itself no longer interrupts this)
        game.cleaning = True
        try:
            close_popup(game)
            close_any_menu(game)
        except Exception as e:
            log(f"(couldn't tidy the screen on the way out: {e})")
        log(f"Stopped. {fisher.catches} reels, {packs.opened} pack opens.")


if __name__ == "__main__":
    main()
