"""Fishing for Underground Artist RNG.

Fish only:  python fisher.py   (stand at a fishing spot first; F8 stops)
The full schedule (fishing + packs + event) is in bot.py.
"""
import argparse
import json
import os
import time

import cv2

from game import HERE, Game, StopBot
from packs import close_popup, dismiss_popup, read_catch_popup
from vision import PANEL_FROM_BOTTOM, PANEL_HALF_WIDTH, STRIP_HALF, STRIP_ROWS, detect

# Bar physics fitted from live reels on Angie's PC at 50 fps (px/s^2 at UI scale 1)
A_HOLD = 1015
A_RELEASE = 737
DEFAULT_LEAD = 0.4  # best in replays of real reels (analysis/sim_reels.py)
CAST_DELAY = 0.3  # seconds the fishing panel must be gone before the first cast press
RECAST_EVERY = 0.4  # then E is pressed this often until a cast starts (the panel takes ~0.3s to show)
SLOW_FULL_EVERY = 0.5  # seconds between whole-window frames while fishing without the GPU stream
LOG_FIRST_REELS = 10 # reels of each run written to reel_log.csv
FAST_LOOK = 0.02 # seconds between looks (50 a second) the bar controller was tuned at
SLOW_LEAD = 1.5  # extra lead per second of look time beyond that
CALIB_FILE = os.path.join(HERE, "reel_calib.json")
PENDING_WAIT = 20# seconds act() (opening event packs...) waits for a cast in the water to be caught
STUCK_AFTER = 15  # seconds of pressing E with no fishing panel before it counts as stuck


def fit_lag(reels, min_frames=15):
    """How long after E is pressed or released the bar starts to answer, fitted from recorded reels
    [(times, bar centres, holds)]: acceleration = (A_hold if held else -A_release) + drag * velocity, with the
    hold delayed by `lag`. About 50 ms on Angie's PC and 175 ms on a PC with a slower link to the game
    (analysis/fit_physics.py). None if there isn't enough to go on."""
    import numpy as np
    hz = 50.0
    rs = []
    for t, c, hold in reels:
        if len(t) < min_frames:
            continue
        t, c, hold = np.asarray(t, float), np.asarray(c, float), np.asarray(hold, float)
        tt = np.arange(t[0], t[-1], 1 / hz)
        if len(tt) < 20:
            continue
        # every reel is resampled to 50 Hz and smoothed, so the fit means the same at 25 or 100 looks a second
        # (differentiating raw whole-pixel positions at 90 looks/s is mostly noise: it fitted 0 ms for a 200 ms PC)
        cs = np.convolve(np.pad(np.interp(tt, t, c), 2, mode="edge"), np.ones(5) / 5, mode="valid")
        hh = hold[np.clip(np.searchsorted(t, tt, side="right") - 1, 0, None)]
        v = (cs[4:] - cs[:-4]) * hz / 4  # velocity over 80 ms
        a = (v[4:] - v[:-4]) * hz / 4
        rs.append((hh, v, a))
    if sum(len(a) for _, _, a in rs) < 150:
        return None
    best = None
    for lag_i in range(0, 13):  # 0 to 240 ms in 20 ms steps
        X, y = [], []
        for hh, v, a in rs:
            n = len(a)
            hi = np.arange(n) + 6 - lag_i  # the hold that acted on the frame this acceleration is centred on
            ok = hi >= 0
            X.append(np.c_[hh[hi[ok]], 1 - hh[hi[ok]], v[2:2 + n][ok]])
            y.append(a[ok])
        X, y = np.vstack(X), np.concatenate(y)
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        err = float(np.mean((X @ coef - y) ** 2))
        if best is None or err < best[0]:
            best = (err, lag_i / hz)
    return best[1]


def lead_for_lag(lag):
    """How far ahead (seconds) to aim the bar for a given input lag: the best lead in replays was 0.4 at 50 ms
    of lag and about 1.0 at 175 ms (analysis/sim_friend.py). A lag under ~90 ms leaves the default alone."""
    if lag is None or lag <= 0.09:
        return DEFAULT_LEAD
    return min(1.3, max(DEFAULT_LEAD, 0.4 + 4.5 * (lag - 0.05)))


