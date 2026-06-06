# Moveprobe Plausibility Summary

Gate: command coverage and movement plausibility, not speed alone.

Expected forward defaults to each run's `MOVEPROBE_FORWARDMOVE`, falling back to `800`.
For aim-independent probes with variable local forward values, set `--min-forward-ratio 0` and use `--min-horizontal-ratio` instead.

| Run | Map | Mode | Player | Gate | Cmds | Forward | Move | Side | Back | Jump | Yaws | Abs delta avg | Abs delta p90 | >90 | Avg | P95 | Stationary | Low | Air | Reasons |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `20260606T001705Z` | `dm3` | `6` | `/ bro` | PASS | `110` | 0.9% | 93.6% | 93.6% | 0.0% | 93.6% | `107` | `82.2` | `163.1` | 43.6% | `167.4` | `362.9` | 3.1% | 38.3% | 47.8% |  |
| `20260606T001705Z` | `dm3` | `6` | `/ goldenboy` | PASS | `86` | 0.0% | 88.4% | 87.2% | 0.0% | 88.4% | `83` | `66.3` | `124.2` | 40.7% | `236.0` | `382.4` | 1.8% | 24.4% | 40.9% |  |
| `20260606T001825Z` | `frobodm2` | `6` | `/ bro` | PASS | `110` | 0.0% | 94.5% | 94.5% | 0.0% | 94.5% | `102` | `84.3` | `167.1` | 50.0% | `246.3` | `361.0` | 1.7% | 13.8% | 13.7% |  |
| `20260606T001825Z` | `frobodm2` | `6` | `/ goldenboy` | PASS | `87` | 0.0% | 85.1% | 85.1% | 0.0% | 85.1% | `83` | `85.8` | `163.2` | 51.7% | `217.3` | `374.6` | 3.6% | 26.8% | 28.9% |  |
