"""A sturdier fit of the bar's delay: resample every reel to 50 Hz, smooth, then regress acceleration on the delayed hold.
Works the same whether the log was taken at 25 or 100 looks a second. Usage: python analysis/fit_physics2.py <reel_log.csv>"""
import sys

import numpy as np
import pandas as pd

HZ = 50.0


def load(path):
    df = pd.read_csv(path, dtype=str)
    df = df[df.reel != "reel"]
    for c in ("reel", "t", "zl", "zr", "fish", "hold"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    f = df[df.zl.notna()].copy()
    f["run"] = (f.reel.diff() < 0).cumsum()
    return [(g.t.values, ((g.zl + g.zr) / 2).values, g.hold.values) for _, g in f.groupby(["run", "reel"]) if len(g) >= 15]


def resample(t, c, h):
    tt = np.arange(t[0], t[-1], 1 / HZ)
    cc = np.interp(tt, t, c)
    hh = h[np.clip(np.searchsorted(t, tt, side="right") - 1, 0, None)]
    k = np.ones(5) / 5
    cs = np.convolve(np.pad(cc, 2, mode="edge"), k, mode="valid")
    return tt, cs, hh


def fit(reels):
    rs = [resample(*r) for r in reels]
    out = []
    for lag_i in range(0, 13):  # 0 .. 240 ms in 20 ms steps
        lag = lag_i / HZ
        X, y = [], []
        for tt, c, h in rs:
            v = (c[4:] - c[:-4]) * HZ / 4  # velocity over 80 ms
            a = (v[4:] - v[:-4]) * HZ / 4
            n = len(a)
            idx = np.arange(n) + 4 + 2  # frame the acceleration is centred on
            hi = idx - lag_i
            ok = hi >= 0
            vv = v[2:2 + n]
            X.append(np.c_[h[hi[ok]], 1 - h[hi[ok]], vv[ok]])
            y.append(a[ok])
        X, y = np.vstack(X), np.concatenate(y)
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        out.append((float(np.mean((X @ coef - y) ** 2)), lag, coef))
    return out


if __name__ == "__main__":
    reels = load(sys.argv[1])
    res = fit(reels)
    best = min(res, key=lambda r: r[0])
    for err, lag, coef in res:
        print(f"lag {lag * 1000:4.0f} ms  mse {err:11.0f}  hold {coef[0]:7.0f}  release {-coef[1]:7.0f}  drag {coef[2]:6.2f}" + ("   <-- best" if lag == best[1] else ""))
