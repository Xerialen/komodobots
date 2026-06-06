# Route State Diagnosis s6b-route-state

## Scope

- Run: `20260606T031102Z`
- Map: `dm3` / `The Abandoned Base`
- Moveprobe mode: `7`
- Low-speed threshold: `100.0` qu/s
- Route direction available: `yes`
- Route node/goal/obstruction state available: `yes`

## Artifact Capability

- Artifacts expose position traces, sampled final commands, view yaw, route yaw, and backward-command diagnostics when command logging is enabled.
- Command rows also expose route-state context such as marker ids, goal entity/marker ids, path/bot state flags, blocked state, and route dir_speed.
- Command/sample clock overlap: `ok` (overlap `21666` ms, margin `150` ms).

## Player Summary

| Player | Avg | P95 | Max | Low | Low windows | Longest low | Top windows with strong-command low speed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/ bro` | 136.3 | 359.6 | 406.2 | 52.1% | `17` | `1646` ms | `5` / `5` |
| `/ goldenboy` | 285.5 | 381.3 | 427.8 | 7.0% | `0` | `0` ms | `0` / `0` |

## Top Low-Speed Windows

| Player | Rank | Window | Low ms | Avg low | From | To | Cmds | Avg cmd | Strong | Jump | Abs delta p90 | Route | Blocked | Hint |
|---|---:|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|---:|---|
| `/ bro` | `1` | `3181-5292` | `1646` | 22.0 | `Quad` (170q) | `Quad` (174q) | `5` | 659.1 | 80.0% | 80.0% | 88.6 | `L[-1, 91, 119, 170] T[43, 119, 168, 170, 172] G[-1, 3] P[0]` | 0.0% | `low_speed_despite_strong_commands` |
| `/ bro` | `2` | `13193-14307` | `1074` | 83.0 | `water.LG` (12q) | `water.LG` (12q) | `5` | 824.1 | 100.0% | 100.0% | 106.4 | `L[59] T[37, 273] G[59] P[0, 32768]` | 0.0% | `low_speed_despite_strong_commands` |
| `/ bro` | `3` | `24441-25517` | `1056` | 80.1 | `water.LG` (21q) | `water.LG` (10q) | `5` | 823.8 | 100.0% | 100.0% | 96.5 | `L[59] T[276] G[59] P[32768]` | 0.0% | `low_speed_despite_strong_commands` |
| `/ bro` | `4` | `21860-22918` | `1002` | 83.5 | `water.LG` (20q) | `water.LG` (14q) | `6` | 824.1 | 100.0% | 100.0% | 75.2 | `L[59] T[276] G[59] P[32768]` | 0.0% | `low_speed_despite_strong_commands` |
| `/ bro` | `5` | `9008-9882` | `833` | 57.0 | `bridge.low` (120q) | `bridge.low` (77q) | `5` | 824.0 | 100.0% | 100.0% | 168.6 | `L[161] T[159] G[10] P[0]` | 0.0% | `low_speed_despite_strong_commands` |

## Interpretation

- This diagnosis used MVD position samples plus sampled final moveprobe commands; no new controller heuristic was added.
- The artifacts can show where low-speed spans happen and whether strong commands were sampled nearby.
- Route-state logging can now tag low-speed spans with marker, goal, path-state, bot-state, blocked, and dir_speed context.
- 5 of 5 analyzed low-speed windows show low speed despite average sampled horizontal command >= 400.

## Next Goal

- S6c should use route-state-tagged low-speed windows to identify repeated marker/path-state/blocked patterns before changing mode 7 or adding another movement-command heuristic.
