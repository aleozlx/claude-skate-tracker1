#!/usr/bin/env python3
"""validate_session_length.py — does hr_above_rest_per_kmh depend on how long the session was?

Runs on your own files and prints aggregates only (raw/ stays private).

1. Truncation test, the controlled experiment. Every long session is measured whole, then as if it
   had stopped after L rolling minutes (pieces from the start: what a short session really is) and
   as L-minute pieces from the middle (no warm-up). Per L: median bias and robust spread of
   log(piece / whole). A duration-independent metric shows bias near 0 and spread that shrinks
   with L.
2. Noise model. Fits sd^2 = a/L + b to those spreads (session_length.py) and shows fitted vs seen.
   The a and b it prints are what process_fit.py --se-a/--se-b take.
3. Across sessions. Median metric per duration band, and the correlation of log duration with what
   is left of the metric after a log learning curve (should be near 0).

    python validate_session_length.py raw/*.zip --hrrest 55
"""
import argparse, glob, math
from datetime import date

import numpy as np

import process_fit
import session_length as sl


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--hrrest", type=int, default=59)
    ap.add_argument("--min-full", type=float, default=45, help="rolling minutes for a 'long' session")
    ap.add_argument("--windows", default="3,5,7,10,15,20,30")
    ap.add_argument("--mid-start", type=float, default=15, help="mid pieces start here (rolling min)")
    a = ap.parse_args()

    paths = sorted(p for pat in a.files for p in glob.glob(pat))
    rows, series = [], []
    for p in paths:
        row, rec = process_fit.process(p, 190, a.hrrest)
        s = sl.Series(rec, a.hrrest)
        if s.ratio() is not None:
            rows.append(row)
            series.append(s)
    longs = [s for s in series if s.rolling_min >= a.min_full]
    windows = [float(w) for w in a.windows.split(",")]
    print(f"{len(series)} sessions, {len(longs)} with >= {a.min_full:.0f} rolling minutes")

    print("\n== 1. truncation test: log(piece / whole session)")
    print(f"   {'piece':>8s}  {'from start: n, bias, sd':>28s}   {'from minute %.0f: n, bias, sd' % a.mid_start:>30s}")
    pieces = {}
    for L in windows:
        cols = []
        for lo in (0.0, a.mid_start):
            d = []
            for s in longs:
                if s.rolling_min < lo + L + 5:  # a piece must be a strict part of the session
                    continue
                k = s.ratio(s.window(lo, lo + L))
                if k:
                    d.append(math.log(k / s.ratio()))
            pieces.setdefault(L, []).extend(d)
            cols.append(f"{len(d):3d}  {100 * np.median(d):+6.1f}%  {100 * sl.robust_sd(d):5.1f}%" if len(d) >= 5
                        else f"{len(d):3d}  (too few)")
        print(f"   {L:5.0f} min  {cols[0]:>28s}   {cols[1]:>30s}")

    print("\n== 2. noise model sd = sqrt(a/L + b), start and mid pieces pooled")
    fa, fb = sl.fit_noise(pieces)
    print(f"   a = {fa:.4f}, b = {fb:.5f}   (process_fit.py --se-a {fa:.3f} --se-b {fb:.4f})")
    for L in windows:
        if len(pieces[L]) >= 5:
            print(f"   {L:5.0f} min  seen {100 * sl.robust_sd(pieces[L]):5.1f}%   fitted {100 * sl.rel_sd(L, fa, fb):5.1f}%")
    for L in (90, 120):
        print(f"   {L:5.0f} min  fitted {100 * sl.rel_sd(L, fa, fb):5.1f}%  (floor b alone: {100 * math.sqrt(fb):.1f}%)")

    print("\n== 3. across sessions")
    dur = np.array([s.rolling_min for s in series])
    y = np.array([s.ratio() for s in series])
    for lo, hi in ((0, 15), (15, 40), (40, 70), (70, math.inf)):
        sel = (dur >= lo) & (dur < hi)
        if sel.any():
            band = f"{lo}-{hi} min" if hi < math.inf else f"{lo}+ min"
            print(f"   {band:10s} n={sel.sum():3d}  median {np.median(y[sel]):6.2f}")
    days = [date.fromisoformat(r.get("date_local") or r["date"]) for r in rows]
    d0 = min(days)
    X = np.column_stack([np.ones(len(y)), [math.log1p((d - d0).days) for d in days]])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    print(f"   corr(log duration, metric after learning curve) = {np.corrcoef(np.log(dur), y - X @ b)[0, 1]:+.2f}")


if __name__ == "__main__":
    main()
