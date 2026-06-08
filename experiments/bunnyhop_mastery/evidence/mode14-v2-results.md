# Mode 14 v2 (carve-around-velocity + standoff) — live, trick.bsp, 2026-06-08

v2 rebuild after v1's perimeter-hug/weak-accel diagnosis. Changes: (1) carve around the
actual **velocity** at `acos(K/|v|)` (full mode-13 accel) with the carve **sign chosen to
steer velocity toward the base heading** (S-strafe when on the orbit, lock toward it when the
heading error exceeds a 20° deadband); (2) direction = **standoff** wall-follow (a side
traceline holds a target gap to the outward wall; a forward traceline rounds corners).

## Results

| cell | turnrate | sustained hspeed | peak | path |
|---|---:|---:|---:|---|
| v2 CCW so300 | 120 | ~300 | 656 | full 2016 box, chaotic |
| **v2 gentle so450** | **35** | **~400–440** | 469 | full 2016 box, smoother |
| (v1 for ref) | 120 | ~350 | 666 | square perimeter |
| human trick5 | — | ~880 | 1088 | interior figure-8, bbox 1750 |

## Findings

- **The carve is correct.** View yaw is held ~85° ahead of velocity (textbook air-strafe);
  the accel mechanism works.
- **Direction SMOOTHNESS is the lever.** At turnrate 120 the base heading jerks around in the
  small square room → carve sign flips chaotically → velocity wanders → speed stuck ~300.
  Dropping turnrate to 35 (smooth, slow steering) lifted sustained speed to ~400–440 — a clear,
  monotonic response. The human's net heading changes slowly (~5–10°/s); the controller must too.
- **Still short of 880 and still reaches the walls.** The standoff did not keep it tightly
  interior (bbox still ~2016), and ~440 is about half the human band.

## Next iteration (clear)

The reactive wall-follow is inherently jerky in a small square room even when gentled. The
evidence now favours a **smooth-by-construction direction reference**: orbit a **center point**
at a target radius (the human centroid (2523,−2554), r≈624) — its tangent rotates slowly and
smoothly, no per-frame ray reactivity — combined with v2's working carve-around-velocity. That
is the deprioritised "orbit a center" option; v1/v2 are the evidence that pure wall-following is
too jerky for the speed build. (If wall-follow is kept, it needs heavy low-pass filtering of the
base heading.) Replay already proved 880 is reachable on this map; the generative gap is a
smooth slow direction signal.

Demos: `tricks/dm3/trick14v2_*__*.mvd`.
