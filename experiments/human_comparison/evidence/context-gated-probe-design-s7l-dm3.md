# Context-Gated Probe Design s7l-context-gated-probe-design-dm3

## Scope

- Map: `dm3`
- Source S7k diagnosis: `experiments/human_comparison/evidence/failed-bucket-diagnosis-s7k-dm3.json`
- S7l consumes the committed S7k failed-bucket diagnosis and turns it into a design-only context gate for the next air-transition probe. It does not change KTX, Frogbot behavior, route files, parser behavior, or lab runners.

## Context Slices

| Bucket | Slice | Player rows | Segments | Segment ratio | p50 speed |
|---|---|---:|---:|---:|---:|
| `pre_air_window_segments` | `clean_air_transition_candidate` | 2 | 326 | 0.148 | 229.0 |
| `pre_air_window_segments` | `route_guardrail_slice` | 1 | 1445 | 0.656 | 97.2 |
| `pre_air_window_segments` | `measurement_risk` | 1 | 431 | 0.196 | 87.5 |
| `airborne_proxy_segments` | `clean_air_transition_candidate` | 3 | 844 | 0.417 | 101.8 |
| `airborne_proxy_segments` | `route_guardrail_slice` | 1 | 1179 | 0.583 | 99.1 |
| `airborne_proxy_segments` | `measurement_risk` | 0 | 0 | 0.000 |  |
| `non_airborne_segments` | `clean_air_transition_candidate` | 3 | 3613 | 0.825 | 303.9 |
| `non_airborne_segments` | `route_guardrail_slice` | 1 | 766 | 0.175 | 100.8 |
| `non_airborne_segments` | `measurement_risk` | 0 | 0 | 0.000 |  |

## Context Gate Rules

- `eligible_air_transition_context`: Only claim target-bucket success on pre-air or airborne-proxy slices with sampled command ratio >= 0.5, strong command ratio >= 0.75, low-dir-speed ratio < 0.25, and WATER_PATH ratio <= 0.05.
- `route_context_is_guardrail_not_success`: Low-dir-speed or WATER_PATH slices must be reported separately. They may reject or make the probe inconclusive, but they cannot be counted as evidence that the air-transition controller improved.
- `live_gate_must_use_frogbot_state`: A future KTX patch must gate using live Frogbot route/water state available in BotSetCommand. Offline S7k labels are evidence for the contract, not a runtime oracle.

## Probe Contract

- Probe id: `s7m-context-gated-air-transition-horizontal-speed`
- Status: `design_only_no_controller_behavior_changed`
- Follow-up stage: `S7m`
- Runtime gate: Start from mode 8's transition-window command-budget idea, but activate it only when the live route context is clean: no WATER_PATH, no low-dir-speed route primitive, command/probe diagnostics present, and the bot is inside the intended takeoff/recent-air/recent-landing window.

Required clean target buckets:

| Bucket | Clean rows | Clean segments | Ready for claim |
|---|---:|---:|---|
| `pre_air_window_segments` | 2 | 326 | `True` |
| `airborne_proxy_segments` | 3 | 844 | `True` |

Allowed changes:
- One temporary mode or cvar-gated variant that changes horizontal command budget only in clean air-transition context.
- Additional command log fields only if needed to prove runtime gate eligibility, activation, and rejection.

Forbidden changes:
- No route file edit or WATER_PATH primitive fix in the same PR.
- No cadence/jump-timing controller change.
- No success claim from all-segment speed alone.
- No combat, item, spawn, parser, or lab-runner behavior change unless required for missing evidence reporting.

## Stop Conditions

- `missing_context_split_reporting` (inconclusive): The follow-up comparison must split pre-air, airborne-proxy, and non-airborne buckets into clean, route-guardrail, and measurement-risk slices. Missing split reporting blocks success claims.
- `insufficient_clean_target_evidence` (inconclusive): Each claimed clean target bucket needs at least 2 player rows and 50 segments.
- `clean_air_transition_regression` (reject): Reject if any claimed clean pre-air or airborne-proxy p50 drops more than 5 percent versus S7k clean baseline.
- `no_clean_air_transition_gain` (reject): Reject if no clean air-transition target bucket improves while all-segment or dirty-route slices improve.
- `route_guardrail_regression` (reject_or_route_primitive_handoff): Reject the controller probe or hand off to a route primitive if route-guardrail slices get worse, especially WATER_PATH or low-dir-speed contexts.
- `cadence_and_route_diagnostics_preserved` (inconclusive): Missing cadence, route-state, water-state, or probe-activation diagnostics makes the result inconclusive.

## Decision Gates

- `continue_ktx_frogbots`: Continue with KTX/Frogbots if the next clean-context probe improves a human-comparable air bucket while preserving route/cadence diagnostics and dirty-context guardrails.
- `switch_to_route_primitive`: If clean air-transition slices are too sparse or route-dirty slices dominate every failure, pivot to a narrow route primitive instead of increasing controller scope.
- `consider_from_scratch`: Consider abandoning Frogbots only after bounded clean-context probes still fail under strong command coverage and the live route/map state cannot separate controller failures from map-understanding failures.

## Decision

- Verdict: `ready_to_implement_context_gated_air_transition_probe`
- Frogbots-vs-from-scratch: `continue_frogbots_for_next_bounded_stage`
- Reason: S7k contains enough clean air-transition rows to test a narrower controller primitive, while route-dirty rows explain why S7j aggregate buckets were misleading. This supports one more bounded Frogbots probe.
- Next goal: S7m should implement and run the context-gated air-transition probe, then compare clean and route-dirty slices separately against S7k/S7g baselines.
