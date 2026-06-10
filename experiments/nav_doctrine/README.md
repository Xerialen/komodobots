# nav_doctrine — frogbot-nav base (mode 23): movement doctrine, goal pinning, look-through carrot

One overnight execution of the approved phased plan (2026-06-09/10). The hypothesis
under test, per `docs/10_FROGBOTS_VS_NEW_BOT.md`: keep frogbot's navigation (goals →
marker graph → linked marker) and replace only the actuation.

## Findings (each measured, evidence in `evidence/`)

1. **Stairs doctrine works via delegation, not heuristics.** Mode 23 walks stairs
   grounded (~300 qu/s, top of the SE staircase in 0.9–1.1 s, ZERO jump inputs
   pre-crest) by early-returning to vanilla actuation on walkable climb legs, with a
   3 s same-marker livelock guard. Terrain-probe and jump-suppression variants all
   failed measurably first (ledger entries 22:18–22:45).
2. **Directed reach-rate doubles with the look-through carrot.** Treating pass-radius
   proximity as the marker touch (SetMarker + ProcessNewLinkedMarker — frogbot's own
   selection, not a clone) raised sng_shortcut2 reach from 4/10 to 6–8/10
   (pooled carrot configs 19/30 vs baseline 4/10); journey speed 262–292 qu/s
   (70–78 % of the human's 374 active-mean on the direct trick line).
3. **A corner-precision governor is the wrong tool at this layer.** Both velocity-
   and geometry-triggered grounding at sharp corners cut reach back to 4/10 (tested
   A/B twice); corner conversion moves to the offline sweep.
4. **The variance was physics, not path scoring.** Goal/marker selection held on
   every record of all 10 baseline runs; failures concentrate at two precision gates
   (ledge lip fall-backs; a 90° corner that converts 36 % at weave speed, 100 % at
   224–415 qu/s). See `evidence/p2-variance-decomposition.md`.
5. **Offline pmove simulator validated** (`scripts/pmove_sim.py`, mvdsv-master port):
   human .qwd replay tracks 692/692 frames within 0.20 qu, launch-edge speed 529.1
   vs 528.2 recorded; bot-log replay per-step p95 0.004 qu. En-masse parameter
   sweeps are now possible offline. See `evidence/pmove-validation-report.md`.
6. **dm3 trick-route difficulty ladder** (`evidence/trick-ladder.md`): 11 routes
   ranked from human trajectories + BSP ballistics; sng_shortcut2 easiest (437 qu/s
   required, +21.9 margin), sng_to_rl ranks 9/11 — the benchmark order is now
   evidence-based, easiest first.
7. **Prewar is unusable for directed dm3 labs**: it spawns a different item set
   (63 vs 65), shifting live marker numbering so `.bot` references ≥53 mis-resolve
   (and 298/299 → NULL, previously a 100 %-reproducible segfault — fixed KTX-side
   with NULL guards; bug verified still present in upstream QW-Group/ktx master).
   Matchless + `k_fb_moveprobe_fixed_goal` achieves the goal-quiet intent
   (goal_ed pinned on 100 % of ticks).

## Apparatus in this PR

- `scripts/route_metrics.py` — single metric source of truth (time-weighted speed
  with the stray-teleport guard inside; one canonical active-mean).
- `scripts/verify_route.py` — `--route <name>` scores any census route; default
  sng_to_rl output byte-identical (regression-checked).
- `scripts/climb_detector.py` — locked climb-segment detector (contact-height
  chaining; thresholds locked against hand-labeled traces).
- `scripts/pmove_sim.py` + `scripts/run_pmove_validation.py` — the validated
  simulator + its validation harness.
- `scripts/run_frobodm2_lab.py` — quotes multi-word `--ktx-extra-cvars` values
  (were silently truncated); presets `k_fb_enabled 1` in prewar cfgs (runtime flip
  segfaults); mode 23 in choices.

KTX-side changes (deployed on the lab server, source mirrored in claude-config):
mode-23 v8 + carrot config-5 in `bot_movement.c`, fixed-goal cvar in
`bot_botgoals.c`, NULL/bounds guards + marker dump in `marker_load.c`.

## Reproduce

Stair test: `python scripts/run_dm3.py --moveprobe-mode 23 --duration 20 --bot-count 1
--ktx-extra-cvars "k_fb_moveprobe_fixed_goal 75;k_fb_moveprobe_spawn_origin 1984 -108 -144"`
Rung test: same with `k_fb_moveprobe_fixed_goal 191;k_fb_moveprobe_spawn_origin 385.5 614.25 56`,
45 s. Judge with `scripts/climb_detector.py <run>` / `scripts/verify_route.py --route sng_shortcut2`.
Run IDs for every claim: `evidence/run-ledger.md`.
