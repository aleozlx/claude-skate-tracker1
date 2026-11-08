# skate-tracker

De-identified progression tracking for inline skating sessions recorded on Garmin.

Ingests Garmin FIT files and maintains a **privacy-safe** CSV of per-session
aggregates plus a headline skill metric: the **heart-rate / speed decoupling**.
Early on, balance and adrenaline pin HR into Zone 4–5 even at walking pace.
As technique automates, the same speed costs fewer beats — so a rising
`efficiency_index` (moving speed per heartbeat above rest) tracks skill more
honestly than raw speed does.

## ⚠️ Privacy — read before making this public

Garmin FIT files embed **GPS coordinates, your name, body metrics, device
serials, and sleep schedule**. Never commit raw `.fit`/`.zip` to a public repo.
`.gitignore` blocks them by default. Everything written to `data/` (except
`*_route.csv`) is de-identified and safe to publish:

- **`sessions.csv`** — aggregates only. No GPS, no name, no serials.
- **`*_series.csv`** — per-session time series with **GPS stripped**.
- **`*_route.csv`** — opt-in (`--with-gps`), origin-translated so shape is kept
  but absolute location is destroyed. Still gitignored; treat as sensitive.

### Pre-push privacy guard (recommended)

`.gitignore` is the first line of defense; a versioned `hooks/pre-push` script
is the second. It refuses to push if any outgoing commit contains a raw
`.fit`/`.zip`, a `*_route.csv`, or un-stripped GPS/device fields
(`position_lat`, `latitude`, `serial_number`, …). Git never auto-enables hooks
from a clone, so activate it once per clone:

```bash
git config core.hooksPath hooks
```

Emergency bypass (think twice): `git push --no-verify`.

## Usage

```bash
pip install -r requirements.txt

# One-time: enable the pre-push privacy guard for this clone.
git config core.hooksPath hooks

# Drop Garmin "Export Original" zips (or .fit) into raw/ (gitignored), then:
python process_fit.py raw/*.zip --series

# Tune HR calc to your physiology (defaults: hrmax 190, resting 59):
python process_fit.py raw/*.zip --series --hrmax 188 --hrrest 55

# Plot progression once you have a few sessions:
python plot_progression.py

# Separate practice from conditions (new skates, altitude, venue); see below:
python trend_models.py --regimes /private/path/regimes.csv
python plot_progression.py --regimes /private/path/regimes.csv --color-by skates
```

Re-running is idempotent: sessions are keyed by ID, so re-processing updates
rather than duplicates. Columns you add to `sessions.csv` by hand are kept.
The session ID is the Garmin activity ID wherever it appears in the filename
(`<id>.zip`, `<id>_ACTIVITY.fit`, `…-inline_skating-<id>.fit`).

## Practice vs conditions

The efficiency metrics improve with practice, and they also move when
conditions change. Since each condition usually covers one unbroken stretch of
dates, comparing condition averages mixes the two up. `trend_models.py` fits a
practice trend (straight line, and a log learning curve that is fast early and
slows later) plus one step per condition, and reports each step as "better or
worse than baseline once practice is accounted for", with standard errors.

Conditions come from a **regimes file**: `factor,level,start,end,note` rows,
inclusive dates, empty `end` = still true. `regimes.example.csv` shows the
format with made-up dates.

> **Keep your real regimes file outside this repo.** It records where you were
> and when. `regimes.csv` is gitignored and the pre-push hook refuses it, and the
> regime figure (`data/ratio_trend.png`, which draws those dates) is gitignored
> too.

## Metrics in sessions.csv

| column | meaning |
|---|---|
| `distance_km`, `active_min`, `elapsed_min`, `moving_pct` | volume; `moving_pct` low = lots of drilling/stopping |
| `avg_moving_speed_kmh` | speed while actually rolling (excludes stops) |
| `avg_hr`, `z1..z5_pct` | cardiovascular load + zone distribution |
| `efficiency_index` | `avg_moving_speed / (avg_hr − resting)` — **↑ = more efficient** |
| `aerobic_te`, `anaerobic_te` | Garmin training-effect scores |
| `date_local` | start date in the watch's local time (`date` is UTC, so evening sessions can land on the next day) |
| `sport_name` | sport profile name recorded on the watch; check it if an activity was mis-tagged |
| `moving_min`, `median_moving_speed_kmh` | rolling time (pauses over 10 s excluded) and its median speed |
| `moving_hr` | mean HR over rolling samples only; stops are recovery, not effort |
| `hr_above_rest_per_kmh` | `(moving_hr − resting) / avg_moving_speed` — **↓ = more efficient**; the metric `trend_models.py` uses |

## What Garmin does NOT capture for skating

No stroke cadence, no push power, no stride mechanics — there's no skating
dynamics sensor, so those FIT fields stay empty. This is a speed/HR/route log,
not a technique analyzer. The efficiency proxy is the workaround.
