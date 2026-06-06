# Air-Transition Probe Design s7i-air-transition-probe-design-dm3

## Scope

- Map: `dm3`
- Source S7g evidence: `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`
- Source S7h decision: `experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.json`
- Source S7e cadence evidence: `experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.json`
- S7i consumes committed S7g/S7h/S7e evidence and writes a constrained probe design. It does not change KTX, Frogbot behavior, lab runners, parser behavior, or cadence policy.

## Baseline Buckets

| Bucket | Reference rows | Bot rows | Reference p50 | Bot p50 | Bot/ref p50 |
|---|---:|---:|---:|---:|---:|
| Pre-air window | 6 | 6 | 418.0 | 207.1 | 0.495 |
| Airborne-proxy segments | 6 | 6 | 433.8 | 122.6 | 0.283 |
| Post-air window | 6 | 6 | 365.7 | 184.5 | 0.505 |
| All accepted segments | 6 | 6 | 334.0 | 222.0 | 0.665 |
| Non-airborne segments | 6 | 6 | 320.0 | 312.1 | 0.975 |
| Route low-dir-speed segments | 0 | 4 |  | 141.0 |  |
| Route WATER_PATH segments | 0 | 2 |  | 95.3 |  |

## Probe Contract

- Probe id: `s7i-mode8-air-transition-horizontal-speed`
- Status: `design_only_no_controller_behavior_changed`
- Follow-up stage: `S7j`
- Implementation hint: Start from moveprobe mode 7. Add at most one temporary mode-8 or mode-7-variant branch that changes horizontal command budget only during takeoff/air-transition windows. Keep combat view yaw, route projection, no-backpedal folding, command bounding outside the transition window, jump-button policy, route logging, water logging, and cadence reporting unchanged.

Allowed changes:
- A short-lived air-transition horizontal command-budget probe, preferably behind a new cvar or mode.
- Additional diagnostic fields only if they are needed to prove the transition window fired.

Forbidden changes:
- No cadence controller or jump timing change.
- No route file or WATER_PATH route primitive fix.
- No all-segment speed objective.
- No combat aiming, firing, item, spawn, parser, or lab-runner behavior change.

## Cadence Baseline

| Axis | Reference range | Bot range | Bot relation |
|---|---:|---:|---|
| Cadence/active min | 40.4-51.0 | 18.5-138.7 | `mixed_bot_relation` |
| Cadence/non-low-speed min | 48.7-61.3 | 20.2-289.5 | `mixed_bot_relation` |
| Cadence/air-proxy min | 128.0-143.1 | 164.1-274.1 | `all_bots_above_reference_range` |

## Stop Conditions

- `missing_required_reporting` (reject_or_inconclusive): Reject success claims if the post-probe comparison omits pre-air, airborne, post-air, non-air, cadence, route low-dir-speed, or WATER_PATH reporting.
- `all_segment_proxy_win` (reject): Reject any result where all-segment p50 speed improves but none of pre-air, airborne, or post-air p50 speed improves over the S7g baseline.
- `air_transition_regression` (reject): Reject if any required air-transition bucket p50 drops by more than 5 percent versus S7g baseline.
- `non_airborne_guardrail` (reject): Reject if non-airborne p50 falls more than 5 percent below the S7g baseline.
- `water_path_guardrail` (reject_or_inconclusive): Reject if WATER_PATH p50 speed falls more than 5 percent below baseline when WATER_PATH evidence is present. Treat a run with missing route/WATER_PATH diagnostics as inconclusive rather than ready.
- `cadence_still_diagnostic` (reject_or_inconclusive): Do not claim success from cadence changes. Cadence must remain reported on the same active, movement-time, and airborne-proxy bases so S7d/S7e warnings stay visible.

## Decision

- Verdict: `ready_to_design_tiny_air_transition_probe`
- Selected probe target: `air_transition_horizontal_speed`
- Reason: S7h selected a human-comparable air-transition speed gap; S7i turns that into a constrained probe contract with explicit guardrails before any controller behavior changes.
- Next goal: S7j should implement and run the tiny air-transition probe only if it preserves the S7i contract, then compare it against the S7g/S7h/S7e baselines.
