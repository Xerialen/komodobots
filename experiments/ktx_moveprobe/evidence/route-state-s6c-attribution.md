# Route-State Attribution s6c-route-attribution

## Scope

- Run: `20260606T031102Z`
- Map: `dm3` / `The Abandoned Base`
- Controller change: `none`
- Marker index invariant: Attribution assumes logged marker->fb.index + 1 matches the .bot file's 1-based marker ids. CreateMarker ids are assigned by file order; item/runtime marker ids can be referenced by route commands without static origins.

## Decoded Flags

- `32768` -> `WATER_PATH`
- `524288` -> `STUCK_PATH`
- bot state `128` -> `AWARE_SURROUNDINGS`

## Repeated Patterns

| Player | Windows | Locations | Linked | Goal | Water path | Water levels | Swim | Upmove | Dir z avg | Blocked | Low dir | Dir speed avg | Avg cmd | Classification |
|---|---:|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| `/ bro` | `3` | `['water.LG']` | `[59]` | `[59]` | yes | `` | `` |  |  | 0.0% | 62.5% | 0.338 | 824.0 | `water_path_without_obstruction` |
| `/ bro` | `1` | `['Quad']` | `[91, 119, 170]` | `[3]` | no | `` | `` |  |  | 0.0% | 20.0% | 0.774 | 659.1 | `route_state_unresolved` |
| `/ bro` | `1` | `['bridge.low']` | `[161]` | `[10]` | no | `` | `` |  |  | 0.0% | 0.0% | 0.7 | 824.0 | `route_state_unresolved` |

## Window Attribution

| Player | Rank | Window | Location | Avg cmd | Linked | Touch | Goal | Path state | Water levels | Swim | Upmove | Dir z avg | Vel z avg | Blocked | Dir speed avg | Classification |
|---|---:|---|---|---:|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| `/ bro` | `1` | `3181-5292` | `Quad` | 659.1 | `[-1, 91, 119, 170]` | `[43, 119, 168, 170, 172]` | `[-1, 3]` | `['0:none']` | `` | `` |  |  |  | 0.0% | 0.774 | `route_state_unresolved` |
| `/ bro` | `2` | `13193-14307` | `water.LG` | 824.1 | `[59]` | `[37, 273]` | `[59]` | `['0:none', '32768:WATER_PATH']` | `` | `` |  |  |  | 0.0% | 0.787 | `water_path_without_obstruction` |
| `/ bro` | `3` | `24441-25517` | `water.LG` | 823.8 | `[59]` | `[276]` | `[59]` | `['32768:WATER_PATH']` | `` | `` |  |  |  | 0.0% | 0.059 | `water_path_without_obstruction` |
| `/ bro` | `4` | `21860-22918` | `water.LG` | 824.1 | `[59]` | `[276]` | `[59]` | `['32768:WATER_PATH']` | `` | `` |  |  |  | 0.0% | 0.196 | `water_path_without_obstruction` |
| `/ bro` | `5` | `9008-9882` | `bridge.low` | 824.0 | `[161]` | `[159]` | `[10]` | `['0:none']` | `` | `` |  |  |  | 0.0% | 0.7 | `route_state_unresolved` |

## Map Edge Evidence

| Player | Rank | Touch-to-linked edges from `.bot` map |
|---|---:|---|
| `/ bro` | `1` | `['172->170 idx=[0]', '168->170 idx=[0]', '170->119 idx=[0]', '119->91 idx=[5]']` |
| `/ bro` | `2` | `['273->59 idx=[4]', '37->59 idx=[2]']` |
| `/ bro` | `3` | `['276->59 idx=[0]']` |
| `/ bro` | `4` | `['276->59 idx=[0]']` |
| `/ bro` | `5` | `['159->161 idx=[0]']` |

## Interpretation

- S6c used the existing S6b run and source route definitions; no KTX patch or controller behavior changed.
- The repeated water.LG low-speed pattern decodes path_state 32768 as WATER_PATH, not STUCK_PATH.
- The repeated water-path windows have blocked=0, so obstruction recovery is not the current explanation.
- In the worst repeated windows, native Frogbot dir_speed is very low before the probe normalizes direction, while sampled command magnitude remains strong.

## Next Goal

- S6d should inspect water-path movement intent around water.LG by adding or deriving minimal waterlevel/swim_arrow/upmove/velocity context before changing mode 7.
