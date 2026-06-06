# Moveprobe Plausibility Summary

Gate: command coverage and movement plausibility, not speed alone.

Expected forward defaults to each run's `MOVEPROBE_FORWARDMOVE`, falling back to `800`.
For aim-independent probes with variable local forward values, set `--min-forward-ratio 0` and use `--min-horizontal-ratio` instead.

| Run | Map | Mode | Player | Gate | Cmds | Forward | Move | Side | Back | Jump | Yaws | Abs delta avg | Abs delta p90 | >90 | Avg | P95 | Stationary | Low | Air | Reasons |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `20260606T000331Z` | `frobodm2` | `5` | `/ bro` | PASS | `110` | 0.0% | 96.4% | 96.4% | 22.7% | 96.4% | `99` | `53.1` | `110.9` | 19.1% | `264.5` | `382.4` | 3.3% | 14.3% | 8.8% |  |
| `20260606T000331Z` | `frobodm2` | `5` | `/ goldenboy` | PASS | `86` | 1.2% | 98.8% | 98.8% | 14.0% | 98.8% | `83` | `44.2` | `91.8` | 10.5% | `316.7` | `389.1` | 0.5% | 4.0% | 15.0% |  |
| `20260606T000414Z` | `dm3` | `5` | `/ bro` | FAIL | `109` | 0.0% | 99.1% | 99.1% | 41.3% | 99.1% | `103` | `79.6` | `154.7` | 43.1% | `149.8` | `370.2` | 0.1% | 43.1% | 62.5% | low-speed 43.1% > 40.0% |
| `20260606T000414Z` | `dm3` | `5` | `/ goldenboy` | FAIL | `86` | 0.0% | 98.8% | 98.8% | 14.0% | 98.8% | `78` | `44.7` | `99.4` | 16.3% | `168.5` | `382.1` | 4.9% | 52.8% | 21.9% | low-speed 52.8% > 40.0% |
