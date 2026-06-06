# S7j Failed-Bucket Diagnosis s7k-failed-bucket-diagnosis-dm3

## Scope

- Map: `dm3`
- Source S7j result: `experiments/human_comparison/evidence/air-transition-probe-s7j-dm3.json`
- Source S7g baseline: `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`
- Transition window: `400` ms
- Command match margin: `150` ms
- S7k reuses corrected S7j artifacts and recomputes per-segment command/probe/route context for the failed pre-air, airborne-proxy, and non-airborne buckets. It does not rerun the lab or add a movement mode.

## Frogbots-Vs-From-Scratch Gates

| Gate | Continue Frogbots/KTX if | Abandon or rebuild if |
|---|---|---|
| `engine_native_substrate` | KTX/Frogbots continue to spawn, fight, accept controller overrides, emit command diagnostics, and produce MVD evidence without rebuilding physics/collision/combat. | The needed movement evidence cannot be gathered inside KTX/Frogbots, or controller hooks corrupt core server-native behavior. |
| `isolated_movement_primitive` | A tiny movement primitive improves a target human-comparable bucket while preserving non-target guardrails and route/cadence diagnostics. | Multiple bounded primitives cannot improve target buckets without broad regressions that cannot be attributed or gated. |
| `route_and_map_context` | Route/map failures can be exposed as guardrails or corrected with narrow route/context changes. | Frogbot route state is too opaque or too static to separate movement-controller failures from map-understanding failures. |

## Failed Buckets

| Bucket | S7g p50 | S7j p50 | S7j/S7g | Bot/ref | Context | Classification |
|---|---:|---:|---:|---:|---|---|
| Pre-air window | 207.1 | 149.7 | 0.723 | 0.358 | strong `0.936`, active `0.091`, low-dir `0.565`, WATER_PATH `0.469` | `mixed_controller_and_route_context` |
| Airborne-proxy segments | 122.6 | 100.4 | 0.819 | 0.232 | strong `0.925`, active `0.140`, low-dir `0.535`, WATER_PATH `0.404` | `mixed_controller_and_route_context` |
| Non-airborne segments | 312.1 | 286.3 | 0.917 | 0.895 | strong `0.932`, active `0.206`, low-dir `0.168`, WATER_PATH `0.101` | `route_or_map_context_guardrail_contamination` |

## Per-Player Context

| Bucket | Player | Run | Segments | p50 | Strong | Active | Low-dir | WATER_PATH |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Pre-air window | `/ bro` | `20260606T163907Z` | 207 | 202.1 | 0.912 | 0.082 | 0.088 | 0.000 |
| Airborne-proxy segments | `/ bro` | `20260606T163907Z` | 198 | 101.8 | 0.862 | 0.164 | 0.138 | 0.000 |
| Non-airborne segments | `/ bro` | `20260606T163907Z` | 1058 | 303.9 | 0.982 | 0.166 | 0.018 | 0.000 |
| Pre-air window | `/ goldenboy` | `20260606T163907Z` | 119 | 256.0 | 1.000 | 0.200 | 0.000 | 0.000 |
| Airborne-proxy segments | `/ goldenboy` | `20260606T163907Z` | 131 | 181.2 | 0.909 | 0.091 | 0.091 | 0.000 |
| Non-airborne segments | `/ goldenboy` | `20260606T163907Z` | 829 | 331.8 | 0.955 | 0.192 | 0.045 | 0.000 |
| Pre-air window | `/ bro` | `20260606T164610Z` | 431 | 87.5 | 0.720 | 0.243 | 0.280 | 0.000 |
| Airborne-proxy segments | `/ bro` | `20260606T164610Z` | 515 | 68.8 | 0.777 | 0.342 | 0.223 | 0.000 |
| Non-airborne segments | `/ bro` | `20260606T164610Z` | 1726 | 268.7 | 0.873 | 0.300 | 0.127 | 0.000 |
| Pre-air window | `/ goldenboy` | `20260606T164610Z` | 1445 | 97.2 | 1.000 | 0.042 | 0.729 | 0.683 |
| Airborne-proxy segments | `/ goldenboy` | `20260606T164610Z` | 1179 | 99.1 | 1.000 | 0.052 | 0.758 | 0.665 |
| Non-airborne segments | `/ goldenboy` | `20260606T164610Z` | 766 | 100.8 | 0.979 | 0.046 | 0.626 | 0.614 |

## Interpretation

- Water is not the whole S7j problem. `WATER_PATH`/low-dir context explains the non-airborne guardrail contamination, especially where route context dominates, but the intended air-transition buckets still fail under strong command/probe coverage.
- This is not yet evidence that Frogbots lack strategic intelligence. The current split is lower-level: controller timing/physics interaction for air transitions, plus route/map-context guardrails around low-dir-speed and `WATER_PATH`.
- The from-scratch trigger is not reached while the KTX/Frogbots shell still supports spawning, combat, command overrides, diagnostics, and MVD evidence.

## Decision

- Verdict: `continue_frogbots_with_context_gated_probe`
- Frogbots-vs-from-scratch: `continue_frogbots_for_next_bounded_stage`
- Reason: S7k separates the corrected S7j failure into a controller/timing problem in the intended air buckets plus route/map-context contamination in the non-airborne guardrail. This does not disprove the KTX/Frogbots substrate; it says the next probe must be narrower and context-gated.
- Next goal: S7l should design a smaller air-transition probe that either excludes low-dir-speed/WATER_PATH contexts or treats them as hard stop-condition slices before another lab rerun.
