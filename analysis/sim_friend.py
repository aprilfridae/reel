"""Replays the friend's recorded fish movements against his fitted bar physics (input lag 175 ms) at the frame rate
he gets, to compare controllers. Usage: python analysis/sim_friend.py <his reel_log.csv> [looks_per_second]"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from fisher import plan_hold  # noqa: E402

df = pd.read_csv(sys.argv[1], dtype=str)
df = df[df.reel != "reel"]
for c in ("reel", "t", "zl", "zr", "fish", "hold"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
f = df[df.zl.notna()].copy()
f["run"] = (f.reel.diff() < 0).cumsum()
LOOKS = float(sys.argv[2]) if len(sys.argv) > 2 else 26.0
FRAME = 1.0 / LOOKS
DT = 0.01
LAG, A_HOLD, A_REL, DRAG, LO, HI = 0.175, 1096.0, 991.0, -0.09, 148.0, 572.0


def reels():
    for _, g in f.groupby(["run", "reel"]):
        if len(g) < 30:
            continue
        fish = g.fish.ffill().bfill().values
        w = (g.zr - g.zl).max()
        yield g.t.values, fish, w, ((g.zl + g.zr) / 2).values[0]


def step(c, v, hold, dt):
    a = (A_HOLD if hold else -A_REL) + DRAG * v
    v += a * dt
    c += v * dt
    if c < LO:
        c, v = LO, max(v, 0)
    if c > HI:
        c, v = HI, min(v, 0)
    return c, v


def run(ctl):
    tot = ins = 0
    for t, fish, w, c0 in reels():
        c, v = c0, 0.0
        pipe, hold = [], False
        sim_t, next_look = t[0], t[0]
        pc = pf = pt = None
        ev = efv = 0.0
        last = False
        while sim_t < t[-1]:
            fx = np.interp(sim_t, t, fish)
            if sim_t >= next_look:
                next_look = sim_t + FRAME
                if pt is not None:
                    d = sim_t - pt
                    ev = 0.5 * ev + 0.5 * (c - pc) / d
                    efv = 0.7 * efv + 0.3 * (fx - pf) / d
                pc, pf, pt = c, fx, sim_t
                last = ctl(fx, c, ev, efv, w, last)
                pipe.append((sim_t + LAG, last))
            while pipe and pipe[0][0] <= sim_t:
                hold = pipe.pop(0)[1]
            c, v = step(c, v, hold, DT)
            ins += abs(fx - c) < w / 2
            tot += 1
            sim_t += DT
    return ins / tot


def relative(lead, ah=1015.0, ar=737.0):
    def ctl(fx, c, v, fv, w, last):
        vr = v - fv
        brake = ar if vr > 0 else ah
        return fx - c > vr * lead + vr * abs(vr) / (2 * brake)
    return ctl


def planner(horizon, lag=LAG + 0.5 * FRAME):
    phys = (A_HOLD, A_REL, DRAG, lag, LO, HI)

    def ctl(fx, c, v, fv, w, last):
        return plan_hold(fx, fv, c, v, w, phys, horizon=horizon, dt=0.02, last=last)
    return ctl


print(f"looks/s {LOOKS:.0f}, lag {LAG * 1000:.0f} ms, {sum(1 for _ in reels())} reels")
print(f"current (lead 0.40, Angie's brakes):      {run(relative(0.40)):.1%}")
for lead in (0.2, 0.3, 0.5, 0.6, 0.8, 1.0):
    print(f"relative lead {lead:.2f}, his brakes:         {run(relative(lead, A_HOLD, A_REL)):.1%}")
for h in (0.6, 0.8, 1.0, 1.3):
    print(f"plan_hold horizon {h:.1f}s (lag {LAG * 1000 + 0.5 * FRAME * 1000:.0f} ms): {run(planner(h)):.1%}")
