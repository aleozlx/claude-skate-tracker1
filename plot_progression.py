#!/usr/bin/env python3
"""
plot_progression.py — visualize skill progression across sessions.

The headline metric is the HR-vs-speed DECOUPLING: as skating becomes
efficient, the same speed costs less heart rate. Rising efficiency_index
(moving speed per heartbeat above rest) is the cleanest skill proxy.

    python plot_progression.py                    # reads data/sessions.csv
    python plot_progression.py --out prog.png
"""
import argparse, csv, sys
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("pip install matplotlib")

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/sessions.csv")
    ap.add_argument("--out", default="data/progression.png")
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

if __name__ == "__main__":
    main()
