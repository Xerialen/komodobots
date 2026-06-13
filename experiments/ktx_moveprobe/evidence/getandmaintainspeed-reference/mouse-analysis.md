# getandmaintainspeed.qwd mouse and speed analysis

## Summary

- Frames: `2541` paired command/state rows over `32.987s`.
- Speed: avg `666.1`, p50 `720.8`, p95 `924.4`, max `948.5` qu/s.
- Time above speed thresholds: 320 `30.156s`, 400 `29.74s`, 500 `25.779s`, 700 `18.507s`, 900 `6.377s`.

## Mouse Movement

- Yaw total travel: `4157.5` deg (`126.0` deg/s average absolute travel).
- Yaw rate: p50 `132.7` deg/s, p95 `244.8` deg/s, p99 `618.2` deg/s.
- Yaw reversals: `43` (`1.3` / s).
- Pitch range: `0.0`..`40.7` deg, total pitch travel `690.1` deg.
- Yaw-vs-velocity lead: mean `-36.3` deg; abs p50/p95 `37.0` / `132.7` deg.

## Inputs

- Forward values: `[-400, 0, 400]`.
- Side values: `[-400, 0, 400]`.
- Forward-only `1.1%`, side-only `84.8%`, both forward+side `3.4%`, no-move `10.8%`.
- Jump button `74.0%`.
- Side+mouse coupled frames: `1918`; same-sign `4.9%`, opposite-sign `95.1%`.

## Interpretation

This is not just speed. The demo maintains very high velocity while the mouse keeps moving in a controlled, repeated pattern. The important controller target is the relationship between yaw, pitch, side input, and velocity heading over time, not just the max-speed row.
