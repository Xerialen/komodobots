# Route Edge Geometry s6f-route-edge-geometry

## Scope

- Bot map: `../engine/ktx/resources/example-configs/ktx/bots/maps/dm3.bot`
- Focus edge: `276->59`
- Focus marker: `59`

## Edge

- Edge: `276->59 idx=[0] lines=[1837]`
- Reciprocal: `59->276 idx=[0] lines=[549]`
- Source marker: `id=276 zone=17 goal= origin=missing`
- Target marker: `id=59 zone=17 goal=5 origin=[1329.0, -378.0, -24.0]`
- Static geometry status: `incomplete_missing_static_origin`
- Missing static origins: `['276']`

## Attribution Summary

- Window sample rows touching focus marker/edge: `54`
- Unique samples touching focus marker/edge: `52`
- Exact focus-edge samples: `30`
- Focus-edge path states: `['WATER_PATH']`
- Waterlevels: `[0, 1, 2]`
- Blocked ratio: `0.0%`
- Low native dir-speed ratio: `86.7%`
- Dir-speed avg/min/max: `0.132` / `0.009` / `1.0`
- Emitted upmove nonzero ratio: `6.7%`

## Neighborhood

| Marker | Direction | Edge | Source origin | Target origin | Geometry |
|---:|---|---|---|---|---|
| `276` | `outgoing` | `276->59 idx=[0] lines=[1837]` | `missing` | `[1329.0, -378.0, -24.0]` | `incomplete_missing_static_origin` |
| `276` | `outgoing` | `276->37 idx=[1] lines=[1838]` | `missing` | `[-217.0, 263.0, -8.0]` | `incomplete_missing_static_origin` |
| `276` | `outgoing` | `276->280 idx=[2] lines=[1839]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `outgoing` | `276->80 idx=[3] lines=[1840]` | `missing` | `[654.0, 439.0, 56.0]` | `incomplete_missing_static_origin` |
| `276` | `outgoing` | `276->278 idx=[4] lines=[1841]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `outgoing` | `276->294 idx=[5] lines=[1842]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `outgoing` | `276->284 idx=[6] lines=[1843]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `incoming` | `59->276 idx=[0] lines=[549]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `276` | `incoming` | `273->276 idx=[5] lines=[1828]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `incoming` | `278->276 idx=[3] lines=[1854]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `incoming` | `280->276 idx=[0] lines=[1861]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `incoming` | `284->276 idx=[0] lines=[1884]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `276` | `incoming` | `294->276 idx=[1] lines=[1937]` | `missing` | `missing` | `incomplete_missing_static_origin` |
| `59` | `outgoing` | `59->276 idx=[0] lines=[549]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `59` | `outgoing` | `59->278 idx=[1] lines=[550]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `59` | `outgoing` | `59->284 idx=[2] lines=[551]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `59` | `outgoing` | `59->286 idx=[3] lines=[552]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `59` | `outgoing` | `59->273 idx=[4] lines=[553]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `59` | `outgoing` | `59->280 idx=[5] lines=[554]` | `[1329.0, -378.0, -24.0]` | `missing` | `incomplete_missing_static_origin` |
| `59` | `incoming` | `37->59 idx=[2] lines=[443]` | `[-217.0, 263.0, -8.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `38->59 idx=[6] lines=[453]` | `[-310.0, -702.0, -16.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `72->59 idx=[4] lines=[624]` | `[1447.0, -896.0, 88.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `77->59 idx=[4] lines=[644]` | `[1112.0, 624.0, 56.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `81->59 idx=[5] lines=[674]` | `[655.0, 280.0, 56.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `83->59 idx=[6] lines=[686]` | `[1354.0, 218.0, 24.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `84->59 idx=[6] lines=[694]` | `[1204.0, 488.0, 56.0]` | `[1329.0, -378.0, -24.0]` | `computed` |
| `59` | `incoming` | `273->59 idx=[4] lines=[1827]` | `missing` | `[1329.0, -378.0, -24.0]` | `incomplete_missing_static_origin` |
| `59` | `incoming` | `276->59 idx=[0] lines=[1837]` | `missing` | `[1329.0, -378.0, -24.0]` | `incomplete_missing_static_origin` |
| `59` | `incoming` | `278->59 idx=[0] lines=[1851]` | `missing` | `[1329.0, -378.0, -24.0]` | `incomplete_missing_static_origin` |
| `59` | `incoming` | `280->59 idx=[3] lines=[1864]` | `missing` | `[1329.0, -378.0, -24.0]` | `incomplete_missing_static_origin` |
| `59` | `incoming` | `284->59 idx=[3] lines=[1887]` | `missing` | `[1329.0, -378.0, -24.0]` | `incomplete_missing_static_origin` |

## Focus Samples

| Stage | Player | Rank | Time | Location | Edge | Dir speed | Waterlevel | Upmove | Blocked |
|---|---|---:|---:|---|---|---:|---|---:|---:|
| `s6d-water-path` | `/ bro` | `1` | `14807` | `water.LG` | `276->59` | 0.344 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `15063` | `water.LG` | `278->59` | 0.294 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `15322` | `water.LG` | `278->59` | 0.466 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `15578` | `water.LG` | `278->278` | 0.556 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `15844` | `water.LG` | `278->59` | 0.645 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `16104` | `water.LG` | `278->59` | 0.504 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `16360` | `water.LG` | `278->278` | 0.426 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `16626` | `water.LG` | `278->59` | 0.258 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `1` | `16876` | `water.LG` | `59->59` | 0.066 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `2` | `16876` | `water.LG` | `59->59` | 0.066 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `2` | `17132` | `water.LG` | `276->276` | 1.0 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `2` | `17388` | `water.LG` | `276->59` | 0.018 | `2` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `2` | `17647` | `water.LG` | `59->59` | 0.039 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `2` | `17903` | `water.LG` | `276->59` | 0.019 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `2` | `18169` | `water.LG` | `276->59` | 0.04 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `3` | `18169` | `water.LG` | `276->59` | 0.04 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `3` | `18429` | `water.LG` | `276->59` | 0.048 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `3` | `18685` | `water.LG` | `276->276` | 0.118 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `3` | `18941` | `water.LG` | `276->59` | 0.016 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `3` | `19201` | `water.LG` | `276->59` | 0.028 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `4` | `19713` | `water.LG` | `276->59` | 0.035 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `4` | `19972` | `water.LG` | `276->59` | 0.093 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `4` | `20228` | `water.LG` | `276->59` | 0.024 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `4` | `20494` | `water.LG` | `59->59` | 0.077 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `4` | `20754` | `water.LG` | `276->59` | 0.024 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `5` | `24868` | `water.LG` | `276->59` | 0.078 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `5` | `25118` | `water.LG` | `276->59` | 0.021 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `5` | `25373` | `water.LG` | `276->59` | 0.083 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `5` | `25629` | `water.LG` | `276->59` | 0.121 | `1` | 0.0 | no |
| `s6d-water-path` | `/ bro` | `5` | `25879` | `water.LG` | `276->59` | 0.016 | `2` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `22686` | `water.LG` | `276->59` | 1.0 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `22936` | `water.LG` | `276->59` | 1.0 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `23192` | `water.LG` | `276->59` | 0.014 | `2` | -26.8 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `23447` | `water.LG` | `276->59` | 0.026 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `23697` | `water.LG` | `276->59` | 0.009 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `23963` | `water.LG` | `276->59` | 0.073 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `24219` | `water.LG` | `276->59` | 0.097 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `24469` | `water.LG` | `276->59` | 0.038 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `24725` | `water.LG` | `276->59` | 0.127 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `24980` | `water.LG` | `276->59` | 0.044 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `1` | `25241` | `water.LG` | `276->59` | 0.011 | `2` | 214.7 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `3` | `16738` | `water.LG` | `287->293` | 1.0 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `3` | `16998` | `water.LG` | `287->37` | 0.967 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `3` | `17254` | `water.LG` | `287->37` | 0.952 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `3` | `17520` | `water.LG` | `287->37` | 0.952 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `3` | `17781` | `water.LG` | `287->37` | 0.938 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `4` | `21658` | `water.LG` | `59->59` | 1.0 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `4` | `21924` | `water.LG` | `276->59` | 0.106 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `4` | `22174` | `water.LG` | `276->59` | 0.022 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `4` | `22430` | `water.LG` | `59->59` | 0.033 | `1` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `5` | `18818` | `water.LG` | `37->59` | 0.697 | `0` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `5` | `19078` | `water.LG` | `37->59` | 0.493 | `0` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `5` | `19334` | `water.LG` | `276->59` | 0.377 | `0` | 0.0 | no |
| `s6e-water-edge-upmove` | `/ goldenboy` | `5` | `19600` | `water.LG` | `278->278` | 1.0 | `1` | 0.0 | no |

## Interpretation

- `276->59` is explicitly defined in `dm3.bot` with path indexes [0].
- The reciprocal `59->276` edge is also defined with path indexes [0].
- The focus edge has no explicit `SetMarkerPathFlags`; the observed `WATER_PATH` flag is runtime route-state classification, not a literal route-file flag on this edge.
- Static vector geometry is incomplete because marker(s) ['276'] have no `CreateMarker` origin in `dm3.bot`.
- S6d/S6e evidence contains 30 sampled `276->59` rows; low native `dir_speed < 0.25` appears in 86.7% of the focus-edge samples.
- S6f does not justify another water-upmove or command-magnitude tweak from static route data alone.

## Decision

- No tiny static route-data fix is justified by S6f: marker 276 lacks a static origin, the reciprocal edge exists, and the water-path state is runtime classification rather than an explicit edge flag.

## Next Goal

- S7a should seed player-specific movement signatures from the existing exact-player dm3 references (Milton, carapace, yeti) before any player-specific controller work; keep the headline land-speed/bunnyhop gap visible.
