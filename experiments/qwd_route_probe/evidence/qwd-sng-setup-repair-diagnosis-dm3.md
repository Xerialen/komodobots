# QWD SNG Probe Diagnosis qwd-sng-setup-repair-dm3

## Scope

- Run: `20260606T231007Z`
- Source result: `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-result-dm3.json`
- Source verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Server start time: `4.2690496` s
- Match duration: `45814` ms

## Player Diagnosis

| Player | Class | MVD window | MVD reached | Active rows | Active in MVD | Active MVD range | Min cp0 from qwd | Min any qwd | Max advanced |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| `/ bro` | `activated_but_failed_control_point_advancement` | `0-45814` | 4 | 446 | 424 | `0-47998` | 227.668 | 99.086 | 4 |
| `/ goldenboy` | `activated_but_failed_control_point_advancement` | `6263-45814` | 0 | 181 | 159 | `29288-47998` | 232.815 | 232.815 | 0 |

## Closest MVD Approaches

### / bro

| CP | Min distance | Time | Origin |
|---:|---:|---:|---|
| 0 | 53.046 | 31816 | `[265.75, -288.875, 61.75]` |
| 1 | 37.896 | 31919 | `[275.5, -263.875, 80.875]` |
| 2 | 56.48 | 32741 | `[272.5, -94.375, 56.0]` |
| 3 | 35.939 | 44432 | `[221.25, 5.375, 56.0]` |
| 4 | 181.154 | 43814 | `[272.0, -2.0, 56.0]` |
| 5 | 296.564 | 43814 | `[272.0, -2.0, 56.0]` |

### / goldenboy

| CP | Min distance | Time | Origin |
|---:|---:|---:|---|
| 0 | 232.805 | 29839 | `[200.375, -240.0, -134.125]` |
| 1 | 216.22 | 29839 | `[200.375, -240.0, -134.125]` |
| 2 | 243.392 | 29839 | `[200.375, -240.0, -134.125]` |
| 3 | 193.887 | 10086 | `[368.5, 151.375, 56.0]` |
| 4 | 43.604 | 10107 | `[372.375, 146.25, 56.0]` |
| 5 | 57.616 | 8975 | `[429.875, 278.125, 56.0]` |

## Interpretation

- This is an offline diagnosis of the already-generated mode-9 run; it does not rerun KTX or change controller behavior.
- Command rows use server time, while MVD position rows use demo-relative time. The diagnosis aligns command rows by subtracting the demo start ServerTime from events kind 0.
- QWD activation now overlaps the parsed MVD movement window, so the remaining blocker is no longer the timing/start-context evidence gate.
- The scorer still rejects the run on guardrails: waypoint_only_slow_success.

## Decision

- Verdict: `qwd_sng_setup_repaired_but_rejected_by_guardrails`
- Reason: QWD activation and control-point advancement now overlap the parsed MVD movement window, but guardrails rejected the run: waypoint_only_slow_success.
- Next goal: Diagnose whether the remaining failure is controller command policy, route/map context, or a too-loose setup radius before widening QWD control or trying other DM3 QWD moves.
