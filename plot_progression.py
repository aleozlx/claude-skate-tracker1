#!/usr/bin/env python3
"""
plot_progression.py — visualize skill progression across sessions.

The headline metric is the HR-vs-speed DECOUPLING: as skating becomes
efficient, the same speed costs less heart rate. Rising efficiency_index
(moving speed per heartbeat above rest) is the cleanest skill proxy.

    python plot_progression.py                    # reads data/sessions.csv
    python plot_progression.py --out prog.png

A second figure (--ratio-out) puts the HR cost of speed on a date axis: one dot per session (size =
moving time), the weekly moving-time-weighted mean, a log learning curve, and the regimes from
--regimes as shaded bands (closed date ranges) or dashed lines (open-ended).

    python plot_progression.py --regimes /private/path/regimes.csv --color-by skates
"""
import argparse, csv, math, sys
from collections import defaultdict
from datetime import timedelta
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    sys.exit("pip install matplotlib")

from skate_analysis import factor_levels, learning_x, load_regimes, load_sessions, ols

# Light-mode chart tokens; categorical slots in fixed order (blue, orange, aqua).
INK, INK2, MUTED, GRID, SURF, BAND = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb", "#efeee9"
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a"]


def plot_ratio(rows, regs, out, color_by=None, metric="hr_above_rest_per_kmh"):
    """HR cost of speed over time, with regimes marked."""
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
    fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
    lo = min(r["y"] for r in rows); hi = max(r["y"] for r in rows)
    pad = (hi - lo) * 0.12 or 1
    top = hi + 2.5 * pad
    first, last = rows[0]["d"], rows[-1]["d"]
    x0, x1 = first - timedelta(days=3), last + timedelta(days=3)
    day = lambda d: f"{d:%b} {d.day}"

    # Regimes: closed ranges as bands, open-ended as a dashed line; labels staggered to avoid collisions.
    # Only what overlaps the sessions is drawn, so a stray date can't stretch the axis.
    shown = [g for g in regs if g.start <= last and (g.end is None or g.end >= first)]
    for i, g in enumerate(shown):
        ty = top - pad * 0.4 * (1 + i % 3)
        lx = max(g.start, x0)
        if g.end:
            ax.axvspan(lx, min(g.end + timedelta(days=1), x1), color=BAND, zorder=0, lw=0)
            label = g.name
        elif g.start >= first:
            ax.axvline(g.start, color=MUTED, lw=1, ls=(0, (3, 3)), zorder=1)
            label = f"{g.name} from {day(g.start)}"
        else:
            label = f"{g.name} (whole period)"
        ax.text(lx + timedelta(days=0.8), ty, label, color=INK2, fontsize=9, va="top")
    skipped = len(regs) - len(shown)
    if skipped:
        print(f"{skipped} regime row(s) fall outside {first}..{last}; not drawn")

    # Sessions, colored by one factor's level when asked (at most three groups incl. baseline).
    groups = {"session": rows}
    if color_by:
        levels = factor_levels(regs).get(color_by)
        if levels is None:
            sys.exit(f"--color-by {color_by}: no such factor in the regimes file")
        if len(levels) + 1 > len(SLOTS):
            print(f"--color-by {color_by}: more than {len(SLOTS) - 1} levels, drawing one color")
        else:
            groups = {}
            for r in rows:
                lv = next((g.level for g in regs if g.factor == color_by and g.active(r["d"])), "baseline")
                groups.setdefault(f"{color_by}={lv}", []).append(r)
            groups = dict(sorted(groups.items(), key=lambda kv: kv[1][0]["d"]))
    for (name, rs), col in zip(groups.items(), SLOTS):
        ax.scatter([r["d"] for r in rs], [r["y"] for r in rs], s=[max(30, r["w"] * 1.1) for r in rs],
                   color=col, alpha=0.75, edgecolors=SURF, linewidths=1.5, zorder=3,
                   label=f"{name} (size = moving time)")

    # Weekly moving-time-weighted mean, placed at the mean date of that ISO week's sessions.
    wk = defaultdict(list)
    for r in rows:
        y, w, _ = r["d"].isocalendar(); wk[(y, w)].append(r)
    pts = []
    for _, rs in sorted(wk.items()):
        d0 = min(r["d"] for r in rs)
        when = d0 + timedelta(days=sum((r["d"] - d0).days for r in rs) / len(rs))
        tw = sum(r["w"] for r in rs)
        pts.append((when, sum(r["y"] * r["w"] for r in rs) / tw if tw else sum(r["y"] for r in rs) / len(rs)))
    ax.plot([p[0] for p in pts], [p[1] for p in pts], color=INK, lw=2, marker="o", ms=4, zorder=4,
            label="weekly mean (moving-time weighted)")

    # Log learning curve over all sessions, no regime terms: the "practice only" reference.
    b, *_ = ols([[1.0, x] for x in learning_x(rows)], [r["y"] for r in rows])
    days = range((last - first).days + 1)
    ax.plot([first + timedelta(days=i) for i in days], [b[0] + b[1] * math.log1p(i) for i in days],
            color=MUTED, lw=1.5, ls="--", zorder=2, label="log learning curve, all sessions")

    ax.set_ylim(max(0, lo - pad), top)
    ax.set_xlim(x0, x1)
    ax.set_ylabel(f"{metric}\nlower = more efficient", color=INK2, fontsize=10)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.set_title(f"Heart-rate cost of speed, {len(rows)} sessions ({day(first)} – {day(last)}, {last.year})",
                 loc="left", color=INK, fontsize=12, pad=12)
    ax.legend(loc="lower left", fontsize=8.5, frameon=False, labelcolor=INK2, markerscale=0.6)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)
    print(f"wrote {out}")

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/sessions.csv")
    ap.add_argument("--out", default="data/progression.png")
    ap.add_argument("--ratio-out", default="data/ratio_trend.png",
                    help="HR-cost-of-speed figure; skipped when the CSV predates that column")
    ap.add_argument("--regimes", help="regimes CSV to mark on the ratio figure (keep yours outside the repo)")
    ap.add_argument("--color-by", help="color sessions by this regime factor, e.g. skates")
    a = ap.parse_args()

    with open(a.csv) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("no sessions yet")

    x    = list(range(1, len(rows) + 1))
    lbl  = [r["session_id"] for r in rows]
    dist = [num(r["distance_km"]) for r in rows]
    eff  = [num(r["efficiency_index"]) for r in rows]
    ahr  = [num(r["avg_hr"]) for r in rows]
    aspd = [num(r["avg_moving_speed_kmh"]) for r in rows]

    fig, ax = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("Inline Skating — progression", fontsize=13, weight="bold")

    ax[0,0].plot(x, eff, "o-", color="#7c3aed")
    ax[0,0].set_title("Efficiency index (speed per HR above rest) ↑ = better")
    ax[0,0].set_xticks(x); ax[0,0].set_xticklabels(lbl, rotation=45, fontsize=7)

    ax[0,1].plot(x, aspd, "o-", color="#2563eb", label="avg moving km/h")
    ax2 = ax[0,1].twinx()
    ax2.plot(x, ahr, "s--", color="#dc2626", label="avg HR")
    ax[0,1].set_title("Speed vs HR (want speed ↑, HR ↓)")
    ax[0,1].set_ylabel("km/h", color="#2563eb"); ax2.set_ylabel("bpm", color="#dc2626")
    ax[0,1].set_xticks(x); ax[0,1].set_xticklabels(lbl, rotation=45, fontsize=7)

    ax[1,0].plot(x, dist, "o-", color="#059669")
    ax[1,0].set_title("Distance (km)")
    ax[1,0].set_xticks(x); ax[1,0].set_xticklabels(lbl, rotation=45, fontsize=7)

    # HR zone stacked bars
    zk = ["z1_pct","z2_pct","z3_pct","z4_pct","z5_pct"]
    zc = ["#bfdbfe","#86efac","#fde68a","#fca5a5","#ef4444"]
    bottom = [0]*len(rows)
    for k, c in zip(zk, zc):
        vals = [num(r[k]) or 0 for r in rows]
        ax[1,1].bar(x, vals, bottom=bottom, color=c, label=k[:2].upper())
        bottom = [b+v for b, v in zip(bottom, vals)]
    ax[1,1].set_title("HR zone distribution (%)")
    ax[1,1].legend(fontsize=7, ncol=5, loc="lower center")
    ax[1,1].set_xticks(x); ax[1,1].set_xticklabels(lbl, rotation=45, fontsize=7)

    for row in ax:
        for a_ in row: a_.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(a.out, dpi=130)
    print(f"wrote {a.out}")

    ratio_rows = load_sessions(a.csv)
    if len(ratio_rows) >= 2:
        plot_ratio(ratio_rows, load_regimes(a.regimes), a.ratio_out, a.color_by)
    else:
        print("skipping ratio figure: re-run process_fit.py to add hr_above_rest_per_kmh")

if __name__ == "__main__":
    main()
