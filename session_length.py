"""session_length.py — how much a session's length should count when trending HR cost of speed.

`hr_above_rest_per_kmh` is a ratio of means over a session's rolling samples. A short session gives
the same metric as a long one, only noisier: measured on the author's sessions (validate_session_length.py),
a piece cut from a long session lands within a few percent of the whole session's value on average,
with a spread that shrinks as the piece gets longer. So short sessions are not excluded and not
corrected; they get a standard error, and trend_models.py weights by it.

The noise model is relative, in log space:

    sd(log metric) = sqrt(a / L + b)        L = rolling minutes

  a  noise that averages out with time (pace changes, HR not yet settled, sensor jitter)
  b  floor that does not: a session is one day's conditions, however long it lasts

`hr_above_rest_per_kmh_se` = metric * sd. Refit a and b on your own files with
validate_session_length.py and pass them to process_fit.py (--se-a, --se-b).
"""
import math

try:
    import numpy as np
except ImportError:  # pragma: no cover
    raise SystemExit("pip install numpy")

MOVING_MS = 0.3        # m/s, same threshold as process_fit.moving_stats
MAX_GAP_S = 10         # same pause rule as process_fit.moving_stats
MIN_SAMPLES = 30

# Fitted on the author's 65 inline-skating sessions by validate_session_length.py.
DEFAULT_A = 0.107
DEFAULT_B = 0.0072


def rel_sd(minutes, a=DEFAULT_A, b=DEFAULT_B):
    """Relative standard error of the metric for a session of this many rolling minutes."""
    if not minutes or minutes <= 0:
        return None
    return math.sqrt(a / minutes + b)


def metric_se(value, minutes, a=DEFAULT_A, b=DEFAULT_B):
    sd = rel_sd(minutes, a, b)
    return round(value * sd, 3) if (value is not None and sd is not None) else None


class Series:
    """One session's rolling samples, from fitparse record dicts (as process_fit.process returns them)."""

    def __init__(self, records, hrrest):
        recs = [r for r in records if r.get("timestamp") is not None]
        t0 = recs[0]["timestamp"] if recs else None
        t = np.array([(r["timestamp"] - t0).total_seconds() for r in recs], float)
        spd = [r.get("enhanced_speed") if r.get("enhanced_speed") is not None else r.get("speed") for r in recs]
        self.v = np.array([(s or 0.0) * 3.6 for s in spd], float)
        self.y = np.array([r["heart_rate"] - hrrest if r.get("heart_rate") is not None else np.nan
                           for r in recs], float)
        dt = np.diff(t, prepend=t[:1])
        moving = self.v > MOVING_MS * 3.6
        self.minutes = np.cumsum(np.where(moving & (dt > 0) & (dt <= MAX_GAP_S), dt, 0.0)) / 60
        self.use = moving & np.isfinite(self.y)

    @property
    def rolling_min(self):
        return float(self.minutes[-1]) if len(self.minutes) else 0.0

    def window(self, lo_min, hi_min):
        """Usable samples whose rolling time falls in [lo_min, hi_min)."""
        return self.use & (self.minutes >= lo_min) & (self.minutes < hi_min)

    def ratio(self, mask=None):
        """hr_above_rest_per_kmh over these samples (all rolling samples by default)."""
        mask = self.use if mask is None else mask
        if mask.sum() < MIN_SAMPLES:
            return None
        v = float(self.v[mask].mean())
        return float(self.y[mask].mean()) / v if v > 0 else None


def robust_sd(xs):
    xs = np.asarray(xs, float)
    return float((np.percentile(xs, 75) - np.percentile(xs, 25)) / 1.349)


def fit_noise(pieces):
    """Fit sd^2 = a/L + b to {L: [log(piece / whole), ...]}; returns (a, b), both clipped at 0."""
    Ls = sorted(L for L, d in pieces.items() if len(d) >= 5)
    if len(Ls) < 2:
        return DEFAULT_A, DEFAULT_B
    X = np.array([[1.0 / L, 1.0] for L in Ls])
    v = np.array([robust_sd(pieces[L]) ** 2 for L in Ls])
    w = np.sqrt([len(pieces[L]) for L in Ls])
    (a, b), *_ = np.linalg.lstsq(X * w[:, None], v * w, rcond=None)
    if b < 0:
        b, a = 0.0, float(np.sum(w * w * v / Ls) / np.sum(w * w / np.square(Ls)))
    return max(float(a), 0.0), max(float(b), 0.0)
