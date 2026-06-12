# ztricks Distance Reference Trace

- Schema: `komodobots.ztricks_reference_trace.v1`
- Demo: `getspeed.qwd`
- SHA-256: `dfb893a32d24b0aec5a5a94a94b16cee9cd42dcdd6602c6a093c5f21e9988307`
- Attempt: `11`
- Rows: `1807` to `1969`
- Samples: `163`
- Controller curve: `local_quadratic_lagrange_by_time` step `0.01`s

| event | row | t | x | y | z | vh | vel yaw | view yaw | target err | yaw lead | d_lip | buttons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `attempt_start` | `1807` | 0.000 | -3516.1 | 3712.0 | -453.1 | 300.0 | 0.0 | 3.0 | 5.9 | 3.0 | 168.1 | 2 |
| `first_grounded` | `1830` | 0.298 | -3434.4 | 3686.9 | -488.0 | 310.9 | -33.6 | 78.4 | 44.3 | 112.0 | 86.4 | 0 |
| `terminal_sweep_start` | `1904` | 1.259 | -3439.4 | 3758.1 | -488.0 | 441.4 | 41.4 | 39.1 | -41.1 | -2.3 | 91.4 | 0 |
| `speed_floor_crossed` | `1908` | 1.311 | -3419.9 | 3770.6 | -488.0 | 450.8 | 27.5 | 23.8 | -29.0 | -3.7 | 71.9 | 0 |
| `aligned_near_target_line` | `1916` | 1.415 | -3373.0 | 3779.2 | -488.0 | 472.8 | -3.3 | -11.4 | 0.0 | -8.1 | 25.0 | 0 |
| `release_jump` | `1918` | 1.441 | -3360.8 | 3777.2 | -488.0 | 475.2 | -11.3 | -19.0 | 8.3 | -7.7 | 12.8 | 2 |
| `physical_lip_x_crossing` | `1920..1921` | 1.468 | -3348.0 | 3774.6 | -481.0 | 475.2 | -11.3 | -24.6 | 8.6 | -13.3 | 0.0 | 2 |
| `landing` | `1969` | 2.103 | -3044.1 | 3760.5 | -488.0 | 495.5 | 2.7 | 1.0 | -2.7 | -1.7 | -303.9 | 0 |

Interpolation notes:

- View yaw, velocity yaw, target yaw, yaw lead, and target error are unwrapped before interpolation.
- `physical_lip_x_crossing` is estimated between adjacent rows at `x=-3348.0`.
- Controller guidance samples use local quadratic interpolation over the successful attempt only.
- Event proof stays piecewise-linear/projection based to avoid spline overshoot in evidence.
- Rows flagged as A5 dropped-state interpolations remain marked in JSON as `reference_state_interpolated`.
