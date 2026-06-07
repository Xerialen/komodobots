# QWD to Frogbot route mapping

## Verdict

- Recommended next probe: `hybrid_waypoint_controller_probe`.
- Confidence: `medium_low`.
- Reason: The marker cloud is close enough for spatial context, but the existing `.bot` topology does not match the human shortcut well enough for pure route following. The QWD action labels are side-move dominant, so the controller probe should preserve local command imitation rather than reducing the move to a simple forward waypoint chase.

## Evidence

- Demo: `dm3_sng_to_rl.qwd`.
- Command/state coverage: `1.0`.
- QWD waypoints: `53`.
- Collapsed nearest-marker sequence: `22` markers.
- Nearest-marker p50/p95/max: `68.25` / `184.518` / `218.489` qu.
- Waypoints within 128 qu of a static marker: `0.792`.
- Direct Frogbot edge ratio across collapsed transitions: `0.143`.
- Graph reachable ratio: `1.0`.
- Shortest-path edge p50/p95/max: `6.0` / `19.0` / `20.0`.
- QWD command profile: nonzero forward `0.275`, nonzero side `0.736`, jump `0.204`.

## Marker Sequence

| # | marker | nearest distance | frame span | waypoint count |
| ---: | ---: | ---: | --- | ---: |
| 1 | 121 | 36.355 | 0..29 | 2 |
| 2 | 117 | 150.346 | 43..87 | 4 |
| 3 | 118 | 49.351 | 102..127 | 3 |
| 4 | 157 | 184.158 | 128..128 | 1 |
| 5 | 28 | 125.379 | 144..174 | 3 |
| 6 | 231 | 38.913 | 186..209 | 3 |
| 7 | 230 | 58.784 | 221..244 | 3 |
| 8 | 75 | 50.994 | 255..267 | 2 |
| 9 | 76 | 28.678 | 279..290 | 2 |
| 10 | 69 | 48.033 | 302..313 | 2 |
| 11 | 70 | 52.219 | 323..355 | 4 |
| 12 | 71 | 185.059 | 366..366 | 1 |
| 13 | 13 | 133.461 | 376..393 | 3 |
| 14 | 60 | 73.551 | 403..403 | 1 |
| 15 | 61 | 46.553 | 413..423 | 2 |
| 16 | 59 | 66.869 | 433..453 | 3 |
| 17 | 19 | 68.25 | 463..473 | 2 |
| 18 | 7 | 79.326 | 483..503 | 3 |
| 19 | 45 | 136.259 | 512..522 | 2 |
| 20 | 83 | 192.572 | 532..542 | 2 |
| 21 | 226 | 163.651 | 551..570 | 3 |
| 22 | 4 | 99.259 | 582..610 | 2 |

## Transition Check

| source | target | direct edge | shortest path edges |
| ---: | ---: | --- | ---: |
| 121 | 117 | `False` | 9 |
| 117 | 118 | `False` | 3 |
| 118 | 157 | `False` | 5 |
| 157 | 28 | `False` | 5 |
| 28 | 231 | `False` | 14 |
| 231 | 230 | `True` | 1 |
| 230 | 75 | `False` | 19 |
| 75 | 76 | `True` | 1 |
| 76 | 69 | `False` | 5 |
| 69 | 70 | `False` | 3 |
| 70 | 71 | `True` | 1 |
| 71 | 13 | `False` | 20 |
| 13 | 60 | `False` | 17 |
| 60 | 61 | `False` | 6 |
| 61 | 59 | `False` | 3 |
| 59 | 19 | `False` | 19 |
| 19 | 7 | `False` | 18 |
| 7 | 45 | `False` | 15 |
| 45 | 83 | `False` | 8 |
| 83 | 226 | `False` | 18 |
| 226 | 4 | `False` | 4 |

## Stop Conditions

- Do not claim success from reaching waypoints if movement buckets regress against S7/S7k baselines.
- Do not mutate dm3.bot route data until a controller/waypoint probe shows the human route is executable under KTX physics.
- Preserve route, water, probe-activation, command, and cadence diagnostics in any follow-up run.