def plan_hold(fish, fish_v, c, v, width, physics, horizon=0.6, dt=0.025, last=None):
    """Look ahead `horizon` seconds and pick hold/release now.
    Tries every plan of the form 'do X for k steps, then the opposite' (the best
    plan for a push/pull bar like this switches at most once in a short window),
    simulates the bar with the fitted physics and the input delay, predicts the
    fish from its recent speed, and keeps the plan that keeps the fish deepest
    inside the zone. Returns True to hold E."""
    a_hold, a_rel, drag, lag, lo, hi = physics
    steps = max(2, int(horizon / dt))
    lag_steps = int(round(lag / dt))
    half = width / 2
    margin = 0.2 * width  # aim to keep the fish this far from the zone's edges
    best_cost, best_first = None, fish > c
    for first in (True, False):
        for k in range(steps + 1):
            cc, vv, cost = c, v, 0.0
            for i in range(steps):
                # inputs already sent are still arriving for the first `lag` steps
                if i < lag_steps and last is not None:
                    h = last
                else:
                    j = i - lag_steps
                    h = first if j < k else not first
                a = (a_hold if h else -a_rel) + drag * vv
                vv += a * dt
                cc += vv * dt
                if cc < lo:
                    cc, vv = lo, max(vv, 0.0)
                elif cc > hi:
                    cc, vv = hi, min(vv, 0.0)
                # the fish tends to keep sweeping the way it's going
                f = min(max(fish + fish_v * (i + 1) * dt, lo), hi)
                err = abs(f - cc)
                out = err - (half - margin)
                cost += (out * out if out > 0 else 0.0) + 0.002 * err * err
            if best_cost is None or cost < best_cost:
                # k == 0 means the switch happens right away, so "now" is the opposite
                best_cost, best_first = cost, first if k > 0 else not first
    return best_first


class Reeler:
    def __init__(self, lead):
        self.lead = lead
        self.T = FAST_LOOK  # smoothed time between looks at the screen (a slow PC sees fewer frames)
        self.reset()

    def reset(self):
        self.prev_c = self.prev_t = None
        self.v = 0.0
        self.width = 0
        self.fish = None
        self.prev_fish = None
        self.fish_v = 0.0

    def step(self, d, now):
        """Returns True if E should be held."""
        zl, zr = d["zone"]
        s = d["scale"]
        if d["fish"] is not None:
            self.fish = d["fish"]
        # The fish icon can cover one end of the zone; rebuild it from the full width
        self.width = max(self.width, zr - zl)
        if zr - zl < self.width - 4 and self.fish is not None:
            if abs(self.fish - zl) < abs(self.fish - zr):
                zl = zr - self.width
            else:
                zr = zl + self.width
        c = (zl + zr) / 2

        if self.prev_t is not None and now > self.prev_t:
            dt = now - self.prev_t
            self.T = 0.9 * self.T + 0.1 * min(dt, 0.5)
            self.v = 0.5 * self.v + 0.5 * (c - self.prev_c) / dt
            if self.fish is not None and self.prev_fish is not None:
                self.fish_v = 0.7 * self.fish_v + 0.3 * (self.fish - self.prev_fish) / dt
        self.prev_c, self.prev_t = c, now
        self.prev_fish = self.fish
        if self.fish is None:
            return False

        # Chase the fish, not where it is now: the fish often sweeps steadily one
        # way, so judge by how fast the bar is closing in on it (relative speed),
        # and hold E if the bar would still fall short after reacting and braking.
        vr = self.v - self.fish_v
        brake = (A_RELEASE if vr > 0 else A_HOLD) * s
        # fewer looks per second means the hold/release is acted on later and lasts longer: aim further
        # ahead then (replays in analysis/sim_lowfps.py; nothing changes at 50 looks/s or more)
        lead = self.lead + SLOW_LEAD * max(0.0, self.T - FAST_LOOK)
        return self.fish - c > vr * lead + vr * abs(vr) / (2 * brake)


