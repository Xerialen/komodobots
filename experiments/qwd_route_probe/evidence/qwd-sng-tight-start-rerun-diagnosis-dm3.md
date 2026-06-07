# QWD SNG Probe Diagnosis qwd-sng-tight-start-rerun-dm3

## Scope

- Run: `20260607T003837Z`
- Source result: `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-dm3.json`
- Source verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Server start time: `4.2668004` s
- Match duration: `45821` ms

## Player Diagnosis

| Player | Class | MVD window | MVD reached | Active rows | Active in MVD | Active MVD range | Min cp0 from qwd | Min any qwd | Max advanced |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| `/ bro` | `activated_but_failed_control_point_advancement` | `0-45821` | 11 | 157 | 157 | `1587-17888` | 864.836 | 96.066 | 11 |
| `/ goldenboy` | `activated_but_failed_control_point_advancement` | `6264-45821` | 12 | 117 | 117 | `7248-19336` | 368.649 | 96.257 | 12 |

## Closest MVD Approaches

### / bro

| CP | Min distance | Time | Origin |
|---:|---:|---:|---|
| 0 | 68.756 | 1904 | `[251.0, -282.875, 64.75]` |
| 1 | 39.992 | 2026 | `[271.125, -252.125, 80.875]` |
| 2 | 51.399 | 2430 | `[305.75, -142.875, 92.375]` |
| 3 | 48.396 | 3202 | `[258.25, 27.875, 56.0]` |
| 4 | 44.519 | 3749 | `[368.75, 135.375, 56.0]` |
| 5 | 23.461 | 4219 | `[441.0, 242.875, 56.0]` |

### / goldenboy

| CP | Min distance | Time | Origin |
|---:|---:|---:|---|
| 0 | 56.214 | 7598 | `[262.5, -288.125, 63.0]` |
| 1 | 37.581 | 7700 | `[273.75, -261.75, 79.125]` |
| 2 | 47.842 | 8131 | `[302.0, -141.75, 92.875]` |
| 3 | 47.873 | 8995 | `[258.25, 32.5, 56.0]` |
| 4 | 46.506 | 9469 | `[372.625, 129.25, 56.0]` |
| 5 | 27.261 | 10261 | `[480.25, 213.25, 56.0]` |

## Interpretation

- This is an offline diagnosis of the already-generated mode-9 run; it does not rerun KTX or change controller behavior.
- Command rows use server time, while MVD position rows use demo-relative time. The diagnosis aligns command rows by subtracting the demo start ServerTime from events kind 0.
- QWD activation and advancement overlap the parsed MVD movement window, but pre-advance CP0 tight-start evidence remains unresolved in the sampled command log.
- The scorer still rejects the run on guardrails: phase_target_progression, waypoint_only_slow_success.
- The scorer also marks these gates inconclusive: tight_start_activation.

## Decision

- Verdict: `qwd_sng_start_evidence_inconclusive`
- Reason: QWD activation and control-point advancement overlap the parsed MVD movement window, but the scorer could not verify pre-advance CP0 tight-start evidence from sampled command rows. Rejected guardrails: phase_target_progression, waypoint_only_slow_success.
- Next goal: Add denser or event-level QWD start/advancement evidence and active-window diagnostics before changing projection policy or trying other DM3 QWD moves.
