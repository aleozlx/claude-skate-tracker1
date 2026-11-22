"""Tests for the session-length noise model and the inverse-variance trend weights (synthetic data only).

    python -m pytest test_session_length.py      # or: python test_session_length.py
"""
import csv, math, os, tempfile
from datetime import datetime, timedelta

import numpy as np

import process_fit
import session_length as sl
import trend_models
from skate_analysis import between_variance, load_sessions


def records(minutes, speed_ms=2.5, hr=140, step_s=2, pause_at=None, pause_s=60):
    """Steady synthetic session; optional auto-pause gap (no records) at `pause_at` minutes."""
    t0, out = datetime(2026, 1, 1, 12), []
    for i in range(int(minutes * 60 / step_s) + 1):
        rolled = i * step_s
        t = rolled + (pause_s if pause_at is not None and rolled >= pause_at * 60 else 0)
        out.append({"timestamp": t0 + timedelta(seconds=t), "enhanced_speed": speed_ms, "heart_rate": hr})
    return out


def test_rel_sd_shrinks_with_length_to_floor():
    sds = [sl.rel_sd(L) for L in (3, 7, 15, 30, 90, 600)]
    assert all(x > y for x, y in zip(sds, sds[1:]))
    assert sds[-1] > math.sqrt(sl.DEFAULT_B) and abs(sds[-1] - math.sqrt(sl.DEFAULT_B)) < 0.01
    assert sl.rel_sd(0) is None and sl.metric_se(None, 30) is None
    assert sl.metric_se(12.0, 30) == round(12.0 * sl.rel_sd(30), 3)


def test_series_matches_metric_definition_and_skips_pauses():
    s = sl.Series(records(20, speed_ms=2.5, hr=140, pause_at=10, pause_s=120), hrrest=55)
    assert abs(s.rolling_min - 20) < 0.1                    # the 2-minute gap is not rolling time
    assert abs(s.ratio() - (140 - 55) / 9.0) < 1e-9          # 2.5 m/s = 9 km/h
    w = s.window(0, 5)
    assert abs(s.minutes[w].max() - 5) < 0.1 and s.ratio(w) is not None
    assert s.ratio(s.window(0, 0.5)) is None                 # too few samples


def test_fit_noise_recovers_parameters():
    rng = np.random.default_rng(1)
    a, b = 0.1, 0.008
    pieces = {L: list(rng.normal(0, math.sqrt(a / L + b), 400)) for L in (3, 5, 7, 10, 15, 20, 30)}
    fa, fb = sl.fit_noise(pieces)
    assert abs(fa - a) < 0.03 and abs(fb - b) < 0.004


def test_between_variance_zero_when_errors_explain_scatter():
    rng = np.random.default_rng(2)
    se = rng.uniform(0.5, 3, 200)
    y = 10 + rng.normal(0, se)
    _, s2 = between_variance(np.ones((200, 1)), y, se)
    assert s2 < 0.3


def test_between_variance_recovers_extra_scatter():
    rng = np.random.default_rng(3)
    se = rng.uniform(0.5, 3, 400)
    y = 10 + rng.normal(0, se) + rng.normal(0, 2.0, 400)
    w, s2 = between_variance(np.ones((400, 1)), y, se)
    assert abs(math.sqrt(s2) - 2.0) < 0.4
    assert np.allclose(w, 1 / (se ** 2 + s2))


def test_process_fit_whitelists_the_se_column():
    assert "hr_above_rest_per_kmh_se" in process_fit.AGG_COLUMNS


def test_trend_models_short_noisy_sessions_count_less():
    """True trend -0.5/week. A few short sessions read far too low; IV weights must resist them."""
    rng = np.random.default_rng(4)
    rows, d0 = [], datetime(2026, 1, 1)
    for i in range(60):
        mins = 7 if i % 6 == 0 else 60
        week = i / 4
        y = 14 - 0.5 * week + rng.normal(0, 0.3)
        if mins == 7:
            y -= 4 if i > 30 else -4                         # short-session outliers, tilting the slope
        rows.append({"session_id": str(i), "date_local": (d0 + timedelta(days=7 * week)).strftime("%Y-%m-%d"),
                     "distance_km": "5", "moving_min": str(mins), "hr_above_rest_per_kmh": f"{y:.3f}",
                     "hr_above_rest_per_kmh_se": f"{sl.metric_se(y, mins):.3f}"})
    path = os.path.join(tempfile.mkdtemp(), "s.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    loaded = load_sessions(path)
    assert all(r["se"] for r in loaded)
    from skate_analysis import weeks_x
    slopes = {}
    for mode in (None, "iv"):
        lines, _, _, _ = trend_models.fit(loaded, [("t", weeks_x(loaded))], mode)
        slopes[mode] = float(lines[0].split()[1])
    assert abs(slopes["iv"] + 0.5) < abs(slopes[None] + 0.5)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
