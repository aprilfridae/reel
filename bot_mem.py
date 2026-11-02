"""underground-rng-bot — memory-reading version.

Same schedule as bot.py (fishing + events + packs + market + rebirth),
but fishing state and balance come from direct Roblox memory reads
instead of screen capture + CV / OCR.

Read-only memory access — no injection, no writes, no hooks.
"""
import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2

import balance
import chat
import gifts
import index_check
import launcher
import market
import market_scan
import mybids
import whoowns
import rebirth
import webstate
from config import load as load_config
from events import EventWatcher
from mem_fisher import MemFisher
from game import HERE, TEMPLATES, Game, StopBot, WindowLost, find_roblox
from packs import Packs, close_any_menu, close_popup, teleport_to_fishing
from mem_catch_popup import read_catch_popup_mem
from mem_market_scan import scan_market as mem_market_scan_func
from memory_backend import MemoryBackend

FULL_CHECK_EVERY = 60
EVENT_DEBOUNCE = 8
METEOR_STOP_FISHING = 20
METEOR_TELEPORT = 4
CFG = load_config()
ATLANTIS_POPUP = os.path.join(HERE, "atlantis_popup.png")
PACK_SESSION_START, PACK_SESSION_LATEST = CFG["session_start_hour"], CFG["session_end_hour"]
SESSION_STATE = os.path.join(HERE, "pack_session_done.txt")
MARKET_EVERY = CFG["market_every_minutes"] * 60
MARKET_TRIPS = CFG["market_trips"]
MARKET_KINDS = ("bid", "buy", "lookup", "join")
WEB_CHECK_EVERY = 1
REBIRTH_PEEK_EVERY = 1800
DRY_REBIRTH = False


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    webstate.set_status(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true", help="print fishing state every second")
    ap.add_argument("--log-reels", help="write every reel to this CSV")
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

    # --- memory backend: balance + fishing state (replaces vision.py + ocr.py) ---
    mb = MemoryBackend()
    mb.start()

    fisher = MemFisher(debug=args.debug, log_path=args.log_reels)
    fisher.start()
    packs = Packs(game)
    events = EventWatcher(game)
    chores = gifts.Chores(game, log=log)
    log("Bot started (memory-reading). Press F8 or create stop.flag to stop.")

    req = {"checked": 0.0, "any": False}

    def has_request():
        if time.time() - req["checked"] > 1.0:
            req["checked"] = time.time()
            req["any"] = any(r.get("status") == "waiting" and (MARKET_TRIPS or r.get("kind") == "rebirth")
                             for r in webstate.load("requests.json", []))
        return req["any"]

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
    dc = {"checked": 0.0}
    ev = {"val": "?", "since": 0.0}

    def chat_waiting():
        if time.time() - cw["checked"] > 1.0:
            cw["checked"] = time.time()
            cw["value"] = talk.pending()
            if talk.due():
                talk.read(game.frame())
        return cw["value"]

    def send_chat():
        talk.send_pending(log=log)
        cw["checked"] = 0.0

    def interrupted():
        return has_request() or chat_waiting()

    mw = {"checked": 0.0, "value": False}

    def market_work():
        if time.time() - mw["checked"] > 1.0:
            mw["checked"] = time.time()
            mw["value"] = has_request() or market_due()
        return mw["value"]

    def check_atlantis():
        won_pack, _ = read_catch_popup_mem(game, mb)
        if won_pack:
            log("Opened Atlantis pack x1")
            if not os.path.exists(ATLANTIS_POPUP):
                cv2.imwrite(ATLANTIS_POPUP, game.frame())

    state = {"pack": None, "last_full": 0.0, "ended": None}
    talk = chat.Chat(game)
    web = {"checked": 0.0, "wants": False}

    def chores_due():
        return CFG["claim_gifts"] and chores.due()

    rb = {"wanted": False, "peeked": 0.0}

    def rb_peek_due():
        return time.time() - rb["peeked"] > REBIRTH_PEEK_EVERY

    def rebirth_peek():
        rb["peeked"] = time.time()
        st = rebirth.peek(game)
        if st:
            log(f"Rebirths: {st['rebirths']} (next costs {st['cost']}, luck x{st['luck_now']} -> x{st['luck_after']})")

    def run_nightly_rebirth():
        log("Nightly rebirth")
        finished = rebirth.run_nightly(game, fraction=CFG["rebirth_fraction"],
                                       should_stop=lambda: market_work() or chat_waiting(),
                                       dry_run=DRY_REBIRTH, log=log)
        rb["wanted"] = not finished and not DRY_REBIRTH
        rb["peeked"] = time.time()

    def waiting_requests(kinds=MARKET_KINDS):
        reqs = [r for r in webstate.load("requests.json", [])
                if r["status"] == "waiting" and r["kind"] in kinds]
        if reqs and not MARKET_TRIPS and any(k in kinds for k in MARKET_KINDS):
            for r in reqs:
                if r["kind"] in MARKET_KINDS:
                    set_request(r["id"], status="failed", result="market trips are switched off for now")
            reqs = [r for r in reqs if r["kind"] not in MARKET_KINDS]
        return reqs

    def do_rebirth_requests():
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
        if time.time() - web["checked"] > WEB_CHECK_EVERY:
            web["checked"] = time.time()
            web["wants"] = (talk.pending() or bool(waiting_requests(MARKET_KINDS + ("rebirth",)))
                            or market_due() or rb_peek_due())
        return web["wants"]

    def set_request(rid, **fields):
        def fn(reqs):
            for r in reqs:
                if r["id"] == rid:
                    r.update(fields)
            return reqs
        webstate.update("requests.json", [], fn)

    jr = {"joined": False}

    def do_requests():
        for r in waiting_requests():
            set_request(r["id"], status="working", result={"lookup": "looking it up...", "join": "joining..."}
                        .get(r["kind"], "placing it now..."))
            card = r.get("card", {})
            try:
                if r["kind"] == "bid":
                    ok, msg = market_scan.place_bid(game, card, r["amount"])
                elif r["kind"] == "buy":
                    ok, msg = market_scan.buy_now(game, card, r["amount"])
                elif r["kind"] == "lookup":
                    res = whoowns.lookup(game, card.get("artist", ""), card.get("rarity", "common"),
                                         card.get("find") or None, log=log)
                    ok, msg = res["ok"] and bool(res["rows"]), (f"{len(res['rows'])} owner(s) read" if res["rows"] else res["message"])
                else:  # join
                    ok, msg = whoowns.join(game, card.get("artist", ""), card.get("rarity", "common"),
                                           card.get("serial", 0), card.get("name", ""), log=log)
                    if ok:
                        jr["joined"] = True
            except StopBot:
                raise
            except Exception as e:
                ok, msg = False, f"error: {e}"
            set_request(r["id"], status="done" if ok else "failed",
                        result=f"{msg} ({datetime.now():%H:%M})")
            log(("Done: " if ok else "Failed: ") + msg)
            if ok and r["kind"] in ("bid", "buy"):
                now = balance_after_spending(mb)
                if now:
                    log(f"Balance now {now}")
            if jr["joined"]:
                break
        req["checked"] = 0

    def balance_after_spending(mb_ref):
        """Read the balance from memory after a purchase."""
        return mb_ref.get_balance()

    def teleport_back():
        teleport_to_fishing(game)

    def market_trip():
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
                os.remove(webstate.path("scan_now.json"))
            except OSError:
                pass
            chat.restore_window(game)
            teleport_to_fishing(game)
            return
        try:
            do_requests()
            if jr["joined"]:
                jr["joined"] = False
                log("Joining another server; waiting for it to load...")
                launcher.wait_in_game(game, timeout=150, log=log)
                return
            if reqs and all(r["kind"] == "lookup" for r in reqs) and not market_due():
                gifts.close_menus(game)
                return teleport_back()
            for _ in range(3):
                cards = market_scan.scan(game, log=log, should_stop=has_request)
                # enrich with memory-read card metadata (name, pack, earnings, grade)
                try:
                    mem_cards = mem_market_scan_func(mb)
                    for card in cards:
                        for mc in mem_cards:
                            if str(card.get("serial")) == str(mc.get("serial")):
                                if mc.get("pack") and not card.get("pack"):
                                    card["pack"] = mc["pack"]
                                if mc.get("earnings") and not card.get("earnings"):
                                    card["earnings"] = mc["earnings"]
                                if mc.get("grade") and not card.get("grade"):
                                    card["grade"] = mc["grade"]
                                if mc.get("name") and not card.get("name"):
                                    card["name"] = mc["name"]
                                break
                except Exception as e:
                    log(f"(memory scan enrichment failed: {e})")
                if not has_request():
                    break
                req["checked"] = 0
                do_requests()
            try:
                mybids.read_my_bids(game, log=log)
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
            try:
                chat.restore_window(game)
            except Exception:
                pass
        teleport_to_fishing(game)

    idx = {"wanted": False}

    def run_index():
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
        return False

    def watch(img, reeling):
        """Runs on every frame while fishing.
        With memory-based fishing, this no longer reads the reel bar —
        it only handles events, disconnects, chat, and balance display."""
        if reeling:
            events.update_label(img, defer=True)
            return False
        if time.time() - dc["checked"] > 20:
            dc["checked"] = time.time()
            if launcher.is_disconnected(game, img):
                raise WindowLost()
        if talk.due():
            talk.read(img)
        if coins_due():
            coins_update(mb)
        rolled_during_reel = events.read_deferred()
        events.update_banner(img)
        raw_pack = events.pack
        if raw_pack == state["pack"]:
            ev["val"] = "?"
            pack = raw_pack
        else:
            if ev["val"] != raw_pack:
                ev["val"], ev["since"] = raw_pack, time.time()
            pack = raw_pack if time.time() - ev["since"] >= EVENT_DEBOUNCE else state["pack"]
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

    cu = {"checked": 0.0}

    def coins_due():
        if time.time() - cu["checked"] > 5.0:
            cu["checked"] = time.time()
            return True
        return False

    def coins_update(mb_ref):
        bal = mb_ref.get_balance()
        if bal:
            webstate.set_status(f"Balance: {bal}")

    def act():
        if waiting_requests(MARKET_KINDS + ("rebirth",)) or market_due():
            market_trip()
        if rb_peek_due():
            rebirth_peek()
        if talk.pending():
            send_chat()
        web["wants"] = False
        if has_request():
            return
        if chores_due():
            chores.run()
        if not state["ended"] and not state["pack"]:
            return
        if state["ended"]:
            ended, state["ended"] = state["ended"], None
            open_event_packs(ended)
            if auto():
                idx["wanted"] = True
                run_index()
            return
        if state["pack"] and state["pack"] != "meteor":
            open_event_packs(state["pack"])
            state["last_full"] = time.time()

    def session_due():
        now = datetime.now()
        if not auto() or not CFG["nightly_session"] or not PACK_SESSION_START <= now.hour < PACK_SESSION_LATEST:
            return False
        try:
            return open(SESSION_STATE).read().strip() != now.date().isoformat()
        except OSError:
            return True

    def run_session():
        manual = once("packs")
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

    try:
        packs_done_today = open(SESSION_STATE).read().strip() == datetime.now().date().isoformat()
    except OSError:
        packs_done_today = False
    rb["wanted"] = (CFG["nightly_rebirth"] and packs_done_today and rebirth.nightly_wanted()
                    and datetime.now().hour < PACK_SESSION_LATEST)

    def one_round():
        if time.time() - dc["checked"] > 20:
            dc["checked"] = time.time()
            if launcher.is_disconnected(game):
                raise WindowLost()
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
                   on_stuck=lambda: teleport_to_fishing(game))

    try:
        while True:
            try:
                one_round()
            except WindowLost:
                if not launcher.recover(game, CFG, log=log):
                    log("Roblox is gone and couldn't be restarted; stopping.")
                    break
    except StopBot:
        pass
    finally:
        fisher.close()
        game.release_all()
        game.cleaning = True
        try:
            close_popup(game)
            close_any_menu(game)
        except Exception as e:
            log(f"(couldn't tidy the screen on the way out: {e})")
        log(f"Stopped. {fisher.catches} reels, {packs.opened} pack opens.")


if __name__ == "__main__":
    main()
