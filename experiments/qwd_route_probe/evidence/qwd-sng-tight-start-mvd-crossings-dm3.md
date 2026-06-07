# QWD SNG MVD Crossing Diagnosis qwd-sng-tight-start-mvd-crossings-dm3

## Scope

- Run: `20260607T003837Z`
- Source result: `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-dm3.json`
- Source verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Start radius: `192.0` qu
- Point radius: `96.0` qu
- Use MVD position samples to derive first CP0 start-radius entry and sequential point-radius control-point entries, then compare those physical crossings with the first sampled QWD command row.

## Player Summary

| Player | Start entry | Sequential CPs | First sampled QWD | Nearest MVD at first QWD | Status |
|---|---:|---:|---|---|---|
| `/ bro` | 1761 ms / 83.482 qu | 11 | `t=1587ms cp=2 adv=2 dist=160.417` | `t=1577ms d_cp0=921.333 d_target=912.735` | `sampled_after_internal_advancement` |
| `/ goldenboy` | 7432 ms / 85.522 qu | 12 | `t=7248ms cp=2 adv=2 dist=167.498` | `t=7247ms d_cp0=924.485 d_target=910.064` | `sampled_after_internal_advancement` |

## Sequential MVD Entries

### / bro

| CP | Time | Distance | Transition s | Straight speed | Window p50 | Window low ratio |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1761 | 83.482 |  |  |  |  |
| 1 | 1781 | 95.218 | 0.02 | 300.52 | 300.52 | 0.0 |
| 2 | 2108 | 95.133 | 0.327 | 300.995 | 300.463 | 0.0 |
| 3 | 2998 | 92.225 | 0.89 | 216.927 | 282.981 | 0.0 |
| 4 | 3489 | 93.865 | 0.491 | 262.773 | 324.306 | 0.0 |
| 5 | 3871 | 94.569 | 0.382 | 289.046 | 329.323 | 0.0 |
| 6 | 4581 | 92.49 | 0.71 | 290.852 | 330.246 | 0.0 |
| 7 | 5175 | 95.421 | 0.594 | 252.29 | 301.623 | 0.0 |
| 8 | 10879 | 93.887 | 5.704 | 35.34 | 186.455 | 0.186 |
| 9 | 17834 | 95.617 | 6.955 | 28.742 | 183.231 | 0.221 |
| 10 | 18123 | 92.487 | 0.289 | 273.093 | 333.288 | 0.0 |

### / goldenboy

| CP | Time | Distance | Transition s | Straight speed | Window p50 | Window low ratio |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 7432 | 85.522 |  |  |  |  |
| 1 | 7473 | 91.731 | 0.041 | 303.319 | 303.605 | 0.0 |
| 2 | 7823 | 91.593 | 0.35 | 279.263 | 288.736 | 0.0 |
| 3 | 8770 | 92.57 | 0.947 | 195.127 | 283.601 | 0.087 |
| 4 | 9264 | 91.997 | 0.494 | 282.28 | 335.396 | 0.0 |
| 5 | 9612 | 89.78 | 0.348 | 340.733 | 350.13 | 0.0 |
| 6 | 15539 | 91.976 | 5.927 | 34.808 | 180.602 | 0.252 |
| 7 | 16209 | 93.878 | 0.67 | 195.086 | 247.882 | 0.061 |
| 8 | 16908 | 94.958 | 0.699 | 268.834 | 317.111 | 0.0 |
| 9 | 18041 | 93.468 | 1.133 | 212.006 | 263.465 | 0.018 |
| 10 | 18267 | 95.658 | 0.226 | 281.261 | 317.522 | 0.0 |
| 11 | 18720 | 93.983 | 0.453 | 171.381 | 196.036 | 0.0 |

## Interpretation

- MVD-derived crossings can prove physical traversal of QWD control-point geometry, but they do not by themselves prove internal mode-9 activation timing.
- If the first sampled QWD row is already after internal advancement, the remaining gap is event-level QWD activation/advance instrumentation, not another projection change.
- Movement-quality conclusions must still respect the source scorer guardrails; control-point count alone is not movement realism.

## Decision

- Verdict: `qwd_sng_mvd_crossing_progress_but_start_instrumentation_needed`
- Reason: MVD position samples independently show tight CP0 approach and sequential point-radius traversal, but the first sampled QWD command rows are already after internal advancement. This preserves the start-proof uncertainty while narrowing it to instrumentation/timing correlation rather than route geometry.
- Next goal: Add event-level QWD activation/advance logging or unsampled advancement rows, then rescore active-window movement quality before changing projection policy or trying other DM3 QWD moves.
