# QWD to Frogbot route mapping

## Verdict

- Recommended next probe: `hybrid_waypoint_controller_probe`.
- Confidence: `medium`.
- Reason: The human route is spatially close to Frogbot markers, but consecutive human waypoints usually require multi-edge graph paths rather than direct `.bot` edges. The QWD action labels are side-move dominant, so the controller probe should preserve local command imitation rather than reducing the move to a simple forward waypoint chase.

## Evidence

- Demo: `dm3_sng_shortcut.qwd`.
- Command/state coverage: `1.0`.
- QWD waypoints: `33`.
- Collapsed nearest-marker sequence: `14` markers.
- Nearest-marker p50/p95/max: `70.112` / `120.324` / `142.597` qu.
- Waypoints within 128 qu of a static marker: `0.939`.
- Direct Frogbot edge ratio across collapsed transitions: `0.0`.
- Graph reachable ratio: `1.0`.
- Shortest-path edge p50/p95/max: `5.0` / `15.8` / `17.0`.
- QWD command profile: nonzero forward `0.089`, nonzero side `0.718`, jump `0.284`.

## Marker Sequence

| # | marker | nearest distance | frame span | waypoint count |
| ---: | ---: | ---: | --- | ---: |
| 1 | 157 | 99.853 | 0..0 | 1 |
| 2 | 28 | 86.379 | 16..30 | 2 |
| 3 | 158 | 46.2 | 41..65 | 3 |
| 4 | 159 | 129.086 | 77..100 | 3 |
| 5 | 29 | 43.624 | 111..122 | 2 |
| 6 | 53 | 85.732 | 132..154 | 3 |
| 7 | 51 | 82.499 | 165..186 | 3 |
| 8 | 155 | 75.401 | 196..216 | 3 |
| 9 | 149 | 85.087 | 226..246 | 3 |
| 10 | 143 | 61.493 | 256..256 | 1 |
| 11 | 145 | 71.067 | 266..276 | 2 |
| 12 | 153 | 114.482 | 285..295 | 2 |
| 13 | 32 | 105.222 | 305..328 | 3 |
| 14 | 126 | 53.23 | 347..374 | 2 |

## Transition Check

| source | target | direct edge | shortest path edges |
| ---: | ---: | --- | ---: |
| 157 | 28 | `False` | 5 |
| 28 | 158 | `False` | 5 |
| 158 | 159 | `False` | 3 |
| 159 | 29 | `False` | 3 |
| 29 | 53 | `False` | 7 |
| 53 | 51 | `False` | 17 |
| 51 | 155 | `False` | 7 |
| 155 | 149 | `False` | 8 |
| 149 | 143 | `False` | 2 |
| 143 | 145 | `False` | 3 |
| 145 | 153 | `False` | 3 |
| 153 | 32 | `False` | 14 |
| 32 | 126 | `False` | 15 |

## Stop Conditions

- Do not claim success from reaching waypoints if movement buckets regress against S7/S7k baselines.
- Do not mutate dm3.bot route data until a controller/waypoint probe shows the human route is executable under KTX physics.
- Preserve route, water, probe-activation, command, and cadence diagnostics in any follow-up run.

