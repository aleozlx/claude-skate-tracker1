#!/usr/bin/env python3
"""
process_fit.py — ingest Garmin FIT skating sessions into a privacy-safe CSV.

Design goal: everything written under data/ is safe to publish in a PUBLIC repo.
That means NO GPS, NO name, NO device serials, NO sleep schedule. Only
de-identified performance aggregates + a GPS-stripped per-session time series.

Usage:
    python process_fit.py raw/*.fit                 # append aggregates to data/sessions.csv
    python process_fit.py raw/123.fit --series      # also write data/123_series.csv (no GPS)
    python process_fit.py raw/123.fit --with-gps    # LOCAL-ONLY route, origin-translated (gitignored)

HRmax / resting HR drive zone + efficiency calcs; override if you know yours:
    python process_fit.py raw/*.fit --hrmax 190 --hrrest 59
"""
import argparse, csv, glob, os, re, statistics, sys, zipfile, tempfile
from datetime import datetime, timedelta

try:
    import fitparse
except ImportError:
    sys.exit("pip install fitparse")

SC = 180 / 2**31  # semicircles -> degrees

# Fields we NEVER emit to the public CSV (defense-in-depth allow-list below is the real guard).
AGG_COLUMNS = [
    "session_id", "date", "sport",
    "distance_km", "active_min", "elapsed_min", "moving_pct",
    "avg_speed_kmh", "max_speed_kmh", "avg_moving_speed_kmh",
    "avg_hr", "max_hr", "min_hr",
    "z1_pct", "z2_pct", "z3_pct", "z4_pct", "z5_pct",
    "calories", "cycles", "ascent_m", "descent_m",
    "aerobic_te", "anaerobic_te",
    "efficiency_index",  # avg_moving_speed / (avg_hr - resting) — rises as you get efficient
    # Added later; appended so older CSVs keep their column order.
    "date_local",              # start date in the watch's local time (`date` above is UTC)
    "sport_name",              # the sport profile name recorded on the device, e.g. "Inline Skating"
    "moving_min",              # time spent rolling (speed > 0.3 m/s), pauses > 10 s excluded
    "median_moving_speed_kmh",
    "moving_hr",               # mean HR over rolling samples only (stops are recovery, not effort)
    "hr_above_rest_per_kmh",   # (moving_hr - resting) / avg_moving_speed — ↓ = more efficient
]

MOVING_MS = 0.3       # m/s; below this the skater is standing
MAX_GAP_S = 10        # record gaps longer than this are pauses, not rolling time
FIT_EPOCH = datetime(1989, 12, 31)

def _extract_fit_path(path):
    """Accept a .fit, or a Garmin 'Export Original' .zip containing one .fit."""
    if path.lower().endswith(".zip"):
        z = zipfile.ZipFile(path)
        fit = next(n for n in z.namelist() if n.lower().endswith(".fit"))
        tmp = os.path.join(tempfile.gettempdir(), os.path.basename(fit))
        with open(tmp, "wb") as f:
            f.write(z.read(fit))
        return tmp
    return path

