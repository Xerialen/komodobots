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

## The wall (open problem)
Every hand-crafted confinement (hard flips, gentle centering, fixed/variable target radius) settles
into the **same ~6 s crash-limit-cycle**: builds to ~440–720, crashes to ~150–200, rebuilds. The
crash is **NOT a wall** (R at 440 is only ~84 qu) and **NOT accel** — it's a **control instability in
the confinement loop**. Median caps ~315; the human's lobe-switch loses only ~20% vs my 60–85%.
Next structural attempt: a **smooth curl-direction reversal** (ramp through straight over ~0.5 s) to
mimic the human's gentle figure-8 lobe-switch instead of the violent hard reversal.

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
