# Bunnyhop tuning — session state, best config, and reproduction (2026-06-08)

Consolidated so the current peak is reproducible and reusable. Accel is solved and physics-optimal;
the open problem is a STABLE high-speed confinement (see "the wall").

## Headline results (trick.bsp, single bot, mode = moveprobe)

| controller | sustained median | peak | confined? | note |
|---|---:|---:|---:|---|
| mode 13 (one-way carve, no confinement) | — | 656 | NO (spirals to wall) | proven accel |
| mode 15 (open-loop constant-side circle-strafe) | ~150 | 657 | NO | wrong model, retired |
| mode 16 v1 (carve + hard center-flip) | ~290 | 594 | YES (box≈human) | flips crash the median |
| **mode 16 v3 (carve + gentle centered orbit + bootstrap gate)** | **~315 steady (502 transient)** | **726** | **YES** | best so far |
| human trick5 (reference) | 880 | 1088 | YES | the target |

**Current best config (mode 16 v3):** all are runtime cvars (no rebuild to retune).

```
set k_fb_moveprobe_mode 16
set k_fb_moveprobe_accel_numerator 18        // carve angle = acos(K/v); real optimum K=15
set k_fb_moveprobe_curl_radius_gain 0.12     // centering strength (0.04 weak, >0.18 overcorrects->crash)
set k_fb_moveprobe_curl_radius_div 2310      // natural curl radius R = v^2/div
set k_fb_moveprobe_curl_radius_min 120
set k_fb_moveprobe_curl_radius_max 560
set k_fb_moveprobe_curl_angle_span 25        // max deg the centering may shift the carve
set k_fb_moveprobe_curl_engage_speed 420     // pure accel below this, center above (bootstrap gate)
```
Server build: `~/nquakesv/qwprogs-curl.so` (mode-16 v3). Patch: `experiments/ktx_moveprobe/frogbot-moveprobe.patch`.

## The confirmed physics (authoritative, from mvdsv/src/pmove.c)
- Air-accel has the **30-cap**: per airborne frame velocity gains `(30 - v·wishdir)` along wishdir,
  only while `v·wishdir < 30`. Optimal speed-gain angle = **`acos(15/v)` ≈ 88°** (near-perpendicular).
- **No server speed cap** (`bunnyspeedcap` off; `sv_maxspeed 320` is only the wishspeed clamp).
- Ground frames use full accel + friction → bunnyhop jumps every ground frame.
See `PHYSICS-confirmed-air-accel.md` and `STEP0-circle-strafe-overturns-ceiling.md`.

## The wall (open problem) — hand-crafted control EXHAUSTED

Every hand-crafted confinement settles into the **same intrinsic ~6 s crash-limit-cycle**: builds
to ~440–726, crashes to ~150–200, rebuilds. The crash is **NOT a wall** (R at 440 is only ~84 qu)
and **NOT accel** — it's a **control instability in the confinement loop**. Verified steady-state
medians (clean 80 s runs), all ~the same:

| confinement variant | mode | verified steady median | peak | note |
|---|---|---:|---:|---|
| hard center-flip | 16 v1 | ~290 | 594 | flips crash median |
| P-centering (radius error) | 16 v3 | ~315–327 | 726 | crash-cycle |
| **PD-centering (+ radial-velocity damping)** | 16 + damp | **~327** | 711 | damping did NOT remove the cycle |
| smooth figure-8 lobe-switch (ramp through 0) | 17 | ~200 | 357 | too much low-carve transition |

Conclusion: hand-crafted closed-loop control that **simultaneously** accelerates, stays confined,
and stays stable is the unsolved piece — P, PD, hard-flip and smooth-flip all plateau at median
~325 / peak ~700. The human achieves 880 median via learned fine motor control; an **open-loop
replay of the human commands already sustains ~880 through the bot seam**. So the path past this
ceiling is the **imitation / replay-derived** route (learn a state->command policy from the demo
frames, or track the replay closed-loop), NOT more hand-tuned controllers.

**Verified maximum (this approach):** confined, accelerating, median ~325 / peak ~726 on trick.bsp
— up from the old (wrong) ~540 "ceiling" being a myth, and a fully working live-tuning rig to
continue from.

## Reproduce the live tuning rig
1. Build KTX with the patch; stage as `~/nquakesv/qwprogs-curl.so`; symlink
   `~/nquakesv/ktx/qwprogs.so -> qwprogs-curl.so`.
2. Launch a long session (mvdsv-lab survives the 60 s login timeout; QTV + per-frame telemetry on):
   ```
   python scripts/run_frobodm2_lab.py --map trick --moveprobe-mode 16 --bot-count 1 --prewar \
     --lab-mvdsv mvdsv-lab --duration 1800 --timelimit 32 \
     --moveprobe-log-commands --moveprobe-log-interval 0.3 --record-trick-name tuneN
   ```
3. **Watch live:** ezQuake `/qtvplay 192.168.86.33:28599`.
4. **Live cvar tweak:** `screen -S <komodobots_lab_trick_28599_*> -p 0 -X stuff $'\025set <cvar> <val>\r'`
5. **Respawn the bot** (unstick, no restart): stuff `kill`.
6. **Telemetry:** tail `~/komodobots-lab/runs/<runid>/screen.log` for `FBMOVEPROBE_CMD`; horizontal
   speed = `hypot(velocity[0],velocity[1])` from the `water=...,vx,vy,vz,...` field.
7. **Autonomous sweep:** `~/komodobots-lab/tune_driver.py <session> <screenlog> <cvar> <v1,..> <dwell> <measure> <out.json>`.

## Restore
Server back to stock: `ln -sf ~/nquakesv/ktx/qwprogs-1.48-dev-08807d.so ~/nquakesv/ktx/qwprogs.so`.
