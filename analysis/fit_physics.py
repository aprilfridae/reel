"""Fit the bar's response to E from a reel_log.csv: acceleration = (hold ? A_hold : -A_release) + drag * v,
with the hold delayed by `lag`. Usage: python analysis/fit_physics.py <reel_log.csv>"""
import sys

import numpy as np
import pandas as pd

df = pd.read_csv(sys.argv[1], dtype=str)
df = df[df.reel != "reel"]
for c in ("reel", "t", "zl", "zr", "fish", "hold"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
f = df[df.zl.notna()].copy()
f["run"] = (f.reel.diff() < 0).cumsum()

best = None
for lag in np.arange(0.0, 0.45, 0.025):
    X, y = [], []
    for _, g in f.groupby(["run", "reel"]):
        if len(g) < 15:
            continue
        t = g.t.values
        c = ((g.zl + g.zr) / 2).values
        hold = g.hold.values
        v = np.gradient(c, t)
        a = np.gradient(v, t)
        # the hold that acted on this frame is the one sent `lag` seconds earlier
        idx = np.searchsorted(t, t - lag, side="right") - 1
        h = hold[np.clip(idx, 0, None)]
        ok = (t - lag) >= t[0]
        # smooth a little: positions are whole pixels
        k = np.ones(3) / 3
        a_s = np.convolve(a, k, mode="same")
        v_s = np.convolve(v, k, mode="same")
        for i in np.where(ok)[0][2:-2]:
            X.append([h[i], 1 - h[i], v_s[i]])
            y.append(a_s[i])
    X, y = np.array(X), np.array(y)
    coef, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    err = np.mean((X @ coef - y) ** 2)
    if best is None or err < best[0]:
        best = (err, lag, coef)
    print(f"lag {lag * 1000:4.0f} ms  mse {err:12.0f}  A_hold {coef[0]:7.0f}  A_release {-coef[1]:7.0f}  drag {coef[2]:6.2f}")
err, lag, coef = best
print(f"\nbest: lag {lag * 1000:.0f} ms, hold +{coef[0]:.0f} px/s^2, release {coef[1]:.0f} px/s^2, drag {coef[2]:.2f}")