class Fisher:
    def __init__(self, game, lead=DEFAULT_LEAD, debug=False, log_path=None, on_log_ready=None, settings=None):
        self.game = game
        self.reeler = Reeler(lead)
        self.debug = debug
        self.catches = 0
        self.last_popup = None
        # Optional per-frame record of every reel, for tuning the controller
        self.log = open(log_path, "a", buffering=1) if log_path else None
        if self.log and self.log.tell() == 0:
            self.log.write("reel,t,zl,zr,fish,hold,caught\n")
        # A short record of the first reels of every run (reel_log.csv next to the program), to
        # tune the controller to a PC it hasn't seen: how the bar answered E, how the fish moved
        self.csv = self.log
        self.csv_path = self.csv_start = None
        self.on_log_ready = on_log_ready  # called once, with a summary line, after LOG_FIRST_REELS reels
        self.looks = []
        self.first_reel_t = None
        self.grab_ms = 0.0  # smoothed time to get one frame
        self.grab_full_ms = 0.0  # ...and one whole frame
        self.detect_ms = 0.0  # ...and to read the bar and fish off it
        if self.csv is None:
            path = os.path.join(HERE, "reel_log.csv")
            try:
                if not os.path.exists(path) or os.path.getsize(path) < 300_000:
                    self.csv_path = path
                    self.csv_start = os.path.getsize(path) if os.path.exists(path) else 0
                    self.csv = open(path, "a", buffering=1 << 16)  # (flushed after each reel: a write per frame is slow on a weak PC)
                    if self.csv.tell() == 0:
                        self.csv.write("reel,t,zl,zr,fish,hold,caught\n")
            except OSError:
                self.csv = None
        self.reel_id = 0
        self.sample_saved = False
        # The bar answers E after a delay that differs by PC (50 ms on one, 175 ms on another): it's fitted from the
        # first reels and sets how far ahead to aim (a saved value is used until then)
        self.auto_lead = lead == DEFAULT_LEAD
        self.cal_frames, self.cal_reels, self.lag = [], [], None
        self.settings = settings  # the website's fishing settings (fishing.json), read at the start of each reel
        self.fit_lead = lead  # the aim-ahead the fitted lag asks for
        self._applied = None
        if self.auto_lead:
            try:
                saved = json.load(open(CALIB_FILE))
                self.lag = saved.get("lag")
                self.fit_lead = float(saved.get("lead", lead))
            except (OSError, ValueError, TypeError):
                pass
        self.apply_settings()

    def apply_settings(self):
        """The aim-ahead actually used: the fitted one scaled by the website's "ping compensation" (0% = always the
        default 0.4 s, 100% = as fitted, up to 150%), or a number of seconds typed in by hand."""
        s = {}
        try:
            s = (self.settings() if self.settings else None) or {}
        except Exception:
            pass
        try:
            if s.get("manual") and s.get("lead") is not None:
                lead = min(2.0, max(0.1, float(s["lead"])))
            else:
                comp = min(1.5, max(0.0, float(s.get("comp", 100)) / 100))
                lead = DEFAULT_LEAD + (self.fit_lead - DEFAULT_LEAD) * comp
        except (TypeError, ValueError):
            lead = self.fit_lead
        self.reeler.lead = lead
        shown = (None if self.lag is None else round(self.lag, 3), round(self.fit_lead, 2), round(lead, 2))
        if shown != self._applied:
            self._applied = shown
            try:
                import webstate
                webstate.save("fishcal.json", {"lag": shown[0], "fitted": shown[1], "lead": shown[2],
                                               "at": time.strftime("%H:%M:%S")})
            except Exception:
                pass

    def _calibrate(self):
        frames, self.cal_frames = self.cal_frames, []
        if len(frames) >= 15:
            t, c, h = zip(*frames)
            self.cal_reels = (self.cal_reels + [(t, c, h)])[-12:]
        if not self.auto_lead or len(self.cal_reels) not in (3, 6, 10) or len(frames) < 15:
            return
        try:
            lag = fit_lag(self.cal_reels)
        except Exception as e:  # tuning is a convenience: the default lead stays
            print(f"(couldn't fit the bar's response: {type(e).__name__})")
            return
        if lag is None:
            return
        self.lag = lag
        lead = lead_for_lag(lag)
        if abs(lead - self.fit_lead) > 0.05:
            print(f"The bar answers E after about {lag * 1000:.0f} ms here: the fit asks for {lead:.2f}s ahead (was {self.fit_lead:.2f}s)")
        self.fit_lead = lead
        self.apply_settings()
        try:
            json.dump({"lag": lag, "lead": lead}, open(CALIB_FILE, "w"))
        except OSError:
            pass

    def run(self, should_stop=lambda: False, on_catch=None, on_stuck=None,
            watch=None, act=None):
        """Fish until should_stop() is true (checked between reels).
        on_catch() runs after a catch that won a pack (popup already closed);
        on_stuck() runs when casting keeps failing.
        watch(img, reeling) is called on every frame; once it returns True, act()
        runs as soon as no reel is in progress, then fishing carries on. While
        reeling, watch should do only quick work so the reel isn't slowed down."""
        game = self.game
        state = "idle"
        idle_since = time.time()
        last_cast = 0.0
        last_stuck = 0.0
        saved_stuck = False
        last_zone = 0.0
        pending = False
        pending_since = 0.0
        reel_t0, reel_frames = time.time(), 0
        scale, last_full = None, 0.0
        try:
            while True:
                now = time.time()
                # Without the GPU stream a whole frame takes ~100 ms; the strip around the panel is all the
                # reel needs, and several times quicker. A whole frame is still taken now and then
                # (for watch: events, chat, coins) while not reeling.
                # (the longer a whole frame takes, the less often one is taken)
                full_every = max(SLOW_FULL_EVERY, self.grab_full_ms / 1000 * 20)
                panel_only = (game.panel_capture and scale is not None
                              and (state == "reel" or now - last_full < full_every))
                half = PANEL_HALF_WIDTH
                if panel_only:
                    rows, half = STRIP_ROWS, STRIP_HALF  # just the Stop button, the track and the blue button
                    t_grab = time.time()
                    img = game.panel_frame(rows, half, scale)
                else:
                    rows = PANEL_FROM_BOTTOM
                    t_grab = time.time()
                    img = game.frame()
                    last_full = time.time()
                    self.grab_full_ms = 0.9 * self.grab_full_ms + 0.1 * (last_full - t_grab) * 1000
                    scale = game.ui_scale(img)
                    if watch and not pending and watch(img, state == "reel"):
                        pending = True
                        pending_since = now
                self.grab_ms = 0.95 * self.grab_ms + 0.05 * (time.time() - t_grab) * 1000
                t_det = time.time()
                d = detect(img, scale if scale is not None else game.ui_scale(img), rows, reeling=state == "reel", half=half)
                self.detect_ms = 0.95 * self.detect_ms + 0.05 * (time.time() - t_det) * 1000
                # act() opens menus: not while a fish is on the line or being reeled (that catch is
                # finished and its popup closed first), but don't wait more than PENDING_WAIT for it
                if pending and not d["zone"] and state != "reel" and (not d["busy"] or now - pending_since > PENDING_WAIT):
                    game.key("e", False)
                    close_popup(game)
                    act()
                    pending = False
                    state = "idle"
                    idle_since = time.time()
                    continue

                if d["zone"]:
                    last_zone = now
                    if state != "reel":
                        state = "reel"
                        saved_stuck = False
                        self.reeler.reset()
                        self.apply_settings()  # (the website's setting may have changed since the last reel)
                        reel_t0, reel_frames = now, 0
                    reel_frames += 1
                    if not self.sample_saved and now - reel_t0 > 1.5:
                        # one picture of a reel in progress, to check the vision against on a new PC
                        self.sample_saved = True
                        cv2.imwrite(os.path.join(HERE, "reel_sample.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    hold = self.reeler.step(d, now)
                    game.key("e", hold)
                    self.cal_frames.append((now, (d["zone"][0] + d["zone"][1]) / 2, float(hold)))
                    if self.log and self.reel_id < 6 and int(now * 4) % 4 == 0 and \
                            now - getattr(self, "_last_shot", 0) > 0.9:
                        # a few screenshots mid-reel, to check the vision against
                        self._last_shot = now
                        cv2.imwrite(os.path.join(HERE, f"reel_{self.reel_id}_{int(now * 10) % 100000}.png"), img)
                    if self.csv and (self.log or self.reel_id < LOG_FIRST_REELS):
                        fish = "" if d["fish"] is None else f"{d['fish']:.1f}"
                        self.csv.write(f"{self.reel_id},{now:.3f},{d['zone'][0]},{d['zone'][1]},"
                                       f"{fish},{int(hold)},\n")
                    if self.debug:
                        print(f"zone={d['zone']} fish={d['fish']} v={self.reeler.v:6.0f} hold={hold}")
                    if d["fish"] is None and not saved_stuck:
                        # Save what the bot saw so we can teach it this fish
                        name = f"stuck_{int(time.time())}.jpg"
                        cv2.imwrite(os.path.join(HERE, name), img)
                        print(f"Couldn't find the fish; saved {name}")
                        saved_stuck = True
                    time.sleep(0.005)
                    continue

                if state == "reel" and d["busy"] and now - last_zone < 1.0:
                    # Panel still up: just a frame where the bar wasn't read
                    time.sleep(0.005)
                    continue
                if state == "reel":
                    game.key("e", False)
                    self.catches += 1
                    won_pack, self.last_popup = read_catch_popup(game)
                    if self.csv and (self.log or self.reel_id < LOG_FIRST_REELS):
                        # A popup means the fish was caught; none means it got away
                        self.csv.write(f"{self.reel_id},{time.time():.3f},,,,,"
                                       f"{int(self.last_popup is not None)}\n")
                    self.reel_id += 1
                    self._calibrate()
                    if self.csv:
                        self.csv.flush()
                    secs = max(time.time() - reel_t0, 0.1)
                    self.looks.append(reel_frames / secs)
                    print(f"Reel finished ({self.catches} so far, {reel_frames / secs:.0f} looks/s)"
                          + (", got an Atlantis pack!" if won_pack else ""))
                    if self.first_reel_t is None:
                        self.first_reel_t = time.time()
                    # after 10 reels, or (if reels are few) 3 or more and 4 minutes since the first
                    if self.on_log_ready and self.csv_path and (
                            self.reel_id >= LOG_FIRST_REELS
                            or (self.reel_id >= 3 and time.time() - self.first_reel_t > 240)):
                        mid = sorted(self.looks)[len(self.looks) // 2]
                        self.on_log_ready(f"window {img.shape[1]}x{img.shape[0]}, ui scale {game.ui_scale(img):.2f}, "
                                          f"capture {game.cap.mode}{' + strip' if game.strips or game.slow_capture else ''}, "
                                          f"median {mid:.0f} looks/s, "
                                          f"frame grab {self.grab_ms:.0f} ms (whole frame {self.grab_full_ms:.0f} ms), "
                                          f"detect {self.detect_ms:.0f} ms, "
                                          f"bar lag {'?' if self.lag is None else f'{self.lag * 1000:.0f} ms'}, "
                                          f"{self.reeler.lead:.2f}s lead")
                        self.on_log_ready = None
                    if won_pack:
                        close_popup(game)  # (the packs menu is opened next: the popup must be gone)
                        if on_catch:
                            on_catch()
                    else:
                        dismiss_popup(game)  # click its X and carry on: no waiting for it to fade
                    state = "idle"
                    idle_since = time.time()
                    continue

                if should_stop():
                    return
                if d["busy"]:
                    state = "wait"
                else:
                    if state != "idle":
                        idle_since = now
                    state = "idle"
                    # The game ignores E for a while after a catch (1.4 to 2.5 seconds, it varies),
                    # then accepts it. So E is pressed every RECAST_EVERY seconds from the moment
                    # the fishing panel is gone: the first press the game accepts casts, with no
                    # timer guess in between (a fixed wait either wastes time or comes too early)
                    if now - idle_since > CAST_DELAY and now - last_cast > RECAST_EVERY:
                        if now - idle_since > STUCK_AFTER and now - last_stuck > STUCK_AFTER:
                            print("Casting isn't working.")
                            last_stuck = now
                            if on_stuck:
                                on_stuck()
                        game.tap("e")
                        last_cast = time.time()
                time.sleep(0.005)
        finally:
            game.key("e", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lead", type=float, default=DEFAULT_LEAD, help="how far ahead (seconds) to aim the bar")
    ap.add_argument("--debug", action="store_true", help="print what the bot sees every frame")
    args = ap.parse_args()

    game = Game()
    fisher = Fisher(game, args.lead, args.debug)
    print("Fishing. Press F8 to stop.")
    try:
        fisher.run()
    except StopBot:
        pass
    finally:
        game.release_all()
        print(f"Stopped. {fisher.catches} reels.")


if __name__ == "__main__":
    main()
