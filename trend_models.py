#!/usr/bin/env python3
"""
trend_models.py — separate practice from conditions in the HR-cost-of-speed metric.

The metric (default `hr_above_rest_per_kmh`, lower = more efficient) improves with practice, and it
also moves when conditions change: new skates, altitude, venue. Because each condition usually covers
one unbroken stretch of dates, comparing condition averages confounds them with practice. This fits:

  1. per condition: n, median, moving-time-weighted mean, and the slope per week inside it;
  2. across all sessions: practice trend + one step per regime indicator, with the trend as a
     straight line and as a log learning curve (fast early gains, then slower), each unweighted
     and weighted by moving time.

    python trend_models.py --regimes /private/path/regimes.csv
    python trend_models.py --csv data/sessions.csv --regimes regimes.example.csv --min-km 1

Read the steps as "how much worse (+) or better (-) than baseline, once practice is accounted for".
They are model-dependent when conditions don't overlap in time; check that both trend shapes agree.
"""
import argparse, statistics

from skate_analysis import (condition, indicators, learning_x, load_regimes, load_sessions, ols,
                            t_pvalue, weeks_x)


def fmt_coef(name, b, se, dof):
    t = b / se if se and se == se and se > 0 else float("nan")
    return f"   {name:34s} {b:+8.3f}  se {se:6.3f}  p={t_pvalue(t, dof):.3f}"


def fit(rows, cols, weighted):
    """cols: list of (name, values). Returns printable lines and rss."""
    X = [[1.0] + [c[1][i] for c in cols] for i in range(len(rows))]
    y = [r["y"] for r in rows]
    w = [r["w"] for r in rows] if weighted else None
    b, se, dof, rss = ols(X, y, w)
    return [fmt_coef(n, b[i + 1], se[i + 1], dof) for i, (n, _) in enumerate(cols)], rss, dof


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--csv", default="data/sessions.csv")
    ap.add_argument("--regimes", help="regimes CSV (keep yours outside the repo)")
    ap.add_argument("--metric", default="hr_above_rest_per_kmh")
    ap.add_argument("--min-km", type=float, default=0.0, help="drop sessions shorter than this")
    a = ap.parse_args()

    rows = load_sessions(a.csv, a.metric, a.min_km)
    if len(rows) < 3:
        raise SystemExit(f"need at least 3 sessions with {a.metric}; found {len(rows)}")
    regs = load_regimes(a.regimes)
    ind = indicators(regs)
    print(f"{len(rows)} sessions {rows[0]['d']}..{rows[-1]['d']}, metric {a.metric}"
          f"{f', distance >= {a.min_km} km' if a.min_km else ''}")

    print("\n== per condition (slope = change per week inside the condition)")
    groups = {}
    for r in rows:
        groups.setdefault(condition(r["d"], regs), []).append(r)
    for name, rs in sorted(groups.items(), key=lambda kv: kv[1][0]["d"]):
        ys, ws = [r["y"] for r in rs], [r["w"] for r in rs]
        wmean = sum(y * w for y, w in zip(ys, ws)) / sum(ws) if sum(ws) else float("nan")
        line = (f"-- {name}: n={len(rs)}, {rs[0]['d']}..{rs[-1]['d']}, median {statistics.median(ys):.2f}, "
                f"weighted mean {wmean:.2f}")
        print(line)
        if len(rs) >= 4:
            lines, _, _ = fit(rs, [("slope per week", weeks_x(rs))], weighted=False)
            print("\n".join(lines))
        else:
            print("   (fewer than 4 sessions, no slope)")

    if not ind:
        print("\n(no regimes given: skipping the step models)")
    steps = [(f"step {n}", [f(r["d"]) for r in rows]) for n, f in ind.items()]
    steps = [s for s in steps if 0 < sum(s[1]) < len(rows)]  # a step that never or always applies is not estimable
    for trend_name, xs in (("linear trend (per week)", weeks_x(rows)),
                           ("log learning curve", learning_x(rows))):
        for weighted in (False, True):
            lines, rss, dof = fit(rows, [(trend_name, xs)] + steps, weighted)
            print(f"\n== {trend_name} + steps{' (weighted by moving time)' if weighted else ''}"
                  f"  rss {rss:.1f}, dof {dof}")
            print("\n".join(lines))
    if steps:
        print("\nSteps are deviations from baseline after the trend. When a condition covers one unbroken")
        print("date range it overlaps with the trend; trust a step only if both trend shapes agree.")


if __name__ == "__main__":
    main()
