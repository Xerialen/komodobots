# Mode 14 v1 (orbit + carve) — first live result, trick.bsp, 2026-06-08

Built (compiles clean), deployed (`qwprogs-orbit.so`, lab port), ran, stock restored.
Two cells: orbit CCW defaults (lookahead 200, turnrate 120) and a smoother variant
(lookahead 600, turnrate 70).

## Result: it runs and orbits, but plateaus at ~350 (not 880)

| cell | speed max | speed plateau | path |
|---|---:|---:|---|
| CCW defaults | 655 | ~340 | square perimeter, bbox 2016×2016 |
| CCW smooth (la600 tr70) | 666 | ~350 | square perimeter, bbox 2016×2016 |
| human trick5 (ref) | 1088 | ~880 | interior figure-8, bbox 1749×1788 |

The bot **stays active and confined and clearly orbits** (huge improvement over a
crash/stall), but two diagnosed problems cap it — and **tuning the cvars did not move
either** (both cells gave the same square perimeter + ~350 plateau), so they are
structural, not parameter issues:

1. **Wall-following hugs the perimeter.** trick.bsp's boundary is a **square** ~2016 qu;
   the "steer away from the wall ahead" rule makes the bot run *along* the walls (the path
   traces the square's 4 edges — see `bot-mode14-v1-path.txt`). That puts it at bbox 2016
   (wider than the human's 1750) and forces **4 sharp ~90° corners per lap**, each bleeding
   speed. The human loops the *interior* smoothly with no corners.
2. **Carving around the base heading weakened the accel.** Even on the long straight edges
   the bot only reached ~340 (mode-13's carve-around-velocity hit 656). Rotating the wish-dir
   off the base heading instead of off the actual velocity loses the precise
   `velocity·wishdir ≈ K` angle QW air-accel needs, so it accelerates poorly.

## v2 fix (clear, needs a recode not a cvar)

- **Carve around VELOCITY** at `acos(K/|v|)` (restore mode-13's strong accel), but **choose
  the carve SIGN to steer velocity toward the orbit heading** — decouple accel (magnitude,
  off velocity) from steering (sign, toward the goal). This keeps the accel while still
  directing the orbit.
- **Make the direction a SMOOTH INTERIOR orbit, not a perimeter hug.** Evidence says pure
  wall-following traces the square edges with corners. Options: orbit a center at a target
  radius (seed from the human centroid (2523,−2554) r≈624, stays interior, no corners), or a
  wall-follow with a **standoff** that holds an interior radius and rounds the corners. The
  square room + the human's interior loops point to a center/standoff orbit over edge-hugging.

## Status
Mode 14 v1 proves the two-layer architecture runs and orbits on the real server. v2 (carve
around velocity + smooth interior orbit) is the path to the ~880 band. Demos:
`tricks/dm3/trick14_orbit_*__*.mvd`.
