"""Fishing for Underground Artist RNG.

Fish only:  python fisher.py   (stand at a fishing spot first; F8 stops)
The full schedule (fishing + packs + event) is in bot.py.
"""
import argparse
import os
import time

import cv2

from game import HERE, Game, StopBot
from packs import close_popup, dismiss_popup, read_catch_popup
from vision import detect

# Bar physics fitted from live reels on a test PC at 50 fps (px/s^2 at UI scale 1)
A_HOLD = 1015
A_RELEASE = 737
DEFAULT_LEAD = 0.4  # best in replays of real reels (analysis/sim_reels.py)
CAST_DELAY = 0.3  # seconds the fishing panel must be gone before the first cast press
RECAST_EVERY = 0.4  # then E is pressed this often until a cast starts (the panel takes ~0.3s to show)
STUCK_AFTER = 15  # seconds of pressing E with no fishing panel before it counts as stuck


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
        return self.fish - c > vr * self.lead + vr * abs(vr) / (2 * brake)


class Fisher:
    def __init__(self, game, lead=DEFAULT_LEAD, debug=False, log_path=None):
        self.game = game
        self.reeler = Reeler(lead)
        self.debug = debug
        self.catches = 0
        self.last_popup = None
        # Optional per-frame record of every reel, for tuning the controller
        self.log = open(log_path, "a", buffering=1) if log_path else None
        if self.log and self.log.tell() == 0:
            self.log.write("reel,t,zl,zr,fish,hold,caught\n")
        self.reel_id = 0

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
        try:
            while True:
                now = time.time()
                img = game.frame()
                if watch and not pending and watch(img, state == "reel"):
                    pending = True
                d = detect(img, game.ui_scale(img))
                if pending and not d["zone"] and state != "reel":
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
                    hold = self.reeler.step(d, now)
                    game.key("e", hold)
                    if self.log and self.reel_id < 6 and int(now * 4) % 4 == 0 and \
                            now - getattr(self, "_last_shot", 0) > 0.9:
                        # a few screenshots mid-reel, to check the vision against
                        self._last_shot = now
                        cv2.imwrite(os.path.join(HERE, f"reel_{self.reel_id}_{int(now * 10) % 100000}.png"), img)
                    if self.log:
                        fish = "" if d["fish"] is None else f"{d['fish']:.1f}"
                        self.log.write(f"{self.reel_id},{now:.3f},{d['zone'][0]},{d['zone'][1]},"
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
                    if self.log:
                        # A popup means the fish was caught; none means it got away
                        self.log.write(f"{self.reel_id},{time.time():.3f},,,,,"
                                       f"{int(self.last_popup is not None)}\n")
                    self.reel_id += 1
                    print(f"Reel finished ({self.catches} so far)" + (", got an Atlantis pack!" if won_pack else ""))
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
