"""skate_analysis.py — shared helpers for trend_models.py and plot_progression.py.

A *regime* is a stretch of dates during which some condition held: new skates, a trip to altitude,
a different venue. Regimes live in a small CSV you keep OUTSIDE this repo (it says where you were
and when). See regimes.example.csv for the format:

    factor,level,start,end,note
    skates,new,2025-03-15,,second pair from here on
    altitude,high,2025-02-20,2025-04-10,

Dates are inclusive; an empty `end` means "still true". Each (factor, level) row becomes a 0/1
indicator on a session's local date. Sessions where no level of a factor is active are that factor's
baseline.
"""
import csv, math
from collections import OrderedDict
from datetime import date

try:
    import numpy as np
except ImportError:  # pragma: no cover
    raise SystemExit("pip install numpy")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def session_date(r):
    """Local date when the CSV has it, else the UTC `date` column."""
    d = r.get("date_local") or r.get("date")
    return date.fromisoformat(d) if d else None


def load_sessions(path, metric="hr_above_rest_per_kmh", min_km=0.0):
    """Rows with a usable metric, each with .d (date), .y (metric), .w (moving minutes weight)."""
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            y, d = num(r.get(metric)), session_date(r)
            if y is None or d is None or (num(r.get("distance_km")) or 0) < min_km:
                continue
            r["d"], r["y"] = d, y
            r["w"] = num(r.get("moving_min")) or num(r.get("active_min")) or 0.0
            out.append(r)
    out.sort(key=lambda r: (r["d"], r["session_id"]))
    return out


class Regime:
    def __init__(self, factor, level, start, end, note=""):
        self.factor, self.level, self.note = factor, level, note
        self.start = date.fromisoformat(start)
        self.end = date.fromisoformat(end) if end else None
        if self.end and self.end < self.start:
            raise ValueError(f"regime {factor}={level}: end {end} is before start {start}")

    @property
    def name(self):
        return f"{self.factor}={self.level}"

    def active(self, d):
        return self.start <= d and (self.end is None or d <= self.end)


def load_regimes(path):
    if not path:
        return []
    with open(path) as f:
        rows = [r for r in csv.DictReader(f) if (r.get("factor") or "").strip()]
    regs = [Regime(r["factor"].strip(), r["level"].strip(), r["start"].strip(),
                   (r.get("end") or "").strip(), (r.get("note") or "").strip()) for r in rows]
    # Several rows may share a name (e.g. two separate trips to altitude): one indicator, OR'ed.
    return regs


def indicators(regs):
    """OrderedDict name -> fn(date) -> 0/1, merging rows that share a factor=level name."""
    by = OrderedDict()
    for g in regs:
        by.setdefault(g.name, []).append(g)
    return OrderedDict((n, (lambda gs: (lambda d: int(any(g.active(d) for g in gs))))(gs))
                       for n, gs in by.items())


def factor_levels(regs):
    by = OrderedDict()
    for g in regs:
        by.setdefault(g.factor, [])
        if g.level not in by[g.factor]:
            by[g.factor].append(g.level)
    return by


def condition(d, regs):
    """Label of the combination of regimes active on date d, e.g. 'skates=new, altitude=high'."""
    parts = []
    for factor in factor_levels(regs):
        lv = [g.level for g in regs if g.factor == factor and g.active(d)]
        parts.append(f"{factor}={lv[0]}" if lv else f"{factor}=baseline")
    return ", ".join(parts) if parts else "all"


def ols(X, y, w=None):
    """Weighted least squares. Returns (coef, stderr, dof, rss)."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    sw = np.sqrt(w)
    Xw, yw = X * sw[:, None], y * sw
    b, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
    res = yw - Xw @ b
    dof = len(y) - X.shape[1]
    rss = float(res @ res)
    if dof <= 0:
        return b, np.full(len(b), float("nan")), dof, rss
    cov = rss / dof * np.linalg.pinv(Xw.T @ Xw)
    return b, np.sqrt(np.diag(cov)), dof, rss


def t_pvalue(t, dof):
    """Two-sided p-value of a Student-t statistic (no scipy needed)."""
    if dof <= 0 or not math.isfinite(t):
        return float("nan")
    x = dof / (dof + t * t)
    a, b = dof / 2.0, 0.5

    def cf(a, b, x):  # continued fraction for the incomplete beta function
        qab, qap, qam = a + b, a + 1, a - 1
        c, d = 1.0, 1 - qab * x / qap
        d = 1 / d if abs(d) > 1e-300 else 1e300
        h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1 + aa * d; c = 1 + aa / c; d = 1 / d; h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1 + aa * d; c = 1 + aa / c; d = 1 / d; delta = d * c; h *= delta
            if abs(delta - 1) < 1e-12:
                break
        return h

    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * cf(a, b, x) / a
    return 1 - math.exp(lbt) * cf(b, a, 1 - x) / b


def learning_x(rows):
    """log(1 + days since first session): practice gains that are fast early and then slow down."""
    d0 = min(r["d"] for r in rows)
    return [math.log1p((r["d"] - d0).days) for r in rows]


def weeks_x(rows):
    d0 = min(r["d"] for r in rows)
    return [(r["d"] - d0).days / 7 for r in rows]
