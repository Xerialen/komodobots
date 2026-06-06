# QWD trajectory and route applicability probe

## Verdict

- Status: `partial_success`.
- Demos measured: `29`.
- Exact command/state frame matches: `29`.
- Coverage >= 98%: `29`.
- Route candidates after waypoint downsampling: `29`.
- No-discontinuity demos: `26`.

QWD can provide exact actions plus anchored self trajectory for these DM3 POV demos. The output is route/controller-ready evidence, but not yet a Frogbot .bot route or a proven replay controller.

## Method

- Decode exact outgoing commands with `tools/qwd_usercmd/qwd_usercmd.py`.
- Recover self-player `svc_playerinfo` only at QWD network-body offset `8`.
- Pair commands and states by QWD frame order and measure absolute time deltas.
- Split discontinuities instead of hiding teleport, respawn, or parser-confidence breaks.
- Downsample continuous trajectories into geometric waypoints at the configured spacing.

## Per-demo results

| demo | commands | states | paired | coverage | p50 speed | p95 speed | discontinuities | waypoints | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| dm3_bridge_to_rl.qwd | 398 | 398 | 398 | 1.000 | 380.866 | 523.531 | 0 | 25 | trajectory_route_candidate |
| dm3_bridgespawn_to_rl.qwd | 328 | 328 | 328 | 1.000 | 369.911 | 534.739 | 1 | 21 | trajectory_route_candidate |
| dm3_hilljump.qwd | 724 | 724 | 724 | 1.000 | 443.344 | 551.135 | 0 | 52 | trajectory_route_candidate |
| dm3_lifts_to_window.qwd | 240 | 240 | 240 | 1.000 | 370.618 | 767.888 | 0 | 17 | trajectory_route_candidate |
| dm3_lifts_to_window2.qwd | 234 | 234 | 234 | 1.000 | 280.005 | 744.384 | 0 | 14 | trajectory_route_candidate |
| dm3_mega_to_rl.qwd | 619 | 619 | 619 | 1.000 | 526.831 | 748.185 | 0 | 55 | trajectory_route_candidate |
| dm3_mega_to_window.qwd | 292 | 292 | 292 | 1.000 | 361.953 | 747.142 | 0 | 21 | trajectory_route_candidate |
| dm3_mound_rjumps.qwd | 1460 | 1460 | 1460 | 1.000 | 56.065 | 681.176 | 0 | 57 | trajectory_route_candidate |
| dm3_pent_advanced.qwd | 599 | 599 | 599 | 1.000 | 317.455 | 776.077 | 0 | 37 | trajectory_route_candidate |
| dm3_pent_grenade_rjump.qwd | 1401 | 1401 | 1401 | 1.000 | 28.846 | 813.726 | 0 | 56 | trajectory_route_candidate |
| dm3_quad_to_lifts.qwd | 368 | 368 | 368 | 1.000 | 481.056 | 595.066 | 0 | 26 | trajectory_route_candidate |
| dm3_ra_jumps.qwd | 1021 | 1021 | 1021 | 1.000 | 173.337 | 473.423 | 0 | 40 | trajectory_route_candidate |
| dm3_ra_rjumps.qwd | 997 | 997 | 997 | 1.000 | 205.553 | 620.844 | 0 | 44 | trajectory_route_candidate |
| dm3_ra_rjumps_hard.qwd | 460 | 460 | 460 | 1.000 | 0.0 | 624.39 | 0 | 14 | trajectory_route_candidate |
| dm3_ra_stair_to_ra.qwd | 192 | 193 | 192 | 1.000 | 170.724 | 497.793 | 0 | 10 | trajectory_route_candidate |
| dm3_ring_to_mega.qwd | 459 | 459 | 459 | 1.000 | 493.583 | 721.101 | 0 | 39 | trajectory_route_candidate |
| dm3_rjump_to_mega.qwd | 301 | 301 | 301 | 1.000 | 102.213 | 384.916 | 0 | 10 | trajectory_route_candidate |
| dm3_rjump_to_ra.qwd | 335 | 335 | 335 | 1.000 | 317.489 | 499.395 | 0 | 17 | trajectory_route_candidate |
| dm3_rl_to_bridge.qwd | 981 | 981 | 981 | 1.000 | 323.214 | 592.244 | 0 | 54 | trajectory_route_candidate |
| dm3_rl_to_ya.qwd | 400 | 400 | 400 | 1.000 | 421.379 | 872.46 | 0 | 32 | trajectory_route_candidate |
| dm3_sng_jumps.qwd | 1644 | 1644 | 1644 | 1.000 | 343.216 | 504.947 | 0 | 92 | trajectory_route_candidate |
| dm3_sng_mega_combo.qwd | 510 | 510 | 510 | 1.000 | 421.984 | 541.94 | 0 | 35 | trajectory_route_candidate |
| dm3_sng_rjumps.qwd | 1651 | 1651 | 1651 | 1.000 | 431.928 | 759.899 | 0 | 132 | trajectory_route_candidate |
| dm3_sng_shortcut.qwd | 440 | 440 | 440 | 1.000 | 465.924 | 548.283 | 0 | 33 | trajectory_route_candidate |
| dm3_sng_shortcut2.qwd | 281 | 281 | 281 | 1.000 | 326.923 | 503.767 | 0 | 16 | trajectory_route_candidate |
| dm3_sng_to_rl.qwd | 692 | 692 | 692 | 1.000 | 438.634 | 580.517 | 1 | 53 | trajectory_route_candidate |
| dm3_water_escapes.qwd | 1922 | 1922 | 1922 | 1.000 | 173.344 | 457.226 | 0 | 65 | trajectory_route_candidate |
| dm3_water_rjumps.qwd | 2753 | 2753 | 2753 | 1.000 | 38.466 | 541.457 | 0 | 65 | trajectory_route_candidate |
| dm3_water_shafting.qwd | 1047 | 1047 | 1047 | 1.000 | 0.0 | 322.967 | 1 | 14 | trajectory_route_candidate |

## Interpretation

This works as a measurement bridge: POV QWDs can provide exact human action labels and a plausible self trajectory on the same frames. The result can seed route and controller probes.

This does not yet mean a Frogbot can replay the movement. Applying it to Frogbots still needs semantic route mapping, controller execution under server physics, and stop conditions that reject route or combat regressions.

