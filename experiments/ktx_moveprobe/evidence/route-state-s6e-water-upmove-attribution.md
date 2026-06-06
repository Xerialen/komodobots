# Route-State Attribution s6e-water-edge-upmove

## Scope

- Run: `20260606T044000Z`
- Map: `dm3` / `The Abandoned Base`
- Controller change: `mode 7 preserves native pre-probe upmove when waterlevel > 1`
- Marker index invariant: Attribution assumes logged marker->fb.index + 1 matches the .bot file's 1-based marker ids. CreateMarker ids are assigned by file order; item/runtime marker ids can be referenced by route commands without static origins.

## Decoded Flags

- `32768` -> `WATER_PATH`
- `524288` -> `STUCK_PATH`
- bot state `128` -> `AWARE_SURROUNDINGS`

## Repeated Patterns

| Player | Windows | Locations | Linked | Goal | Water path | Water levels | Swim | Upmove | Dir z avg | Blocked | Low dir | Dir speed avg | Avg cmd | Classification |
|---|---:|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| `/ goldenboy` | `2` | `['water.LG']` | `[59]` | `[59]` | yes | `[1, 2]` | `['none']` | 13.3% | 0.013 | 0.0% | 80.0% | 0.24 | 823.9 | `water_path_without_obstruction` |
| `/ bro` | `1` | `['YA.box']` | `[10, 44, 53, 131, 283]` | `[10, 44, 53]` | yes | `[0, 1, 2]` | `['none']` | 0.0% | -0.008 | 55.3% | 2.6% | 0.95 | 758.8 | `blocked_or_stuck_path` |
| `/ goldenboy` | `1` | `['bridge.low']` | `[70, 71, 73]` | `[10]` | yes | `[0, 1]` | `['none']` | 0.0% | -0.131 | 0.0% | 0.0% | 0.992 | 824.1 | `water_path_without_obstruction` |
| `/ goldenboy` | `1` | `['water.LG']` | `[37, 293]` | `[59]` | no | `[1]` | `['none']` | 0.0% | -0.007 | 0.0% | 0.0% | 0.962 | 823.8 | `route_state_unresolved` |
| `/ bro` | `1` | `['water.GL']` | `[156, 162]` | `[10]` | no | `[0]` | `['none']` | 0.0% | 0.0 | 0.0% | 0.0% | 0.997 | 823.6 | `route_state_unresolved` |
| `/ goldenboy` | `1` | `['water.LG']` | `[59, 278]` | `[59]` | yes | `[0, 1]` | `['none']` | 0.0% | -0.056 | 0.0% | 0.0% | 0.642 | 823.8 | `water_path_without_obstruction` |
| `/ bro` | `1` | `['lifts']` | `[]` | `[]` | no | `` | `` |  |  | 0.0% | 0.0% | 0.0 | 0.0 | `route_state_unresolved` |

## Window Attribution

| Player | Rank | Window | Location | Avg cmd | Linked | Touch | Goal | Path state | Water levels | Swim | Upmove | Dir z avg | Vel z avg | Blocked | Dir speed avg | Classification |
|---|---:|---|---|---:|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| `/ bro` | `1` | `16279-25781` | `YA.box` | 758.8 | `[10, 44, 53, 131, 283]` | `[10, 44, 131, 283, 293]` | `[-1, 10, 44, 53]` | `['0:none', '32768:WATER_PATH', '524288:STUCK_PATH', '1081344:WATER_PATH,AIR_ACCELERATION']` | `[0, 1, 2]` | `['none']` | 0.0% | -0.008 | -0.8 | 55.3% | 0.95 | `blocked_or_stuck_path` |
| `/ bro` | `2` | `805-1760` | `lifts` | 0.0 | `[]` | `[]` | `[]` | `[]` | `` | `` |  |  |  | 0.0% | 0.0 | `route_state_unresolved` |
| `/ bro` | `3` | `12865-13576` | `water.GL` | 823.6 | `[156, 162]` | `[158, 160, 162]` | `[10]` | `['0:none']` | `[0]` | `['none']` | 0.0% | 0.0 | 0.0 | 0.0% | 0.997 | `route_state_unresolved` |
| `/ goldenboy` | `1` | `22814-25352` | `water.LG` | 824.0 | `[59]` | `[276]` | `[59]` | `['32768:WATER_PATH']` | `[1, 2]` | `['none']` | 18.2% | -0.041 | 12.8 | 0.0% | 0.222 | `water_path_without_obstruction` |
| `/ goldenboy` | `2` | `12926-14654` | `bridge.low` | 824.1 | `[70, 71, 73]` | `[70, 73, 277, 290]` | `[10]` | `['0:none', '32768:WATER_PATH']` | `[0, 1]` | `['none']` | 0.0% | -0.131 | -40.4 | 0.0% | 0.992 | `water_path_without_obstruction` |
| `/ goldenboy` | `3` | `16702-17679` | `water.LG` | 823.8 | `[37, 293]` | `[287]` | `[59]` | `['0:none']` | `[1]` | `['none']` | 0.0% | -0.007 | 6.2 | 0.0% | 0.962 | `route_state_unresolved` |
| `/ goldenboy` | `4` | `21619-22308` | `water.LG` | 823.8 | `[59]` | `[59, 276]` | `[59]` | `['32768:WATER_PATH']` | `[1]` | `['none']` | 0.0% | 0.161 | 20.4 | 0.0% | 0.29 | `water_path_without_obstruction` |
| `/ goldenboy` | `5` | `18813-19523` | `water.LG` | 823.8 | `[59, 278]` | `[37, 276, 278]` | `[59]` | `['0:none', '32768:WATER_PATH']` | `[0, 1]` | `['none']` | 0.0% | -0.056 | -21.9 | 0.0% | 0.642 | `water_path_without_obstruction` |

## Map Edge Evidence

| Player | Rank | Touch-to-linked edges from `.bot` map |
|---|---:|---|
| `/ bro` | `1` | `['293->283 idx=[4]', '283->53 idx=[3]', '44->131 idx=[2]', '131->10 idx=[1]', '10->131 idx=[0]', '131->44 idx=[0]']` |
| `/ bro` | `2` | `[]` |
| `/ bro` | `3` | `['160->162 idx=[0]', '162->156 idx=[0]', '158->156 idx=[0]']` |
| `/ goldenboy` | `1` | `['276->59 idx=[0]']` |
| `/ goldenboy` | `2` | `['70->71 idx=[1]', '73->71 idx=[1]', '290->73 idx=[0]', '73->70 idx=[0]', '277->73 idx=[0]']` |
| `/ goldenboy` | `3` | `['287->293 idx=[2]', '287->37 idx=[1]']` |
| `/ goldenboy` | `4` | `['59->59 missing', '276->59 idx=[0]']` |
| `/ goldenboy` | `5` | `['37->59 idx=[2]', '276->59 idx=[0]', '278->278 missing']` |

## Interpretation

- This attribution decodes sampled route and water/swim state for the current S6 window set.
- The repeated water.LG low-speed pattern decodes path_state 32768 as WATER_PATH, not STUCK_PATH.
- The repeated water-path windows have blocked=0, so obstruction recovery is not the current explanation.
- When water_state samples are present, waterlevel/swim_arrow/upmove/velocity/dir_move context can distinguish shallow-water edge handling from active swim intent.

## Next Goal

- S6f should inspect dm3.bot route-edge geometry around 276->59 / marker 59 and stop water-upmove tuning; after that narrow audit, pivot toward the headline land-speed/bunnyhop gap or broader human reference evidence.
