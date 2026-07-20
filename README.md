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
```

Re-running is idempotent: sessions are keyed by ID, so re-processing updates
rather than duplicates.

## Metrics in sessions.csv

| column | meaning |
|---|---|
| `distance_km`, `active_min`, `elapsed_min`, `moving_pct` | volume; `moving_pct` low = lots of drilling/stopping |
| `avg_moving_speed_kmh` | speed while actually rolling (excludes stops) |
| `avg_hr`, `z1..z5_pct` | cardiovascular load + zone distribution |
| `efficiency_index` | `avg_moving_speed / (avg_hr − resting)` — **↑ = more efficient** |
| `aerobic_te`, `anaerobic_te` | Garmin training-effect scores |

## What Garmin does NOT capture for skating

No stroke cadence, no push power, no stride mechanics — there's no skating
dynamics sensor, so those FIT fields stay empty. This is a speed/HR/route log,
not a technique analyzer. The efficiency proxy is the workaround.
