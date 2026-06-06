# Moveprobe Plausibility Summary

Gate: command coverage and movement plausibility, not speed alone.

Expected forward defaults to each run's `MOVEPROBE_FORWARDMOVE`, falling back to `800`.
For aim-independent probes with variable local forward values, set `--min-forward-ratio 0` and use `--min-horizontal-ratio` instead.

| Run | Map | Mode | Player | Gate | Cmds | Forward | Move | Side | Back | Jump | Yaws | MaxF | MaxS | MaxMove | Abs delta avg | Abs delta p90 | >90 | Avg | P95 | Stationary | Low | Air | Cadence/min | Reasons |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `20260606T003718Z` | `dm3` | `7` | `/ bro` | PASS | `109` | 0.0% | 98.2% | 98.2% | 0.0% | 98.2% | `109` | `823` | `824` | `824.5` | `85.8` | `157.7` | 46.8% | `190.1` | `361.0` | 0.4% | 26.1% | 44.2% | `91.7` |  |
| `20260606T003718Z` | `dm3` | `7` | `/ goldenboy` | PASS | `86` | 0.0% | 94.2% | 94.2% | 0.0% | 94.2% | `82` | `824` | `824` | `824.5` | `77.8` | `157.5` | 40.7% | `248.2` | `375.3` | 2.5% | 18.9% | 24.8% | `43.3` |  |
| `20260606T003808Z` | `frobodm2` | `7` | `/ bro` | PASS | `110` | 0.0% | 99.1% | 99.1% | 0.0% | 99.1% | `105` | `824` | `824` | `824.5` | `59.9` | `135.5` | 30.9% | `322.0` | `386.2` | 0.1% | 5.5% | 12.7% | `16.3` |  |
| `20260606T003808Z` | `frobodm2` | `7` | `/ goldenboy` | PASS | `87` | 0.0% | 98.9% | 98.9% | 0.0% | 98.9% | `86` | `824` | `824` | `824.6` | `65.8` | `149.3` | 33.3% | `312.1` | `392.5` | 0.0% | 2.7% | 6.6% | `15.4` |  |