def session_id_from_path(path):
    """Garmin activity ID from the filename.

    Handles '<id>.zip', '<id>_ACTIVITY.fit' (Export Original / API download) and names that carry
    the ID after other tokens, like '20250301T1500Z-inline_skating-<id>.fit'. Falls back to the stem.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    lead = re.match(r"(\d+)(?:_|$)", stem)
    if lead:
        return lead.group(1)
    runs = re.findall(r"\d{9,}", stem)
    return runs[-1] if runs else stem

def _as_datetime(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return FIT_EPOCH + timedelta(seconds=v)
    return None

def local_offset(fit):
    """Watch's UTC offset, from the activity message's local_timestamp vs timestamp."""
    for m in fit.get_messages("activity"):
        ts, local = _as_datetime(m.get_value("timestamp")), _as_datetime(m.get_value("local_timestamp"))
        if ts and local:
            return local - ts
    return None

def moving_stats(records):
    """Rolling-only time, median speed and mean HR."""
    spd, hr, sec, prev = [], [], 0.0, None
    for r in records:
        ts = r.get("timestamp")
        s = r.get("enhanced_speed") if r.get("enhanced_speed") is not None else r.get("speed")
        if s is not None and s > MOVING_MS:
            spd.append(s * 3.6)
            if r.get("heart_rate") is not None:
                hr.append(r["heart_rate"])
            if prev is not None and ts is not None:
                dt = (ts - prev).total_seconds()
                if 0 < dt <= MAX_GAP_S:
                    sec += dt
        if ts is not None:
            prev = ts
    return (round(sec / 60, 1),
            round(statistics.median(spd), 2) if spd else None,
            round(statistics.mean(hr), 1) if hr else None)

def _first(msgs, field):
    for m in msgs:
        v = m.get_value(field)
        if v is not None:
            return v
    return None

def process(path, hrmax, hrrest):
    fit = fitparse.FitFile(_extract_fit_path(path))
    session = list(fit.get_messages("session"))
    records = [{d.name: d.value for d in m} for m in fit.get_messages("record")]

    def sess(field):
        return _first(session, field)

    spd = [r.get("enhanced_speed") or r.get("speed") for r in records]
    spd = [s for s in spd if s is not None]
    hr  = [r.get("heart_rate") for r in records if r.get("heart_rate") is not None]

    moving = [s for s in spd if s > 0.3]
    def kmh(x): return round(x * 3.6, 3)

    # HR zones by fraction of hrmax
    z = [0] * 6
    for h in hr:
        p = h / hrmax
        idx = 1 if p < .6 else 2 if p < .7 else 3 if p < .8 else 4 if p < .9 else 5
        z[idx] += 1
    zpct = [round(100 * z[i] / len(hr), 1) if hr else 0 for i in range(6)]

    avg_hr = round(sum(hr) / len(hr)) if hr else None
    avg_mv = sum(moving) / len(moving) if moving else 0
    eff = round(kmh(avg_mv) / (avg_hr - hrrest), 4) if (avg_hr and avg_hr > hrrest) else None

    sport_msgs = list(fit.get_messages("sport"))
    offset = local_offset(fit)
    mv_min, med_mv, mv_hr = moving_stats(records)
    avg_mv_kmh = kmh(avg_mv)

    start = sess("start_time")
    start_local = start + offset if (start and offset is not None) else start
    row = {
        "session_id": session_id_from_path(path),
        "date": start.strftime("%Y-%m-%d") if start else "",
        "sport": sess("sport"),
        "distance_km": round((sess("total_distance") or 0) / 1000, 3),
        "active_min": round((sess("total_timer_time") or 0) / 60, 1),
        "elapsed_min": round((sess("total_elapsed_time") or 0) / 60, 1),
        "moving_pct": round(100 * len(moving) / len(spd), 1) if spd else 0,
        "avg_speed_kmh": kmh(sess("enhanced_avg_speed") or 0),
        "max_speed_kmh": kmh(sess("enhanced_max_speed") or 0),
        "avg_moving_speed_kmh": kmh(avg_mv),
        "avg_hr": avg_hr, "max_hr": max(hr) if hr else None, "min_hr": min(hr) if hr else None,
        "z1_pct": zpct[1], "z2_pct": zpct[2], "z3_pct": zpct[3], "z4_pct": zpct[4], "z5_pct": zpct[5],
        "calories": sess("total_calories"), "cycles": sess("total_cycles"),
        "ascent_m": sess("total_ascent"), "descent_m": sess("total_descent"),
        "aerobic_te": sess("total_training_effect"), "anaerobic_te": sess("total_anaerobic_training_effect"),
        "efficiency_index": eff,
        "date_local": start_local.strftime("%Y-%m-%d") if start_local else "",
        "sport_name": _first(sport_msgs, "name"),
        "moving_min": mv_min,
        "median_moving_speed_kmh": med_mv,
        "moving_hr": mv_hr,
        "hr_above_rest_per_kmh": round((mv_hr - hrrest) / avg_mv_kmh, 2) if (mv_hr and avg_mv_kmh > 0) else None,
    }
    # Hard guard: only whitelisted keys leave this function for the public CSV.
    return {k: row.get(k) for k in AGG_COLUMNS}, records

def write_series(records, out):
    """Per-second-ish time series, GPS STRIPPED. Safe to publish."""
    t0 = records[0]["timestamp"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["elapsed_s", "speed_kmh", "hr", "altitude_m", "distance_m"])
        for r in records:
            if r.get("timestamp") is None:
                continue
            spd = r.get("enhanced_speed") or r.get("speed")
            w.writerow([
                round((r["timestamp"] - t0).total_seconds(), 1),
                round(spd * 3.6, 3) if spd is not None else "",
                r.get("heart_rate", ""),
                round(r["enhanced_altitude"], 1) if r.get("enhanced_altitude") is not None else "",
                round(r["distance"], 1) if r.get("distance") is not None else "",
            ])

def write_route_local(records, out):
    """Origin-translated route: preserves SHAPE, destroys absolute location.
    Still gitignored by default — treat as sensitive."""
    lat = [r.get("position_lat") for r in records if r.get("position_lat")]
    lon = [r.get("position_long") for r in records if r.get("position_long")]
    if not lat:
        print("  (no GPS in file, skipping route)"); return
    lat0, lon0 = lat[0], lon[0]
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["d_north_m", "d_east_m"])
        for r in records:
            if not r.get("position_lat"):
                continue
            dlat = (r["position_lat"] - lat0) * SC
            dlon = (r["position_long"] - lon0) * SC
            # rough local meters
            w.writerow([round(dlat * 111_320, 2), round(dlon * 111_320 * 0.795, 2)])
    print(f"  route (origin-translated, LOCAL ONLY) -> {out}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--csv", default="data/sessions.csv")
    ap.add_argument("--series", action="store_true", help="also write GPS-stripped per-session series")
    ap.add_argument("--with-gps", action="store_true", help="LOCAL-ONLY origin-translated route (gitignored)")
    ap.add_argument("--hrmax", type=int, default=190)
    ap.add_argument("--hrrest", type=int, default=59)
    a = ap.parse_args()

    paths = [p for pat in a.files for p in glob.glob(pat)]
    if not paths:
        sys.exit("no files matched")

    os.makedirs(os.path.dirname(a.csv), exist_ok=True)
    existing, extra_cols = {}, []
    if os.path.exists(a.csv):
        with open(a.csv) as f:
            reader = csv.DictReader(f)
            # Columns someone added to the CSV by hand are kept, not dropped and not a crash.
            extra_cols = [c for c in (reader.fieldnames or []) if c not in AGG_COLUMNS]
            for r in reader:
                existing[r["session_id"]] = r
    if extra_cols:
        print(f"keeping {len(extra_cols)} extra column(s) already in {a.csv}: {', '.join(extra_cols)}")

    for p in sorted(paths):
        row, records = process(p, a.hrmax, a.hrrest)
        prior = existing.get(row["session_id"], {})
        existing[row["session_id"]] = {**{c: prior.get(c, "") for c in extra_cols}, **row}
        print(f"{row['session_id']}: {row['distance_km']} km, {row['active_min']} min active, "
              f"avgHR {row['avg_hr']}, eff {row['efficiency_index']}")
        if a.series:
            write_series(records, f"data/{row['session_id']}_series.csv")
        if a.with_gps:
            write_route_local(records, f"data/{row['session_id']}_route.csv")

    rows = sorted(existing.values(),
                  key=lambda r: (r.get("date_local") or r.get("date") or "", r.get("session_id")))
    with open(a.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=AGG_COLUMNS + extra_cols, restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} sessions -> {a.csv}")

if __name__ == "__main__":
    main()
