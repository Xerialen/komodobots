# Route-State Attribution s6d-water-path

## Scope

- Run: `20260606T041805Z`
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
| `/ bro` | `2` | `['water.LG']` | `[59, 276]` | `[59]` | yes | `[1, 2]` | `['none']` | 0.0% | -0.142 | 0.0% | 90.9% | 0.13 | 824.0 | `water_path_without_obstruction` |
| `/ bro` | `2` | `['water.LG']` | `[59]` | `[59]` | yes | `[1, 2]` | `['none']` | 0.0% | -0.125 | 0.0% | 100.0% | 0.057 | 823.8 | `water_path_without_obstruction` |
| `/ bro` | `1` | `['water.LG']` | `[59, 278]` | `[59]` | yes | `[1]` | `['none']` | 0.0% | 0.033 | 0.0% | 11.1% | 0.395 | 823.9 | `water_path_without_obstruction` |
| `/ goldenboy` | `1` | `['water']` | `[10, 44, 131]` | `[10]` | no | `[0]` | `['none']` | 0.0% | 0.0 | 0.0% | 0.0% | 1.0 | 824.0 | `route_state_unresolved` |
| `/ goldenboy` | `1` | `['water.rox']` | `[46, 69]` | `[10]` | no | `[0]` | `['none']` | 0.0% | 0.0 | 0.0% | 0.0% | 1.0 | 824.0 | `route_state_unresolved` |

## Window Attribution

| Player | Rank | Window | Location | Avg cmd | Linked | Touch | Goal | Path state | Water levels | Swim | Upmove | Dir z avg | Vel z avg | Blocked | Dir speed avg | Classification |
|---|---:|---|---|---:|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| `/ bro` | `1` | `14818-16908` | `water.LG` | 823.9 | `[59, 278]` | `[59, 276, 278]` | `[59]` | `['0:none', '32768:WATER_PATH']` | `[1]` | `['none']` | 0.0% | 0.033 | -8.3 | 0.0% | 0.395 | `water_path_without_obstruction` |
| `/ bro` | `2` | `16989-18042` | `water.LG` | 823.9 | `[59, 276]` | `[59, 276]` | `[59]` | `['0:none', '32768:WATER_PATH']` | `[1, 2]` | `['none']` | 0.0% | -0.153 | -19.8 | 0.0% | 0.197 | `water_path_without_obstruction` |
| `/ bro` | `3` | `18246-19100` | `water.LG` | 824.0 | `[59, 276]` | `[276]` | `[59]` | `['0:none', '32768:WATER_PATH']` | `[1]` | `['none']` | 0.0% | -0.129 | -13.6 | 0.0% | 0.05 | `water_path_without_obstruction` |
| `/ bro` | `4` | `19830-20643` | `water.LG` | 823.8 | `[59]` | `[59, 276]` | `[59]` | `['0:none', '32768:WATER_PATH']` | `[1]` | `['none']` | 0.0% | 0.02 | 3.4 | 0.0% | 0.051 | `water_path_without_obstruction` |
| `/ bro` | `5` | `25006-25782` | `water.LG` | 823.9 | `[59]` | `[276]` | `[59]` | `['32768:WATER_PATH']` | `[1, 2]` | `['none']` | 0.0% | -0.27 | 2.3 | 0.0% | 0.064 | `water_path_without_obstruction` |
| `/ goldenboy` | `1` | `22610-23320` | `water` | 824.0 | `[10, 44, 131]` | `[2, 44, 131]` | `[10]` | `['0:none']` | `[0]` | `['none']` | 0.0% | 0.0 | 0.0 | 0.0% | 1.0 | `route_state_unresolved` |
| `/ goldenboy` | `2` | `10434-11022` | `water.rox` | 824.0 | `[46, 69]` | `[1, 46]` | `[10]` | `['0:none']` | `[0]` | `['none']` | 0.0% | 0.0 | 0.0 | 0.0% | 1.0 | `route_state_unresolved` |

## Map Edge Evidence

| Player | Rank | Touch-to-linked edges from `.bot` map |
|---|---:|---|
| `/ bro` | `1` | `['276->59 idx=[0]', '278->59 idx=[0]', '278->278 missing', '59->59 missing']` |
| `/ bro` | `2` | `['59->59 missing', '276->276 missing', '276->59 idx=[0]']` |
| `/ bro` | `3` | `['276->59 idx=[0]', '276->276 missing']` |
| `/ bro` | `4` | `['276->59 idx=[0]', '59->59 missing']` |
| `/ bro` | `5` | `['276->59 idx=[0]']` |
| `/ goldenboy` | `1` | `['2->44 idx=[2]', '44->131 idx=[2]', '131->10 idx=[1]']` |
| `/ goldenboy` | `2` | `['1->46 idx=[2]', '46->69 idx=[1]']` |

## Interpretation

- This attribution is diagnostic-only; it decodes sampled route and water/swim state without adding a new movement mode.
- The repeated water.LG low-speed pattern decodes path_state 32768 as WATER_PATH, not STUCK_PATH.
- The repeated water-path windows have blocked=0, so obstruction recovery is not the current explanation.
- When water_state samples are present, waterlevel/swim_arrow/upmove/velocity/dir_move context can distinguish shallow-water edge handling from active swim intent.

## Next Goal

- S6e should use the S6d water/swim evidence to choose the smallest targeted fix: swim/upmove handling, route-edge geometry diagnosis, or a repeated-run check if the water-path pattern is not reproduced.
