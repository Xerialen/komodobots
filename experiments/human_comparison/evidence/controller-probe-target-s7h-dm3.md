# Controller Probe Target Decision s7h-controller-probe-target-dm3

## Scope

- Map: `dm3`
- Source S7g evidence: `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`
- S7h consumes S7g land-speed context and chooses the first controller-probe target. It prefers a human-comparable context gap over a narrow bot-only route diagnostic unless the comparable evidence is missing.

## Candidate Comparison

| Candidate | Priority | Human comparable | Score | Key evidence |
|---|---|---:|---:|---|
| Air-transition horizontal speed production | `preferred_first_probe_target` | `True` | `0.572` | pre `0.495`, air `0.283`, post `0.505`, non-air `0.975` |
| Route WATER_PATH low-dir-speed recovery | `secondary_guardrail_target` | `False` | `0.567` | WATER_PATH `95.3`, low-dir `141.0`, route-matched segments `3674` |

## Decision

- Verdict: `choose_air_transition_horizontal_speed_probe`
- Selected target: `air_transition_horizontal_speed`
- Deferred target: `water_path_low_dir_speed_recovery`
- Reason: Air-transition speed is the first controller probe target because it is human-comparable across the exact-player and bot row set, affects pre-air/airborne/post-air contexts, and is clearly separated from generic non-airborne speed. WATER_PATH remains a guardrail and later narrow route target rather than the first probe.
- Next goal: S7i should design a tiny air-transition horizontal-speed probe with unchanged cadence reporting, unchanged route diagnostics, and stop conditions that reject all-segment speed gains if air transition buckets or WATER_PATH context get worse.

## Probe Guardrails

- Do not treat all-segment speed as success by itself.
- Keep cadence diagnostic and report airborne-proxy cadence after any probe.
- Report pre-air, airborne, post-air, non-airborne, route low-dir-speed, and WATER_PATH buckets after any probe.
- Reject a probe if it improves one bucket while making combat/route context or WATER_PATH behavior worse.
