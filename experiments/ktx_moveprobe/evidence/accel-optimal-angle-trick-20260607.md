# Velocity-aware accelerator: physics-optimal strafe angle (trick.bsp, 2026-06-07)

Follow-up to `bunnyhop-accel-trick-20260607.md`. That run fixed the jump toggle but
left the bot ~7x under the human (max 476, p50 75). This pass fixes the **air-strafe
angle** and unblocks **long single-bot lab runs**, isolating the true ceiling.

Human benchmark (`trick5` POV demo on trick.bsp): **median 880, peak 1088 qu/s.**

## The controller fix (KTX moveprobe mode 13)

The original air-strafe used `rotation = acos((K/speed)^2)` (K=numerator). For any real
speed this parks the wish-angle at ~89.96 deg, where `velocity . wishdir ~= 0`. QW air
accel adds the (capped) increment along wishdir, and the gain in |v| is
`~= accelspeed * (velocity . wishdir) / speed` -- so a ~90 deg angle adds speed almost
purely perpendicular and barely grows |v|. That is why it crawled to 476.

Corrected to the **speed-optimal angle** `rotation = acos(K / speed)` with K = target
`velocity . wishdir` held just under the ~30 qu/s air cap (K ~= 26 = 30 - accelspeed).
This maximises |v| gain every frame and rises toward 90 deg as speed grows, which is
correct (faster -> the velocity may turn less while keeping headroom under the cap).

Also added (cvar-parametric, no rebuild to retune):
- `k_fb_moveprobe_accel_angle` -- fixed-angle override (experiments; a fixed angle
  stalls at the speed where `speed*cos(angle)=30`, so it cannot reach the top end).
- `k_fb_moveprobe_accel_alternate` -- flip strafe side each hop (S-strafe vs circle).

## Verified: the bot really mouses for strafe

Emitted view-yaw vs velocity direction during acceleration (circle, K=26):

| t (s) | view yaw | vel dir | offset | speed |
|---|---|---|---|---|
| 18.2 | 275 | 190 | +85 | 295 |
| 18.6 | 294 | 209 | +85 | 305 |
| 19.0 | 317 | 232 | +85 | 316 |
| 19.4 | 341 | 255 | +85 | 327 |

The view-yaw sweeps continuously (~6 deg/frame) and is held ~85 deg ahead of velocity --
textbook air-strafe. Ground-contact frames drop the offset to 0 (run straight), by design.

## Results (single bot, trick.bsp, prewar, patched lab server)

| arm | active | p50 | p95 | max | note |
|---|---|---|---|---|---|
| old squared formula | 30s | 75 | - | 476 | ~90 deg wish-angle, near-zero |v| gain |
| **linear-optimal K=26** | 30s | 285 | 488 | 539 | clean accel, still climbing at cutoff |
| **linear-optimal K=26** | 60s | 535 | 574 | 656 | 96% airborne, 1% landing loss |
| linear-optimal K=26 | 203s | 268 | 516 | 604 | circle; oscillates 54<->604 |
| alternate S-strafe | 153s | 263 | 362 | 412 | straighter but lower top end |

## The real ceiling is map geometry, not acceleration

With the 60s lab cap removed (see below) the circle run shows the bot accelerating
**smoothly at the exact optimal rate** (+3 qu/s per 0.1s frame) up to ~360-600, then a
**single-frame -324 qu/s drop** (a wall hit), then re-accelerating -- repeating every ~8s.
The drops are instantaneous (not gradual desync), and there are no fly-off/falls
(vz never below -290). So:

- **Acceleration is solved and physics-optimal.** The bot mouses correctly and gains
  speed at the theoretical max rate.
- **The ~600 ceiling is trick.bsp geometry.** A map-blind circle's radius grows as v^2
  and quickly exceeds the open area, so it slams into walls before reaching the top end.
- **Reaching the human 880/1088 needs navigation** (strafe the open runway, turn at the
  ends) -- the routes/objectives pillar, not acceleration tuning.

## Lab apparatus unblocked (so the ceiling could be seen at all)

Single-bot runs were hard-capped at 60s by a chain of server-side behaviours, each
diagnosed and worked around:
- matchless FFA aborts a lone-bot match at 60s -> `--prewar` (k_matchless 0, no match).
- KTX auto-fills bots over a long match -> re-assert `k_fb_autoadd_limit 0` post-map.
- **mvdsv drops the headless client shim at a hardcoded 60s login timeout**
  (`SV_LoginCheckTimeOut`), and the server stops simulating the bot when it leaves.
  No cvar disables it. Fix: a **lab-only** `mvdsv-lab` binary that gates the login
  timeout on `sv_login` (so it does not fire when login is disabled). Production
  `mvdsv` is untouched; the harness selects the binary via `--lab-mvdsv`.
- Added `--timelimit` (raise the clamp-limited match length for completeness).

With `--prewar --lab-mvdsv mvdsv-lab` a single bot now runs 200s+, recorded via the
moveprobe console velocity log (independent of the 60s MVD).

## Status / next

Acceleration: **done** (optimal + verified). Absolute speed on trick.bsp: **~600,
geometry-capped**. Next is map-aware navigation to use the open runway -- a separate
(routes) effort, not more strafe tuning.
