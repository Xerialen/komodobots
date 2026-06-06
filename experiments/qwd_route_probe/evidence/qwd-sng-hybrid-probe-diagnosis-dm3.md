# QWD SNG Probe Diagnosis qwd-sng-repair-diagnosis-dm3

## Scope

- Run: `20260606T221429Z`
- Source result: `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-result-dm3.json`
- Source verdict: `qwd_sng_hybrid_probe_inconclusive`
- Server start time: `4.267595` s
- Match duration: `45816` ms

## Player Diagnosis

| Player | Class | MVD window | MVD reached | Active rows | Active in MVD | Active MVD range | Min cp0 from qwd | Min any qwd | Max advanced |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| `/ bro` | `spawn_or_route_context_missed_start_radius` | `0-45816` | 0 | 0 | 0 | `None-None` | 282.748 | 282.748 | 0 |
| `/ goldenboy` | `qwd_activation_after_mvd_window` | `6264-45816` | 0 | 11 | 0 | `47044-48082` | 282.748 | 97.576 | 2 |

## Closest MVD Approaches

### / bro

| CP | Min distance | Time | Origin |
|---:|---:|---:|---|
| 0 | 281.954 | 0 | `[192.0, -208.0, -175.0]` |
| 1 | 260.137 | 0 | `[192.0, -208.0, -175.0]` |
| 2 | 262.723 | 14151 | `[210.75, -116.25, -176.0]` |
| 3 | 270.816 | 14338 | `[264.375, -55.5, -176.0]` |
| 4 | 331.836 | 14523 | `[342.875, -36.75, -176.875]` |
| 5 | 352.99 | 15489 | `[665.125, 85.875, -186.0]` |

### / goldenboy

| CP | Min distance | Time | Origin |
|---:|---:|---:|---|
| 0 | 282.774 | 41871 | `[192.0, -208.0, -176.0]` |
| 1 | 261.025 | 41871 | `[192.0, -208.0, -176.0]` |
| 2 | 273.481 | 41871 | `[192.0, -208.0, -176.0]` |
| 3 | 349.516 | 42132 | `[182.75, -206.625, -176.0]` |
| 4 | 481.333 | 41871 | `[192.0, -208.0, -176.0]` |
| 5 | 564.144 | 41871 | `[192.0, -208.0, -176.0]` |

## Interpretation

- This is an offline diagnosis of the already-generated mode-9 run; it does not rerun KTX or change controller behavior.
- Command rows use server time, while MVD position rows use demo-relative time. The diagnosis aligns command rows by subtracting the demo start ServerTime from events kind 0.
- At least one bot activated the QWD probe only after the parsed MVD movement window, so the current run's control-point advancement is command evidence but not clean movement evidence.
- At least one bot never reached the configured start radius during the MVD window, pointing at spawn/context setup before controller-policy expansion.

## Decision

- Verdict: `qwd_sng_repair_needs_timing_and_start_context`
- Reason: The first SNG run is still useful, but its activation/advancement evidence is not aligned with the parsed MVD movement window and one bot missed the start radius entirely.
- Next goal: Before rerunning live KTX, repair mode-9 setup so QWD activation overlaps recorded MVD movement evidence; then decide whether the control-point radius, start context, or projection policy needs the smallest change.
