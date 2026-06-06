# Route State Diagnosis s6a-route-state

## Scope

- Run: `20260606T003718Z`
- Map: `dm3` / `The Abandoned Base`
- Moveprobe mode: `7`
- Low-speed threshold: `100.0` qu/s
- Route direction available: `yes`
- Route node/goal/obstruction state available: `no`

## Artifact Capability

- Current S3g artifacts expose position traces, sampled final commands, view yaw, route yaw, and backward-command diagnostics.
- They do not expose Frogbot route node, next waypoint, target entity, obstruction, or route primitive state.

## Player Summary

| Player | Avg | P95 | Max | Low | Low windows | Longest low | Top windows with strong-command low speed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/ bro` | 190.1 | 361.0 | 449.4 | 26.1% | `7` | `1198` ms | `5` / `5` |
| `/ goldenboy` | 248.2 | 375.3 | 415.0 | 18.9% | `4` | `1078` ms | `3` / `4` |

## Top Low-Speed Windows

| Player | Rank | Window | Low ms | Avg low | From | To | Cmds | Avg cmd | Strong | Jump | Abs delta p90 | Hint |
|---|---:|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|
| `/ bro` | `1` | `21819-23281` | `1198` | 69.2 | `water.LG` (7q) | `water.LG` (13q) | `7` | 824.1 | 100.0% | 100.0% | 123.3 | `low_speed_despite_strong_commands` |
| `/ bro` | `2` | `14819-15913` | `1074` | 57.0 | `Quad` (194q) | `water.GL` (188q) | `5` | 824.0 | 100.0% | 100.0% | 164.9 | `low_speed_despite_strong_commands` |
| `/ bro` | `3` | `18084-18836` | `752` | 52.9 | `bridge.low` (90q) | `bridge.low` (68q) | `4` | 824.1 | 100.0% | 100.0% | 145.8 | `low_speed_despite_strong_commands` |
| `/ bro` | `4` | `16561-17257` | `696` | 45.5 | `bridge.low` (184q) | `bridge.low` (160q) | `4` | 824.0 | 100.0% | 100.0% | 157.8 | `low_speed_despite_strong_commands` |
| `/ bro` | `5` | `23976-24645` | `547` | 84.7 | `water.LG` (6q) | `water.LG` (1q) | `4` | 824.0 | 100.0% | 100.0% | 113.3 | `low_speed_despite_strong_commands` |
| `/ goldenboy` | `1` | `17415-18493` | `1078` | 49.0 | `RA` (92q) | `RA` (51q) | `5` | 659.1 | 80.0% | 80.0% | 122.0 | `low_speed_despite_strong_commands` |
| `/ goldenboy` | `2` | `9234-9904` | `670` | 82.8 | `hill` (66q) | `hill` (37q) | `0` | 0.0 | 0.0% | 0.0% | 0.0 | `low_speed_without_sampled_commands` |
| `/ goldenboy` | `3` | `13154-13680` | `506` | 21.9 | `Quad` (108q) | `SNG.tele` (2q) | `3` | 824.0 | 100.0% | 100.0% | 102.7 | `low_speed_despite_strong_commands` |
| `/ goldenboy` | `4` | `20992-21313` | `260` | 47.2 | `RA.low` (96q) | `RA.low` (96q) | `2` | 412.0 | 50.0% | 50.0% | 129.6 | `low_speed_despite_strong_commands` |

## Interpretation

- S6a used existing MVD position samples plus sampled final moveprobe commands; no new controller heuristic was added.
- Current artifacts can show where low-speed spans happen and whether strong commands were sampled nearby.
- Current artifacts cannot attribute those spans to a Frogbot route node, next waypoint, obstruction, or route primitive.
- 8 of 9 analyzed low-speed windows show low speed despite average sampled horizontal command >= 400.

## Next Goal

- S6b should add minimal route-state logging around the Frogbot command boundary so low-speed windows can be tagged with route node/goal/obstruction context before changing the movement controller again.
